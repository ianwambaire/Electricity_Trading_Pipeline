from __future__ import annotations

from pathlib import Path


ARTIFACT_MAPPINGS = {
    "data/raw/entsoe/prices.csv": "raw/entsoe/prices/prices.csv",
    "data/raw/entsoe/load.csv": "raw/entsoe/load/load.csv",
    "data/raw/entsoe/generation.csv": "raw/entsoe/generation/generation.csv",
    "data/raw/weather/open_meteo_weather.csv": "raw/weather/open_meteo_weather.csv",
    "data/processed/silver_electricity_market_data.csv": "silver/silver_electricity_market_data.csv",
    "data/features/gold_model_features.csv": "gold/gold_model_features.csv",
    "data/reports/actual_vs_predicted.csv": "reports/predictions/actual_vs_predicted.csv",
    "data/reports/actual_vs_predicted.png": "reports/predictions/actual_vs_predicted.png",
    "data/reports/detected_anomalies.csv": "reports/anomalies/detected_anomalies.csv",
    "data/reports/anomaly_detection.png": "reports/anomalies/anomaly_detection.png",
    "data/reports/feature_importance.csv": "reports/monitoring/feature_importance.csv",
    "data/reports/feature_importance.png": "reports/monitoring/feature_importance.png",
    "artifacts/models/final_gold_model.joblib": "models/releases/final_gold_model.joblib",
    "artifacts/models/final_gold_model_features.joblib": "models/releases/final_gold_model_features.joblib",
    "artifacts/models/final_model_release_manifest.json": "models/releases/final_model_release_manifest.json",
    "data/reports/final_holdout_metrics.csv": "models/releases/final_holdout_metrics.csv",
    "data/reports/final_holdout_baselines.csv": "models/releases/final_holdout_baselines.csv",
    "data/reports/final_holdout_regime_performance.csv": "models/releases/final_holdout_regime_performance.csv",
}

GROUPS = {
    "raw": tuple(key for key in ARTIFACT_MAPPINGS if key.startswith("data/raw/")),
    "raw_entsoe": tuple(key for key in ARTIFACT_MAPPINGS if key.startswith("data/raw/entsoe/")),
    "raw_weather": ("data/raw/weather/open_meteo_weather.csv",),
    "silver": ("data/processed/silver_electricity_market_data.csv",),
    "gold": ("data/features/gold_model_features.csv",),
    "predictions": tuple(key for key in ARTIFACT_MAPPINGS if "reports/actual_vs_predicted" in key),
    "anomalies": tuple(key for key in ARTIFACT_MAPPINGS if "reports/detected_anomalies" in key or "reports/anomaly_detection" in key),
    "monitoring": tuple(key for key in ARTIFACT_MAPPINGS if "reports/feature_importance" in key),
    "model_release": (
        "artifacts/models/final_gold_model.joblib",
        "artifacts/models/final_gold_model_features.joblib",
        "artifacts/models/final_model_release_manifest.json",
    ),
    "model_evaluations": tuple(key for key in ARTIFACT_MAPPINGS if key.startswith("data/reports/final_holdout_")),
}
GROUPS["models"] = GROUPS["model_release"] + GROUPS["model_evaluations"]


def object_key(local_path: str | Path) -> str:
    normalized = Path(local_path).as_posix().lstrip("./")
    try:
        return ARTIFACT_MAPPINGS[normalized]
    except KeyError as exc:
        raise KeyError(f"No S3 mapping is defined for {normalized}") from exc
