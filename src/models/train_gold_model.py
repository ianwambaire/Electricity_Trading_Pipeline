import os
import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import GradientBoostingRegressor


DATA_PATH = "data/features/gold_model_features.csv"
MODEL_DIR = "artifacts/models"

os.makedirs(MODEL_DIR, exist_ok=True)


def evaluate_model(name, model, X_train, X_test, y_train, y_test):
    model.fit(X_train, y_train)

    predictions = model.predict(X_test)

    mae = mean_absolute_error(y_test, predictions)
    rmse = mean_squared_error(y_test, predictions) ** 0.5
    r2 = r2_score(y_test, predictions)

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

    drop_columns = [
        "timestamp",
        target,
    ]

    X = df.drop(columns=drop_columns)
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