import json

from models.artifact_metadata import (
    calculate_file_sha256,
    generate_dataset_version,
    write_training_manifest,
)


def test_dataset_version_is_deterministic_and_content_based(tmp_path):
    first_dataset = tmp_path / "gold_a.csv"
    second_dataset = tmp_path / "gold_b.csv"
    first_dataset.write_bytes(b"timestamp,target\n2024-01-01,10.0\n")
    second_dataset.write_bytes(first_dataset.read_bytes())

    first_version = generate_dataset_version(first_dataset)
    second_version = generate_dataset_version(second_dataset)

    assert first_version == second_version
    assert first_version == f"gold-sha256-{calculate_file_sha256(first_dataset)}"

    second_dataset.write_bytes(b"timestamp,target\n2024-01-01,11.0\n")
    assert generate_dataset_version(second_dataset) != first_version


def test_training_manifest_records_reproducibility_metadata(tmp_path):
    dataset_path = tmp_path / "gold.csv"
    manifest_path = tmp_path / "artifacts" / "training_manifest.json"
    model_path = tmp_path / "artifacts" / "best_gold_model.joblib"
    feature_list_path = tmp_path / "artifacts" / "gold_model_features.joblib"
    comparison_path = tmp_path / "reports" / "gold_model_comparison.csv"
    dataset_path.write_text(
        "timestamp,target_price_next_hour\n2024-01-01T00:00:00Z,10.0\n",
        encoding="utf-8",
    )

    manifest = write_training_manifest(
        manifest_path=manifest_path,
        dataset_path=dataset_path,
        source_start="2024-01-01T00:00:00+00:00",
        source_end="2024-01-01T00:00:00+00:00",
        gold_row_count=10,
        feature_count=31,
        train_row_count=8,
        test_row_count=2,
        selected_model="XGBoost",
        selection_method="lowest_time_series_cv_rmse",
        cv_method="TimeSeriesSplit",
        cv_splits=3,
        best_hyperparameters={"max_depth": 6},
        mae=9.1,
        rmse=19.0,
        r2=0.9,
        mlflow_run_id="test-run-id",
        git_commit_sha="abc123",
        model_path=model_path,
        feature_list_path=feature_list_path,
        comparison_path=comparison_path,
        training_timestamp="2026-01-01T00:00:00+00:00",
    )

    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert saved_manifest == manifest
    assert manifest["dataset"]["version"].startswith("gold-sha256-")
    assert manifest["dataset"]["gold_row_count"] == 10
    assert manifest["training"] == {
        "timestamp_utc": "2026-01-01T00:00:00+00:00",
        "feature_count": 31,
        "train_row_count": 8,
        "test_row_count": 2,
        "selected_model": "XGBoost",
        "selection_method": "lowest_time_series_cv_rmse",
        "cross_validation": {
            "method": "TimeSeriesSplit",
            "splits": 3,
            "scoring": "RMSE",
        },
        "best_hyperparameters": {"max_depth": 6},
        "final_metrics": {"mae": 9.1, "rmse": 19.0, "r2": 0.9},
        "mlflow_run_id": "test-run-id",
        "git_commit_sha": "abc123",
    }
