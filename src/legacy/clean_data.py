import pandas as pd
from pathlib import Path


PROCESSED_DATA_PATH = Path("data/processed/clean_electricity_market_data.csv")


def clean_data(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()

    data.columns = data.columns.str.strip().str.lower()

    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce")

    numeric_columns = [
        "market_price",
        "demand_mw",
        "supply_mw",
        "weather_temperature"
    ]

    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    data = data.drop_duplicates()

    data = data.dropna(subset=["timestamp", "market_price", "demand_mw", "supply_mw"])

    data["region"] = data["region"].fillna("Unknown")
    data["energy_source"] = data["energy_source"].fillna("Unknown")

    data = data[data["market_price"] >= 0]
    data = data[data["demand_mw"] >= 0]
    data = data[data["supply_mw"] >= 0]

    data["hour"] = data["timestamp"].dt.hour
    data["day"] = data["timestamp"].dt.day
    data["month"] = data["timestamp"].dt.month
    data["day_of_week"] = data["timestamp"].dt.day_name()

    data["supply_demand_gap"] = data["supply_mw"] - data["demand_mw"]

    return data


def save_clean_data(data: pd.DataFrame):
    PROCESSED_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(PROCESSED_DATA_PATH, index=False)
    print(f"Clean data saved to {PROCESSED_DATA_PATH}")


if __name__ == "__main__":
    from ingest_data import ingest_data

    raw_data = ingest_data()
    clean_df = clean_data(raw_data)
    save_clean_data(clean_df)

    print(clean_df.head())