import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import pandas as pd
from xgboost import XGBRegressor

from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

if __package__:
    from .artifact_metadata import (
        generate_dataset_version,
        get_git_commit_sha,
        write_training_manifest,
    )
else:
    from artifact_metadata import (
        generate_dataset_version,
        get_git_commit_sha,
        write_training_manifest,
    )


DATA_PATH = Path("data/features/gold_model_features.csv")
MODEL_DIR = Path("artifacts/models")
MODEL_COMPARISON_PATH = Path("data/reports/gold_model_comparison.csv")
MLFLOW_TRACKING_URI = "sqlite:///mlflow.db"
MLFLOW_EXPERIMENT_NAME = "electricity-price-forecasting-entsoe"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def evaluate_model(name, model, X_train, X_test, y_train, y_test, run_metadata):
    with mlflow.start_run(run_name=name) as run:
        model.fit(X_train, y_train)
        predictions = model.predict(X_test)

        mae = mean_absolute_error(y_test, predictions)
        rmse = mean_squared_error(y_test, predictions) ** 0.5
        r2 = r2_score(y_test, predictions)

        mlflow.log_param("model_name", name)
        mlflow.log_param("training_rows", X_train.shape[0])
        mlflow.log_param("testing_rows", X_test.shape[0])
        mlflow.log_param("features", X_train.shape[1])
        for key, value in run_metadata.items():
            if value is not None:
                mlflow.log_param(key, value)

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
            "mlflow_run_id": run.info.run_id,
        }


def main(
    data_path: Path = DATA_PATH,
    model_dir: Path = MODEL_DIR,
    comparison_path: Path = MODEL_COMPARISON_PATH,
    mlflow_tracking_uri: str = MLFLOW_TRACKING_URI,
):
    data_path = Path(data_path)
    model_dir = Path(model_dir)
    comparison_path = Path(comparison_path)

    model_dir.mkdir(parents=True, exist_ok=True)
    comparison_path.parent.mkdir(parents=True, exist_ok=True)

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)

    df = pd.read_csv(data_path)

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

    training_timestamp = datetime.now(timezone.utc).isoformat()
    dataset_version = generate_dataset_version(data_path)
    git_commit_sha = get_git_commit_sha(PROJECT_ROOT)
    source_start = df["timestamp"].min().isoformat()
    source_end = df["timestamp"].max().isoformat()

    run_metadata = {
        "dataset_version": dataset_version,
        "training_timestamp_utc": training_timestamp,
        "source_date_start": source_start,
        "source_date_end": source_end,
        "gold_rows": len(df),
        "git_commit_sha": git_commit_sha,
    }

    print("Training rows:", X_train.shape[0])
    print("Testing rows:", X_test.shape[0])
    print("Features:", X_train.shape[1])
    print("Dataset version:", dataset_version)

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
            y_test,
            run_metadata,
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

    results_df.to_csv(comparison_path, index=False)

    best_result = min(results, key=lambda x: x["rmse"])
    best_model = best_result["model"]

    model_path = model_dir / "best_gold_model.joblib"
    feature_list_path = model_dir / "gold_model_features.joblib"
    manifest_path = model_dir / "training_manifest.json"

    joblib.dump(best_model, model_path)
    joblib.dump(list(X.columns), feature_list_path)

    write_training_manifest(
        manifest_path=manifest_path,
        dataset_path=data_path,
        source_start=source_start,
        source_end=source_end,
        gold_row_count=len(df),
        feature_count=X.shape[1],
        train_row_count=X_train.shape[0],
        test_row_count=X_test.shape[0],
        selected_model=best_result["model_name"],
        mae=best_result["mae"],
        rmse=best_result["rmse"],
        r2=best_result["r2"],
        mlflow_run_id=best_result["mlflow_run_id"],
        git_commit_sha=git_commit_sha,
        model_path=model_path,
        feature_list_path=feature_list_path,
        comparison_path=comparison_path,
        training_timestamp=training_timestamp,
    )

    print("\nBest Model:")
    print(best_result["model_name"])
    print(f"Saved to {model_path}")
    print(f"Training manifest saved to {manifest_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="Train PowerFlow gold models.")
    parser.add_argument(
        "--data-path",
        type=Path,
        default=Path(os.getenv("POWERFLOW_GOLD_DATA_PATH", DATA_PATH)),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("POWERFLOW_MODEL_OUTPUT_DIR", MODEL_DIR)),
    )
    parser.add_argument(
        "--comparison-path",
        type=Path,
        default=Path(
            os.getenv("POWERFLOW_MODEL_COMPARISON_PATH", MODEL_COMPARISON_PATH)
        ),
    )
    parser.add_argument(
        "--mlflow-tracking-uri",
        default=os.getenv("POWERFLOW_MLFLOW_TRACKING_URI", MLFLOW_TRACKING_URI),
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    main(
        data_path=arguments.data_path,
        model_dir=arguments.output_dir,
        comparison_path=arguments.comparison_path,
        mlflow_tracking_uri=arguments.mlflow_tracking_uri,
    )
