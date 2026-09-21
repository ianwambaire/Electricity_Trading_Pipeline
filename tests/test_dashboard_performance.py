import os
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

import dashboard_data
from dashboard_data import (
    downsample_time_series,
    load_csv_summary,
    load_dashboard_csv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_downsample_time_series_is_deterministic_and_keeps_endpoints():
    source = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=10_000, freq="h", tz="UTC"),
            "value": range(10_000),
        }
    )

    first = downsample_time_series(source, max_points=4_000)
    second = downsample_time_series(source, max_points=4_000)

    assert len(first) <= 4_000
    assert first.index.tolist() == second.index.tolist()
    assert first.iloc[0].equals(source.iloc[0])
    assert first.iloc[-1].equals(source.iloc[-1])
    assert first["timestamp"].is_monotonic_increasing


def test_dashboard_csv_cache_tracks_file_modification_time(tmp_path):
    csv_path = tmp_path / "series.csv"
    pd.DataFrame(
        {
            "timestamp": ["2024-01-01 01:00:00+00:00", "2024-01-01 00:00:00+00:00"],
            "value": [2, 1],
        }
    ).to_csv(csv_path, index=False)
    st.cache_data.clear()

    first = load_dashboard_csv(
        csv_path,
        timestamp_columns=("timestamp",),
        sort_by="timestamp",
    )
    original_mtime = csv_path.stat().st_mtime_ns

    pd.DataFrame(
        {
            "timestamp": [
                "2024-01-01 02:00:00+00:00",
                "2024-01-01 01:00:00+00:00",
                "2024-01-01 00:00:00+00:00",
            ],
            "value": [3, 2, 1],
        }
    ).to_csv(csv_path, index=False)
    updated_mtime = original_mtime + 1_000_000
    os.utime(csv_path, ns=(updated_mtime, updated_mtime))

    second = load_dashboard_csv(
        csv_path,
        timestamp_columns=("timestamp",),
        sort_by="timestamp",
    )

    assert len(first) == 2
    assert len(second) == 3
    assert isinstance(second["timestamp"].dtype, pd.DatetimeTZDtype)
    assert second["timestamp"].is_monotonic_increasing
    assert second.iloc[-1]["value"] == 3


def test_dashboard_csv_cache_reuses_unchanged_file(tmp_path, monkeypatch):
    csv_path = tmp_path / "cached.csv"
    pd.DataFrame({"value": [1, 2, 3]}).to_csv(csv_path, index=False)
    st.cache_data.clear()
    read_csv = dashboard_data.pd.read_csv
    read_count = 0

    def count_reads(*args, **kwargs):
        nonlocal read_count
        read_count += 1
        return read_csv(*args, **kwargs)

    monkeypatch.setattr(dashboard_data.pd, "read_csv", count_reads)

    first = load_dashboard_csv(csv_path)
    second = load_dashboard_csv(csv_path)

    assert first.equals(second)
    assert read_count == 1


def test_csv_summary_reads_coverage_without_loading_other_columns(tmp_path):
    csv_path = tmp_path / "summary.csv"
    pd.DataFrame(
        {
            "timestamp": [
                "2024-01-03 00:00:00+00:00",
                "2024-01-01 00:00:00+00:00",
                "2024-01-02 00:00:00+00:00",
            ],
            "feature_a": [1, 2, 3],
            "feature_b": [4, 5, 6],
        }
    ).to_csv(csv_path, index=False)
    st.cache_data.clear()

    summary = load_csv_summary(csv_path)

    assert summary["available"] is True
    assert summary["row_count"] == 3
    assert summary["columns"] == ("timestamp", "feature_a", "feature_b")
    assert summary["earliest_timestamp"] == pd.Timestamp("2024-01-01", tz="UTC")
    assert summary["latest_timestamp"] == pd.Timestamp("2024-01-03", tz="UTC")


def test_page_switches_only_request_their_full_csvs(tmp_path, monkeypatch):
    loaded_files = []

    def record_full_load(path_string, *_args):
        loaded_files.append(Path(path_string).name)
        return pd.DataFrame()

    monkeypatch.setattr(dashboard_data, "_load_csv_versioned", record_full_load)
    monkeypatch.chdir(tmp_path)
    st.cache_data.clear()

    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)

    loaded_files.clear()
    app.radio[0].set_value("Forecasting").run(timeout=30)
    assert loaded_files == [
        "next24h_forecast.csv",
        "next24h_realized_errors.csv",
        "next24h_forecast_history.csv",
        "actual_vs_predicted.csv",
    ]

    loaded_files.clear()
    app.radio[0].set_value("Model Insights").run(timeout=30)
    assert loaded_files == ["feature_importance.csv"]

    loaded_files.clear()
    app.radio[0].set_value("Pipeline Summary").run(timeout=30)
    # Health status validates the small, 24-row production forecast; it does
    # not load the historical market, model, or realized-error datasets.
    assert loaded_files == ["next24h_forecast.csv"]
