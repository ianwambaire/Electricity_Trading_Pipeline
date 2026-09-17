import pandas as pd
import pytest

from models.backtesting import TARGET_COLUMN, build_expanding_window_folds
from models.research_evaluation import (
    FEATURE_GROUPS,
    REGIME_LABELS,
    assign_price_regimes,
    build_ablation_aggregate,
    build_regime_performance,
    validate_feature_groups,
)


def test_feature_groups_are_permitted_complete_and_leakage_free():
    permitted = {feature for features in FEATURE_GROUPS.values() for feature in features}
    available = ["timestamp", *permitted, TARGET_COLUMN]

    validate_feature_groups(available)

    for features in FEATURE_GROUPS.values():
        assert TARGET_COLUMN not in features
        assert "timestamp" not in features
        assert set(features) <= permitted
    assert len(FEATURE_GROUPS["Full PowerFlow"]) == 31


def test_feature_groups_are_strictly_cumulative():
    previous = set()
    counts = []
    for features in FEATURE_GROUPS.values():
        current = set(features)
        if previous:
            assert previous < current
        previous = current
        counts.append(len(current))

    assert counts == [4, 10, 14, 26, 31]


def test_development_folds_exclude_2025():
    timestamps = pd.date_range(
        "2019-01-08T00:00:00Z",
        "2025-09-30T22:00:00Z",
        freq="h",
    )
    data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "price_eur_mwh": range(len(timestamps)),
            TARGET_COLUMN: range(1, len(timestamps) + 1),
        }
    )
    target_times = timestamps + pd.Timedelta(hours=1)
    holdout_indices = set(data.index[target_times >= pd.Timestamp("2025-01-01", tz="UTC")])

    for fold in build_expanding_window_folds(data):
        assert set(fold.train_indices).isdisjoint(holdout_indices)
        assert set(fold.validation_indices).isdisjoint(holdout_indices)


def test_price_regimes_are_mutually_exclusive_and_cover_targets():
    targets = pd.Series([-50.0, -0.01, 0.0, 99.99, 100.0, 199.99, 200.0, 500.0])

    regimes = assign_price_regimes(targets)

    assert regimes.astype(str).tolist() == [
        "Negative",
        "Negative",
        "Normal",
        "Normal",
        "High",
        "High",
        "Extreme",
        "Extreme",
    ]
    assert regimes.notna().all()
    assert set(regimes.astype(str)) == set(REGIME_LABELS)

    predictions = pd.DataFrame(
        {
            "model_name": "Linear Regression",
            "feature_group": "Full PowerFlow",
            "validation_period": "2024",
            "actual": targets,
            "predicted": targets + 1.0,
        }
    )
    report = build_regime_performance(predictions)
    yearly = report[report["validation_period"] == "2024"]
    assert yearly["observation_count"].sum() == len(targets)
    assert set(yearly["price_regime"]) == set(REGIME_LABELS)


def test_ablation_aggregate_improvements_use_correct_references():
    rows = []
    group_rmse = {
        "Time Only": 20.0,
        "Time + Price History": 16.0,
        "Time + Price + Load": 12.0,
        "Time + Price + Load + Generation": 10.0,
        "Full PowerFlow": 8.0,
    }
    for group_name, rmse in group_rmse.items():
        for year in ("2022", "2023", "2024"):
            rows.append(
                {
                    "model_name": "Linear Regression",
                    "feature_group": group_name,
                    "feature_count": len(FEATURE_GROUPS[group_name]),
                    "validation_period": year,
                    "mae": rmse / 2,
                    "rmse": rmse,
                }
            )

    aggregate = build_ablation_aggregate(
        pd.DataFrame(rows),
        persistence_mean_rmse=25.0,
    ).set_index("feature_group")

    full = aggregate.loc["Full PowerFlow"]
    assert full["improvement_vs_previous_feature_group_pct"] == pytest.approx(20.0)
    assert full["improvement_vs_time_only_pct"] == pytest.approx(60.0)
    assert full["improvement_vs_persistence_baseline_pct"] == pytest.approx(68.0)
