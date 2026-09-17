import json

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression

from models.backtesting import TARGET_COLUMN, build_baseline_predictions
from models.final_evaluation import (
    FINAL_FEATURES,
    FINAL_FEATURE_GROUP,
    FINAL_HOLDOUT_END,
    FINAL_HOLDOUT_START,
    FINAL_MODEL_NAME,
    build_final_metrics,
    build_final_model,
    ensure_release_not_completed,
    evaluate_final_baselines,
    final_chronological_split,
    fit_and_predict_final_model,
    validate_frozen_features,
    write_final_release_manifest,
)


def final_period_data():
    timestamps = pd.date_range(
        "2024-12-24T00:00:00Z",
        "2025-09-30T22:00:00Z",
        freq="h",
    )
    base = np.arange(len(timestamps), dtype="float64")
    data = pd.DataFrame({"timestamp": timestamps})
    for position, feature in enumerate(FINAL_FEATURES):
        data[feature] = base + position
    data["price_eur_mwh"] = base
    data[TARGET_COLUMN] = base + 1.0
    return data


def test_final_split_excludes_2025_targets_from_training():
    split = final_chronological_split(final_period_data())

    assert split.training_target_times.max() < FINAL_HOLDOUT_START
    assert split.holdout_target_times.min() == FINAL_HOLDOUT_START
    assert split.holdout_target_times.max() == FINAL_HOLDOUT_END
    assert len(split.holdout_data) == 6552
    assert set(split.training_data.index).isdisjoint(split.holdout_data.index)


def test_scaler_is_fitted_only_on_final_training_data():
    split = final_chronological_split(final_period_data())

    model, _ = fit_and_predict_final_model(split)

    expected_means = split.training_data[list(FINAL_FEATURES)].mean().to_numpy()
    np.testing.assert_allclose(model.named_steps["scaler"].mean_, expected_means)
    full_means = pd.concat([split.training_data, split.holdout_data])[
        list(FINAL_FEATURES)
    ].mean().to_numpy()
    assert not np.allclose(model.named_steps["scaler"].mean_, full_means)


def test_model_design_and_feature_set_are_frozen_without_tuning():
    data = final_period_data()
    validate_frozen_features(data)
    model = build_final_model()

    assert FINAL_MODEL_NAME == "Ordinary Linear Regression"
    assert FINAL_FEATURE_GROUP == "Full PowerFlow"
    assert len(FINAL_FEATURES) == 31
    assert list(model.named_steps) == ["scaler", "model"]
    assert isinstance(model.named_steps["model"], LinearRegression)
    assert model.named_steps["model"].get_params()["fit_intercept"] is True


def test_final_holdout_prediction_is_made_exactly_once():
    class CountingModel:
        def __init__(self):
            self.fit_calls = 0
            self.predict_calls = 0

        def fit(self, features, target):
            self.fit_calls += 1
            return self

        def predict(self, features):
            self.predict_calls += 1
            return np.zeros(len(features))

    split = final_chronological_split(final_period_data())
    counting_model = CountingModel()

    returned_model, predictions = fit_and_predict_final_model(
        split,
        model=counting_model,
    )

    assert returned_model.fit_calls == 1
    assert returned_model.predict_calls == 1
    assert len(predictions) == len(split.holdout_data)


def test_final_baselines_preserve_forecast_timestamp_alignment():
    data = final_period_data()
    split = final_chronological_split(data)
    predictions = build_baseline_predictions(data)
    first_index = split.holdout_data.index[0]

    assert predictions.loc[first_index, "Persistence Baseline"] == data.loc[
        first_index, "price_eur_mwh"
    ]
    assert predictions.loc[first_index, "Daily Seasonal Naive"] == data.loc[
        first_index - 23, "price_eur_mwh"
    ]
    assert predictions.loc[first_index, "Weekly Seasonal Naive"] == data.loc[
        first_index - 167, "price_eur_mwh"
    ]


def test_release_manifest_records_final_holdout_usage(tmp_path):
    data = final_period_data()
    dataset_path = tmp_path / "gold.csv"
    data.to_csv(dataset_path, index=False)
    split = final_chronological_split(data)
    model, predictions = fit_and_predict_final_model(split)
    baselines = evaluate_final_baselines(data, split)
    metrics = build_final_metrics(split, predictions, baselines)
    manifest_path = tmp_path / "final_manifest.json"

    write_final_release_manifest(
        manifest_path=manifest_path,
        dataset_path=dataset_path,
        data=data,
        split=split,
        metrics=metrics,
        baselines=baselines,
        git_commit_sha="abc123",
        mlflow_run_id="final-run-id",
        model_path=tmp_path / "model.joblib",
        feature_path=tmp_path / "features.joblib",
        metrics_path=tmp_path / "metrics.csv",
        baselines_path=tmp_path / "baselines.csv",
        regime_path=tmp_path / "regimes.csv",
    )
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert saved["final_holdout_used"] is True
    assert saved["model"]["selected_model"] == FINAL_MODEL_NAME
    assert saved["model"]["hyperparameters_selected_using_holdout"] is False
    assert saved["final_holdout"]["rows"] == 6552
    with pytest.raises(FileExistsError):
        ensure_release_not_completed(manifest_path)
