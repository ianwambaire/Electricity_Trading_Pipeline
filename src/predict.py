import sqlite3
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd


DATABASE_PATH = Path("database/electricity_trading.db")
MODEL_PATH = Path("models/electricity_price_model.pkl")
FEATURES_PATH = Path("models/model_features.pkl")
MODEL_METADATA_PATH = Path("models/model_metadata.pkl")


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

    feature_columns = joblib.load(FEATURES_PATH)

    return data[feature_columns]


def predict_price(features):
    model = joblib.load(MODEL_PATH)

    prediction = model.predict(features)

    return prediction[0]


def load_model_metadata():
    if MODEL_METADATA_PATH.exists():
        return joblib.load(MODEL_METADATA_PATH)

    return {
        "model_name": "Unknown",
        "version": "v2.0",
    }


def store_prediction(predicted_price, model_version):
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
            float(predicted_price),
            model_version,
        ),
    )

    connection.commit()
    connection.close()


def main():
    print("Loading latest market data...")
    data = load_latest_data()

    if data.empty:
        raise ValueError("No market data available for prediction.")

    print("Preparing prediction features...")
    features = prepare_prediction_features(data)

    print("Generating prediction...")
    predicted_price = predict_price(features)

    metadata = load_model_metadata()
    model_version = metadata.get("version", "v2.0")
    model_name = metadata.get("model_name", "Unknown")

    print(f"Selected Model: {model_name}")
    print(f"Model Version: {model_version}")
    print(f"Predicted Electricity Price: {predicted_price:.2f}")

    store_prediction(predicted_price, model_version)

    print("Prediction stored successfully.")


if __name__ == "__main__":
    main()