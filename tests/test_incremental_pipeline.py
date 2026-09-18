from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ingestion.fetch_weather_data import fetch_open_meteo_weather
from ingestion.fetch_entsoe_data import _incremental_dataset
from ingestion.incremental_utils import (
    append_csv_safely,
    infer_stored_interval,
    merge_incremental_rows,
    normalize_utc_timestamps,
)
from models.final_evaluation import FINAL_FEATURES
from models import prediction_visualization
from processing.build_gold_dataset import build_gold_dataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def observations(timestamps, values=None):
    values = values if values is not None else range(len(timestamps))
    return pd.DataFrame({"timestamp": timestamps, "value": list(values)})


def test_no_new_data_leaves_stored_csv_unchanged(tmp_path):
    path = tmp_path / "raw.csv"
    existing = observations(["2025-01-01T00:00:00Z"], [10.0])
    existing.to_csv(path, index=False)
    before = path.read_bytes()

    result = append_csv_safely(path, existing)

    assert result.new_rows == 0
    assert result.changed is False
    assert path.read_bytes() == before


@pytest.mark.parametrize("new_hours", [1, 3])
def test_one_or_multiple_new_hours_append_once_and_chronologically(
    tmp_path, new_hours
):
    path = tmp_path / "raw.csv"
    observations(["2025-01-01T00:00:00Z"], [0.0]).to_csv(path, index=False)
    timestamps = pd.date_range(
        "2025-01-01T01:00:00Z", periods=new_hours, freq="h"
    )

    result = append_csv_safely(path, observations(timestamps, range(1, new_hours + 1)))
    stored = pd.read_csv(path)
    parsed = pd.to_datetime(stored["timestamp"], utc=True)

    assert result.new_rows == new_hours
    assert parsed.is_monotonic_increasing
    assert parsed.is_unique
    assert len(stored) == new_hours + 1


def test_duplicate_overlap_is_deduplicated_but_conflict_fails():
    existing = observations(
        ["2025-01-01T00:00:00Z", "2025-01-01T01:00:00Z"], [1.0, 2.0]
    )
    identical_overlap = observations(
        ["2025-01-01T01:00:00Z", "2025-01-01T02:00:00Z"], [2.0, 3.0]
    )

    merged, new_rows = merge_incremental_rows(existing, identical_overlap)

    assert new_rows == 1
    assert len(merged) == 3
    assert merged["timestamp"].is_unique

    conflict = observations(["2025-01-01T01:00:00Z"], [999.0])
    with pytest.raises(ValueError, match="inconsistent"):
        merge_incremental_rows(existing, conflict)


def test_incremental_timestamps_preserve_dst_instants_in_utc():
    data = observations(
        [
            "2024-10-27T02:00:00+02:00",
            "2024-10-27T02:00:00+01:00",
        ],
        [1.0, 2.0],
    )

    normalized = normalize_utc_timestamps(data)

    assert normalized["timestamp"].tolist() == [
        pd.Timestamp("2024-10-27T00:00:00Z"),
        pd.Timestamp("2024-10-27T01:00:00Z"),
    ]


def test_recent_subhourly_transition_controls_next_request_timestamp(tmp_path):
    path = tmp_path / "prices.csv"
    timestamps = [
        "2025-09-30T21:00:00Z",
        "2025-09-30T22:00:00Z",
        "2025-09-30T22:15:00Z",
        "2025-09-30T22:30:00Z",
        "2025-09-30T22:45:00Z",
    ]
    observations(timestamps).to_csv(path, index=False)

    assert infer_stored_interval(path, "1h") == pd.Timedelta(minutes=15)


def test_entsoe_incremental_request_starts_immediately_after_latest_row(tmp_path):
    path = tmp_path / "prices.csv"
    observations(["2025-01-01T00:00:00Z"], [10.0]).rename(
        columns={"value": "price_eur_mwh"}
    ).to_csv(path, index=False)
    requested = {}

    def query(country_code, start, end):
        requested["start"] = start
        requested["end"] = end
        return pd.Series(
            [11.0, 12.0],
            index=pd.date_range(start, periods=2, freq="h"),
        )

    result = _incremental_dataset(
        None,
        query,
        dataset_name="day-ahead prices",
        output_path=path,
        default_interval="1h",
        end_utc_exclusive=pd.Timestamp("2025-01-01T03:00:00Z"),
        value_name="price_eur_mwh",
    )

    assert requested["start"] == pd.Timestamp("2025-01-01T01:00:00Z")
    assert requested["end"] == pd.Timestamp("2025-01-01T03:00:00Z")
    assert result["new_rows"] == 2


def _silver_frame(periods=201):
    timestamps = pd.date_range("2024-01-01T00:00:00Z", periods=periods, freq="h")
    sequence = np.arange(periods, dtype="float64")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "price_eur_mwh": 40.0 + sequence,
            "load_mw": 50000.0 + sequence,
            "biomass_mw": 1000.0,
            "lignite_mw": 5000.0,
            "gas_mw": 6000.0,
            "hard_coal_mw": 4000.0,
            "hydro_mw": 2000.0,
            "nuclear_mw": 0.0,
            "solar_mw": 1000.0,
            "wind_offshore_mw": 2000.0,
            "wind_onshore_mw": 3000.0,
            "wind_total_mw": 5000.0,
            "temperature_2m": 10.0,
            "relative_humidity_2m": 70.0,
            "wind_speed_10m": 5.0,
            "cloud_cover": 50.0,
            "shortwave_radiation": 100.0,
        }
    )


def test_full_gold_rebuild_preserves_features_across_old_new_boundary(tmp_path):
    silver_path = tmp_path / "silver.csv"
    old_gold_path = tmp_path / "old_gold.csv"
    new_gold_path = tmp_path / "new_gold.csv"
    silver = _silver_frame()

    silver.iloc[:-1].to_csv(silver_path, index=False)
    old_gold = build_gold_dataset(silver_path, old_gold_path)
    silver.to_csv(silver_path, index=False)
    new_gold = build_gold_dataset(silver_path, new_gold_path)

    assert len(new_gold) == len(old_gold) + 1
    boundary = new_gold.iloc[-1]
    assert boundary["timestamp"] == silver.iloc[-2]["timestamp"]
    assert boundary["target_price_next_hour"] == silver.iloc[-1]["price_eur_mwh"]
    assert boundary["price_lag_168h"] == silver.iloc[-170]["price_eur_mwh"]


def test_weather_no_new_interval_does_not_call_api(tmp_path):
    path = tmp_path / "weather.csv"
    row = {"timestamp": "2025-01-10T23:00:00Z"}
    row.update({feature: 1.0 for feature in [
        "temperature_2m",
        "relative_humidity_2m",
        "wind_speed_10m",
        "cloud_cover",
        "shortwave_radiation",
    ]})
    pd.DataFrame([row]).to_csv(path, index=False)

    class NoNetworkSession:
        def get(self, *args, **kwargs):
            raise AssertionError("No API request should be made.")

    result = fetch_open_meteo_weather(
        mode="incremental",
        now=pd.Timestamp("2025-01-15T12:00:00Z"),
        output_path=path,
        session=NoNetworkSession(),
    )

    assert result["new_rows"] == 0


def test_incremental_prediction_only_appends_newly_eligible_gold_row(
    tmp_path, monkeypatch
):
    data_path = tmp_path / "gold.csv"
    output_path = tmp_path / "actual_vs_predicted.csv"
    plot_path = tmp_path / "actual_vs_predicted.png"
    features = {
        feature: [float(position), float(position + 1)]
        for position, feature in enumerate(FINAL_FEATURES)
    }
    gold = pd.DataFrame(features)
    gold.insert(
        0,
        "timestamp",
        ["2025-09-30T22:00:00Z", "2025-09-30T23:00:00Z"],
    )
    gold["target_price_next_hour"] = [50.0, 60.0]
    gold.to_csv(data_path, index=False)
    pd.DataFrame(
        {
            "timestamp": ["2025-09-30T23:00:00Z"],
            "actual_price": [50.0],
            "predicted_price": [49.0],
        }
    ).to_csv(output_path, index=False)

    class FrozenModel:
        def predict(self, frame):
            assert frame.columns.tolist() == list(FINAL_FEATURES)
            return np.array([59.0])

    monkeypatch.setattr(
        prediction_visualization,
        "load_final_model_release",
        lambda: (FrozenModel(), list(FINAL_FEATURES)),
    )
    monkeypatch.setattr(
        prediction_visualization,
        "load_release_holdout_period",
        lambda: (
            pd.Timestamp("2025-01-01T00:00:00Z"),
            pd.Timestamp("2025-09-30T23:00:00Z"),
        ),
    )

    generated = prediction_visualization.run_prediction_report(
        "incremental",
        data_path=data_path,
        csv_output_path=output_path,
        plot_output_path=plot_path,
    )
    stored = pd.read_csv(output_path)

    assert generated == 1
    assert len(stored) == 2
    assert pd.Timestamp(stored.iloc[-1]["timestamp"]) == pd.Timestamp(
        "2025-10-01T00:00:00Z"
    )
    assert plot_path.exists()


def test_production_pipeline_keeps_frozen_model_and_excludes_final_evaluator():
    scheduled_source = (PROJECT_ROOT / "src/scheduled_pipeline.py").read_text(
        encoding="utf-8"
    )
    prediction_source = (
        PROJECT_ROOT / "src/models/prediction_visualization.py"
    ).read_text(encoding="utf-8")

    assert "run_final_holdout_evaluation" not in scheduled_source
    assert "train_gold_model.py" not in scheduled_source
    assert "load_final_model_release" in scheduled_source
    assert "load_final_model_release" in prediction_source
    assert len(FINAL_FEATURES) == 31
