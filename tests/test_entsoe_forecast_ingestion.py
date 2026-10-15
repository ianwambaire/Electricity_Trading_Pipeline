from pathlib import Path

import pandas as pd
import pytest

from ingestion.fetch_entsoe_forecasts import (
    ENTSOE_FORECAST_COLUMNS,
    append_entsoe_vintages,
    collect_entsoe_forecast_vintages,
    merge_entsoe_vintages,
    normalize_entsoe_vintages,
    parse_entsoe_forecast_xml,
)


ACQUIRED = pd.Timestamp("2026-10-15T00:05:00Z")
START = pd.Timestamp("2026-10-15T01:00:00Z")
END = pd.Timestamp("2026-10-15T05:00:00Z")


def _series(psr_type=None, *, first_value=100.0, resolution="PT60M"):
    psr = (
        f"<MktPSRType><psrType>{psr_type}</psrType></MktPSRType>"
        if psr_type
        else ""
    )
    points = "".join(
        f"<Point><position>{position}</position>"
        f"<quantity>{first_value + position - 1}</quantity></Point>"
        for position in range(1, 5)
    )
    return f"""
    <TimeSeries>
      <mRID>series-{psr_type or 'aggregate'}</mRID>
      {psr}
      <Period>
        <timeInterval>
          <start>2026-10-15T01:00:00Z</start>
          <end>2026-10-15T05:00:00Z</end>
        </timeInterval>
        <resolution>{resolution}</resolution>
        {points}
      </Period>
    </TimeSeries>
    """


def _xml(
    document_type,
    process_type,
    *,
    revision="1",
    document_id="document-1",
    created="2026-10-15T00:00:00Z",
    first_value=100.0,
):
    if document_type == "A69":
        series = "".join(
            _series(psr, first_value=first_value + offset)
            for psr, offset in (("B16", 0), ("B18", 100), ("B19", 200))
        )
    else:
        # A71 must remain TOTAL_GENERATION even if a misleading PSR is present.
        series = _series(
            "B16" if document_type == "A71" else None,
            first_value=first_value,
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">
  <mRID>{document_id}</mRID>
  <revisionNumber>{revision}</revisionNumber>
  <type>{document_type}</type>
  <process.processType>{process_type}</process.processType>
  <createdDateTime>{created}</createdDateTime>
  {series}
</GL_MarketDocument>
"""


def _parse(xml, document_type, process_type, acquired=ACQUIRED):
    return parse_entsoe_forecast_xml(
        xml,
        expected_document_type=document_type,
        expected_process_type=process_type,
        acquired_at_utc=acquired,
    )


class MockRawClient:
    def __init__(self):
        self.calls = []

    def _response(self, method, country_code, start, end):
        self.calls.append((method, country_code, start, end))
        responses = {
            "query_load_forecast": _xml("A65", "A01", document_id="load-1"),
            "query_wind_and_solar_forecast": _xml(
                "A69", "A01", document_id="wind-day-1"
            ),
            "query_intraday_wind_and_solar_forecast": _xml(
                "A69", "A40", document_id="wind-intraday-1"
            ),
            "query_generation_forecast": _xml(
                "A71", "A01", document_id="generation-1"
            ),
        }
        return responses[method]

    def query_load_forecast(self, country_code, start, end):
        return self._response("query_load_forecast", country_code, start, end)

    def query_wind_and_solar_forecast(self, country_code, start, end):
        return self._response(
            "query_wind_and_solar_forecast", country_code, start, end
        )

    def query_intraday_wind_and_solar_forecast(self, country_code, start, end):
        return self._response(
            "query_intraday_wind_and_solar_forecast", country_code, start, end
        )

    def query_generation_forecast(self, country_code, start, end):
        return self._response("query_generation_forecast", country_code, start, end)


@pytest.mark.parametrize(
    ("document_type", "process_type", "technologies", "row_count"),
    [
        ("A65", "A01", {"TOTAL_LOAD"}, 4),
        ("A69", "A01", {"SOLAR", "WIND_OFFSHORE", "WIND_ONSHORE"}, 12),
        ("A69", "A40", {"SOLAR", "WIND_OFFSHORE", "WIND_ONSHORE"}, 12),
        ("A71", "A01", {"TOTAL_GENERATION"}, 4),
    ],
)
def test_xml_contract_schema_technology_and_utc_normalization(
    document_type, process_type, technologies, row_count
):
    frame = _parse(_xml(document_type, process_type), document_type, process_type)

    assert tuple(frame.columns) == ENTSOE_FORECAST_COLUMNS
    assert len(frame) == row_count
    assert set(frame["technology"]) == technologies
    assert set(frame["document_type"]) == {document_type}
    assert set(frame["process_type"]) == {process_type}
    assert str(frame["target_timestamp"].dt.tz) == "UTC"
    assert set(frame["collection_issue_time"]) == {ACQUIRED.floor("h")}
    assert (frame["acquired_at_utc"] >= frame["source_created_at_utc"]).all()
    assert sorted(frame["source_horizon_minutes"].unique()) == [
        60.0,
        120.0,
        180.0,
        240.0,
    ]


def test_revision_rows_and_day_ahead_intraday_processes_remain_distinct():
    day_ahead = _parse(_xml("A69", "A01", revision="1"), "A69", "A01")
    revised = _parse(_xml("A69", "A01", revision="2"), "A69", "A01")
    intraday = _parse(_xml("A69", "A40", revision="1"), "A69", "A40")

    combined = merge_entsoe_vintages(day_ahead, pd.concat([revised, intraday]))

    assert len(combined) == 36
    assert set(combined["revision_number"].astype(str)) == {"1", "2"}
    assert set(combined["process_type"]) == {"A01", "A40"}


def test_quarter_hour_resolution_produces_exact_utc_targets():
    xml = _xml("A65", "A01").replace(
        "<resolution>PT60M</resolution>",
        "<resolution>PT15M</resolution>",
    )
    frame = _parse(xml, "A65", "A01")

    assert set(frame["resolution"]) == {"PT15M"}
    assert frame["target_timestamp"].tolist() == list(
        pd.date_range("2026-10-15T01:00:00Z", periods=4, freq="15min")
    )
    assert frame["source_horizon_minutes"].tolist() == [
        60.0,
        75.0,
        90.0,
        105.0,
    ]


def test_same_source_vintage_is_idempotent_but_conflicts_are_rejected():
    original = _parse(_xml("A65", "A01"), "A65", "A01")
    reacquired = _parse(
        _xml("A65", "A01"),
        "A65",
        "A01",
        acquired=pd.Timestamp("2026-10-15T00:10:00Z"),
    )
    merged = merge_entsoe_vintages(original, reacquired)

    assert len(merged) == 4
    assert set(merged["acquired_at_utc"]) == {ACQUIRED}

    conflicting = reacquired.copy()
    conflicting.loc[0, "value_mw"] += 1
    with pytest.raises(ValueError, match="Conflicting ENTSO-E values"):
        merge_entsoe_vintages(original, conflicting)


def test_invalid_timestamp_horizon_and_numeric_values_fail_safely():
    with pytest.raises(ValueError, match="explicit timezone"):
        _parse(
            _xml("A65", "A01", created="2026-10-15T00:00:00"),
            "A65",
            "A01",
        )
    with pytest.raises(ValueError, match="non-negative"):
        _parse(
            _xml("A65", "A01", created="2026-10-15T01:30:00Z"),
            "A65",
            "A01",
            acquired=pd.Timestamp("2026-10-15T02:05:00Z"),
        )
    with pytest.raises(ValueError, match="finite"):
        _parse(
            _xml("A65", "A01", first_value=float("nan")),
            "A65",
            "A01",
        )


def test_acquisition_must_follow_source_creation_without_clock_skew_tolerance():
    with pytest.raises(ValueError, match="must not precede"):
        _parse(
            _xml("A65", "A01", created="2026-10-15T00:05:01Z"),
            "A65",
            "A01",
            acquired=pd.Timestamp("2026-10-15T00:05:00Z"),
        )


def test_collection_issue_time_is_distinct_from_source_and_acquisition_times():
    issue = pd.Timestamp("2026-10-15T00:00:00Z")
    acquired = pd.Timestamp("2026-10-15T00:07:00Z")
    frame = parse_entsoe_forecast_xml(
        _xml("A65", "A01", created="2026-10-15T00:03:00Z"),
        expected_document_type="A65",
        expected_process_type="A01",
        collection_issue_time=issue,
        acquired_at_utc=acquired,
    )

    assert set(frame["collection_issue_time"]) == {issue}
    assert set(frame["source_created_at_utc"]) == {
        pd.Timestamp("2026-10-15T00:03:00Z")
    }
    assert set(frame["acquired_at_utc"]) == {acquired}


def test_collection_writes_only_new_forecast_paths_and_expected_sample_counts(tmp_path):
    raw = tmp_path / "data/raw/entsoe"
    raw.mkdir(parents=True)
    observed = {
        name: raw / name for name in ("prices.csv", "load.csv", "generation.csv")
    }
    for path in observed.values():
        path.write_text("protected observed data\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in observed.values()}
    forecast_dir = raw / "forecasts"
    paths = {
        "load": forecast_dir / "load_forecast_vintages.csv",
        "wind_solar": forecast_dir / "wind_solar_forecast_vintages.csv",
        "generation": forecast_dir / "generation_forecast_vintages.csv",
    }

    client = MockRawClient()
    result = collect_entsoe_forecast_vintages(
        START,
        END,
        client=client,
        acquired_at_utc=ACQUIRED,
        output_paths=paths,
    )

    assert result["load"]["rows_after"] == 4
    assert result["wind_solar"]["rows_after"] == 24
    assert result["generation"]["rows_after"] == 4
    assert result["endpoints"] == {
        "load": 4,
        "wind_solar_day_ahead": 12,
        "wind_solar_intraday": 12,
        "generation": 4,
    }
    assert len(client.calls) == 4
    assert all(call[1] == "DE_LU" for call in client.calls)
    assert before == {path: path.read_bytes() for path in observed.values()}
    first_files = {path: path.read_bytes() for path in paths.values()}

    second = collect_entsoe_forecast_vintages(
        START,
        END,
        client=MockRawClient(),
        acquired_at_utc=pd.Timestamp("2026-10-15T00:15:00Z"),
        output_paths=paths,
    )
    assert second["load"]["new_rows"] == 0
    assert second["wind_solar"]["new_rows"] == 0
    assert second["generation"]["new_rows"] == 0
    assert first_files == {path: path.read_bytes() for path in paths.values()}


def test_sequential_provider_responses_get_distinct_post_response_acquisitions(
    tmp_path,
):
    acquisition_times = iter(
        pd.date_range("2026-10-15T00:05:00Z", periods=4, freq="min")
    )
    client = MockRawClient()
    responses_seen = []

    def acquisition_clock():
        responses_seen.append(len(client.calls))
        return next(acquisition_times)

    paths = {
        "load": tmp_path / "load_forecast_vintages.csv",
        "wind_solar": tmp_path / "wind_solar_forecast_vintages.csv",
        "generation": tmp_path / "generation_forecast_vintages.csv",
    }

    result = collect_entsoe_forecast_vintages(
        START,
        END,
        client=client,
        collection_issue_time="2026-10-15T00:00:00Z",
        acquisition_clock=acquisition_clock,
        output_paths=paths,
    )

    assert list(result["endpoint_acquired_at_utc"].values()) == [
        "2026-10-15T00:05:00+00:00",
        "2026-10-15T00:06:00+00:00",
        "2026-10-15T00:07:00+00:00",
        "2026-10-15T00:08:00+00:00",
    ]
    assert responses_seen == [1, 2, 3, 4]
    wind = pd.read_csv(paths["wind_solar"])
    assert set(wind["acquired_at_utc"]) == {
        "2026-10-15 00:06:00+00:00",
        "2026-10-15 00:07:00+00:00",
    }


def test_legacy_schema_remains_readable_without_inventing_collection_issue_time():
    current = _parse(_xml("A65", "A01"), "A65", "A01")
    legacy = current.drop(columns="collection_issue_time").rename(
        columns={"source_horizon_minutes": "horizon_minutes"}
    )
    legacy.loc[:, "acquired_at_utc"] = pd.Timestamp("2026-10-14T23:59:59Z")

    normalized = normalize_entsoe_vintages(legacy)

    assert normalized["collection_issue_time"].isna().all()
    assert "source_horizon_minutes" in normalized
    assert "horizon_minutes" not in normalized
    assert set(normalized["document_id"]) == {"document-1"}


def test_idempotent_reacquisition_does_not_rewrite_legacy_file(tmp_path):
    incoming = _parse(_xml("A65", "A01"), "A65", "A01")
    legacy = incoming.drop(columns="collection_issue_time").rename(
        columns={"source_horizon_minutes": "horizon_minutes"}
    )
    path = tmp_path / "load_forecast_vintages.csv"
    legacy.to_csv(path, index=False)
    before = path.read_bytes()

    result = append_entsoe_vintages(path, incoming)

    assert result["new_rows"] == 0
    assert path.read_bytes() == before


def test_new_revision_explicitly_migrates_legacy_rows_without_changing_identity(
    tmp_path,
):
    original = _parse(
        _xml("A65", "A01", revision="1"), "A65", "A01"
    )
    legacy = original.drop(columns="collection_issue_time").rename(
        columns={"source_horizon_minutes": "horizon_minutes"}
    )
    path = tmp_path / "load_forecast_vintages.csv"
    legacy.to_csv(path, index=False)
    revised = _parse(
        _xml("A65", "A01", revision="2"),
        "A65",
        "A01",
        acquired=ACQUIRED + pd.Timedelta(minutes=1),
    )

    result = append_entsoe_vintages(path, revised)
    saved = normalize_entsoe_vintages(
        pd.read_csv(path, dtype={"revision_number": "string"})
    )

    assert result["new_rows"] == 4
    assert len(saved) == 8
    assert set(saved["revision_number"].astype(str)) == {"1", "2"}
    assert saved.loc[
        saved["revision_number"].astype(str).eq("1"), "collection_issue_time"
    ].isna().all()
    assert saved.loc[
        saved["revision_number"].astype(str).eq("2"), "collection_issue_time"
    ].notna().all()


def test_atomic_append_rejects_observed_filename(tmp_path):
    frame = _parse(_xml("A65", "A01"), "A65", "A01")
    observed_path = tmp_path / "load.csv"
    observed_path.write_text("do not replace\n", encoding="utf-8")

    with pytest.raises(ValueError, match="observed-data path"):
        append_entsoe_vintages(observed_path, frame)
    assert observed_path.read_text(encoding="utf-8") == "do not replace\n"


def test_query_failure_does_not_expose_client_error_or_write_files(tmp_path):
    secret = "security-token-must-not-escape"

    class FailingClient(MockRawClient):
        def query_load_forecast(self, country_code, start, end):
            raise RuntimeError(secret)

    paths = {
        "load": tmp_path / "load_forecast_vintages.csv",
        "wind_solar": tmp_path / "wind_solar_forecast_vintages.csv",
        "generation": tmp_path / "generation_forecast_vintages.csv",
    }
    with pytest.raises(RuntimeError, match="error type: RuntimeError") as error:
        collect_entsoe_forecast_vintages(
            START,
            END,
            client=FailingClient(),
            acquired_at_utc=ACQUIRED,
            output_paths=paths,
        )

    assert secret not in str(error.value)
    assert not any(path.exists() for path in paths.values())
