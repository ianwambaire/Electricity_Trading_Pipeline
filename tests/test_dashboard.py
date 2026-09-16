from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_handles_missing_generated_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    st.cache_data.clear()

    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)

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
