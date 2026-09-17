import argparse
import os
from contextlib import nullcontext
from pathlib import Path

import mlflow
import pandas as pd
from mlflow.tracking import MlflowClient

if __package__:
    from .artifact_metadata import generate_dataset_version, get_git_commit_sha
    from .backtesting import (
        TARGET_COLUMN,
        build_baseline_predictions,
        calculate_forecast_metrics,
    )
    from .focused_tuning import (
        FINAL_HOLDOUT_START,
        add_persistence_improvement,
        build_coefficient_diagnostics,
        build_focused_candidates,
        build_focused_development_folds,
        configuration_key,
        evaluate_parameter_configuration,
        parameter_configurations,
        select_best_family_configurations,
        select_development_winner,
        validate_candidate_features,
    )
    from .research_evaluation import build_regime_performance
else:
    from artifact_metadata import generate_dataset_version, get_git_commit_sha
    from backtesting import (
        TARGET_COLUMN,
        build_baseline_predictions,
        calculate_forecast_metrics,
    )
    from focused_tuning import (
        FINAL_HOLDOUT_START,
        add_persistence_improvement,
        build_coefficient_diagnostics,
        build_focused_candidates,
        build_focused_development_folds,
        configuration_key,
        evaluate_parameter_configuration,
        parameter_configurations,
        select_best_family_configurations,
        select_development_winner,
        validate_candidate_features,
    )
    from research_evaluation import build_regime_performance


DATA_PATH = Path("data/features/gold_model_features.csv")
RESULTS_PATH = Path("data/reports/focused_model_tuning_results.csv")
AGGREGATE_PATH = Path("data/reports/focused_model_tuning_aggregate.csv")
COEFFICIENTS_PATH = Path("data/reports/linear_model_coefficients.csv")
REGIME_PATH = Path("data/reports/focused_regime_performance.csv")
MLFLOW_TRACKING_URI = "sqlite:///mlflow.db"
MLFLOW_EXPERIMENT_NAME = "electricity-price-forecasting-entsoe"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def log_candidate_run(summary: dict, fold_rows: list[dict], metadata: dict) -> str:
    with mlflow.start_run(run_name=summary["configuration_id"], nested=True) as run:
        mlflow.set_tag("evaluation_type", "focused_development_tuning")
        mlflow.set_tag("final_holdout_used", "false")
        mlflow.log_param("model_name", summary["model_name"])
        mlflow.log_param("configuration_id", summary["configuration_id"])
        mlflow.log_param("feature_group", summary["feature_group"])
        mlflow.log_param("feature_count", summary["feature_count"])
        mlflow.log_param(
            "selected_hyperparameters",
            summary["selected_hyperparameters"],
        )
        mlflow.log_param("validation_years", "2022,2023,2024")
        mlflow.log_param("selection_metric", "mean_expanding_window_rmse")
        for key, value in metadata.items():
            if value is not None:
                mlflow.log_param(key, value)
        for row in fold_rows:
            year = row["validation_period"]
            mlflow.log_metric(f"rmse_{year}", row["rmse"])
            mlflow.log_metric(f"mae_{year}", row["mae"])
            mlflow.log_metric(f"r2_{year}", row["r2"])
        for metric in ("mean_mae", "mean_rmse", "rmse_std", "min_rmse", "max_rmse"):
            mlflow.log_metric(metric, summary[metric])
        return run.info.run_id


def persistence_mean_rmse(data: pd.DataFrame, folds) -> float:
    predictions = build_baseline_predictions(data)["Persistence Baseline"]
    fold_rmse = []
    for fold in folds:
        validation = data.loc[fold.validation_indices]
        metrics = calculate_forecast_metrics(
            validation[TARGET_COLUMN],
            predictions.loc[fold.validation_indices],
        )
        fold_rmse.append(metrics["rmse"])
    return float(pd.Series(fold_rmse).mean())


def evaluate_focused_candidates(
    data: pd.DataFrame,
    metadata: dict,
    log_mlflow: bool,
):
    candidates = build_focused_candidates()
    validate_candidate_features(candidates, data.columns)
    folds = build_focused_development_folds(data)
    baseline_rmse = persistence_mean_rmse(data, folds)

    all_fold_rows = []
    all_summaries = []
    best_predictions = {}
    best_summary_by_family = {}
    untuned_predictions = {}

    for candidate in candidates:
        for position, parameters in enumerate(
            parameter_configurations(candidate),
            start=1,
        ):
            configuration_id = (
                f"{candidate.name.lower().replace(' ', '-')}-{position:03d}"
            )
            print(
                f"Evaluating {candidate.name} configuration "
                f"{position}/{len(parameter_configurations(candidate))}"
            )
            fold_rows, summary, predictions = evaluate_parameter_configuration(
                data,
                folds,
                candidate,
                parameters,
                configuration_id,
            )
            if log_mlflow:
                summary["mlflow_run_id"] = log_candidate_run(
                    summary,
                    fold_rows,
                    metadata,
                )
            else:
                summary["mlflow_run_id"] = None
            for row in fold_rows:
                row["mlflow_run_id"] = summary["mlflow_run_id"]
            all_fold_rows.extend(fold_rows)
            all_summaries.append(summary)
            if candidate.include_untuned_reference and not parameters:
                untuned_predictions[candidate.name] = predictions

            current_best = best_summary_by_family.get(candidate.name)
            if current_best is None or configuration_key(summary) < configuration_key(
                current_best
            ):
                best_summary_by_family[candidate.name] = summary
                best_predictions[candidate.name] = predictions

    aggregate = add_persistence_improvement(
        pd.DataFrame(all_summaries),
        baseline_rmse,
    )
    family_results = select_best_family_configurations(aggregate)
    selected_ids = set(family_results["configuration_id"])
    predictions = pd.concat(
        [
            best_predictions[model_name]
            for model_name in family_results["model_name"]
        ],
        ignore_index=True,
    )
    regimes = build_regime_performance(predictions)

    if untuned_predictions:
        untuned_regimes = build_regime_performance(
            pd.concat(untuned_predictions.values(), ignore_index=True)
        )
        untuned_reference = untuned_regimes[
            ["model_name", "validation_period", "price_regime", "rmse"]
        ].rename(columns={"rmse": "untuned_reference_rmse"})
        regimes = regimes.merge(
            untuned_reference,
            on=["model_name", "validation_period", "price_regime"],
            how="left",
        )
        regimes["rmse_improvement_vs_untuned_pct"] = (
            (regimes["untuned_reference_rmse"] - regimes["rmse"])
            / regimes["untuned_reference_rmse"]
            * 100.0
        ).where(regimes["untuned_reference_rmse"] > 0)
    else:
        regimes["untuned_reference_rmse"] = float("nan")
        regimes["rmse_improvement_vs_untuned_pct"] = float("nan")

    selected_metadata = family_results[
        [
            "model_name",
            "configuration_id",
            "selected_hyperparameters",
        ]
    ]
    regimes = regimes.merge(selected_metadata, on="model_name", how="left")
    extreme_2022 = regimes[
        (regimes["validation_period"].astype(str) == "2022")
        & (regimes["price_regime"] == "Extreme")
    ][["model_name", "rmse"]].rename(columns={"rmse": "extreme_2022_rmse"})
    family_results = family_results.merge(extreme_2022, on="model_name", how="left")

    winner = select_development_winner(family_results)
    aggregate["best_within_family"] = aggregate["configuration_id"].isin(selected_ids)
    aggregate["selected"] = aggregate["configuration_id"].eq(
        winner["configuration_id"]
    )
    aggregate = aggregate.merge(extreme_2022, on="model_name", how="left")
    aggregate.loc[
        ~aggregate["best_within_family"],
        "extreme_2022_rmse",
    ] = float("nan")

    fold_results = pd.DataFrame(all_fold_rows)
    fold_results["best_within_family"] = fold_results["configuration_id"].isin(
        selected_ids
    )
    fold_results["selected"] = fold_results["configuration_id"].eq(
        winner["configuration_id"]
    )
    coefficients = build_coefficient_diagnostics(
        data,
        candidates,
        family_results,
    )
    return fold_results, aggregate, coefficients, regimes, family_results, winner


def tag_selected_runs(family_results: pd.DataFrame, winner: dict) -> None:
    client = MlflowClient()
    for row in family_results.to_dict(orient="records"):
        run_id = row.get("mlflow_run_id")
        if not run_id:
            continue
        client.set_tag(run_id, "best_within_family", "true")
        client.set_tag(
            run_id,
            "development_winner",
            str(row["configuration_id"] == winner["configuration_id"]).lower(),
        )


def write_reports(
    results: pd.DataFrame,
    aggregate: pd.DataFrame,
    coefficients: pd.DataFrame,
    regimes: pd.DataFrame,
    paths: list[Path],
) -> None:
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(paths[0], index=False)
    aggregate.to_csv(paths[1], index=False)
    coefficients.to_csv(paths[2], index=False)
    regimes.to_csv(paths[3], index=False)


def main(
    data_path: Path = DATA_PATH,
    results_path: Path = RESULTS_PATH,
    aggregate_path: Path = AGGREGATE_PATH,
    coefficients_path: Path = COEFFICIENTS_PATH,
    regime_path: Path = REGIME_PATH,
    mlflow_tracking_uri: str = MLFLOW_TRACKING_URI,
    log_mlflow: bool = True,
) -> None:
    data_path = Path(data_path)
    data = pd.read_csv(data_path)
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    data = data.sort_values("timestamp").reset_index(drop=True)

    metadata = {
        "dataset_version": generate_dataset_version(data_path),
        "git_commit_sha": get_git_commit_sha(PROJECT_ROOT),
        "gold_rows": len(data),
        "source_date_start": data["timestamp"].min().isoformat(),
        "source_date_end": data["timestamp"].max().isoformat(),
        "final_holdout_start": FINAL_HOLDOUT_START,
        "final_holdout_used": False,
    }
    output_paths = [results_path, aggregate_path, coefficients_path, regime_path]

    if log_mlflow:
        mlflow.set_tracking_uri(mlflow_tracking_uri)
        mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
    run_context = (
        mlflow.start_run(run_name="focused-model-development-tuning")
        if log_mlflow
        else nullcontext()
    )

    with run_context:
        results = evaluate_focused_candidates(data, metadata, log_mlflow)
        fold_results, aggregate, coefficients, regimes, family_results, winner = results
        write_reports(
            fold_results,
            aggregate,
            coefficients,
            regimes,
            output_paths,
        )
        if log_mlflow:
            mlflow.set_tag("evaluation_type", "focused_model_tuning_parent")
            mlflow.set_tag("final_holdout_used", "false")
            mlflow.log_param("dataset_version", metadata["dataset_version"])
            mlflow.log_param("git_commit_sha", metadata["git_commit_sha"] or "unavailable")
            mlflow.log_param("development_winner", winner["model_name"])
            mlflow.log_param(
                "winner_hyperparameters",
                winner["selected_hyperparameters"],
            )
            mlflow.log_metric("winner_mean_rmse", winner["mean_rmse"])
            for path in output_paths:
                mlflow.log_artifact(str(path), artifact_path="focused_tuning_reports")
            tag_selected_runs(family_results, winner)

    print(f"Development winner: {winner['model_name']}")
    print(f"Mean expanding-window RMSE: {winner['mean_rmse']:.6f}")
    print(f"Selected parameters: {winner['selected_hyperparameters']}")
    for path in output_paths:
        print(f"Focused tuning report saved to {path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run focused PowerFlow development-only model tuning."
    )
    parser.add_argument("--data-path", type=Path, default=DATA_PATH)
    parser.add_argument("--results-path", type=Path, default=RESULTS_PATH)
    parser.add_argument("--aggregate-path", type=Path, default=AGGREGATE_PATH)
    parser.add_argument("--coefficients-path", type=Path, default=COEFFICIENTS_PATH)
    parser.add_argument("--regime-path", type=Path, default=REGIME_PATH)
    parser.add_argument(
        "--mlflow-tracking-uri",
        default=os.getenv("POWERFLOW_MLFLOW_TRACKING_URI", MLFLOW_TRACKING_URI),
    )
    parser.add_argument(
        "--no-mlflow",
        action="store_true",
        help="Generate CSV reports without writing MLflow runs.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    main(
        data_path=arguments.data_path,
        results_path=arguments.results_path,
        aggregate_path=arguments.aggregate_path,
        coefficients_path=arguments.coefficients_path,
        regime_path=arguments.regime_path,
        mlflow_tracking_uri=arguments.mlflow_tracking_uri,
        log_mlflow=not arguments.no_mlflow,
    )
