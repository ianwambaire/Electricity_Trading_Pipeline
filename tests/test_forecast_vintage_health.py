import json
import sqlite3
from pathlib import Path

import pandas as pd

import scheduled_pipeline
from ingestion.fetch_entsoe_forecasts import ENTSOE_FORECAST_COLUMNS
from ingestion.fetch_operational_weather_forecasts import WEATHER_FORECAST_COLUMNS
from monitoring.forecast_vintage_health import (
    SourceSpec,
    build_forecast_vintage_health_report,
    consecutive_collection_failures,
    write_forecast_vintage_health_report,
)


NOW = pd.Timestamp("2026-10-15T12:30:00Z")
ISSUE = pd.Timestamp("2026-10-15T12:00:00Z")
ACQUIRED = pd.Timestamp("2026-10-15T12:05:00Z")
CREATED = pd.Timestamp("2026-10-15T11:50:00Z")


def _entsoe_rows(
    document_type,
    process_type,
    technology,
    *,
    resolution="PT60M",
    periods=24,
    document_id=None,
    revision_number="1",
    issue=ISSUE,
    acquired=ACQUIRED,
):
    step = pd.Timedelta(resolution)
    targets = pd.date_range(issue + pd.Timedelta(hours=1), periods=periods, freq=step)
    document_id = document_id or f"{document_type}-{process_type}-{technology}-1"
    rows = []
    for index, target in enumerate(targets):
        rows.append(
            {
                "source": "ENTSOE",
                "document_type": document_type,
                "process_type": process_type,
                "document_id": document_id,
                "revision_number": revision_number,
                "source_created_at_utc": CREATED.isoformat(),
                "collection_issue_time": issue.isoformat(),
                "acquired_at_utc": acquired.isoformat(),
                "market_area": "DE_LU",
                "target_timestamp": target.isoformat(),
                "resolution": resolution,
                "source_horizon_minutes": (
                    target - CREATED
                ).total_seconds()
                / 60,
                "technology": technology,
                "value_mw": 10_000.0 + index,
            }
        )
    return rows


def _weather_rows(*, issue=ISSUE, acquired=ACQUIRED, horizons=range(1, 25)):
    return [
        {
            "collection_issue_time": issue.isoformat(),
            "acquired_at_utc": acquired.isoformat(),
            "target_timestamp": (issue + pd.Timedelta(hours=horizon)).isoformat(),
            "horizon_hours": horizon,
            "temperature_2m": 12.0 + horizon / 10,
            "relative_humidity_2m": 70.0,
            "wind_speed_10m": 8.0,
            "cloud_cover": 40.0,
            "shortwave_radiation": 100.0,
            "provider": "OPEN_METEO",
            "model": "best_match",
        }
        for horizon in horizons
    ]


def _write_frame(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


def _successful_collection_result():
    return {
        "status": "SUCCESS",
        "sources": [
            {"source": "ENTSOE_TOTAL_LOAD", "status": "SUCCESS", "s3_sync_status": "SUCCESS"},
            {"source": "ENTSOE_WIND_SOLAR", "status": "SUCCESS", "s3_sync_status": "SUCCESS"},
            {"source": "ENTSOE_TOTAL_GENERATION", "status": "SUCCESS", "s3_sync_status": "SUCCESS"},
            {"source": "OPEN_METEO", "status": "SUCCESS", "s3_sync_status": "SUCCESS"},
        ],
    }


def _create_complete_files(root):
    load_path = root / "data/raw/entsoe/forecasts/load.csv"
    wind_path = root / "data/raw/entsoe/forecasts/wind.csv"
    generation_path = root / "data/raw/entsoe/forecasts/generation.csv"
    weather_path = root / "data/raw/weather/forecast.csv"
    _write_frame(
        load_path,
        _entsoe_rows("A65", "A01", "TOTAL_LOAD"),
        ENTSOE_FORECAST_COLUMNS,
    )
    wind_rows = []
    for process, resolution, periods in (
        ("A01", "PT60M", 24),
        ("A40", "PT15M", 96),
    ):
        for technology in ("SOLAR", "WIND_OFFSHORE", "WIND_ONSHORE"):
            wind_rows.extend(
                _entsoe_rows(
                    "A69",
                    process,
                    technology,
                    resolution=resolution,
                    periods=periods,
                )
            )
    _write_frame(wind_path, wind_rows, ENTSOE_FORECAST_COLUMNS)
    _write_frame(
        generation_path,
        _entsoe_rows("A71", "A01", "TOTAL_GENERATION"),
        ENTSOE_FORECAST_COLUMNS,
    )
    _write_frame(weather_path, _weather_rows(), WEATHER_FORECAST_COLUMNS)
    specs = (
        SourceSpec("ENTSOE_TOTAL_LOAD", "ENTSOE", load_path, "A65", "A01", "ENTSOE_TOTAL_LOAD"),
        SourceSpec("ENTSOE_WIND_SOLAR_DAY_AHEAD", "ENTSOE", wind_path, "A69", "A01", "ENTSOE_WIND_SOLAR"),
        SourceSpec("ENTSOE_WIND_SOLAR_INTRADAY", "ENTSOE", wind_path, "A69", "A40", "ENTSOE_WIND_SOLAR"),
        SourceSpec("ENTSOE_TOTAL_GENERATION", "ENTSOE", generation_path, "A71", "A01", "ENTSOE_TOTAL_GENERATION"),
        SourceSpec("OPEN_METEO", "OPEN_METEO", weather_path, collection_result_source="OPEN_METEO"),
    )
    return specs


def _by_source(report):
    return {item["source"]: item for item in report["sources"]}


def test_fresh_complete_collection_is_healthy_and_preserves_endpoint_grain(tmp_path):
    specs = _create_complete_files(tmp_path)
    report = build_forecast_vintage_health_report(
        project_root=tmp_path,
        now=NOW,
        source_specs=specs,
        collection_result=_successful_collection_result(),
    )
    sources = _by_source(report)

    assert report["overall_status"] == "HEALTHY"
    assert all(source["status"] == "HEALTHY" for source in sources.values())
    assert sources["OPEN_METEO"]["observed_target_count"] == 24
    assert sources["OPEN_METEO"]["coverage_complete"] is True
    assert sources["ENTSOE_WIND_SOLAR_DAY_AHEAD"]["resolutions"] == ["PT60M"]
    assert sources["ENTSOE_WIND_SOLAR_INTRADAY"]["resolutions"] == ["PT15M"]
    assert sources["ENTSOE_WIND_SOLAR_DAY_AHEAD"]["process_type"] == "A01"
    assert sources["ENTSOE_WIND_SOLAR_INTRADAY"]["process_type"] == "A40"


def test_stale_collection_is_reported_as_stale(tmp_path):
    specs = _create_complete_files(tmp_path)
    report = build_forecast_vintage_health_report(
        project_root=tmp_path,
        now=NOW + pd.Timedelta(hours=4),
        source_specs=(specs[-1],),
        collection_result=_successful_collection_result(),
    )
    source = report["sources"][0]

    assert report["overall_status"] == "STALE"
    assert source["status"] == "STALE"
    assert source["acquisition_age_minutes"] > 180


def test_missing_open_meteo_horizon_degrades_only_that_provider(tmp_path):
    specs = _create_complete_files(tmp_path)
    weather_path = specs[-1].path
    _write_frame(
        weather_path,
        _weather_rows(horizons=[hour for hour in range(1, 25) if hour != 7]),
        WEATHER_FORECAST_COLUMNS,
    )
    report = build_forecast_vintage_health_report(
        project_root=tmp_path,
        now=NOW,
        source_specs=specs,
        collection_result=_successful_collection_result(),
    )
    sources = _by_source(report)

    assert report["overall_status"] == "DEGRADED"
    assert sources["OPEN_METEO"]["status"] == "DEGRADED"
    assert sources["OPEN_METEO"]["missing_target_count"] == 1
    assert sources["OPEN_METEO"]["missing_target_intervals"] == [
        {"provider": "OPEN_METEO", "model": "best_match", "horizon_hours": 7}
    ]
    assert sources["ENTSOE_TOTAL_LOAD"]["status"] == "HEALTHY"


def test_missing_entsoe_interval_uses_its_actual_resolution(tmp_path):
    specs = _create_complete_files(tmp_path)
    wind_path = specs[1].path
    wind = pd.read_csv(wind_path)
    missing_target = (ISSUE + pd.Timedelta(hours=3, minutes=15)).isoformat()
    wind = wind.loc[
        ~(
            (wind["process_type"] == "A40")
            & (wind["technology"] == "SOLAR")
            & (wind["target_timestamp"] == missing_target)
        )
    ]
    wind.to_csv(wind_path, index=False)
    report = build_forecast_vintage_health_report(
        project_root=tmp_path,
        now=NOW,
        source_specs=(specs[2],),
        collection_result=_successful_collection_result(),
    )
    source = report["sources"][0]

    assert source["status"] == "DEGRADED"
    assert source["missing_target_count"] == 1
    assert source["missing_target_intervals"][0]["resolution"] == "PT15M"


def test_duplicate_identity_is_counted_without_hiding_valid_health_data(tmp_path):
    specs = _create_complete_files(tmp_path)
    load_path = specs[0].path
    load = pd.read_csv(load_path)
    load = pd.concat([load, load.iloc[[0]]], ignore_index=True)
    load.to_csv(load_path, index=False)
    report = build_forecast_vintage_health_report(
        project_root=tmp_path,
        now=NOW,
        source_specs=(specs[0],),
        collection_result=_successful_collection_result(),
    )
    source = report["sources"][0]

    assert source["status"] == "DEGRADED"
    assert source["duplicate_identity_count"] == 1
    assert source["coverage_complete"] is True


def test_revision_presence_is_reported_without_collapsing_revisions(tmp_path):
    specs = _create_complete_files(tmp_path)
    load_path = specs[0].path
    load = pd.read_csv(load_path)
    revision = pd.DataFrame(
        _entsoe_rows(
            "A65",
            "A01",
            "TOTAL_LOAD",
            document_id="A65-revision-two",
            revision_number="2",
        ),
        columns=ENTSOE_FORECAST_COLUMNS,
    )
    pd.concat([load, revision], ignore_index=True).to_csv(load_path, index=False)
    report = build_forecast_vintage_health_report(
        project_root=tmp_path,
        now=NOW,
        source_specs=(specs[0],),
        collection_result=_successful_collection_result(),
    )
    source = report["sources"][0]

    assert source["status"] == "HEALTHY"
    assert source["revision_count"] == 2
    assert source["revision_numbers"] == ["1", "2"]
    assert source["newest_collection_rows"] == 48


def test_idempotent_reacquisition_uses_current_success_for_freshness(tmp_path):
    specs = _create_complete_files(tmp_path)
    current_cycle = ISSUE + pd.Timedelta(hours=1)
    current_acquired = current_cycle + pd.Timedelta(minutes=5)
    result = {
        "status": "SUCCESS",
        "sources": [
            {
                "source": "ENTSOE_TOTAL_LOAD",
                "status": "SUCCESS",
                "collection_issue_time": current_cycle.isoformat(),
                "endpoint_rows": {"load": 24},
                "endpoint_acquired_at_utc": {"load": current_acquired.isoformat()},
                "s3_sync_status": "SUCCESS",
            }
        ],
    }
    report = build_forecast_vintage_health_report(
        project_root=tmp_path,
        now=current_acquired + pd.Timedelta(minutes=20),
        source_specs=(specs[0],),
        collection_result=result,
    )
    source = report["sources"][0]

    assert source["status"] == "HEALTHY"
    assert source["latest_successful_collection_cycle"] == current_cycle.isoformat()
    assert source["coverage_collection_cycle"] == ISSUE.isoformat()
    assert source["latest_acquired_at_utc"] == current_acquired.isoformat()
    assert source["newest_collection_rows"] == 24


def test_missing_file_fails_source_and_report_is_written_atomically(tmp_path):
    missing = SourceSpec(
        "OPEN_METEO",
        "OPEN_METEO",
        tmp_path / "missing.csv",
        collection_result_source="OPEN_METEO",
    )
    destination = tmp_path / "reports/health.json"
    report = write_forecast_vintage_health_report(
        project_root=tmp_path,
        destination=destination,
        now=NOW,
        source_specs=(missing,),
    )

    assert report["overall_status"] == "FAILED"
    assert report["sources"][0]["status"] == "FAILED"
    assert json.loads(destination.read_text())["overall_status"] == "FAILED"


def test_consecutive_failures_are_read_from_operational_metadata(tmp_path):
    spec = SourceSpec(
        "OPEN_METEO",
        "OPEN_METEO",
        Path("unused.csv"),
        collection_result_source="OPEN_METEO",
    )
    database = tmp_path / "operational.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE pipeline_runs (id INTEGER PRIMARY KEY, run_time TEXT, status TEXT, records_processed INTEGER, message TEXT)"
        )
        for index, status in enumerate(("SUCCESS", "FAILED", "FAILED"), start=1):
            payload = {
                "forecast_vintage_collection": {
                    "sources": [{"source": "OPEN_METEO", "status": status}]
                }
            }
            connection.execute(
                "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?)",
                (index, f"2026-10-15T0{index}:00:00+00:00", "SUCCESS", 0, json.dumps(payload)),
            )

    assert consecutive_collection_failures(spec, database_path=database) == 2


def test_monitoring_failure_is_non_blocking_for_production_pipeline(monkeypatch):
    def fail_monitor(_collection_result):
        raise RuntimeError("monitor unavailable")

    monkeypatch.setattr(scheduled_pipeline, "forecast_vintage_health_task", fail_monitor)
    storage_state = {"warnings": []}
    result = scheduled_pipeline._run_forecast_vintage_health(
        _successful_collection_result(), storage_state
    )

    assert result == {"overall_status": "FAILED", "monitoring_error": "RuntimeError"}
    assert storage_state["forecast_vintage_health_status"] == "FAILED"
    assert "production forecasting continued" in storage_state["warnings"][0]

