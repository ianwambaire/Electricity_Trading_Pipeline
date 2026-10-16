import pandas as pd
import pytest

from ingestion.fetch_operational_weather_forecasts import (
    WEATHER_FORECAST_COLUMNS,
    WEATHER_VARIABLES,
    WEATHER_VINTAGE_IDENTITY,
    append_weather_forecast_vintages,
    fetch_operational_weather_forecast_vintage,
    merge_weather_forecast_vintages,
    normalize_weather_forecast_vintages,
    parse_open_meteo_forecast,
)


ISSUE = pd.Timestamp("2026-10-15T12:00:00Z")
ACQUIRED = pd.Timestamp("2026-10-15T12:05:00Z")


def _payload(*, remove_hour=None, duplicate_hour=None, model="best_match"):
    timestamps = list(pd.date_range(ISSUE, ISSUE + pd.Timedelta(hours=30), freq="h"))
    if remove_hour is not None:
        timestamps.remove(ISSUE + pd.Timedelta(hours=remove_hour))
    if duplicate_hour is not None:
        timestamps.append(ISSUE + pd.Timedelta(hours=duplicate_hour))
    count = len(timestamps)
    return {
        "timezone": "UTC",
        "utc_offset_seconds": 0,
        "model": model,
        "hourly": {
            "time": [timestamp.strftime("%Y-%m-%dT%H:%M") for timestamp in timestamps],
            "temperature_2m": [10.0 + index / 10 for index in range(count)],
            "relative_humidity_2m": [60.0] * count,
            "wind_speed_10m": [12.0] * count,
            "cloud_cover": [40.0] * count,
            "shortwave_radiation": [100.0] * count,
        },
    }


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, params, timeout))
        return FakeResponse(self.payload)


def test_parser_keeps_exactly_t_plus_1_through_t_plus_24_in_utc():
    frame = parse_open_meteo_forecast(
        _payload(),
        collection_issue_time=ISSUE,
        acquired_at_utc=ACQUIRED,
    )

    assert tuple(frame.columns) == WEATHER_FORECAST_COLUMNS
    assert len(frame) == 24
    assert frame["horizon_hours"].tolist() == list(range(1, 25))
    assert frame["target_timestamp"].iloc[0] == ISSUE + pd.Timedelta(hours=1)
    assert frame["target_timestamp"].iloc[-1] == ISSUE + pd.Timedelta(hours=24)
    assert str(frame["target_timestamp"].dt.tz) == "UTC"
    assert set(frame["provider"]) == {"OPEN_METEO"}
    assert set(frame["model"]) == {"best_match"}
    assert frame[list(WEATHER_VARIABLES)].notna().all().all()


def test_missing_or_duplicate_target_hours_are_rejected():
    with pytest.raises(ValueError, match="does not cover every"):
        parse_open_meteo_forecast(
            _payload(remove_hour=8),
            collection_issue_time=ISSUE,
            acquired_at_utc=ACQUIRED,
        )
    with pytest.raises(ValueError, match="duplicate target hours"):
        parse_open_meteo_forecast(
            _payload(duplicate_hour=8),
            collection_issue_time=ISSUE,
            acquired_at_utc=ACQUIRED,
        )


def test_finite_ranges_and_non_negative_horizons_are_strict():
    frame = parse_open_meteo_forecast(
        _payload(), collection_issue_time=ISSUE, acquired_at_utc=ACQUIRED
    )
    invalid = frame.copy()
    invalid.loc[0, "temperature_2m"] = float("inf")
    with pytest.raises(ValueError, match="finite"):
        normalize_weather_forecast_vintages(invalid)

    invalid = frame.copy()
    invalid.loc[0, "relative_humidity_2m"] = 101
    with pytest.raises(ValueError, match="between 0 and 100"):
        normalize_weather_forecast_vintages(invalid)

    invalid = frame.copy()
    invalid.loc[0, "horizon_hours"] = -1
    with pytest.raises(ValueError, match="non-negative"):
        normalize_weather_forecast_vintages(invalid)


def test_same_collection_cycle_is_idempotent_and_keeps_earliest_acquisition():
    original = parse_open_meteo_forecast(
        _payload(), collection_issue_time=ISSUE, acquired_at_utc=ACQUIRED
    )
    assert len(merge_weather_forecast_vintages(original, original)) == 24

    later = parse_open_meteo_forecast(
        _payload(),
        collection_issue_time=ISSUE,
        acquired_at_utc=ACQUIRED + pd.Timedelta(minutes=10),
    )
    combined = merge_weather_forecast_vintages(original, later)
    assert len(combined) == 24
    assert set(combined["acquired_at_utc"]) == {ACQUIRED}


def test_fetcher_requests_expected_window_and_never_mutates_observed_weather(tmp_path):
    raw = tmp_path / "data/raw/weather"
    raw.mkdir(parents=True)
    observed = raw / "open_meteo_weather.csv"
    observed.write_text("protected observed weather\n", encoding="utf-8")
    before = observed.read_bytes()
    output = raw / "open_meteo_forecast_vintages.csv"
    session = FakeSession(_payload())

    result = fetch_operational_weather_forecast_vintage(
        ISSUE,
        acquired_at_utc=ACQUIRED,
        session=session,
        output_path=output,
    )

    assert result["rows_after"] == 24
    assert result["new_rows"] == 24
    assert observed.read_bytes() == before
    _, params, timeout = session.calls[0]
    assert params["start_hour"] == "2026-10-15T13:00"
    assert params["end_hour"] == "2026-10-16T12:00"
    assert params["timezone"] == "UTC"
    assert timeout == 60
    saved = pd.read_csv(output)
    assert len(saved) == 24


def test_observed_weather_destination_is_rejected(tmp_path):
    frame = parse_open_meteo_forecast(
        _payload(), collection_issue_time=ISSUE, acquired_at_utc=ACQUIRED
    )
    observed = tmp_path / "open_meteo_weather.csv"
    observed.write_text("do not replace\n", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot overwrite observed"):
        append_weather_forecast_vintages(observed, frame)
    assert observed.read_text(encoding="utf-8") == "do not replace\n"


def test_issue_time_timezone_and_schema_are_strict():
    with pytest.raises(ValueError, match="explicit timezone"):
        parse_open_meteo_forecast(
            _payload(),
            collection_issue_time="2026-10-15T12:00:00",
            acquired_at_utc=ACQUIRED,
        )
    frame = parse_open_meteo_forecast(
        _payload(), collection_issue_time=ISSUE, acquired_at_utc=ACQUIRED
    )
    with pytest.raises(ValueError, match="current schema or the documented legacy"):
        normalize_weather_forecast_vintages(frame.drop(columns="model"))


def test_legacy_issue_time_schema_is_readable_and_horizons_remain_1_to_24():
    current = parse_open_meteo_forecast(
        _payload(), collection_issue_time=ISSUE, acquired_at_utc=ACQUIRED
    )
    legacy = current.rename(
        columns={"collection_issue_time": "forecast_issue_time"}
    )

    normalized = normalize_weather_forecast_vintages(legacy)

    assert tuple(normalized.columns) == WEATHER_FORECAST_COLUMNS
    assert set(normalized["collection_issue_time"]) == {ISSUE}
    assert normalized["horizon_hours"].tolist() == list(range(1, 25))


def test_idempotent_weather_reacquisition_does_not_rewrite_existing_file(tmp_path):
    frame = parse_open_meteo_forecast(
        _payload(), collection_issue_time=ISSUE, acquired_at_utc=ACQUIRED
    )
    path = tmp_path / "open_meteo_forecast_vintages.csv"
    frame.to_csv(path, index=False)
    before = path.read_bytes()
    later = parse_open_meteo_forecast(
        _payload(),
        collection_issue_time=ISSUE,
        acquired_at_utc=ACQUIRED + pd.Timedelta(minutes=10),
    )

    result = append_weather_forecast_vintages(path, later)

    assert result["new_rows"] == 0
    assert path.read_bytes() == before


def test_append_repairs_identical_persisted_duplicates_and_adds_new_cycle(tmp_path):
    original = parse_open_meteo_forecast(
        _payload(), collection_issue_time=ISSUE, acquired_at_utc=ACQUIRED
    )
    path = tmp_path / "open_meteo_forecast_vintages.csv"
    pd.concat([original, original], ignore_index=True).to_csv(path, index=False)
    next_issue = ISSUE + pd.Timedelta(hours=1)
    next_payload = _payload()
    next_payload["hourly"]["time"] = [
        (pd.Timestamp(value, tz="UTC") + pd.Timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M"
        )
        for value in next_payload["hourly"]["time"]
    ]
    incoming = parse_open_meteo_forecast(
        next_payload,
        collection_issue_time=next_issue,
        acquired_at_utc=ACQUIRED + pd.Timedelta(hours=1),
    )

    result = append_weather_forecast_vintages(path, incoming)
    saved = pd.read_csv(path)

    assert result["rows_before"] == 24
    assert result["new_rows"] == 24
    assert result["rows_after"] == 48
    assert len(saved) == 48
    assert saved["collection_issue_time"].nunique() == 2
    assert not saved.duplicated(list(WEATHER_VINTAGE_IDENTITY)).any()


def test_new_weather_cycle_migrates_legacy_issue_column_without_losing_rows(
    tmp_path,
):
    original = parse_open_meteo_forecast(
        _payload(), collection_issue_time=ISSUE, acquired_at_utc=ACQUIRED
    )
    legacy = original.rename(
        columns={"collection_issue_time": "forecast_issue_time"}
    )
    path = tmp_path / "open_meteo_forecast_vintages.csv"
    legacy.to_csv(path, index=False)
    next_issue = ISSUE + pd.Timedelta(hours=1)
    next_payload = _payload()
    next_payload["hourly"]["time"] = [
        (pd.Timestamp(value, tz="UTC") + pd.Timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M"
        )
        for value in next_payload["hourly"]["time"]
    ]
    incoming = parse_open_meteo_forecast(
        next_payload,
        collection_issue_time=next_issue,
        acquired_at_utc=ACQUIRED + pd.Timedelta(hours=1),
    )

    result = append_weather_forecast_vintages(path, incoming)
    saved = pd.read_csv(path)

    assert result["new_rows"] == 24
    assert len(saved) == 48
    assert "collection_issue_time" in saved
    assert "forecast_issue_time" not in saved


def test_weather_acquisition_clock_runs_after_successful_response(tmp_path):
    events = []

    class OrderedSession(FakeSession):
        def get(self, url, params, timeout):
            events.append("response")
            return super().get(url, params, timeout)

    def acquisition_clock():
        events.append("acquired")
        return ACQUIRED

    result = fetch_operational_weather_forecast_vintage(
        ISSUE,
        acquisition_clock=acquisition_clock,
        session=OrderedSession(_payload()),
        output_path=tmp_path / "open_meteo_forecast_vintages.csv",
    )

    assert events == ["response", "acquired"]
    assert result["collection_issue_time"] == ISSUE.isoformat()
    assert result["acquired_at_utc"] == ACQUIRED.isoformat()
