"""Verified production inference for the separate next-24-hour release."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from models.final_evaluation import FINAL_FEATURES
from models.next24h import (
    FORECAST_COLUMNS,
    HORIZONS,
    ISSUE_TIME,
    build_issue_features,
    create_next24h_forecast,
)


RELEASE_DIR = Path("artifacts/models/releases/next24h")
SILVER_PATH = Path("data/processed/silver_electricity_market_data.csv")
LATEST_PATH = Path("data/reports/next24h_forecast.csv")
HISTORY_PATH = Path("data/reports/next24h_forecast_history.csv")
HISTORY_COLUMNS = (*FORECAST_COLUMNS, "issued_at_utc")
DEFAULT_MAX_AGE_HOURS = 3.0


class ForecastUnavailableError(ValueError):
    """No current, complete issue time exists; preserve the prior forecast."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def max_age_hours_from_env() -> float:
    value = float(os.getenv("POWERFLOW_NEXT24H_MAX_AGE_HOURS", DEFAULT_MAX_AGE_HOURS))
    if not 0 < value <= 24:
        raise ValueError("POWERFLOW_NEXT24H_MAX_AGE_HOURS must be > 0 and <= 24.")
    return value


def load_next24h_release(release_dir: Path = RELEASE_DIR):
    release_dir = Path(release_dir)
    manifest = json.loads(
        (release_dir / "next24h_release_manifest.json").read_text(encoding="utf-8")
    )
    if (
        manifest.get("release_type") != "next24h_production"
        or manifest.get("horizons_hours") != list(HORIZONS)
        or manifest.get("feature_count") != 31
        or manifest.get("features") != list(FINAL_FEATURES)
        or manifest.get("model_file") != "next24h_model.joblib"
        or manifest.get("feature_contract_file") != "next24h_feature_contract.joblib"
        or not manifest.get("release_id")
    ):
        raise ValueError("Next24h release manifest or feature contract is invalid.")

    model_path = release_dir / manifest["model_file"]
    contract_path = release_dir / manifest["feature_contract_file"]
    if (
        _sha256(model_path) != manifest.get("model_sha256")
        or _sha256(contract_path) != manifest.get("feature_contract_sha256")
    ):
        raise ValueError("Next24h release artifact hash mismatch.")
    features = tuple(joblib.load(contract_path))
    if features != tuple(FINAL_FEATURES):
        raise ValueError("Next24h release feature-contract order mismatch.")
    model = joblib.load(model_path)
    if len(getattr(model, "estimators_", ())) != 24:
        raise ValueError("Next24h release model must have 24 direct outputs.")
    return model, features, manifest


def validate_forecast(forecast: pd.DataFrame) -> None:
    if list(forecast.columns) != list(FORECAST_COLUMNS) or len(forecast) != 24:
        raise ValueError("Next24h forecast must contain exactly 24 contract rows.")
    horizons = pd.to_numeric(forecast["horizon_hours"], errors="raise").tolist()
    predictions = pd.to_numeric(
        forecast["predicted_price_eur_mwh"], errors="raise"
    )
    if horizons != list(HORIZONS):
        raise ValueError("Next24h forecast horizons must be ordered 1..24.")
    issues = pd.to_datetime(forecast[ISSUE_TIME], errors="raise", utc=True)
    targets = pd.to_datetime(forecast["target_timestamp"], errors="raise", utc=True)
    if (
        issues.nunique() != 1
        or targets.duplicated().any()
        or not targets.is_monotonic_increasing
        or not (targets == issues + pd.to_timedelta(horizons, unit="h")).all()
        or forecast["model_release"].nunique() != 1
        or not np.isfinite(predictions.to_numpy(dtype=float)).all()
        or not str(forecast["model_release"].iloc[0]).strip()
    ):
        raise ValueError("Next24h forecast timestamps or predictions are invalid.")


def forecast_from_silver(
    silver: pd.DataFrame,
    model,
    features,
    release_id: str,
    *,
    now: pd.Timestamp | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> pd.DataFrame:
    if not 0 < max_age_hours <= 24:
        raise ValueError("Forecast freshness threshold must be > 0 and <= 24 hours.")
    if silver.empty:
        raise ForecastUnavailableError("Silver has no observable issue-time rows.")
    latest_silver = pd.to_datetime(silver["timestamp"], errors="raise", utc=True).max()
    issues = build_issue_features(silver)
    eligible = issues.loc[issues["timestamp"] == latest_silver]
    if len(eligible) != 1:
        raise ForecastUnavailableError(
            "Latest Silver hour lacks complete exact-hour feature history."
        )
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    if latest_silver > current or current - latest_silver > pd.Timedelta(hours=max_age_hours):
        raise ForecastUnavailableError(
            f"Latest Silver hour {latest_silver.isoformat()} exceeds the "
            f"{max_age_hours:g}-hour freshness threshold."
        )
    if tuple(features) != tuple(FINAL_FEATURES):
        raise ValueError("Next24h feature contract mismatch.")
    forecast = create_next24h_forecast(
        eligible.rename(columns={"timestamp": ISSUE_TIME}),
        model,
        model_release=release_id,
        features=features,
    )
    validate_forecast(forecast)
    return forecast


def _atomic_csv(data: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    data.to_csv(temporary, index=False)
    temporary.replace(path)


def save_forecast(
    forecast: pd.DataFrame,
    latest_path: Path = LATEST_PATH,
    history_path: Path = HISTORY_PATH,
    *,
    issued_at_utc: pd.Timestamp | None = None,
) -> bool:
    validate_forecast(forecast)
    latest_path, history_path = Path(latest_path), Path(history_path)
    issued_at = pd.Timestamp.now(tz="UTC") if issued_at_utc is None else pd.Timestamp(issued_at_utc)
    issued_at = issued_at.tz_localize("UTC") if issued_at.tzinfo is None else issued_at.tz_convert("UTC")
    issue_time = pd.to_datetime(forecast[ISSUE_TIME], utc=True).iloc[0]
    if issued_at < issue_time:
        raise ValueError("Forecast issuance cannot precede its Silver issue hour.")
    issued_forecast = forecast.copy()
    issued_forecast["issued_at_utc"] = issued_at
    if history_path.exists():
        history = pd.read_csv(history_path)
        if list(history.columns) != list(HISTORY_COLUMNS):
            raise ValueError("Existing next24h forecast history schema is invalid.")
        key = [ISSUE_TIME, "target_timestamp", "horizon_hours", "model_release"]
        current = issued_forecast.copy()
        for column in (ISSUE_TIME, "target_timestamp"):
            history[column] = pd.to_datetime(history[column], utc=True)
            current[column] = pd.to_datetime(current[column], utc=True)
        existing = history.merge(current[key], on=key, how="inner")
        if not existing.empty:
            if len(existing) != 24:
                raise ValueError("Existing forecast issue has partial history.")
            prior = existing.sort_values("horizon_hours")["predicted_price_eur_mwh"].to_numpy()
            proposed = current.sort_values("horizon_hours")["predicted_price_eur_mwh"].to_numpy()
            if not np.allclose(prior, proposed, rtol=0, atol=1e-12):
                raise ValueError("Existing issued forecast cannot be changed.")
            latest_issue = (
                pd.to_datetime(pd.read_csv(latest_path)[ISSUE_TIME], utc=True).max()
                if latest_path.exists() else None
            )
            if latest_issue is None or issue_time >= latest_issue:
                _atomic_csv(forecast, latest_path)
            return False
        combined = pd.concat([history, current], ignore_index=True)
    else:
        combined = issued_forecast
    if combined.duplicated([ISSUE_TIME, "target_timestamp", "horizon_hours", "model_release"]).any():
        raise ValueError("Forecast history contains duplicate issue-target pairs.")
    combined = combined.sort_values([ISSUE_TIME, "horizon_hours"])
    _atomic_csv(combined, history_path)
    _atomic_csv(forecast, latest_path)
    return True


def run_next24h_forecast(
    *,
    release_dir: Path = RELEASE_DIR,
    silver_path: Path = SILVER_PATH,
    latest_path: Path = LATEST_PATH,
    history_path: Path = HISTORY_PATH,
    now: pd.Timestamp | None = None,
    max_age_hours: float | None = None,
) -> tuple[pd.DataFrame, bool]:
    model, features, manifest = load_next24h_release(release_dir)
    silver = pd.read_csv(silver_path, low_memory=False)
    forecast = forecast_from_silver(
        silver, model, features, manifest["release_id"], now=now,
        max_age_hours=max_age_hours if max_age_hours is not None else max_age_hours_from_env(),
    )
    changed = save_forecast(forecast, latest_path, history_path, issued_at_utc=now)
    return forecast, changed


if __name__ == "__main__":
    produced, new_issue = run_next24h_forecast()
    print(f"Next24h forecast: {len(produced)} rows; new issue={new_issue}.")
