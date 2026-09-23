"""Verify the EC2 runtime imports and frozen release without running the pipeline."""

from __future__ import annotations

import importlib
import importlib.abc
import json
import os
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

RUNTIME_CACHE = Path(tempfile.gettempdir()) / "powerflow-production-import-check"
RUNTIME_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(RUNTIME_CACHE / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(RUNTIME_CACHE / "xdg"))

BLOCKED_RESEARCH_PACKAGES = {"mlflow", "xgboost"}
REQUIRED_DISTRIBUTIONS = (
    "awscrt",
    "boto3",
    "entsoe-py",
    "joblib",
    "matplotlib",
    "numpy",
    "pandas",
    "plotly",
    "prefect",
    "python-dotenv",
    "requests",
    "scikit-learn",
    "streamlit",
)
PRODUCTION_MODULES = (
    "dashboard_data",
    "dashboard_health",
    "ingestion.fetch_entsoe_data",
    "ingestion.fetch_weather_data",
    "ingestion.incremental_utils",
    "models.feature_importance",
    "models.final_model_runtime",
    "models.next24h_production",
    "models.next24h_monitoring",
    "models.prediction_visualization",
    "operational_recovery",
    "presentation_snapshot",
    "powerflow_secrets",
    "processing.build_gold_dataset",
    "processing.build_silver_dataset",
    "scheduled_pipeline",
    "storage",
    "store_data",
    "validate_data",
)


class _BlockResearchImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in BLOCKED_RESEARCH_PACKAGES:
            raise ImportError(
                f"Production verification attempted to import excluded package {fullname!r}."
            )
        return None


def main() -> None:
    requirements = (PROJECT_ROOT / "requirements-prod.txt").read_text(
        encoding="utf-8"
    ).lower()
    forbidden = [name for name in BLOCKED_RESEARCH_PACKAGES if name in requirements]
    if forbidden:
        raise RuntimeError(
            "Research-only packages found in production requirements: "
            + ", ".join(sorted(forbidden))
        )

    blocker = _BlockResearchImports()
    sys.meta_path.insert(0, blocker)
    try:
        for module_name in PRODUCTION_MODULES:
            importlib.import_module(module_name)

        # These entry points execute UI or report logic at module import time, so
        # compile them and import their third-party runtime dependencies instead.
        for relative_path in (
            "src/dashboard.py",
            "src/models/anomaly_detection.py",
        ):
            source_path = PROJECT_ROOT / relative_path
            compile(source_path.read_bytes(), str(source_path), "exec")
        importlib.import_module("plotly.express")
        importlib.import_module("plotly.graph_objects")
        importlib.import_module("sklearn.ensemble")
        importlib.import_module("streamlit")

        from models.final_model_runtime import (
            load_final_model_release,
            predict_with_final_model,
        )

        model, features = load_final_model_release(
            PROJECT_ROOT / "artifacts/models/final_gold_model.joblib",
            PROJECT_ROOT / "artifacts/models/final_gold_model_features.joblib",
        )
        if len(features) != 31:
            raise RuntimeError(f"Expected 31 frozen features, found {len(features)}.")

        pandas = importlib.import_module("pandas")
        probe = pandas.DataFrame([{feature: 0.0 for feature in features}])
        predictions = predict_with_final_model(probe, model, features)
        if len(predictions) != 1:
            raise RuntimeError("Frozen model inference probe returned an invalid result.")

        from models.next24h_production import load_next24h_release

        next24h_model, next24h_features, next24h_manifest = load_next24h_release(
            PROJECT_ROOT / "artifacts/models/releases/next24h"
        )
        next24h_probe = pandas.DataFrame(
            [{feature: 0.0 for feature in next24h_features}]
        )
        if next24h_model.predict(next24h_probe).shape != (1, 24):
            raise RuntimeError("Next24h release inference probe returned an invalid shape.")

        orchestration_source = (
            PROJECT_ROOT / "src/scheduled_pipeline.py"
        ).read_text(encoding="utf-8")
        forbidden_call = "run_" + "final_holdout_evaluation"
        if forbidden_call in orchestration_source:
            raise RuntimeError("Production orchestration references the final holdout evaluator.")
    finally:
        sys.meta_path.remove(blocker)

    print(
        json.dumps(
            {
                "dependencies": {
                    name: version(name) for name in REQUIRED_DISTRIBUTIONS
                },
                "excluded_research_imports": sorted(BLOCKED_RESEARCH_PACKAGES),
                "frozen_feature_count": len(features),
                "frozen_model_type": type(model).__qualname__,
                "inference_probe_rows": len(predictions),
                "next24h_release_id": next24h_manifest["release_id"],
                "next24h_feature_count": len(next24h_features),
                "production_modules_checked": list(PRODUCTION_MODULES),
                "status": "ok",
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
