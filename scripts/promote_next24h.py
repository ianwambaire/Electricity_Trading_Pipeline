"""Package the already-evaluated next-24-hour candidate; never fit a model."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models.final_evaluation import FINAL_FEATURES  # noqa: E402


CANDIDATE = ROOT / "artifacts/models/candidates/next24h/development-2026-09-21"
RELEASE = ROOT / "artifacts/models/releases/next24h"
VERSION = "next24h-hgb-2026-09-21-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(metrics: pd.DataFrame, split: str, model_name: str) -> dict:
    selected = metrics.loc[
        (metrics["split"] == split)
        & (metrics["model_name"] == model_name)
        & (metrics["horizon_hours"] == 0)
    ]
    if len(selected) != 1:
        raise ValueError(f"Expected one overall {split} metric for {model_name}.")
    row = selected.iloc[0]
    return {
        "observations": int(row["observations"]),
        "mae": float(row["mae"]),
        "rmse": float(row["rmse"]),
        "r2": float(row["r2"]),
        "bias_predicted_minus_actual": float(row["bias_predicted_minus_actual"]),
    }


def promote(candidate_dir: Path = CANDIDATE, release_dir: Path = RELEASE) -> Path:
    candidate_dir, release_dir = Path(candidate_dir), Path(release_dir)
    if release_dir.exists():
        raise FileExistsError(f"Release already exists: {release_dir}")

    candidate_manifest = json.loads(
        (candidate_dir / "candidate_manifest.json").read_text(encoding="utf-8")
    )
    source_model = candidate_dir / candidate_manifest["model_file"]
    if (
        candidate_manifest.get("release_type") != "next24h_candidate_not_promoted"
        or candidate_manifest.get("model_name") != "Histogram Gradient Boosting"
        or tuple(candidate_manifest.get("features", ())) != tuple(FINAL_FEATURES)
        or candidate_manifest.get("horizons_hours") != list(range(1, 25))
        or sha256(source_model) != candidate_manifest.get("model_sha256")
    ):
        raise ValueError("Approved candidate identity, contract, or hash is invalid.")

    metrics = pd.read_csv(candidate_dir / "metrics_by_horizon.csv")
    release_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="next24h-release-", dir=release_dir.parent) as staging:
        staged = Path(staging)
        model_path = staged / "next24h_model.joblib"
        contract_path = staged / "next24h_feature_contract.joblib"
        shutil.copyfile(source_model, model_path)
        joblib.dump(tuple(FINAL_FEATURES), contract_path)
        manifest = {
            "release_type": "next24h_production",
            "release_id": VERSION,
            "model_type": "Histogram Gradient Boosting (24 direct outputs)",
            "model_purpose": "next-24-hour electricity price forecasting",
            "candidate_evaluated_at_utc": candidate_manifest["created_at_utc"],
            "candidate_evaluation_date": candidate_manifest["created_at_utc"][:10],
            "training_evaluation_date": candidate_manifest["created_at_utc"][:10],
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "horizons_hours": list(range(1, 25)),
            "feature_count": len(FINAL_FEATURES),
            "features": list(FINAL_FEATURES),
            "model_file": model_path.name,
            "model_sha256": sha256(model_path),
            "feature_contract_file": contract_path.name,
            "feature_contract_sha256": sha256(contract_path),
            "validation_metrics": metric(metrics, "validation", "Histogram Gradient Boosting"),
            "test_metrics": metric(metrics, "test", "Histogram Gradient Boosting"),
            "persistence_test_metrics": metric(metrics, "test", "Persistence"),
            "known_limitations": [
                "Weaker performance during extreme electricity-price events.",
                "Future forecast weather is not used; inputs are observed through issue time.",
            ],
            "source_candidate_path": str(candidate_dir.relative_to(ROOT)),
            "source_candidate_model_sha256": candidate_manifest["model_sha256"],
            "selection_rule": candidate_manifest["selection_rule"],
            "validation_start": candidate_manifest["validation_start"],
            "test_start": candidate_manifest["test_start"],
        }
        (staged / "next24h_release_manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        staged.rename(release_dir)
    return release_dir


if __name__ == "__main__":
    print(promote())
