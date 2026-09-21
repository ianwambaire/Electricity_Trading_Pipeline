"""Weather freshness checks use fake API responses and temporary CSVs only."""

import pandas as pd
import pytest

from ingestion.fetch_weather_data import (
    OPEN_METEO_URL,
    WEATHER_VARIABLES,
    fetch_open_meteo_weather,
)


def weather_row(timestamp, value=1.0):
    return {"timestamp": timestamp, **{name: value for name in WEATHER_VARIABLES}}


class FakeResponse:
    def __init__(self, hourly):
        self.hourly = hourly

    def raise_for_status(self):
        pass

    def json(self):
        return {"hourly": self.hourly}


class FakeSession:
    def __init__(self, times, *, missing=None, extra=None):
        self.times = times
        self.missing = missing
        self.extra = extra or {}
        self.calls = []

    def get(self, url, *, params, timeout):
        self.calls.append((url, params, timeout))
        hourly = {"time": self.times}
        for name in WEATHER_VARIABLES:
            hourly[name] = [
                None if timestamp == self.missing else self.extra.get(timestamp, 1.0)
                for timestamp in self.times
            ]
        return FakeResponse(hourly)


def test_recent_archive_weather_advances_without_changing_history(tmp_path):
    path = tmp_path / "weather.csv"
    pd.DataFrame([weather_row("2026-09-15T23:00:00Z", 5.0)]).to_csv(path, index=False)
    times = [
        "2026-09-15T23:00",
        *pd.date_range("2026-09-16", "2026-09-20T23:00", freq="h").strftime(
            "%Y-%m-%dT%H:%M"
        ),
        "2026-09-21T00:00",
    ]
    session = FakeSession(times)

    result = fetch_open_meteo_weather(
        mode="incremental",
        now=pd.Timestamp("2026-09-21T15:00:00+03:00"),
        output_path=path,
        session=session,
    )
    stored = pd.read_csv(path)

    assert result["new_rows"] == 120
    assert result["latest_timestamp"] == pd.Timestamp("2026-09-20T23:00Z")
    assert stored.columns.tolist() == ["timestamp", *WEATHER_VARIABLES]
    assert len(stored) == 121
    assert stored.iloc[0][WEATHER_VARIABLES].tolist() == [5.0] * 5
    assert pd.to_datetime(stored["timestamp"], utc=True).is_unique
    assert session.calls[0][0] == OPEN_METEO_URL
    assert session.calls[0][1]["start_date"] == "2026-09-16"
    assert session.calls[0][1]["end_date"] == "2026-09-20"
    assert session.calls[0][1]["timezone"] == "UTC"


def test_weather_overlap_is_deduplicated_and_existing_row_is_preserved(tmp_path):
    path = tmp_path / "weather.csv"
    pd.DataFrame([weather_row("2026-09-19T23:00:00Z", 9.0)]).to_csv(path, index=False)
    session = FakeSession(
        ["2026-09-19T23:00", "2026-09-20T00:00", "2026-09-20T00:00", "2026-09-20T01:00"],
        extra={"2026-09-19T23:00": 100.0},
    )

    result = fetch_open_meteo_weather(
        mode="incremental",
        now=pd.Timestamp("2026-09-21T00:30Z"),
        output_path=path,
        session=session,
    )
    stored = pd.read_csv(path)

    assert result["new_rows"] == 2
    assert len(stored) == 3
    assert stored.iloc[0][WEATHER_VARIABLES].tolist() == [9.0] * 5
    assert pd.to_datetime(stored["timestamp"], utc=True).is_unique


def test_weather_missing_hour_rejects_append(tmp_path):
    path = tmp_path / "weather.csv"
    pd.DataFrame([weather_row("2026-09-19T23:00:00Z")]).to_csv(path, index=False)
    before = path.read_bytes()
    session = FakeSession(["2026-09-20T00:00", "2026-09-20T02:00"])

    with pytest.raises(ValueError, match="not continuous"):
        fetch_open_meteo_weather(
            mode="incremental",
            now=pd.Timestamp("2026-09-21T12:00Z"),
            output_path=path,
            session=session,
        )
    assert path.read_bytes() == before


def test_weather_empty_response_leaves_dataset_untouched(tmp_path):
    path = tmp_path / "weather.csv"
    pd.DataFrame([weather_row("2026-09-19T23:00:00Z")]).to_csv(path, index=False)
    before = path.read_bytes()
    session = FakeSession([])

    result = fetch_open_meteo_weather(
        mode="incremental",
        now=pd.Timestamp("2026-09-21T12:00Z"),
        output_path=path,
        session=session,
    )

    assert result["new_rows"] == 0
    assert path.read_bytes() == before


def test_weather_unpublished_trailing_hour_is_not_appended(tmp_path):
    path = tmp_path / "weather.csv"
    pd.DataFrame([weather_row("2026-09-19T23:00:00Z")]).to_csv(path, index=False)
    session = FakeSession(
        ["2026-09-20T00:00", "2026-09-20T01:00", "2026-09-20T02:00"],
        missing="2026-09-20T02:00",
    )

    result = fetch_open_meteo_weather(
        mode="incremental",
        now=pd.Timestamp("2026-09-21T12:00Z"),
        output_path=path,
        session=session,
    )

    assert result["new_rows"] == 2
    assert result["latest_timestamp"] == pd.Timestamp("2026-09-20T01:00Z")
    assert len(pd.read_csv(path)) == 3


def test_weather_no_completed_day_due_does_not_call_api(tmp_path):
    path = tmp_path / "weather.csv"
    pd.DataFrame([weather_row("2026-09-20T23:00:00Z")]).to_csv(path, index=False)

    class NoNetworkSession:
        def get(self, *args, **kwargs):
            raise AssertionError("No API request should be made.")

    result = fetch_open_meteo_weather(
        mode="incremental",
        now=pd.Timestamp("2026-09-21T12:00Z"),
        output_path=path,
        session=NoNetworkSession(),
    )

    assert result["new_rows"] == 0
    assert result["latest_timestamp"] == pd.Timestamp("2026-09-20T23:00Z")
