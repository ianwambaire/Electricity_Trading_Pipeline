import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from models.evaluate_next24h_fallback import chronological_splits, select_candidate
from models.next24h import ISSUE_TIME
from models.next24h_fallback import (
    FALLBACK_FEATURES,
    PRICE_DERIVED_FEATURES,
    TARGET_COLUMNS,
    build_fallback_issue_features,
    build_fallback_training_data,
    create_fallback_forecast,
    prepare_fallback_features,
)


PRODUCTION_ARTIFACTS = (
    Path("artifacts/models/final_gold_model.joblib"),
    Path("artifacts/models/final_gold_model_features.joblib"),
    Path("artifacts/models/final_model_release_manifest.json"),
    Path("artifacts/models/releases/next24h/next24h_model.joblib"),
    Path("artifacts/models/releases/next24h/next24h_feature_contract.joblib"),
    Path("artifacts/models/releases/next24h/next24h_release_manifest.json"),
)


def silver_hours(count=220, start="2026-03-21T00:00Z"):
    timestamps = pd.date_range(start, periods=count, freq="h")
    steps = np.arange(count, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "price_eur_mwh": 40 + steps / 10,
            "load_mw": 40000 + steps,
            "biomass_mw": 1000 + steps / 20,
            "lignite_mw": 3000 + steps / 20,
            "gas_mw": 2000 + steps / 20,
            "hard_coal_mw": 1000 + steps / 20,
            "hydro_mw": 200 + steps / 20,
            "nuclear_mw": 0.0,
            "solar_mw": 100 + steps / 20,
            "wind_offshore_mw": 100 + steps / 20,
            "wind_onshore_mw": 200 + steps / 20,
            "wind_total_mw": 300 + steps / 10,
            "temperature_2m": 10 + steps / 100,
            "relative_humidity_2m": 60 + steps / 100,
            "wind_speed_10m": 8 + steps / 100,
            "cloud_cover": 50 + steps / 100,
            "shortwave_radiation": 100 + steps / 100,
        }
    )


class FixedFallbackModel:
    def predict(self, features):
        assert features.columns.tolist() == list(FALLBACK_FEATURES)
        return np.arange(1, 25, dtype=float).reshape(1, 24)


def test_fallback_contract_contains_no_price_derived_features():
    assert not PRICE_DERIVED_FEATURES.intersection(FALLBACK_FEATURES)
    assert len(FALLBACK_FEATURES) == len(set(FALLBACK_FEATURES)) == 25


def test_future_prices_are_targets_only_and_cannot_change_issue_features():
    silver = silver_hours()
    issue_time = silver.loc[100, "timestamp"]
    original = build_fallback_issue_features(silver).loc[
        lambda frame: frame["timestamp"] == issue_time, list(FALLBACK_FEATURES)
    ]
    changed = silver.copy()
    changed.loc[changed["timestamp"] > issue_time, "price_eur_mwh"] += 10000
    modified = build_fallback_issue_features(changed).loc[
        lambda frame: frame["timestamp"] == issue_time, list(FALLBACK_FEATURES)
    ]
    pd.testing.assert_frame_equal(original.reset_index(drop=True), modified.reset_index(drop=True))
    original_target = build_fallback_training_data(silver).loc[
        lambda frame: frame[ISSUE_TIME] == issue_time, "target_price_1h"
    ].item()
    changed_target = build_fallback_training_data(changed).loc[
        lambda frame: frame[ISSUE_TIME] == issue_time, "target_price_1h"
    ].item()
    assert changed_target == original_target + 10000


def test_issue_features_can_be_built_when_price_column_is_absent():
    result = build_fallback_issue_features(silver_hours().drop(columns="price_eur_mwh"))
    assert result.columns.tolist() == ["timestamp", *FALLBACK_FEATURES]
    assert not result.empty


def test_targets_use_exact_utc_hours_and_missing_targets_are_not_fabricated():
    silver = silver_hours()
    missing_time = silver.loc[101, "timestamp"]
    training = build_fallback_training_data(silver.drop(index=101))
    assert missing_time - pd.Timedelta(hours=1) not in set(training[ISSUE_TIME])
    first = training.iloc[0]
    for horizon in range(1, 25):
        assert first[f"target_timestamp_{horizon}h"] == (
            first[ISSUE_TIME] + pd.Timedelta(hours=horizon)
        )
    assert set(TARGET_COLUMNS).isdisjoint(FALLBACK_FEATURES)


def test_fallback_features_remain_utc_hourly_across_dst():
    data = build_fallback_training_data(silver_hours(start="2026-03-21T00:00Z"))
    row = data.loc[data[ISSUE_TIME] == pd.Timestamp("2026-03-28T23:00Z")].iloc[0]
    assert row["target_timestamp_1h"] == pd.Timestamp("2026-03-29T00:00Z")
    assert row["target_timestamp_24h"] == pd.Timestamp("2026-03-29T23:00Z")


def test_split_boundaries_embargo_crossing_target_windows():
    times = pd.date_range("2025-12-28", "2026-05-03", freq="h", tz="UTC")
    data = pd.DataFrame({ISSUE_TIME: times})
    data["target_timestamp_24h"] = data[ISSUE_TIME] + pd.Timedelta(hours=24)
    split = chronological_splits(data)
    assert split["train"]["target_timestamp_24h"].max() < pd.Timestamp("2026-01-01T00:00Z")
    assert split["validation"]["target_timestamp_24h"].max() < pd.Timestamp("2026-05-01T00:00Z")
    assert split["test"][ISSUE_TIME].min() >= pd.Timestamp("2026-05-01T00:00Z")


def test_feature_order_and_missing_required_features_fail_safely():
    issue = build_fallback_issue_features(silver_hours()).tail(1)
    with pytest.raises(ValueError, match="feature order"):
        prepare_fallback_features(issue, tuple(reversed(FALLBACK_FEATURES)))
    with pytest.raises(ValueError, match="Missing fallback features"):
        prepare_fallback_features(issue.drop(columns=[FALLBACK_FEATURES[-1]]))


def test_fallback_forecast_contains_exactly_24_finite_predictions():
    issue = build_fallback_issue_features(silver_hours()).tail(1).rename(
        columns={"timestamp": ISSUE_TIME}
    )
    forecast = create_fallback_forecast(
        issue, FixedFallbackModel(), model_release="fallback-test"
    )
    assert len(forecast) == 24
    assert forecast["horizon_hours"].tolist() == list(range(1, 25))
    assert np.isfinite(forecast["predicted_price_eur_mwh"]).all()


def test_candidate_selection_uses_validation_models_and_excludes_persistence():
    metrics = pd.DataFrame(
        [
            {"split": "validation", "horizon_hours": 0, "model_name": "Linear Regression", "rmse": 10.1},
            {"split": "validation", "horizon_hours": 0, "model_name": "Random Forest", "rmse": 10.0},
            {"split": "validation", "horizon_hours": 0, "model_name": "Histogram Gradient Boosting", "rmse": 11.0},
            {"split": "validation", "horizon_hours": 0, "model_name": "Persistence (benchmark only)", "rmse": 1.0},
            {"split": "test", "horizon_hours": 0, "model_name": "Histogram Gradient Boosting", "rmse": 0.1},
        ]
    )
    assert select_candidate(metrics) == "Linear Regression"


def test_production_release_artifacts_remain_unchanged_during_fallback_helpers():
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in PRODUCTION_ARTIFACTS}
    silver = silver_hours()
    issue = build_fallback_issue_features(silver).tail(1).rename(
        columns={"timestamp": ISSUE_TIME}
    )
    create_fallback_forecast(issue, FixedFallbackModel(), model_release="test")
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in PRODUCTION_ARTIFACTS}
    assert after == before
