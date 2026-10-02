"""Offline evaluation of horizon-specific next24h fallback v2 candidates."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from models.evaluate_next24h_fallback import (
    TEST_START,
    VALIDATION_START,
    chronological_splits,
    extreme_metric_rows,
    metric_rows,
    select_candidate,
)
from models.next24h import HORIZONS, ISSUE_TIME
from models.next24h_fallback import (
    FALLBACK_FEATURES,
    PERSISTENCE_BENCHMARK_COLUMN,
    TARGET_COLUMNS,
    build_fallback_issue_features,
    build_fallback_training_data,
)
from models.next24h_fallback_v2 import (
    FALLBACK_V2_HORIZON_FEATURES,
    TARGET_CALENDAR_FEATURES,
    HorizonSpecificFallbackModel,
    create_fallback_v2_forecast,
    load_fallback_v2_candidate,
    prepare_horizon_features,
)


DEFAULT_SILVER = Path("data/processed/silver_electricity_market_data.csv")
DEFAULT_OUTPUT = Path(
    "artifacts/models/candidates/next24h_fallback_v2/development-2026-10-02"
)
DEFAULT_V1_DIR = Path(
    "artifacts/models/candidates/next24h_fallback/development-2026-10-02"
)
DEFAULT_PRIMARY_DIR = Path(
    "artifacts/models/candidates/next24h/development-2026-09-21"
)


def estimator_factory(model_name: str):
    if model_name == "Linear Regression":
        return lambda: make_pipeline(StandardScaler(), LinearRegression())
    if model_name == "Histogram Gradient Boosting":
        return lambda: HistGradientBoostingRegressor(
            max_iter=80,
            max_leaf_nodes=15,
            min_samples_leaf=50,
            l2_regularization=1.0,
            random_state=42,
        )
    if model_name == "Random Forest":
        return lambda: RandomForestRegressor(
            n_estimators=40,
            max_depth=18,
            min_samples_leaf=5,
            max_features=0.8,
            n_jobs=4,
            random_state=42,
        )
    raise ValueError(f"Unknown fallback v2 model: {model_name}")


def fit_horizon_model(model_name: str, training: pd.DataFrame):
    factory = estimator_factory(model_name)
    estimators = {}
    for horizon in HORIZONS:
        estimator = factory()
        estimator.fit(
            prepare_horizon_features(training, horizon),
            training[f"target_price_{horizon}h"].to_numpy(),
        )
        estimators[horizon] = estimator
    return HorizonSpecificFallbackModel(estimators)


def _reference_metric_rows(
    v1_dir: Path,
    primary_dir: Path,
) -> pd.DataFrame:
    v1_manifest = json.loads((v1_dir / "candidate_manifest.json").read_text())
    primary_manifest = json.loads((primary_dir / "candidate_manifest.json").read_text())
    references = []
    for directory, manifest, architecture in (
        (v1_dir, v1_manifest, "fallback_v1"),
        (primary_dir, primary_manifest, "primary_hgb_context_only"),
    ):
        metrics = pd.read_csv(directory / "metrics_by_horizon.csv")
        rows = metrics.loc[
            (metrics["model_name"] == manifest["model_name"])
        ].copy()
        rows.insert(0, "architecture", architecture)
        references.append(rows)
    return pd.concat(references, ignore_index=True)


def _reference_extreme_rows(v1_dir: Path, primary_dir: Path) -> pd.DataFrame:
    v1_manifest = json.loads((v1_dir / "candidate_manifest.json").read_text())
    primary_manifest = json.loads((primary_dir / "candidate_manifest.json").read_text())
    references = []
    for directory, manifest, architecture in (
        (v1_dir, v1_manifest, "fallback_v1"),
        (primary_dir, primary_manifest, "primary_hgb_context_only"),
    ):
        metrics = pd.read_csv(directory / "extreme_price_metrics.csv")
        rows = metrics.loc[metrics["model_name"] == manifest["model_name"]].copy()
        rows["price_regime"] = rows["price_regime"].replace(
            {"extreme_high_price": "price_gte_200_eur_mwh"}
        )
        rows.insert(0, "architecture", architecture)
        references.append(rows)
    return pd.concat(references, ignore_index=True)


def evaluate(
    silver_path: Path = DEFAULT_SILVER,
    output_dir: Path = DEFAULT_OUTPUT,
    v1_dir: Path = DEFAULT_V1_DIR,
    primary_dir: Path = DEFAULT_PRIMARY_DIR,
):
    silver_path, output_dir = Path(silver_path), Path(output_dir)
    v1_dir, primary_dir = Path(v1_dir), Path(primary_dir)
    if output_dir.exists():
        raise FileExistsError(f"Fallback v2 output already exists: {output_dir}")
    silver = pd.read_csv(silver_path, low_memory=False)
    splits = chronological_splits(build_fallback_training_data(silver))
    train = splits["train"]
    metrics, extremes, trained = [], [], {}

    for name in ("Linear Regression", "Histogram Gradient Boosting", "Random Forest"):
        print(
            f"Fitting fallback v2 {name} across 24 horizons on {len(train)} issue times...",
            flush=True,
        )
        model = fit_horizon_model(name, train)
        trained[name] = model
        validation = splits["validation"]
        actual = validation[list(TARGET_COLUMNS)].to_numpy()
        predicted = model.predict(validation)
        metrics.extend(metric_rows(name, "validation", actual, predicted))
        extremes.extend(extreme_metric_rows(name, "validation", actual, predicted))

    validation = splits["validation"]
    actual = validation[list(TARGET_COLUMNS)].to_numpy()
    persistence = np.repeat(
        validation[[PERSISTENCE_BENCHMARK_COLUMN]].to_numpy(), 24, axis=1
    )
    benchmark_name = "Persistence (benchmark only)"
    metrics.extend(metric_rows(benchmark_name, "validation", actual, persistence))
    extremes.extend(extreme_metric_rows(benchmark_name, "validation", actual, persistence))
    selected = select_candidate(pd.DataFrame(metrics))

    test = splits["test"]
    actual = test[list(TARGET_COLUMNS)].to_numpy()
    for name, model in trained.items():
        predicted = model.predict(test)
        metrics.extend(metric_rows(name, "test", actual, predicted))
        extremes.extend(extreme_metric_rows(name, "test", actual, predicted))
    persistence = np.repeat(test[[PERSISTENCE_BENCHMARK_COLUMN]].to_numpy(), 24, axis=1)
    metrics.extend(metric_rows(benchmark_name, "test", actual, persistence))
    extremes.extend(extreme_metric_rows(benchmark_name, "test", actual, persistence))

    metric_table, extreme_table = pd.DataFrame(metrics), pd.DataFrame(extremes)
    output_dir.mkdir(parents=True, exist_ok=False)
    model_file = selected.lower().replace(" ", "_") + "_horizon_models.joblib"
    model_path = output_dir / model_file
    joblib.dump(trained[selected], model_path)
    manifest = {
        "release_type": "next24h_fallback_v2_candidate_not_promoted",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_promoted": False,
        "architecture": "one_direct_estimator_per_horizon_with_target_calendar",
        "model_name": selected,
        "model_file": model_file,
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "base_features": list(FALLBACK_FEATURES),
        "target_calendar_features": list(TARGET_CALENDAR_FEATURES),
        "features_per_horizon": list(FALLBACK_V2_HORIZON_FEATURES),
        "feature_count_per_horizon": len(FALLBACK_V2_HORIZON_FEATURES),
        "horizons_hours": list(HORIZONS),
        "source_silver_path": str(silver_path),
        "source_silver_sha256": hashlib.sha256(silver_path.read_bytes()).hexdigest(),
        "selection_rule": "Validation overall RMSE; simplest within 2% of best",
        "validation_start": VALIDATION_START.isoformat(),
        "test_start": TEST_START.isoformat(),
        "training_rows": len(train),
        "validation_rows": len(validation),
        "test_rows": len(test),
        "price_derived_inference_features_excluded": True,
        "future_observed_inference_features_excluded": True,
        "target_calendar_derivation": "forecast_issue_time + horizon_hours in UTC",
        "inference_feature_statement": (
            "Each horizon uses issue-time fallback v1 inputs plus deterministic target-time "
            "calendar fields. No future observed price, load, generation, or weather enters "
            "inference. Persistence remains evaluation-only."
        ),
        "v1_reference_manifest_sha256": hashlib.sha256(
            (v1_dir / "candidate_manifest.json").read_bytes()
        ).hexdigest(),
        "primary_reference_manifest_sha256": hashlib.sha256(
            (primary_dir / "candidate_manifest.json").read_bytes()
        ).hexdigest(),
    }
    manifest_path = output_dir / "candidate_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    metric_table.to_csv(output_dir / "metrics_by_horizon.csv", index=False)
    extreme_table.to_csv(output_dir / "extreme_price_metrics.csv", index=False)

    references = _reference_metric_rows(v1_dir, primary_dir)
    v2_metrics = metric_table.loc[
        (metric_table["model_name"] == selected)
    ].copy()
    v2_metrics.insert(0, "architecture", "fallback_v2")
    comparison = pd.concat([references, v2_metrics], ignore_index=True)
    comparison.loc[comparison["horizon_hours"] == 0].to_csv(
        output_dir / "architecture_comparison.csv", index=False
    )
    comparison.loc[comparison["horizon_hours"] != 0].to_csv(
        output_dir / "horizon_architecture_comparison.csv", index=False
    )

    extreme_references = _reference_extreme_rows(v1_dir, primary_dir)
    v2_extremes = extreme_table.loc[extreme_table["model_name"] == selected].copy()
    v2_extremes.insert(0, "architecture", "fallback_v2")
    pd.concat([extreme_references, v2_extremes], ignore_index=True).to_csv(
        output_dir / "extreme_architecture_comparison.csv", index=False
    )

    loaded, recorded = load_fallback_v2_candidate(model_path, manifest_path)
    latest = build_fallback_issue_features(silver).tail(1).rename(
        columns={"timestamp": ISSUE_TIME}
    )
    example = create_fallback_v2_forecast(
        latest,
        loaded,
        model_release=output_dir.name,
    )
    example.to_csv(output_dir / "example_next24h_fallback_v2_forecast.csv", index=False)
    print(f"Fallback v2 selected from validation only: {selected}")
    print(f"Fallback v2 files saved under {output_dir}")
    return metric_table, extreme_table, manifest


def main():
    parser = argparse.ArgumentParser(description="Offline next24h fallback v2 evaluation.")
    parser.add_argument("--silver", type=Path, default=DEFAULT_SILVER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--v1-dir", type=Path, default=DEFAULT_V1_DIR)
    parser.add_argument("--primary-dir", type=Path, default=DEFAULT_PRIMARY_DIR)
    args = parser.parse_args()
    evaluate(args.silver, args.output_dir, args.v1_dir, args.primary_dir)


if __name__ == "__main__":
    main()
