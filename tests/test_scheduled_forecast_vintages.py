from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import scheduled_pipeline as pipeline
from storage import StorageConfig
from storage.sync import SyncResult


ACQUIRED = "2026-10-15T10:17:00+00:00"
COLLECTION_ISSUE = "2026-10-15T10:00:00+00:00"


def _successful_source(source="OPEN_METEO", destination="forecast.csv"):
    return {
        "source": source,
        "status": "SUCCESS",
        "rows_acquired": 24,
        "rows_newly_persisted": 24,
        "duplicate_rows": 0,
        "revision_count": None,
        "collection_issue_time": COLLECTION_ISSUE,
        "acquisition_timestamp": ACQUIRED,
        "local_destination": destination,
        "s3_sync_status": "PENDING",
    }


def _collection_result(*sources, validated=True):
    return {
        "status": "SUCCESS",
        "collection_issue_time": COLLECTION_ISSUE,
        "validated_local_persistence": validated,
        "sources": list(sources),
    }


def test_provider_failure_is_isolated_and_does_not_expose_provider_payload(
    tmp_path,
    monkeypatch,
):
    observed_paths = [
        tmp_path / "data/raw/entsoe/prices.csv",
        tmp_path / "data/raw/entsoe/load.csv",
        tmp_path / "data/raw/entsoe/generation.csv",
        tmp_path / "data/raw/weather/open_meteo_weather.csv",
    ]
    for path in observed_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("protected observed data\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in observed_paths}
    requested = {}
    secret_url = "https://example.invalid/?securityToken=must-not-escape"

    def fail_entsoe(*args, **kwargs):
        requested["entsoe_paths"] = kwargs["output_paths"]
        assert kwargs["collection_issue_time"] == pd.Timestamp(COLLECTION_ISSUE)
        assert "acquired_at_utc" not in kwargs
        raise RuntimeError(secret_url)

    def collect_weather(issue_time, **kwargs):
        requested["weather_path"] = kwargs["output_path"]
        assert issue_time == pd.Timestamp(COLLECTION_ISSUE)
        assert "acquired_at_utc" not in kwargs
        return {"path": str(kwargs["output_path"]), "new_rows": 24}

    monkeypatch.setattr(pipeline, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "collect_entsoe_forecast_vintages", fail_entsoe)
    monkeypatch.setattr(
        pipeline,
        "fetch_operational_weather_forecast_vintage",
        collect_weather,
    )
    monkeypatch.setattr(
        pipeline,
        "_validate_weather_collection_result",
        lambda result, acquired: _successful_source(
            destination=result["path"]
        ),
    )

    result = pipeline.forecast_vintage_collection_task.fn(ACQUIRED)

    assert result["status"] == "PARTIAL"
    assert [item["status"] for item in result["sources"]] == [
        "FAILED",
        "SUCCESS",
    ]
    assert result["sources"][0]["error_type"] == "RuntimeError"
    assert secret_url not in json.dumps(result)
    assert all(
        "data/raw/entsoe/forecasts" in str(path)
        for path in requested["entsoe_paths"].values()
    )
    assert str(requested["weather_path"]).endswith(
        "data/raw/weather/open_meteo_forecast_vintages.csv"
    )
    assert before == {path: path.read_bytes() for path in observed_paths}


def test_validated_collection_syncs_only_optional_forecast_vintage_group(
    monkeypatch,
):
    source = _successful_source()
    collection = _collection_result(source)
    calls = []

    class FakeSync:
        config = StorageConfig("s3", "bucket")

        def sync_group(self, group, *, require_all=True):
            calls.append((group, require_all))
            return SyncResult(
                group,
                "SUCCESS",
                uploaded=["raw/weather/operational-forecasts/forecast.csv"],
            )

    monkeypatch.setattr(
        pipeline,
        "forecast_vintage_collection_task",
        lambda: collection,
    )
    monkeypatch.setattr(pipeline, "initialize_database", lambda: None)
    monkeypatch.setattr(pipeline, "log_data_quality_result", lambda *args: None)
    state = {
        "s3_sync_status": "SUCCESS",
        "warnings": [],
        "objects_uploaded": [],
        "objects_unchanged": [],
    }

    result = pipeline._run_forecast_vintage_collection(FakeSync(), state)

    assert calls == [("forecast_vintages", False)]
    assert result["s3_sync_status"] == "SUCCESS"
    assert result["sources"][0]["s3_sync_status"] == "SUCCESS"
    assert state["s3_sync_status"] == "SUCCESS"
    assert state["objects_uploaded"] == [
        "raw/weather/operational-forecasts/forecast.csv"
    ]


def test_s3_sync_requires_successful_local_validation(monkeypatch):
    collection = _collection_result(_successful_source(), validated=False)

    class SyncMustNotRun:
        config = StorageConfig("s3", "bucket")

        def sync_group(self, *args, **kwargs):
            raise AssertionError("S3 sync ran before local validation")

    monkeypatch.setattr(
        pipeline,
        "forecast_vintage_collection_task",
        lambda: collection,
    )
    monkeypatch.setattr(pipeline, "initialize_database", lambda: None)
    monkeypatch.setattr(pipeline, "log_data_quality_result", lambda *args: None)
    state = {"warnings": [], "objects_uploaded": [], "objects_unchanged": []}

    result = pipeline._run_forecast_vintage_collection(SyncMustNotRun(), state)

    assert result["s3_sync_status"] == "NOT_ATTEMPTED"


def test_all_optional_sources_can_fail_without_raising_or_s3_sync(monkeypatch):
    failure = {
        "source": "ENTSOE",
        "status": "FAILED",
        "rows_acquired": 0,
        "rows_newly_persisted": 0,
        "duplicate_rows": 0,
        "revision_count": None,
        "collection_issue_time": COLLECTION_ISSUE,
        "acquisition_timestamp": None,
        "local_destination": None,
        "s3_sync_status": "NOT_ATTEMPTED",
        "error_type": "RuntimeError",
    }
    collection = {
        **_collection_result(failure, validated=False),
        "status": "FAILED",
    }
    production_forecast_calls = []

    class SyncMustNotRun:
        config = StorageConfig("s3", "bucket")

        def sync_group(self, *args, **kwargs):
            raise AssertionError("optional failed collection must not sync")

    monkeypatch.setattr(
        pipeline,
        "forecast_vintage_collection_task",
        lambda: collection,
    )
    monkeypatch.setattr(pipeline, "initialize_database", lambda: None)
    monkeypatch.setattr(pipeline, "log_data_quality_result", lambda *args: None)
    monkeypatch.setattr(
        pipeline,
        "run_next24h_forecast",
        lambda: production_forecast_calls.append(True),
    )
    state = {"warnings": [], "objects_uploaded": [], "objects_unchanged": []}

    result = pipeline._run_forecast_vintage_collection(SyncMustNotRun(), state)

    assert result["status"] == "FAILED"
    assert result["s3_sync_status"] == "NOT_ATTEMPTED"
    assert production_forecast_calls == []
    assert state["warnings"] == [
        "Optional forecast-vintage source ENTSOE failed (RuntimeError)."
    ]


def test_reacquisition_metrics_preserve_idempotent_duplicate_count(monkeypatch):
    duplicate = _successful_source()
    duplicate.update(rows_newly_persisted=0, duplicate_rows=24)
    collection = _collection_result(duplicate)

    class LocalSync:
        config = StorageConfig("local")

        def sync_group(self, group, *, require_all=True):
            return SyncResult(group, "NOT_REQUIRED")

    monkeypatch.setattr(
        pipeline,
        "forecast_vintage_collection_task",
        lambda: collection,
    )
    monkeypatch.setattr(pipeline, "initialize_database", lambda: None)
    monkeypatch.setattr(pipeline, "log_data_quality_result", lambda *args: None)
    state = {"warnings": [], "objects_uploaded": [], "objects_unchanged": []}

    result = pipeline._run_forecast_vintage_collection(LocalSync(), state)

    assert result["sources"][0]["rows_acquired"] == 24
    assert result["sources"][0]["rows_newly_persisted"] == 0
    assert result["sources"][0]["duplicate_rows"] == 24
    assert result["sources"][0]["s3_sync_status"] == "NOT_REQUIRED"


def test_stage_is_wired_without_calling_or_replacing_production_forecasting():
    source = Path(pipeline.__file__).read_text(encoding="utf-8")
    collection = source.index(
        "_run_forecast_vintage_collection(storage_sync, storage_state, run_id)"
    )
    existing_forecast = source.index(
        "_run_next24h_stages(storage_sync, storage_state, run_id)",
        collection,
    )

    assert collection < existing_forecast
    assert "run_next24h_forecast" not in source[
        source.index("def _run_forecast_vintage_collection") :
        source.index("def _run_next24h_stages")
    ]
