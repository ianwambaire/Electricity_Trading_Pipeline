import argparse
import os
from pathlib import Path

import mlflow
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from xgboost import XGBRegressor

if __package__:
    from .backtesting import (
        BASELINE_NAMES,
        TARGET_COLUMN,
        add_improvement_statistics,
        build_aggregate_statistics,
        build_baseline_predictions,
        build_expanding_window_folds,
        calculate_forecast_metrics,
    )
else:
    from backtesting import (
        BASELINE_NAMES,
        TARGET_COLUMN,
        add_improvement_statistics,
        build_aggregate_statistics,
        build_baseline_predictions,
        build_expanding_window_folds,
        calculate_forecast_metrics,
    )


DATA_PATH = Path("data/features/gold_model_features.csv")
BACKTEST_REPORT_PATH = Path("data/reports/backtest_model_comparison.csv")
BACKTEST_AGGREGATE_PATH = Path("data/reports/backtest_model_aggregate.csv")
MLFLOW_TRACKING_URI = "sqlite:///mlflow.db"
MLFLOW_EXPERIMENT_NAME = "electricity-price-forecasting-entsoe"
RANDOM_STATE = 42


def build_untuned_models():
    return {
        "Linear Regression": LinearRegression(),
        "Random Forest": RandomForestRegressor(
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
        "Gradient Boosting": GradientBoostingRegressor(
            random_state=RANDOM_STATE,
        ),
        "XGBoost": XGBRegressor(
            objective="reg:squarederror",
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
    }


def log_backtest_result(result: dict):
    run_name = f"backtest-{result['model_name']}-{result['validation_period']}"
    with mlflow.start_run(run_name=run_name):
        mlflow.set_tag("evaluation_type", "expanding_window_backtest")
        mlflow.set_tag(
            "model_type",
            "baseline" if result["model_name"] in BASELINE_NAMES else "untuned_ml",
        )
        for parameter in (
            "model_name",
            "validation_period",
            "train_start",
            "train_end",
            "validation_start",
            "validation_end",
            "train_rows",
            "validation_rows",
        ):
            mlflow.log_param(parameter, result[parameter])
        for metric in (
            "mae",
            "rmse",
            "r2",
            "rmse_improvement_vs_persistence_pct",
            "rmse_improvement_vs_best_seasonal_pct",
        ):
            if metric in result and pd.notna(result[metric]):
                mlflow.log_metric(metric, result[metric])


def evaluate_backtests(data: pd.DataFrame, log_mlflow: bool = True) -> pd.DataFrame:
    data = data.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    data = data.sort_values("timestamp").reset_index(drop=True)

    feature_columns = [
        column for column in data.columns if column not in {"timestamp", TARGET_COLUMN}
    ]
    baseline_predictions = build_baseline_predictions(data)
    folds = build_expanding_window_folds(data)
    model_templates = build_untuned_models()
    rows = []

    for fold in folds:
        train_data = data.loc[fold.train_indices]
        validation_data = data.loc[fold.validation_indices]
        actual = validation_data[TARGET_COLUMN]
        common = {
            "validation_period": fold.validation_period,
            "train_start": fold.train_start.isoformat(),
            "train_end": fold.train_end.isoformat(),
            "validation_start": fold.validation_start.isoformat(),
            "validation_end": fold.validation_end.isoformat(),
            "train_rows": len(train_data),
            "validation_rows": len(validation_data),
        }

        for model_name in BASELINE_NAMES:
            predicted = baseline_predictions.loc[fold.validation_indices, model_name]
            if predicted.isna().any():
                raise ValueError(
                    f"{model_name} lacks historical observations for "
                    f"validation period {fold.validation_period}."
                )
            result = {
                "model_name": model_name,
                **common,
                **calculate_forecast_metrics(actual, predicted),
            }
            rows.append(result)

        for model_name, template in model_templates.items():
            model = clone(template)
            model.fit(train_data[feature_columns], train_data[TARGET_COLUMN])
            predicted = model.predict(validation_data[feature_columns])
            result = {
                "model_name": model_name,
                **common,
                **calculate_forecast_metrics(actual, predicted),
            }
            rows.append(result)

    results = add_improvement_statistics(pd.DataFrame(rows))
    if log_mlflow:
        for result in results.to_dict(orient="records"):
            log_backtest_result(result)
    return results


def main(
    data_path: Path = DATA_PATH,
    report_path: Path = BACKTEST_REPORT_PATH,
    aggregate_path: Path = BACKTEST_AGGREGATE_PATH,
    mlflow_tracking_uri: str = MLFLOW_TRACKING_URI,
    log_mlflow: bool = True,
):
    data = pd.read_csv(data_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)

    if log_mlflow:
        mlflow.set_tracking_uri(mlflow_tracking_uri)
        mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)

    results = evaluate_backtests(data, log_mlflow=log_mlflow)
    aggregate = build_aggregate_statistics(results)
    results.to_csv(report_path, index=False)
    aggregate.to_csv(aggregate_path, index=False)

    print(f"Backtest comparison saved to {report_path}")
    print(f"Backtest aggregate statistics saved to {aggregate_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run expanding-window PowerFlow model backtests."
    )
    parser.add_argument("--data-path", type=Path, default=DATA_PATH)
    parser.add_argument("--report-path", type=Path, default=BACKTEST_REPORT_PATH)
    parser.add_argument(
        "--aggregate-path",
        type=Path,
        default=BACKTEST_AGGREGATE_PATH,
    )
    parser.add_argument(
        "--mlflow-tracking-uri",
        default=os.getenv("POWERFLOW_MLFLOW_TRACKING_URI", MLFLOW_TRACKING_URI),
    )
    parser.add_argument(
        "--no-mlflow",
        action="store_true",
        help="Run the report without writing MLflow runs.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    main(
        data_path=arguments.data_path,
        report_path=arguments.report_path,
        aggregate_path=arguments.aggregate_path,
        mlflow_tracking_uri=arguments.mlflow_tracking_uri,
        log_mlflow=not arguments.no_mlflow,
    )
