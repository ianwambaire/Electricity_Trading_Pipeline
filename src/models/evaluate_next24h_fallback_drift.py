"""Offline-only fallback temporal-drift and release-style refit experiment."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from models.evaluate_next24h_fallback import (
    TEST_START,
    VALIDATION_START,
    chronological_splits,
    extreme_metric_rows,
    metric_rows,
)
from models.next24h import HORIZONS, ISSUE_TIME
from models.next24h_fallback import (
    PERSISTENCE_BENCHMARK_COLUMN,
    TARGET_COLUMNS,
    build_fallback_training_data,
)
from models.next24h_fallback_v2 import (
    HorizonSpecificFallbackModel,
    prepare_horizon_features,
)


DEFAULT_SILVER = Path("data/processed/silver_electricity_market_data.csv")
DEFAULT_OUTPUT = Path(
    "artifacts/models/candidates/next24h_fallback_drift/development-2026-10-02"
)
DEFAULT_V1_DIR = Path(
    "artifacts/models/candidates/next24h_fallback/development-2026-10-02"
)
DEFAULT_V2_DIR = Path(
    "artifacts/models/candidates/next24h_fallback_v2/development-2026-10-02"
)
DEFAULT_PRIMARY_DIR = Path(
    "artifacts/models/candidates/next24h/development-2026-09-21"
)
MODEL_FAMILY = "Histogram Gradient Boosting"
TRAINING_STRATEGIES = (
    "full_history",
    "recency_weighted_365d",
    "rolling_3y",
)
FEATURE_DRIFT_COLUMNS = (
    "load_mw",
    "wind_total_mw",
    "solar_mw",
    "renewable_share",
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "cloud_cover",
    "shortwave_radiation",
)


def _distribution(values: pd.Series) -> dict:
    values = pd.to_numeric(values, errors="raise").dropna()
    quantiles = values.quantile([0.05, 0.25, 0.75, 0.95])
    return {
        "observations": len(values),
        "mean": float(values.mean()),
        "median": float(values.median()),
        "std": float(values.std()),
        "minimum": float(values.min()),
        "maximum": float(values.max()),
        "p05": float(quantiles.loc[0.05]),
        "p25": float(quantiles.loc[0.25]),
        "p75": float(quantiles.loc[0.75]),
        "p95": float(quantiles.loc[0.95]),
    }


def temporal_drift_tables(silver: pd.DataFrame, splits: dict):
    """Profile unique hourly prices and issue-time features by temporal period."""
    prices = silver.loc[:, ["timestamp", "price_eur_mwh"]].copy()
    prices["timestamp"] = pd.to_datetime(prices["timestamp"], errors="raise", utc=True)
    prices["price_eur_mwh"] = pd.to_numeric(prices["price_eur_mwh"], errors="raise")
    if prices["timestamp"].duplicated().any():
        raise ValueError("Price drift diagnostics require unique hourly timestamps.")
    price_periods = {
        "train": prices.loc[prices["timestamp"] < VALIDATION_START],
        "validation": prices.loc[
            (prices["timestamp"] >= VALIDATION_START)
            & (prices["timestamp"] < TEST_START)
        ],
        "test": prices.loc[prices["timestamp"] >= TEST_START],
    }
    price_rows, monthly_rows = [], []
    for period, frame in price_periods.items():
        summary = _distribution(frame["price_eur_mwh"])
        summary.update(
            {
                "period": period,
                "start_utc": frame["timestamp"].min().isoformat(),
                "end_utc": frame["timestamp"].max().isoformat(),
                "negative_price_pct": float((frame["price_eur_mwh"] < 0).mean() * 100),
                "price_gte_200_pct": float((frame["price_eur_mwh"] >= 200).mean() * 100),
            }
        )
        price_rows.append(summary)
        monthly = (
            frame.assign(month=frame["timestamp"].dt.strftime("%Y-%m"))
            .groupby("month", as_index=False)["price_eur_mwh"]
            .agg(monthly_mean="mean", monthly_median="median", observations="count")
        )
        monthly.insert(0, "period", period)
        monthly_rows.extend(monthly.to_dict("records"))

    feature_rows = []
    for period, frame in splits.items():
        for feature in FEATURE_DRIFT_COLUMNS:
            feature_rows.append(
                {"period": period, "feature": feature, **_distribution(frame[feature])}
            )
    return (
        pd.DataFrame(price_rows),
        pd.DataFrame(monthly_rows),
        pd.DataFrame(feature_rows),
    )


def strategy_rows_and_weights(data: pd.DataFrame, strategy: str):
    """Apply a predeclared training strategy without consulting evaluation targets."""
    if strategy not in TRAINING_STRATEGIES:
        raise ValueError(f"Unknown training strategy: {strategy}")
    issue_times = pd.to_datetime(data[ISSUE_TIME], errors="raise", utc=True)
    if strategy == "full_history":
        return data.copy(), None
    if strategy == "recency_weighted_365d":
        age_days = (issue_times.max() - issue_times).dt.total_seconds() / 86400
        weights = np.power(0.5, age_days / 365.0)
        return data.copy(), weights.to_numpy(dtype=float)
    cutoff = issue_times.max() - pd.DateOffset(years=3)
    mask = issue_times >= cutoff
    return data.loc[mask].copy(), None


def _new_hgb():
    return HistGradientBoostingRegressor(
        max_iter=80,
        max_leaf_nodes=15,
        min_samples_leaf=50,
        l2_regularization=1.0,
        random_state=42,
    )


def fit_strategy(data: pd.DataFrame, strategy: str):
    selected_rows, weights = strategy_rows_and_weights(data, strategy)
    estimators = {}
    for horizon in HORIZONS:
        estimator = _new_hgb()
        estimator.fit(
            prepare_horizon_features(selected_rows, horizon),
            selected_rows[f"target_price_{horizon}h"].to_numpy(),
            sample_weight=weights,
        )
        estimators[horizon] = estimator
    return HorizonSpecificFallbackModel(estimators), len(selected_rows)


def select_training_strategy(validation_metrics: pd.DataFrame) -> str:
    """Freeze the training strategy using validation overall RMSE only."""
    overall = validation_metrics.loc[
        (validation_metrics["split"] == "validation")
        & (validation_metrics["horizon_hours"] == 0)
    ]
    if set(overall["strategy"]) != set(TRAINING_STRATEGIES):
        raise ValueError("Every predefined strategy requires validation metrics.")
    return overall.sort_values(["rmse", "strategy"]).iloc[0]["strategy"]


def combined_refit_rows(splits: dict) -> pd.DataFrame:
    """Combine train and validation only, enforcing a target-time test embargo."""
    combined = pd.concat([splits["train"], splits["validation"]], ignore_index=True)
    last_targets = pd.to_datetime(combined["target_timestamp_24h"], utc=True)
    if last_targets.max() >= TEST_START:
        raise ValueError("Refit targets must end before the untouched test period.")
    if (pd.to_datetime(combined[ISSUE_TIME], utc=True) >= TEST_START).any():
        raise ValueError("Test issue rows cannot enter refitting.")
    return combined


def _tag_metric_rows(rows: list, strategy: str) -> list:
    return [{"strategy": strategy, **row} for row in rows]


def _reference_tables(v1_dir: Path, v2_dir: Path, primary_dir: Path):
    references, extreme_references = [], []
    for directory, architecture in (
        (v1_dir, "fallback_v1_original"),
        (v2_dir, "fallback_v2_original"),
        (primary_dir, "primary_hgb_context_only"),
    ):
        manifest = json.loads((directory / "candidate_manifest.json").read_text())
        model_name = manifest["model_name"]
        metrics = pd.read_csv(directory / "metrics_by_horizon.csv")
        selected = metrics.loc[metrics["model_name"] == model_name].copy()
        selected.insert(0, "architecture", architecture)
        references.append(selected)
        extremes = pd.read_csv(directory / "extreme_price_metrics.csv")
        selected_extremes = extremes.loc[extremes["model_name"] == model_name].copy()
        selected_extremes["price_regime"] = selected_extremes["price_regime"].replace(
            {"extreme_high_price": "price_gte_200_eur_mwh"}
        )
        selected_extremes.insert(0, "architecture", architecture)
        extreme_references.append(selected_extremes)
    persistence = pd.read_csv(v2_dir / "metrics_by_horizon.csv").loc[
        lambda frame: frame["model_name"] == "Persistence (benchmark only)"
    ].copy()
    persistence.insert(0, "architecture", "persistence_evaluation_only")
    references.append(persistence)
    persistence_extremes = pd.read_csv(v2_dir / "extreme_price_metrics.csv").loc[
        lambda frame: frame["model_name"] == "Persistence (benchmark only)"
    ].copy()
    persistence_extremes.insert(0, "architecture", "persistence_evaluation_only")
    extreme_references.append(persistence_extremes)
    return (
        pd.concat(references, ignore_index=True),
        pd.concat(extreme_references, ignore_index=True),
    )


def evaluate(
    silver_path: Path = DEFAULT_SILVER,
    output_dir: Path = DEFAULT_OUTPUT,
    v1_dir: Path = DEFAULT_V1_DIR,
    v2_dir: Path = DEFAULT_V2_DIR,
    primary_dir: Path = DEFAULT_PRIMARY_DIR,
):
    silver_path, output_dir = Path(silver_path), Path(output_dir)
    v1_dir, v2_dir, primary_dir = Path(v1_dir), Path(v2_dir), Path(primary_dir)
    if output_dir.exists():
        raise FileExistsError(f"Fallback drift output already exists: {output_dir}")
    v2_manifest = json.loads((v2_dir / "candidate_manifest.json").read_text())
    if v2_manifest["model_name"] != MODEL_FAMILY:
        raise ValueError("This experiment requires the validation-selected fallback v2 HGB.")

    silver = pd.read_csv(silver_path, low_memory=False)
    splits = chronological_splits(build_fallback_training_data(silver))
    price_drift, monthly_prices, feature_drift = temporal_drift_tables(silver, splits)

    validation_metrics, validation_extremes = [], []
    for strategy in TRAINING_STRATEGIES:
        print(f"Validating predeclared strategy {strategy}...", flush=True)
        model, rows_used = fit_strategy(splits["train"], strategy)
        actual = splits["validation"][list(TARGET_COLUMNS)].to_numpy()
        predicted = model.predict(splits["validation"])
        rows = _tag_metric_rows(
            metric_rows(MODEL_FAMILY, "validation", actual, predicted), strategy
        )
        for row in rows:
            row["fit_rows"] = rows_used
        validation_metrics.extend(rows)
        validation_extremes.extend(
            _tag_metric_rows(
                extreme_metric_rows(MODEL_FAMILY, "validation", actual, predicted),
                strategy,
            )
        )

    validation_table = pd.DataFrame(validation_metrics)
    selected_strategy = select_training_strategy(validation_table)
    combined = combined_refit_rows(splits)

    refit_models, refit_metrics, refit_extremes, refit_rows = {}, [], [], {}
    for strategy in TRAINING_STRATEGIES:
        print(f"Refitting frozen HGB with {strategy} on pre-test data...", flush=True)
        model, rows_used = fit_strategy(combined, strategy)
        refit_models[strategy] = model
        refit_rows[strategy] = rows_used
        actual = splits["test"][list(TARGET_COLUMNS)].to_numpy()
        predicted = model.predict(splits["test"])
        rows = _tag_metric_rows(
            metric_rows(MODEL_FAMILY, "test", actual, predicted), strategy
        )
        for row in rows:
            row["fit_rows"] = rows_used
        refit_metrics.extend(rows)
        refit_extremes.extend(
            _tag_metric_rows(
                extreme_metric_rows(MODEL_FAMILY, "test", actual, predicted),
                strategy,
            )
        )

    refit_metric_table = pd.concat(
        [validation_table, pd.DataFrame(refit_metrics)], ignore_index=True
    )
    refit_extreme_table = pd.concat(
        [pd.DataFrame(validation_extremes), pd.DataFrame(refit_extremes)],
        ignore_index=True,
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    models_path = output_dir / "refitted_horizon_models.joblib"
    joblib.dump(refit_models, models_path)

    references, extreme_references = _reference_tables(v1_dir, v2_dir, primary_dir)
    refit_comparison = refit_metric_table.copy()
    refit_comparison.insert(
        0,
        "architecture",
        refit_comparison["strategy"].map(lambda value: f"fallback_v2_refit_{value}"),
    )
    comparison = pd.concat([references, refit_comparison], ignore_index=True)
    comparison.loc[comparison["horizon_hours"] == 0].to_csv(
        output_dir / "overall_comparison.csv", index=False
    )
    comparison.loc[comparison["horizon_hours"] != 0].to_csv(
        output_dir / "horizon_comparison.csv", index=False
    )
    refit_extreme_comparison = refit_extreme_table.copy()
    refit_extreme_comparison.insert(
        0,
        "architecture",
        refit_extreme_comparison["strategy"].map(
            lambda value: f"fallback_v2_refit_{value}"
        ),
    )
    pd.concat([extreme_references, refit_extreme_comparison], ignore_index=True).to_csv(
        output_dir / "extreme_price_comparison.csv", index=False
    )

    price_drift.to_csv(output_dir / "price_target_drift.csv", index=False)
    monthly_prices.to_csv(output_dir / "monthly_price_drift.csv", index=False)
    feature_drift.to_csv(output_dir / "input_feature_drift.csv", index=False)
    validation_table.to_csv(output_dir / "training_strategy_validation.csv", index=False)
    refit_metric_table.to_csv(output_dir / "refit_metrics_by_horizon.csv", index=False)
    refit_extreme_table.to_csv(output_dir / "refit_extreme_price_metrics.csv", index=False)

    manifest = {
        "release_type": "next24h_fallback_temporal_drift_experiment_not_promoted",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_promoted": False,
        "selected_model_family_before_test": MODEL_FAMILY,
        "selected_training_strategy_before_test": selected_strategy,
        "predeclared_training_strategies": list(TRAINING_STRATEGIES),
        "selection_rule": "Lowest validation overall RMSE; test excluded",
        "refit_model_file": models_path.name,
        "refit_model_sha256": hashlib.sha256(models_path.read_bytes()).hexdigest(),
        "source_silver_sha256": hashlib.sha256(silver_path.read_bytes()).hexdigest(),
        "validation_start": VALIDATION_START.isoformat(),
        "test_start": TEST_START.isoformat(),
        "combined_refit_rows": len(combined),
        "combined_refit_last_issue_time": pd.to_datetime(
            combined[ISSUE_TIME], utc=True
        ).max().isoformat(),
        "combined_refit_last_target_time": pd.to_datetime(
            combined["target_timestamp_24h"], utc=True
        ).max().isoformat(),
        "test_rows": len(splits["test"]),
        "refit_rows_by_strategy": refit_rows,
        "leakage_statement": (
            "Model family, hyperparameters, and training strategy were frozen from "
            "pre-test validation. All refit target windows end before 2026-05-01 UTC. "
            "No test target was used for fitting, weighting, calibration, or selection."
        ),
        "bias_correction_applied": False,
        "v1_manifest_sha256": hashlib.sha256(
            (v1_dir / "candidate_manifest.json").read_bytes()
        ).hexdigest(),
        "v2_manifest_sha256": hashlib.sha256(
            (v2_dir / "candidate_manifest.json").read_bytes()
        ).hexdigest(),
        "primary_manifest_sha256": hashlib.sha256(
            (primary_dir / "candidate_manifest.json").read_bytes()
        ).hexdigest(),
    }
    (output_dir / "experiment_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Training strategy selected before test: {selected_strategy}")
    print(f"Experiment files saved under {output_dir}")
    return price_drift, feature_drift, refit_metric_table, manifest


def main():
    parser = argparse.ArgumentParser(
        description="Offline fallback temporal-drift and pre-test refit experiment."
    )
    parser.add_argument("--silver", type=Path, default=DEFAULT_SILVER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--v1-dir", type=Path, default=DEFAULT_V1_DIR)
    parser.add_argument("--v2-dir", type=Path, default=DEFAULT_V2_DIR)
    parser.add_argument("--primary-dir", type=Path, default=DEFAULT_PRIMARY_DIR)
    args = parser.parse_args()
    evaluate(args.silver, args.output_dir, args.v1_dir, args.v2_dir, args.primary_dir)


if __name__ == "__main__":
    main()
