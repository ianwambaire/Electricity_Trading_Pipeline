import json
import sqlite3

import streamlit as st

from dashboard_health import (
    alert_configuration_status,
    concise_history_message,
    count_quality_statuses,
    derive_system_health,
    load_latest_successful_run_time,
    load_recent_data_quality_history,
    load_recent_pipeline_history,
    prepare_pipeline_history,
)


def create_operational_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_time TEXT NOT NULL,
                status TEXT NOT NULL,
                records_processed INTEGER,
                message TEXT
            );
            CREATE TABLE data_quality_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_time TEXT NOT NULL,
                check_name TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT
            );
            """
        )


def test_pipeline_health_summary_rules_are_condition_based():
    assert derive_system_health("SUCCESS", 0, 0, 0)["label"] == "Operational"
    assert (
        derive_system_health("SUCCESS", 0, 1, 0)["label"]
        == "Operational with warnings"
    )
    assert (
        derive_system_health("SUCCESS", 0, 0, 2)["label"]
        == "Operational with warnings"
    )
    assert (
        derive_system_health("FAILED", 0, 0, 0)["label"]
        == "Attention required"
    )
    assert (
        derive_system_health("SUCCESS", 1, 0, 0)["label"]
        == "Attention required"
    )
    assert derive_system_health(None, 0, 0, 0)["label"] == "Status unavailable"


def test_recent_pipeline_history_is_read_in_reverse_run_order(tmp_path):
    database_path = tmp_path / "operations.db"
    create_operational_database(database_path)
    metadata = json.dumps(
        {
            "new_rows_ingested": 7,
            "message": "Incremental pipeline completed.",
        }
    )
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO pipeline_runs
                (run_time, status, records_processed, message)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("2026-01-01 01:00:00", "SUCCESS", 10, "Earlier run."),
                ("2026-01-01 02:00:00", "FAILED", 4, "Failed run."),
                ("2026-01-01 03:00:00", "SUCCESS", 20, metadata),
            ],
        )
    st.cache_data.clear()

    history = load_recent_pipeline_history(database_path, limit=2)
    displayed = prepare_pipeline_history(history)

    assert history["status"].tolist() == ["SUCCESS", "FAILED"]
    assert displayed.iloc[0].to_dict() == {
        "Run Time": "2026-01-01 03:00:00",
        "Status": "SUCCESS",
        "Rows": 7,
        "Message": "Incremental pipeline completed.",
    }
    assert load_latest_successful_run_time(database_path) == "2026-01-01 03:00:00"


def test_recent_data_quality_history_and_counts(tmp_path):
    database_path = tmp_path / "operations.db"
    create_operational_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO data_quality_results
                (check_time, check_name, status, message)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("2026-01-01 01:00:00", "row-count", "PASSED", "Rows found."),
                ("2026-01-01 02:00:00", "continuity", "WARNING", "Gap found."),
                ("2026-01-01 03:00:00", "nulls", "FAILED", "Null found."),
            ],
        )
    st.cache_data.clear()

    history = load_recent_data_quality_history(database_path, limit=20)

    assert history["check_name"].tolist() == ["nulls", "continuity", "row-count"]
    assert count_quality_statuses(history) == {
        "passed": 1,
        "failed": 1,
        "warnings": 1,
    }


def test_missing_database_and_missing_tables_return_safe_empty_results(tmp_path):
    missing_path = tmp_path / "missing.db"
    st.cache_data.clear()

    assert load_recent_pipeline_history(missing_path).empty
    assert load_recent_data_quality_history(missing_path).empty
    assert load_latest_successful_run_time(missing_path) is None
    assert not missing_path.exists()

    empty_path = tmp_path / "empty.db"
    with sqlite3.connect(empty_path):
        pass
    st.cache_data.clear()

    assert load_recent_pipeline_history(empty_path).empty
    assert load_recent_data_quality_history(empty_path).empty
    assert load_latest_successful_run_time(empty_path) is None


def test_alert_status_detection_never_returns_secret_values():
    environment = {
        "ALERT_EMAIL_SENDER": "sender@example.com",
        "ALERT_EMAIL_PASSWORD": "top-secret-password",
        "ALERT_EMAIL_RECEIVER": "receiver@example.com",
    }

    status = alert_configuration_status(environment)

    assert status == "Configured"
    assert all(value not in status for value in environment.values())
    assert alert_configuration_status({}) is None


def test_continuity_message_omits_missing_timestamp_array():
    message = json.dumps(
        {
            "first_unresolved_timestamp": "2026-01-01T03:00:00+00:00",
            "missing_count": 72,
            "missing_timestamps": [
                "2026-01-01T03:00:00+00:00",
                "2026-01-01T04:00:00+00:00",
            ],
        }
    )

    summary = concise_history_message(message)

    assert summary == (
        "72 missing timestamps; first unresolved 2026-01-01T03:00:00+00:00"
    )
    assert "2026-01-01T04:00:00+00:00" not in summary
