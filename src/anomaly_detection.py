import sqlite3
from pathlib import Path

import pandas as pd
from sklearn.ensemble import IsolationForest


DATABASE_PATH = Path("database/electricity_trading.db")
OUTPUT_PATH = Path("data/reports/price_anomalies.csv")


def load_market_data():
    connection = sqlite3.connect(DATABASE_PATH)

    query = """
    SELECT *
    FROM clean_market_data
    """

    data = pd.read_sql_query(query, connection)
    connection.close()

    return data


def detect_price_anomalies(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()

    data["timestamp"] = pd.to_datetime(data["timestamp"])

    features = data[
        [
            "market_price",
            "demand_mw",
            "supply_mw",
            "weather_temperature",
            "supply_demand_gap",
        ]
    ].dropna()

    model = IsolationForest(
        contamination=0.05,
        random_state=42,
    )

    anomaly_labels = model.fit_predict(features)

    result = data.loc[features.index].copy()
    result["anomaly_score"] = model.decision_function(features)
    result["is_anomaly"] = anomaly_labels

    anomalies = result[result["is_anomaly"] == -1]

    return anomalies


def main():
    print("Loading market data...")
    data = load_market_data()

    if data.empty:
        raise ValueError("No market data available for anomaly detection.")

    print("Detecting price anomalies...")
    anomalies = detect_price_anomalies(data)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    anomalies.to_csv(OUTPUT_PATH, index=False)

    print(f"Anomalies detected: {len(anomalies)}")
    print(f"Anomaly report saved to {OUTPUT_PATH}")

    if not anomalies.empty:
        print(anomalies[["timestamp", "market_price", "demand_mw", "supply_mw", "anomaly_score"]].head())


if __name__ == "__main__":
    main()