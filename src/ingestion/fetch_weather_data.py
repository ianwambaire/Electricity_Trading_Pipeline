import argparse
from pathlib import Path

import pandas as pd
import requests

if __package__:
    from .historical_range import get_historical_date_range, iter_year_chunks
else:
    from historical_range import get_historical_date_range, iter_year_chunks


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
    combined["timestamp"] = pd.to_datetime(combined["timestamp"])
    return (
        combined.drop_duplicates(subset=["timestamp"], keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def fetch_open_meteo_weather(
    start_date: str | None = None,
    end_date: str | None = None,
    session=requests,
):
    historical_range = get_historical_date_range(start_date, end_date)
    chunks = []

    for chunk_start, chunk_end in iter_year_chunks(historical_range):
        chunk_end_inclusive = (chunk_end - pd.Timedelta(days=1)).date()
        params = {
            "latitude": 52.52,
            "longitude": 13.41,
            "start_date": chunk_start.date().isoformat(),
            "end_date": chunk_end_inclusive.isoformat(),
            "hourly": WEATHER_VARIABLES,
            "timezone": "Europe/Berlin",
        }
        print(
            "Fetching Open-Meteo historical weather: "
            f"{params['start_date']} to {params['end_date']}"
        )
        response = session.get(OPEN_METEO_URL, params=params, timeout=60)
        response.raise_for_status()
        hourly = response.json().get("hourly", {})

        missing_variables = [
            variable
            for variable in ["time", *WEATHER_VARIABLES]
            if variable not in hourly
        ]
        if missing_variables:
            raise RuntimeError(
                f"Open-Meteo response is missing variables: {missing_variables}"
            )

        weather_chunk = pd.DataFrame(hourly).rename(columns={"time": "timestamp"})
        if weather_chunk.empty:
            raise RuntimeError(
                f"Open-Meteo returned no data for {params['start_date']} "
                f"to {params['end_date']}."
            )
        chunks.append(weather_chunk)

    weather = combine_weather_chunks(chunks)
    null_counts = weather[WEATHER_VARIABLES].isna().sum()
    unavailable = {
        column: int(count) for column, count in null_counts.items() if count > 0
    }
    if unavailable:
        raise RuntimeError(f"Open-Meteo variables contain missing values: {unavailable}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    weather.to_csv(OUTPUT_PATH, index=False)
    print(f"Saved {OUTPUT_PATH} with shape {weather.shape}")


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch historical Berlin weather.")
    parser.add_argument("--start-date", help="Inclusive start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", help="Inclusive end date (YYYY-MM-DD).")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    fetch_open_meteo_weather(arguments.start_date, arguments.end_date)
