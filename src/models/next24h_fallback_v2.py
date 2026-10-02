"""Offline-only horizon-specific next24h fallback v2 helpers."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from models.next24h import FORECAST_COLUMNS, HORIZONS, ISSUE_TIME
from models.next24h_fallback import (
    FALLBACK_FEATURES,
    PRICE_DERIVED_FEATURES,
    prepare_fallback_features,
)


TARGET_CALENDAR_FEATURES = (
    "target_hour",
    "target_day_of_week",
    "target_month",
    "target_is_weekend",
)
FALLBACK_V2_HORIZON_FEATURES = (*FALLBACK_FEATURES, *TARGET_CALENDAR_FEATURES)


def target_timestamps(issue_times: pd.Series, horizon: int) -> pd.Series:
    """Derive an exact UTC target timestamp from issue time and direct horizon."""
    if horizon not in HORIZONS:
        raise ValueError(f"Fallback v2 horizon must be in {HORIZONS}.")
    parsed = pd.to_datetime(issue_times, errors="raise", utc=True)
    if (parsed != parsed.dt.floor("h")).any():
        raise ValueError("Fallback v2 issue times must be exact UTC hours.")
    return parsed + pd.Timedelta(hours=horizon)


def prepare_horizon_features(
    data: pd.DataFrame,
    horizon: int,
    features=FALLBACK_V2_HORIZON_FEATURES,
) -> pd.DataFrame:
    """Build one horizon matrix; target calendars are always recomputed internally."""
    features = tuple(features)
    if features != FALLBACK_V2_HORIZON_FEATURES:
        raise ValueError("Fallback v2 horizon feature order does not match its contract.")
    if PRICE_DERIVED_FEATURES.intersection(features):
        raise ValueError("Fallback v2 inference cannot use price-derived features.")
    if ISSUE_TIME not in data.columns:
        raise ValueError(f"Fallback v2 inputs require {ISSUE_TIME}.")

    base = prepare_fallback_features(data).copy()
    target_time = target_timestamps(data[ISSUE_TIME], horizon)
    base["target_hour"] = target_time.dt.hour.to_numpy()
    base["target_day_of_week"] = target_time.dt.dayofweek.to_numpy()
    base["target_month"] = target_time.dt.month.to_numpy()
    base["target_is_weekend"] = target_time.dt.dayofweek.isin([5, 6]).astype(int).to_numpy()
    result = base.loc[:, list(features)]
    if not np.isfinite(result.to_numpy(dtype=float)).all():
        raise ValueError("Fallback v2 horizon features must contain only finite values.")
    return result


@dataclass
class HorizonSpecificFallbackModel:
    """A separate direct estimator for each of the 24 forecast horizons."""

    estimators: dict

    def __post_init__(self):
        if set(self.estimators) != set(HORIZONS):
            raise ValueError("Fallback v2 requires exactly one estimator per horizon.")

    def predict(self, issue_rows: pd.DataFrame) -> np.ndarray:
        predictions = []
        for horizon in HORIZONS:
            values = np.asarray(
                self.estimators[horizon].predict(
                    prepare_horizon_features(issue_rows, horizon)
                ),
                dtype=float,
            ).reshape(-1)
            if len(values) != len(issue_rows) or not np.isfinite(values).all():
                raise ValueError(
                    f"Fallback v2 horizon {horizon} returned invalid predictions."
                )
            predictions.append(values)
        return np.column_stack(predictions)


def create_fallback_v2_forecast(
    issue_row: pd.DataFrame,
    model: HorizonSpecificFallbackModel,
    *,
    model_release: str,
) -> pd.DataFrame:
    if len(issue_row) != 1:
        raise ValueError("Exactly one fallback v2 issue-time row is required.")
    if not model_release:
        raise ValueError("Fallback v2 candidate release must be identified.")
    issue_time = pd.to_datetime(issue_row[ISSUE_TIME], errors="raise", utc=True).iloc[0]
    if issue_time != issue_time.floor("h"):
        raise ValueError("Fallback v2 issue time must be an exact UTC hour.")
    predictions = model.predict(issue_row)
    if predictions.shape != (1, len(HORIZONS)):
        raise ValueError("Fallback v2 candidate must return 24 predictions.")
    return pd.DataFrame(
        {
            ISSUE_TIME: [issue_time] * len(HORIZONS),
            "target_timestamp": [
                issue_time + pd.Timedelta(hours=horizon) for horizon in HORIZONS
            ],
            "horizon_hours": HORIZONS,
            "predicted_price_eur_mwh": predictions[0],
            "model_release": [model_release] * len(HORIZONS),
        },
        columns=FORECAST_COLUMNS,
    )


def load_fallback_v2_candidate(model_path: Path, manifest_path: Path):
    """Load only an isolated, unpromoted fallback v2 candidate."""
    model_path, manifest_path = Path(model_path), Path(manifest_path)
    if not model_path.exists() or not manifest_path.exists():
        raise FileNotFoundError("Fallback v2 model and manifest must both exist.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("release_type") != "next24h_fallback_v2_candidate_not_promoted":
        raise ValueError("Not an unpromoted next24h fallback v2 candidate.")
    if tuple(manifest.get("base_features", [])) != FALLBACK_FEATURES:
        raise ValueError("Fallback v2 base feature contract is invalid.")
    if tuple(manifest.get("target_calendar_features", [])) != TARGET_CALENDAR_FEATURES:
        raise ValueError("Fallback v2 target-calendar contract is invalid.")
    if manifest.get("model_file") != model_path.name:
        raise ValueError("Fallback v2 manifest does not identify this model file.")
    if manifest.get("model_sha256") != hashlib.sha256(model_path.read_bytes()).hexdigest():
        raise ValueError("Fallback v2 model hash does not match its manifest.")
    model = joblib.load(model_path)
    if not isinstance(model, HorizonSpecificFallbackModel):
        raise ValueError("Fallback v2 artifact has an unexpected model type.")
    return model, manifest
