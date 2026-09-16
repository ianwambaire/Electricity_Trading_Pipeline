import shutil
from datetime import datetime

import pandas as pd
import requests

from config.settings import (
    BACKUP_DATA_DIR,
    DEFAULT_END_DATE,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_START_DATE,
    WEATHER_DATA_PATH,
)


def load_existing_weather_backup() -> pd.DataFrame:
    if not WEATHER_DATA_PATH.exists():
        raise FileNotFoundError(
            "Weather API failed and no local weather backup exists. "
            "Check your internet connection."
        )

    print("Using existing weather backup file.")
    data = pd.read_csv(WEATHER_DATA_PATH)
    data["date"] = pd.to_datetime(data["date"])
    return data


def backup_file(file_path):
    BACKUP_DATA_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DATA_DIR / f"{file_path.stem}_{timestamp}{file_path.suffix}"

    shutil.copy(file_path, backup_path)

    print(f"Backup created: {backup_path}")


def fetch_weather_data(
    latitude: float = DEFAULT_LATITUDE,
    longitude: float = DEFAULT_LONGITUDE,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
) -> pd.DataFrame:
    try:
        url = "https://archive-api.open-meteo.com/v1/archive"

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "daily": [
                "temperature_2m_mean",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "wind_speed_10m_max",
            ],
            "timezone": "auto",
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        json_data = response.json()
        daily_data = json_data["daily"]

        data = pd.DataFrame(daily_data)

        data = data.rename(
            columns={
                "time": "date",
                "temperature_2m_mean": "avg_temperature",
                "temperature_2m_max": "max_temperature",
                "temperature_2m_min": "min_temperature",
                "precipitation_sum": "precipitation",
                "wind_speed_10m_max": "wind_speed",
            }
        )

        data["date"] = pd.to_datetime(data["date"])

        WEATHER_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        data.to_csv(WEATHER_DATA_PATH, index=False)

        backup_file(WEATHER_DATA_PATH)

        print(f"Weather data saved to {WEATHER_DATA_PATH}")
        print(f"Rows fetched: {len(data)}")

        return data

    except Exception as error:
        print(f"Weather API ingestion failed: {error}")
        return load_existing_weather_backup()


if __name__ == "__main__":
    fetch_weather_data()