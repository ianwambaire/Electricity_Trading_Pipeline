import pandas as pd
import pytest

from models.backtesting import (
    BASELINE_NAMES,
    baseline_source_timestamps,
    build_baseline_predictions,
    build_expanding_window_folds,
    calculate_rmse_improvement,
)


def hourly_price_data(row_count=200):
    prices = pd.Series(range(row_count), dtype="float64")
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2024-01-01",
                periods=row_count,
                freq="h",
                tz="UTC",
            ),
            "price_eur_mwh": prices,
            "target_price_next_hour": prices.shift(-1).fillna(prices.iloc[-1]),
        }
    )


def development_period_data():
    timestamps = pd.date_range(
        "2019-01-08T00:00:00Z",
        "2025-09-30T22:00:00Z",
        freq="h",
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "price_eur_mwh": range(len(timestamps)),
            "target_price_next_hour": range(1, len(timestamps) + 1),
        }
    )


def test_baseline_predictions_align_to_forecast_target_time():
    data = hourly_price_data()

    predictions = build_baseline_predictions(data)

    assert predictions.loc[168, "Persistence Baseline"] == 168.0
    assert predictions.loc[168, "Daily Seasonal Naive"] == 145.0
    assert predictions.loc[168, "Weekly Seasonal Naive"] == 1.0


def test_baselines_use_only_prices_available_by_prediction_time():
    data = hourly_price_data()
    sources = baseline_source_timestamps(data)
    current_times = pd.to_datetime(data["timestamp"], utc=True)
    forecast_times = current_times + pd.Timedelta(hours=1)

    for baseline_name in BASELINE_NAMES:
        assert (sources[baseline_name] <= current_times).all()
        assert (sources[baseline_name] < forecast_times).all()

    original = build_baseline_predictions(data)
    data["target_price_next_hour"] = 999999.0
    changed_target = build_baseline_predictions(data)
    pd.testing.assert_frame_equal(original, changed_target)


def test_expanding_windows_are_ordered_growing_and_precede_validation():
    folds = build_expanding_window_folds(development_period_data())

    assert [fold.validation_period for fold in folds] == ["2022", "2023", "2024"]
    assert [len(fold.train_indices) for fold in folds] == sorted(
        len(fold.train_indices) for fold in folds
    )
    assert len({len(fold.train_indices) for fold in folds}) == len(folds)

    for fold in folds:
        assert fold.train_end < fold.validation_start
        assert fold.validation_indices.is_monotonic_increasing
        assert fold.validation_end < pd.Timestamp("2025-01-01T00:00:00Z")


def test_final_holdout_is_excluded_from_development_folds():
    data = development_period_data()
    target_times = pd.to_datetime(data["timestamp"], utc=True) + pd.Timedelta(hours=1)
    holdout_indices = set(data.index[target_times >= pd.Timestamp("2025-01-01T00:00:00Z")])

    folds = build_expanding_window_folds(data)

    for fold in folds:
        assert set(fold.train_indices).isdisjoint(holdout_indices)
        assert set(fold.validation_indices).isdisjoint(holdout_indices)


def test_rmse_improvement_percentage():
    assert calculate_rmse_improvement(20.0, 25.0) == pytest.approx(20.0)
    assert calculate_rmse_improvement(30.0, 25.0) == pytest.approx(-20.0)
