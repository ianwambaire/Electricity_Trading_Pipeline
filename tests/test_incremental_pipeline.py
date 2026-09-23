from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ingestion.fetch_weather_data import fetch_open_meteo_weather
from ingestion.fetch_entsoe_data import (
    _incremental_dataset,
    combine_time_chunks,
    fetch_entsoe_data,
    parse_price_observations,
)
from ingestion.incremental_utils import (
    append_csv_safely,
    contiguous_prefix,
    contiguous_price_prefix,
    infer_stored_interval,
    merge_incremental_rows,
    normalize_utc_timestamps,
)
from models.final_evaluation import FINAL_FEATURES
from models import prediction_visualization
from processing.build_gold_dataset import build_gold_dataset
from processing.build_silver_dataset import (
    aggregate_hourly_prices,
    aggregate_quarter_hourly,
    build_silver_dataset,
    clean_load,
    set_utc_timestamp_index,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def observations(timestamps, values=None):
    values = values if values is not None else range(len(timestamps))
    return pd.DataFrame({"timestamp": timestamps, "value": list(values)})


def price_xml(periods):
    """Minimal ENTSO-E period shape with explicit resolution and positions."""
    elements = []
    for start, end, resolution, positions in periods:
        points = "".join(
            f"<Point><position>{position}</position>"
            f"<price.amount>{position}</price.amount></Point>"
            for position in positions
        )
        elements.append(
            "<TimeSeries><Period><timeInterval>"
            f"<start>{start}</start><end>{end}</end>"
            "</timeInterval>"
            f"<resolution>{resolution}</resolution>{points}"
            "</Period></TimeSeries>"
        )
    return (
        '<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:0">'
        + "".join(elements)
        + "</Publication_MarketDocument>"
    )


def test_price_parser_retains_pt15m_and_pt60m_periods():
    parsed = parse_price_observations(
        price_xml(
            [
                ("2026-09-12T21:00Z", "2026-09-12T22:00Z", "PT15M", range(1, 5)),
                ("2026-09-12T22:00Z", "2026-09-13T00:00Z", "PT60M", range(1, 3)),
            ]
        )
    )

    assert parsed.index.tolist() == list(
        pd.to_datetime(
            [
                "2026-09-12T21:00Z",
                "2026-09-12T21:15Z",
                "2026-09-12T21:30Z",
                "2026-09-12T21:45Z",
                "2026-09-12T22:00Z",
                "2026-09-12T23:00Z",
            ],
            utc=True,
        )
    )
    assert parsed["source_resolution"].tolist() == ["PT15M"] * 4 + ["PT60M"] * 2
    assert parsed.index.is_unique


def test_price_parser_rejects_duplicate_source_timestamps():
    xml = price_xml(
        [
            ("2026-09-12T22:00Z", "2026-09-12T23:00Z", "PT60M", [1]),
            ("2026-09-12T22:00Z", "2026-09-12T23:00Z", "PT60M", [1]),
        ]
    )
    with pytest.raises(ValueError, match="duplicate timestamps"):
        parse_price_observations(xml)


def test_price_parser_uses_explicit_utc_across_autumn_dst():
    parsed = parse_price_observations(
        price_xml(
            [
                ("2024-10-27T00:00Z", "2024-10-27T02:00Z", "PT60M", [1, 2])
            ]
        )
    )
    assert parsed.index.tolist() == [
        pd.Timestamp("2024-10-27T00:00:00Z"),
        pd.Timestamp("2024-10-27T01:00:00Z"),
    ]


def test_price_continuity_accepts_complete_mixed_resolution_hours():
    values = parse_price_observations(
        price_xml(
            [
                ("2026-09-12T21:00Z", "2026-09-12T22:00Z", "PT15M", range(1, 5)),
                ("2026-09-12T22:00Z", "2026-09-13T00:00Z", "PT60M", range(1, 3)),
            ]
        )
    )
    result = contiguous_price_prefix(
        values,
        pd.Timestamp("2026-09-12T21:00Z"),
        quarter_hourly_transition=pd.Timestamp("2025-09-30T22:00Z"),
    )
    hourly = aggregate_hourly_prices(values)

    assert result.first_unresolved_timestamp is None
    assert len(result.data) == 6
    assert hourly.index.tolist() == list(
        pd.date_range("2026-09-12T21:00Z", periods=3, freq="h")
    )
    assert hourly["price_eur_mwh"].tolist() == [2.5, 1.0, 2.0]


def test_price_continuity_does_not_complete_partial_pt15m_hour_with_pt60m():
    values = parse_price_observations(
        price_xml(
            [
                ("2026-09-12T21:00Z", "2026-09-12T22:00Z", "PT15M", range(1, 5)),
                ("2026-09-12T22:00Z", "2026-09-12T23:00Z", "PT15M", [1]),
                ("2026-09-12T23:00Z", "2026-09-13T00:00Z", "PT60M", [1]),
            ]
        )
    )
    result = contiguous_price_prefix(
        values,
        pd.Timestamp("2026-09-12T21:00Z"),
        quarter_hourly_transition=pd.Timestamp("2025-09-30T22:00Z"),
    )
    hourly = aggregate_hourly_prices(values)

    assert result.data.index[-1] == pd.Timestamp("2026-09-12T21:45Z")
    assert result.first_unresolved_timestamp == pd.Timestamp("2026-09-12T22:15Z")
    assert set(result.missing_timestamps) == {
        pd.Timestamp("2026-09-12T22:15Z"),
        pd.Timestamp("2026-09-12T22:30Z"),
        pd.Timestamp("2026-09-12T22:45Z"),
    }
    assert hourly.index.tolist() == [pd.Timestamp("2026-09-12T21:00Z"), pd.Timestamp("2026-09-12T23:00Z")]


def test_price_continuity_stops_at_missing_pt60m_hour():
    values = parse_price_observations(
        price_xml(
            [
                ("2026-09-12T22:00Z", "2026-09-13T01:00Z", "PT60M", [1, 3]),
            ]
        )
    )
    result = contiguous_price_prefix(
        values,
        pd.Timestamp("2026-09-12T22:00Z"),
        quarter_hourly_transition=pd.Timestamp("2025-09-30T22:00Z"),
    )

    assert result.data.index.tolist() == [pd.Timestamp("2026-09-12T22:00Z")]
    assert result.first_unresolved_timestamp == pd.Timestamp("2026-09-12T23:00Z")
    assert result.missing_timestamps == (pd.Timestamp("2026-09-12T23:00Z"),)


def test_incremental_price_transition_appends_without_duplicates(tmp_path):
    path = tmp_path / "prices.csv"
    old_index = pd.date_range("2026-09-12T21:00Z", periods=4, freq="15min")
    pd.DataFrame({"timestamp": old_index, "price_eur_mwh": [1, 2, 3, 4]}).to_csv(
        path, index=False
    )
    requests = []

    def query(_country_code, start, end):
        requests.append((start, end))
        return parse_price_observations(
            price_xml(
                [
                    ("2026-09-12T22:00Z", "2026-09-13T00:00Z", "PT60M", [1, 2])
                ]
            )
        )

    first = _incremental_dataset(
        None,
        query,
        dataset_name="day-ahead prices",
        output_path=path,
        default_interval="1h",
        end_utc_exclusive=pd.Timestamp("2026-09-13T00:00Z"),
        value_name="price_eur_mwh",
    )
    after_first = path.read_bytes()
    second = _incremental_dataset(
        None,
        query,
        dataset_name="day-ahead prices",
        output_path=path,
        default_interval="1h",
        end_utc_exclusive=pd.Timestamp("2026-09-13T00:00Z"),
        value_name="price_eur_mwh",
    )
    stored = pd.read_csv(path)

    assert requests == [
        (pd.Timestamp("2026-09-12T22:00Z"), pd.Timestamp("2026-09-13T00:00Z"))
    ]
    assert first["new_rows"] == 2
    assert first["unresolved_gap"] is None
    assert first["latest_complete_hour"] == "2026-09-12T23:00:00+00:00"
    assert second["new_rows"] == 0
    assert path.read_bytes() == after_first
    assert stored["timestamp"].is_unique
    assert stored["source_resolution"].tail(2).tolist() == ["PT60M", "PT60M"]
    stored_hourly = aggregate_hourly_prices(
        stored.assign(timestamp=pd.to_datetime(stored["timestamp"], utc=True))
        .set_index("timestamp")
    )
    assert stored_hourly["price_eur_mwh"].tolist() == [2.5, 1.0, 2.0]


def test_historical_price_ingestion_preserves_resolution_and_later_rows_after_gap(
    tmp_path, monkeypatch
):
    import ingestion.fetch_entsoe_data as ingestion

    monkeypatch.setattr(ingestion, "RAW_ENTSOE_DIR", tmp_path / "raw")
    quarter_hours = pd.date_range(
        "2026-09-12T00:00Z", "2026-09-12T21:45Z", freq="15min"
    )
    price_rows = pd.DataFrame(
        {
            "price_eur_mwh": np.arange(len(quarter_hours), dtype="float64"),
            "source_resolution": "PT15M",
        },
        index=quarter_hours,
    )
    hourly_rows = pd.DataFrame(
        {
            "price_eur_mwh": [100.0, 101.0],
            "source_resolution": ["PT60M", "PT60M"],
        },
        index=pd.date_range("2026-09-12T22:00Z", periods=2, freq="h"),
    )

    class FakeClient:
        prices = pd.concat([price_rows, hourly_rows])

        def query_day_ahead_prices(self, _country_code, start, end):
            return self.prices.loc[(self.prices.index >= start) & (self.prices.index < end)]

        def query_load(self, _country_code, start, end):
            return pd.Series(
                [1.0], index=pd.DatetimeIndex([pd.Timestamp("2026-09-12T00:00Z")])
            )

        def query_generation(self, _country_code, start, end):
            return pd.DataFrame(
                {"Biomass": [1.0]},
                index=pd.DatetimeIndex([pd.Timestamp("2026-09-12T00:00Z")]),
            )

    client = FakeClient()
    result = fetch_entsoe_data(
        "2026-09-12", "2026-09-12", mode="historical", client=client
    )
    stored = pd.read_csv(tmp_path / "raw" / "prices.csv")

    assert result["datasets"]["day-ahead prices"]["new_rows"] == 90
    assert stored["source_resolution"].tail(2).tolist() == ["PT60M", "PT60M"]
    assert pd.to_datetime(stored["timestamp"], utc=True).is_unique

    client.prices = client.prices.drop(pd.Timestamp("2026-09-12T20:15Z"))
    with_gap = fetch_entsoe_data(
        "2026-09-12", "2026-09-12", mode="historical", client=client
    )
    stored_with_gap = pd.read_csv(tmp_path / "raw" / "prices.csv")
    assert with_gap["datasets"]["day-ahead prices"]["unresolved_gap"]["missing_count"] == 1
    assert "2026-09-12 23:00:00+00:00" in stored_with_gap["timestamp"].tolist()
    assert "2026-09-12 20:15:00+00:00" not in stored_with_gap["timestamp"].tolist()


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


def test_real_quarter_hour_gap_returns_only_complete_contiguous_hours():
    index = pd.date_range(
        "2026-09-12T20:00:00Z",
        "2026-09-12T23:00:00Z",
        freq="15min",
    ).difference(
        pd.DatetimeIndex(
            [
                "2026-09-12T22:15:00Z",
                "2026-09-12T22:30:00Z",
                "2026-09-12T22:45:00Z",
            ]
        )
    )
    returned = pd.Series(np.arange(len(index), dtype="float64"), index=index)

    result = contiguous_prefix(
        returned,
        pd.Timestamp("2026-09-12T20:00:00Z"),
        "15min",
        quarter_hourly_transition=pd.Timestamp("2025-09-30T22:00:00Z"),
        require_complete_quarter_hourly_hours=True,
    )

    assert result.data.index[-1] == pd.Timestamp("2026-09-12T21:45:00Z")
    assert result.first_unresolved_timestamp == pd.Timestamp(
        "2026-09-12T22:15:00Z"
    )
    assert set(result.missing_timestamps) == {
        pd.Timestamp("2026-09-12T22:15:00Z"),
        pd.Timestamp("2026-09-12T22:30:00Z"),
        pd.Timestamp("2026-09-12T22:45:00Z"),
    }
    assert set(result.data.index).issubset(set(returned.index))


def test_gap_retains_later_raw_observations_without_duplicates(
    tmp_path,
):
    path = tmp_path / "prices.csv"
    initial_index = pd.date_range(
        "2026-09-12T19:00:00Z", periods=4, freq="15min"
    )
    pd.DataFrame(
        {"timestamp": initial_index, "price_eur_mwh": [1.0, 2.0, 3.0, 4.0]}
    ).to_csv(path, index=False)
    starts = []

    def query(country_code, start, end):
        starts.append(start)
        index = pd.date_range(start, "2026-09-12T23:00:00Z", freq="15min")
        index = index.difference(
            pd.DatetimeIndex(
                [
                    "2026-09-12T22:15:00Z",
                    "2026-09-12T22:30:00Z",
                    "2026-09-12T22:45:00Z",
                ]
            )
        )
        return pd.Series(np.arange(len(index), dtype="float64"), index=index)

    first = _incremental_dataset(
        None,
        query,
        dataset_name="day-ahead prices",
        output_path=path,
        default_interval="15min",
        end_utc_exclusive=pd.Timestamp("2026-09-12T23:15:00Z"),
        value_name="price_eur_mwh",
    )
    first_bytes = path.read_bytes()
    second = _incremental_dataset(
        None,
        query,
        dataset_name="day-ahead prices",
        output_path=path,
        default_interval="15min",
        end_utc_exclusive=pd.Timestamp("2026-09-12T23:15:00Z"),
        value_name="price_eur_mwh",
    )
    stored = pd.read_csv(path)
    stored_timestamps = pd.to_datetime(stored["timestamp"], utc=True)

    assert first["latest_timestamp"] == pd.Timestamp("2026-09-12T23:00:00Z")
    assert first["latest_complete_hour"] == "2026-09-12T21:00:00+00:00"
    assert first["unresolved_gap"]["later_observations_retained"] == 1
    assert first["unresolved_gap"]["first_unresolved_timestamp"] == (
        "2026-09-12T22:15:00+00:00"
    )
    assert second["new_rows"] == 0
    assert starts == [pd.Timestamp("2026-09-12T20:00:00Z")]
    assert path.read_bytes() == first_bytes
    assert stored_timestamps.is_unique
    assert pd.Timestamp("2026-09-12T22:00:00Z") in set(stored_timestamps)
    assert pd.Timestamp("2026-09-12T23:00:00Z") in set(stored_timestamps)


def test_missing_load_quarter_hour_does_not_block_later_raw_hours(tmp_path):
    path = tmp_path / "load.csv"
    pd.DataFrame({"timestamp": ["2026-09-19T08:00Z"], "load_mw": [40000.0]}).to_csv(
        path, index=False
    )

    def query(_country_code, start, end):
        observed = pd.date_range(start, end - pd.Timedelta(minutes=15), freq="15min")
        observed = observed.difference(pd.DatetimeIndex(["2026-09-19T08:45Z"]))
        return pd.Series(40000.0, index=observed)

    result = _incremental_dataset(
        None, query, dataset_name="actual load", output_path=path,
        default_interval="15min", end_utc_exclusive=pd.Timestamp("2026-09-19T11:00Z"),
        value_name="load_mw",
    )
    stored = pd.read_csv(path)
    timestamps = pd.to_datetime(stored["timestamp"], utc=True)
    assert result["unresolved_gap"]["first_unresolved_timestamp"] == "2026-09-19T08:45:00+00:00"
    assert result["unresolved_gap"]["later_observations_retained"] > 0
    assert pd.Timestamp("2026-09-19T10:45Z") in set(timestamps)
    assert pd.Timestamp("2026-09-19T08:45Z") not in set(timestamps)


def test_recent_load_overlap_repairs_late_quarter_and_restores_clean_hour(tmp_path):
    path = tmp_path / "load.csv"
    end = pd.Timestamp("2026-09-23T06:00:00Z")
    timestamps = pd.date_range(end - pd.Timedelta(hours=50), end, freq="15min", inclusive="left")
    missing = end - pd.Timedelta(hours=20, minutes=45)
    stored = timestamps.difference(pd.DatetimeIndex([missing]))
    pd.DataFrame({"timestamp": stored, "load_mw": 40000.0}).to_csv(path, index=False)
    starts = []

    def query(_country_code, start, end):
        starts.append(start)
        returned = pd.date_range(
            start, end - pd.Timedelta(minutes=15), freq="15min"
        )
        return pd.Series(40000.0, index=returned)

    result = _incremental_dataset(
        None, query, dataset_name="actual load", output_path=path,
        default_interval="15min", end_utc_exclusive=end, value_name="load_mw",
    )
    repaired = pd.read_csv(path)
    repaired_timestamps = pd.to_datetime(repaired["timestamp"], utc=True)
    assert starts[0] <= missing
    assert result["new_rows"] == 1
    assert result["changed"] is True
    assert repaired_timestamps.is_unique
    assert missing in set(repaired_timestamps)
    assert missing.floor("h") in clean_load(path).index


def test_identical_load_overlap_is_noop_without_file_rewrite(tmp_path):
    path = tmp_path / "load.csv"
    end = pd.Timestamp("2026-09-23T06:00:00Z")
    timestamps = pd.date_range(end - pd.Timedelta(hours=50), end, freq="15min", inclusive="left")
    pd.DataFrame({"timestamp": timestamps, "load_mw": 40000.0}).to_csv(path, index=False)
    before = path.read_bytes()

    def query(_country_code, start, end):
        returned = pd.date_range(
            start, end - pd.Timedelta(minutes=15), freq="15min"
        )
        return pd.Series(40000.0, index=returned)

    result = _incremental_dataset(
        None, query, dataset_name="actual load", output_path=path,
        default_interval="15min", end_utc_exclusive=end, value_name="load_mw",
    )
    assert result["new_rows"] == 0
    assert result["repaired_cells"] == 0
    assert result["revised_cells"] == 0
    assert result["changed"] is False
    assert path.read_bytes() == before


def test_load_overlap_does_not_report_gap_for_timestamp_already_stored(tmp_path):
    path = tmp_path / "load.csv"
    end = pd.Timestamp("2026-09-23T06:00:00Z")
    timestamps = pd.date_range(
        end - pd.Timedelta(hours=50), end, freq="15min", inclusive="left"
    )
    omitted_by_retry = end - pd.Timedelta(hours=12, minutes=15)
    pd.DataFrame({"timestamp": timestamps, "load_mw": 40000.0}).to_csv(
        path, index=False
    )
    before = path.read_bytes()

    def query(_country_code, start, end):
        returned = pd.date_range(
            start, end - pd.Timedelta(minutes=15), freq="15min"
        ).difference(pd.DatetimeIndex([omitted_by_retry]))
        return pd.Series(40000.0, index=returned)

    result = _incremental_dataset(
        None, query, dataset_name="actual load", output_path=path,
        default_interval="15min", end_utc_exclusive=end, value_name="load_mw",
    )
    assert result["unresolved_gap"] is None
    assert result["changed"] is False
    assert path.read_bytes() == before


def test_recent_load_revision_is_accepted_and_old_revision_is_protected(tmp_path):
    end = pd.Timestamp("2026-09-23T06:00:00Z")
    recent_path = tmp_path / "recent-load.csv"
    timestamps = pd.date_range(end - pd.Timedelta(hours=50), end, freq="15min", inclusive="left")
    pd.DataFrame({"timestamp": timestamps, "load_mw": 40000.0}).to_csv(
        recent_path, index=False
    )
    revised_at = end - pd.Timedelta(hours=2)

    def recent_query(_country_code, start, end):
        returned = pd.date_range(
            start, end - pd.Timedelta(minutes=15), freq="15min"
        )
        values = pd.Series(40000.0, index=returned)
        values.loc[revised_at] = 40123.0
        return values

    recent = _incremental_dataset(
        None, recent_query, dataset_name="actual load", output_path=recent_path,
        default_interval="15min", end_utc_exclusive=end, value_name="load_mw",
    )
    recent_stored = pd.read_csv(recent_path)
    recent_stored["timestamp"] = pd.to_datetime(recent_stored["timestamp"], utc=True)
    assert recent["revised_cells"] == 1 and recent["changed"] is True
    assert recent_stored.loc[
        recent_stored["timestamp"] == revised_at, "load_mw"
    ].iloc[0] == 40123.0

    old_path = tmp_path / "old-load.csv"
    old_start = end - pd.Timedelta(hours=50)
    old_timestamps = pd.date_range(old_start, periods=8, freq="15min")
    pd.DataFrame({"timestamp": old_timestamps, "load_mw": 40000.0}).to_csv(
        old_path, index=False
    )
    before = old_path.read_bytes()

    def old_query(_country_code, start, end):
        values = pd.Series(40000.0, index=old_timestamps)
        values.iloc[0] = 49999.0
        return values

    protected = _incremental_dataset(
        None, old_query, dataset_name="actual load", output_path=old_path,
        default_interval="15min", end_utc_exclusive=end, value_name="load_mw",
    )
    assert protected["protected_conflicts"] == 1
    assert protected["revised_cells"] == 0
    assert protected["changed"] is False
    assert old_path.read_bytes() == before


def test_unresolved_recent_load_gap_is_warning_metadata_only(tmp_path):
    path = tmp_path / "load.csv"
    end = pd.Timestamp("2026-09-23T06:00:00Z")
    timestamps = pd.date_range(end - pd.Timedelta(hours=50), end, freq="15min", inclusive="left")
    missing = end - pd.Timedelta(hours=10, minutes=45)
    observed = timestamps.difference(pd.DatetimeIndex([missing]))
    pd.DataFrame({"timestamp": observed, "load_mw": 40000.0}).to_csv(path, index=False)
    before = path.read_bytes()

    def query(_country_code, start, end):
        returned = pd.date_range(
            start, end - pd.Timedelta(minutes=15), freq="15min"
        ).difference(pd.DatetimeIndex([missing]))
        return pd.Series(40000.0, index=returned)

    result = _incremental_dataset(
        None, query, dataset_name="actual load", output_path=path,
        default_interval="15min", end_utc_exclusive=end, value_name="load_mw",
    )
    assert result["changed"] is False
    assert result["unresolved_gap"]["first_unresolved_timestamp"] == missing.isoformat()
    assert result["unresolved_gap"]["affected_hours"] == [missing.floor("h").isoformat()]
    assert path.read_bytes() == before


def test_incomplete_quarter_hour_price_is_not_aggregated():
    index = pd.to_datetime(
        [
            "2026-09-12T20:00:00Z",
            "2026-09-12T20:15:00Z",
            "2026-09-12T20:30:00Z",
            "2026-09-12T20:45:00Z",
            "2026-09-12T21:00:00Z",
        ]
    )
    prices = pd.DataFrame({"price_eur_mwh": [10, 20, 30, 40, 999]}, index=index)

    hourly = aggregate_hourly_prices(prices)

    assert hourly.index.tolist() == [pd.Timestamp("2026-09-12T20:00:00Z")]
    assert hourly.iloc[0]["price_eur_mwh"] == 25


def test_quarter_hour_gaps_exclude_only_affected_silver_hours_across_dst():
    index = pd.date_range("2026-03-28T22:00Z", periods=20, freq="15min")
    gaps = pd.DatetimeIndex(["2026-03-28T23:45Z", "2026-03-29T01:15Z"])
    observed = index.difference(gaps)
    load = pd.DataFrame({"load_mw": 40000.0}, index=observed)
    hourly = aggregate_quarter_hourly(
        load, require_complete_hours=True, required_columns=["load_mw"]
    )

    assert hourly.index.tolist() == [
        pd.Timestamp("2026-03-28T22:00Z"),
        pd.Timestamp("2026-03-29T00:00Z"),
        pd.Timestamp("2026-03-29T02:00Z"),
    ]
    assert hourly.index.is_unique
    assert str(hourly.index.tz) == "UTC"


def test_duplicate_raw_timestamp_is_rejected_not_silently_deduplicated():
    raw = pd.DataFrame(
        {"timestamp": ["2026-09-19T08:00Z", "2026-09-19T08:00Z"], "load_mw": [1, 2]}
    )
    with pytest.raises(ValueError, match="unique"):
        set_utc_timestamp_index(raw)


def test_duplicate_source_chunks_are_rejected():
    timestamp = pd.Timestamp("2026-09-19T08:00Z")
    source = pd.Series([1.0], index=pd.DatetimeIndex([timestamp]))
    with pytest.raises(ValueError, match="duplicate timestamps"):
        combine_time_chunks([source, source])


def test_silver_rebuild_skips_incomplete_hour_and_keeps_later_hour(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    quarter_hours = pd.date_range("2026-09-19T08:00Z", periods=12, freq="15min")
    complete_hours = pd.date_range("2026-09-19T08:00Z", periods=3, freq="h")
    raw_dir = tmp_path / "data/raw/entsoe"
    weather_dir = tmp_path / "data/raw/weather"
    raw_dir.mkdir(parents=True)
    weather_dir.mkdir(parents=True)
    pd.DataFrame({
        "timestamp": quarter_hours,
        "price_eur_mwh": np.arange(12, dtype=float),
        "source_resolution": "PT15M",
    }).to_csv(raw_dir / "prices.csv", index=False)
    observed_load = quarter_hours.difference(pd.DatetimeIndex(["2026-09-19T08:45Z"]))
    pd.DataFrame({"timestamp": observed_load, "load_mw": 40000.0}).to_csv(
        raw_dir / "load.csv", index=False
    )
    generation = pd.DataFrame({"timestamp": quarter_hours})
    for column in (
        "Biomass", "Fossil Brown coal/Lignite", "Fossil Gas",
        "Fossil Hard coal", "Hydro Run-of-river and poundage", "Nuclear",
        "Solar", "Wind Offshore", "Wind Onshore",
    ):
        generation[column] = 100.0
    generation.to_csv(raw_dir / "generation.csv", index=False)
    weather = pd.DataFrame({"timestamp": complete_hours})
    for column in (
        "temperature_2m", "relative_humidity_2m", "wind_speed_10m",
        "cloud_cover", "shortwave_radiation",
    ):
        weather[column] = 10.0
    weather.to_csv(weather_dir / "open_meteo_weather.csv", index=False)

    build_silver_dataset()
    silver = pd.read_csv("data/processed/silver_electricity_market_data.csv")
    assert pd.to_datetime(silver["timestamp"], utc=True).tolist() == [
        pd.Timestamp("2026-09-19T09:00Z"),
        pd.Timestamp("2026-09-19T10:00Z"),
    ]


def test_entsoe_no_new_data_after_clean_catchup_does_not_query(tmp_path):
    path = tmp_path / "prices.csv"
    index = pd.date_range("2026-09-12T00:00:00Z", periods=4, freq="15min")
    pd.DataFrame(
        {"timestamp": index, "price_eur_mwh": [1.0, 2.0, 3.0, 4.0]}
    ).to_csv(path, index=False)

    def forbidden_query(*args, **kwargs):
        raise AssertionError("No API query should be made.")

    result = _incremental_dataset(
        None,
        forbidden_query,
        dataset_name="day-ahead prices",
        output_path=path,
        default_interval="15min",
        end_utc_exclusive=pd.Timestamp("2026-09-12T01:00:00Z"),
        value_name="price_eur_mwh",
    )

    assert result["new_rows"] == 0
    assert result["unresolved_gap"] is None


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
        now=pd.Timestamp("2025-01-11T12:00:00Z"),
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
