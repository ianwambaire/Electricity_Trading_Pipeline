import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
import streamlit as st

import store_data
from notifications.email_alert import alert_cooldown_hours, failure_fingerprint
from dashboard_data import prediction_count_metrics, summarize_next24h_forecast
from dashboard_health import (
    age_label,
    assess_operational_health,
    filter_incidents,
    forecast_freshness_state,
    load_recent_incidents,
    load_recent_stage_timings,
    model_performance_state,
    source_freshness_state,
    summarize_pipeline_timings,
)
from models.next24h_monitoring import summarize_realized_performance
from scheduled_pipeline import _record_protected_generation_conflicts, _timed_stage


NOW = pd.Timestamp("2026-09-21T20:30:00Z")


def health(**overrides):
    inputs = {
        "latest_run_status": "SUCCESS",
        "latest_success_time": NOW - pd.Timedelta(minutes=45),
        "core_source_timestamps": {
            "prices": NOW - pd.Timedelta(hours=1),
            "load": NOW - pd.Timedelta(hours=1),
            "generation": NOW - pd.Timedelta(hours=1),
        },
        "forecast_issue_time": NOW - pd.Timedelta(hours=1),
        "forecast_withheld": False,
        "quality_state": {"failed": 0, "warnings": 0},
        "unresolved_gap_count": 0,
        "required_artifacts_available": True,
        "now": NOW,
    }
    inputs.update(overrides)
    return assess_operational_health(**inputs)


def test_health_rules_and_expected_archive_lag():
    assert health()["label"] == "Healthy"
    assert health(forecast_issue_time=NOW - pd.Timedelta(hours=4))["label"] == "Warning"
    assert health(forecast_withheld=True)["label"] == "Warning"
    assert health(latest_run_status="FAILED")["label"] == "Degraded"
    assert health(quality_state={"failed": 1, "warnings": 0})["label"] == "Degraded"
    assert health(required_artifacts_available=False)["label"] == "Degraded"
    assert source_freshness_state(
        NOW - pd.Timedelta(days=6), source_kind="historical_weather", now=NOW
    ) == "Archive history"
    assert health()["label"] == "Healthy"  # Archive age is not a live-health input.
    assert age_label(NOW - pd.Timedelta(minutes=18), now=NOW) == "18 min ago"
    assert forecast_freshness_state(None, now=NOW) == "Unavailable"
    assert forecast_freshness_state(NOW, now=NOW, withholding_known=True).startswith("Withheld")


def test_incident_write_read_dedupe_filter_and_redaction(temporary_database):
    first = store_data.log_incident(
        "WARNING", "next24h forecast", "forecast_withheld", "ACTIVE",
        "Weather token=do-not-display unavailable",
        {"api_key": "secret-value", "source": "Open-Meteo"},
    )
    repeated = store_data.log_incident(
        "WARNING", "next24h forecast", "forecast_withheld", "ACTIVE",
        "Weather token=do-not-display unavailable",
        {"api_key": "secret-value", "source": "Open-Meteo"},
    )
    assert first and not repeated
    assert store_data.incident_is_active("next24h forecast", "forecast_withheld")
    store_data.log_incident(
        "INFO", "ENTSO-E generation", "generation_revision", "RECORDED",
        "Two recent source revisions accepted.", {"by_column": {"Fossil Gas": 2}},
    )
    st.cache_data.clear()
    history = load_recent_incidents(temporary_database)
    assert len(history) == 2
    assert len(filter_incidents(history, severity="WARNING")) == 1
    assert len(filter_incidents(history, component="ENTSO-E generation")) == 1
    assert "do-not-display" not in history.to_string()
    assert "secret-value" not in history.to_string()
    assert "[REDACTED]" in history.to_string()
    store_data.log_incident(
        "INFO", "next24h forecast", "forecast_withheld", "RESOLVED",
        "Forecasting recovered.",
    )
    assert not store_data.incident_is_active("next24h forecast", "forecast_withheld")
    store_data.initialize_database()  # Idempotent migration preserves rows.
    with sqlite3.connect(temporary_database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM operational_incidents").fetchone()[0] == 3


def test_incident_dedupe_uses_canonical_sanitized_details(temporary_database):
    args = ("WARNING", "ENTSO-E", "source_gap", "ACTIVE", "Four intervals missing.")
    first = {
        "missing_count": 4,
        "first_unresolved_timestamp": "2026-09-21T08:45:00+00:00",
        "api_token": "first-secret",
    }
    same_safe_details = {
        "api_token": "second-secret",
        "first_unresolved_timestamp": "2026-09-21T08:45:00+00:00",
        "missing_count": 4,
    }
    different_gap = {
        "missing_count": 4,
        "first_unresolved_timestamp": "2026-09-21T11:45:00+00:00",
    }

    assert store_data.log_incident(*args, first)
    assert not store_data.log_incident(*args, same_safe_details)
    assert store_data.log_incident(*args, different_gap)

    with sqlite3.connect(temporary_database) as connection:
        details = [row[0] for row in connection.execute(
            "SELECT details_json FROM operational_incidents ORDER BY id"
        )]
    assert len(details) == 2
    assert details[0] != details[1]
    assert "first-secret" not in str(details)
    assert "second-secret" not in str(details)
    assert "api_token" not in str(details)


def test_identical_incident_is_recorded_after_dedupe_window(temporary_database):
    args = ("WARNING", "ENTSO-E", "source_gap", "ACTIVE", "Four intervals missing.")
    details = {"first_unresolved_timestamp": "2026-09-21T08:45:00+00:00"}
    assert store_data.log_incident(*args, details)
    older_than_window = (datetime.now(timezone.utc) - timedelta(minutes=61)).isoformat()
    with sqlite3.connect(temporary_database) as connection:
        connection.execute(
            "UPDATE operational_incidents SET timestamp_utc = ? WHERE id = 1",
            (older_than_window,),
        )

    assert store_data.log_incident(*args, details)
    with sqlite3.connect(temporary_database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM operational_incidents"
        ).fetchone()[0] == 2


def test_failure_alert_cooldown_new_duplicate_expired_and_distinct(
    temporary_database, monkeypatch,
):
    import scheduled_pipeline as pipeline

    sent = []
    monkeypatch.setenv("POWERFLOW_ALERT_COOLDOWN_HOURS", "12")
    monkeypatch.setattr(
        pipeline,
        "send_failure_alert",
        lambda subject, message: sent.append((subject, message)) or "SENT",
    )
    common = {
        "component": "pipeline",
        "category": "ingestion_failed:RuntimeError",
        "subject": "PowerFlow failed",
        "message": "ENTSO-E request failed token=do-not-store",
    }
    assert pipeline._send_incident_failure_alert(**common) == "SENT"
    assert pipeline._send_incident_failure_alert(**common) == "SUPPRESSED"
    assert len(sent) == 1

    with sqlite3.connect(temporary_database) as connection:
        old = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
        connection.execute(
            """
            UPDATE operational_incidents SET timestamp_utc = ?
            WHERE event_type = 'failure_alert_sent'
            """,
            (old,),
        )
    assert pipeline._send_incident_failure_alert(**common) == "SENT"
    distinct = {**common, "category": "model_verification_failed:ValueError"}
    assert pipeline._send_incident_failure_alert(**distinct) == "SENT"
    assert len(sent) == 3

    with sqlite3.connect(temporary_database) as connection:
        rows = connection.execute(
            "SELECT event_type, message, details_json FROM operational_incidents"
        ).fetchall()
    assert sum(row[0] == "failure_alert_suppressed" for row in rows) == 1
    assert "do-not-store" not in str(rows)
    assert all("do-not-store" not in message for _, message in sent)


def test_email_delivery_failure_records_once_without_recursive_alert(
    temporary_database, monkeypatch,
):
    import scheduled_pipeline as pipeline

    attempts = []
    monkeypatch.setattr(
        pipeline,
        "send_failure_alert",
        lambda *args, **kwargs: attempts.append((args, kwargs)) or "FAILED",
    )
    result = pipeline._send_incident_failure_alert(
        component="pipeline",
        category="RuntimeError",
        subject="PowerFlow failed",
        message="Source unavailable",
    )
    assert result == "FAILED"
    assert len(attempts) == 1
    with sqlite3.connect(temporary_database) as connection:
        event_types = [row[0] for row in connection.execute(
            "SELECT event_type FROM operational_incidents"
        )]
    assert event_types == ["email_alert_failed"]


@pytest.mark.parametrize("value", ["0", "169", "nan", "invalid"])
def test_alert_cooldown_configuration_validation(value):
    with pytest.raises(ValueError, match="POWERFLOW_ALERT_COOLDOWN_HOURS"):
        alert_cooldown_hours({"POWERFLOW_ALERT_COOLDOWN_HOURS": value})
    assert alert_cooldown_hours({}) == 12
    assert alert_cooldown_hours({"POWERFLOW_ALERT_COOLDOWN_HOURS": "1"}) == 1
    assert alert_cooldown_hours({"POWERFLOW_ALERT_COOLDOWN_HOURS": "168"}) == 168


def test_failure_fingerprint_is_stable_and_contains_no_secrets():
    first = failure_fingerprint(
        "pipeline", "RuntimeError",
        "Failed at 2026-09-21T10:00:00+00:00 token=first-secret",
    )
    second = failure_fingerprint(
        "pipeline", "RuntimeError",
        "Failed at 2026-09-22T11:00:00+00:00 token=second-secret",
    )
    assert first == second
    assert len(first) == 64
    assert "secret" not in first


def test_protected_generation_conflict_records_safe_warning(monkeypatch):
    import scheduled_pipeline as pipeline

    incidents = []
    monkeypatch.setattr(
        pipeline,
        "_record_incident",
        lambda *args, **kwargs: incidents.append((args, kwargs)) or True,
    )
    state = {"warnings": []}
    metadata = {
        "protected_conflicts": 2,
        "protected_conflicts_by_column": {"Fossil Gas": 1, "Solar": 1},
        "protected_conflict_first_timestamp": "2026-09-18T01:00:00+00:00",
        "protected_conflict_last_timestamp": "2026-09-18T02:00:00+00:00",
    }
    assert _record_protected_generation_conflicts(metadata, state) == 2
    assert state["generation_protected_conflicts"] == 2
    assert "stored value retained" in state["warnings"][0]
    args, _ = incidents[0]
    assert args[:4] == (
        "WARNING", "ENTSO-E generation", "protected_historical_revision", "ACTIVE"
    )
    assert args[5] == {
        "count": 2,
        "affected_columns": ["Fossil Gas", "Solar"],
        "by_column": {"Fossil Gas": 1, "Solar": 1},
        "first_timestamp": "2026-09-18T01:00:00+00:00",
        "last_timestamp": "2026-09-18T02:00:00+00:00",
    }


def test_stage_timing_records_success_failure_and_total(temporary_database, monkeypatch):
    monkeypatch.setattr("scheduled_pipeline.log_stage_timing", store_data.log_stage_timing)
    assert _timed_stage("run-1", "Silver build", lambda: 7) == 7
    with pytest.raises(RuntimeError, match="broken"):
        _timed_stage("run-1", "Gold validation", lambda: (_ for _ in ()).throw(RuntimeError("broken")))
    store_data.log_stage_timing(
        "run-1", "Total pipeline", NOW.isoformat(),
        (NOW + pd.Timedelta(seconds=8)).isoformat(), 8.0, "FAILED",
    )
    st.cache_data.clear()
    rows = load_recent_stage_timings(temporary_database)
    assert rows["stage_name"].tolist() == ["Total pipeline", "Gold validation", "Silver build"]
    assert rows["status"].tolist() == ["FAILED", "FAILED", "SUCCESS"]
    assert rows["duration_seconds"].ge(0).all()
    assert rows.iloc[0]["duration_seconds"] == 8.0
    summary = summarize_pipeline_timings(rows)
    assert summary["latest_total_seconds"] == 8.0
    assert summary["slowest_stage"] in {"Gold validation", "Silver build"}
    assert summary["recent_average_seconds"] is None


def realized_row(target, signed_error, horizon=1, issued_late=False):
    target = pd.Timestamp(target)
    issue = target - pd.Timedelta(hours=horizon)
    issued = target + pd.Timedelta(minutes=1) if issued_late else issue + pd.Timedelta(minutes=1)
    return {
        "forecast_issue_time": issue, "target_timestamp": target,
        "issued_at_utc": issued, "horizon_hours": horizon,
        "signed_error": float(signed_error),
        "absolute_error": abs(float(signed_error)),
        "squared_error": float(signed_error) ** 2,
    }


def test_realized_metrics_windows_horizons_and_issuance_guard():
    realized = pd.DataFrame([
        realized_row(NOW - pd.Timedelta(hours=3), 2.0),
        realized_row(NOW - pd.Timedelta(days=3), -4.0, horizon=2),
        realized_row(NOW - pd.Timedelta(days=20), 6.0, horizon=3),
        realized_row(NOW - pd.Timedelta(hours=2), 1000.0, issued_late=True),
    ])
    metrics = summarize_realized_performance(
        realized, now=NOW, min_pairs=1, min_horizon_pairs=1,
    )
    assert metrics["overall"]["pair_count"] == 3
    assert metrics["overall"]["mae"] == pytest.approx(4)
    assert metrics["overall"]["rmse"] == pytest.approx((56 / 3) ** 0.5)
    assert metrics["overall"]["bias"] == pytest.approx(4 / 3)
    assert [metrics["windows"][key]["pair_count"] for key in ("24h", "7d", "30d")] == [1, 2, 3]
    horizons = metrics["horizons"]
    assert len(horizons) == 24
    assert horizons.loc[horizons["horizon_hours"] == 2, "mae"].iloc[0] == 4
    insufficient = summarize_realized_performance(realized, now=NOW)
    assert insufficient["overall"]["status"] == "Insufficient data"
    assert insufficient["horizons"]["mae"].isna().all()


def test_model_review_rule_is_conservative():
    summary = {"overall": {"pair_count": 110}, "target_dates": 7,
               "windows": {"7d": {"status": "Available", "rmse": 100.0}}}
    manifest = {"test_metrics": {"rmse": 44.0},
                "persistence_test_metrics": {"rmse": 88.0}}
    assert model_performance_state(summary, manifest)["label"] == "Review recommended"
    summary["target_dates"] = 2
    assert model_performance_state(summary, manifest)["label"] == "Insufficient data"
    summary["target_dates"] = 7
    summary["windows"]["7d"]["rmse"] = 70.0
    assert model_performance_state(summary, manifest)["label"] == "Monitoring"


def _forecast_frame(issue=NOW.floor("h")):
    values = [-10.0, *([100.0] * 21), 200.0, 250.0]
    return pd.DataFrame({
        "forecast_issue_time": [issue] * 24,
        "target_timestamp": [issue + pd.Timedelta(hours=h) for h in range(1, 25)],
        "horizon_hours": range(1, 25),
        "predicted_price_eur_mwh": values,
        "model_release": ["approved-v1"] * 24,
    })


def test_forecast_analyst_summary_and_forward_looking_counts():
    issue = NOW.floor("h")
    frame = _forecast_frame(issue)
    result = summarize_next24h_forecast(frame, now=issue + pd.Timedelta(hours=2))
    assert result["rows"] == 24
    assert result["forward_looking_rows"] == 22
    assert result["minimum"] == -10
    assert result["maximum"] == 250
    assert result["negative_hours"] == 1
    assert result["elevated_hours"] == 2
    assert result["first_to_last_change"] == 260


def test_forecast_forward_looking_count_boundaries_and_missing_report():
    issue = NOW.floor("h")
    frame = _forecast_frame(issue)
    assert summarize_next24h_forecast(frame, now=issue)["forward_looking_rows"] == 24
    assert summarize_next24h_forecast(
        frame, now=issue + pd.Timedelta(hours=24)
    )["forward_looking_rows"] == 0
    assert summarize_next24h_forecast(pd.DataFrame(), now=issue) is None


def test_prediction_count_labels_distinguish_one_hour_and_next24h():
    metrics = prediction_count_metrics(7, _forecast_frame())
    assert metrics == (
        ("New One-Hour Predictions", 7),
        ("Next24h Forecast Rows", 24),
    )
    assert prediction_count_metrics(0, pd.DataFrame())[1] == (
        "Next24h Forecast Rows", 0
    )


def test_withheld_forecast_records_once_and_alerts_without_changing_prior_report(
    tmp_path, monkeypatch,
):
    import scheduled_pipeline as pipeline

    calls = []

    class LocalSync:
        config = type("Config", (), {"backend": "local"})()

        def sync_group(self, group):
            calls.append(("sync", group))
            return type("Result", (), {"uploaded": [], "unchanged": []})()

    latest = tmp_path / "next24h_forecast.csv"
    latest.write_text("prior issued forecast\n", encoding="utf-8")
    monkeypatch.setattr(pipeline, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "verify_next24h_release_task", lambda: "approved-v1")
    monkeypatch.setattr(
        pipeline, "next24h_forecast_task",
        lambda: (_ for _ in ()).throw(pipeline.ForecastUnavailableError("required load history unavailable")),
    )
    monkeypatch.setattr(pipeline, "next24h_monitoring_task", lambda: (0, 0))
    monkeypatch.setattr(pipeline, "initialize_database", lambda: None)
    monkeypatch.setattr(pipeline, "log_data_quality_result", lambda *args: calls.append(("quality", args)))
    monkeypatch.setattr(pipeline, "_record_incident", lambda *args, **kwargs: calls.append(("incident", args)) or True)
    monkeypatch.setattr(pipeline, "send_failure_alert", lambda *args, **kwargs: calls.append(("alert", args)) or "SENT")
    state = {"warnings": [], "objects_uploaded": [], "objects_unchanged": [],
             "s3_sync_status": "NOT_REQUIRED"}
    pipeline._run_next24h_stages(LocalSync(), state)
    assert state["next24h_forecast_status"] == "UNAVAILABLE"
    assert any(item[0] == "incident" and item[1][3] == "ACTIVE" for item in calls)
    assert any(item[0] == "alert" for item in calls)
    assert latest.read_text(encoding="utf-8") == "prior issued forecast\n"
