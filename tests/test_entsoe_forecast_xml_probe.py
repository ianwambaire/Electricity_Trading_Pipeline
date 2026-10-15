import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from scripts.probe_entsoe_forecast_xml import (
    ENDPOINTS,
    parse_forecast_xml,
    probe_xml_endpoints,
    write_summary,
)


START = pd.Timestamp("2026-10-15T00:00:00Z")
END = pd.Timestamp("2026-10-17T00:00:00Z")
ACQUIRED = datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc)


def _xml(
    *,
    document_type="A69",
    process_type="A01",
    resolution="PT15M",
    psr_type="B16",
    quantity="101.5",
):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">
  <mRID>document-123</mRID>
  <revisionNumber>2</revisionNumber>
  <type>{document_type}</type>
  <process.processType>{process_type}</process.processType>
  <sender_MarketParticipant.mRID codingScheme="A01">sender-10</sender_MarketParticipant.mRID>
  <sender_MarketParticipant.marketRole.type>A04</sender_MarketParticipant.marketRole.type>
  <receiver_MarketParticipant.mRID codingScheme="A01">receiver-20</receiver_MarketParticipant.mRID>
  <receiver_MarketParticipant.marketRole.type>A32</receiver_MarketParticipant.marketRole.type>
  <createdDateTime>2026-10-15T11:55:00Z</createdDateTime>
  <time_Period.timeInterval>
    <start>2026-10-15T12:00Z</start>
    <end>2026-10-16T12:00Z</end>
  </time_Period.timeInterval>
  <TimeSeries>
    <mRID>series-456</mRID>
    <businessType>A01</businessType>
    <in_Domain.mRID codingScheme="A01">10Y1001A1001A82H</in_Domain.mRID>
    <MktPSRType><psrType>{psr_type}</psrType></MktPSRType>
    <Period>
      <timeInterval>
        <start>2026-10-15T12:00Z</start>
        <end>2026-10-15T13:00Z</end>
      </timeInterval>
      <resolution>{resolution}</resolution>
      <Point><position>1</position><quantity>{quantity}</quantity></Point>
      <Point><position>2</position><quantity>102.5</quantity></Point>
      <Point><position>3</position><quantity>103.5</quantity></Point>
      <Point><position>4</position><quantity>104.5</quantity></Point>
    </Period>
  </TimeSeries>
</GL_MarketDocument>
"""


class MockRawClient:
    def __init__(self, responses=None, failures=None):
        self.responses = responses or {}
        self.failures = failures or {}
        self.calls = []

    def _call(self, method, country_code, start, end):
        self.calls.append((method, country_code, start, end))
        if method in self.failures:
            raise self.failures[method]
        return self.responses[method]

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
    return {
        "query_load_forecast": _xml(document_type="A65", psr_type="B20"),
        "query_wind_and_solar_forecast": _xml(),
        "query_intraday_wind_and_solar_forecast": _xml(process_type="A40"),
        "query_generation_forecast": _xml(document_type="A71", psr_type="B20"),
    }


def test_raw_xml_parser_extracts_document_and_series_metadata_only():
    summary = parse_forecast_xml(
        _xml(),
        endpoint="wind_and_solar_forecast",
        acquired_at_utc=ACQUIRED.isoformat(),
    )

    assert summary["xml_root_element"] == "GL_MarketDocument"
    assert summary["document"] == {
        "identifier": "document-123",
        "revision_number": "2",
        "created_at_utc": "2026-10-15T11:55:00+00:00",
        "created_datetime_timezone_valid": True,
        "process_type": "A01",
        "document_type": "A69",
        "sender": {
            "value": "sender-10",
            "coding_scheme": "A01",
            "role": "A04",
        },
        "receiver": {
            "value": "receiver-20",
            "coding_scheme": "A01",
            "role": "A32",
        },
        "domains": [],
        "time_interval": {
            "start_utc": "2026-10-15T12:00:00+00:00",
            "end_utc": "2026-10-16T12:00:00+00:00",
        },
    }
    series = summary["time_series"][0]
    assert series["identifier"] == "series-456"
    assert series["psr_type"] == "B16"
    assert series["domains"] == [
        {
            "xml_element": "in_Domain.mRID",
            "value": "10Y1001A1001A82H",
            "coding_scheme": "A01",
        }
    ]
    assert series["periods"][0] == {
        "start_utc": "2026-10-15T12:00:00+00:00",
        "end_utc": "2026-10-15T13:00:00+00:00",
        "resolution": "PT15M",
        "point_count": 4,
        "position_min": 1,
        "position_max": 4,
        "duplicate_positions": 0,
        "first_target_timestamp_utc": "2026-10-15T12:00:00+00:00",
        "last_target_timestamp_utc": "2026-10-15T12:45:00+00:00",
    }
    rendered = json.dumps(summary)
    assert "101.5" not in rendered
    assert "quantity" not in rendered.casefold()
    assert summary["raw_xml_persisted"] is False


def test_revision_and_creation_time_are_not_overclaimed_as_publication_time():
    summary = parse_forecast_xml(
        _xml(), endpoint="wind_and_solar_forecast", acquired_at_utc=ACQUIRED.isoformat()
    )
    assessment = summary["provenance_assessment"]

    assert assessment["source_creation_time_exposed"] is True
    assert assessment["revision_number_exposed"] is True
    assert assessment["multiple_revision_identity_supported"] is True
    assert assessment["multiple_revisions_observed_in_this_response"] is False
    assert assessment["created_datetime_is_proven_api_publication_time"] is False
    assert assessment["safe_as_sole_vintage_identity"] is False
    assert assessment["store_source_created_at_utc"] is True
    assert assessment["store_acquired_at_utc"] is True


def test_each_endpoint_is_isolated_and_errors_never_include_secret_details():
    secret = "token-must-not-be-written"
    client = MockRawClient(
        _responses(), failures={"query_wind_and_solar_forecast": RuntimeError(secret)}
    )
    report = probe_xml_endpoints(
        client,
        START,
        END,
        acquired_at_factory=lambda: ACQUIRED,
    )

    assert [call[0] for call in client.calls] == [item[1] for item in ENDPOINTS]
    assert all(call[1] == "DE_LU" for call in client.calls)
    failed = report["endpoints"]["wind_and_solar_forecast"]
    assert failed["status"] == "error"
    assert failed["error_type"] == "RuntimeError"
    assert report["endpoints"]["generation_forecast"]["status"] == "success"
    assert secret not in json.dumps(report)


def test_writer_rejects_credentials_and_outside_paths(tmp_path, monkeypatch):
    import scripts.probe_entsoe_forecast_xml as probe

    approved = tmp_path / "artifacts/probes/entsoe_forecast_xml"
    monkeypatch.setattr(probe, "OUTPUT_DIR", approved)
    output = approved / "metadata_summary.json"
    secret = "protected-entsoe-token"
    report = probe_xml_endpoints(
        MockRawClient(_responses()),
        START,
        END,
        acquired_at_factory=lambda: ACQUIRED,
    )
    write_summary(report, output, secret_values=(secret,))

    content = output.read_text(encoding="utf-8")
    assert secret not in content
    assert "raw_xml" not in content or '"raw_xml_persisted": false' in content
    with pytest.raises(ValueError, match="must remain under"):
        write_summary(report, tmp_path / "outside.json")
    with pytest.raises(ValueError, match="protected value"):
        write_summary({"unsafe": secret}, output, secret_values=(secret,))


def test_raw_quantity_content_is_not_retained_even_if_it_looks_like_a_secret():
    secret = "forecast-value-that-must-not-survive"
    summary = parse_forecast_xml(
        _xml(quantity=secret),
        endpoint="wind_and_solar_forecast",
        acquired_at_utc=ACQUIRED.isoformat(),
    )

    assert secret not in json.dumps(summary)


def test_invalid_timezone_and_non_de_lu_scope_fail_safely():
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_forecast_xml(
            _xml(),
            endpoint="wind_and_solar_forecast",
            acquired_at_utc="2026-10-15T12:30:00",
        )
    with pytest.raises(ValueError, match="restricted to DE_LU"):
        probe_xml_endpoints(
            MockRawClient(_responses()),
            START,
            END,
            country_code="FR",
            acquired_at_factory=lambda: ACQUIRED,
        )
