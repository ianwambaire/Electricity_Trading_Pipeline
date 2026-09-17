import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

if __package__:
    from .artifact_metadata import calculate_file_sha256
    from .backtesting import (
        BASELINE_NAMES,
        TARGET_COLUMN,
        build_baseline_predictions,
        calculate_forecast_metrics,
        calculate_rmse_improvement,
        forecast_timestamps,
    )
    from .research_evaluation import FEATURE_GROUPS, REGIME_LABELS, assign_price_regimes
else:
    from artifact_metadata import calculate_file_sha256
    from backtesting import (
        BASELINE_NAMES,
        TARGET_COLUMN,
        build_baseline_predictions,
        calculate_forecast_metrics,
        calculate_rmse_improvement,
        forecast_timestamps,
    )
    from research_evaluation import FEATURE_GROUPS, REGIME_LABELS, assign_price_regimes


FINAL_MODEL_NAME = "Ordinary Linear Regression"
FINAL_FEATURE_GROUP = "Full PowerFlow"
FINAL_FEATURES = tuple(FEATURE_GROUPS[FINAL_FEATURE_GROUP])
FINAL_HOLDOUT_START = pd.Timestamp("2025-01-01T00:00:00Z")
FINAL_HOLDOUT_END = pd.Timestamp("2025-09-30T23:00:00Z")


@dataclass(frozen=True)
class FinalChronologicalSplit:
    training_data: pd.DataFrame
    holdout_data: pd.DataFrame
    training_target_times: pd.Series
    holdout_target_times: pd.Series


def validate_frozen_features(data: pd.DataFrame) -> None:
    available = set(data.columns) - {"timestamp", TARGET_COLUMN}
    frozen = set(FINAL_FEATURES)
    if len(FINAL_FEATURES) != 31 or len(frozen) != 31:
        raise ValueError("The frozen Full PowerFlow feature set must contain 31 features.")
    if available != frozen:
        raise ValueError(
            "Gold feature schema does not match the frozen 31-feature release schema; "
            f"missing={sorted(frozen - available)}, unexpected={sorted(available - frozen)}."
        )


def build_final_model() -> Pipeline:
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            ("model", LinearRegression()),
        ]
    )


def final_chronological_split(data: pd.DataFrame) -> FinalChronologicalSplit:
    target_times = forecast_timestamps(data)
    training_mask = target_times < FINAL_HOLDOUT_START
    holdout_mask = (target_times >= FINAL_HOLDOUT_START) & (
        target_times <= FINAL_HOLDOUT_END
    )
    if (target_times > FINAL_HOLDOUT_END).any():
        raise ValueError("Gold data extends beyond the frozen final holdout period.")

    training_data = data.loc[training_mask].copy()
    holdout_data = data.loc[holdout_mask].copy()
    training_target_times = target_times.loc[training_mask]
    holdout_target_times = target_times.loc[holdout_mask]
    if training_data.empty or holdout_data.empty:
        raise ValueError("Both development training and final holdout rows are required.")
    if holdout_target_times.min() != FINAL_HOLDOUT_START:
        raise ValueError("Final holdout does not begin at 2025-01-01 00:00 UTC.")
    if holdout_target_times.max() != FINAL_HOLDOUT_END:
        raise ValueError("Final holdout does not end at 2025-09-30 23:00 UTC.")
    if training_target_times.max() >= holdout_target_times.min():
        raise ValueError("Training and final holdout periods overlap.")

    return FinalChronologicalSplit(
        training_data=training_data,
        holdout_data=holdout_data,
        training_target_times=training_target_times,
        holdout_target_times=holdout_target_times,
    )


def fit_and_predict_final_model(
    split: FinalChronologicalSplit,
    model=None,
):
    frozen_model = model if model is not None else build_final_model()
    frozen_model.fit(
        split.training_data[list(FINAL_FEATURES)],
        split.training_data[TARGET_COLUMN],
    )
    predictions = frozen_model.predict(split.holdout_data[list(FINAL_FEATURES)])
    return frozen_model, predictions


def build_final_metrics(
    split: FinalChronologicalSplit,
    predictions,
    baseline_results: pd.DataFrame,
) -> pd.DataFrame:
    metrics = calculate_forecast_metrics(
        split.holdout_data[TARGET_COLUMN],
        predictions,
    )
    persistence_rmse = baseline_results.loc[
        baseline_results["baseline_name"] == "Persistence Baseline",
        "rmse",
    ].item()
    seasonal = baseline_results[
        baseline_results["baseline_name"].isin(
            {"Daily Seasonal Naive", "Weekly Seasonal Naive"}
        )
    ].sort_values("rmse")
    best_seasonal = seasonal.iloc[0]

    return pd.DataFrame(
        [
            {
                "model_name": FINAL_MODEL_NAME,
                "feature_group": FINAL_FEATURE_GROUP,
                "feature_count": len(FINAL_FEATURES),
                "training_rows": len(split.training_data),
                "holdout_rows": len(split.holdout_data),
                "training_start": split.training_target_times.min().isoformat(),
                "training_end": split.training_target_times.max().isoformat(),
                "holdout_start": split.holdout_target_times.min().isoformat(),
                "holdout_end": split.holdout_target_times.max().isoformat(),
                **metrics,
                "rmse_improvement_vs_persistence_pct": calculate_rmse_improvement(
                    metrics["rmse"], persistence_rmse
                ),
                "best_seasonal_baseline": best_seasonal["baseline_name"],
                "best_seasonal_rmse": best_seasonal["rmse"],
                "rmse_improvement_vs_best_seasonal_pct": calculate_rmse_improvement(
                    metrics["rmse"], best_seasonal["rmse"]
                ),
            }
        ]
    )


def evaluate_final_baselines(
    data: pd.DataFrame,
    split: FinalChronologicalSplit,
) -> pd.DataFrame:
    baseline_predictions = build_baseline_predictions(data)
    rows = []
    for baseline_name in BASELINE_NAMES:
        predictions = baseline_predictions.loc[split.holdout_data.index, baseline_name]
        if predictions.isna().any():
            raise ValueError(f"{baseline_name} has missing final-holdout predictions.")
        rows.append(
            {
                "baseline_name": baseline_name,
                "holdout_rows": len(split.holdout_data),
                "holdout_start": split.holdout_target_times.min().isoformat(),
                "holdout_end": split.holdout_target_times.max().isoformat(),
                **calculate_forecast_metrics(
                    split.holdout_data[TARGET_COLUMN],
                    predictions,
                ),
            }
        )
    return pd.DataFrame(rows)


def build_final_regime_performance(
    split: FinalChronologicalSplit,
    predictions,
) -> pd.DataFrame:
    evaluated = pd.DataFrame(
        {
            "actual": split.holdout_data[TARGET_COLUMN].to_numpy(),
            "predicted": predictions,
        }
    )
    evaluated["price_regime"] = assign_price_regimes(evaluated["actual"])
    rows = []
    for regime in REGIME_LABELS:
        regime_rows = evaluated[evaluated["price_regime"] == regime]
        row = {
            "model_name": FINAL_MODEL_NAME,
            "price_regime": regime,
            "observation_count": len(regime_rows),
            "mae": float("nan"),
            "rmse": float("nan"),
            "mean_signed_error_bias": float("nan"),
        }
        if not regime_rows.empty:
            metrics = calculate_forecast_metrics(
                regime_rows["actual"],
                regime_rows["predicted"],
            )
            row.update(
                {
                    "mae": metrics["mae"],
                    "rmse": metrics["rmse"],
                    "mean_signed_error_bias": float(
                        (regime_rows["predicted"] - regime_rows["actual"]).mean()
                    ),
                }
            )
        rows.append(row)
    return pd.DataFrame(rows)


def ensure_release_not_completed(manifest_path: Path) -> None:
    if Path(manifest_path).exists():
        raise FileExistsError(
            f"Final holdout release already exists at {manifest_path}; "
            "refusing to evaluate the frozen holdout again."
        )


def write_final_release_manifest(
    *,
    manifest_path: Path,
    dataset_path: Path,
    data: pd.DataFrame,
    split: FinalChronologicalSplit,
    metrics: pd.DataFrame,
    baselines: pd.DataFrame,
    git_commit_sha: str | None,
    mlflow_run_id: str,
    model_path: Path,
    feature_path: Path,
    metrics_path: Path,
    baselines_path: Path,
    regime_path: Path,
) -> dict:
    dataset_sha256 = calculate_file_sha256(dataset_path)
    metric_row = metrics.iloc[0]
    manifest = {
        "manifest_schema_version": 1,
        "release_type": "final_2025_holdout_evaluation",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "final_holdout_used": True,
        "dataset": {
            "path": str(dataset_path),
            "sha256": dataset_sha256,
            "version": f"gold-sha256-{dataset_sha256}",
            "source_date_range": {
                "start": pd.to_datetime(data["timestamp"], utc=True).min().isoformat(),
                "end": pd.to_datetime(data["timestamp"], utc=True).max().isoformat(),
            },
        },
        "training": {
            "target_date_range": {
                "start": split.training_target_times.min().isoformat(),
                "end": split.training_target_times.max().isoformat(),
            },
            "rows": len(split.training_data),
        },
        "final_holdout": {
            "target_date_range": {
                "start": split.holdout_target_times.min().isoformat(),
                "end": split.holdout_target_times.max().isoformat(),
            },
            "rows": len(split.holdout_data),
            "metrics": {
                "mae": float(metric_row["mae"]),
                "rmse": float(metric_row["rmse"]),
                "r2": float(metric_row["r2"]),
            },
        },
        "model": {
            "selected_model": FINAL_MODEL_NAME,
            "selected_feature_group": FINAL_FEATURE_GROUP,
            "feature_count": len(FINAL_FEATURES),
            "hyperparameters_selected_using_holdout": False,
        },
        "baseline_comparisons": baselines.to_dict(orient="records"),
        "rmse_improvements": {
            "vs_persistence_pct": float(
                metric_row["rmse_improvement_vs_persistence_pct"]
            ),
            "best_seasonal_baseline": metric_row["best_seasonal_baseline"],
            "vs_best_seasonal_pct": float(
                metric_row["rmse_improvement_vs_best_seasonal_pct"]
            ),
        },
        "git_commit_sha": git_commit_sha,
        "mlflow_run_id": mlflow_run_id,
        "artifacts": {
            "model_path": str(model_path),
            "feature_list_path": str(feature_path),
            "metrics_report_path": str(metrics_path),
            "baselines_report_path": str(baselines_path),
            "regime_report_path": str(regime_path),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
