import pandas as pd

from models.model_evaluation import (
    COMPARISON_COLUMNS,
    build_comparison_dataframe,
    build_time_series_cv,
    chronological_holdout_split,
    select_best_result,
)


def sample_training_frame(row_count=20):
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2024-01-01", periods=row_count, freq="h", tz="UTC"
            ),
            "feature": range(row_count),
            "target_price_next_hour": range(1, row_count + 1),
        }
    )


def model_result(name, cv_rmse, test_rmse):
    return {
        "model_name": name,
        "tuning_status": "tuned_timeseries_cv",
        "cv_rmse": cv_rmse,
        "test_mae": test_rmse - 1,
        "test_rmse": test_rmse,
        "test_r2": 0.8,
    }


def test_chronological_holdout_preserves_order():
    data = sample_training_frame()

    X_train, X_test, y_train, y_test = chronological_holdout_split(
        data, "target_price_next_hour"
    )

    assert X_train.index.tolist() == list(range(16))
    assert X_test.index.tolist() == list(range(16, 20))
    assert y_train.index.max() < y_test.index.min()


def test_time_series_cv_never_shuffles_or_reverses_time():
    X_train = sample_training_frame(16)[["feature"]]
    splitter = build_time_series_cv(n_splits=3)

    for training_indices, validation_indices in splitter.split(X_train):
        assert list(training_indices) == sorted(training_indices)
        assert list(validation_indices) == sorted(validation_indices)
        assert training_indices.max() < validation_indices.min()


def test_tuning_folds_are_restricted_to_training_portion():
    data = sample_training_frame()
    X_train, X_test, _, _ = chronological_holdout_split(
        data, "target_price_next_hour"
    )
    final_test_indices = set(X_test.index)

    for training_indices, validation_indices in build_time_series_cv(3).split(X_train):
        original_fold_indices = set(X_train.iloc[training_indices].index) | set(
            X_train.iloc[validation_indices].index
        )
        assert original_fold_indices.isdisjoint(final_test_indices)


def test_comparison_dataframe_has_required_and_legacy_columns():
    results = [
        model_result("Linear Regression", 21.0, 20.0),
        model_result("XGBoost", 19.0, 18.0),
    ]

    comparison = build_comparison_dataframe(results, selected_model="XGBoost")

    assert comparison.columns.tolist() == COMPARISON_COLUMNS
    assert comparison.loc[comparison["model_name"] == "XGBoost", "selected"].item()
    assert comparison["rmse"].equals(comparison["test_rmse"])


def test_selection_uses_cv_rmse_not_test_rmse():
    results = [
        model_result("CV Winner", 10.0, 30.0),
        model_result("Holdout Winner", 12.0, 8.0),
    ]

    selected = select_best_result(results)

    assert selected["model_name"] == "CV Winner"
