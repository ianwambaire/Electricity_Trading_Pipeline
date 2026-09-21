import sqlite3

import store_data


def test_schema_initialization_creates_only_operational_tables(temporary_database):
    with sqlite3.connect(temporary_database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
                """
            )
        }

    assert tables == {
        "pipeline_runs", "data_quality_results", "operational_incidents",
        "pipeline_stage_timings",
    }
    assert indexes == {
        "idx_pipeline_runs_run_time",
        "idx_data_quality_results_check_time",
        "idx_operational_incidents_time",
        "idx_operational_incidents_event",
        "idx_pipeline_stage_timings_run",
        "idx_pipeline_stage_timings_time",
    }


def test_pipeline_run_logging_uses_temporary_database(temporary_database):
    store_data.log_pipeline_run("SUCCESS", 42, "Test pipeline completed.")

    with sqlite3.connect(temporary_database) as connection:
        row = connection.execute(
            """
            SELECT status, records_processed, message
            FROM pipeline_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    assert row == ("SUCCESS", 42, "Test pipeline completed.")


def test_data_quality_logging_uses_temporary_database(temporary_database):
    store_data.log_data_quality_result(
        "Test Check", "PASSED", "Test validation passed."
    )

    with sqlite3.connect(temporary_database) as connection:
        row = connection.execute(
            """
            SELECT check_name, status, message
            FROM data_quality_results
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    assert row == ("Test Check", "PASSED", "Test validation passed.")
