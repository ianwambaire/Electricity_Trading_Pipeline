import pandas as pd

from config.settings import (
    EIA_ELECTRICITY_PATH,
    FINAL_REAL_WORLD_DATASET_PATH,
    PIPELINE_INPUT_PATH,
    WEATHER_DATA_PATH,
)


def load_eia_data() -> pd.DataFrame:
    if not EIA_ELECTRICITY_PATH.exists():
        raise FileNotFoundError("EIA data not found. Run fetch_eia_data.py first.")

    data = pd.read_csv(EIA_ELECTRICITY_PATH)
    data["timestamp"] = pd.to_datetime(data["timestamp"])

    return data


def load_weather_data() -> pd.DataFrame:
    if not WEATHER_DATA_PATH.exists():
        raise FileNotFoundError("Weather data not found. Run fetch_weather_data.py first.")

    data = pd.read_csv(WEATHER_DATA_PATH)
    data["date"] = pd.to_datetime(data["date"])

    return data


def aggregate_weather_monthly(weather_data: pd.DataFrame) -> pd.DataFrame:
    weather_data = weather_data.copy()

    weather_data["month_start"] = weather_data["date"].dt.to_period("M").dt.to_timestamp()

    monthly_weather = (
        weather_data.groupby("month_start")
        .agg(
            avg_temperature=("avg_temperature", "mean"),
            max_temperature=("max_temperature", "mean"),
            min_temperature=("min_temperature", "mean"),
            precipitation=("precipitation", "sum"),
            wind_speed=("wind_speed", "mean"),
        )
        .reset_index()
    )

    return monthly_weather


def add_time_features(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()

    data["hour"] = data["timestamp"].dt.hour
    data["day"] = data["timestamp"].dt.day
    data["month"] = data["timestamp"].dt.month
    data["year"] = data["timestamp"].dt.year
    data["day_of_week"] = data["timestamp"].dt.day_name()

    return data


def add_ml_features(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    data = data.sort_values("timestamp")

    data["price_lag_1"] = data["market_price"].shift(1)
    data["price_lag_3"] = data["market_price"].shift(3)
    data["sales_lag_1"] = data["electricity_sales"].shift(1)

    data["price_rolling_3_month_avg"] = data["market_price"].rolling(window=3).mean()
    data["sales_rolling_3_month_avg"] = data["electricity_sales"].rolling(window=3).mean()

    data["supply_demand_gap"] = data["supply_mw"] - data["demand_mw"]

    return data


def fill_missing_weather_values(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()

    weather_columns = [
        "weather_temperature",
        "avg_temperature",
        "max_temperature",
        "min_temperature",
        "wind_speed",
    ]

    for column in weather_columns:
        if column in data.columns:
            data[column] = data[column].interpolate()
            data[column] = data[column].bfill()
            data[column] = data[column].ffill()

    if "precipitation" in data.columns:
        data["precipitation"] = data["precipitation"].fillna(0)

    return data


def build_dataset() -> pd.DataFrame:
    electricity_data = load_eia_data()
    weather_data = load_weather_data()

    monthly_weather = aggregate_weather_monthly(weather_data)

    electricity_data["month_start"] = electricity_data["timestamp"].dt.to_period("M").dt.to_timestamp()

    merged_data = electricity_data.merge(
        monthly_weather,
        on="month_start",
        how="left",
    )

    final_data = merged_data.copy()

    final_data["timestamp"] = final_data["month_start"]

    final_data["demand_mw"] = final_data["electricity_sales"]
    final_data["supply_mw"] = final_data["electricity_sales"] * 1.05
    final_data["weather_temperature"] = final_data["avg_temperature"]

    final_data = fill_missing_weather_values(final_data)

    final_data["energy_source"] = "Mixed"

    final_data = add_time_features(final_data)
    final_data = add_ml_features(final_data)

    final_data = final_data[
        [
            "timestamp",
            "market_price",
            "demand_mw",
            "supply_mw",
            "weather_temperature",
            "region",
            "energy_source",
            "hour",
            "day",
            "month",
            "year",
            "day_of_week",
            "supply_demand_gap",
            "electricity_sales",
            "electricity_revenue",
            "avg_temperature",
            "max_temperature",
            "min_temperature",
            "precipitation",
            "wind_speed",
            "price_lag_1",
            "price_lag_3",
            "sales_lag_1",
            "price_rolling_3_month_avg",
            "sales_rolling_3_month_avg",
        ]
    ]

    final_data = final_data.dropna(subset=["timestamp", "market_price", "demand_mw"])
    final_data = final_data.sort_values("timestamp")

    FINAL_REAL_WORLD_DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    final_data.to_csv(FINAL_REAL_WORLD_DATASET_PATH, index=False)

    PIPELINE_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    pipeline_data = final_data[
        [
            "timestamp",
            "market_price",
            "demand_mw",
            "supply_mw",
            "weather_temperature",
            "region",
            "energy_source",
        ]
    ]

    pipeline_data.to_csv(PIPELINE_INPUT_PATH, index=False)

    print(f"Final real-world dataset saved to {FINAL_REAL_WORLD_DATASET_PATH}")
    print(f"Pipeline-compatible dataset saved to {PIPELINE_INPUT_PATH}")
    print(f"Rows: {len(final_data)}")

    return final_data


if __name__ == "__main__":
    build_dataset()