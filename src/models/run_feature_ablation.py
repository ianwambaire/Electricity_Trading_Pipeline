import argparse
import os
import re
from pathlib import Path

import mlflow
import pandas as pd
from sklearn.base import clone

if __package__:
    from .backtesting import (
        BASELINE_NAMES,
        TARGET_COLUMN,
        build_baseline_predictions,
        build_expanding_window_folds,
        calculate_forecast_metrics,
    )
    from .research_evaluation import (
        FEATURE_GROUPS,
        build_ablation_aggregate,
        build_regime_performance,
        build_yearly_price_regimes,
        validate_feature_groups,
    )
    from .run_backtest import build_untuned_models
else:
    from backtesting import (
        BASELINE_NAMES,
        TARGET_COLUMN,
        build_baseline_predictions,
        build_expanding_window_folds,
        calculate_forecast_metrics,
    )
    from research_evaluation import (
        FEATURE_GROUPS,
        build_ablation_aggregate,
        build_regime_performance,
        build_yearly_price_regimes,
        validate_feature_groups,
    )
    from run_backtest import build_untuned_models


DATA_PATH = Path("data/features/gold_model_features.csv")
ABLATION_RESULTS_PATH = Path("data/reports/feature_ablation_results.csv")
ABLATION_AGGREGATE_PATH = Path("data/reports/feature_ablation_aggregate.csv")
REGIME_REPORT_PATH = Path("data/reports/model_regime_performance.csv")
YEARLY_REGIMES_PATH = Path("data/reports/yearly_price_regimes.csv")
MLFLOW_TRACKING_URI = "sqlite:///mlflow.db"
MLFLOW_EXPERIMENT_NAME = "electricity-price-forecasting-entsoe"
FULL_FEATURE_GROUP = "Full PowerFlow"


def evaluate_feature_ablation(data: pd.DataFrame):
    data = data.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    data = data.sort_values("timestamp").reset_index(drop=True)
    validate_feature_groups(data.columns)

    folds = build_expanding_window_folds(data)
    model_templates = build_untuned_models()
    baseline_predictions = build_baseline_predictions(data)
    ablation_rows = []
    persistence_rows = []
    prediction_frames = []

    for fold in folds:
        train_data = data.loc[fold.train_indices]
        validation_data = data.loc[fold.validation_indices]
        actual = validation_data[TARGET_COLUMN]

        persistence = baseline_predictions.loc[
            fold.validation_indices,
            "Persistence Baseline",
        ]
        persistence_rows.append(calculate_forecast_metrics(actual, persistence))

        for baseline_name in BASELINE_NAMES:
            predicted = baseline_predictions.loc[fold.validation_indices, baseline_name]
            if predicted.isna().any():
                raise ValueError(
                    f"{baseline_name} lacks historical observations for "
                    f"validation period {fold.validation_period}."
                )
            prediction_frames.append(
                pd.DataFrame(
                    {
                        "model_name": baseline_name,
                        "feature_group": "Price-only Baseline",
                        "validation_period": fold.validation_period,
                        "actual": actual.to_numpy(),
                        "predicted": predicted.to_numpy(),
                    }
                )
            )

        for feature_group, feature_columns in FEATURE_GROUPS.items():
            for model_name, template in model_templates.items():
                model = clone(template)
                model.fit(
                    train_data[feature_columns],
                    train_data[TARGET_COLUMN],
                )
                predicted = model.predict(validation_data[feature_columns])
                metrics = calculate_forecast_metrics(actual, predicted)
                ablation_rows.append(
                    {
                        "model_name": model_name,
                        "feature_group": feature_group,
                        "feature_count": len(feature_columns),
                        "validation_period": fold.validation_period,
                        **metrics,
                        "train_rows": len(train_data),
                        "validation_rows": len(validation_data),
                    }
                )
                if feature_group == FULL_FEATURE_GROUP:
                    prediction_frames.append(
                        pd.DataFrame(
                            {
                                "model_name": model_name,
                                "feature_group": feature_group,
                                "validation_period": fold.validation_period,
                                "actual": actual.to_numpy(),
                                "predicted": predicted,
                            }
                        )
                    )

    ablation_results = pd.DataFrame(ablation_rows)
    persistence_mean_rmse = float(
        pd.DataFrame(persistence_rows)["rmse"].mean()
    )
    ablation_aggregate = build_ablation_aggregate(
        ablation_results,
        persistence_mean_rmse,
    )
    regime_performance = build_regime_performance(
        pd.concat(prediction_frames, ignore_index=True)
    )
    yearly_regimes = build_yearly_price_regimes(data)
    return (
        ablation_results,
        ablation_aggregate,
        regime_performance,
        yearly_regimes,
    )


def metric_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def log_experiment_to_mlflow(
    aggregate: pd.DataFrame,
    report_paths: list[Path],
) -> None:
    with mlflow.start_run(run_name="feature-ablation-regime-analysis"):
        mlflow.set_tag("evaluation_type", "feature_ablation_and_regime_analysis")
        mlflow.set_tag("final_holdout_used", "false")
        mlflow.log_param("validation_years", "2022,2023,2024")
        mlflow.log_param("feature_groups", len(FEATURE_GROUPS))
        mlflow.log_param("models", "Linear Regression,Random Forest,Gradient Boosting,XGBoost")
        for row in aggregate.to_dict(orient="records"):
            metric_name = "mean_rmse__{}__{}".format(
                metric_slug(row["model_name"]),
                metric_slug(row["feature_group"]),
            )
            mlflow.log_metric(metric_name, row["mean_rmse"])
        for report_path in report_paths:
            mlflow.log_artifact(str(report_path), artifact_path="research_reports")


def main(
    data_path: Path = DATA_PATH,
    ablation_results_path: Path = ABLATION_RESULTS_PATH,
    ablation_aggregate_path: Path = ABLATION_AGGREGATE_PATH,
    regime_report_path: Path = REGIME_REPORT_PATH,
    yearly_regimes_path: Path = YEARLY_REGIMES_PATH,
    mlflow_tracking_uri: str = MLFLOW_TRACKING_URI,
    log_mlflow: bool = True,
) -> None:
    data = pd.read_csv(data_path)
    output_paths = [
        ablation_results_path,
        ablation_aggregate_path,
        regime_report_path,
        yearly_regimes_path,
    ]
    for output_path in output_paths:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    results, aggregate, regimes, yearly = evaluate_feature_ablation(data)
    results.to_csv(ablation_results_path, index=False)
    aggregate.to_csv(ablation_aggregate_path, index=False)
    regimes.to_csv(regime_report_path, index=False)
    yearly.to_csv(yearly_regimes_path, index=False)

    if log_mlflow:
        mlflow.set_tracking_uri(mlflow_tracking_uri)
        mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
        log_experiment_to_mlflow(aggregate, output_paths)

    for output_path in output_paths:
        print(f"Research report saved to {output_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run PowerFlow feature ablation and market-regime analysis."
    )
    parser.add_argument("--data-path", type=Path, default=DATA_PATH)
    parser.add_argument(
        "--ablation-results-path",
        type=Path,
        default=ABLATION_RESULTS_PATH,
    )
    parser.add_argument(
        "--ablation-aggregate-path",
        type=Path,
        default=ABLATION_AGGREGATE_PATH,
    )
    parser.add_argument(
        "--regime-report-path",
        type=Path,
        default=REGIME_REPORT_PATH,
    )
    parser.add_argument(
        "--yearly-regimes-path",
        type=Path,
        default=YEARLY_REGIMES_PATH,
    )
    parser.add_argument(
        "--mlflow-tracking-uri",
        default=os.getenv("POWERFLOW_MLFLOW_TRACKING_URI", MLFLOW_TRACKING_URI),
    )
    parser.add_argument(
        "--no-mlflow",
        action="store_true",
        help="Generate CSV reports without writing an MLflow run.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    main(
        data_path=arguments.data_path,
        ablation_results_path=arguments.ablation_results_path,
        ablation_aggregate_path=arguments.ablation_aggregate_path,
        regime_report_path=arguments.regime_report_path,
        yearly_regimes_path=arguments.yearly_regimes_path,
        mlflow_tracking_uri=arguments.mlflow_tracking_uri,
        log_mlflow=not arguments.no_mlflow,
    )
