from api_ingestion.build_real_world_dataset import build_dataset
from api_ingestion.fetch_eia_data import fetch_eia_electricity_data
from api_ingestion.fetch_weather_data import fetch_weather_data


def run_api_ingestion_pipeline():
    print("Starting API ingestion pipeline...")

    print("Fetching electricity data from EIA...")
    fetch_eia_electricity_data()

    print("Fetching weather data from Open-Meteo...")
    fetch_weather_data()

    print("Building final real-world dataset...")
    final_data = build_dataset()

    print("API ingestion pipeline completed successfully.")
    print(f"Final dataset rows: {len(final_data)}")


if __name__ == "__main__":
    run_api_ingestion_pipeline()