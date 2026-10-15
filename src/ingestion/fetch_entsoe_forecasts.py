"""Isolated ENTSO-E forecast-vintage ingestion for DE_LU."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoeRawClient

from powerflow_secrets import get_secret


COUNTRY_CODE = "DE_LU"
SOURCE = "ENTSOE"
FORECAST_DIR = Path("data/raw/entsoe/forecasts")
LOAD_FORECAST_PATH = FORECAST_DIR / "load_forecast_vintages.csv"
WIND_SOLAR_FORECAST_PATH = FORECAST_DIR / "wind_solar_forecast_vintages.csv"
GENERATION_FORECAST_PATH = FORECAST_DIR / "generation_forecast_vintages.csv"
DEFAULT_OUTPUT_PATHS = {
    "load": LOAD_FORECAST_PATH,
    "wind_solar": WIND_SOLAR_FORECAST_PATH,
    "generation": GENERATION_FORECAST_PATH,
}
OBSERVED_FILENAMES = {"prices.csv", "load.csv", "generation.csv"}

ENTSOE_FORECAST_COLUMNS = (
    "source",
    "document_type",
    "process_type",
    "document_id",
    "revision_number",
    "source_created_at_utc",
    "collection_issue_time",
    "acquired_at_utc",
    "market_area",
    "target_timestamp",
    "resolution",
    "source_horizon_minutes",
    "technology",
    "value_mw",
)
LEGACY_ENTSOE_FORECAST_COLUMNS = tuple(
    "horizon_minutes" if column == "source_horizon_minutes" else column
    for column in ENTSOE_FORECAST_COLUMNS
    if column != "collection_issue_time"
)
ENTSOE_VINTAGE_IDENTITY = (
    "source",
    "document_type",
    "process_type",
    "document_id",
    "revision_number",
    "source_created_at_utc",
    "market_area",
    "target_timestamp",
    "technology",
)
CONTROLLED_TECHNOLOGIES = {
    "TOTAL_LOAD",
    "TOTAL_GENERATION",
    "SOLAR",
    "WIND_OFFSHORE",
    "WIND_ONSHORE",
}
PSR_TECHNOLOGIES = {
    "B16": "SOLAR",
    "B18": "WIND_OFFSHORE",
    "B19": "WIND_ONSHORE",
}
_DURATION_PATTERN = re.compile(
    r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


@dataclass(frozen=True)
class ForecastSpec:
    key: str
    method: str
    document_type: str
    process_type: str
    output_group: str


FORECAST_SPECS = (
    ForecastSpec("load", "query_load_forecast", "A65", "A01", "load"),
    ForecastSpec(
        "wind_solar_day_ahead",
        "query_wind_and_solar_forecast",
        "A69",
        "A01",
        "wind_solar",
    ),
    ForecastSpec(
        "wind_solar_intraday",
        "query_intraday_wind_and_solar_forecast",
        "A69",
        "A40",
        "wind_solar",
    ),
    ForecastSpec(
        "generation",
        "query_generation_forecast",
        "A71",
        "A01",
        "generation",
    ),
)


def _child(parent: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return parent.find(f"{{*}}{name}")


def _required_text(parent: ElementTree.Element, name: str) -> str:
    child = _child(parent, name)
    if child is None or child.text is None or not child.text.strip():
        raise ValueError(f"ENTSO-E forecast XML is missing {name}.")
    return child.text.strip()


def _utc_timestamp(value: Any, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"{name} must include an explicit timezone.")
    return timestamp.tz_convert("UTC")


def _resolution_delta(resolution: str) -> pd.Timedelta:
    match = _DURATION_PATTERN.fullmatch(str(resolution))
    if not match:
        raise ValueError(f"Unsupported ENTSO-E forecast resolution: {resolution}")
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    delta = pd.Timedelta(hours=hours, minutes=minutes, seconds=seconds)
    if delta <= pd.Timedelta(0):
        raise ValueError("ENTSO-E forecast resolution must be positive.")
    return delta


def _technology(document_type: str, series: ElementTree.Element) -> str:
    if document_type == "A65":
        return "TOTAL_LOAD"
    if document_type == "A71":
        # A71 is aggregate generation. Never infer a generation technology here.
        return "TOTAL_GENERATION"
    psr_container = _child(series, "MktPSRType")
    if psr_container is None:
        raise ValueError("A69 forecast series is missing MktPSRType.")
    psr_type = _required_text(psr_container, "psrType")
    if psr_type not in PSR_TECHNOLOGIES:
        raise ValueError(f"Unsupported A69 forecast PSR type: {psr_type}")
    return PSR_TECHNOLOGIES[psr_type]


def parse_entsoe_forecast_xml(
    xml_text: str,
    *,
    expected_document_type: str,
    expected_process_type: str,
    acquired_at_utc: Any,
    collection_issue_time: Any | None = None,
    market_area: str = COUNTRY_CODE,
    target_start_utc: Any | None = None,
    target_end_utc: Any | None = None,
) -> pd.DataFrame:
    """Parse forecast values with source-document provenance intact."""
    root = ElementTree.fromstring(xml_text)
    document_type = _required_text(root, "type")
    process_type = _required_text(root, "process.processType")
    if document_type != expected_document_type or process_type != expected_process_type:
        raise ValueError(
            "ENTSO-E forecast document/process type did not match the requested contract."
        )
    if (document_type, process_type) not in {
        ("A65", "A01"),
        ("A69", "A01"),
        ("A69", "A40"),
        ("A71", "A01"),
    }:
        raise ValueError("Unsupported ENTSO-E forecast document/process type.")
    if market_area != COUNTRY_CODE:
        raise ValueError("ENTSO-E forecast ingestion is restricted to DE_LU.")

    document_id = _required_text(root, "mRID")
    revision_number = _required_text(root, "revisionNumber")
    source_created = _utc_timestamp(
        _required_text(root, "createdDateTime"), "source_created_at_utc"
    )
    acquired = _utc_timestamp(acquired_at_utc, "acquired_at_utc")
    issue = _utc_timestamp(
        collection_issue_time
        if collection_issue_time is not None
        else acquired.floor("h"),
        "collection_issue_time",
    )
    if issue != issue.floor("h"):
        raise ValueError("collection_issue_time must be an exact UTC hour.")
    if acquired < source_created:
        raise ValueError(
            "ENTSO-E acquired_at_utc must not precede source_created_at_utc."
        )

    rows: list[dict[str, Any]] = []
    for series in root.findall("{*}TimeSeries"):
        technology = _technology(document_type, series)
        for period in series.findall("{*}Period"):
            interval = _child(period, "timeInterval")
            if interval is None:
                raise ValueError("ENTSO-E forecast period is missing timeInterval.")
            period_start = _utc_timestamp(
                _required_text(interval, "start"), "period start"
            )
            period_end = _utc_timestamp(_required_text(interval, "end"), "period end")
            if period_end <= period_start:
                raise ValueError("ENTSO-E forecast period end must follow its start.")
            resolution = _required_text(period, "resolution")
            step = _resolution_delta(resolution)
            for point in period.findall("{*}Point"):
                position = int(_required_text(point, "position"))
                if position < 1:
                    raise ValueError("ENTSO-E forecast point position must be positive.")
                target = period_start + (position - 1) * step
                if target >= period_end:
                    raise ValueError("ENTSO-E forecast point falls outside its period.")
                value = float(_required_text(point, "quantity"))
                rows.append(
                    {
                        "source": SOURCE,
                        "document_type": document_type,
                        "process_type": process_type,
                        "document_id": document_id,
                        "revision_number": revision_number,
                        "source_created_at_utc": source_created,
                        "collection_issue_time": issue,
                        "acquired_at_utc": acquired,
                        "market_area": market_area,
                        "target_timestamp": target,
                        "resolution": resolution,
                        "source_horizon_minutes": (
                            target - source_created
                        ).total_seconds()
                        / 60.0,
                        "technology": technology,
                        "value_mw": value,
                    }
                )

    if not rows:
        raise ValueError("ENTSO-E forecast document contains no forecast points.")
    frame = pd.DataFrame(rows, columns=ENTSOE_FORECAST_COLUMNS)
    if target_start_utc is not None:
        target_start = _utc_timestamp(target_start_utc, "target_start_utc")
        frame = frame.loc[frame["target_timestamp"] >= target_start]
    if target_end_utc is not None:
        target_end = _utc_timestamp(target_end_utc, "target_end_utc")
        frame = frame.loc[frame["target_timestamp"] < target_end]
    if frame.empty:
        raise ValueError("ENTSO-E forecast document has no points in the target range.")
    return normalize_entsoe_vintages(frame)


def _normalize_utc_column(frame: pd.DataFrame, column: str) -> None:
    values = []
    for value in frame[column]:
        values.append(_utc_timestamp(value, column))
    frame[column] = pd.DatetimeIndex(values)


def _migrate_legacy_entsoe_schema(frame: pd.DataFrame) -> pd.DataFrame:
    """Adapt the pre-cycle schema without inventing historical issue times."""
    if list(frame.columns) == list(ENTSOE_FORECAST_COLUMNS):
        return frame.copy()
    if list(frame.columns) != list(LEGACY_ENTSOE_FORECAST_COLUMNS):
        raise ValueError(
            "ENTSO-E forecast schema must be the current schema or the "
            "documented legacy schema."
        )
    migrated = frame.rename(
        columns={"horizon_minutes": "source_horizon_minutes"}
    ).copy()
    migrated.insert(
        migrated.columns.get_loc("acquired_at_utc"),
        "collection_issue_time",
        pd.NaT,
    )
    return migrated.loc[:, ENTSOE_FORECAST_COLUMNS]


def normalize_entsoe_vintages(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize, validate, and deduplicate identical source-vintage rows."""
    normalized = _migrate_legacy_entsoe_schema(frame)
    for column in (
        "source_created_at_utc",
        "acquired_at_utc",
        "target_timestamp",
    ):
        _normalize_utc_column(normalized, column)
    raw_issue_time = normalized["collection_issue_time"]
    missing_legacy_issue = raw_issue_time.isna() | raw_issue_time.astype(
        "string"
    ).str.strip().eq("").fillna(True)
    normalized["collection_issue_time"] = pd.to_datetime(
        raw_issue_time, errors="coerce", utc=True
    )
    if (
        normalized["collection_issue_time"].isna() & ~missing_legacy_issue
    ).any():
        raise ValueError("collection_issue_time contains an invalid timestamp.")
    for column in ("source_horizon_minutes", "value_mw"):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    if normalized.empty:
        raise ValueError("ENTSO-E forecast vintages cannot be empty.")
    if set(normalized["source"]) != {SOURCE}:
        raise ValueError("ENTSO-E forecast source must be ENTSOE.")
    if set(normalized["market_area"]) != {COUNTRY_CODE}:
        raise ValueError("ENTSO-E forecast market_area must be DE_LU.")
    if not set(normalized["technology"]).issubset(CONTROLLED_TECHNOLOGIES):
        raise ValueError("ENTSO-E forecast contains an uncontrolled technology label.")
    if normalized[["document_id", "revision_number", "resolution"]].isna().any().any():
        raise ValueError("ENTSO-E forecast provenance fields cannot be missing.")
    if not np.isfinite(
        normalized[["source_horizon_minutes", "value_mw"]]
    ).all().all():
        raise ValueError("ENTSO-E forecast numeric values must be finite.")
    if (normalized["source_horizon_minutes"] < 0).any():
        raise ValueError("ENTSO-E forecast horizons must be non-negative.")

    expected_horizon = (
        normalized["target_timestamp"] - normalized["source_created_at_utc"]
    ).dt.total_seconds() / 60.0
    if not np.allclose(normalized["source_horizon_minutes"], expected_horizon):
        raise ValueError(
            "ENTSO-E forecast source_horizon_minutes is inconsistent."
        )
    current_rows = normalized["collection_issue_time"].notna()
    if not normalized.loc[current_rows, "collection_issue_time"].eq(
        normalized.loc[current_rows, "collection_issue_time"].dt.floor("h")
    ).all():
        raise ValueError("collection_issue_time must be an exact UTC hour.")
    if (
        normalized.loc[current_rows, "acquired_at_utc"]
        < normalized.loc[current_rows, "source_created_at_utc"]
    ).any():
        raise ValueError(
            "ENTSO-E acquired_at_utc must not precede source_created_at_utc."
        )
    for resolution in normalized["resolution"].unique():
        _resolution_delta(str(resolution))

    allowed = {
        ("A65", "A01"): {"TOTAL_LOAD"},
        ("A69", "A01"): {"SOLAR", "WIND_OFFSHORE", "WIND_ONSHORE"},
        ("A69", "A40"): {"SOLAR", "WIND_OFFSHORE", "WIND_ONSHORE"},
        ("A71", "A01"): {"TOTAL_GENERATION"},
    }
    for (document_type, process_type), group in normalized.groupby(
        ["document_type", "process_type"], dropna=False
    ):
        permitted = allowed.get((document_type, process_type))
        if permitted is None or not set(group["technology"]).issubset(permitted):
            raise ValueError("ENTSO-E forecast document/process/technology is invalid.")

    duplicate_mask = normalized.duplicated(
        subset=list(ENTSOE_VINTAGE_IDENTITY), keep=False
    )
    if duplicate_mask.any():
        for _, duplicates in normalized.loc[duplicate_mask].groupby(
            list(ENTSOE_VINTAGE_IDENTITY), dropna=False, sort=False
        ):
            if duplicates[
                ["resolution", "source_horizon_minutes", "value_mw"]
            ].nunique(dropna=False).max() > 1:
                raise ValueError(
                    "Conflicting ENTSO-E values share one source-vintage identity."
                )
        normalized = normalized.sort_values("acquired_at_utc").drop_duplicates(
            subset=list(ENTSOE_VINTAGE_IDENTITY), keep="first"
        )

    return normalized.sort_values(
        ["target_timestamp", "document_type", "process_type", "technology"]
    ).reset_index(drop=True)


def _read_existing(path: Path) -> pd.DataFrame:
    existing = pd.read_csv(path, dtype={"revision_number": "string"})
    return normalize_entsoe_vintages(existing)


def merge_entsoe_vintages(
    existing: pd.DataFrame | None,
    incoming: pd.DataFrame,
) -> pd.DataFrame:
    incoming = normalize_entsoe_vintages(incoming)
    if existing is None or existing.empty:
        return incoming
    existing = normalize_entsoe_vintages(existing)
    return normalize_entsoe_vintages(
        pd.concat([existing, incoming], ignore_index=True)
        .loc[:, ENTSOE_FORECAST_COLUMNS]
    )


def _assert_safe_output_path(path: Path) -> None:
    if path.name in OBSERVED_FILENAMES:
        raise ValueError("Forecast vintages cannot be written to an observed-data path.")


def _write_atomic(frame: pd.DataFrame, path: Path) -> None:
    _assert_safe_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        frame.to_csv(temporary, index=False)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def append_entsoe_vintages(path: Path, incoming: pd.DataFrame) -> dict[str, Any]:
    """Atomically append source vintages while preserving explicit revisions."""
    path = Path(path)
    _assert_safe_output_path(path)
    existing = _read_existing(path) if path.exists() else None
    previous_rows = 0 if existing is None else len(existing)
    combined = merge_entsoe_vintages(existing, incoming)
    new_rows = len(combined) - previous_rows
    if existing is None or new_rows:
        _write_atomic(combined, path)
    return {
        "path": str(path),
        "rows_before": previous_rows,
        "rows_after": len(combined),
        "new_rows": new_rows,
    }


def collect_entsoe_forecast_vintages(
    start_utc: Any,
    end_utc: Any,
    *,
    client: Any | None = None,
    collection_issue_time: Any | None = None,
    acquired_at_utc: Any | None = None,
    acquisition_clock=None,
    output_paths: dict[str, Path] | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch four raw XML products, validate them, then persist new vintages."""
    start = _utc_timestamp(start_utc, "start_utc")
    end = _utc_timestamp(end_utc, "end_utc")
    if end <= start:
        raise ValueError("end_utc must be later than start_utc.")
    if acquired_at_utc is not None and acquisition_clock is not None:
        raise ValueError(
            "Use either acquired_at_utc or acquisition_clock, not both."
        )
    cycle_reference = (
        acquired_at_utc
        if acquired_at_utc is not None
        else datetime.now(timezone.utc)
    )
    issue = _utc_timestamp(
        collection_issue_time
        if collection_issue_time is not None
        else pd.Timestamp(cycle_reference).floor("h"),
        "collection_issue_time",
    )
    if issue != issue.floor("h"):
        raise ValueError("collection_issue_time must be an exact UTC hour.")
    if acquisition_clock is None:
        acquisition_clock = (
            (lambda: acquired_at_utc)
            if acquired_at_utc is not None
            else (lambda: datetime.now(timezone.utc))
        )
    if client is None:
        load_dotenv()
        client = EntsoeRawClient(
            api_key=get_secret("ENTSOE_API_KEY"),
            retry_count=1,
            retry_delay=0,
            timeout=30,
        )
    paths = {
        key: Path(value)
        for key, value in (output_paths or DEFAULT_OUTPUT_PATHS).items()
    }
    if set(paths) != set(DEFAULT_OUTPUT_PATHS):
        raise ValueError("output_paths must define load, wind_solar, and generation.")

    grouped: dict[str, list[pd.DataFrame]] = {key: [] for key in paths}
    endpoint_rows: dict[str, int] = {}
    endpoint_acquired_at: dict[str, str] = {}
    for spec in FORECAST_SPECS:
        try:
            xml_text = getattr(client, spec.method)(
                COUNTRY_CODE, start=start, end=end
            )
        except Exception as error:
            raise RuntimeError(
                f"ENTSO-E {spec.key} forecast query failed; "
                f"error type: {type(error).__name__}."
            ) from None
        acquired = _utc_timestamp(acquisition_clock(), "acquired_at_utc")
        frame = parse_entsoe_forecast_xml(
            xml_text,
            expected_document_type=spec.document_type,
            expected_process_type=spec.process_type,
            acquired_at_utc=acquired,
            collection_issue_time=issue,
            target_start_utc=start,
            target_end_utc=end,
        )
        grouped[spec.output_group].append(frame)
        endpoint_rows[spec.key] = len(frame)
        endpoint_acquired_at[spec.key] = acquired.isoformat()

    incoming = {
        group: normalize_entsoe_vintages(pd.concat(frames, ignore_index=True))
        for group, frames in grouped.items()
    }
    results = {
        group: append_entsoe_vintages(paths[group], frame)
        for group, frame in incoming.items()
    }
    for group, result in results.items():
        result["fetched_rows"] = len(incoming[group])
        result["revision_count"] = len(
            incoming[group][
                [
                    "document_type",
                    "process_type",
                    "document_id",
                    "revision_number",
                ]
            ].drop_duplicates()
        )
        result["acquisition_timestamps"] = sorted(
            timestamp.isoformat()
            for timestamp in incoming[group]["acquired_at_utc"].unique()
        )
        result["collection_issue_time"] = issue.isoformat()
    results["endpoints"] = endpoint_rows
    results["endpoint_acquired_at_utc"] = endpoint_acquired_at
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect isolated DE_LU ENTSO-E forecast vintages."
    )
    parser.add_argument("--start", required=True, help="Inclusive UTC timestamp.")
    parser.add_argument("--end", required=True, help="Exclusive UTC timestamp.")
    args = parser.parse_args()
    result = collect_entsoe_forecast_vintages(args.start, args.end)
    for group, details in result.items():
        print(f"{group}: {details}")


if __name__ == "__main__":
    main()
