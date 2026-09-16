import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.tracking import MlflowClient
from xgboost import XGBRegressor

from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import RandomizedSearchCV, cross_val_score

if __package__:
    from .artifact_metadata import (
        generate_dataset_version,
        get_git_commit_sha,
        write_training_manifest,
    )
    from .model_evaluation import (
        build_comparison_dataframe,
        build_time_series_cv,
        chronological_holdout_split,
        select_best_result,
    )
else:
    from artifact_metadata import (
        generate_dataset_version,
        get_git_commit_sha,
        write_training_manifest,
    )
    from model_evaluation import (
        build_comparison_dataframe,
        build_time_series_cv,
        chronological_holdout_split,
        select_best_result,
    )


DATA_PATH = Path("data/features/gold_model_features.csv")
MODEL_DIR = Path("artifacts/models")
MODEL_COMPARISON_PATH = Path("data/reports/gold_model_comparison.csv")
MLFLOW_TRACKING_URI = "sqlite:///mlflow.db"
MLFLOW_EXPERIMENT_NAME = "electricity-price-forecasting-entsoe"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TARGET_COLUMN = "target_price_next_hour"
CV_SPLITS = 3
TUNING_ITERATIONS = 6
RANDOM_STATE = 42
CV_METHOD = "TimeSeriesSplit"
SELECTION_METHOD = "lowest_time_series_cv_rmse"


def build_model_configurations():
    return [
        {
            "name": "Linear Regression",
            "estimator": LinearRegression(),
            "tuning_status": "untuned_baseline",
            "search_space": None,
        },
        {
            "name": "Random Forest",
            "estimator": RandomForestRegressor(
                random_state=RANDOM_STATE,
                n_jobs=-1,
            ),
            "tuning_status": "tuned_timeseries_cv",
            "search_space": {
                "n_estimators": [100, 200, 300],
                "max_depth": [None, 8, 12],
                "min_samples_split": [2, 5],
                "min_samples_leaf": [1, 2],
                "max_features": [1.0, "sqrt"],
            },
        },
        {
            "name": "Gradient Boosting",
            "estimator": GradientBoostingRegressor(random_state=RANDOM_STATE),
            "tuning_status": "tuned_timeseries_cv",
            "search_space": {
                "n_estimators": [100, 200, 300],
                "learning_rate": [0.03, 0.05, 0.1],
                "max_depth": [2, 3, 4],
                "subsample": [0.8, 1.0],
                "min_samples_leaf": [1, 3],
            },
        },
        {
            "name": "XGBoost",
            "estimator": XGBRegressor(
                objective="reg:squarederror",
                random_state=RANDOM_STATE,
                n_jobs=-1,
            ),
            "tuning_status": "tuned_timeseries_cv",
            "search_space": {
                "n_estimators": [300, 500, 700],
                "learning_rate": [0.03, 0.05, 0.1],
                "max_depth": [4, 6, 8],
                "subsample": [0.8, 1.0],
                "colsample_bytree": [0.8, 1.0],
                "min_child_weight": [1, 3],
            },
        },
    ]


def fit_candidate(configuration, X_train, y_train, cross_validator):
    estimator = configuration["estimator"]
    search_space = configuration["search_space"]

    if search_space is None:
        cv_scores = cross_val_score(
            estimator,
            X_train,
            y_train,
            cv=cross_validator,
            scoring="neg_root_mean_squared_error",
            n_jobs=1,
        )
        estimator.fit(X_train, y_train)
        return estimator, float(-cv_scores.mean()), {}

    search = RandomizedSearchCV(
        estimator=estimator,
        param_distributions=search_space,
        n_iter=TUNING_ITERATIONS,
        scoring="neg_root_mean_squared_error",
        cv=cross_validator,
        random_state=RANDOM_STATE,
        n_jobs=1,
        refit=True,
        return_train_score=False,
    )
    search.fit(X_train, y_train)

    return search.best_estimator_, float(-search.best_score_), search.best_params_


def evaluate_model(
    configuration,
    X_train,
    X_test,
    y_train,
    y_test,
    cross_validator,
    run_metadata,
):
    name = configuration["name"]

    with mlflow.start_run(run_name=name) as run:
        model, cv_rmse, best_hyperparameters = fit_candidate(
            configuration,
            X_train,
            y_train,
            cross_validator,
        )

        # The final holdout is touched only after CV/tuning and the full training fit.
        predictions = model.predict(X_test)
        test_mae = mean_absolute_error(y_test, predictions)
        test_rmse = mean_squared_error(y_test, predictions) ** 0.5
        test_r2 = r2_score(y_test, predictions)

        mlflow.log_param("model_name", name)
        mlflow.log_param("tuning_status", configuration["tuning_status"])
        mlflow.log_param("cv_method", CV_METHOD)
        mlflow.log_param("cv_splits", CV_SPLITS)
        mlflow.log_param("cv_scoring", "RMSE")
        mlflow.log_param("training_rows", X_train.shape[0])
        mlflow.log_param("testing_rows", X_test.shape[0])
        mlflow.log_param("features", X_train.shape[1])
        mlflow.log_param(
            "best_hyperparameters",
            json.dumps(best_hyperparameters, sort_keys=True),
        )
        for key, value in run_metadata.items():
            if value is not None:
                mlflow.log_param(key, value)
        for key, value in best_hyperparameters.items():
            mlflow.log_param(f"best_{key}", value)

        mlflow.log_metric("cv_rmse", cv_rmse)
        mlflow.log_metric("test_mae", test_mae)
        mlflow.log_metric("test_rmse", test_rmse)
        mlflow.log_metric("test_r2", test_r2)
        # Preserve the existing metric names for MLflow history compatibility.
        mlflow.log_metric("mae", test_mae)
        mlflow.log_metric("rmse", test_rmse)
        mlflow.log_metric("r2", test_r2)

        mlflow.sklearn.log_model(model, name="model")

        print(f"\n{name}")
        print(f"Tuning status: {configuration['tuning_status']}")
        print(f"CV RMSE: {cv_rmse:.2f}")
        print(f"Test MAE: {test_mae:.2f}")
        print(f"Test RMSE: {test_rmse:.2f}")
        print(f"Test R² Score: {test_r2:.2f}")
        if best_hyperparameters:
            print("Best hyperparameters:", best_hyperparameters)

        return {
            "model_name": name,
            "tuning_status": configuration["tuning_status"],
            "cv_rmse": cv_rmse,
            "test_mae": test_mae,
            "test_rmse": test_rmse,
            "test_r2": test_r2,
            "best_hyperparameters": best_hyperparameters,
            "model": model,
            "mlflow_run_id": run.info.run_id,
        }


def tag_model_runs(results, selected_model):
    client = MlflowClient()
    for result in results:
        is_selected = result["model_name"] == selected_model
        client.set_tag(result["mlflow_run_id"], "selected", str(is_selected).lower())
        client.set_tag(
            result["mlflow_run_id"],
            "selection_method",
            SELECTION_METHOD,
        )


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

    data = pd.read_csv(data_path)
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    data = data.sort_values("timestamp").reset_index(drop=True)

    X_train, X_test, y_train, y_test = chronological_holdout_split(
        data,
        TARGET_COLUMN,
    )
    cross_validator = build_time_series_cv(CV_SPLITS)

    training_timestamp = datetime.now(timezone.utc).isoformat()
    dataset_version = generate_dataset_version(data_path)
    git_commit_sha = get_git_commit_sha(PROJECT_ROOT)
    source_start = data["timestamp"].min().isoformat()
    source_end = data["timestamp"].max().isoformat()

    run_metadata = {
        "dataset_version": dataset_version,
        "training_timestamp_utc": training_timestamp,
        "source_date_start": source_start,
        "source_date_end": source_end,
        "gold_rows": len(data),
        "git_commit_sha": git_commit_sha,
    }

    print("Training rows:", X_train.shape[0])
    print("Testing rows:", X_test.shape[0])
    print("Features:", X_train.shape[1])
    print("Dataset version:", dataset_version)
    print(f"Cross-validation: {CV_METHOD} ({CV_SPLITS} splits)")

    results = []
    for configuration in build_model_configurations():
        results.append(
            evaluate_model(
                configuration,
                X_train,
                X_test,
                y_train,
                y_test,
                cross_validator,
                run_metadata,
            )
        )

    best_result = select_best_result(results)
    selected_model = best_result["model_name"]
    comparison = build_comparison_dataframe(results, selected_model)
    comparison.to_csv(comparison_path, index=False)
    tag_model_runs(results, selected_model)

    model_path = model_dir / "best_gold_model.joblib"
    feature_list_path = model_dir / "gold_model_features.joblib"
    manifest_path = model_dir / "training_manifest.json"

    joblib.dump(best_result["model"], model_path)
    joblib.dump(list(X_train.columns), feature_list_path)

    write_training_manifest(
        manifest_path=manifest_path,
        dataset_path=data_path,
        source_start=source_start,
        source_end=source_end,
        gold_row_count=len(data),
        feature_count=X_train.shape[1],
        train_row_count=X_train.shape[0],
        test_row_count=X_test.shape[0],
        selected_model=selected_model,
        selection_method=SELECTION_METHOD,
        cv_method=CV_METHOD,
        cv_splits=CV_SPLITS,
        best_hyperparameters=best_result["best_hyperparameters"],
        mae=best_result["test_mae"],
        rmse=best_result["test_rmse"],
        r2=best_result["test_r2"],
        mlflow_run_id=best_result["mlflow_run_id"],
        git_commit_sha=git_commit_sha,
        model_path=model_path,
        feature_list_path=feature_list_path,
        comparison_path=comparison_path,
        training_timestamp=training_timestamp,
    )

    print("\nBest Model:")
    print(selected_model)
    print(f"Selection method: {SELECTION_METHOD}")
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
