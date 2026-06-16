import os
import requests
import pandas as pd


RAW_WEATHER_DIR = "data/raw/weather"
OUTPUT_PATH = f"{RAW_WEATHER_DIR}/open_meteo_weather.csv"

os.makedirs(RAW_WEATHER_DIR, exist_ok=True)


def fetch_open_meteo_weather():
    url = "https://archive-api.open-meteo.com/v1/archive"

    params = {
        "latitude": 52.52,
        "longitude": 13.41,
        "start_date": "2022-01-01",
        "end_date": "2024-12-31",
        "hourly": [
            "temperature_2m",
            "relative_humidity_2m",
            "wind_speed_10m",
            "cloud_cover",
            "shortwave_radiation",
        ],
        "timezone": "Europe/Berlin",
    }

    print("Fetching Open-Meteo historical weather data...")

    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()

    data = response.json()

    weather_df = pd.DataFrame(data["hourly"])
    weather_df = weather_df.rename(columns={"time": "timestamp"})

    weather_df["timestamp"] = pd.to_datetime(weather_df["timestamp"])
    weather_df.to_csv(OUTPUT_PATH, index=False)

    print("Weather data saved.")
    print(weather_df.head())
    print(weather_df.shape)
    print(weather_df.columns)


if __name__ == "__main__":
    fetch_open_meteo_weather()