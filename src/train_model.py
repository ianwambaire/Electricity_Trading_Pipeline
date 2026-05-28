import sqlite3
import pandas as pd
import joblib
from pathlib import Path
from datetime import datetime

from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


DATABASE_PATH = Path("database/electricity_trading.db")
MODEL_PATH = Path("models/electricity_price_model.pkl")


def load_data():
    connection = sqlite3.connect(DATABASE_PATH)

    query = """
    SELECT *
    FROM clean_market_data
    """

    data = pd.read_sql_query(query, connection)
    connection.close()

    return data


def prepare_features(data: pd.DataFrame):
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

    X = data[feature_columns]

    y = data["market_price"]

    return X, y


def train_model(X, y):
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42
    )

    model = RandomForestRegressor(
        n_estimators=100,
        random_state=42
    )

    model.fit(X_train, y_train)

    predictions = model.predict(X_test)

    mae = mean_absolute_error(y_test, predictions)

    rmse = mean_squared_error(y_test, predictions) ** 0.5

    r2 = r2_score(y_test, predictions)

    return model, mae, rmse, r2


def save_model(model):
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump(model, MODEL_PATH)

    print(f"Model saved to {MODEL_PATH}")


def register_model(mae, rmse, r2):
    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO model_registry
        (
            model_name,
            version,
            training_date,
            rmse,
            mae,
            r2_score
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "Electricity Price Prediction Model",
            "v1.0",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            rmse,
            mae,
            r2
        )
    )

    connection.commit()
    connection.close()


def main():
    print("Loading data...")
    data = load_data()

    print("Preparing features...")
    X, y = prepare_features(data)

    print("Training model...")
    model, mae, rmse, r2 = train_model(X, y)

    print(f"MAE: {mae:.2f}")
    print(f"RMSE: {rmse:.2f}")
    print(f"R² Score: {r2:.2f}")

    save_model(model)

    register_model(mae, rmse, r2)

    print("Model training completed successfully.")


if __name__ == "__main__":
    main()