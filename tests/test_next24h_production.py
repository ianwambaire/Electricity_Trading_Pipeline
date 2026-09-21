import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dashboard_data import load_next24h_forecast_report
from models.next24h import FINAL_FEATURES, build_issue_features
from models.next24h_monitoring import (
    match_realized_forecasts,
    performance_metrics,
    update_next24h_monitoring,
)
from models.next24h_production import (
    ForecastUnavailableError,
    RELEASE_DIR,
    assemble_operational_issue_features,
    forecast_from_silver,
    load_next24h_release,
    run_next24h_forecast,
    save_forecast,
)
from ingestion.fetch_weather_data import WEATHER_VARIABLES, fetch_operational_weather
from processing.build_silver_dataset import clean_generation, clean_load, clean_prices
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


def operational_inputs(tmp_path, *, count=220, missing_market_hour=None, weather_offset=0):
    silver = silver_hours(count)
    hours = pd.to_datetime(silver["timestamp"], utc=True)
    prices = tmp_path / "prices.csv"
    load = tmp_path / "load.csv"
    generation = tmp_path / "generation.csv"
    pd.DataFrame({
        "timestamp": hours, "price_eur_mwh": silver["price_eur_mwh"],
        "source_resolution": "PT60M",
    }).to_csv(prices, index=False)
    quarter_hours = pd.DatetimeIndex(
        [hour + pd.Timedelta(minutes=minute) for hour in hours for minute in (0, 15, 30, 45)]
    )
    if missing_market_hour is not None:
        quarter_hours = quarter_hours[quarter_hours != missing_market_hour]
    pd.DataFrame({"timestamp": quarter_hours, "load_mw": 110.0}).to_csv(load, index=False)
    pd.DataFrame({
        "timestamp": quarter_hours,
        "Biomass": 10.0, "Fossil Brown coal/Lignite": 10.0,
        "Fossil Gas": 10.0, "Fossil Hard coal": 10.0,
        "Hydro Run-of-river and poundage": 10.0,
        "Nuclear": 0.0, "Solar": 10.0, "Wind Offshore": 5.0,
        "Wind Onshore": 5.0,
    }).to_csv(generation, index=False)

    class WeatherSession:
        def __init__(self):
            self.params = None

        def get(self, url, *, params, timeout):
            assert url == "https://api.open-meteo.com/v1/forecast"
            assert timeout == 60
            self.params = params
            end = pd.Timestamp(params["end_hour"], tz="UTC") + pd.Timedelta(hours=weather_offset)
            times = pd.date_range(end - pd.Timedelta(hours=4), end, freq="h")

            class Response:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {
                        "timezone": "GMT",
                        "utc_offset_seconds": 0,
                        "hourly": {
                            "time": [time.strftime("%Y-%m-%dT%H:%M") for time in times],
                            **{name: [50.0] * len(times) for name in WEATHER_VARIABLES},
                        },
                    }

            return Response()

    return (prices, load, generation), WeatherSession(), hours.iloc[-1]


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


def test_local_forecast_and_append_only_history(tmp_path, monkeypatch):
    (prices, load, generation), session, issue = operational_inputs(tmp_path)
    release_dir = RELEASE_DIR.resolve()
    silver = tmp_path / "data/processed/silver_electricity_market_data.csv"
    historical_weather = tmp_path / "data/raw/weather/open_meteo_weather.csv"
    for path in (silver, historical_weather):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unchanged historical data\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    latest = tmp_path / "latest.csv"
    history = tmp_path / "history.csv"
    provenance = tmp_path / "provenance.json"
    first, changed = run_next24h_forecast(
        release_dir=release_dir,
        prices_path=prices, load_path=load, generation_path=generation,
        latest_path=latest, history_path=history, provenance_path=provenance,
        now=issue + pd.Timedelta(hours=1, minutes=30), weather_session=session,
    )
    assert changed and len(pd.read_csv(latest)) == len(pd.read_csv(history)) == 24
    assert list(pd.read_csv(latest).columns) == [
        "forecast_issue_time", "target_timestamp", "horizon_hours",
        "predicted_price_eur_mwh", "model_release",
    ]
    assert "issued_at_utc" in pd.read_csv(history).columns
    assert json.loads(provenance.read_text())["weather_source"] == (
        "open_meteo_forecast_api_operational_model"
    )
    latest.unlink()  # Simulate interruption after the history write.
    second, changed = run_next24h_forecast(
        release_dir=release_dir,
        prices_path=prices, load_path=load, generation_path=generation,
        latest_path=latest, history_path=history, provenance_path=provenance,
        now=issue + pd.Timedelta(hours=1, minutes=40), weather_session=session,
    )
    assert not changed and len(pd.read_csv(history)) == len(pd.read_csv(latest)) == 24
    assert first.equals(second)
    next_hour = issue + pd.Timedelta(hours=1)
    price_data = pd.read_csv(prices)
    price_data.loc[len(price_data)] = [next_hour, 111.0, "PT60M"]
    price_data.to_csv(prices, index=False)
    for path in (load, generation):
        data = pd.read_csv(path)
        additions = data.tail(4).copy()
        additions["timestamp"] = [next_hour + pd.Timedelta(minutes=m) for m in (0, 15, 30, 45)]
        pd.concat([data, additions], ignore_index=True).to_csv(path, index=False)
    _, changed = run_next24h_forecast(
        release_dir=release_dir,
        prices_path=prices, load_path=load, generation_path=generation,
        latest_path=latest, history_path=history, provenance_path=provenance,
        now=issue + pd.Timedelta(hours=2, minutes=30), weather_session=session,
    )
    assert changed and len(pd.read_csv(history)) == 48
    assert len(pd.read_csv(latest)) == 24
    with pytest.raises(ForecastUnavailableError):
        run_next24h_forecast(
            release_dir=release_dir,
            prices_path=prices, load_path=load, generation_path=generation,
            latest_path=latest, history_path=history, provenance_path=provenance,
            now=issue + pd.Timedelta(hours=5), weather_session=session,
        )
    assert len(pd.read_csv(latest)) == 24
    assert len(pd.read_csv(history)) == 48
    assert silver.read_text() == "unchanged historical data\n"
    assert historical_weather.read_text() == "unchanged historical data\n"


def test_operational_weather_is_utc_bounded_and_separate_from_history(tmp_path):
    paths, session, issue = operational_inputs(tmp_path)
    historical = tmp_path / "open_meteo_weather.csv"
    historical.write_text("historical sentinel\n", encoding="utf-8")
    weather, acquired = fetch_operational_weather(
        issue + pd.Timedelta(hours=1, minutes=30), session=session,
    )
    assert acquired == issue + pd.Timedelta(hours=1, minutes=30)
    assert weather["timestamp"].dt.tz is not None
    assert weather["timestamp"].max() == issue + pd.Timedelta(hours=1)
    assert session.params["timezone"] == "UTC"
    assert session.params["end_hour"] == (issue + pd.Timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    assert historical.read_text() == "historical sentinel\n"


def test_operational_weather_rejects_duplicate_utc_hours_at_dst(tmp_path):
    _, session, _ = operational_inputs(tmp_path)

    class DuplicateSession:
        def get(self, *args, **kwargs):
            response = session.get(*args, **kwargs)
            payload = response.json()
            payload["hourly"]["time"][-1] = payload["hourly"]["time"][-2]

            class DuplicateResponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    return payload

            return DuplicateResponse()

    with pytest.raises(ValueError, match="unique exact UTC hours"):
        fetch_operational_weather(
            pd.Timestamp("2026-10-25T03:30Z"), session=DuplicateSession(),
        )


def test_operational_issue_ignores_future_market_rows(tmp_path):
    (prices, load, generation), session, issue = operational_inputs(tmp_path)
    future = issue + pd.Timedelta(hours=1)
    price_data = pd.read_csv(prices)
    price_data.loc[len(price_data)] = [future, 999.0, "PT60M"]
    price_data.to_csv(prices, index=False)
    for path in (load, generation):
        data = pd.read_csv(path)
        additions = data.tail(4).copy()
        additions["timestamp"] = [future + pd.Timedelta(minutes=m) for m in (0, 15, 30, 45)]
        pd.concat([data, additions], ignore_index=True).to_csv(path, index=False)
    row, provenance = assemble_operational_issue_features(
        prices_path=prices, load_path=load, generation_path=generation,
        now=issue + pd.Timedelta(hours=1, minutes=30), weather_session=session,
    )
    assert row["forecast_issue_time"].iloc[0] == issue
    assert provenance["market_latest_complete_hour"] == issue.isoformat()


def test_operational_issue_exact_contract_and_market_history(tmp_path):
    (prices, load, generation), session, issue = operational_inputs(tmp_path)
    row, provenance = assemble_operational_issue_features(
        prices_path=prices, load_path=load, generation_path=generation,
        now=issue + pd.Timedelta(hours=1, minutes=30), weather_session=session,
    )
    assert row["forecast_issue_time"].iloc[0] == issue
    assert tuple(row.drop(columns="forecast_issue_time")) == tuple(FINAL_FEATURES)
    assert row["price_lag_1h"].iloc[0] == pytest.approx(100 + 218 / 10)
    assert row["price_lag_24h"].iloc[0] == pytest.approx(100 + 195 / 10)
    assert row["price_lag_168h"].iloc[0] == pytest.approx(100 + 51 / 10)
    assert row["renewable_generation_mw"].iloc[0] == pytest.approx(40.0)
    assert row["renewable_share"].iloc[0] == pytest.approx(4 / 7)
    assert provenance["weather_hour"] == issue.isoformat()
    assert provenance["weather_acquired_at_utc"] == (
        issue + pd.Timedelta(hours=1, minutes=30)
    ).isoformat()


def test_operational_features_match_complete_gold_style_history(tmp_path):
    (prices, load, generation), session, issue = operational_inputs(tmp_path)
    row, _ = assemble_operational_issue_features(
        prices_path=prices, load_path=load, generation_path=generation,
        now=issue + pd.Timedelta(hours=1, minutes=30), weather_session=session,
    )
    silver = clean_prices(prices).join(clean_load(load)).join(clean_generation(generation))
    for name in WEATHER_VARIABLES:
        silver[name] = 50.0
    expected = build_issue_features(silver.rename_axis("timestamp").reset_index())
    expected = expected.loc[expected["timestamp"] == issue, list(FINAL_FEATURES)].iloc[0]
    np.testing.assert_allclose(
        row.loc[0, list(FINAL_FEATURES)].to_numpy(dtype=float),
        expected.to_numpy(dtype=float), rtol=1e-12, atol=1e-12,
    )
    assert tuple(row.columns) == ("forecast_issue_time", *FINAL_FEATURES)
    assert np.isfinite(row[list(FINAL_FEATURES)].to_numpy(dtype=float)).all()


def test_old_generation_gap_does_not_poison_later_price_load_history(tmp_path):
    (prices, load, generation), session, issue = operational_inputs(tmp_path)
    old_gap = issue - pd.Timedelta(hours=5) + pd.Timedelta(minutes=45)
    raw_generation = pd.read_csv(generation)
    raw_generation = raw_generation.loc[
        pd.to_datetime(raw_generation["timestamp"], utc=True) != old_gap
    ]
    raw_generation.to_csv(generation, index=False)
    assert old_gap.floor("h") not in clean_generation(generation).index
    row, _ = assemble_operational_issue_features(
        prices_path=prices, load_path=load, generation_path=generation,
        now=issue + pd.Timedelta(hours=1, minutes=30), weather_session=session,
    )
    assert row["forecast_issue_time"].iloc[0] == issue
    price = clean_prices(prices)["price_eur_mwh"]
    assert row["price_rolling_mean_24h"].iloc[0] == pytest.approx(price.loc[issue - pd.Timedelta(hours=23):issue].mean())
    assert row["price_rolling_std_24h"].iloc[0] == pytest.approx(price.loc[issue - pd.Timedelta(hours=23):issue].std())
    assert row["load_rolling_mean_24h"].iloc[0] == pytest.approx(110.0)


def test_missing_latest_generation_uses_previous_eligible_or_withholds(tmp_path):
    (prices, load, generation), session, issue = operational_inputs(tmp_path)
    raw_generation = pd.read_csv(generation)
    raw_generation = raw_generation.loc[
        pd.to_datetime(raw_generation["timestamp"], utc=True)
        != issue + pd.Timedelta(minutes=45)
    ]
    raw_generation.to_csv(generation, index=False)
    row, _ = assemble_operational_issue_features(
        prices_path=prices, load_path=load, generation_path=generation,
        now=issue + pd.Timedelta(hours=1, minutes=30), weather_session=session,
    )
    assert row["forecast_issue_time"].iloc[0] == issue - pd.Timedelta(hours=1)
    with pytest.raises(ForecastUnavailableError, match="Current generation unavailable"):
        assemble_operational_issue_features(
            prices_path=prices, load_path=load, generation_path=generation,
            now=issue + pd.Timedelta(hours=1, minutes=30), weather_session=session,
            max_age_hours=1.75,
        )


@pytest.mark.parametrize("source,hours_ago,expected", [
    ("price", 1, "Required price history unavailable"),
    ("price", 24, "Required price history unavailable"),
    ("price", 168, "Required price history unavailable"),
    ("load", 1, "Required load history unavailable"),
    ("load", 5, "Required load history unavailable"),
    ("load", 24, "Required load history unavailable"),
])
def test_missing_exact_historical_dependency_withholds(
    tmp_path, source, hours_ago, expected,
):
    (prices, load, generation), session, issue = operational_inputs(tmp_path)
    path = prices if source == "price" else load
    raw = pd.read_csv(path)
    missing = issue - pd.Timedelta(hours=hours_ago)
    if source == "load":
        missing += pd.Timedelta(minutes=45)
    raw = raw.loc[pd.to_datetime(raw["timestamp"], utc=True) != missing]
    raw.to_csv(path, index=False)
    with pytest.raises(ForecastUnavailableError, match=expected):
        assemble_operational_issue_features(
            prices_path=prices, load_path=load, generation_path=generation,
            now=issue + pd.Timedelta(hours=1, minutes=30), weather_session=session,
            max_age_hours=1.75,
        )


def test_operational_issue_uses_latest_eligible_not_gap_crossing(tmp_path):
    gap = pd.Timestamp("2026-09-10T02:45Z")
    (prices, load, generation), session, issue = operational_inputs(
        tmp_path, missing_market_hour=gap,
    )
    assert gap.floor("h") == issue - pd.Timedelta(hours=1)
    row, provenance = assemble_operational_issue_features(
        prices_path=prices, load_path=load, generation_path=generation,
        now=issue + pd.Timedelta(hours=1, minutes=30), weather_session=session,
        max_age_hours=4,
    )
    assert row["forecast_issue_time"].iloc[0] == issue - pd.Timedelta(hours=2)
    assert provenance["market_latest_complete_hour"] == issue.isoformat()


@pytest.mark.parametrize("weather_offset", [-5, 6])
def test_operational_issue_refuses_stale_or_missing_weather(tmp_path, weather_offset):
    (prices, load, generation), session, issue = operational_inputs(
        tmp_path, weather_offset=weather_offset,
    )
    with pytest.raises(ForecastUnavailableError, match="weather|issue hour"):
        assemble_operational_issue_features(
            prices_path=prices, load_path=load, generation_path=generation,
            now=issue + pd.Timedelta(hours=1, minutes=30), weather_session=session,
        )


def test_operational_issue_refuses_stale_market_before_weather_request(tmp_path):
    (prices, load, generation), session, issue = operational_inputs(tmp_path)
    with pytest.raises(ForecastUnavailableError, match="market hour"):
        assemble_operational_issue_features(
            prices_path=prices, load_path=load, generation_path=generation,
            now=issue + pd.Timedelta(hours=5), weather_session=session,
        )
    assert session.params is None


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
    (reports / "next24h_forecast_provenance.json").write_text("{}\n", encoding="utf-8")
    forecast_sync = sync.sync_group("next24h_forecasts")
    assert forecast_sync.uploaded == [
        "reports/predictions/next24h/next24h_forecast.csv",
        "reports/predictions/next24h/next24h_forecast_history.csv",
        "reports/predictions/next24h/next24h_forecast_provenance.json",
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
