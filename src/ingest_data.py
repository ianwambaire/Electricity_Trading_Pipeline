import pandas as pd
from pathlib import Path


RAW_DATA_PATH = Path("data/raw/electricity_market_data.csv")


def ingest_data():
    if not RAW_DATA_PATH.exists():
        raise FileNotFoundError(f"Raw data file not found: {RAW_DATA_PATH}")

    data = pd.read_csv(RAW_DATA_PATH)
    print(f"Data ingested successfully. Rows loaded: {len(data)}")

    return data


if __name__ == "__main__":
    df = ingest_data()
    print(df.head())