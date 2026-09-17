import traceback

import pandas as pd
import pytest

from ingestion.fetch_entsoe_data import (
    combine_time_chunks,
    fetch_in_chunks,
    redact_sensitive_url,
)
from ingestion.fetch_weather_data import combine_weather_chunks
from ingestion.historical_range import (
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    get_historical_date_range,
    iter_time_chunks,
)
from processing.build_silver_dataset import (
    aggregate_quarter_hourly,
    set_utc_timestamp_index,
)


def test_default_and_explicit_date_range_configuration(monkeypatch):
    monkeypatch.delenv("POWERFLOW_HISTORY_START_DATE", raising=False)
    monkeypatch.delenv("POWERFLOW_HISTORY_END_DATE", raising=False)

    default_range = get_historical_date_range()
    explicit_range = get_historical_date_range("2020-02-01", "2020-02-29")

    assert default_range.start_date.isoformat() == DEFAULT_START_DATE
    assert default_range.end_date.isoformat() == DEFAULT_END_DATE
    assert explicit_range.start_date.isoformat() == "2020-02-01"
    assert explicit_range.end_date.isoformat() == "2020-02-29"

    monkeypatch.setenv("POWERFLOW_HISTORY_START_DATE", "2021-01-01")
    monkeypatch.setenv("POWERFLOW_HISTORY_END_DATE", "2021-12-31")
    environment_range = get_historical_date_range()

    assert environment_range.start_date.isoformat() == "2021-01-01"
    assert environment_range.end_date.isoformat() == "2021-12-31"


def test_entsoe_chunk_boundaries_are_contiguous_and_end_exclusive():
    historical_range = get_historical_date_range("2019-01-01", "2021-03-15")
    chunks = list(iter_time_chunks(historical_range))

    assert chunks[0][0] == pd.Timestamp("2019-01-01", tz="UTC")
    assert chunks[-1][1] == pd.Timestamp("2021-03-16", tz="UTC")
    assert all(
        current[1] == following[0]
        for current, following in zip(chunks, chunks[1:])
    )
    assert all(end > start for start, end in chunks)
    assert any(
        current[1] == pd.Timestamp("2020-01-01", tz="UTC")
        and following[0] == pd.Timestamp("2020-01-01", tz="UTC")
        for current, following in zip(chunks, chunks[1:])
    )


def test_entsoe_chunk_combination_removes_duplicate_timestamps_and_sorts():
    first = pd.Series(
        [10.0, 20.0],
        index=pd.to_datetime(["2020-01-01T01:00Z", "2020-01-01T02:00Z"]),
    )
    second = pd.Series(
        [21.0, 30.0],
        index=pd.to_datetime(["2020-01-01T02:00Z", "2020-01-01T03:00Z"]),
    )

    combined = combine_time_chunks([second, first])

    assert combined.index.is_monotonic_increasing
    assert combined.index.is_unique
    assert combined.loc[pd.Timestamp("2020-01-01T02:00Z")] == 20.0


def test_short_chunks_preserve_hour_at_calendar_year_boundary():
    historical_range = get_historical_date_range("2019-01-01", "2020-01-02")

    def boundary_sensitive_query(country_code, start, end):
        index = pd.date_range(start, end, freq="h", inclusive="left")
        if end - start >= pd.Timedelta(days=365):
            index = index.delete(index.get_loc(end - pd.Timedelta(days=1)))
        return pd.Series(range(len(index)), index=index, dtype="float64")

    combined = fetch_in_chunks(
        None,
        boundary_sensitive_query,
        historical_range,
        "day-ahead prices",
    )

    expected = pd.date_range(
        "2019-01-01T00:00:00Z",
        "2020-01-03T00:00:00Z",
        freq="h",
        inclusive="left",
    )
    assert combined.index.equals(expected)
    assert pd.Timestamp("2019-12-31T00:00:00Z") in combined.index


def test_entsoe_token_is_redacted_and_absent_from_failure_output(capsys):
    fake_token = "fake-secret-token-value"
    unsafe_url = (
        "https://web-api.tp.entsoe.eu/api?documentType=A44&"
        f"securityToken={fake_token}&api_key={fake_token}"
    )

    redacted_url = redact_sensitive_url(unsafe_url)

    def failing_query(*args, **kwargs):
        raise ConnectionError(f"Request failed: {unsafe_url}")

    historical_range = get_historical_date_range("2020-01-01", "2020-01-01")
    with pytest.raises(RuntimeError) as caught:
        fetch_in_chunks(None, failing_query, historical_range, "day-ahead prices")

    captured = capsys.readouterr()
    rendered_exception = "".join(
        traceback.format_exception(
            type(caught.value),
            caught.value,
            caught.value.__traceback__,
        )
    )
    visible_output = captured.out + captured.err + rendered_exception + redacted_url

    assert fake_token not in visible_output
    assert "ConnectionError" in visible_output
    assert "%5BREDACTED%5D" in redacted_url


def test_weather_chunk_combination_removes_duplicates_and_sorts():
    first = pd.DataFrame(
        {
            "timestamp": ["2020-01-01T01:00", "2020-01-01T02:00"],
            "temperature_2m": [1.0, 2.0],
        }
    )
    second = pd.DataFrame(
        {
            "timestamp": ["2020-01-01T00:00", "2020-01-01T01:00"],
            "temperature_2m": [0.0, 1.5],
        }
    )

    combined = combine_weather_chunks([first, second])

    assert combined["timestamp"].is_monotonic_increasing
    assert combined["timestamp"].is_unique
    duplicate_value = combined.loc[
        combined["timestamp"] == pd.Timestamp("2020-01-01T01:00Z"),
        "temperature_2m",
    ].item()
    assert duplicate_value == 1.5


def test_spring_dst_offsets_normalize_to_continuous_utc_hours():
    data = pd.DataFrame(
        {
            "timestamp": [
                "2024-03-31T01:00:00+01:00",
                "2024-03-31T03:00:00+02:00",
            ],
            "value": [1.0, 2.0],
        }
    )

    normalized = set_utc_timestamp_index(data)

    assert normalized.index.tolist() == [
        pd.Timestamp("2024-03-31T00:00:00Z"),
        pd.Timestamp("2024-03-31T01:00:00Z"),
    ]


def test_autumn_repeated_local_hour_remains_two_unique_utc_hours():
    data = pd.DataFrame(
        {
            "timestamp": [
                "2024-10-27T02:00:00+02:00",
                "2024-10-27T02:00:00+01:00",
            ],
            "value": [1.0, 2.0],
        }
    )

    normalized = set_utc_timestamp_index(data)

    assert normalized.index.tolist() == [
        pd.Timestamp("2024-10-27T00:00:00Z"),
        pd.Timestamp("2024-10-27T01:00:00Z"),
    ]
    assert normalized.index.is_unique


def test_quarter_hour_values_aggregate_into_each_real_utc_hour():
    data = pd.DataFrame(
        {
            "timestamp": [
                "2024-10-27T02:00:00+02:00",
                "2024-10-27T02:15:00+02:00",
                "2024-10-27T02:30:00+02:00",
                "2024-10-27T02:45:00+02:00",
                "2024-10-27T02:00:00+01:00",
                "2024-10-27T02:15:00+01:00",
                "2024-10-27T02:30:00+01:00",
                "2024-10-27T02:45:00+01:00",
            ],
            "load_mw": range(1, 9),
        }
    )
    indexed = set_utc_timestamp_index(data)

    hourly = aggregate_quarter_hourly(indexed)

    assert hourly.index.tolist() == [
        pd.Timestamp("2024-10-27T00:00:00Z"),
        pd.Timestamp("2024-10-27T01:00:00Z"),
    ]
    assert hourly["load_mw"].tolist() == [2.5, 6.5]
