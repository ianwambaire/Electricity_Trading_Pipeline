import argparse
from pathlib import Path

import pandas as pd
import requests

if __package__:
    from .historical_range import get_historical_date_range, iter_time_chunks, iter_utc_chunks
    from .incremental_utils import (
        append_csv_safely,
        completed_utc_hour,
        latest_stored_timestamp,
    )
else:
    from historical_range import get_historical_date_range, iter_time_chunks, iter_utc_chunks
    from incremental_utils import (
        append_csv_safely,
        completed_utc_hour,
        latest_stored_timestamp,
    )


RAW_WEATHER_DIR = Path("data/raw/weather")
OUTPUT_PATH = RAW_WEATHER_DIR / "open_meteo_weather.csv"
OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "cloud_cover",
    "shortwave_radiation",
]


def combine_weather_chunks(chunks: list[pd.DataFrame]) -> pd.DataFrame:
    if not chunks:
        raise ValueError("At least one non-empty Open-Meteo chunk is required.")

    combined = pd.concat(chunks, ignore_index=True)
    combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True)
    return (
        combined.drop_duplicates(subset=["timestamp"], keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def fetch_weather_timestamp_range(
    start_utc: pd.Timestamp,
    end_utc_exclusive: pd.Timestamp,
    *,
    session=requests,
    allow_empty: bool,
) -> pd.DataFrame | None:
    chunks = []

    for chunk_start, chunk_end in iter_utc_chunks(start_utc, end_utc_exclusive):
        chunk_end_inclusive = (chunk_end - pd.Timedelta(nanoseconds=1)).date()
        params = {
            "latitude": 52.52,
            "longitude": 13.41,
            "start_date": chunk_start.date().isoformat(),
            "end_date": chunk_end_inclusive.isoformat(),
            "hourly": WEATHER_VARIABLES,
            "timezone": "UTC",
        }
        print(
            "Fetching Open-Meteo historical weather: "
            f"{params['start_date']} to {params['end_date']}"
        )
        response = session.get(OPEN_METEO_URL, params=params, timeout=60)
        response.raise_for_status()
        hourly = response.json().get("hourly", {})

        if not hourly and allow_empty:
            print(
                "No new Open-Meteo weather records were available for "
                f"{chunk_start.isoformat()} to {chunk_end.isoformat()}."
            )
            continue

        missing_variables = [
            variable
            for variable in ["time", *WEATHER_VARIABLES]
            if variable not in hourly
        ]
        if missing_variables:
            raise RuntimeError(
                f"Open-Meteo response is missing variables: {missing_variables}"
            )

        weather_chunk = pd.DataFrame(hourly).rename(columns={"time": "timestamp"})[
            ["timestamp", *WEATHER_VARIABLES]
        ]
        if not weather_chunk.empty:
            weather_chunk["timestamp"] = pd.to_datetime(
                weather_chunk["timestamp"], utc=True
            )
            weather_chunk = weather_chunk.loc[
                (weather_chunk["timestamp"] >= chunk_start)
                & (weather_chunk["timestamp"] < chunk_end)
            ]
        if weather_chunk.empty:
            if allow_empty:
                print(
                    "No new Open-Meteo weather records were available for "
                    f"{chunk_start.isoformat()} to {chunk_end.isoformat()}."
                )
                continue
            raise RuntimeError(
                f"Open-Meteo returned no data for {params['start_date']} "
                f"to {params['end_date']}."
            )
        chunks.append(weather_chunk)

    if not chunks:
        return None

    weather = combine_weather_chunks(chunks)
    incomplete_rows = weather[WEATHER_VARIABLES].isna().any(axis=1)
    if allow_empty and incomplete_rows.any():
        first_incomplete = incomplete_rows.idxmax()
        if incomplete_rows.loc[first_incomplete:].all():
            unavailable_count = int(incomplete_rows.sum())
            weather = weather.loc[: first_incomplete - 1].copy()
            print(
                f"Open-Meteo has not published {unavailable_count} trailing "
                "hourly records yet; those records were not appended."
            )
            if weather.empty:
                return None
        else:
            raise RuntimeError(
                "Open-Meteo contains internal missing weather observations."
            )
    null_counts = weather[WEATHER_VARIABLES].isna().sum()
    unavailable = {
        column: int(count) for column, count in null_counts.items() if count > 0
    }
    if unavailable:
        raise RuntimeError(f"Open-Meteo variables contain missing values: {unavailable}")
    return weather


def fetch_open_meteo_weather(
    start_date: str | None = None,
    end_date: str | None = None,
    session=requests,
    *,
    mode: str = "historical",
    now: pd.Timestamp | None = None,
    output_path: Path = OUTPUT_PATH,
):
    if mode not in {"historical", "incremental"}:
        raise ValueError("mode must be 'historical' or 'incremental'.")
    if mode == "incremental" and (start_date is not None or end_date is not None):
        raise ValueError("start_date/end_date are supported only in historical mode.")

    output_path = Path(output_path)
    if mode == "incremental":
        latest = latest_stored_timestamp(output_path)
        start_utc = (
            get_historical_date_range().start_utc
            if latest is None
            else latest + pd.Timedelta(hours=1)
        )
        # The archive endpoint includes recent IFS data. Request completed UTC
        # days only; do not treat current-day or future forecast hours as history.
        end_utc_exclusive = completed_utc_hour(now).floor("D")
        if start_utc >= end_utc_exclusive:
            print("No new Open-Meteo weather interval is currently due.")
            return {
                "mode": mode,
                "new_rows": 0,
                "latest_timestamp": latest,
            }

        weather = fetch_weather_timestamp_range(
            start_utc,
            end_utc_exclusive,
            session=session,
            allow_empty=True,
        )
        if weather is None:
            return {
                "mode": mode,
                "new_rows": 0,
                "latest_timestamp": latest,
            }
        expected_timestamps = pd.date_range(
            start_utc,
            weather["timestamp"].max(),
            freq="h",
        )
        actual_timestamps = pd.DatetimeIndex(weather["timestamp"])
        if not actual_timestamps.equals(expected_timestamps):
            missing = expected_timestamps.difference(actual_timestamps)
            raise ValueError(
                "Open-Meteo incremental response is not continuous from the "
                f"requested start; missing={list(missing[:5])}."
            )
        result = append_csv_safely(output_path, weather)
        print(
            f"Incremental Open-Meteo ingestion: appended {result.new_rows} rows; "
            f"latest timestamp={result.latest_timestamp}."
        )
        return {
            "mode": mode,
            "new_rows": result.new_rows,
            "latest_timestamp": result.latest_timestamp,
        }

    historical_range = get_historical_date_range(start_date, end_date)
    weather = fetch_weather_timestamp_range(
        historical_range.start_utc,
        historical_range.end_utc_exclusive,
        session=session,
        allow_empty=False,
    )
    if weather is None:
        raise RuntimeError("Open-Meteo returned no data for the historical range.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    weather.to_csv(output_path, index=False)
    print(f"Saved {output_path} with shape {weather.shape}")
    return {
        "mode": mode,
        "new_rows": len(weather),
        "latest_timestamp": weather["timestamp"].max(),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch Berlin Open-Meteo weather.")
    parser.add_argument(
        "--mode",
        choices=["historical", "incremental"],
        default="historical",
    )
    parser.add_argument("--start-date", help="Inclusive start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", help="Inclusive end date (YYYY-MM-DD).")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    fetch_open_meteo_weather(
        arguments.start_date,
        arguments.end_date,
        mode=arguments.mode,
    )
