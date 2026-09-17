import argparse
import os
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import pandas as pd

if __package__:
    from .artifact_metadata import generate_dataset_version, get_git_commit_sha
    from .final_evaluation import (
        FINAL_FEATURES,
        FINAL_FEATURE_GROUP,
        FINAL_MODEL_NAME,
        build_final_metrics,
        build_final_regime_performance,
        ensure_release_not_completed,
        evaluate_final_baselines,
        final_chronological_split,
        fit_and_predict_final_model,
        validate_frozen_features,
        write_final_release_manifest,
    )
else:
    from artifact_metadata import generate_dataset_version, get_git_commit_sha
    from final_evaluation import (
        FINAL_FEATURES,
        FINAL_FEATURE_GROUP,
        FINAL_MODEL_NAME,
        build_final_metrics,
        build_final_regime_performance,
        ensure_release_not_completed,
        evaluate_final_baselines,
        final_chronological_split,
        fit_and_predict_final_model,
        validate_frozen_features,
        write_final_release_manifest,
    )


DATA_PATH = Path("data/features/gold_model_features.csv")
MODEL_PATH = Path("artifacts/models/final_gold_model.joblib")
FEATURE_PATH = Path("artifacts/models/final_gold_model_features.joblib")
MANIFEST_PATH = Path("artifacts/models/final_model_release_manifest.json")
METRICS_PATH = Path("data/reports/final_holdout_metrics.csv")
REGIME_PATH = Path("data/reports/final_holdout_regime_performance.csv")
BASELINES_PATH = Path("data/reports/final_holdout_baselines.csv")
MLFLOW_TRACKING_URI = "sqlite:///mlflow.db"
MLFLOW_EXPERIMENT_NAME = "electricity-price-forecasting-entsoe"
MLFLOW_RUN_NAME = "PowerFlow Final 2025 Holdout Evaluation"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main(
    data_path: Path = DATA_PATH,
    model_path: Path = MODEL_PATH,
    feature_path: Path = FEATURE_PATH,
    manifest_path: Path = MANIFEST_PATH,
    metrics_path: Path = METRICS_PATH,
    regime_path: Path = REGIME_PATH,
    baselines_path: Path = BASELINES_PATH,
    mlflow_tracking_uri: str = MLFLOW_TRACKING_URI,
) -> None:
    ensure_release_not_completed(manifest_path)
    data_path = Path(data_path)
    data = pd.read_csv(data_path)
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    data = data.sort_values("timestamp").reset_index(drop=True)
    validate_frozen_features(data)
    split = final_chronological_split(data)

    model, predictions = fit_and_predict_final_model(split)
    baselines = evaluate_final_baselines(data, split)
    metrics = build_final_metrics(split, predictions, baselines)
    regimes = build_final_regime_performance(split, predictions)

    for path in (
        model_path,
        feature_path,
        manifest_path,
        metrics_path,
        regime_path,
        baselines_path,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    joblib.dump(list(FINAL_FEATURES), feature_path)
    metrics.to_csv(metrics_path, index=False)
    regimes.to_csv(regime_path, index=False)
    baselines.to_csv(baselines_path, index=False)

    dataset_version = generate_dataset_version(data_path)
    git_commit_sha = get_git_commit_sha(PROJECT_ROOT)
    metric_row = metrics.iloc[0]
    mlflow.set_tracking_uri(mlflow_tracking_uri)
    mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
    with mlflow.start_run(run_name=MLFLOW_RUN_NAME) as run:
        mlflow.set_tag("evaluation_type", "final_2025_holdout_evaluation")
        mlflow.set_tag("final_holdout_used", "true")
        mlflow.set_tag("frozen_model_design", "true")
        mlflow.log_param("model_name", FINAL_MODEL_NAME)
        mlflow.log_param("feature_group", FINAL_FEATURE_GROUP)
        mlflow.log_param("feature_count", len(FINAL_FEATURES))
        mlflow.log_param("dataset_version", dataset_version)
        mlflow.log_param("git_commit_sha", git_commit_sha or "unavailable")
        mlflow.log_param("training_rows", len(split.training_data))
        mlflow.log_param("holdout_rows", len(split.holdout_data))
        mlflow.log_param("holdout_start", split.holdout_target_times.min().isoformat())
        mlflow.log_param("holdout_end", split.holdout_target_times.max().isoformat())
        mlflow.log_metric("final_holdout_mae", metric_row["mae"])
        mlflow.log_metric("final_holdout_rmse", metric_row["rmse"])
        mlflow.log_metric("final_holdout_r2", metric_row["r2"])
        mlflow.log_metric(
            "rmse_improvement_vs_persistence_pct",
            metric_row["rmse_improvement_vs_persistence_pct"],
        )
        mlflow.log_metric(
            "rmse_improvement_vs_best_seasonal_pct",
            metric_row["rmse_improvement_vs_best_seasonal_pct"],
        )
        for baseline in baselines.to_dict(orient="records"):
            prefix = baseline["baseline_name"].lower().replace(" ", "_")
            mlflow.log_metric(f"{prefix}_mae", baseline["mae"])
            mlflow.log_metric(f"{prefix}_rmse", baseline["rmse"])
            mlflow.log_metric(f"{prefix}_r2", baseline["r2"])
        for regime in regimes.to_dict(orient="records"):
            prefix = regime["price_regime"].lower()
            mlflow.log_metric(f"{prefix}_observations", regime["observation_count"])
            if pd.notna(regime["mae"]):
                mlflow.log_metric(f"{prefix}_mae", regime["mae"])
                mlflow.log_metric(f"{prefix}_rmse", regime["rmse"])
                mlflow.log_metric(f"{prefix}_signed_bias", regime["mean_signed_error_bias"])

        write_final_release_manifest(
            manifest_path=manifest_path,
            dataset_path=data_path,
            data=data,
            split=split,
            metrics=metrics,
            baselines=baselines,
            git_commit_sha=git_commit_sha,
            mlflow_run_id=run.info.run_id,
            model_path=model_path,
            feature_path=feature_path,
            metrics_path=metrics_path,
            baselines_path=baselines_path,
            regime_path=regime_path,
        )
        mlflow.sklearn.log_model(model, name="final_gold_model")
        for path in (metrics_path, regime_path, baselines_path, manifest_path):
            mlflow.log_artifact(str(path), artifact_path="final_release")

    print(f"Final holdout MAE: {metric_row['mae']:.6f}")
    print(f"Final holdout RMSE: {metric_row['rmse']:.6f}")
    print(f"Final holdout R²: {metric_row['r2']:.6f}")
    print(f"Final holdout rows: {len(split.holdout_data)}")
    print(f"Final release manifest saved to {manifest_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the one-time frozen PowerFlow 2025 holdout evaluation."
    )
    parser.add_argument("--data-path", type=Path, default=DATA_PATH)
    parser.add_argument("--model-path", type=Path, default=MODEL_PATH)
    parser.add_argument("--feature-path", type=Path, default=FEATURE_PATH)
    parser.add_argument("--manifest-path", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--metrics-path", type=Path, default=METRICS_PATH)
    parser.add_argument("--regime-path", type=Path, default=REGIME_PATH)
    parser.add_argument("--baselines-path", type=Path, default=BASELINES_PATH)
    parser.add_argument(
        "--mlflow-tracking-uri",
        default=os.getenv("POWERFLOW_MLFLOW_TRACKING_URI", MLFLOW_TRACKING_URI),
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    main(
        data_path=arguments.data_path,
        model_path=arguments.model_path,
        feature_path=arguments.feature_path,
        manifest_path=arguments.manifest_path,
        metrics_path=arguments.metrics_path,
        regime_path=arguments.regime_path,
        baselines_path=arguments.baselines_path,
        mlflow_tracking_uri=arguments.mlflow_tracking_uri,
    )
