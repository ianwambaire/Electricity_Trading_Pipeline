import shutil
from datetime import datetime

import pandas as pd
import requests

from config.settings import (
    BACKUP_DATA_DIR,
    DEFAULT_EIA_LENGTH,
    DEFAULT_STATE_CODE,
    EIA_API_KEY,
    EIA_ELECTRICITY_PATH,
)


def load_existing_eia_backup() -> pd.DataFrame:
    if not EIA_ELECTRICITY_PATH.exists():
        raise FileNotFoundError(
            "EIA API failed and no local EIA backup exists. "
            "Check your API key or internet connection."
        )

    print("Using existing EIA backup file.")
    data = pd.read_csv(EIA_ELECTRICITY_PATH)
    data["timestamp"] = pd.to_datetime(data["timestamp"])
    return data


def backup_file(file_path):
    BACKUP_DATA_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DATA_DIR / f"{file_path.stem}_{timestamp}{file_path.suffix}"

    shutil.copy(file_path, backup_path)

    print(f"Backup created: {backup_path}")


def fetch_eia_electricity_data(
    state_code: str = DEFAULT_STATE_CODE,
    sector_id: str = "ALL",
    length: int = DEFAULT_EIA_LENGTH,
) -> pd.DataFrame:
    try:
        if not EIA_API_KEY:
            raise ValueError("EIA_API_KEY not found in .env file.")

        url = "https://api.eia.gov/v2/electricity/retail-sales/data/"

        params = {
            "api_key": EIA_API_KEY,
            "frequency": "monthly",
            "data[]": ["price", "sales", "revenue"],
            "facets[stateid][]": state_code,
            "facets[sectorid][]": sector_id,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": length,
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        json_data = response.json()
        records = json_data["response"]["data"]

        data = pd.DataFrame(records)

        if data.empty:
            raise ValueError("EIA API returned no records.")

        data = data.rename(
            columns={
                "period": "timestamp",
                "price": "market_price",
                "sales": "electricity_sales",
                "revenue": "electricity_revenue",
                "stateid": "region",
                "sectorName": "sector",
            }
        )

        required_columns = [
            "timestamp",
            "market_price",
            "electricity_sales",
            "electricity_revenue",
            "region",
        ]

        missing_columns = [column for column in required_columns if column not in data.columns]

        if missing_columns:
            raise ValueError(f"EIA response missing expected columns: {missing_columns}")

        data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce")
        data["market_price"] = pd.to_numeric(data["market_price"], errors="coerce")
        data["electricity_sales"] = pd.to_numeric(data["electricity_sales"], errors="coerce")
        data["electricity_revenue"] = pd.to_numeric(data["electricity_revenue"], errors="coerce")

        if "sector" not in data.columns:
            data["sector"] = sector_id

        data = data.dropna(subset=["timestamp", "market_price", "electricity_sales"])
        data = data.drop_duplicates(subset=["timestamp", "region", "sector"])
        data = data.sort_values("timestamp")

        EIA_ELECTRICITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        data.to_csv(EIA_ELECTRICITY_PATH, index=False)

        backup_file(EIA_ELECTRICITY_PATH)

        print(f"EIA electricity data saved to {EIA_ELECTRICITY_PATH}")
        print(f"Rows fetched: {len(data)}")
        print(f"Date range: {data['timestamp'].min().date()} to {data['timestamp'].max().date()}")

        return data

    except Exception as error:
        print(f"EIA API ingestion failed: {error}")
        return load_existing_eia_backup()


if __name__ == "__main__":
    fetch_eia_electricity_data()