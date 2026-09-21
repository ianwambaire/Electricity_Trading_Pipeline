import hashlib
import json

import joblib
import numpy as np
import pandas as pd
import pytest

from models.evaluate_next24h import chronological_splits, select_candidate
from models.final_model_runtime import load_final_model_release, predict_with_final_model
from models.next24h import (
    FINAL_FEATURES,
    FORECAST_COLUMNS,
    ISSUE_TIME,
    build_issue_features,
    build_training_data,
    create_next24h_forecast,
    generate_candidate_forecast,
    load_candidate_model,
)
from processing.build_gold_dataset import build_gold_dataset


def silver_hours(count=220, start="2026-03-25T00:00Z"):
    hours = pd.date_range(start, periods=count, freq="h")
    steps = np.arange(count, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": hours,
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


class FixedModel:
    def predict(self, features):
        assert features.columns.tolist() == list(FINAL_FEATURES)
        return np.arange(1, 25, dtype=float).reshape(1, 24)


def test_all_24_targets_use_exact_future_utc_hours():
    silver = silver_hours()
    data = build_training_data(silver)
    first = data.iloc[0]

    assert len(data) == 220 - 168 - 24
    assert first[ISSUE_TIME] == silver.loc[168, "timestamp"]
    for horizon in range(1, 25):
        assert first[f"target_timestamp_{horizon}h"] == (
            first[ISSUE_TIME] + pd.Timedelta(hours=horizon)
        )
        assert first[f"target_price_{horizon}h"] == silver.loc[168 + horizon, "price_eur_mwh"]


def test_targets_remain_hourly_utc_across_spring_dst():
    silver = silver_hours(start="2026-03-21T00:00Z")
    data = build_training_data(silver)
    issue = data.loc[data[ISSUE_TIME] == pd.Timestamp("2026-03-28T23:00Z")].iloc[0]
    targets = [issue[f"target_timestamp_{h}h"] for h in range(1, 25)]

    assert targets[0] == pd.Timestamp("2026-03-29T00:00Z")
    assert targets[-1] == pd.Timestamp("2026-03-29T23:00Z")
    assert all(
        later - earlier == pd.Timedelta(hours=1)
        for earlier, later in zip(targets, targets[1:])
    )


def test_issue_features_match_existing_gold_and_do_not_use_future_values(tmp_path):
    silver = silver_hours()
    silver_path, gold_path = tmp_path / "silver.csv", tmp_path / "gold.csv"
    silver.to_csv(silver_path, index=False)
    gold = build_gold_dataset(silver_path, gold_path)
    issues = build_issue_features(silver)
    matching = issues.iloc[:-1].reset_index(drop=True)
    np.testing.assert_allclose(
        matching[list(FINAL_FEATURES)].to_numpy(dtype=float),
        gold[list(FINAL_FEATURES)].to_numpy(dtype=float),
        atol=1e-9,
    )

    changed = silver.copy()
    changed.loc[changed.index > 180, "price_eur_mwh"] += 1000
    changed.loc[changed.index > 180, "temperature_2m"] += 1000
    original_issue = issues.loc[issues["timestamp"] == silver.loc[180, "timestamp"]]
    changed_issue = build_issue_features(changed).loc[
        lambda frame: frame["timestamp"] == silver.loc[180, "timestamp"]
    ]
    np.testing.assert_allclose(
        original_issue[list(FINAL_FEATURES)].to_numpy(dtype=float),
        changed_issue[list(FINAL_FEATURES)].to_numpy(dtype=float),
    )
    original_label = build_training_data(silver).loc[
        lambda frame: frame[ISSUE_TIME] == silver.loc[180, "timestamp"], "target_price_1h"
    ].item()
    changed_label = build_training_data(changed).loc[
        lambda frame: frame[ISSUE_TIME] == silver.loc[180, "timestamp"], "target_price_1h"
    ].item()
    assert changed_label == original_label + 1000


def test_missing_silver_hour_excludes_affected_candidate_issues():
    silver = silver_hours().drop(index=180)
    issues = build_issue_features(silver)
    training = build_training_data(silver)
    gap = silver_hours().loc[180, "timestamp"]
    assert gap not in set(issues["timestamp"])
    assert gap + pd.Timedelta(hours=1) not in set(issues["timestamp"])
    assert gap - pd.Timedelta(hours=1) not in set(training[ISSUE_TIME])


def test_gold_and_candidate_features_resume_only_with_exact_history(tmp_path):
    full = silver_hours(count=520)
    gaps = [full.loc[180, "timestamp"], full.loc[300, "timestamp"]]
    silver = full.loc[~full["timestamp"].isin(gaps)]
    silver_path, gold_path = tmp_path / "silver.csv", tmp_path / "gold.csv"
    silver.to_csv(silver_path, index=False)

    gold = build_gold_dataset(silver_path, gold_path)
    issues = build_issue_features(silver)
    gold_times = set(gold["timestamp"])
    issue_times = set(issues["timestamp"])
    for gap in gaps:
        assert gap not in gold_times
        assert gap + pd.Timedelta(hours=1) not in gold_times
        assert gap + pd.Timedelta(hours=23) not in gold_times
        assert gap + pd.Timedelta(hours=168) not in gold_times
        assert gap + pd.Timedelta(hours=24) not in gold_times
        assert gap + pd.Timedelta(hours=24) not in issue_times
        assert gap + pd.Timedelta(hours=25) in gold_times
        assert gap + pd.Timedelta(hours=25) in issue_times
        assert gap + pd.Timedelta(hours=168) not in issue_times
    assert gold["timestamp"].is_unique
    assert gold["timestamp"].is_monotonic_increasing


def test_candidate_refuses_latest_hour_with_incomplete_feature_history(tmp_path):
    silver = silver_hours().drop(index=218)
    silver_path = tmp_path / "silver.csv"
    silver.to_csv(silver_path, index=False)
    with pytest.raises(ValueError, match="Latest Silver hour lacks complete feature history"):
        generate_candidate_forecast(
            silver_path,
            tmp_path / "unused-model.joblib",
            tmp_path / "unused-manifest.json",
            tmp_path / "forecast.csv",
            now=silver["timestamp"].max() + pd.Timedelta(hours=1),
        )


def test_forecast_schema_order_and_missing_features():
    issue = build_issue_features(silver_hours()).tail(1).rename(
        columns={"timestamp": ISSUE_TIME}
    )
    forecast = create_next24h_forecast(
        issue, FixedModel(), model_release="unpromoted-test"
    )

    assert forecast.columns.tolist() == list(FORECAST_COLUMNS)
    assert len(forecast) == 24
    assert forecast["horizon_hours"].tolist() == list(range(1, 25))
    assert forecast["target_timestamp"].is_monotonic_increasing
    assert forecast["target_timestamp"].iloc[0] == issue[ISSUE_TIME].iloc[0] + pd.Timedelta(hours=1)
    assert forecast["target_timestamp"].iloc[-1] == issue[ISSUE_TIME].iloc[0] + pd.Timedelta(hours=24)
    with pytest.raises(ValueError, match="Missing candidate features"):
        create_next24h_forecast(
            issue.drop(columns=[FINAL_FEATURES[0]]), FixedModel(), model_release="test"
        )


def test_chronological_split_embargoes_cross_boundary_targets():
    times = pd.date_range("2025-12-30", "2026-05-03", freq="h")
    data = pd.DataFrame({ISSUE_TIME: times})
    data["target_timestamp_24h"] = data[ISSUE_TIME] + pd.Timedelta(hours=24)
    train, validation, test = chronological_splits(data).values()
    assert train["target_timestamp_24h"].max() < validation[ISSUE_TIME].min()
    assert validation["target_timestamp_24h"].max() < test[ISSUE_TIME].min()


def test_validation_selection_prefers_simpler_within_two_percent():
    metrics = pd.DataFrame(
        [
            {"split": "validation", "horizon_hours": 0, "model_name": "Linear Regression", "rmse": 10.1},
            {"split": "validation", "horizon_hours": 0, "model_name": "Random Forest", "rmse": 10.0},
            {"split": "validation", "horizon_hours": 0, "model_name": "Histogram Gradient Boosting", "rmse": 11.0},
        ]
    )
    assert select_candidate(metrics) == "Linear Regression"


def test_candidate_load_and_manual_report_are_separate_from_frozen_release(tmp_path):
    model_path = tmp_path / "candidate.joblib"
    manifest_path = tmp_path / "candidate_manifest.json"
    silver_path, output_path = tmp_path / "silver.csv", tmp_path / "forecast.csv"
    joblib.dump(FixedModel(), model_path)
    manifest_path.write_text(
        json.dumps(
            {
                "release_type": "next24h_candidate_not_promoted",
                "model_file": model_path.name,
                "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
                "features": list(FINAL_FEATURES),
            }
        ),
        encoding="utf-8",
    )
    silver_hours().to_csv(silver_path, index=False)
    model, manifest = load_candidate_model(model_path, manifest_path)
    assert manifest["release_type"] == "next24h_candidate_not_promoted"
    assert len(model.predict(build_issue_features(silver_hours()).tail(1)[list(FINAL_FEATURES)])[0]) == 24
    result = generate_candidate_forecast(
        silver_path, model_path, manifest_path, output_path,
        now=silver_hours()["timestamp"].iloc[-1] + pd.Timedelta(hours=1),
    )
    assert len(result) == len(pd.read_csv(output_path)) == 24
    with pytest.raises(FileExistsError):
        generate_candidate_forecast(silver_path, model_path, manifest_path, output_path)

    with pytest.raises(ValueError, match="stale"):
        generate_candidate_forecast(
            silver_path, model_path, manifest_path, tmp_path / "stale.csv",
            now=pd.Timestamp("2026-09-21T12:00Z"),
        )

    frozen_model, frozen_features = load_final_model_release()
    gold_row = pd.read_csv("data/features/gold_model_features.csv", nrows=1)
    assert len(predict_with_final_model(gold_row, frozen_model, frozen_features)) == 1
