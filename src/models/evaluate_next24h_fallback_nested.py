"""Offline-only nested rolling-origin validation for next24h fallback v2."""

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from models.evaluate_next24h_fallback import (
    TEST_START,
    extreme_metric_rows,
    metric_rows,
)
from models.evaluate_next24h_fallback_drift import (
    MODEL_FAMILY,
    combined_refit_rows,
)
from models.next24h import HORIZONS, ISSUE_TIME
from models.next24h_fallback import TARGET_COLUMNS, build_fallback_training_data
from models.next24h_fallback_v2 import (
    HorizonSpecificFallbackModel,
    prepare_horizon_features,
)


DEFAULT_SILVER = Path("data/processed/silver_electricity_market_data.csv")
DEFAULT_OUTPUT = Path(
    "artifacts/models/candidates/next24h_fallback_nested/development-2026-10-02"
)
DEFAULT_DRIFT_DIR = Path(
    "artifacts/models/candidates/next24h_fallback_drift/development-2026-10-02"
)
STRATEGIES = (
    "full_expanding",
    "rolling_1y",
    "rolling_2y",
    "rolling_3y",
    "recency_weighted_90d",
    "recency_weighted_180d",
    "recency_weighted_365d",
    "recency_weighted_730d",
)
SEASON_MONTHS = (
    ("winter", 1),
    ("spring", 4),
    ("summer", 7),
    ("autumn", 10),
)


@dataclass(frozen=True)
class RollingFold:
    fold_id: str
    season: str
    validation_start: pd.Timestamp
    validation_end: pd.Timestamp
    training: pd.DataFrame
    validation: pd.DataFrame

    def manifest_record(self) -> dict:
        return {
            "fold_id": self.fold_id,
            "season": self.season,
            "training_rows": len(self.training),
            "training_issue_start": pd.to_datetime(
                self.training[ISSUE_TIME], utc=True
            ).min().isoformat(),
            "training_issue_end": pd.to_datetime(
                self.training[ISSUE_TIME], utc=True
            ).max().isoformat(),
            "training_last_target": pd.to_datetime(
                self.training["target_timestamp_24h"], utc=True
            ).max().isoformat(),
            "validation_rows": len(self.validation),
            "validation_start": self.validation_start.isoformat(),
            "validation_end_exclusive": self.validation_end.isoformat(),
            "validation_issue_end": pd.to_datetime(
                self.validation[ISSUE_TIME], utc=True
            ).max().isoformat(),
            "validation_last_target": pd.to_datetime(
                self.validation["target_timestamp_24h"], utc=True
            ).max().isoformat(),
        }


def build_rolling_folds(pretest_data: pd.DataFrame) -> list[RollingFold]:
    """Choose the latest full pre-test year covering four seasonal monthly folds."""
    issue = pd.to_datetime(pretest_data[ISSUE_TIME], errors="raise", utc=True)
    last_target = pd.to_datetime(
        pretest_data["target_timestamp_24h"], errors="raise", utc=True
    )
    if (issue >= TEST_START).any() or (last_target >= TEST_START).any():
        raise ValueError("Rolling-fold construction accepts pre-test target windows only.")
    if not issue.is_monotonic_increasing or not issue.is_unique:
        raise ValueError("Rolling-fold issue times must be unique and ordered.")

    for year in range(issue.max().year, issue.min().year - 1, -1):
        folds = []
        for season, month in SEASON_MONTHS:
            start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
            end = start + pd.offsets.MonthBegin(1)
            training = pretest_data.loc[last_target < start].copy()
            validation = pretest_data.loc[
                (issue >= start) & (last_target < end)
            ].copy()
            expected_issue_times = pd.date_range(
                start,
                end - pd.Timedelta(hours=25),
                freq="h",
                tz="UTC",
            )
            actual_issue_times = pd.DatetimeIndex(
                pd.to_datetime(validation[ISSUE_TIME], utc=True)
            )
            if (
                len(training) < 365 * 24
                or len(actual_issue_times) != len(expected_issue_times)
                or not actual_issue_times.equals(expected_issue_times)
            ):
                folds = []
                break
            if pd.to_datetime(training["target_timestamp_24h"], utc=True).max() >= start:
                raise ValueError("A training target crosses its fold validation boundary.")
            folds.append(
                RollingFold(
                    fold_id=f"{year}-{season}",
                    season=season,
                    validation_start=start,
                    validation_end=end,
                    training=training,
                    validation=validation,
                )
            )
        if len(folds) == len(SEASON_MONTHS):
            return folds
    raise ValueError("No complete pre-test calendar year supports all seasonal folds.")


def strategy_rows_and_weights(data: pd.DataFrame, strategy: str):
    """Apply one predeclared window/weight rule using training timestamps only."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown nested-validation strategy: {strategy}")
    issue = pd.to_datetime(data[ISSUE_TIME], errors="raise", utc=True)
    if strategy == "full_expanding":
        return data.copy(), None
    if strategy.startswith("rolling_"):
        years = int(strategy.removeprefix("rolling_").removesuffix("y"))
        cutoff = issue.max() - pd.DateOffset(years=years)
        return data.loc[issue >= cutoff].copy(), None
    half_life_days = int(
        strategy.removeprefix("recency_weighted_").removesuffix("d")
    )
    age_days = (issue.max() - issue).dt.total_seconds() / 86400
    weights = np.power(0.5, age_days / half_life_days)
    return data.copy(), weights.to_numpy(dtype=float)


def _new_hgb():
    return HistGradientBoostingRegressor(
        max_iter=80,
        max_leaf_nodes=15,
        min_samples_leaf=50,
        l2_regularization=1.0,
        random_state=42,
    )


def fit_strategy(data: pd.DataFrame, strategy: str):
    selected, weights = strategy_rows_and_weights(data, strategy)

    def fit_horizon(horizon):
        estimator = _new_hgb()
        estimator.fit(
            prepare_horizon_features(selected, horizon),
            selected[f"target_price_{horizon}h"].to_numpy(),
            sample_weight=weights,
        )
        return horizon, estimator

    fitted = joblib.Parallel(n_jobs=4)(
        joblib.delayed(fit_horizon)(horizon) for horizon in HORIZONS
    )
    return HorizonSpecificFallbackModel(dict(fitted)), len(selected)


def aggregate_fold_results(
    fold_metrics: pd.DataFrame,
    fold_extremes: pd.DataFrame,
) -> pd.DataFrame:
    overall = fold_metrics.loc[fold_metrics["horizon_hours"] == 0].copy()
    aggregate = (
        overall.groupby("strategy", sort=False)
        .agg(
            fold_count=("fold_id", "nunique"),
            mean_rmse=("rmse", "mean"),
            median_rmse=("rmse", "median"),
            rmse_std=("rmse", lambda values: values.std(ddof=0)),
            worst_fold_rmse=("rmse", "max"),
            mean_absolute_bias=(
                "bias_predicted_minus_actual",
                lambda values: values.abs().mean(),
            ),
            worst_absolute_bias=(
                "bias_predicted_minus_actual",
                lambda values: values.abs().max(),
            ),
        )
        .reset_index()
    )
    high = fold_extremes.loc[
        fold_extremes["price_regime"] == "price_gte_200_eur_mwh"
    ].copy()

    def pooled_rmse(group):
        valid = group.loc[group["observations"] > 0]
        if valid.empty:
            return float("nan")
        return float(
            np.sqrt(
                np.average(
                    np.square(valid["rmse"]),
                    weights=valid["observations"],
                )
            )
        )

    high_summary = (
        high.groupby("strategy", sort=False)
        .apply(
            lambda group: pd.Series(
                {
                    "high_price_observations": int(group["observations"].sum()),
                    "high_price_rmse": pooled_rmse(group),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
    return aggregate.merge(high_summary, on="strategy", how="left")


def select_preferred_strategy(aggregate: pd.DataFrame) -> str:
    """Predeclared selection rule; accepts rolling-validation aggregates only."""
    required = set(STRATEGIES)
    if set(aggregate["strategy"]) != required:
        raise ValueError("Every predeclared strategy requires aggregate fold metrics.")
    ranked = aggregate.sort_values(
        ["mean_rmse", "worst_fold_rmse", "mean_absolute_bias", "strategy"]
    )
    return ranked.iloc[0]["strategy"]


def run_rolling_validation(pretest_data: pd.DataFrame):
    """Select a strategy without accepting or reading an untouched test frame."""
    folds = build_rolling_folds(pretest_data)
    metrics, extremes = [], []
    for fold in folds:
        for strategy in STRATEGIES:
            print(f"Evaluating {fold.fold_id} / {strategy}...", flush=True)
            model, fit_rows = fit_strategy(fold.training, strategy)
            actual = fold.validation[list(TARGET_COLUMNS)].to_numpy()
            predicted = model.predict(fold.validation)
            for row in metric_rows(MODEL_FAMILY, "rolling_validation", actual, predicted):
                metrics.append(
                    {
                        "fold_id": fold.fold_id,
                        "season": fold.season,
                        "strategy": strategy,
                        "fit_rows": fit_rows,
                        **row,
                    }
                )
            for row in extreme_metric_rows(
                MODEL_FAMILY, "rolling_validation", actual, predicted
            ):
                extremes.append(
                    {
                        "fold_id": fold.fold_id,
                        "season": fold.season,
                        "strategy": strategy,
                        **row,
                    }
                )
    metric_table, extreme_table = pd.DataFrame(metrics), pd.DataFrame(extremes)
    aggregate = aggregate_fold_results(metric_table, extreme_table)
    selected = select_preferred_strategy(aggregate)
    return folds, metric_table, extreme_table, aggregate, selected


def evaluate_test_once(model, test: pd.DataFrame, strategy: str):
    """Single final test prediction after nested strategy selection is frozen."""
    actual = test[list(TARGET_COLUMNS)].to_numpy()
    predicted = model.predict(test)
    metrics = pd.DataFrame(
        [{"strategy": strategy, **row} for row in metric_rows(
            MODEL_FAMILY, "test", actual, predicted
        )]
    )
    extremes = pd.DataFrame(
        [{"strategy": strategy, **row} for row in extreme_metric_rows(
            MODEL_FAMILY, "test", actual, predicted
        )]
    )
    return metrics, extremes


def evaluate(
    silver_path: Path = DEFAULT_SILVER,
    output_dir: Path = DEFAULT_OUTPUT,
    drift_dir: Path = DEFAULT_DRIFT_DIR,
):
    silver_path, output_dir, drift_dir = map(Path, (silver_path, output_dir, drift_dir))
    if output_dir.exists():
        raise FileExistsError(f"Nested fallback output already exists: {output_dir}")
    silver = pd.read_csv(silver_path, low_memory=False)
    all_data = build_fallback_training_data(silver)
    issue = pd.to_datetime(all_data[ISSUE_TIME], utc=True)
    last_target = pd.to_datetime(all_data["target_timestamp_24h"], utc=True)
    split_like = {
        "train": all_data.loc[last_target < pd.Timestamp("2026-01-01T00:00Z")].copy(),
        "validation": all_data.loc[
            (issue >= pd.Timestamp("2026-01-01T00:00Z"))
            & (last_target < TEST_START)
        ].copy(),
        "test": all_data.loc[issue >= TEST_START].copy(),
    }
    if any(frame.empty for frame in split_like.values()):
        raise ValueError("Train, validation, and untouched test rows are required.")
    pretest = combined_refit_rows(split_like)
    folds, fold_metrics, fold_extremes, aggregate, selected = run_rolling_validation(
        pretest
    )

    print(f"Nested validation selected {selected}; refitting once before test...", flush=True)
    final_model, final_fit_rows = fit_strategy(pretest, selected)
    final_metrics, final_extremes = evaluate_test_once(
        final_model, split_like["test"], selected
    )

    output_dir.mkdir(parents=True, exist_ok=False)
    model_path = output_dir / "nested_selected_horizon_model.joblib"
    joblib.dump(final_model, model_path)
    fold_metrics.to_csv(output_dir / "fold_metrics_by_horizon.csv", index=False)
    fold_extremes.to_csv(output_dir / "fold_extreme_price_metrics.csv", index=False)
    aggregate.to_csv(output_dir / "strategy_aggregate.csv", index=False)
    final_metrics.to_csv(output_dir / "final_test_metrics_by_horizon.csv", index=False)
    final_extremes.to_csv(output_dir / "final_test_extreme_price_metrics.csv", index=False)

    prior_overall = pd.read_csv(drift_dir / "overall_comparison.csv").loc[
        lambda frame: frame["split"] == "test"
    ]
    nested_overall = final_metrics.loc[final_metrics["horizon_hours"] == 0].copy()
    nested_overall.insert(0, "architecture", "fallback_nested_selected")
    pd.concat([prior_overall, nested_overall], ignore_index=True).to_csv(
        output_dir / "final_overall_comparison.csv", index=False
    )
    prior_horizons = pd.read_csv(drift_dir / "horizon_comparison.csv").loc[
        lambda frame: frame["split"] == "test"
    ]
    nested_horizons = final_metrics.loc[final_metrics["horizon_hours"] != 0].copy()
    nested_horizons.insert(0, "architecture", "fallback_nested_selected")
    pd.concat([prior_horizons, nested_horizons], ignore_index=True).to_csv(
        output_dir / "final_horizon_comparison.csv", index=False
    )
    prior_extremes = pd.read_csv(drift_dir / "extreme_price_comparison.csv").loc[
        lambda frame: frame["split"] == "test"
    ]
    nested_extremes = final_extremes.copy()
    nested_extremes.insert(0, "architecture", "fallback_nested_selected")
    pd.concat([prior_extremes, nested_extremes], ignore_index=True).to_csv(
        output_dir / "final_extreme_price_comparison.csv", index=False
    )

    selected_aggregate = aggregate.loc[aggregate["strategy"] == selected].iloc[0]
    manifest = {
        "release_type": "next24h_fallback_nested_validation_experiment_not_promoted",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_promoted": False,
        "model_family": MODEL_FAMILY,
        "core_hyperparameters_changed": False,
        "predeclared_strategies": list(STRATEGIES),
        "fold_selection_rule": (
            "Latest complete pre-test calendar year containing exact contiguous January, "
            "April, July, and October validation windows"
        ),
        "strategy_selection_rule": (
            "Lowest rolling-fold mean RMSE; ties by lower worst-fold RMSE, then lower "
            "mean absolute bias, then strategy name"
        ),
        "selected_strategy_before_test": selected,
        "selected_strategy_aggregate": {
            key: value.item() if hasattr(value, "item") else value
            for key, value in selected_aggregate.to_dict().items()
        },
        "folds": [fold.manifest_record() for fold in folds],
        "final_refit_rows": final_fit_rows,
        "final_refit_last_issue": pd.to_datetime(
            pretest[ISSUE_TIME], utc=True
        ).max().isoformat(),
        "final_refit_last_target": pd.to_datetime(
            pretest["target_timestamp_24h"], utc=True
        ).max().isoformat(),
        "untouched_test_start": TEST_START.isoformat(),
        "untouched_test_rows": len(split_like["test"]),
        "test_evaluations_after_selection": 1,
        "bias_correction_applied": False,
        "model_file": model_path.name,
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "source_silver_sha256": hashlib.sha256(silver_path.read_bytes()).hexdigest(),
        "leakage_statement": (
            "Fold training targets precede fold validation, validation targets remain "
            "inside each fold, strategy selection uses only rolling-origin aggregates, "
            "and the final refit target ends before 2026-05-01 UTC."
        ),
    }
    (output_dir / "experiment_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Nested experiment files saved under {output_dir}")
    return fold_metrics, aggregate, final_metrics, manifest


def main():
    parser = argparse.ArgumentParser(
        description="Offline nested rolling-origin validation for fallback v2."
    )
    parser.add_argument("--silver", type=Path, default=DEFAULT_SILVER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--drift-dir", type=Path, default=DEFAULT_DRIFT_DIR)
    args = parser.parse_args()
    evaluate(args.silver, args.output_dir, args.drift_dir)


if __name__ == "__main__":
    main()
