import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


MANIFEST_SCHEMA_VERSION = 2


def calculate_file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()

    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)

    return digest.hexdigest()


def generate_dataset_version(path: Path) -> str:
    """Return a deterministic identifier for the exact dataset file bytes."""
    return f"gold-sha256-{calculate_file_sha256(path)}"


def get_git_commit_sha(project_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    commit_sha = result.stdout.strip()
    return commit_sha or None


def write_training_manifest(
    *,
    manifest_path: Path,
    dataset_path: Path,
    source_start: str,
    source_end: str,
    gold_row_count: int,
    feature_count: int,
    train_row_count: int,
    test_row_count: int,
    selected_model: str,
    selection_method: str,
    cv_method: str,
    cv_splits: int,
    best_hyperparameters: dict,
    mae: float,
    rmse: float,
    r2: float,
    mlflow_run_id: str | None,
    git_commit_sha: str | None,
    model_path: Path,
    feature_list_path: Path,
    comparison_path: Path,
    training_timestamp: str | None = None,
) -> dict:
    dataset_path = Path(dataset_path)
    manifest_path = Path(manifest_path)
    dataset_sha256 = calculate_file_sha256(dataset_path)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset": {
            "version": f"gold-sha256-{dataset_sha256}",
            "sha256": dataset_sha256,
            "path": str(dataset_path),
            "source_date_range": {
                "start": source_start,
                "end": source_end,
            },
            "gold_row_count": int(gold_row_count),
        },
        "training": {
            "timestamp_utc": training_timestamp
            or datetime.now(timezone.utc).isoformat(),
            "feature_count": int(feature_count),
            "train_row_count": int(train_row_count),
            "test_row_count": int(test_row_count),
            "selected_model": selected_model,
            "selection_method": selection_method,
            "cross_validation": {
                "method": cv_method,
                "splits": int(cv_splits),
                "scoring": "RMSE",
            },
            "best_hyperparameters": best_hyperparameters,
            "final_metrics": {
                "mae": float(mae),
                "rmse": float(rmse),
                "r2": float(r2),
            },
            "mlflow_run_id": mlflow_run_id,
            "git_commit_sha": git_commit_sha,
        },
        "artifacts": {
            "model_path": str(model_path),
            "feature_list_path": str(feature_list_path),
            "comparison_path": str(comparison_path),
        },
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)
        file.write("\n")

    return manifest
