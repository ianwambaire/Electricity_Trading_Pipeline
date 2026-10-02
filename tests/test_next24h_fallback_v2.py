import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from models.next24h import HORIZONS, ISSUE_TIME
from models.next24h_fallback import (
    FALLBACK_FEATURES,
    PRICE_DERIVED_FEATURES,
    build_fallback_issue_features,
)
from models.next24h_fallback_v2 import (
    FALLBACK_V2_HORIZON_FEATURES,
    TARGET_CALENDAR_FEATURES,
    HorizonSpecificFallbackModel,
    create_fallback_v2_forecast,
    prepare_horizon_features,
)
from tests.test_next24h_fallback import PRODUCTION_ARTIFACTS, silver_hours


class HorizonEstimator:
    def __init__(self, horizon):
        self.horizon = horizon

    def predict(self, features):
        assert features.columns.tolist() == list(FALLBACK_V2_HORIZON_FEATURES)
        return np.repeat(float(self.horizon), len(features))


def fixed_model():
    return HorizonSpecificFallbackModel(
        {horizon: HorizonEstimator(horizon) for horizon in HORIZONS}
    )


def issue_rows():
    return build_fallback_issue_features(silver_hours()).tail(3).rename(
        columns={"timestamp": ISSUE_TIME}
    )


def test_target_calendar_is_derived_only_from_exact_target_timestamp():
    issues = issue_rows()
    horizon = 24
    features = prepare_horizon_features(issues, horizon)
    targets = pd.to_datetime(issues[ISSUE_TIME], utc=True) + pd.Timedelta(hours=horizon)
    assert features["target_hour"].tolist() == targets.dt.hour.tolist()
    assert features["target_day_of_week"].tolist() == targets.dt.dayofweek.tolist()
    assert features["target_month"].tolist() == targets.dt.month.tolist()
    assert features["target_is_weekend"].tolist() == (
        targets.dt.dayofweek.isin([5, 6]).astype(int).tolist()
    )


def test_supplied_target_calendar_columns_are_ignored_and_recomputed():
    issues = issue_rows().assign(
        target_hour=99,
        target_day_of_week=99,
        target_month=99,
        target_is_weekend=99,
    )
    features = prepare_horizon_features(issues, 1)
    targets = pd.to_datetime(issues[ISSUE_TIME], utc=True) + pd.Timedelta(hours=1)
    assert features["target_hour"].tolist() == targets.dt.hour.tolist()
    assert 99 not in features[list(TARGET_CALENDAR_FEATURES)].to_numpy()


def test_no_price_or_future_observed_values_enter_v2_inference_features():
    assert not PRICE_DERIVED_FEATURES.intersection(FALLBACK_V2_HORIZON_FEATURES)
    issues = issue_rows()
    malicious = issues.assign(
        price_eur_mwh=999999,
        future_load_mw=999999,
        future_generation_mw=999999,
        future_temperature_2m=999999,
        target_price_1h=999999,
    )
    expected = prepare_horizon_features(issues, 1)
    actual = prepare_horizon_features(malicious, 1)
    pd.testing.assert_frame_equal(actual, expected)
    assert actual.columns.tolist() == [*FALLBACK_FEATURES, *TARGET_CALENDAR_FEATURES]


def test_each_horizon_receives_its_own_target_calendar():
    issue = issue_rows().tail(1)
    first = prepare_horizon_features(issue, 1)
    last = prepare_horizon_features(issue, 24)
    issue_time = pd.Timestamp(issue[ISSUE_TIME].iloc[0])
    assert first["target_hour"].item() == (issue_time + pd.Timedelta(hours=1)).hour
    assert last["target_hour"].item() == (issue_time + pd.Timedelta(hours=24)).hour
    assert not first[list(TARGET_CALENDAR_FEATURES)].equals(
        last[list(TARGET_CALENDAR_FEATURES)]
    )


def test_v2_contract_order_is_strict_and_base_features_are_required():
    issues = issue_rows()
    with pytest.raises(ValueError, match="feature order"):
        prepare_horizon_features(
            issues,
            1,
            tuple(reversed(FALLBACK_V2_HORIZON_FEATURES)),
        )
    with pytest.raises(ValueError, match="Missing fallback features"):
        prepare_horizon_features(issues.drop(columns=[FALLBACK_FEATURES[-1]]), 1)


def test_horizon_specific_model_requires_all_24_estimators():
    with pytest.raises(ValueError, match="one estimator per horizon"):
        HorizonSpecificFallbackModel({1: HorizonEstimator(1)})


def test_v2_forecast_produces_exactly_24_finite_ordered_predictions():
    issue = issue_rows().tail(1)
    forecast = create_fallback_v2_forecast(
        issue,
        fixed_model(),
        model_release="fallback-v2-test",
    )
    assert len(forecast) == 24
    assert forecast["horizon_hours"].tolist() == list(HORIZONS)
    assert forecast["predicted_price_eur_mwh"].tolist() == list(HORIZONS)
    assert np.isfinite(forecast["predicted_price_eur_mwh"]).all()
    assert forecast["target_timestamp"].is_monotonic_increasing


def test_v2_helpers_leave_all_production_artifacts_unchanged():
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in PRODUCTION_ARTIFACTS
    }
    create_fallback_v2_forecast(
        issue_rows().tail(1),
        fixed_model(),
        model_release="fallback-v2-test",
    )
    after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in PRODUCTION_ARTIFACTS
    }
    assert after == before
