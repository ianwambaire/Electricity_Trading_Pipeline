"""Health monitoring for prospectively collected forecast vintages.

The monitor is intentionally read-only with respect to vintage datasets.  It
summarises freshness, target coverage, duplicate identities, revisions, S3
sync state, and recent collection failures without participating in forecast
generation.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from ingestion.fetch_entsoe_forecasts import (
    ENTSOE_FORECAST_COLUMNS,
    ENTSOE_VINTAGE_IDENTITY,
    LEGACY_ENTSOE_FORECAST_COLUMNS,
    normalize_entsoe_vintages,
)
from ingestion.fetch_operational_weather_forecasts import (
    LEGACY_WEATHER_FORECAST_COLUMNS,
    WEATHER_FORECAST_COLUMNS,
    WEATHER_VINTAGE_IDENTITY,
)


EXPECTED_SCHEDULE_MINUTES = 60
HEALTHY_MAX_AGE_MINUTES = 90
STALE_AFTER_MINUTES = 180
MAX_REPORTED_MISSING_INTERVALS = 24

STATUS_HEALTHY = "HEALTHY"
STATUS_DEGRADED = "DEGRADED"
STATUS_STALE = "STALE"
STATUS_FAILED = "FAILED"

DEFAULT_REPORT_PATH = Path("data/reports/monitoring/forecast_vintage_health.json")
DEFAULT_ENTSOE_LOAD_PATH = Path(
    "data/raw/entsoe/forecasts/load_forecast_vintages.csv"
)
DEFAULT_ENTSOE_WIND_SOLAR_PATH = Path(
    "data/raw/entsoe/forecasts/wind_solar_forecast_vintages.csv"
)
DEFAULT_ENTSOE_GENERATION_PATH = Path(
    "data/raw/entsoe/forecasts/generation_forecast_vintages.csv"
)
DEFAULT_OPEN_METEO_PATH = Path(
    "data/raw/weather/open_meteo_forecast_vintages.csv"
)


@dataclass(frozen=True)
class SourceSpec:
    source: str
    provider: str
    path: Path
    document_type: str | None = None
    process_type: str | None = None
    collection_result_source: str | None = None


DEFAULT_SOURCE_SPECS = (
    SourceSpec(
        source="ENTSOE_TOTAL_LOAD",
        provider="ENTSOE",
        path=DEFAULT_ENTSOE_LOAD_PATH,
        document_type="A65",
        process_type="A01",
        collection_result_source="ENTSOE_TOTAL_LOAD",
    ),
    SourceSpec(
        source="ENTSOE_WIND_SOLAR_DAY_AHEAD",
        provider="ENTSOE",
        path=DEFAULT_ENTSOE_WIND_SOLAR_PATH,
        document_type="A69",
        process_type="A01",
        collection_result_source="ENTSOE_WIND_SOLAR",
    ),
    SourceSpec(
        source="ENTSOE_WIND_SOLAR_INTRADAY",
        provider="ENTSOE",
        path=DEFAULT_ENTSOE_WIND_SOLAR_PATH,
        document_type="A69",
        process_type="A40",
        collection_result_source="ENTSOE_WIND_SOLAR",
    ),
    SourceSpec(
        source="ENTSOE_TOTAL_GENERATION",
        provider="ENTSOE",
        path=DEFAULT_ENTSOE_GENERATION_PATH,
        document_type="A71",
        process_type="A01",
        collection_result_source="ENTSOE_TOTAL_GENERATION",
    ),
    SourceSpec(
        source="OPEN_METEO",
        provider="OPEN_METEO",
        path=DEFAULT_OPEN_METEO_PATH,
        collection_result_source="OPEN_METEO",
    ),
)


def _utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _iso(timestamp: Any) -> str | None:
    if timestamp is None or pd.isna(timestamp):
        return None
    return _utc_timestamp(timestamp).isoformat()


def _safe_relative_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def _atomic_write_json(payload: Mapping[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _collection_sources(collection_result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(collection_result, Mapping):
        return []
    sources = collection_result.get("sources", [])
    return [dict(item) for item in sources if isinstance(item, Mapping)]


def _matching_collection_events(
    spec: SourceSpec,
    collection_result: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    expected = spec.collection_result_source
    matches: list[dict[str, Any]] = []
    for item in _collection_sources(collection_result):
        source = str(item.get("source", ""))
        if source == expected or (spec.provider == "ENTSOE" and source == "ENTSOE"):
            matches.append(item)
    return matches


def _current_s3_status(
    spec: SourceSpec,
    collection_result: Mapping[str, Any] | None,
) -> str:
    matches = _matching_collection_events(spec, collection_result)
    values = [str(item.get("s3_sync_status", "UNKNOWN")).upper() for item in matches]
    if not values:
        return "UNKNOWN"
    if any(value == "FAILED" for value in values):
        return "FAILED"
    if all(value == "SUCCESS" for value in values):
        return "SUCCESS"
    if all(value in {"NOT_REQUIRED", "DISABLED"} for value in values):
        return "NOT_REQUIRED"
    return values[-1]


def _latest_successful_event(
    spec: SourceSpec,
    collection_result: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    matches = _matching_collection_events(spec, collection_result)
    successful = [
        item for item in matches if str(item.get("status", "")).upper() == "SUCCESS"
    ]
    return successful[-1] if successful else None


def _event_acquisition_and_rows(
    spec: SourceSpec,
    event: Mapping[str, Any] | None,
) -> tuple[Any | None, int | None]:
    if event is None:
        return None, None
    endpoint_by_process = {
        ("A65", "A01"): "load",
        ("A69", "A01"): "wind_solar_day_ahead",
        ("A69", "A40"): "wind_solar_intraday",
        ("A71", "A01"): "generation",
    }
    endpoint = endpoint_by_process.get((spec.document_type, spec.process_type))
    acquisitions = event.get("endpoint_acquired_at_utc")
    endpoint_rows = event.get("endpoint_rows")
    acquired = (
        acquisitions.get(endpoint)
        if endpoint and isinstance(acquisitions, Mapping)
        else event.get("acquisition_timestamp")
    )
    rows = (
        endpoint_rows.get(endpoint)
        if endpoint and isinstance(endpoint_rows, Mapping)
        else event.get("rows_acquired")
    )
    return acquired, int(rows) if rows is not None else None


def _event_failed(events: Sequence[Mapping[str, Any]]) -> bool | None:
    if not events:
        return None
    return any(str(item.get("status", "")).upper() == "FAILED" for item in events)


def _parse_pipeline_message(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def consecutive_collection_failures(
    spec: SourceSpec,
    *,
    database_path: Path | None = None,
    current_collection_result: Mapping[str, Any] | None = None,
    history_limit: int = 100,
) -> int | None:
    """Return consecutive source failures, or ``None`` when metadata is absent."""

    results: list[Mapping[str, Any]] = []
    if current_collection_result is not None:
        results.append(current_collection_result)

    if database_path is not None and database_path.exists():
        try:
            connection = sqlite3.connect(
                f"file:{database_path.resolve()}?mode=ro",
                uri=True,
            )
            try:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_runs'"
                ).fetchone()
                if exists:
                    rows = connection.execute(
                        "SELECT message FROM pipeline_runs ORDER BY run_time DESC, id DESC LIMIT ?",
                        (history_limit,),
                    ).fetchall()
                    for (message,) in rows:
                        payload = _parse_pipeline_message(message)
                        if payload is not None:
                            vintage = payload.get("forecast_vintage_collection")
                            if isinstance(vintage, Mapping):
                                results.append(vintage)
            finally:
                connection.close()
        except sqlite3.Error:
            pass

    failures = 0
    saw_metadata = False
    for result in results:
        events = _matching_collection_events(spec, result)
        outcome = _event_failed(events)
        if outcome is None:
            continue
        saw_metadata = True
        if outcome:
            failures += 1
            continue
        break
    return failures if saw_metadata else None


def _migrate_entsoe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    columns = tuple(frame.columns)
    if columns == ENTSOE_FORECAST_COLUMNS:
        return frame.copy()
    if columns == LEGACY_ENTSOE_FORECAST_COLUMNS:
        migrated = frame.rename(columns={"horizon_minutes": "source_horizon_minutes"})
        migrated.insert(
            ENTSOE_FORECAST_COLUMNS.index("collection_issue_time"),
            "collection_issue_time",
            pd.NaT,
        )
        return migrated.loc[:, ENTSOE_FORECAST_COLUMNS]
    raise ValueError("Unexpected ENTSO-E forecast-vintage schema")


def _migrate_weather_frame(frame: pd.DataFrame) -> pd.DataFrame:
    columns = tuple(frame.columns)
    if columns == WEATHER_FORECAST_COLUMNS:
        return frame.copy()
    if columns == LEGACY_WEATHER_FORECAST_COLUMNS:
        migrated = frame.rename(columns={"forecast_issue_time": "collection_issue_time"})
        return migrated.loc[:, WEATHER_FORECAST_COLUMNS]
    raise ValueError("Unexpected Open-Meteo forecast-vintage schema")


def _duplicate_count(frame: pd.DataFrame, identity: Sequence[str]) -> int:
    return int(frame.duplicated(subset=list(identity), keep="first").sum())


def _timing_status(
    latest_acquired: pd.Timestamp,
    now: pd.Timestamp,
    reasons: list[str],
) -> tuple[str, float]:
    age_minutes = max(0.0, (now - latest_acquired).total_seconds() / 60.0)
    if age_minutes > STALE_AFTER_MINUTES:
        reasons.append(
            f"Latest acquisition is {age_minutes:.1f} minutes old; "
            f"stale threshold is {STALE_AFTER_MINUTES} minutes."
        )
        return STATUS_STALE, age_minutes
    if age_minutes > HEALTHY_MAX_AGE_MINUTES:
        reasons.append(
            f"Latest acquisition is {age_minutes:.1f} minutes old; "
            f"healthy threshold is {HEALTHY_MAX_AGE_MINUTES} minutes."
        )
        return STATUS_DEGRADED, age_minutes
    return STATUS_HEALTHY, age_minutes


def _resolution_delta(value: Any) -> pd.Timedelta:
    try:
        delta = pd.Timedelta(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Unsupported source resolution {value!r}") from exc
    if delta <= pd.Timedelta(0):
        raise ValueError(f"Source resolution must be positive, got {value!r}")
    return delta


def _entsoe_coverage(frame: pd.DataFrame) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    expected_count = 0
    observed_count = 0
    group_columns = ["document_id", "revision_number", "technology", "resolution"]
    for keys, group in frame.groupby(group_columns, dropna=False, sort=False):
        document_id, revision_number, technology, resolution = keys
        targets = pd.DatetimeIndex(group["target_timestamp"].dropna().unique()).sort_values()
        if targets.empty:
            continue
        delta = _resolution_delta(resolution)
        expected = pd.date_range(targets[0], targets[-1], freq=delta, tz="UTC")
        absent = expected.difference(targets)
        expected_count += len(expected)
        observed_count += len(targets)
        for timestamp in absent:
            missing.append(
                {
                    "document_id": str(document_id),
                    "revision_number": str(revision_number),
                    "technology": str(technology),
                    "resolution": str(resolution),
                    "target_timestamp": timestamp.isoformat(),
                }
            )
    return {
        "expected_target_count": expected_count,
        "observed_target_count": observed_count,
        "missing_target_count": len(missing),
        "missing_target_intervals": missing[:MAX_REPORTED_MISSING_INTERVALS],
        "missing_target_intervals_truncated": len(missing) > MAX_REPORTED_MISSING_INTERVALS,
        "coverage_complete": not missing and expected_count > 0,
    }


def _open_meteo_coverage(frame: pd.DataFrame) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    expected_count = 0
    observed_count = 0
    for keys, group in frame.groupby(["provider", "model"], dropna=False, sort=False):
        provider, model = keys
        actual = set(pd.to_numeric(group["horizon_hours"], errors="coerce").dropna().astype(int))
        expected = set(range(1, 25))
        absent = sorted(expected - actual)
        expected_count += 24
        observed_count += len(expected & actual)
        for horizon in absent:
            missing.append(
                {
                    "provider": str(provider),
                    "model": str(model),
                    "horizon_hours": horizon,
                }
            )
    return {
        "expected_target_count": expected_count,
        "observed_target_count": observed_count,
        "missing_target_count": len(missing),
        "missing_target_intervals": missing[:MAX_REPORTED_MISSING_INTERVALS],
        "missing_target_intervals_truncated": len(missing) > MAX_REPORTED_MISSING_INTERVALS,
        "coverage_complete": not missing and expected_count > 0,
    }


def _failed_source_report(
    spec: SourceSpec,
    project_root: Path,
    reason: str,
    *,
    s3_sync_status: str,
    failures: int | None,
) -> dict[str, Any]:
    return {
        "source": spec.source,
        "provider": spec.provider,
        "document_type": spec.document_type,
        "process_type": spec.process_type,
        "local_path": _safe_relative_path(spec.path, project_root),
        "status": STATUS_FAILED,
        "latest_successful_collection_cycle": None,
        "coverage_collection_cycle": None,
        "latest_acquired_at_utc": None,
        "acquisition_age_minutes": None,
        "latest_source_created_at_utc": None,
        "newest_collection_rows": 0,
        "target_start_utc": None,
        "target_end_utc": None,
        "resolutions": [],
        "technologies": [],
        "expected_target_count": 0,
        "observed_target_count": 0,
        "missing_target_count": None,
        "missing_target_intervals": [],
        "missing_target_intervals_truncated": False,
        "coverage_complete": False,
        "duplicate_identity_count": 0,
        "revision_count": 0,
        "revision_numbers": [],
        "s3_sync_status": s3_sync_status,
        "consecutive_collection_failures": failures,
        "reasons": [reason],
    }


def _assess_entsoe_source(
    spec: SourceSpec,
    *,
    project_root: Path,
    now: pd.Timestamp,
    collection_result: Mapping[str, Any] | None,
    database_path: Path | None,
) -> dict[str, Any]:
    path = spec.path if spec.path.is_absolute() else project_root / spec.path
    s3_status = _current_s3_status(spec, collection_result)
    failures = consecutive_collection_failures(
        spec,
        database_path=database_path,
        current_collection_result=collection_result,
    )
    if not path.exists():
        return _failed_source_report(
            spec,
            project_root,
            "Forecast-vintage file is missing.",
            s3_sync_status=s3_status,
            failures=failures,
        )
    try:
        raw = _migrate_entsoe_frame(pd.read_csv(path))
        duplicates = _duplicate_count(raw, ENTSOE_VINTAGE_IDENTITY)
        normalized = normalize_entsoe_vintages(raw)
        subset = normalized.loc[
            (normalized["document_type"] == spec.document_type)
            & (normalized["process_type"] == spec.process_type)
        ].copy()
    except Exception as exc:
        return _failed_source_report(
            spec,
            project_root,
            f"Forecast-vintage file is unreadable or invalid: {type(exc).__name__}.",
            s3_sync_status=s3_status,
            failures=failures,
        )
    cycles = subset["collection_issue_time"].dropna()
    if subset.empty or cycles.empty:
        return _failed_source_report(
            spec,
            project_root,
            "No collection cycle is available for this endpoint.",
            s3_sync_status=s3_status,
            failures=failures,
        )
    persisted_cycle = cycles.max()
    successful_event = _latest_successful_event(spec, collection_result)
    event_cycle = (
        successful_event.get("collection_issue_time")
        if successful_event is not None
        else None
    )
    report_cycle = _utc_timestamp(event_cycle) if event_cycle else persisted_cycle
    newest = subset.loc[subset["collection_issue_time"] == report_cycle].copy()
    if newest.empty:
        # An idempotent ENTSO-E reacquisition deliberately retains the original
        # collection timestamp. Its current success still establishes freshness,
        # while coverage remains assessable from the latest persisted vintage.
        newest = subset.loc[subset["collection_issue_time"] == persisted_cycle].copy()
    event_acquired, event_rows = _event_acquisition_and_rows(spec, successful_event)
    latest_acquired = (
        _utc_timestamp(event_acquired)
        if event_acquired is not None
        else newest["acquired_at_utc"].max()
    )
    reasons: list[str] = []
    status, age_minutes = _timing_status(latest_acquired, now, reasons)
    coverage = _entsoe_coverage(newest)
    if not coverage["coverage_complete"]:
        reasons.append(
            f"{coverage['missing_target_count']} source-resolution target interval(s) are missing."
        )
    if duplicates:
        reasons.append(f"{duplicates} duplicate vintage identity row(s) detected.")
    if failures:
        reasons.append(f"{failures} consecutive collection failure(s) recorded.")
    if s3_status == "FAILED":
        reasons.append("Latest S3 synchronization failed.")
    elif s3_status == "NOT_ATTEMPTED":
        reasons.append("Latest S3 synchronization was not attempted.")
    if status == STATUS_HEALTHY and reasons:
        status = STATUS_DEGRADED

    revisions = newest[["document_id", "revision_number"]].drop_duplicates()
    return {
        "source": spec.source,
        "provider": spec.provider,
        "document_type": spec.document_type,
        "process_type": spec.process_type,
        "local_path": _safe_relative_path(path, project_root),
        "status": status,
        "latest_successful_collection_cycle": _iso(report_cycle),
        "coverage_collection_cycle": _iso(newest["collection_issue_time"].max()),
        "latest_acquired_at_utc": _iso(latest_acquired),
        "acquisition_age_minutes": round(age_minutes, 3),
        "latest_source_created_at_utc": _iso(newest["source_created_at_utc"].max()),
        "newest_collection_rows": event_rows if event_rows is not None else int(len(newest)),
        "target_start_utc": _iso(newest["target_timestamp"].min()),
        "target_end_utc": _iso(newest["target_timestamp"].max()),
        "resolutions": sorted(str(value) for value in newest["resolution"].dropna().unique()),
        "technologies": sorted(str(value) for value in newest["technology"].dropna().unique()),
        **coverage,
        "duplicate_identity_count": duplicates,
        "revision_count": int(len(revisions)),
        "revision_numbers": sorted(
            str(value) for value in newest["revision_number"].dropna().unique()
        ),
        "s3_sync_status": s3_status,
        "consecutive_collection_failures": failures,
        "reasons": reasons,
    }


def _prepare_weather_frame(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = _migrate_weather_frame(frame)
    for column in ("collection_issue_time", "acquired_at_utc", "target_timestamp"):
        prepared[column] = pd.to_datetime(prepared[column], utc=True, errors="raise")
    prepared["horizon_hours"] = pd.to_numeric(
        prepared["horizon_hours"], errors="raise"
    ).astype(int)
    numeric_columns = (
        "temperature_2m",
        "relative_humidity_2m",
        "wind_speed_10m",
        "cloud_cover",
        "shortwave_radiation",
    )
    for column in numeric_columns:
        prepared[column] = pd.to_numeric(prepared[column], errors="raise")
        if not prepared[column].map(math.isfinite).all():
            raise ValueError(f"Non-finite Open-Meteo values in {column}")
    if (prepared["horizon_hours"] < 0).any():
        raise ValueError("Open-Meteo horizons must be non-negative")
    return prepared


def _assess_open_meteo_source(
    spec: SourceSpec,
    *,
    project_root: Path,
    now: pd.Timestamp,
    collection_result: Mapping[str, Any] | None,
    database_path: Path | None,
) -> dict[str, Any]:
    path = spec.path if spec.path.is_absolute() else project_root / spec.path
    s3_status = _current_s3_status(spec, collection_result)
    failures = consecutive_collection_failures(
        spec,
        database_path=database_path,
        current_collection_result=collection_result,
    )
    if not path.exists():
        return _failed_source_report(
            spec,
            project_root,
            "Forecast-vintage file is missing.",
            s3_sync_status=s3_status,
            failures=failures,
        )
    try:
        raw = _prepare_weather_frame(pd.read_csv(path))
        duplicates = _duplicate_count(raw, WEATHER_VINTAGE_IDENTITY)
    except Exception as exc:
        return _failed_source_report(
            spec,
            project_root,
            f"Forecast-vintage file is unreadable or invalid: {type(exc).__name__}.",
            s3_sync_status=s3_status,
            failures=failures,
        )
    if raw.empty:
        return _failed_source_report(
            spec,
            project_root,
            "Forecast-vintage file contains no rows.",
            s3_sync_status=s3_status,
            failures=failures,
        )
    persisted_cycle = raw["collection_issue_time"].max()
    successful_event = _latest_successful_event(spec, collection_result)
    event_cycle = (
        successful_event.get("collection_issue_time")
        if successful_event is not None
        else None
    )
    latest_cycle = _utc_timestamp(event_cycle) if event_cycle else persisted_cycle
    newest = raw.loc[raw["collection_issue_time"] == latest_cycle].copy()
    if newest.empty:
        newest = raw.loc[raw["collection_issue_time"] == persisted_cycle].copy()
    event_acquired, event_rows = _event_acquisition_and_rows(spec, successful_event)
    latest_acquired = (
        _utc_timestamp(event_acquired)
        if event_acquired is not None
        else newest["acquired_at_utc"].max()
    )
    reasons: list[str] = []
    status, age_minutes = _timing_status(latest_acquired, now, reasons)
    coverage = _open_meteo_coverage(newest)
    if not coverage["coverage_complete"]:
        reasons.append(
            f"{coverage['missing_target_count']} required horizon(s) from 1 through 24 are missing."
        )
    target_mismatch = newest.loc[
        newest["target_timestamp"]
        != newest["collection_issue_time"]
        + pd.to_timedelta(newest["horizon_hours"], unit="h")
    ]
    if not target_mismatch.empty:
        reasons.append(
            f"{len(target_mismatch)} target timestamp(s) do not match their declared horizon."
        )
    if duplicates:
        reasons.append(f"{duplicates} duplicate vintage identity row(s) detected.")
    if failures:
        reasons.append(f"{failures} consecutive collection failure(s) recorded.")
    if s3_status == "FAILED":
        reasons.append("Latest S3 synchronization failed.")
    elif s3_status == "NOT_ATTEMPTED":
        reasons.append("Latest S3 synchronization was not attempted.")
    if status == STATUS_HEALTHY and reasons:
        status = STATUS_DEGRADED
    return {
        "source": spec.source,
        "provider": spec.provider,
        "document_type": None,
        "process_type": None,
        "local_path": _safe_relative_path(path, project_root),
        "status": status,
        "latest_successful_collection_cycle": _iso(latest_cycle),
        "coverage_collection_cycle": _iso(newest["collection_issue_time"].max()),
        "latest_acquired_at_utc": _iso(latest_acquired),
        "acquisition_age_minutes": round(age_minutes, 3),
        "latest_source_created_at_utc": None,
        "newest_collection_rows": event_rows if event_rows is not None else int(len(newest)),
        "target_start_utc": _iso(newest["target_timestamp"].min()),
        "target_end_utc": _iso(newest["target_timestamp"].max()),
        "resolutions": ["PT60M"],
        "technologies": [],
        **coverage,
        "duplicate_identity_count": duplicates,
        "revision_count": 0,
        "revision_numbers": [],
        "s3_sync_status": s3_status,
        "consecutive_collection_failures": failures,
        "reasons": reasons,
    }


def _overall_status(sources: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(source.get("status")) for source in sources}
    for status in (STATUS_FAILED, STATUS_STALE, STATUS_DEGRADED, STATUS_HEALTHY):
        if status in statuses:
            return status
    return STATUS_FAILED


def build_forecast_vintage_health_report(
    *,
    project_root: Path,
    now: datetime | pd.Timestamp | None = None,
    source_specs: Sequence[SourceSpec] = DEFAULT_SOURCE_SPECS,
    collection_result: Mapping[str, Any] | None = None,
    database_path: Path | None = None,
) -> dict[str, Any]:
    """Build a compact source-isolated health report without writing data."""

    now_utc = _utc_timestamp(now or datetime.now(timezone.utc))
    source_reports: list[dict[str, Any]] = []
    for spec in source_specs:
        if spec.provider == "ENTSOE":
            report = _assess_entsoe_source(
                spec,
                project_root=project_root,
                now=now_utc,
                collection_result=collection_result,
                database_path=database_path,
            )
        elif spec.provider == "OPEN_METEO":
            report = _assess_open_meteo_source(
                spec,
                project_root=project_root,
                now=now_utc,
                collection_result=collection_result,
                database_path=database_path,
            )
        else:
            report = _failed_source_report(
                spec,
                project_root,
                "Unsupported forecast-vintage provider.",
                s3_sync_status="UNKNOWN",
                failures=None,
            )
        source_reports.append(report)

    return {
        "schema_version": 1,
        "generated_at_utc": now_utc.isoformat(),
        "overall_status": _overall_status(source_reports),
        "thresholds": {
            "expected_schedule_minutes": EXPECTED_SCHEDULE_MINUTES,
            "healthy_max_age_minutes": HEALTHY_MAX_AGE_MINUTES,
            "stale_after_minutes": STALE_AFTER_MINUTES,
            "open_meteo_required_horizons": [1, 24],
            "status_rules": {
                "HEALTHY": "Fresh, complete, duplicate-free latest collection with no recorded failure or failed S3 sync.",
                "DEGRADED": "Fresh or slightly late data with missing intervals, duplicates, source failures, failed S3 sync, or another validation warning.",
                "STALE": "Latest successful acquisition is older than the stale threshold.",
                "FAILED": "The source file or a usable collection cycle is missing, unreadable, or invalid.",
            },
        },
        "sources": source_reports,
    }


def write_forecast_vintage_health_report(
    *,
    project_root: Path,
    destination: Path = DEFAULT_REPORT_PATH,
    now: datetime | pd.Timestamp | None = None,
    source_specs: Sequence[SourceSpec] = DEFAULT_SOURCE_SPECS,
    collection_result: Mapping[str, Any] | None = None,
    database_path: Path | None = None,
) -> dict[str, Any]:
    """Build and atomically persist the forecast-vintage health report."""

    report = build_forecast_vintage_health_report(
        project_root=project_root,
        now=now,
        source_specs=source_specs,
        collection_result=collection_result,
        database_path=database_path,
    )
    output_path = destination if destination.is_absolute() else project_root / destination
    _atomic_write_json(report, output_path)
    return report

