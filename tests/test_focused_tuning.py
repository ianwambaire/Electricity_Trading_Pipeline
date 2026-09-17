from sklearn.base import clone

import pandas as pd

from models.backtesting import TARGET_COLUMN
from models.focused_tuning import (
    FINAL_HOLDOUT_START,
    LINEAR_MODEL_NAMES,
    RANDOM_STATE,
    build_focused_candidates,
    build_focused_development_folds,
    parameter_configurations,
    select_development_winner,
    validate_candidate_features,
)
from models.research_evaluation import FEATURE_GROUPS


def development_frame():
    timestamps = pd.date_range(
        "2019-01-08T00:00:00Z",
        "2025-09-30T22:00:00Z",
        freq="h",
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "price_eur_mwh": range(len(timestamps)),
            TARGET_COLUMN: range(1, len(timestamps) + 1),
        }
    )


def test_scaler_is_fitted_on_training_rows_only():
    ridge = next(
        candidate
        for candidate in build_focused_candidates()
        if candidate.name == "Ridge Regression"
    )
    training = pd.DataFrame({"feature": [1.0, 2.0, 3.0]})
    target = pd.Series([2.0, 4.0, 6.0])
    unseen_validation = pd.DataFrame({"feature": [1000.0]})

    model = clone(ridge.estimator)
    model.fit(training, target)

    assert model.named_steps["scaler"].mean_[0] == 2.0
    assert model.named_steps["scaler"].mean_[0] != pd.concat(
        [training, unseen_validation]
    )["feature"].mean()


def test_development_folds_are_time_aware_and_exclude_2025():
    data = development_frame()
    target_times = data["timestamp"] + pd.Timedelta(hours=1)
    holdout_start = pd.Timestamp(FINAL_HOLDOUT_START, tz="UTC")
    holdout_indices = set(data.index[target_times >= holdout_start])

    folds = build_focused_development_folds(data)

    assert [fold.validation_period for fold in folds] == ["2022", "2023", "2024"]
    for fold in folds:
        assert fold.train_end < fold.validation_start
        assert fold.validation_end < holdout_start
        assert set(fold.train_indices).isdisjoint(holdout_indices)
        assert set(fold.validation_indices).isdisjoint(holdout_indices)


def test_model_specific_feature_groups_are_respected_and_leakage_free():
    candidates = build_focused_candidates()
    all_features = FEATURE_GROUPS["Full PowerFlow"]
    validate_candidate_features(
        candidates,
        ["timestamp", *all_features, TARGET_COLUMN],
    )

    expected_groups = {
        **{name: "Full PowerFlow" for name in LINEAR_MODEL_NAMES},
        "Random Forest": "Time + Price History",
        "Gradient Boosting": "Time + Price + Load + Generation",
        "XGBoost": "Time + Price History",
    }
    assert {candidate.name: candidate.feature_group for candidate in candidates} == (
        expected_groups
    )
    for candidate in candidates:
        features = FEATURE_GROUPS[candidate.feature_group]
        assert TARGET_COLUMN not in features
        assert "timestamp" not in features


def test_development_winner_uses_mean_rmse_as_primary_metric():
    results = pd.DataFrame(
        [
            {
                "model_name": "Lower mean RMSE",
                "configuration_id": "first",
                "mean_rmse": 10.0,
                "rmse_std": 9.0,
                "extreme_2022_rmse": 50.0,
                "mean_mae": 9.0,
                "simplicity_rank": 2,
            },
            {
                "model_name": "More stable",
                "configuration_id": "second",
                "mean_rmse": 10.1,
                "rmse_std": 1.0,
                "extreme_2022_rmse": 10.0,
                "mean_mae": 5.0,
                "simplicity_rank": 1,
            },
        ]
    )

    winner = select_development_winner(results)

    assert winner["configuration_id"] == "first"


def test_stochastic_models_have_fixed_random_states_and_grids_are_reproducible():
    first = build_focused_candidates()
    second = build_focused_candidates()

    assert [parameter_configurations(item) for item in first] == [
        parameter_configurations(item) for item in second
    ]
    stochastic_names = {
        "Elastic Net",
        "Random Forest",
        "Gradient Boosting",
        "XGBoost",
    }
    for candidate in first:
        if candidate.name in stochastic_names:
            assert candidate.estimator.named_steps["model"].random_state == RANDOM_STATE

    tree_candidates = [item for item in first if item.include_untuned_reference]
    assert all(parameter_configurations(item)[0] == {} for item in tree_candidates)
