import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from api.app import APISettings, create_app


ISSUE = pd.Timestamp("2026-10-15T12:00:00Z")


def _settings(root: Path) -> APISettings:
    return APISettings.from_root(root)


def _client(root: Path) -> TestClient:
    return TestClient(create_app(_settings(root)))


def _write_next24(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "forecast_issue_time": [ISSUE] * 24,
            "target_timestamp": [
                ISSUE + pd.Timedelta(hours=horizon) for horizon in range(1, 25)
            ],
            "horizon_hours": list(range(1, 25)),
            "predicted_price_eur_mwh": [50.0 + horizon for horizon in range(1, 25)],
            "model_release": ["next24h-test-release"] * 24,
        }
    ).to_csv(path, index=False)


def _write_one_hour(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "timestamp": [ISSUE + pd.Timedelta(hours=1)],
            "actual_price": [55.0],
            "predicted_price": [53.5],
        }
    ).to_csv(path, index=False)


def _write_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "next24h_forecast_status": "GENERATED",
        "message": "Pipeline completed.",
    }
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_time TEXT NOT NULL,
                status TEXT NOT NULL,
                records_processed INTEGER,
                message TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO pipeline_runs (run_time, status, records_processed, message) VALUES (?, ?, ?, ?)",
            (ISSUE.isoformat(), "SUCCESS", 100, json.dumps(metadata)),
        )


def _write_monitoring_reports(settings: APISettings) -> None:
    settings.forecast_vintage_health.parent.mkdir(parents=True, exist_ok=True)
    settings.forecast_vintage_health.write_text(
        json.dumps(
            {
                "overall_status": "HEALTHY",
                "generated_at_utc": ISSUE.isoformat(),
                "sources": [{"source": "OPEN_METEO", "status": "HEALTHY"}],
            }
        ),
        encoding="utf-8",
    )
    settings.exogenous_readiness.write_text(
        json.dumps(
            {
                "dataset_status": "NOT_READY",
                "output_rows": 0,
                "leakage_check": {"passed": True},
            }
        ),
        encoding="utf-8",
    )


def test_health_endpoint_is_utc_and_cors_is_disabled_by_default(tmp_path):
    response = _client(tmp_path).get("/health", headers={"Origin": "https://example.com"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["application"] == "PowerFlow API"
    assert pd.Timestamp(payload["timestamp_utc"]).tzinfo is not None
    assert "access-control-allow-origin" not in response.headers


def test_pipeline_status_reads_latest_sqlite_metadata_read_only(tmp_path):
    settings = _settings(tmp_path)
    _write_database(settings.operational_database)

    response = _client(tmp_path).get("/pipeline/status")

    assert response.status_code == 200
    assert response.json() == {
        "latest_run_status": "SUCCESS",
        "latest_run_timestamp": "2026-10-15T12:00:00Z",
        "forecast_status": "GENERATED",
    }


def test_next24_endpoint_returns_existing_validated_report(tmp_path):
    settings = _settings(tmp_path)
    _write_next24(settings.next24_forecast)

    response = _client(tmp_path).get("/forecast/next24")

    assert response.status_code == 200
    payload = response.json()
    assert payload["row_count"] == 24
    assert payload["forecasts"][0] == {
        "issue_time": "2026-10-15T12:00:00Z",
        "target_time": "2026-10-15T13:00:00Z",
        "horizon_hours": 1,
        "predicted_price_eur_mwh": 51.0,
        "model_release": "next24h-test-release",
    }
    assert payload["forecasts"][-1]["horizon_hours"] == 24


def test_one_hour_endpoint_exposes_only_existing_report(tmp_path):
    settings = _settings(tmp_path)
    _write_one_hour(settings.one_hour_forecast)

    response = _client(tmp_path).get("/forecast/one-hour")

    assert response.status_code == 200
    assert response.json() == {
        "row_count": 1,
        "forecasts": [
            {
                "target_time": "2026-10-15T13:00:00Z",
                "actual_price_eur_mwh": 55.0,
                "predicted_price_eur_mwh": 53.5,
            }
        ],
    }


def test_missing_and_invalid_reports_have_clear_status_codes(tmp_path):
    client = _client(tmp_path)
    assert client.get("/forecast/next24").status_code == 404
    assert client.get("/forecast/one-hour").status_code == 404
    assert client.get("/monitoring/forecast-vintages").status_code == 404
    assert client.get("/monitoring/exogenous-readiness").status_code == 404
    assert client.get("/pipeline/status").status_code == 503

    settings = _settings(tmp_path)
    settings.exogenous_readiness.parent.mkdir(parents=True, exist_ok=True)
    settings.exogenous_readiness.write_text("not-json", encoding="utf-8")
    response = client.get("/monitoring/exogenous-readiness")
    assert response.status_code == 503
    assert response.json()["detail"] == "Exogenous readiness report is invalid or unreadable."


def test_monitoring_endpoints_return_reports_and_redact_sensitive_keys(tmp_path):
    settings = _settings(tmp_path)
    _write_monitoring_reports(settings)
    payload = json.loads(settings.forecast_vintage_health.read_text())
    payload["api_token"] = "must-not-be-returned"
    settings.forecast_vintage_health.write_text(json.dumps(payload), encoding="utf-8")
    client = _client(tmp_path)

    health = client.get("/monitoring/forecast-vintages")
    readiness = client.get("/monitoring/exogenous-readiness")

    assert health.status_code == 200
    assert health.json()["overall_status"] == "HEALTHY"
    assert health.json()["api_token"] == "[REDACTED]"
    assert "must-not-be-returned" not in health.text
    assert readiness.status_code == 200
    assert readiness.json()["dataset_status"] == "NOT_READY"
    assert readiness.json()["leakage_check"] == {"passed": True}


def test_requests_do_not_write_or_modify_any_source_file(tmp_path):
    settings = _settings(tmp_path)
    _write_database(settings.operational_database)
    _write_next24(settings.next24_forecast)
    _write_one_hour(settings.one_hour_forecast)
    _write_monitoring_reports(settings)
    paths = [
        settings.operational_database,
        settings.next24_forecast,
        settings.one_hour_forecast,
        settings.forecast_vintage_health,
        settings.exogenous_readiness,
    ]
    before = {
        path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in paths
    }
    client = _client(tmp_path)

    for route in (
        "/pipeline/status",
        "/forecast/next24",
        "/forecast/one-hour",
        "/monitoring/forecast-vintages",
        "/monitoring/exogenous-readiness",
    ):
        assert client.get(route).status_code == 200

    after = {
        path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in paths
    }
    assert after == before


def test_api_never_invokes_production_inference(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _write_next24(settings.next24_forecast)
    import models.next24h_production as production

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Production inference must not be called by the API")

    monkeypatch.setattr(production, "run_next24h_forecast", forbidden)

    response = _client(tmp_path).get("/forecast/next24")
    assert response.status_code == 200
    assert response.json()["row_count"] == 24

