import sqlite3
import pandas as pd
import joblib
from pathlib import Path
from datetime import datetime


DATABASE_PATH = Path("database/electricity_trading.db")
MODEL_PATH = Path("models/electricity_price_model.pkl")


def load_latest_data():
    connection = sqlite3.connect(DATABASE_PATH)

    query = """
    SELECT *
    FROM clean_market_data
    ORDER BY timestamp DESC
    LIMIT 1
    """

    data = pd.read_sql_query(query, connection)
    connection.close()

    return data


def prepare_prediction_features(data: pd.DataFrame):
    data = data.copy()

    data["day_of_week_encoded"] = pd.factorize(data["day_of_week"])[0]
    data["energy_source_encoded"] = pd.factorize(data["energy_source"])[0]

    feature_columns = [
        "demand_mw",
        "supply_mw",
        "weather_temperature",
        "hour",
        "day",
        "month",
        "supply_demand_gap",
        "day_of_week_encoded",
        "energy_source_encoded"
    ]

    return data[feature_columns]


def predict_price(features):
    model = joblib.load(MODEL_PATH)

    prediction = model.predict(features)

    return prediction[0]


def store_prediction(predicted_price):
    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO predictions
        (
            prediction_time,
            predicted_price,
            model_version
        )
        VALUES (?, ?, ?)
        """,
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            predicted_price,
            "v1.0"
        )
    )

    connection.commit()
    connection.close()


def main():
    print("Loading latest market data...")
    data = load_latest_data()

    print("Preparing prediction features...")
    features = prepare_prediction_features(data)

    print("Generating prediction...")
    predicted_price = predict_price(features)

    print(f"Predicted Electricity Price: {predicted_price:.2f}")

    store_prediction(predicted_price)

    print("Prediction stored successfully.")


if __name__ == "__main__":
    main()