"""Offline-only evaluation of direct next-24-hour model candidates."""

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
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.multioutput import MultiOutputRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from models.next24h import (
    FINAL_FEATURES,
    HORIZONS,
    ISSUE_TIME,
    build_training_data,
    create_next24h_forecast,
    load_candidate_model,
    prepare_candidate_features,
)


DEFAULT_SILVER = Path("data/processed/silver_electricity_market_data.csv")
DEFAULT_OUTPUT = Path("artifacts/models/candidates/next24h/development-2026")
VALIDATION_START = pd.Timestamp("2026-01-01T00:00Z")
TEST_START = pd.Timestamp("2026-05-01T00:00Z")
TARGET_COLUMNS = tuple(f"target_price_{h}h" for h in HORIZONS)
COMPLEXITY_ORDER = ("Linear Regression", "Histogram Gradient Boosting", "Random Forest")


def chronological_splits(data: pd.DataFrame):
    issue = pd.to_datetime(data[ISSUE_TIME], utc=True)
    last_target = pd.to_datetime(data["target_timestamp_24h"], utc=True)
    if not issue.is_unique or not issue.is_monotonic_increasing:
        raise ValueError("Training issue times must be unique and ordered.")
    train = data.loc[last_target < VALIDATION_START].copy()
    validation = data.loc[
        (issue >= VALIDATION_START) & (last_target < TEST_START)
    ].copy()
    test = data.loc[issue >= TEST_START].copy()
    if any(part.empty for part in (train, validation, test)):
        raise ValueError("All three chronological periods must contain complete targets.")
    if not (
        train["target_timestamp_24h"].max() < validation[ISSUE_TIME].min()
        and validation["target_timestamp_24h"].max() < test[ISSUE_TIME].min()
    ):
        raise ValueError("Target windows cross a chronological split boundary.")
    return {"train": train, "validation": validation, "test": test}


def candidate_models():
    return {
        "Linear Regression": make_pipeline(StandardScaler(), LinearRegression()),
        "Random Forest": RandomForestRegressor(
            n_estimators=80,
            max_depth=18,
            min_samples_leaf=5,
            max_features=0.8,
            n_jobs=4,
            random_state=42,
        ),
        "Histogram Gradient Boosting": MultiOutputRegressor(
            HistGradientBoostingRegressor(
                max_iter=80,
                max_leaf_nodes=15,
                min_samples_leaf=50,
                l2_regularization=1.0,
                random_state=42,
            ),
            n_jobs=4,
        ),
    }


def metric_rows(name, split_name, actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if actual.shape != predicted.shape or actual.ndim != 2 or actual.shape[1] != 24:
        raise ValueError("Evaluation requires matching 24-horizon prediction arrays.")
    rows = []
    for horizon in (0, *HORIZONS):
        y = actual.ravel() if horizon == 0 else actual[:, horizon - 1]
        p = predicted.ravel() if horizon == 0 else predicted[:, horizon - 1]
        rows.append(
            {
                "split": split_name,
                "model_name": name,
                "horizon_hours": horizon,
                "observations": len(y),
                "mae": float(mean_absolute_error(y, p)),
                "rmse": float(mean_squared_error(y, p) ** 0.5),
                "r2": float(r2_score(y, p)),
                "bias_predicted_minus_actual": float(np.mean(p - y)),
            }
        )
    return rows


def extreme_metric_rows(name, split_name, actual, predicted):
    actual = np.asarray(actual, dtype=float).ravel()
    predicted = np.asarray(predicted, dtype=float).ravel()
    rows = []
    for regime, mask in (
        ("negative_price", actual < 0),
        ("extreme_high_price", actual >= 200),
    ):
        rows.append(
            {
                "split": split_name,
                "model_name": name,
                "price_regime": regime,
                "observations": int(mask.sum()),
                "mae": float(mean_absolute_error(actual[mask], predicted[mask]))
                if mask.any() else float("nan"),
                "rmse": float(mean_squared_error(actual[mask], predicted[mask]) ** 0.5)
                if mask.any() else float("nan"),
                "bias_predicted_minus_actual": float(np.mean(predicted[mask] - actual[mask]))
                if mask.any() else float("nan"),
            }
        )
    return rows


def select_candidate(validation_metrics: pd.DataFrame) -> str:
    """Use validation RMSE only; prefer simpler models within 2% of best."""
    overall = validation_metrics.loc[
        (validation_metrics["split"] == "validation")
        & (validation_metrics["horizon_hours"] == 0)
        & (validation_metrics["model_name"] != "Persistence")
    ]
    best = overall["rmse"].min()
    eligible = set(overall.loc[overall["rmse"] <= best * 1.02, "model_name"])
    return next(name for name in COMPLEXITY_ORDER if name in eligible)


def evaluate(
    silver_path: Path = DEFAULT_SILVER,
    output_dir: Path = DEFAULT_OUTPUT,
):
    silver_path, output_dir = Path(silver_path), Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"Candidate output already exists: {output_dir}")
    silver = pd.read_csv(silver_path, low_memory=False)
    data = build_training_data(silver)
    splits = chronological_splits(data)
    train = splits["train"]
    x_train = prepare_candidate_features(train)
    y_train = train[list(TARGET_COLUMNS)].to_numpy()
    models = candidate_models()
    metrics, extremes = [], []
    trained = {}

    for name, model in models.items():
        print(f"Fitting {name} on {len(train)} issue times...", flush=True)
        model.fit(x_train, y_train)
        trained[name] = model
        period = splits["validation"]
        actual = period[list(TARGET_COLUMNS)].to_numpy()
        predicted = model.predict(prepare_candidate_features(period))
        metrics.extend(metric_rows(name, "validation", actual, predicted))
        extremes.extend(extreme_metric_rows(name, "validation", actual, predicted))

    period = splits["validation"]
    actual = period[list(TARGET_COLUMNS)].to_numpy()
    predicted = np.repeat(period[["price_eur_mwh"]].to_numpy(), 24, axis=1)
    metrics.extend(metric_rows("Persistence", "validation", actual, predicted))
    extremes.extend(extreme_metric_rows("Persistence", "validation", actual, predicted))
    selected = select_candidate(pd.DataFrame(metrics))

    # Only now inspect the untouched test period; it cannot change selection.
    period = splits["test"]
    actual = period[list(TARGET_COLUMNS)].to_numpy()
    for name, model in trained.items():
        predicted = model.predict(prepare_candidate_features(period))
        metrics.extend(metric_rows(name, "test", actual, predicted))
        extremes.extend(extreme_metric_rows(name, "test", actual, predicted))
    # Persistence uses only the price known at the forecast issue time.
    baseline = np.repeat(period[["price_eur_mwh"]].to_numpy(), 24, axis=1)
    metrics.extend(metric_rows("Persistence", "test", actual, baseline))
    extremes.extend(extreme_metric_rows("Persistence", "test", actual, baseline))

    metric_table = pd.DataFrame(metrics)
    extreme_table = pd.DataFrame(extremes)
    model_name = selected.lower().replace(" ", "_") + ".joblib"
    output_dir.mkdir(parents=True, exist_ok=False)
    model_path = output_dir / model_name
    joblib.dump(trained[selected], model_path)
    manifest = {
        "release_type": "next24h_candidate_not_promoted",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_promoted": False,
        "model_name": selected,
        "model_file": model_name,
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "features": list(FINAL_FEATURES),
        "horizons_hours": list(HORIZONS),
        "source_silver_path": str(silver_path),
        "source_silver_sha256": hashlib.sha256(silver_path.read_bytes()).hexdigest(),
        "selection_rule": "Validation overall RMSE; simplest within 2% of best",
        "validation_start": VALIDATION_START.isoformat(),
        "test_start": TEST_START.isoformat(),
        "training_rows": len(train),
        "validation_rows": len(splits["validation"]),
        "test_rows": len(splits["test"]),
    }
    manifest_path = output_dir / "candidate_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    metric_table.to_csv(output_dir / "metrics_by_horizon.csv", index=False)
    extreme_table.to_csv(output_dir / "extreme_price_metrics.csv", index=False)

    # Load the newly written candidate and verify its complete output contract.
    loaded, recorded = load_candidate_model(model_path, manifest_path)
    from models.next24h import build_issue_features

    latest_issue = build_issue_features(silver).tail(1).rename(columns={"timestamp": ISSUE_TIME})
    forecast = create_next24h_forecast(
        latest_issue, loaded, model_release=output_dir.name,
        features=recorded["features"],
    )
    forecast.to_csv(output_dir / "example_next24h_forecast.csv", index=False)
    print(f"Candidate selected from validation only: {selected}")
    print(f"Candidate files saved under {output_dir}")
    return metric_table, extreme_table, manifest


def main():
    parser = argparse.ArgumentParser(description="Offline next-24h candidate evaluation.")
    parser.add_argument("--silver", type=Path, default=DEFAULT_SILVER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    evaluate(args.silver, args.output_dir)


if __name__ == "__main__":
    main()
