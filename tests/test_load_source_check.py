"""Offline source protocol fixtures; never resolve credentials or make requests."""
import ast
import datetime as dt
import importlib.util
import json
from pathlib import Path
import urllib.parse

import pytest

PATH = Path(__file__).resolve().parents[1] / "deploy/staging/forecast-publication/load-source-check/check.py"
spec = importlib.util.spec_from_file_location("load_source_core", PATH)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def xml(positions=(1, 2, 3, 4), curve="A01", resolution="PT15M", value="12345"):
    return (f'<GL_MarketDocument xmlns="urn:test"><type>A65</type><process.processType>A16</process.processType>'
            f'<TimeSeries><outBiddingZone_Domain.mRID>{c.AREA}</outBiddingZone_Domain.mRID>'
            f'<quantity_Measure_Unit.name>MAW</quantity_Measure_Unit.name><curveType>{curve}</curveType>'
            '<Period><timeInterval><start>2026-11-03T16:00:00+01:00</start>'
            '<end>2026-11-03T16:00:00Z</end></timeInterval>'
            f'<resolution>{resolution}</resolution>' + ''.join(
                f'<Point><position>{p}</position><quantity>{value}</quantity></Point>' for p in positions)
            + '</Period></TimeSeries></GL_MarketDocument>').encode()


SNAPSHOT = b"timestamp,load_mw\n2026-11-03T15:00:00Z,12345\n"
NOW = c.utc("2026-11-03T17:00:00Z")
HISTORY = c.utc("2026-01-01T00:00:00Z")


def test_comparison_and_no_values():
    result = c.compare(xml(), SNAPSHOT, NOW, HISTORY)
    assert all(r["source"] == "PRESENT" and r["snapshot"] == "ABSENT" and r["normal_overlap_revisits"] for r in result["targets"])
    assert "12345" not in json.dumps(result)
    assert result["historical_source_availability"] == result["ingestion_cause"] == "UNVERIFIED"


def test_overlap_ages_out_and_end_is_exclusive():
    raw = b"timestamp,load_mw\n2026-11-05T16:00:00Z,1\n"
    assert not any(r["normal_overlap_revisits"] for r in c.compare(xml(), raw, c.utc("2026-11-05T17:00Z"), HISTORY)["targets"])
    assert not any(r["normal_overlap_revisits"] for r in c.compare(xml(), SNAPSHOT, c.START, HISTORY)["targets"])


def test_partial_and_invalid_and_declared_blocks():
    rows, _ = c.source_rows(xml((1, 2)))
    assert c.TARGETS[0] in rows and c.TARGETS[1] not in rows
    assert not any(c.source_rows(xml(value="nan"))[0].values())
    assert len(c.source_rows(xml((1,), curve="A03"))[0]) == 4
    assert c.START not in c.source_rows(xml((2,), curve="A03"))[0]


@pytest.mark.parametrize("raw,code", [
    (xml(resolution="PT60M"), "RESOLUTION_MISMATCH"),
    (xml((1, 1)), "POINT_POSITION"),
    (xml((0,)), "POINT_POSITION"),
    (xml(curve="A02"), "CURVE_TYPE"),
    (xml().replace(b"A65", b"A44"), "DOCUMENT_TYPE"),
    (xml().replace(b"MAW", b"MWH"), "UNIT"),
    (b'<!DOCTYPE x>' + xml(), "XML_DECLARATION"),
    (b'x' * (c.BODY_LIMIT + 1), "SOURCE_BODY_BOUND"),
])
def test_source_rejections(raw, code):
    with pytest.raises(c.EvidenceError, match=code):
        c.source_rows(raw)


def test_no_data_ack_and_auth_failure():
    raw = b'<Acknowledgement_MarketDocument><Reason><code>999</code><text>No matching data found</text></Reason></Acknowledgement_MarketDocument>'
    assert c.source_rows(raw) == ({}, "NO_MATCHING_DATA")
    with pytest.raises(c.EvidenceError, match="SOURCE_ACK_FAILURE"):
        c.source_rows(raw.replace(b'No matching data found', b'Unauthorized token SECRET'))


@pytest.mark.parametrize("raw", [b"SECRET invalid xml", xml().replace(b"2026-11-03T16:00:00+01:00", b"SECRET"), xml().replace(b"<position>1", b"<position>SECRET")])
def test_malformed_evidence_sanitized(raw):
    result = c.sanitized_compare(raw, SNAPSHOT, NOW, HISTORY)
    assert result == {"status": "UNVERIFIED", "cause": "MALFORMED_EVIDENCE"}
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("raw", [b'timestamp,load_mw\n2026-11-03T15:15:00Z,1\n2026-11-03T15:15:00Z,2\n', b'wrong,schema\n'])
def test_snapshot_fails_closed(raw):
    with pytest.raises(c.EvidenceError):
        c.snapshot_rows(raw)


class Response:
    status = 200
    def __init__(self, body=b"safe", headers=None):
        self.body, self.headers = body, headers or {}
    def getheader(self, name, default=None):
        return self.headers.get(name, default)
    def read1(self, count):
        result, self.body = self.body[:count], self.body[count:]
        return result


def connection(monkeypatch, response):
    calls = []
    class Fake:
        def __init__(self, host, timeout):
            calls.append((host, timeout))
        def request(self, method, path):
            calls.append((method, path))
        def getresponse(self):
            return response
        def close(self):
            calls.append("closed")
    monkeypatch.setattr(c.http.client, "HTTPSConnection", Fake)
    return calls


def test_exact_endpoint_auth_window_one_request(monkeypatch):
    calls = connection(monkeypatch, Response())
    names = []
    def secret(name):
        names.append(name)
        return "SECRET&value"
    assert c.request_source(secret) == (b"safe", None)
    assert names == ["ENTSOE_API_KEY"]
    assert calls[0] == (c.HOST, 5) and calls[1][0] == "GET"
    parsed = urllib.parse.urlsplit(calls[1][1])
    assert parsed.path == "/api"
    assert urllib.parse.parse_qs(parsed.query) == {k: [v] for k, v in {
        "securityToken": "SECRET&value", "documentType": "A65", "processType": "A16",
        "outBiddingZone_Domain": c.AREA, "out_Domain": c.AREA,
        "periodStart": "202611031500", "periodEnd": "202611031600"}.items()}
    assert len(calls) == 3


@pytest.mark.parametrize("response,code", [
    (Response(headers={"Content-Length": "2000001"}), "SOURCE_BODY_BOUND"),
    (Response(b'x' * (c.BODY_LIMIT + 1)), "SOURCE_BODY_BOUND"),
    (Response(headers={"Content-Encoding": "gzip"}), "SOURCE_ENCODING"),
])
def test_transport_bounds(monkeypatch, response, code):
    calls = connection(monkeypatch, response)
    assert c.request_source(lambda _: "SECRET")[1] == {"status": "REQUEST_FAILURE", "cause": code}
    assert len(calls) == 3  # one request and close, no retry


def test_redirect_never_followed(monkeypatch):
    response = Response(headers={"Location": "https://unapproved.invalid/SECRET"})
    response.status = 302
    calls = connection(monkeypatch, response)
    assert c.request_source(lambda _: "SECRET")[1]["cause"] == "SOURCE_HTTP_FAILURE"
    assert len(calls) == 3


@pytest.mark.parametrize("error", [RuntimeError("SECRET"), c.EvidenceError("SECRET")])
def test_provider_failure_redacted_without_network(monkeypatch, error):
    calls = connection(monkeypatch, Response())
    def provider(_):
        raise error
    assert c.request_source(provider)[1] == {"status": "REQUEST_FAILURE", "cause": "SOURCE_REQUEST_FAILURE"}
    assert not calls


def test_transport_timeout_no_retry(monkeypatch):
    calls = connection(monkeypatch, Response())
    monkeypatch.setattr(c.time, "monotonic", iter([0, 21]).__next__)
    assert c.request_source(lambda _: "SECRET")[1]["cause"] == "SOURCE_DEADLINE"
    assert len(calls) == 3


def test_read_only_core_and_python39():
    tree = ast.parse(PATH.read_text(), feature_version=(3, 9))
    imports = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}
    assert not imports & {"subprocess", "os", "sys", "boto3", "requests", "sqlite3"}
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not calls & {"open", "exec", "eval", "compile", "__import__"}
