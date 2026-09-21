"""Isolated next-24-hour candidate data and inference; not a production release."""

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from models.final_evaluation import FINAL_FEATURES


HORIZONS = tuple(range(1, 25))
ISSUE_TIME = "forecast_issue_time"
FORECAST_COLUMNS = (
    ISSUE_TIME,
    "target_timestamp",
    "horizon_hours",
    "predicted_price_eur_mwh",
    "model_release",
)


def _ordered_silver(silver: pd.DataFrame) -> pd.DataFrame:
    required = {
        "timestamp", "price_eur_mwh", "load_mw", "biomass_mw", "lignite_mw",
        "gas_mw", "hard_coal_mw", "hydro_mw", "nuclear_mw", "solar_mw",
        "wind_offshore_mw", "wind_onshore_mw", "wind_total_mw",
        "temperature_2m", "relative_humidity_2m", "wind_speed_10m",
        "cloud_cover", "shortwave_radiation",
    }
    missing = sorted(required - set(silver.columns))
    if missing:
        raise ValueError(f"Silver dataset is missing required columns: {missing}")

    data = silver.loc[:, ["timestamp", *sorted(required - {"timestamp"})]].copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="raise", utc=True)
    data = data.sort_values("timestamp").reset_index(drop=True)
    times = data["timestamp"]
    if times.duplicated().any():
        raise ValueError("Silver timestamps must be unique.")
    if (times != times.dt.floor("h")).any():
        raise ValueError("Silver timestamps must be exact UTC hours.")
    for column in required - {"timestamp"}:
        data[column] = pd.to_numeric(data[column], errors="raise")
    # Match the existing Gold treatment of nuclear generation after shutdown.
    data["nuclear_mw"] = data["nuclear_mw"].fillna(0)
    # In-memory NaN hours preserve elapsed-time semantics for shifts and rolls.
    full_hours = pd.date_range(times.min(), times.max(), freq="h", tz="UTC")
    return (
        data.set_index("timestamp").reindex(full_hours)
        .rename_axis("timestamp").reset_index()
    )


def build_issue_features(silver: pd.DataFrame) -> pd.DataFrame:
    """Reproduce Gold's issue-time features without requiring a future label."""
    data = _ordered_silver(silver)
    data["hour"] = data["timestamp"].dt.hour
    data["day_of_week"] = data["timestamp"].dt.dayofweek
    data["month"] = data["timestamp"].dt.month
    data["is_weekend"] = data["day_of_week"].isin([5, 6]).astype(int)
    for lag in (1, 24, 168):
        data[f"price_lag_{lag}h"] = data["price_eur_mwh"].shift(lag)
    for lag in (1, 24):
        data[f"load_lag_{lag}h"] = data["load_mw"].shift(lag)
    data["price_rolling_mean_24h"] = data["price_eur_mwh"].rolling(24).mean()
    data["price_rolling_std_24h"] = data["price_eur_mwh"].rolling(24).std()
    data["load_rolling_mean_24h"] = data["load_mw"].rolling(24).mean()
    data["renewable_generation_mw"] = (
        data["solar_mw"] + data["wind_total_mw"] + data["biomass_mw"]
        + data["hydro_mw"]
    )
    data["renewable_share"] = data["renewable_generation_mw"] / (
        data["renewable_generation_mw"] + data["lignite_mw"]
        + data["gas_mw"] + data["hard_coal_mw"] + data["nuclear_mw"]
    )
    return data.loc[:, ["timestamp", *FINAL_FEATURES]].dropna().reset_index(drop=True)


def build_training_data(silver: pd.DataFrame) -> pd.DataFrame:
    """Match 24 observed labels by exact UTC time; never use them as features."""
    ordered = _ordered_silver(silver)
    issues = build_issue_features(ordered).rename(columns={"timestamp": ISSUE_TIME})
    prices = ordered.set_index("timestamp")["price_eur_mwh"]
    for horizon in HORIZONS:
        target_time = issues[ISSUE_TIME] + pd.Timedelta(hours=horizon)
        issues[f"target_timestamp_{horizon}h"] = target_time
        issues[f"target_price_{horizon}h"] = prices.reindex(target_time).to_numpy()
    target_columns = [f"target_price_{h}h" for h in HORIZONS]
    return issues.dropna(subset=target_columns).reset_index(drop=True)


def prepare_candidate_features(data: pd.DataFrame, features=FINAL_FEATURES) -> pd.DataFrame:
    features = tuple(features)
    if features != FINAL_FEATURES:
        raise ValueError("Candidate feature order does not match its issue-time contract.")
    missing = [name for name in features if name not in data.columns]
    if missing:
        raise ValueError(f"Missing candidate features: {missing}")
    result = data.loc[:, list(features)]
    if result.isna().any().any() or not np.isfinite(result.to_numpy(dtype=float)).all():
        raise ValueError("Candidate features must contain only finite values.")
    return result


def create_next24h_forecast(
    issue_row: pd.DataFrame,
    model,
    *,
    model_release: str,
    features=FINAL_FEATURES,
) -> pd.DataFrame:
    if len(issue_row) != 1:
        raise ValueError("Exactly one issue-time row is required.")
    issue_time = pd.Timestamp(issue_row.iloc[0][ISSUE_TIME])
    if issue_time.tzinfo is None:
        raise ValueError("Forecast issue time must have an explicit timezone.")
    issue_time = issue_time.tz_convert("UTC")
    if issue_time != issue_time.floor("h"):
        raise ValueError("Forecast issue time must be an exact UTC hour.")
    if not model_release:
        raise ValueError("Candidate model release must be identified.")
    predictions = np.asarray(model.predict(prepare_candidate_features(issue_row, features)))
    if predictions.shape != (1, len(HORIZONS)) or not np.isfinite(predictions).all():
        raise ValueError("Candidate model must return 24 finite hourly predictions.")
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


def load_candidate_model(model_path: Path, manifest_path: Path):
    """Explicit candidate paths prevent accidental frozen-release replacement."""
    model_path, manifest_path = Path(model_path), Path(manifest_path)
    if not model_path.exists() or not manifest_path.exists():
        raise FileNotFoundError("Candidate model and manifest must both exist.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("release_type") != "next24h_candidate_not_promoted":
        raise ValueError("Not a next-24-hour candidate release.")
    if tuple(manifest.get("features", [])) != FINAL_FEATURES:
        raise ValueError("Candidate feature contract is invalid.")
    if manifest.get("model_file") != model_path.name:
        raise ValueError("Candidate manifest does not identify this model file.")
    if manifest.get("model_sha256") != hashlib.sha256(model_path.read_bytes()).hexdigest():
        raise ValueError("Candidate model hash does not match its manifest.")
    return joblib.load(model_path), manifest


def generate_candidate_forecast(
    silver_path: Path,
    model_path: Path,
    manifest_path: Path,
    output_path: Path,
    *,
    now: pd.Timestamp | None = None,
    allow_stale: bool = False,
) -> pd.DataFrame:
    """Manually generate a candidate report; never invoked by the Prefect flow."""
    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError(f"Refusing to replace an existing forecast: {output_path}")
    silver = pd.read_csv(silver_path, low_memory=False)
    issue = build_issue_features(silver).tail(1).rename(columns={"timestamp": ISSUE_TIME})
    if issue.empty:
        raise ValueError("Silver has no complete issue-time feature row.")
    latest_silver_hour = pd.to_datetime(silver["timestamp"], utc=True).max()
    if issue.iloc[0][ISSUE_TIME] != latest_silver_hour:
        raise ValueError(
            "Latest Silver hour lacks complete feature history; refusing "
            "to issue a forecast from an earlier hour."
        )
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    issue_time = issue.iloc[0][ISSUE_TIME]
    if not allow_stale and (issue_time > current or current - issue_time > pd.Timedelta(hours=2)):
        raise ValueError(
            "The latest complete Silver hour is stale or future-dated; "
            "refusing to present retrospective targets as a current forecast."
        )
    model, manifest = load_candidate_model(model_path, manifest_path)
    forecast = create_next24h_forecast(
        issue,
        model,
        model_release=Path(manifest_path).parent.name,
        features=manifest["features"],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    forecast.to_csv(output_path, index=False)
    return forecast


def main():
    parser = argparse.ArgumentParser(description="Generate an unpromoted next-24h candidate forecast.")
    parser.add_argument("--silver", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-stale", action="store_true",
        help="Development-only retrospective output; not a current forecast.",
    )
    args = parser.parse_args()
    forecast = generate_candidate_forecast(
        args.silver, args.model, args.manifest, args.output,
        allow_stale=args.allow_stale,
    )
    print(f"Saved {len(forecast)} candidate forecast rows to {args.output}")


if __name__ == "__main__":
    main()
