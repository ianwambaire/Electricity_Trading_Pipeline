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
    iter_year_chunks,
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
    chunks = list(iter_year_chunks(historical_range))

    assert chunks[0][0] == pd.Timestamp("2019-01-01", tz="Europe/Berlin")
    assert chunks[-1][1] == pd.Timestamp("2021-03-16", tz="Europe/Berlin")
    assert all(
        current[1] == following[0]
        for current, following in zip(chunks, chunks[1:])
    )
    assert all(end > start for start, end in chunks)


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
        combined["timestamp"] == pd.Timestamp("2020-01-01T01:00"),
        "temperature_2m",
    ].item()
    assert duplicate_value == 1.5
