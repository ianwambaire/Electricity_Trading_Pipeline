import hashlib

import numpy as np
import pandas as pd
import pytest

from models.evaluate_next24h_fallback import TEST_START, chronological_splits
from models.evaluate_next24h_fallback_drift import (
    TRAINING_STRATEGIES,
    combined_refit_rows,
    select_training_strategy,
    strategy_rows_and_weights,
    temporal_drift_tables,
)
from models.next24h import ISSUE_TIME
from models.next24h_fallback import build_fallback_training_data
from tests.test_next24h_fallback import PRODUCTION_ARTIFACTS, silver_hours


def split_fixture():
    silver = silver_hours(count=4200, start="2025-12-01T00:00Z")
    return silver, chronological_splits(build_fallback_training_data(silver))


def test_combined_refit_targets_end_before_test_and_exclude_test_rows():
    _, splits = split_fixture()
    combined = combined_refit_rows(splits)
    assert pd.to_datetime(combined["target_timestamp_24h"], utc=True).max() < TEST_START
    assert pd.to_datetime(combined[ISSUE_TIME], utc=True).max() < TEST_START
    assert set(combined[ISSUE_TIME]).isdisjoint(set(splits["test"][ISSUE_TIME]))


def test_combined_refit_rejects_any_target_reaching_test():
    _, splits = split_fixture()
    contaminated = {name: frame.copy() for name, frame in splits.items()}
    contaminated["validation"].loc[
        contaminated["validation"].index[-1], "target_timestamp_24h"
    ] = TEST_START
    with pytest.raises(ValueError, match="targets must end before"):
        combined_refit_rows(contaminated)


def test_strategy_selection_uses_validation_metrics_only():
    rows = []
    for strategy, rmse in zip(TRAINING_STRATEGIES, (10.0, 9.0, 11.0)):
        rows.append(
            {
                "strategy": strategy,
                "split": "validation",
                "horizon_hours": 0,
                "rmse": rmse,
            }
        )
        rows.append(
            {
                "strategy": strategy,
                "split": "test",
                "horizon_hours": 0,
                "rmse": 0.1 if strategy == "rolling_3y" else 100.0,
            }
        )
    assert select_training_strategy(pd.DataFrame(rows)) == "recency_weighted_365d"


def test_changing_test_data_cannot_change_refit_rows_weights_or_selection():
    _, splits = split_fixture()
    before = combined_refit_rows(splits)
    altered = {name: frame.copy() for name, frame in splits.items()}
    altered["test"].loc[:, "target_price_1h"] = 999999.0
    after = combined_refit_rows(altered)
    pd.testing.assert_frame_equal(before, after)
    for strategy in TRAINING_STRATEGIES:
        rows_before, weights_before = strategy_rows_and_weights(before, strategy)
        rows_after, weights_after = strategy_rows_and_weights(after, strategy)
        pd.testing.assert_frame_equal(rows_before, rows_after)
        if weights_before is not None:
            np.testing.assert_allclose(weights_before, weights_after)


def test_recency_weighting_is_predeclared_monotonic_and_uses_all_rows():
    _, splits = split_fixture()
    combined = combined_refit_rows(splits)
    selected, weights = strategy_rows_and_weights(combined, "recency_weighted_365d")
    assert len(selected) == len(combined) == len(weights)
    assert np.all(np.diff(weights) >= 0)
    assert weights[-1] == pytest.approx(1.0)
    assert weights[0] < weights[-1]


def test_rolling_strategy_is_anchored_only_to_pretest_issue_times():
    _, splits = split_fixture()
    combined = combined_refit_rows(splits)
    selected, weights = strategy_rows_and_weights(combined, "rolling_3y")
    assert weights is None
    cutoff = pd.to_datetime(combined[ISSUE_TIME], utc=True).max() - pd.DateOffset(years=3)
    assert pd.to_datetime(selected[ISSUE_TIME], utc=True).min() >= cutoff
    assert pd.to_datetime(selected[ISSUE_TIME], utc=True).max() < TEST_START


def test_drift_diagnostics_use_unique_hourly_prices_and_issue_features():
    silver, splits = split_fixture()
    price, monthly, features = temporal_drift_tables(silver, splits)
    expected = {
        "mean", "median", "std", "minimum", "maximum", "p05", "p25",
        "p75", "p95", "negative_price_pct", "price_gte_200_pct",
    }
    assert expected.issubset(price.columns)
    assert price["period"].tolist() == ["train", "validation", "test"]
    assert {"monthly_mean", "monthly_median"}.issubset(monthly.columns)
    assert set(features["period"]) == {"train", "validation", "test"}
    assert features.groupby("period")["feature"].nunique().eq(9).all()


def test_drift_helpers_leave_production_artifacts_unchanged():
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in PRODUCTION_ARTIFACTS
    }
    _, splits = split_fixture()
    combined = combined_refit_rows(splits)
    strategy_rows_and_weights(combined, "recency_weighted_365d")
    after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in PRODUCTION_ARTIFACTS
    }
    assert after == before
