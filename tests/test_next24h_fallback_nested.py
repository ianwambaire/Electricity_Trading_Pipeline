import hashlib

import numpy as np
import pandas as pd

from models.evaluate_next24h_fallback import TEST_START
from models.evaluate_next24h_fallback_nested import (
    STRATEGIES,
    aggregate_fold_results,
    build_rolling_folds,
    select_preferred_strategy,
    strategy_rows_and_weights,
)
from models.next24h import ISSUE_TIME
from tests.test_next24h_fallback import PRODUCTION_ARTIFACTS


def pretest_rows():
    issues = pd.date_range("2022-01-01", "2026-04-29T23:00", freq="h", tz="UTC")
    frame = pd.DataFrame({ISSUE_TIME: issues})
    frame["target_timestamp_24h"] = frame[ISSUE_TIME] + pd.Timedelta(hours=24)
    return frame.loc[frame["target_timestamp_24h"] < TEST_START].reset_index(drop=True)


def test_all_fold_training_targets_precede_validation_and_windows_are_contiguous():
    folds = build_rolling_folds(pretest_rows())
    assert [fold.season for fold in folds] == ["winter", "spring", "summer", "autumn"]
    for fold in folds:
        train_targets = pd.to_datetime(fold.training["target_timestamp_24h"], utc=True)
        validation_issues = pd.to_datetime(fold.validation[ISSUE_TIME], utc=True)
        validation_targets = pd.to_datetime(
            fold.validation["target_timestamp_24h"], utc=True
        )
        assert train_targets.max() < fold.validation_start
        assert validation_issues.min() == fold.validation_start
        assert validation_targets.max() < fold.validation_end
        assert validation_issues.is_monotonic_increasing
        assert validation_issues.diff().dropna().eq(pd.Timedelta(hours=1)).all()


def test_fold_construction_rejects_test_rows_or_targets():
    contaminated = pretest_rows()
    extra = contaminated.tail(1).copy()
    extra[ISSUE_TIME] = TEST_START
    extra["target_timestamp_24h"] = TEST_START + pd.Timedelta(hours=24)
    contaminated = pd.concat([contaminated, extra], ignore_index=True)
    try:
        build_rolling_folds(contaminated)
    except ValueError as exc:
        assert "pre-test" in str(exc)
    else:
        raise AssertionError("Test rows must be rejected during fold construction.")


def test_strategy_selection_uses_only_rolling_aggregate_columns():
    rows = []
    for index, strategy in enumerate(STRATEGIES):
        rows.append(
            {
                "strategy": strategy,
                "mean_rmse": 10.0 + index,
                "worst_fold_rmse": 20.0 + index,
                "mean_absolute_bias": 5.0 + index,
            }
        )
    aggregate = pd.DataFrame(rows)
    aggregate["test_rmse"] = [999.0] * (len(rows) - 1) + [0.01]
    assert select_preferred_strategy(aggregate) == STRATEGIES[0]


def test_aggregate_selection_metrics_match_predeclared_rules():
    metric_rows, extreme_rows = [], []
    for strategy_index, strategy in enumerate(STRATEGIES):
        for fold in ("a", "b", "c", "d"):
            metric_rows.append(
                {
                    "strategy": strategy,
                    "fold_id": fold,
                    "horizon_hours": 0,
                    "rmse": 10 + strategy_index,
                    "bias_predicted_minus_actual": -2 - strategy_index,
                }
            )
            extreme_rows.append(
                {
                    "strategy": strategy,
                    "fold_id": fold,
                    "price_regime": "price_gte_200_eur_mwh",
                    "observations": 10,
                    "rmse": 30 + strategy_index,
                }
            )
    aggregate = aggregate_fold_results(
        pd.DataFrame(metric_rows), pd.DataFrame(extreme_rows)
    )
    assert select_preferred_strategy(aggregate) == STRATEGIES[0]
    selected = aggregate.loc[aggregate["strategy"] == STRATEGIES[0]].iloc[0]
    assert selected["fold_count"] == 4
    assert selected["mean_rmse"] == 10
    assert selected["high_price_rmse"] == 30


def test_final_strategy_windows_and_weights_use_only_supplied_pretest_rows():
    pretest = pretest_rows()
    for strategy in STRATEGIES:
        selected, weights = strategy_rows_and_weights(pretest, strategy)
        assert pd.to_datetime(selected["target_timestamp_24h"], utc=True).max() < TEST_START
        if strategy.startswith("recency_weighted"):
            assert len(selected) == len(pretest) == len(weights)
            assert np.all(np.diff(weights) >= 0)
        else:
            assert weights is None


def test_nested_helpers_leave_production_artifacts_unchanged():
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in PRODUCTION_ARTIFACTS
    }
    folds = build_rolling_folds(pretest_rows())
    strategy_rows_and_weights(folds[-1].training, "recency_weighted_365d")
    after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in PRODUCTION_ARTIFACTS
    }
    assert after == before
