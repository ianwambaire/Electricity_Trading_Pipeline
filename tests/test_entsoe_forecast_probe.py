import json

import pandas as pd
import pytest

from scripts.probe_entsoe_forecasts import (
    ENDPOINTS,
    probe_forecast_endpoints,
    summarize_response,
    write_summary,
)


START = pd.Timestamp("2026-10-02T00:00:00Z")
END = pd.Timestamp("2026-10-04T00:00:00Z")


class MockForecastClient:
    def __init__(self, responses=None, failures=None):
        self.responses = responses or {}
        self.failures = failures or {}
        self.calls = []

    def _call(self, name, country_code, start, end):
        self.calls.append((name, country_code, start, end))
        if name in self.failures:
            raise self.failures[name]
        return self.responses[name]

    def query_load_forecast(self, country_code, start, end):
        return self._call("query_load_forecast", country_code, start, end)

    def query_wind_and_solar_forecast(self, country_code, start, end):
        return self._call("query_wind_and_solar_forecast", country_code, start, end)

    def query_intraday_wind_and_solar_forecast(self, country_code, start, end):
        return self._call(
            "query_intraday_wind_and_solar_forecast", country_code, start, end
        )

    def query_generation_forecast(self, country_code, start, end):
        return self._call("query_generation_forecast", country_code, start, end)


def _responses():
    hourly = pd.date_range(START, periods=4, freq="h")
    quarter_hourly = pd.date_range(START, periods=8, freq="15min")
    return {
        "query_load_forecast": pd.DataFrame(
            {"Forecasted Load": [50_000.0, 50_100.0, 50_200.0, 50_300.0]},
            index=hourly,
        ),
        "query_wind_and_solar_forecast": pd.DataFrame(
            {
                "Wind Offshore": range(8),
                "Wind Onshore": range(10, 18),
                "Solar": range(20, 28),
            },
            index=quarter_hourly,
        ),
        "query_intraday_wind_and_solar_forecast": pd.DataFrame(
            {"Wind Onshore": range(4), "Solar": range(4)}, index=hourly
        ),
        "query_generation_forecast": pd.Series(
            [60_000.0, 60_100.0, 60_200.0, 60_300.0],
            index=hourly,
            name="Scheduled Generation",
        ),
    }


def test_each_endpoint_is_called_independently_and_summarized():
    client = MockForecastClient(_responses())
    report = probe_forecast_endpoints(client, START, END)

    assert [call[0] for call in client.calls] == [item[1] for item in ENDPOINTS]
    assert all(call[1] == "DE_LU" for call in client.calls)
    assert all(result["status"] == "success" for result in report["endpoints"].values())
    assert report["returned_values_persisted"] is False


def test_failure_is_safe_and_does_not_stop_remaining_endpoints():
    protected = "api-key-must-never-appear"
    client = MockForecastClient(
        _responses(),
        failures={"query_wind_and_solar_forecast": RuntimeError(protected)},
    )
    report = probe_forecast_endpoints(client, START, END)

    failed = report["endpoints"]["wind_and_solar_forecast"]
    assert failed["status"] == "error"
    assert failed["error_type"] == "RuntimeError"
    assert protected not in json.dumps(report)
    assert report["endpoints"]["generation_forecast"]["status"] == "success"
    assert len(client.calls) == 4


def test_timestamp_resolution_schema_and_technology_coverage():
    report = probe_forecast_endpoints(MockForecastClient(_responses()), START, END)
    load = report["endpoints"]["load_forecast"]
    renewable = report["endpoints"]["wind_and_solar_forecast"]

    assert load["timestamp_resolution"] == "1h"
    assert load["timestamp_timezone"] == "UTC"
    assert load["coverage"]["total_load"] is True
    assert renewable["timestamp_resolution"] == "15min"
    assert renewable["available_psr_technology_columns"] == [
        "Solar", "Wind Offshore", "Wind Onshore"
    ]
    assert renewable["coverage"] == {
        "offshore_wind": True,
        "onshore_wind": True,
        "solar": True,
        "total_load": False,
        "aggregate_generation": False,
    }
    assert renewable["source_issue_or_publication_time_exposed"] is False
    assert renewable["can_distinguish_issue_time_from_target_time"] is False


def test_duplicate_and_missing_values_are_counted_without_storing_values():
    index = pd.DatetimeIndex([START, START, START + pd.Timedelta(hours=1)])
    frame = pd.DataFrame(
        {"Wind Offshore": [1.0, None, 3.0], "Solar": [None, 2.0, 3.0]},
        index=index,
    )
    summary = summarize_response(frame, "wind_and_solar_forecast")

    assert summary["duplicate_timestamps"] == 2
    assert summary["missing_values"] == {
        "total": 2,
        "by_column": {"Wind Offshore": 1, "Solar": 1},
    }
    assert summary["timestamp_resolution"] == "1h"
    assert "returned_values" not in summary


def test_summary_writer_restricts_output_and_never_writes_secret(tmp_path, monkeypatch):
    import scripts.probe_entsoe_forecasts as probe

    approved = tmp_path / "artifacts/probes/entsoe_forecasts"
    monkeypatch.setattr(probe, "OUTPUT_DIR", approved)
    output = approved / "probe_summary.json"
    protected = "never-write-this-api-key"
    client = MockForecastClient(
        _responses(), failures={"query_load_forecast": ValueError(protected)}
    )
    report = probe_forecast_endpoints(client, START, END)
    write_summary(report, output)

    content = output.read_text(encoding="utf-8")
    assert protected not in content
    assert json.loads(content)["endpoints"]["load_forecast"]["status"] == "error"
    with pytest.raises(ValueError, match="must remain under"):
        write_summary(report, tmp_path / "outside.json")


def test_probe_rejects_non_de_lu_and_naive_ranges():
    client = MockForecastClient(_responses())
    with pytest.raises(ValueError, match="restricted to DE_LU"):
        probe_forecast_endpoints(client, START, END, country_code="FR")
    with pytest.raises(ValueError, match="explicit timezone"):
        probe_forecast_endpoints(client, pd.Timestamp("2026-10-02"), END)
