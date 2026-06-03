import os
from xgboost import XGBRegressor
import pandas as pd
import joblib
import mlflow
import mlflow.sklearn

from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import LinearRegression


DATA_PATH = "data/features/gold_model_features.csv"
MODEL_DIR = "artifacts/models"

os.makedirs(MODEL_DIR, exist_ok=True)

mlflow.set_tracking_uri("sqlite:///mlflow.db")
mlflow.set_experiment("electricity-price-forecasting-entsoe")


def evaluate_model(name, model, X_train, X_test, y_train, y_test):
    with mlflow.start_run(run_name=name):
        model.fit(X_train, y_train)
        predictions = model.predict(X_test)

        mae = mean_absolute_error(y_test, predictions)
        rmse = mean_squared_error(y_test, predictions) ** 0.5
        r2 = r2_score(y_test, predictions)

        mlflow.log_param("model_name", name)
        mlflow.log_param("training_rows", X_train.shape[0])
        mlflow.log_param("testing_rows", X_test.shape[0])
        mlflow.log_param("features", X_train.shape[1])

        mlflow.log_metric("mae", mae)
        mlflow.log_metric("rmse", rmse)
        mlflow.log_metric("r2", r2)

        mlflow.sklearn.log_model(model, name="model")

        print(f"\n{name}")
        print(f"MAE: {mae:.2f}")
        print(f"RMSE: {rmse:.2f}")
        print(f"R² Score: {r2:.2f}")

        return {
            "model_name": name,
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "model": model,
        }


def main():
    df = pd.read_csv(DATA_PATH)

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp")

    target = "target_price_next_hour"

    X = df.drop(columns=["timestamp", target])
    y = df[target]

    split_index = int(len(df) * 0.8)

    X_train = X.iloc[:split_index]
    X_test = X.iloc[split_index:]
    y_train = y.iloc[:split_index]
    y_test = y.iloc[split_index:]

    print("Training rows:", X_train.shape[0])
    print("Testing rows:", X_test.shape[0])
    print("Features:", X_train.shape[1])

    models = [
        ("Linear Regression", LinearRegression()),
        ("Random Forest", RandomForestRegressor(
            n_estimators=200,
            random_state=42,
            n_jobs=-1
        )),
        ("Gradient Boosting", GradientBoostingRegressor(
            random_state=42
        )),
        ("XGBoost", XGBRegressor(
            n_estimators=500,
            learning_rate=0.05,
            max_depth=6,
            subsample=0.8,
            colsample_bytree=0.8,
            objective="reg:squarederror",
            random_state=42,
            n_jobs=-1
        )),
    ]

    results = []

    for name, model in models:
        result = evaluate_model(
            name,
            model,
            X_train,
            X_test,
            y_train,
            y_test
        )
        results.append(result)

    results_df = pd.DataFrame([
        {
            "model_name": r["model_name"],
            "mae": r["mae"],
            "rmse": r["rmse"],
            "r2": r["r2"],
        }
        for r in results
    ])

    os.makedirs("data/reports", exist_ok=True)
    results_df.to_csv("data/reports/gold_model_comparison.csv", index=False)

    best_result = min(results, key=lambda x: x["rmse"])
    best_model = best_result["model"]

    joblib.dump(best_model, f"{MODEL_DIR}/best_gold_model.joblib")
    joblib.dump(list(X.columns), f"{MODEL_DIR}/gold_model_features.joblib")

    print("\nBest Model:")
    print(best_result["model_name"])
    print(f"Saved to {MODEL_DIR}/best_gold_model.joblib")


if __name__ == "__main__":
    main()