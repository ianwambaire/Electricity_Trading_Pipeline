import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from dashboard_data import load_final_release_metadata
from models.final_evaluation import FINAL_FEATURES, build_final_model
from models.final_model_runtime import (
    load_final_model_release,
    prepare_prediction_features,
    validate_release_feature_order,
)
from models.prediction_visualization import create_prediction_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINAL_RELEASE_MANIFEST = (
    PROJECT_ROOT / "artifacts" / "models" / "final_model_release_manifest.json"
)
FINAL_HOLDOUT_METRICS = PROJECT_ROOT / "data" / "reports" / "final_holdout_metrics.csv"

FINAL_HOLDOUT_METRICS_COLUMNS = [
    "model_name",
    "feature_group",
    "feature_count",
    "training_rows",
    "holdout_rows",
    "training_start",
    "training_end",
    "holdout_start",
    "holdout_end",
    "mae",
    "rmse",
    "r2",
    "rmse_improvement_vs_persistence_pct",
    "best_seasonal_baseline",
    "best_seasonal_rmse",
    "rmse_improvement_vs_best_seasonal_pct",
]


def feature_frame(row_count=3):
    data = pd.DataFrame(
        {
            feature: np.arange(row_count, dtype="float64") + position
            for position, feature in enumerate(FINAL_FEATURES)
        }
    )
    return data


def test_final_artifacts_load_with_exact_31_feature_release(tmp_path):
    model_path = tmp_path / "final_gold_model.joblib"
    features_path = tmp_path / "final_gold_model_features.joblib"
    joblib.dump(build_final_model(), model_path)
    joblib.dump(list(FINAL_FEATURES), features_path)

    model, features = load_final_model_release(model_path, features_path)

    assert list(model.named_steps) == ["scaler", "model"]
    assert features == list(FINAL_FEATURES)
    assert len(features) == 31


def test_feature_order_and_missing_features_fail_clearly():
    reordered = list(FINAL_FEATURES)
    reordered[0], reordered[1] = reordered[1], reordered[0]
    with pytest.raises(ValueError, match="feature order"):
        validate_release_feature_order(reordered)

    incomplete = feature_frame().drop(columns=[FINAL_FEATURES[-1]])
    with pytest.raises(ValueError, match=FINAL_FEATURES[-1]):
        prepare_prediction_features(incomplete, FINAL_FEATURES)


def test_prediction_output_uses_release_order_and_target_timestamps():
    class OrderedPredictionModel:
        def predict(self, features):
            assert features.columns.tolist() == list(FINAL_FEATURES)
            return np.array([11.0, 12.0])

    data = feature_frame(2)
    data.insert(
        0,
        "timestamp",
        ["2025-01-01T00:00:00Z", "2025-01-01T01:00:00Z"],
    )
    data["target_price_next_hour"] = [10.0, 13.0]

    output = create_prediction_output(
        data,
        OrderedPredictionModel(),
        FINAL_FEATURES,
        "2025-01-01T01:00:00Z",
        "2025-01-01T02:00:00Z",
    )

    assert output.columns.tolist() == [
        "timestamp",
        "actual_price",
        "predicted_price",
    ]
    assert output["predicted_price"].tolist() == [11.0, 12.0]
    assert pd.to_datetime(output["timestamp"], utc=True).tolist() == list(
        pd.to_datetime(
            ["2025-01-01T01:00:00Z", "2025-01-01T02:00:00Z"],
            utc=True,
        )
    )


def test_dashboard_metadata_loads_final_release_values(tmp_path):
    manifest_path = tmp_path / "final_manifest.json"
    metrics_path = tmp_path / "metrics.csv"
    manifest_path.write_text(
        json.dumps(
            {
                "model": {
                    "selected_model": "Ordinary Linear Regression",
                    "selected_feature_group": "Full PowerFlow",
                    "feature_count": 31,
                },
                "final_holdout": {
                    "target_date_range": {
                        "start": "2025-01-01T00:00:00+00:00",
                        "end": "2025-09-30T23:00:00+00:00",
                    },
                    "rows": 6552,
                    "metrics": {"mae": 1, "rmse": 2, "r2": 0.5},
                },
                "rmse_improvements": {"vs_persistence_pct": 3},
                "mlflow_run_id": "release-run",
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "mae": 10.786919,
                "rmse": 18.885686,
                "r2": 0.879444,
                "holdout_start": "2025-01-01T00:00:00+00:00",
                "holdout_end": "2025-09-30T23:00:00+00:00",
                "rmse_improvement_vs_persistence_pct": 19.758421,
            }
        ]
    ).to_csv(metrics_path, index=False)

    metadata, error = load_final_release_metadata(manifest_path, metrics_path)

    assert error is None
    assert metadata["model_name"] == "Ordinary Linear Regression"
    assert metadata["feature_count"] == 31
    assert metadata["rmse"] == pytest.approx(18.885686)
    assert metadata["improvement_vs_persistence_pct"] == pytest.approx(19.758421)


def test_canonical_final_holdout_metrics_match_frozen_release_manifest():
    manifest = json.loads(FINAL_RELEASE_MANIFEST.read_text(encoding="utf-8"))
    report = pd.read_csv(FINAL_HOLDOUT_METRICS)

    assert report.columns.tolist() == FINAL_HOLDOUT_METRICS_COLUMNS
    assert len(report) == 1

    row = report.iloc[0]
    model = manifest["model"]
    training = manifest["training"]
    holdout = manifest["final_holdout"]
    improvements = manifest["rmse_improvements"]
    seasonal_baseline = next(
        baseline
        for baseline in manifest["baseline_comparisons"]
        if baseline["baseline_name"] == improvements["best_seasonal_baseline"]
    )

    assert row["model_name"] == model["selected_model"]
    assert row["feature_group"] == model["selected_feature_group"]
    assert row["feature_count"] == model["feature_count"]
    assert row["training_rows"] == training["rows"]
    assert row["holdout_rows"] == holdout["rows"]
    assert row["training_start"] == training["target_date_range"]["start"]
    assert row["training_end"] == training["target_date_range"]["end"]
    assert row["holdout_start"] == holdout["target_date_range"]["start"]
    assert row["holdout_end"] == holdout["target_date_range"]["end"]
    assert row["mae"] == pytest.approx(holdout["metrics"]["mae"])
    assert row["rmse"] == pytest.approx(holdout["metrics"]["rmse"])
    assert row["r2"] == pytest.approx(holdout["metrics"]["r2"])
    assert row["rmse_improvement_vs_persistence_pct"] == pytest.approx(
        improvements["vs_persistence_pct"]
    )
    assert row["best_seasonal_baseline"] == improvements["best_seasonal_baseline"]
    assert row["best_seasonal_rmse"] == pytest.approx(seasonal_baseline["rmse"])
    assert row["rmse_improvement_vs_best_seasonal_pct"] == pytest.approx(
        improvements["vs_best_seasonal_pct"]
    )


def test_primary_prefect_flow_never_invokes_final_holdout_evaluation():
    source = (PROJECT_ROOT / "src" / "scheduled_pipeline.py").read_text(
        encoding="utf-8"
    )

    assert "run_final_holdout_evaluation" not in source
    assert "train_gold_model.py" not in source
    assert "verify_final_model_release_task()" in source
    assert "prediction_report_task(mode)" in source
