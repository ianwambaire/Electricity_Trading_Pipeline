"""Isolated Open-Meteo future-weather forecast-vintage collection."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests


OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OUTPUT_PATH = Path("data/raw/weather/open_meteo_forecast_vintages.csv")
OBSERVED_WEATHER_FILENAME = "open_meteo_weather.csv"
LATITUDE = 52.52
LONGITUDE = 13.41
WEATHER_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "cloud_cover",
    "shortwave_radiation",
)
WEATHER_FORECAST_COLUMNS = (
    "collection_issue_time",
    "acquired_at_utc",
    "target_timestamp",
    "horizon_hours",
    *WEATHER_VARIABLES,
    "provider",
    "model",
)
LEGACY_WEATHER_FORECAST_COLUMNS = tuple(
    "forecast_issue_time" if column == "collection_issue_time" else column
    for column in WEATHER_FORECAST_COLUMNS
)
WEATHER_VINTAGE_IDENTITY = (
    "provider",
    "model",
    "collection_issue_time",
    "target_timestamp",
)


def _utc_timestamp(value: Any, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"{name} must include an explicit timezone.")
    return timestamp.tz_convert("UTC")


def _normalize_utc_column(frame: pd.DataFrame, column: str) -> None:
    frame[column] = pd.DatetimeIndex(
        [_utc_timestamp(value, column) for value in frame[column]]
    )


def _migrate_legacy_weather_schema(frame: pd.DataFrame) -> pd.DataFrame:
    """Rename the prior issue-time field without changing its values."""
    if list(frame.columns) == list(WEATHER_FORECAST_COLUMNS):
        return frame.copy()
    if list(frame.columns) != list(LEGACY_WEATHER_FORECAST_COLUMNS):
        raise ValueError(
            "Open-Meteo forecast schema must be the current schema or the "
            "documented legacy schema."
        )
    return frame.rename(
        columns={"forecast_issue_time": "collection_issue_time"}
    ).loc[:, WEATHER_FORECAST_COLUMNS]


def normalize_weather_forecast_vintages(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate exact 24-hour issue-time vintages and normalize to UTC."""
    normalized = _migrate_legacy_weather_schema(frame)
    for column in (
        "collection_issue_time",
        "acquired_at_utc",
        "target_timestamp",
    ):
        _normalize_utc_column(normalized, column)
    numeric = ["horizon_hours", *WEATHER_VARIABLES]
    for column in numeric:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized["provider"] = normalized["provider"].astype(str)
    normalized["model"] = normalized["model"].fillna("").astype(str)

    if normalized.empty:
        raise ValueError("Open-Meteo forecast vintages cannot be empty.")
    if set(normalized["provider"]) != {"OPEN_METEO"}:
        raise ValueError("Weather forecast provider must be OPEN_METEO.")
    if not np.isfinite(normalized[numeric]).all().all():
        raise ValueError("Weather forecast values and horizons must be finite.")
    if (normalized["horizon_hours"] < 0).any():
        raise ValueError("Weather forecast horizons must be non-negative.")
    if not normalized["collection_issue_time"].eq(
        normalized["collection_issue_time"].dt.floor("h")
    ).all():
        raise ValueError("collection_issue_time must be an exact UTC hour.")
    if not normalized["target_timestamp"].eq(
        normalized["target_timestamp"].dt.floor("h")
    ).all():
        raise ValueError("Weather forecast targets must be exact UTC hours.")
    expected_horizon = (
        normalized["target_timestamp"] - normalized["collection_issue_time"]
    ).dt.total_seconds() / 3600.0
    if not np.allclose(normalized["horizon_hours"], expected_horizon):
        raise ValueError("Weather forecast horizon_hours is inconsistent.")
    if not normalized["relative_humidity_2m"].between(0, 100).all():
        raise ValueError("relative_humidity_2m must be between 0 and 100.")
    if not normalized["cloud_cover"].between(0, 100).all():
        raise ValueError("cloud_cover must be between 0 and 100.")
    if (normalized[["wind_speed_10m", "shortwave_radiation"]] < 0).any().any():
        raise ValueError("Wind speed and shortwave radiation cannot be negative.")

    if normalized.duplicated(
        subset=list(WEATHER_VINTAGE_IDENTITY), keep=False
    ).any():
        duplicate = normalized.duplicated(
            subset=list(WEATHER_VINTAGE_IDENTITY), keep=False
        )
        for _, rows in normalized.loc[duplicate].groupby(
            list(WEATHER_VINTAGE_IDENTITY), dropna=False, sort=False
        ):
            if rows[["horizon_hours", *WEATHER_VARIABLES]].nunique(
                dropna=False
            ).max() > 1:
                raise ValueError(
                    "Conflicting weather values share one forecast-vintage identity."
                )
        normalized = normalized.sort_values("acquired_at_utc").drop_duplicates(
            subset=list(WEATHER_VINTAGE_IDENTITY), keep="first"
        )

    group_columns = [
        "provider",
        "model",
        "collection_issue_time",
    ]
    expected = set(range(1, 25))
    for _, vintage in normalized.groupby(group_columns, dropna=False):
        horizons = set(vintage["horizon_hours"].astype(int))
        if len(vintage) != 24 or horizons != expected:
            raise ValueError("Each weather forecast vintage must contain horizons 1..24.")

    return normalized.sort_values(
        ["collection_issue_time", "acquired_at_utc", "target_timestamp"]
    ).reset_index(drop=True)


def parse_open_meteo_forecast(
    payload: dict[str, Any],
    *,
    collection_issue_time: Any | None = None,
    forecast_issue_time: Any | None = None,
    acquired_at_utc: Any,
) -> pd.DataFrame:
    """Parse exactly t+1 through t+24 from one operational forecast response."""
    if collection_issue_time is not None and forecast_issue_time is not None:
        raise ValueError(
            "Use collection_issue_time; forecast_issue_time is a legacy alias."
        )
    issue_value = (
        collection_issue_time
        if collection_issue_time is not None
        else forecast_issue_time
    )
    if issue_value is None:
        raise ValueError("collection_issue_time is required.")
    issue = _utc_timestamp(issue_value, "collection_issue_time")
    if issue != issue.floor("h"):
        raise ValueError("collection_issue_time must be an exact UTC hour.")
    acquired = _utc_timestamp(acquired_at_utc, "acquired_at_utc")
    if payload.get("timezone") not in {"UTC", "GMT"}:
        raise ValueError("Open-Meteo forecast response is not explicitly UTC.")
    if payload.get("utc_offset_seconds") != 0:
        raise ValueError("Open-Meteo forecast response has a non-zero UTC offset.")
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise ValueError("Open-Meteo forecast response is missing hourly data.")
    missing = [name for name in ("time", *WEATHER_VARIABLES) if name not in hourly]
    if missing:
        raise ValueError(f"Open-Meteo forecast response is missing: {missing}")

    try:
        frame = pd.DataFrame(hourly).loc[:, ["time", *WEATHER_VARIABLES]]
    except ValueError as error:
        raise ValueError("Open-Meteo hourly arrays have inconsistent lengths.") from error
    frame = frame.rename(columns={"time": "target_timestamp"})
    frame["target_timestamp"] = pd.to_datetime(
        frame["target_timestamp"], errors="raise", utc=True
    )
    if frame["target_timestamp"].duplicated().any():
        raise ValueError("Open-Meteo forecast response has duplicate target hours.")
    expected_targets = pd.date_range(
        issue + pd.Timedelta(hours=1),
        issue + pd.Timedelta(hours=24),
        freq="h",
    )
    frame = frame.loc[frame["target_timestamp"].isin(expected_targets)].copy()
    if not pd.DatetimeIndex(frame["target_timestamp"]).sort_values().equals(
        expected_targets
    ):
        missing_targets = expected_targets.difference(frame["target_timestamp"])
        raise ValueError(
            "Open-Meteo forecast response does not cover every t+1..t+24 hour; "
            f"missing={len(missing_targets)}."
        )

    frame["collection_issue_time"] = issue
    frame["acquired_at_utc"] = acquired
    frame["horizon_hours"] = (
        frame["target_timestamp"] - issue
    ).dt.total_seconds() / 3600.0
    frame["provider"] = "OPEN_METEO"
    frame["model"] = str(payload.get("model") or payload.get("models") or "")
    frame = frame.loc[:, WEATHER_FORECAST_COLUMNS]
    return normalize_weather_forecast_vintages(frame)


def merge_weather_forecast_vintages(
    existing: pd.DataFrame | None,
    incoming: pd.DataFrame,
) -> pd.DataFrame:
    incoming = normalize_weather_forecast_vintages(incoming)
    if existing is None or existing.empty:
        return incoming
    existing = normalize_weather_forecast_vintages(existing)
    return normalize_weather_forecast_vintages(
        pd.concat([existing, incoming], ignore_index=True)
        .loc[:, WEATHER_FORECAST_COLUMNS]
    )


def _assert_safe_output_path(path: Path) -> None:
    if path.name == OBSERVED_WEATHER_FILENAME:
        raise ValueError("Forecast vintages cannot overwrite observed weather data.")


def _write_atomic(frame: pd.DataFrame, path: Path) -> None:
    _assert_safe_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        frame.to_csv(temporary, index=False)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def append_weather_forecast_vintages(
    path: Path,
    incoming: pd.DataFrame,
) -> dict[str, Any]:
    path = Path(path)
    _assert_safe_output_path(path)
    existing = pd.read_csv(path) if path.exists() else None
    previous_rows = 0 if existing is None else len(existing)
    combined = merge_weather_forecast_vintages(existing, incoming)
    new_rows = len(combined) - previous_rows
    if existing is None or new_rows:
        _write_atomic(combined, path)
    return {
        "path": str(path),
        "rows_before": previous_rows,
        "rows_after": len(combined),
        "new_rows": new_rows,
    }


def fetch_operational_weather_forecast_vintage(
    issue_time: Any | None = None,
    *,
    acquired_at_utc: Any | None = None,
    acquisition_clock=None,
    session: Any = requests,
    output_path: Path = OUTPUT_PATH,
) -> dict[str, Any]:
    """Fetch and persist one independent Open-Meteo t+1..t+24 vintage."""
    if acquired_at_utc is not None and acquisition_clock is not None:
        raise ValueError(
            "Use either acquired_at_utc or acquisition_clock, not both."
        )
    cycle_started = datetime.now(timezone.utc)
    issue = (
        pd.Timestamp(cycle_started).floor("h")
        if issue_time is None
        else _utc_timestamp(issue_time, "issue_time")
    )
    if issue != issue.floor("h"):
        raise ValueError("issue_time must be an exact UTC hour.")
    start = issue + pd.Timedelta(hours=1)
    end = issue + pd.Timedelta(hours=24)
    response = session.get(
        OPEN_METEO_FORECAST_URL,
        params={
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": list(WEATHER_VARIABLES),
            "timezone": "UTC",
            "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
            "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    acquired = _utc_timestamp(
        acquired_at_utc
        if acquired_at_utc is not None
        else (
            acquisition_clock()
            if acquisition_clock is not None
            else datetime.now(timezone.utc)
        ),
        "acquired_at_utc",
    )
    frame = parse_open_meteo_forecast(
        payload,
        collection_issue_time=issue,
        acquired_at_utc=acquired,
    )
    result = append_weather_forecast_vintages(output_path, frame)
    result.update(
        collection_issue_time=issue.isoformat(),
        acquired_at_utc=acquired.isoformat(),
        target_start_utc=frame["target_timestamp"].min().isoformat(),
        target_end_utc=frame["target_timestamp"].max().isoformat(),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect one isolated Open-Meteo t+1..t+24 forecast vintage."
    )
    parser.add_argument(
        "--issue-time",
        help="Exact UTC issue hour; defaults to the current acquired hour.",
    )
    args = parser.parse_args()
    print(fetch_operational_weather_forecast_vintage(args.issue_time))


if __name__ == "__main__":
    main()
