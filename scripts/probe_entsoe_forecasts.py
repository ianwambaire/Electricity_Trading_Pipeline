"""Read-only capability probe for ENTSO-E DE_LU forecast endpoints."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from powerflow_secrets import SecretConfigurationError, get_secret  # noqa: E402


COUNTRY_CODE = "DE_LU"
OUTPUT_DIR = PROJECT_ROOT / "artifacts/probes/entsoe_forecasts"
OUTPUT_PATH = OUTPUT_DIR / "probe_summary.json"
ENDPOINTS = (
    ("load_forecast", "query_load_forecast", "A65", "A01"),
    ("wind_and_solar_forecast", "query_wind_and_solar_forecast", "A69", "A01"),
    (
        "intraday_wind_and_solar_forecast",
        "query_intraday_wind_and_solar_forecast",
        "A69",
        "A40",
    ),
    ("generation_forecast", "query_generation_forecast", "A71", "A01"),
)
TECHNOLOGY_NAMES = (
    "Biomass",
    "Fossil Brown coal/Lignite",
    "Fossil Coal-derived gas",
    "Fossil Gas",
    "Fossil Hard coal",
    "Fossil Oil",
    "Geothermal",
    "Hydro Pumped Storage",
    "Hydro Run-of-river and poundage",
    "Hydro Water Reservoir",
    "Nuclear",
    "Other renewable",
    "Solar",
    "Waste",
    "Wind Offshore",
    "Wind Onshore",
)


def _utc_timestamp(value: Any, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"{name} must include an explicit timezone.")
    return timestamp.tz_convert("UTC")


def _column_label(column: Any) -> str:
    if isinstance(column, tuple):
        return " | ".join(str(part) for part in column if str(part).strip())
    return str(column)


def _resolution_label(delta: pd.Timedelta) -> str:
    if delta == pd.Timedelta(minutes=15):
        return "15min"
    if delta == pd.Timedelta(minutes=30):
        return "30min"
    if delta == pd.Timedelta(hours=1):
        return "1h"
    return str(delta)


def _timestamp_resolution(index: pd.DatetimeIndex) -> str | list[str] | None:
    unique = index.dropna().unique().sort_values()
    if len(unique) < 2:
        return None
    deltas = pd.Series(unique[1:] - unique[:-1]).drop_duplicates().sort_values()
    labels = [_resolution_label(pd.Timedelta(delta)) for delta in deltas]
    return labels[0] if len(labels) == 1 else labels


def summarize_response(response: pd.Series | pd.DataFrame, endpoint: str) -> dict:
    """Summarize an entsoe-py response without retaining returned forecast values."""
    if not isinstance(response, (pd.Series, pd.DataFrame)):
        raise TypeError("ENTSO-E forecast response must be a pandas Series or DataFrame.")
    if not isinstance(response.index, pd.DatetimeIndex):
        raise TypeError("ENTSO-E forecast response must use a DatetimeIndex.")

    index = response.index
    if isinstance(response, pd.Series):
        labels = []
        series_name = None if response.name is None else _column_label(response.name)
        missing_by_column = {series_name or "value": int(response.isna().sum())}
    else:
        labels = [_column_label(column) for column in response.columns]
        series_name = None
        missing_by_column = {
            _column_label(column): int(response[column].isna().sum())
            for column in response.columns
        }

    searchable = " ".join([endpoint, series_name or "", *labels]).casefold()
    technology_columns = [
        technology
        for technology in TECHNOLOGY_NAMES
        if technology.casefold() in searchable
    ]
    issue_markers = ("issue_time", "issue time", "publication", "created", "acquired")
    issue_time_exposed = any(marker in searchable for marker in issue_markers)

    return {
        "python_object_type": type(response).__name__,
        "columns": labels,
        "series_name": series_name,
        "row_count": int(len(response)),
        "timestamp_timezone": str(index.tz) if index.tz is not None else None,
        "timestamp_resolution": _timestamp_resolution(index),
        "first_timestamp": index.min().isoformat() if len(index) else None,
        "last_timestamp": index.max().isoformat() if len(index) else None,
        "missing_values": {
            "total": int(sum(missing_by_column.values())),
            "by_column": missing_by_column,
        },
        "duplicate_timestamps": int(index.duplicated(keep=False).sum()),
        "available_psr_technology_columns": technology_columns,
        "coverage": {
            "offshore_wind": "wind offshore" in searchable,
            "onshore_wind": "wind onshore" in searchable,
            "solar": "solar" in searchable,
            "total_load": endpoint == "load_forecast" and len(response) > 0,
            "aggregate_generation": endpoint == "generation_forecast" and len(response) > 0,
        },
        "target_timestamps_exposed": True,
        "source_issue_or_publication_time_exposed": issue_time_exposed,
        "can_distinguish_issue_time_from_target_time": issue_time_exposed,
    }


def probe_forecast_endpoints(
    client: Any,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    country_code: str = COUNTRY_CODE,
) -> dict:
    """Call each forecast endpoint independently and return credential-free metadata."""
    start = _utc_timestamp(start, "start")
    end = _utc_timestamp(end, "end")
    if end <= start:
        raise ValueError("end must be later than start.")
    if country_code != COUNTRY_CODE:
        raise ValueError("The forecast capability probe is restricted to DE_LU.")

    results = {}
    for endpoint, method_name, document_type, process_type in ENDPOINTS:
        result = {
            "status": "error",
            "method": method_name,
            "document_type": document_type,
            "process_type": process_type,
        }
        try:
            method: Callable = getattr(client, method_name)
            response = method(country_code, start=start, end=end)
            result.update(status="success", **summarize_response(response, endpoint))
        except Exception as error:  # each independent API must remain isolated
            result.update(
                error_type=type(error).__name__,
                error_message="ENTSO-E forecast query failed; details were omitted for safety.",
            )
        results[endpoint] = result

    return {
        "probe_type": "read_only_entsoe_forecast_capability",
        "country_code": country_code,
        "query_start_utc": start.isoformat(),
        "query_end_utc": end.isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "returned_values_persisted": False,
        "endpoints": results,
    }


def write_summary(summary: dict, output_path: Path = OUTPUT_PATH) -> Path:
    """Write only the JSON metadata summary beneath the approved probe directory."""
    output_path = Path(output_path)
    approved = OUTPUT_DIR.resolve()
    resolved = output_path.resolve()
    if resolved != approved and approved not in resolved.parents:
        raise ValueError("Probe output must remain under artifacts/probes/entsoe_forecasts/.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only probe of ENTSO-E DE_LU forecast capabilities."
    )
    parser.add_argument(
        "--start",
        help="Inclusive timezone-aware start; defaults to the current UTC day.",
    )
    parser.add_argument(
        "--end",
        help="Exclusive timezone-aware end; defaults to 48 hours after start.",
    )
    args = parser.parse_args()

    start = (
        _utc_timestamp(args.start, "start")
        if args.start
        else pd.Timestamp.now(tz="UTC").floor("D")
    )
    end = (
        _utc_timestamp(args.end, "end")
        if args.end
        else start + pd.Timedelta(hours=48)
    )

    load_dotenv(PROJECT_ROOT / ".env")
    try:
        api_key = get_secret("ENTSOE_API_KEY")
    except SecretConfigurationError as error:
        parser.error(str(error))
    client = EntsoePandasClient(
        api_key=api_key,
        retry_count=1,
        retry_delay=0,
        timeout=30,
    )
    try:
        summary = probe_forecast_endpoints(client, start, end)
    except KeyboardInterrupt:
        parser.error("ENTSO-E forecast probe interrupted; request details were omitted.")
    path = write_summary(summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Probe summary written to {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
