import pandas as pd


def build_gold_dataset():
    df = pd.read_csv("data/processed/silver_electricity_market_data.csv")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp")
    # Germany shut down its final nuclear plants in April 2023.
# Missing nuclear generation values are treated as 0 MW.
    df["nuclear_mw"] = df["nuclear_mw"].fillna(0)

    # Time-based features
    df["hour"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["month"] = df["timestamp"].dt.month
    df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)

    # Price lag features
    df["price_lag_1h"] = df["price_eur_mwh"].shift(1)
    df["price_lag_24h"] = df["price_eur_mwh"].shift(24)
    df["price_lag_168h"] = df["price_eur_mwh"].shift(168)

    # Load lag features
    df["load_lag_1h"] = df["load_mw"].shift(1)
    df["load_lag_24h"] = df["load_mw"].shift(24)

    # Rolling features
    df["price_rolling_mean_24h"] = df["price_eur_mwh"].rolling(window=24).mean()
    df["price_rolling_std_24h"] = df["price_eur_mwh"].rolling(window=24).std()
    df["load_rolling_mean_24h"] = df["load_mw"].rolling(window=24).mean()

    # Renewable generation features
    df["renewable_generation_mw"] = (
        df["solar_mw"] + df["wind_total_mw"] + df["biomass_mw"] + df["hydro_mw"]
    )

    df["renewable_share"] = df["renewable_generation_mw"] / (
        df["renewable_generation_mw"]
        + df["lignite_mw"]
        + df["gas_mw"]
        + df["hard_coal_mw"]
        + df["nuclear_mw"]
    )

    # Target: next hour electricity price
    df["target_price_next_hour"] = df["price_eur_mwh"].shift(-1)

    # Remove rows created by lag/rolling/target shifts
    df = df.dropna()

    df.to_csv("data/features/gold_model_features.csv", index=False)

    print("Gold dataset created.")
    print(df.head())
    print(df.shape)
    print(df.columns)


if __name__ == "__main__":
    build_gold_dataset()