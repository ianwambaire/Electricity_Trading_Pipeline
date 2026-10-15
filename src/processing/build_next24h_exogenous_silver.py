"""Build leakage-safe offline Silver data from prospective forecast vintages.

This builder is deliberately isolated from the observed Raw -> Silver -> Gold
pipeline and from production inference.  Its as-of boundary is a logical UTC
collection-cycle hour.  A response acquired during that same hour belongs to
the cycle (for example, an 11:02 response belongs to the 11:00 cycle), but a
document assigned to a later cycle is never eligible for an earlier row.

Legacy ENTSO-E rows that predate ``collection_issue_time`` are assigned the
conservative cycle ``floor(acquired_at_utc)``.  This preserves readability
without claiming that the data was available before it was acquired.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ingestion.fetch_entsoe_forecasts import (
    GENERATION_FORECAST_PATH,
    LOAD_FORECAST_PATH,
    WIND_SOLAR_FORECAST_PATH,
    normalize_entsoe_vintages,
)
from ingestion.fetch_operational_weather_forecasts import (
    OUTPUT_PATH as WEATHER_FORECAST_PATH,
    WEATHER_VARIABLES,
    normalize_weather_forecast_vintages,
)
from models.final_evaluation import FINAL_FEATURES
from models.next24h import build_issue_features


OBSERVED_SILVER_PATH = Path("data/processed/silver_electricity_market_data.csv")
OUTPUT_PATH = Path("data/processed/silver_next24h_exogenous_vintages.csv")
QUALITY_REPORT_PATH = Path(
    "data/reports/monitoring/next24h_exogenous_silver_quality.json"
)
HORIZONS = tuple(range(1, 25))
KEY_COLUMNS = (
    "collection_issue_time",
    "target_timestamp",
    "horizon_hours",
)
TARGET_CALENDAR_FEATURES = (
    "target_hour",
    "target_day_of_week",
    "target_month",
    "target_is_weekend",
)
FORECAST_FEATURES = (
    "forecast_load_mw",
    "forecast_solar_mw",
    "forecast_wind_offshore_mw",
    "forecast_wind_onshore_mw",
    "forecast_wind_total_mw",
    "forecast_total_generation_mw",
    "forecast_temperature_2m",
    "forecast_relative_humidity_2m",
    "forecast_wind_speed_10m",
    "forecast_cloud_cover",
    "forecast_shortwave_radiation",
)
EXOGENOUS_FEATURE_COLUMNS = (
    *FINAL_FEATURES,
    *TARGET_CALENDAR_FEATURES,
    *FORECAST_FEATURES,
)


def _provenance_columns(prefix: str, *, include_process: bool = False) -> tuple[str, ...]:
    process = (f"{prefix}_process_type",) if include_process else ()
    return (
        *process,
        f"{prefix}_document_id",
        f"{prefix}_revision_number",
        f"{prefix}_source_created_at_utc",
        f"{prefix}_collection_issue_time",
        f"{prefix}_acquired_at_utc",
        f"{prefix}_resolution",
    )


LOAD_PROVENANCE_COLUMNS = _provenance_columns("load_forecast")
GENERATION_PROVENANCE_COLUMNS = _provenance_columns("generation_forecast")
SOLAR_PROVENANCE_COLUMNS = _provenance_columns(
    "solar_forecast", include_process=True
)
WIND_OFFSHORE_PROVENANCE_COLUMNS = _provenance_columns(
    "wind_offshore_forecast", include_process=True
)
WIND_ONSHORE_PROVENANCE_COLUMNS = _provenance_columns(
    "wind_onshore_forecast", include_process=True
)
WEATHER_PROVENANCE_COLUMNS = (
    "weather_forecast_collection_issue_time",
    "weather_forecast_acquired_at_utc",
    "weather_forecast_provider",
    "weather_forecast_model",
)
PROVENANCE_COLUMNS = (
    "issue_observed_timestamp",
    *LOAD_PROVENANCE_COLUMNS,
    *GENERATION_PROVENANCE_COLUMNS,
    *SOLAR_PROVENANCE_COLUMNS,
    *WIND_OFFSHORE_PROVENANCE_COLUMNS,
    *WIND_ONSHORE_PROVENANCE_COLUMNS,
    *WEATHER_PROVENANCE_COLUMNS,
)
TARGET_COLUMN = "target_price_eur_mwh"
OUTPUT_COLUMNS = (
    *KEY_COLUMNS,
    "issue_observed_timestamp",
    *FINAL_FEATURES,
    *TARGET_CALENDAR_FEATURES,
    *FORECAST_FEATURES,
    *LOAD_PROVENANCE_COLUMNS,
    *GENERATION_PROVENANCE_COLUMNS,
    *SOLAR_PROVENANCE_COLUMNS,
    *WIND_OFFSHORE_PROVENANCE_COLUMNS,
    *WIND_ONSHORE_PROVENANCE_COLUMNS,
    *WEATHER_PROVENANCE_COLUMNS,
    TARGET_COLUMN,
)

_FORECAST_VALUE_BY_TECHNOLOGY = {
    "TOTAL_LOAD": "forecast_load_mw",
    "TOTAL_GENERATION": "forecast_total_generation_mw",
    "SOLAR": "forecast_solar_mw",
    "WIND_OFFSHORE": "forecast_wind_offshore_mw",
    "WIND_ONSHORE": "forecast_wind_onshore_mw",
}
_PROVENANCE_PREFIX_BY_TECHNOLOGY = {
    "TOTAL_LOAD": "load_forecast",
    "TOTAL_GENERATION": "generation_forecast",
    "SOLAR": "solar_forecast",
    "WIND_OFFSHORE": "wind_offshore_forecast",
    "WIND_ONSHORE": "wind_onshore_forecast",
}
_MISSING_REASON_BY_TECHNOLOGY = {
    "TOTAL_LOAD": "missing_load_forecast",
    "TOTAL_GENERATION": "missing_generation_forecast",
    "SOLAR": "missing_solar_forecast",
    "WIND_OFFSHORE": "missing_wind_offshore_forecast",
    "WIND_ONSHORE": "missing_wind_onshore_forecast",
}


def _utc_series(values: pd.Series, name: str) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce", utc=True)
    if parsed.isna().any():
        raise ValueError(f"{name} contains an invalid UTC timestamp.")
    return parsed


def _read_csv(path: Path, *, revision_strings: bool = False) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Required input does not exist: {path}")
    kwargs = {"dtype": {"revision_number": "string"}} if revision_strings else {}
    return pd.read_csv(path, low_memory=False, **kwargs)


def _prepare_observed_silver(silver: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "timestamp" not in silver.columns or "price_eur_mwh" not in silver.columns:
        raise ValueError("Observed Silver requires timestamp and price_eur_mwh.")
    observed = silver.copy()
    observed["timestamp"] = _utc_series(observed["timestamp"], "Silver timestamp")
    if observed["timestamp"].duplicated().any():
        raise ValueError("Observed Silver timestamps must be unique.")
    if not observed["timestamp"].eq(observed["timestamp"].dt.floor("h")).all():
        raise ValueError("Observed Silver timestamps must be exact UTC hours.")
    observed["price_eur_mwh"] = pd.to_numeric(
        observed["price_eur_mwh"], errors="coerce"
    )
    issue_features = build_issue_features(observed)
    if issue_features["timestamp"].duplicated().any():
        raise ValueError("Issue-time feature rows must be unique.")
    return observed.sort_values("timestamp"), issue_features.set_index("timestamp")


def _prepare_entsoe_vintages(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    normalized = normalize_entsoe_vintages(frame)
    legacy = normalized["collection_issue_time"].isna()
    normalized["effective_collection_issue_time"] = normalized[
        "collection_issue_time"
    ].where(~legacy, normalized["acquired_at_utc"].dt.floor("h"))
    cycle = normalized["effective_collection_issue_time"]
    within_cycle = (
        (normalized["acquired_at_utc"] >= cycle)
        & (normalized["acquired_at_utc"] < cycle + pd.Timedelta(hours=1))
    )
    normalized = normalized.loc[within_cycle].copy()
    if normalized.empty:
        raise ValueError(
            "No ENTSO-E vintage was acquired within its declared collection cycle."
        )
    return normalized, int(legacy.sum())


def _hourly_entsoe_vintages(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Aggregate each source vintage independently to exact UTC target hours."""
    vintage_columns = [
        "source",
        "document_type",
        "process_type",
        "document_id",
        "revision_number",
        "source_created_at_utc",
        "effective_collection_issue_time",
        "acquired_at_utc",
        "market_area",
        "resolution",
        "technology",
    ]
    rows: list[dict[str, Any]] = []
    rejected = Counter()
    for keys, vintage in frame.groupby(vintage_columns, dropna=False, sort=False):
        provenance = dict(zip(vintage_columns, keys))
        resolution = str(provenance["resolution"])
        if resolution not in {"PT15M", "PT60M"}:
            rejected["unsupported_resolution"] += 1
            continue
        vintage = vintage.copy()
        vintage["target_hour"] = vintage["target_timestamp"].dt.floor("h")
        for target_hour, hour in vintage.groupby("target_hour", sort=False):
            timestamps = pd.DatetimeIndex(hour["target_timestamp"]).sort_values()
            if resolution == "PT15M":
                expected = pd.date_range(target_hour, periods=4, freq="15min")
                if (
                    len(hour) != 4
                    or timestamps.duplicated().any()
                    or not timestamps.equals(expected)
                ):
                    rejected["incomplete_pt15m_hour"] += 1
                    continue
            else:
                if (
                    len(hour) != 1
                    or timestamps[0] != target_hour
                    or timestamps.duplicated().any()
                ):
                    rejected["invalid_pt60m_hour"] += 1
                    continue
            value = pd.to_numeric(hour["value_mw"], errors="coerce")
            if value.isna().any() or not np.isfinite(value.to_numpy(dtype=float)).all():
                rejected["non_finite_value"] += 1
                continue
            rows.append(
                {
                    **provenance,
                    "target_timestamp": target_hour,
                    "value_mw": float(value.mean()),
                }
            )
    columns = [*vintage_columns, "target_timestamp", "value_mw"]
    return pd.DataFrame(rows, columns=columns), dict(sorted(rejected.items()))


def _prepare_weather_vintages(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_weather_forecast_vintages(frame)
    within_cycle = (
        (normalized["acquired_at_utc"] >= normalized["collection_issue_time"])
        & (
            normalized["acquired_at_utc"]
            < normalized["collection_issue_time"] + pd.Timedelta(hours=1)
        )
    )
    normalized = normalized.loc[within_cycle].copy()
    if normalized.empty:
        raise ValueError(
            "No Open-Meteo vintage was acquired within its collection cycle."
        )
    return normalized


def _revision_rank(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.fillna(-1)


def _select_latest_entsoe(
    hourly: pd.DataFrame,
    *,
    issue_time: pd.Timestamp,
    target_time: pd.Timestamp,
    technology: str,
    document_type: str,
    process_type: str | None = None,
) -> pd.Series | None:
    candidates = hourly.loc[
        (hourly["technology"] == technology)
        & (hourly["document_type"] == document_type)
        & (hourly["target_timestamp"] == target_time)
        & (hourly["effective_collection_issue_time"] <= issue_time)
    ].copy()
    if process_type is not None:
        candidates = candidates.loc[candidates["process_type"] == process_type]
    if candidates.empty:
        return None
    candidates["_revision_rank"] = _revision_rank(candidates["revision_number"])
    candidates = candidates.sort_values(
        [
            "effective_collection_issue_time",
            "source_created_at_utc",
            "_revision_rank",
            "acquired_at_utc",
            "document_id",
        ]
    )
    return candidates.iloc[-1]


def _select_wind_solar(
    hourly: pd.DataFrame,
    *,
    issue_time: pd.Timestamp,
    target_time: pd.Timestamp,
    technology: str,
) -> pd.Series | None:
    for process_type in ("A40", "A01"):
        selected = _select_latest_entsoe(
            hourly,
            issue_time=issue_time,
            target_time=target_time,
            technology=technology,
            document_type="A69",
            process_type=process_type,
        )
        if selected is not None:
            return selected
    return None


def _select_weather(
    weather: pd.DataFrame,
    *,
    issue_time: pd.Timestamp,
    target_time: pd.Timestamp,
) -> pd.Series | None:
    candidates = weather.loc[
        (weather["collection_issue_time"] == issue_time)
        & (weather["target_timestamp"] == target_time)
    ].copy()
    if candidates.empty:
        return None
    return candidates.sort_values(["acquired_at_utc", "model"]).iloc[-1]


def _forecast_provenance(selected: pd.Series, prefix: str) -> dict[str, Any]:
    result = {
        f"{prefix}_document_id": selected["document_id"],
        f"{prefix}_revision_number": selected["revision_number"],
        f"{prefix}_source_created_at_utc": selected["source_created_at_utc"],
        f"{prefix}_collection_issue_time": selected[
            "effective_collection_issue_time"
        ],
        f"{prefix}_acquired_at_utc": selected["acquired_at_utc"],
        f"{prefix}_resolution": selected["resolution"],
    }
    if prefix in {
        "solar_forecast",
        "wind_offshore_forecast",
        "wind_onshore_forecast",
    }:
        result[f"{prefix}_process_type"] = selected["process_type"]
    return result


def _candidate_cycles(
    entsoe_frames: Sequence[pd.DataFrame], weather: pd.DataFrame
) -> pd.DatetimeIndex:
    values: list[pd.Timestamp] = []
    for frame in entsoe_frames:
        values.extend(frame["effective_collection_issue_time"].dropna().tolist())
    values.extend(weather["collection_issue_time"].dropna().tolist())
    return pd.DatetimeIndex(values).unique().sort_values()


def _audit_output(data: pd.DataFrame) -> dict[str, Any]:
    duplicate_keys = int(data.duplicated(list(KEY_COLUMNS)).sum())
    checks: dict[str, bool] = {
        "unique_row_grain": duplicate_keys == 0,
        "target_after_issue": bool(
            data.empty
            or (data["target_timestamp"] > data["collection_issue_time"]).all()
        ),
        "horizon_derived_from_timestamps": bool(
            data.empty
            or np.allclose(
                data["horizon_hours"],
                (
                    data["target_timestamp"] - data["collection_issue_time"]
                ).dt.total_seconds()
                / 3600.0,
            )
        ),
        "horizon_in_1_to_24": bool(
            data.empty or data["horizon_hours"].isin(HORIZONS).all()
        ),
        "observed_features_not_from_future": bool(
            data.empty
            or (
                data["issue_observed_timestamp"]
                <= data["collection_issue_time"]
            ).all()
        ),
        "target_not_in_feature_contract": TARGET_COLUMN
        not in EXOGENOUS_FEATURE_COLUMNS,
        "features_are_finite": bool(
            data.empty
            or np.isfinite(
                data.loc[:, EXOGENOUS_FEATURE_COLUMNS].to_numpy(dtype=float)
            ).all()
        ),
    }
    cycle_prefixes = (
        "load_forecast",
        "generation_forecast",
        "solar_forecast",
        "wind_offshore_forecast",
        "wind_onshore_forecast",
        "weather_forecast",
    )
    for prefix in cycle_prefixes:
        cycle = data[f"{prefix}_collection_issue_time"]
        acquired = data[f"{prefix}_acquired_at_utc"]
        checks[f"{prefix}_not_from_later_cycle"] = bool(
            data.empty or (cycle <= data["collection_issue_time"]).all()
        )
        checks[f"{prefix}_acquired_within_cycle"] = bool(
            data.empty
            or ((acquired >= cycle) & (acquired < cycle + pd.Timedelta(hours=1))).all()
        )
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "duplicate_key_count": duplicate_keys,
    }


def build_next24h_exogenous_frame(
    observed_silver: pd.DataFrame,
    load_vintages: pd.DataFrame,
    wind_solar_vintages: pd.DataFrame,
    generation_vintages: pd.DataFrame,
    weather_vintages: pd.DataFrame,
    *,
    generated_at_utc: Any | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Construct strict offline rows and a leakage/data-quality audit."""
    observed, issues = _prepare_observed_silver(observed_silver)
    prices = observed.set_index("timestamp")["price_eur_mwh"]

    prepared_entsoe = []
    legacy_counts: dict[str, int] = {}
    aggregation_rejections: dict[str, dict[str, int]] = {}
    hourly_frames = []
    for name, raw in (
        ("load", load_vintages),
        ("wind_solar", wind_solar_vintages),
        ("generation", generation_vintages),
    ):
        prepared, legacy_count = _prepare_entsoe_vintages(raw)
        hourly, rejected = _hourly_entsoe_vintages(prepared)
        prepared_entsoe.append(prepared)
        hourly_frames.append(hourly)
        legacy_counts[name] = legacy_count
        aggregation_rejections[name] = rejected
    load_hourly, wind_solar_hourly, generation_hourly = hourly_frames
    weather = _prepare_weather_vintages(weather_vintages)
    cycles = _candidate_cycles(prepared_entsoe, weather)

    excluded = Counter()
    process_usage = Counter()
    rows: list[dict[str, Any]] = []
    for issue_time in cycles:
        issue_row = issues.loc[issue_time] if issue_time in issues.index else None
        for horizon in HORIZONS:
            target_time = issue_time + pd.Timedelta(hours=horizon)
            reasons: list[str] = []
            if issue_row is None:
                reasons.append("missing_issue_features")
            target_price = prices.get(target_time, np.nan)
            if pd.isna(target_price):
                reasons.append("missing_target_price")

            selections: dict[str, pd.Series | None] = {
                "TOTAL_LOAD": _select_latest_entsoe(
                    load_hourly,
                    issue_time=issue_time,
                    target_time=target_time,
                    technology="TOTAL_LOAD",
                    document_type="A65",
                    process_type="A01",
                ),
                "TOTAL_GENERATION": _select_latest_entsoe(
                    generation_hourly,
                    issue_time=issue_time,
                    target_time=target_time,
                    technology="TOTAL_GENERATION",
                    document_type="A71",
                    process_type="A01",
                ),
            }
            for technology in ("SOLAR", "WIND_OFFSHORE", "WIND_ONSHORE"):
                selections[technology] = _select_wind_solar(
                    wind_solar_hourly,
                    issue_time=issue_time,
                    target_time=target_time,
                    technology=technology,
                )
            for technology, selected in selections.items():
                if selected is None:
                    reasons.append(_MISSING_REASON_BY_TECHNOLOGY[technology])

            weather_row = _select_weather(
                weather, issue_time=issue_time, target_time=target_time
            )
            if weather_row is None:
                reasons.append("missing_weather_forecast")
            if reasons:
                excluded.update(set(reasons))
                continue

            row: dict[str, Any] = {
                "collection_issue_time": issue_time,
                "target_timestamp": target_time,
                "horizon_hours": horizon,
                "issue_observed_timestamp": issue_time,
                **{name: issue_row[name] for name in FINAL_FEATURES},
                "target_hour": target_time.hour,
                "target_day_of_week": target_time.dayofweek,
                "target_month": target_time.month,
                "target_is_weekend": int(target_time.dayofweek in (5, 6)),
                TARGET_COLUMN: float(target_price),
            }
            for technology, selected in selections.items():
                row[_FORECAST_VALUE_BY_TECHNOLOGY[technology]] = float(
                    selected["value_mw"]
                )
                prefix = _PROVENANCE_PREFIX_BY_TECHNOLOGY[technology]
                row.update(_forecast_provenance(selected, prefix))
                if technology in {"SOLAR", "WIND_OFFSHORE", "WIND_ONSHORE"}:
                    process_usage[str(selected["process_type"])] += 1
            row["forecast_wind_total_mw"] = (
                row["forecast_wind_offshore_mw"]
                + row["forecast_wind_onshore_mw"]
            )
            for variable in WEATHER_VARIABLES:
                row[f"forecast_{variable}"] = float(weather_row[variable])
            row.update(
                {
                    "weather_forecast_collection_issue_time": weather_row[
                        "collection_issue_time"
                    ],
                    "weather_forecast_acquired_at_utc": weather_row[
                        "acquired_at_utc"
                    ],
                    "weather_forecast_provider": weather_row["provider"],
                    "weather_forecast_model": weather_row["model"],
                }
            )
            rows.append(row)

    output = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    timestamp_columns = [
        "collection_issue_time",
        "target_timestamp",
        "issue_observed_timestamp",
        *[column for column in PROVENANCE_COLUMNS if column.endswith("_utc") or column.endswith("_issue_time")],
    ]
    for column in dict.fromkeys(timestamp_columns):
        if column in output:
            output[column] = pd.to_datetime(output[column], errors="raise", utc=True)
    output = output.sort_values(list(KEY_COLUMNS)).reset_index(drop=True)
    audit = _audit_output(output)
    if not audit["passed"]:
        failed = sorted(name for name, passed in audit["checks"].items() if not passed)
        raise ValueError(f"Exogenous Silver leakage audit failed: {failed}")

    generated = pd.Timestamp(
        generated_at_utc if generated_at_utc is not None else datetime.now(timezone.utc)
    )
    generated = (
        generated.tz_localize("UTC")
        if generated.tzinfo is None
        else generated.tz_convert("UTC")
    )
    report = {
        "schema_version": 1,
        "generated_at_utc": generated.isoformat(),
        "dataset": str(OUTPUT_PATH),
        "grain": "collection_issue_time x target_timestamp x horizon_hours",
        "as_of_semantics": (
            "A response is eligible only when its logical collection cycle is not "
            "later than the output issue cycle and acquisition occurred within its "
            "declared UTC cycle hour."
        ),
        "issue_cycles": int(len(cycles)),
        "candidate_rows": int(len(cycles) * len(HORIZONS)),
        "output_rows": int(len(output)),
        "horizons_represented": sorted(
            int(value) for value in output["horizon_hours"].unique()
        ),
        "excluded_rows": int(len(cycles) * len(HORIZONS) - len(output)),
        "excluded_rows_by_reason": dict(sorted(excluded.items())),
        "missing_source_counts": {
            key: int(excluded.get(key, 0))
            for key in (
                "missing_load_forecast",
                "missing_solar_forecast",
                "missing_wind_offshore_forecast",
                "missing_wind_onshore_forecast",
                "missing_generation_forecast",
                "missing_weather_forecast",
            )
        },
        "wind_solar_process_usage": {
            "day_ahead_A01": int(process_usage.get("A01", 0)),
            "intraday_A40": int(process_usage.get("A40", 0)),
        },
        "legacy_entsoe_rows": legacy_counts,
        "entsoe_hourly_aggregation_rejections": aggregation_rejections,
        "duplicate_key_count": audit["duplicate_key_count"],
        "leakage_check": {
            "passed": audit["passed"],
            "checks": audit["checks"],
        },
    }
    return output, report


def _atomic_write_csv(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    try:
        frame.to_csv(temporary_name, index=False)
        os.replace(temporary_name, destination)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


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
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def build_next24h_exogenous_silver(
    *,
    observed_silver_path: Path = OBSERVED_SILVER_PATH,
    load_vintages_path: Path = LOAD_FORECAST_PATH,
    wind_solar_vintages_path: Path = WIND_SOLAR_FORECAST_PATH,
    generation_vintages_path: Path = GENERATION_FORECAST_PATH,
    weather_vintages_path: Path = WEATHER_FORECAST_PATH,
    output_path: Path = OUTPUT_PATH,
    quality_report_path: Path = QUALITY_REPORT_PATH,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read source files, validate, and atomically write offline outputs."""
    output, report = build_next24h_exogenous_frame(
        _read_csv(observed_silver_path),
        _read_csv(load_vintages_path, revision_strings=True),
        _read_csv(wind_solar_vintages_path, revision_strings=True),
        _read_csv(generation_vintages_path, revision_strings=True),
        _read_csv(weather_vintages_path),
    )
    output_path = Path(output_path)
    quality_report_path = Path(quality_report_path)
    report["dataset"] = str(output_path)
    _atomic_write_csv(output, output_path)
    _atomic_write_json(report, quality_report_path)
    return output, report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build isolated leakage-safe next24h exogenous Silver data."
    )
    parser.add_argument("--silver", type=Path, default=OBSERVED_SILVER_PATH)
    parser.add_argument("--load-vintages", type=Path, default=LOAD_FORECAST_PATH)
    parser.add_argument(
        "--wind-solar-vintages", type=Path, default=WIND_SOLAR_FORECAST_PATH
    )
    parser.add_argument(
        "--generation-vintages", type=Path, default=GENERATION_FORECAST_PATH
    )
    parser.add_argument(
        "--weather-vintages", type=Path, default=WEATHER_FORECAST_PATH
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--quality-report", type=Path, default=QUALITY_REPORT_PATH)
    args = parser.parse_args()
    output, report = build_next24h_exogenous_silver(
        observed_silver_path=args.silver,
        load_vintages_path=args.load_vintages,
        wind_solar_vintages_path=args.wind_solar_vintages,
        generation_vintages_path=args.generation_vintages,
        weather_vintages_path=args.weather_vintages,
        output_path=args.output,
        quality_report_path=args.quality_report,
    )
    print(
        f"Saved {len(output)} rows to {args.output}; "
        f"leakage_check={report['leakage_check']['passed']}."
    )


if __name__ == "__main__":
    main()
