import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "page",
    [
        "Executive Overview",
        "Market Intelligence",
        "Forecasting",
        "Anomaly Detection",
        "Model Insights",
        "Pipeline Summary",
    ],
)
def test_dashboard_pages_handle_missing_generated_files(tmp_path, monkeypatch, page):
    monkeypatch.chdir(tmp_path)
    st.cache_data.clear()

    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)
    app.radio[0].set_value(page).run(timeout=30)

    assert not app.exception
    assert app.warning


def test_dashboard_loads_silver_data_from_expected_path(tmp_path, monkeypatch):
    silver_path = tmp_path / "data" / "processed"
    silver_path.mkdir(parents=True)
    pd.DataFrame(
        {
            "timestamp": [
                "2024-01-01 00:00:00+00:00",
                "2024-01-01 01:00:00+00:00",
            ],
            "price_eur_mwh": [10.0, 20.0],
            "load_mw": [100.0, 110.0],
            "wind_total_mw": [30.0, 35.0],
            "solar_mw": [0.0, 1.0],
        }
    ).to_csv(silver_path / "silver_electricity_market_data.csv", index=False)

    monkeypatch.chdir(tmp_path)
    st.cache_data.clear()

    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)
    metrics = {metric.label: metric.value for metric in app.metric}

    assert not app.exception
    assert metrics["Hourly Records"] == "2"
    assert metrics["Latest Price"] == "20.00 EUR/MWh"
    assert metrics["Avg Load"] == "105.00 MW"


def test_pipeline_summary_formats_json_operational_metadata(tmp_path, monkeypatch):
    database_path = tmp_path / "database" / "electricity_trading.db"
    database_path.parent.mkdir(parents=True)
    metadata = {
        "mode": "incremental",
        "storage_backend": "s3",
        "s3_sync_status": "SUCCESS",
        "new_rows_ingested": 3,
        "predictions_generated": 0,
        "latest_complete_price_hour": "2026-09-12T21:00:00+00:00",
        "message": (
            "No complete aligned raw hour advanced; derived datasets were left "
            "unchanged."
        ),
        "unresolved_source_gaps": {
            "day-ahead prices": {
                "last_contiguous_timestamp": "2026-09-12T21:45:00+00:00",
                "first_unresolved_timestamp": "2026-09-12T22:15:00+00:00",
                "missing_count": 72,
                "missing_timestamps": ["2026-09-12T22:15:00+00:00"],
            }
        },
    }
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE pipeline_runs (
                id INTEGER PRIMARY KEY,
                run_time TEXT,
                status TEXT,
                records_processed INTEGER,
                message TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO pipeline_runs
                (run_time, status, records_processed, message)
            VALUES (?, ?, ?, ?)
            """,
            (
                "2026-09-19 12:32:52",
                "SUCCESS",
                3,
                json.dumps(metadata),
            ),
        )

    monkeypatch.chdir(tmp_path)
    st.cache_data.clear()
    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)
    app.radio[0].set_value("Pipeline Summary").run(timeout=30)

    metrics = {metric.label: metric.value for metric in app.metric}
    assert not app.exception
    assert metrics["Latest Run Time"] == "2026-09-19 12:32"
    assert metrics["New Rows Ingested"] == "3"
    assert metrics["Latest Complete Price Hour (UTC)"] == "2026-09-12 21:00"
    assert any("No complete aligned raw hour advanced" in item.value for item in app.info)
    assert any("1 source continuity warning detected" in item.value for item in app.warning)
    rendered_tables = "\n".join(frame.value.to_string() for frame in app.dataframe)
    assert "day-ahead prices" in rendered_tables
    assert "missing_timestamps" not in rendered_tables
