import sqlite3
from datetime import datetime
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from xgboost import XGBRegressor


DATABASE_PATH = Path("database/electricity_trading.db")
MODEL_PATH = Path("models/electricity_price_model.pkl")
FEATURES_PATH = Path("models/model_features.pkl")
MODEL_METADATA_PATH = Path("models/model_metadata.pkl")

MODEL_COMPARISON_PATH = Path("data/reports/model_comparison.csv")
FEATURE_IMPORTANCE_PATH = Path("data/reports/feature_importance.csv")

MLFLOW_TRACKING_URI = "http://127.0.0.1:5000"
MLFLOW_EXPERIMENT_NAME = "Electricity Price Forecasting"


FEATURE_COLUMNS = [
    "demand_mw",
    "supply_mw",
    "weather_temperature",
    "hour",
    "day",
    "month",
    "supply_demand_gap",
    "day_of_week_encoded",
    "energy_source_encoded",
]


def load_data() -> pd.DataFrame:
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

    data["timestamp"] = pd.to_datetime(data["timestamp"])
    data["day_of_week_encoded"] = pd.factorize(data["day_of_week"])[0]
    data["energy_source_encoded"] = pd.factorize(data["energy_source"])[0]

    data = data.dropna(subset=FEATURE_COLUMNS + ["market_price"])

    X = data[FEATURE_COLUMNS]
    y = data["market_price"]

    return X, y


def evaluate_model(model, X_test, y_test):
    predictions = model.predict(X_test)

    mae = mean_absolute_error(y_test, predictions)
    rmse = mean_squared_error(y_test, predictions) ** 0.5
    r2 = r2_score(y_test, predictions)

    return mae, rmse, r2


def build_feature_importance(model, model_name: str):
    if not hasattr(model, "feature_importances_"):
        return pd.DataFrame()

    importance_df = pd.DataFrame(
        {
            "feature": FEATURE_COLUMNS,
            "importance": model.feature_importances_,
            "model_name": model_name,
        }
    )

    importance_df = importance_df.sort_values("importance", ascending=False)

    FEATURE_IMPORTANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    importance_df.to_csv(FEATURE_IMPORTANCE_PATH, index=False)

    return importance_df


def train_and_log_model(model_name, model, params, X_train, X_test, y_train, y_test):
    with mlflow.start_run(run_name=model_name) as run:
        print(f"\nTraining {model_name}...")

        model.fit(X_train, y_train)

        mae, rmse, r2 = evaluate_model(model, X_test, y_test)

        mlflow.log_param("model_name", model_name)
        mlflow.log_param("dataset_rows", len(X_train) + len(X_test))
        mlflow.log_param("training_rows", len(X_train))
        mlflow.log_param("test_rows", len(X_test))

        for param_name, param_value in params.items():
            mlflow.log_param(param_name, param_value)

        mlflow.log_metric("mae", mae)
        mlflow.log_metric("rmse", rmse)
        mlflow.log_metric("r2_score", r2)

        mlflow.sklearn.log_model(
            sk_model=model,
            artifact_path="model",
        )

        print(f"{model_name} MAE: {mae:.2f}")
        print(f"{model_name} RMSE: {rmse:.2f}")
        print(f"{model_name} R² Score: {r2:.2f}")

        return {
            "run_id": run.info.run_id,
            "model_name": model_name,
            "model": model,
            "mae": mae,
            "rmse": rmse,
            "r2_score": r2,
            "params": params,
        }


def train_models(X, y):
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
    )

    rf_params = {
        "n_estimators": 200,
        "max_depth": 8,
        "random_state": 42,
    }

    xgb_params = {
        "n_estimators": 300,
        "learning_rate": 0.05,
        "max_depth": 4,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "random_state": 42,
        "objective": "reg:squarederror",
    }

    random_forest = RandomForestRegressor(**rf_params)
    xgboost = XGBRegressor(**xgb_params)

    results = []

    results.append(
        train_and_log_model(
            "Random Forest",
            random_forest,
            rf_params,
            X_train,
            X_test,
            y_train,
            y_test,
        )
    )

    results.append(
        train_and_log_model(
            "XGBoost",
            xgboost,
            xgb_params,
            X_train,
            X_test,
            y_train,
            y_test,
        )
    )

    best_result = min(results, key=lambda item: item["rmse"])

    return best_result, results


def save_model(best_result):
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump(best_result["model"], MODEL_PATH)
    joblib.dump(FEATURE_COLUMNS, FEATURES_PATH)

    metadata = {
        "model_name": best_result["model_name"],
        "version": "v3.0-mlflow",
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mae": best_result["mae"],
        "rmse": best_result["rmse"],
        "r2_score": best_result["r2_score"],
        "features": FEATURE_COLUMNS,
        "mlflow_run_id": best_result["run_id"],
    }

    joblib.dump(metadata, MODEL_METADATA_PATH)

    print(f"\nBest model saved to {MODEL_PATH}")
    print(f"Selected model: {best_result['model_name']}")


def register_model(best_result):
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
            best_result["model_name"],
            "v3.0-mlflow",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            best_result["rmse"],
            best_result["mae"],
            best_result["r2_score"],
        ),
    )

    connection.commit()
    connection.close()


def save_model_comparison(results):
    comparison_data = []

    for result in results:
        comparison_data.append(
            {
                "run_id": result["run_id"],
                "model_name": result["model_name"],
                "mae": result["mae"],
                "rmse": result["rmse"],
                "r2_score": result["r2_score"],
                "training_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    comparison_df = pd.DataFrame(comparison_data)

    MODEL_COMPARISON_PATH.parent.mkdir(parents=True, exist_ok=True)
    comparison_df.to_csv(MODEL_COMPARISON_PATH, index=False)

    print(f"Model comparison saved to {MODEL_COMPARISON_PATH}")

    return comparison_df


def log_best_model_summary(best_result, comparison_df, feature_importance_df):
    with mlflow.start_run(run_name="Best Model Selection"):
        mlflow.log_param("selected_model", best_result["model_name"])
        mlflow.log_param("selected_model_run_id", best_result["run_id"])
        mlflow.log_param("model_version", "v3.0-mlflow")

        mlflow.log_metric("best_mae", best_result["mae"])
        mlflow.log_metric("best_rmse", best_result["rmse"])
        mlflow.log_metric("best_r2_score", best_result["r2_score"])

        if MODEL_COMPARISON_PATH.exists():
            mlflow.log_artifact(str(MODEL_COMPARISON_PATH))

        if FEATURE_IMPORTANCE_PATH.exists() and not feature_importance_df.empty:
            mlflow.log_artifact(str(FEATURE_IMPORTANCE_PATH))


def main():
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)

    print("Loading data...")
    data = load_data()

    print("Preparing ML features...")
    X, y = prepare_features(data)

    if len(X) < 10:
        raise ValueError("Not enough data to train models. Add more records first.")

    print("Training and comparing models with MLflow tracking...")
    best_result, results = train_models(X, y)

    save_model(best_result)
    register_model(best_result)
    comparison_df = save_model_comparison(results)

    feature_importance_df = build_feature_importance(
        best_result["model"],
        best_result["model_name"],
    )

    log_best_model_summary(best_result, comparison_df, feature_importance_df)

    print("\nMLflow model training completed successfully.")
    print(f"Best model: {best_result['model_name']}")
    print(f"Best RMSE: {best_result['rmse']:.2f}")
    print(f"Best MLflow run ID: {best_result['run_id']}")


if __name__ == "__main__":
    main()