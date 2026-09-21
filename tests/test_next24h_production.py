import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dashboard_data import load_next24h_forecast_report
from models.next24h import FINAL_FEATURES
from models.next24h_monitoring import (
    match_realized_forecasts,
    performance_metrics,
    update_next24h_monitoring,
)
from models.next24h_production import (
    ForecastUnavailableError,
    RELEASE_DIR,
    forecast_from_silver,
    load_next24h_release,
    run_next24h_forecast,
    save_forecast,
)
from storage.mappings import object_key
from storage.config import StorageConfig
from storage.sync import SyncResult, StorageSync


def silver_hours(count=220):
    hours = pd.date_range("2026-09-01T00:00Z", periods=count, freq="h")
    steps = np.arange(count, dtype=float)
    data = {"timestamp": hours}
    for feature in FINAL_FEATURES:
        if feature in {
            "price_eur_mwh", "load_mw", "biomass_mw", "lignite_mw",
            "gas_mw", "hard_coal_mw", "hydro_mw", "nuclear_mw",
            "solar_mw", "wind_offshore_mw", "wind_onshore_mw",
            "wind_total_mw", "temperature_2m", "relative_humidity_2m",
            "wind_speed_10m", "cloud_cover", "shortwave_radiation",
        }:
            data[feature] = 100.0 + steps / 10
    return pd.DataFrame(data)


def test_promoted_release_is_separate_and_matches_approved_candidate():
    model, features, manifest = load_next24h_release()
    assert len(model.estimators_) == 24
    assert features == tuple(FINAL_FEATURES)
    assert manifest["model_purpose"] == "next-24-hour electricity price forecasting"
    assert manifest["test_metrics"]["rmse"] == pytest.approx(44.18332312010295)
    assert manifest["persistence_test_metrics"]["rmse"] == pytest.approx(88.00941255701385)


def test_release_rejects_model_hash_and_feature_contract_tampering(tmp_path):
    release = tmp_path / "release"
    shutil.copytree(RELEASE_DIR, release)
    model_path = release / "next24h_model.joblib"
    model_path.write_bytes(model_path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_next24h_release(release)

    shutil.copyfile(RELEASE_DIR / "next24h_model.joblib", model_path)
    manifest_path = release / "next24h_release_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["features"] = manifest["features"][::-1]
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="feature contract"):
        load_next24h_release(release)


def test_production_forecast_exact_24_utc_targets_and_stale_refusal():
    model, features, manifest = load_next24h_release()
    silver = silver_hours()
    issue = silver["timestamp"].max()
    forecast = forecast_from_silver(
        silver, model, features, manifest["release_id"],
        now=issue + pd.Timedelta(minutes=30),
    )
    assert len(forecast) == 24
    assert forecast["horizon_hours"].tolist() == list(range(1, 25))
    targets = pd.to_datetime(forecast["target_timestamp"], utc=True)
    assert targets.is_unique and targets.is_monotonic_increasing
    assert targets.iloc[0] == issue + pd.Timedelta(hours=1)
    assert targets.iloc[-1] == issue + pd.Timedelta(hours=24)
    with pytest.raises(ForecastUnavailableError, match="freshness threshold"):
        forecast_from_silver(
            silver, model, features, manifest["release_id"],
            now=issue + pd.Timedelta(hours=4),
        )


def test_missing_latest_feature_history_refuses_issue():
    model, features, manifest = load_next24h_release()
    silver = silver_hours().drop(index=218)
    with pytest.raises(ForecastUnavailableError, match="feature history"):
        forecast_from_silver(
            silver, model, features, manifest["release_id"],
            now=silver["timestamp"].max() + pd.Timedelta(minutes=30),
        )


def test_local_forecast_and_append_only_history(tmp_path):
    silver = silver_hours()
    issue = silver["timestamp"].max()
    silver_path = tmp_path / "silver.csv"
    latest = tmp_path / "latest.csv"
    history = tmp_path / "history.csv"
    silver.to_csv(silver_path, index=False)
    first, changed = run_next24h_forecast(
        silver_path=silver_path, latest_path=latest, history_path=history,
        now=issue + pd.Timedelta(minutes=30),
    )
    assert changed and len(pd.read_csv(latest)) == len(pd.read_csv(history)) == 24
    assert list(pd.read_csv(latest).columns) == [
        "forecast_issue_time", "target_timestamp", "horizon_hours",
        "predicted_price_eur_mwh", "model_release",
    ]
    assert "issued_at_utc" in pd.read_csv(history).columns
    latest.unlink()  # Simulate interruption after the history write.
    second, changed = run_next24h_forecast(
        silver_path=silver_path, latest_path=latest, history_path=history,
        now=issue + pd.Timedelta(minutes=40),
    )
    assert not changed and len(pd.read_csv(history)) == len(pd.read_csv(latest)) == 24
    assert first.equals(second)
    next_hour = silver.tail(1).copy()
    next_hour["timestamp"] = issue + pd.Timedelta(hours=1)
    next_hour["price_eur_mwh"] += 1
    pd.concat([silver, next_hour], ignore_index=True).to_csv(silver_path, index=False)
    _, changed = run_next24h_forecast(
        silver_path=silver_path, latest_path=latest, history_path=history,
        now=issue + pd.Timedelta(hours=1, minutes=30),
    )
    assert changed and len(pd.read_csv(history)) == 48
    assert len(pd.read_csv(latest)) == 24
    with pytest.raises(ForecastUnavailableError):
        run_next24h_forecast(
            silver_path=silver_path, latest_path=latest, history_path=history,
            now=issue + pd.Timedelta(hours=5),
        )
    assert len(pd.read_csv(latest)) == 24
    assert len(pd.read_csv(history)) == 48


def test_realized_matching_requires_true_pre_target_issuance():
    model, features, manifest = load_next24h_release()
    silver = silver_hours()
    issue = silver["timestamp"].max()
    forecast = forecast_from_silver(
        silver, model, features, manifest["release_id"], now=issue,
    )
    history = forecast.copy()
    history["issued_at_utc"] = issue + pd.Timedelta(minutes=30)
    observed = pd.DataFrame({
        "target_timestamp": [issue + pd.Timedelta(hours=1), issue + pd.Timedelta(hours=2)],
        "price_eur_mwh": [50.0, 60.0],
    })
    realized = match_realized_forecasts(history, observed)
    assert len(realized) == 2
    assert (realized["absolute_error"] ** 2 == realized["squared_error"]).all()
    late_history = history.copy()
    late_history["issued_at_utc"] = issue + pd.Timedelta(hours=2)
    assert match_realized_forecasts(late_history, observed).empty
    assert performance_metrics(realized).empty
    metrics = performance_metrics(pd.concat([realized] * 5, ignore_index=True))
    assert set(metrics["horizon_hours"]) == {0, 1, 2}
    assert (metrics["rolling_rmse"] >= metrics["rolling_mae"]).all()


def test_monitoring_writes_realized_pairs_without_inventing_missing_prices(tmp_path):
    history_path = tmp_path / "history.csv"
    raw_path = tmp_path / "prices.csv"
    issue = pd.Timestamp("2026-09-21T08:00Z")
    history = pd.DataFrame({
        "forecast_issue_time": [issue] * 2,
        "target_timestamp": [issue + pd.Timedelta(hours=h) for h in (1, 2)],
        "horizon_hours": [1, 2],
        "predicted_price_eur_mwh": [50.0, 60.0],
        "model_release": ["release-v1"] * 2,
        "issued_at_utc": [issue + pd.Timedelta(minutes=30)] * 2,
    })
    history.to_csv(history_path, index=False)
    pd.DataFrame({
        "timestamp": [issue + pd.Timedelta(hours=1)],
        "price_eur_mwh": [40.0],
        "source_resolution": ["PT60M"],
    }).to_csv(raw_path, index=False)
    errors_path, metrics_path = tmp_path / "errors.csv", tmp_path / "metrics.csv"
    pair_count, metric_count = update_next24h_monitoring(
        history_path, raw_path, errors_path, metrics_path
    )
    errors = pd.read_csv(errors_path)
    assert (pair_count, metric_count) == (1, 0)
    assert errors["absolute_error"].tolist() == [10.0]
    assert errors["signed_error"].tolist() == [10.0]
    assert errors["squared_error"].tolist() == [100.0]
    assert pd.read_csv(metrics_path).empty


def test_next24h_s3_keys_and_dashboard_loader(tmp_path):
    assert object_key("data/reports/next24h_forecast.csv") == (
        "reports/predictions/next24h/next24h_forecast.csv"
    )
    assert object_key("artifacts/models/releases/next24h/next24h_model.joblib") == (
        "models/releases/next24h/next24h_model.joblib"
    )
    missing, error = load_next24h_forecast_report(tmp_path / "missing.csv")
    assert missing.empty and error
    model, features, manifest = load_next24h_release()
    silver = silver_hours()
    forecast = forecast_from_silver(
        silver, model, features, manifest["release_id"],
        now=silver["timestamp"].max(),
    )
    path = tmp_path / "forecast.csv"
    forecast.to_csv(path, index=False)
    loaded, error = load_next24h_forecast_report(path)
    assert error is None and len(loaded) == 24


def test_next24h_release_s3_group_uses_existing_storage_abstraction(tmp_path):
    class RecordingBackend:
        def __init__(self):
            self.keys = []

        def upload_file(self, source, key):
            assert source.is_file()
            self.keys.append(key)
            return True

    release = tmp_path / "artifacts/models/releases/next24h"
    shutil.copytree(RELEASE_DIR, release)
    backend = RecordingBackend()
    sync = StorageSync(StorageConfig("s3", "test-bucket"), tmp_path, backend=backend)
    result = sync.sync_group("next24h_release")
    assert len(result.uploaded) == 3
    assert backend.keys == result.uploaded
    assert all(key.startswith("models/releases/next24h/") for key in backend.keys)
    reports = tmp_path / "data/reports"
    reports.mkdir(parents=True)
    (reports / "next24h_forecast.csv").write_text("forecast_issue_time\n", encoding="utf-8")
    (reports / "next24h_forecast_history.csv").write_text("forecast_issue_time\n", encoding="utf-8")
    forecast_sync = sync.sync_group("next24h_forecasts")
    assert forecast_sync.uploaded == [
        "reports/predictions/next24h/next24h_forecast.csv",
        "reports/predictions/next24h/next24h_forecast_history.csv",
    ]


def test_prefect_stage_preserves_prior_forecast_on_unavailable_data(monkeypatch):
    import scheduled_pipeline as pipeline

    calls = []

    class LocalSync:
        config = StorageConfig("local")

        def sync_group(self, group):
            calls.append(group)
            return SyncResult(group, "NOT_REQUIRED")

    monkeypatch.setattr(pipeline, "verify_next24h_release_task", lambda: "release-v1")
    monkeypatch.setattr(
        pipeline, "next24h_forecast_task",
        lambda: (_ for _ in ()).throw(ForecastUnavailableError("stale Silver")),
    )
    monkeypatch.setattr(pipeline, "next24h_monitoring_task", lambda: (0, 0))
    monkeypatch.setattr(pipeline, "initialize_database", lambda: None)
    monkeypatch.setattr(
        pipeline, "log_data_quality_result",
        lambda *args: calls.append(args),
    )
    state = {
        "warnings": [], "objects_uploaded": [], "objects_unchanged": [],
        "s3_sync_status": "NOT_REQUIRED",
    }
    pipeline._run_next24h_stages(LocalSync(), state)
    assert state["next24h_forecast_status"] == "UNAVAILABLE"
    assert calls[0] == "next24h_release"
    assert "next24h_forecasts" not in calls
    assert any(isinstance(item, tuple) and item[0] == "next24h_forecast_freshness" for item in calls)


def test_prefect_keeps_one_hour_stage_before_next24h_without_training():
    source = (Path(__file__).parents[1] / "src/scheduled_pipeline.py").read_text()
    assert source.index("predictions_generated = prediction_report_task(mode)") < source.index(
        '_run_next24h_stages(storage_sync, storage_state)',
        source.index('predictions_generated = prediction_report_task(mode)'),
    )
    assert "evaluate_next24h" not in source
    assert ".fit(" not in source


def test_one_hour_release_still_loads_and_infers():
    from models.final_model_runtime import load_final_model_release, predict_with_final_model

    model, features = load_final_model_release()
    assert len(predict_with_final_model(
        pd.DataFrame([{feature: 0.0 for feature in features}]), model, features
    )) == 1
