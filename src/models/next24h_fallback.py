"""Offline-only next-24-hour fallback candidate contract and inference helpers."""

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from models.next24h import FORECAST_COLUMNS, HORIZONS, ISSUE_TIME


FALLBACK_FEATURES = (
    "hour",
    "day_of_week",
    "month",
    "is_weekend",
    "load_mw",
    "load_lag_1h",
    "load_lag_24h",
    "load_rolling_mean_24h",
    "biomass_mw",
    "lignite_mw",
    "gas_mw",
    "hard_coal_mw",
    "hydro_mw",
    "nuclear_mw",
    "solar_mw",
    "wind_offshore_mw",
    "wind_onshore_mw",
    "wind_total_mw",
    "renewable_generation_mw",
    "renewable_share",
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "cloud_cover",
    "shortwave_radiation",
)
PRICE_DERIVED_FEATURES = frozenset(
    {
        "price_eur_mwh",
        "price_lag_1h",
        "price_lag_24h",
        "price_lag_168h",
        "price_rolling_mean_24h",
        "price_rolling_std_24h",
    }
)
TARGET_COLUMNS = tuple(f"target_price_{h}h" for h in HORIZONS)
PERSISTENCE_BENCHMARK_COLUMN = "benchmark_current_price_eur_mwh"

_INPUT_COLUMNS = (
    "load_mw",
    "biomass_mw",
    "lignite_mw",
    "gas_mw",
    "hard_coal_mw",
    "hydro_mw",
    "nuclear_mw",
    "solar_mw",
    "wind_offshore_mw",
    "wind_onshore_mw",
    "wind_total_mw",
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "cloud_cover",
    "shortwave_radiation",
)


def _ordered_fallback_inputs(source: pd.DataFrame) -> pd.DataFrame:
    """Return hourly inputs without reading or retaining any price column."""
    required = {"timestamp", *_INPUT_COLUMNS}
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"Fallback source is missing required columns: {missing}")

    data = source.loc[:, ["timestamp", *_INPUT_COLUMNS]].copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="raise", utc=True)
    data = data.sort_values("timestamp").reset_index(drop=True)
    timestamps = data["timestamp"]
    if timestamps.empty:
        raise ValueError("Fallback source contains no rows.")
    if timestamps.duplicated().any():
        raise ValueError("Fallback source timestamps must be unique.")
    if (timestamps != timestamps.dt.floor("h")).any():
        raise ValueError("Fallback source timestamps must be exact UTC hours.")
    for column in _INPUT_COLUMNS:
        data[column] = pd.to_numeric(data[column], errors="raise")
    data["nuclear_mw"] = data["nuclear_mw"].fillna(0)
    full_hours = pd.date_range(timestamps.min(), timestamps.max(), freq="h", tz="UTC")
    return (
        data.set_index("timestamp")
        .reindex(full_hours)
        .rename_axis("timestamp")
        .reset_index()
    )


def build_fallback_issue_features(source: pd.DataFrame) -> pd.DataFrame:
    """Build the price-independent issue-time feature contract."""
    data = _ordered_fallback_inputs(source)
    data["hour"] = data["timestamp"].dt.hour
    data["day_of_week"] = data["timestamp"].dt.dayofweek
    data["month"] = data["timestamp"].dt.month
    data["is_weekend"] = data["day_of_week"].isin([5, 6]).astype(int)
    data["load_lag_1h"] = data["load_mw"].shift(1)
    data["load_lag_24h"] = data["load_mw"].shift(24)
    data["load_rolling_mean_24h"] = data["load_mw"].rolling(24).mean()
    data["renewable_generation_mw"] = (
        data["solar_mw"]
        + data["wind_total_mw"]
        + data["biomass_mw"]
        + data["hydro_mw"]
    )
    data["renewable_share"] = data["renewable_generation_mw"] / (
        data["renewable_generation_mw"]
        + data["lignite_mw"]
        + data["gas_mw"]
        + data["hard_coal_mw"]
        + data["nuclear_mw"]
    )
    return data.loc[:, ["timestamp", *FALLBACK_FEATURES]].dropna().reset_index(drop=True)


def build_fallback_training_data(silver: pd.DataFrame) -> pd.DataFrame:
    """Attach exact future price targets without exposing prices as inputs."""
    if "price_eur_mwh" not in silver.columns:
        raise ValueError("Fallback evaluation requires price_eur_mwh as the target source.")
    timestamps = pd.to_datetime(silver["timestamp"], errors="raise", utc=True)
    if timestamps.duplicated().any():
        raise ValueError("Fallback training timestamps must be unique.")
    prices = pd.Series(
        pd.to_numeric(silver["price_eur_mwh"], errors="raise").to_numpy(),
        index=timestamps,
    ).sort_index()
    issues = build_fallback_issue_features(silver).rename(columns={"timestamp": ISSUE_TIME})
    issues[PERSISTENCE_BENCHMARK_COLUMN] = prices.reindex(issues[ISSUE_TIME]).to_numpy()
    for horizon in HORIZONS:
        target_time = issues[ISSUE_TIME] + pd.Timedelta(hours=horizon)
        issues[f"target_timestamp_{horizon}h"] = target_time
        issues[f"target_price_{horizon}h"] = prices.reindex(target_time).to_numpy()
    return issues.dropna(
        subset=[PERSISTENCE_BENCHMARK_COLUMN, *TARGET_COLUMNS]
    ).reset_index(drop=True)


def prepare_fallback_features(
    data: pd.DataFrame,
    features=FALLBACK_FEATURES,
) -> pd.DataFrame:
    features = tuple(features)
    if features != FALLBACK_FEATURES:
        raise ValueError("Fallback feature order does not match its contract.")
    if PRICE_DERIVED_FEATURES.intersection(features):
        raise ValueError("Fallback inference cannot use price-derived features.")
    missing = [name for name in features if name not in data.columns]
    if missing:
        raise ValueError(f"Missing fallback features: {missing}")
    result = data.loc[:, list(features)]
    if result.isna().any().any() or not np.isfinite(result.to_numpy(dtype=float)).all():
        raise ValueError("Fallback features must contain only finite values.")
    return result


def create_fallback_forecast(
    issue_row: pd.DataFrame,
    model,
    *,
    model_release: str,
    features=FALLBACK_FEATURES,
) -> pd.DataFrame:
    if len(issue_row) != 1:
        raise ValueError("Exactly one fallback issue-time row is required.")
    issue_time = pd.Timestamp(issue_row.iloc[0][ISSUE_TIME])
    if issue_time.tzinfo is None:
        raise ValueError("Fallback issue time must have an explicit timezone.")
    issue_time = issue_time.tz_convert("UTC")
    if issue_time != issue_time.floor("h"):
        raise ValueError("Fallback issue time must be an exact UTC hour.")
    if not model_release:
        raise ValueError("Fallback candidate release must be identified.")
    predictions = np.asarray(model.predict(prepare_fallback_features(issue_row, features)))
    if predictions.shape != (1, len(HORIZONS)) or not np.isfinite(predictions).all():
        raise ValueError("Fallback candidate must return 24 finite predictions.")
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


def load_fallback_candidate(model_path: Path, manifest_path: Path):
    """Load only an isolated, unpromoted fallback candidate."""
    model_path, manifest_path = Path(model_path), Path(manifest_path)
    if not model_path.exists() or not manifest_path.exists():
        raise FileNotFoundError("Fallback candidate model and manifest must both exist.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("release_type") != "next24h_fallback_candidate_not_promoted":
        raise ValueError("Not an unpromoted next24h fallback candidate.")
    if tuple(manifest.get("features", [])) != FALLBACK_FEATURES:
        raise ValueError("Fallback candidate feature contract is invalid.")
    if manifest.get("model_file") != model_path.name:
        raise ValueError("Fallback manifest does not identify this model file.")
    if manifest.get("model_sha256") != hashlib.sha256(model_path.read_bytes()).hexdigest():
        raise ValueError("Fallback candidate model hash does not match its manifest.")
    return joblib.load(model_path), manifest
