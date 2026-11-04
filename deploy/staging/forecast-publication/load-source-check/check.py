"""Fixed-scope source comparison core; no CLI, credential lookup or file access.

The future reviewed host adapter must supply held snapshot bytes and an approved
secret-provider callback. Importing this module performs no requests.
"""
import csv
import datetime as dt
import hashlib
import http.client
import io
import math
import time
import urllib.parse
import xml.etree.ElementTree as ET

UTC = dt.timezone.utc
HOST = "web-api.tp.entsoe.eu"
AREA = "10Y1001A1001A82H"
START = dt.datetime(2026, 11, 3, 15, tzinfo=UTC)
END = START + dt.timedelta(hours=1)
TARGETS = tuple(START + dt.timedelta(minutes=m) for m in (15, 30, 45))
BODY_LIMIT = 2_000_000
SNAPSHOT_LIMIT = 32_000_000


class EvidenceError(ValueError):
    """Messages are fixed cause codes, never provider exception strings."""


def require(ok, code):
    if not ok:
        raise EvidenceError(code)


def utc(text):
    value = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    require(value.tzinfo is not None, "TIMEZONE_MISSING")
    return value.astimezone(UTC)


def source_rows(raw):
    require(isinstance(raw, bytes) and len(raw) <= BODY_LIMIT, "SOURCE_BODY_BOUND")
    require(b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(), "XML_DECLARATION")
    root = ET.fromstring(raw)
    # Only explicit no-matching-data acknowledgements mean ABSENT. Other
    # acknowledgements, including authentication failures, are request failures.
    if root.tag.rsplit("}", 1)[-1] == "Acknowledgement_MarketDocument":
        codes = [r.findtext("{*}code") for r in root.findall("{*}Reason")]
        require(codes == ["999"] and "no matching data" in "".join(root.itertext()).lower(), "SOURCE_ACK_FAILURE")
        return {}, "NO_MATCHING_DATA"
    require(root.findtext("{*}type") == "A65", "DOCUMENT_TYPE")
    require(root.findtext("{*}process.processType") == "A16", "PROCESS_TYPE")
    series = root.findall("{*}TimeSeries")
    require(0 < len(series) <= 8, "SERIES_COUNT")
    rows = {}
    for item in series:
        require(item.findtext("{*}outBiddingZone_Domain.mRID") == AREA, "AREA")
        require(item.findtext("{*}quantity_Measure_Unit.name") == "MAW", "UNIT")
        curve = item.findtext("{*}curveType")
        require(curve in ("A01", "A03"), "CURVE_TYPE")
        periods = item.findall("{*}Period")
        require(0 < len(periods) <= 32, "PERIOD_COUNT")
        for period in periods:
            first = utc(period.findtext("{*}timeInterval/{*}start"))
            last = utc(period.findtext("{*}timeInterval/{*}end"))
            require(period.findtext("{*}resolution") == "PT15M", "RESOLUTION_MISMATCH")
            require(first.minute % 15 == 0 and first.second == first.microsecond == 0, "PERIOD_GRID")
            slots = (last - first).total_seconds() / 900
            require(0 < slots <= 192 and slots.is_integer(), "PERIOD_BOUND")
            points = period.findall("{*}Point")
            require(len(points) <= slots, "POINT_COUNT")
            values = {}
            for point in points:
                position = int(point.findtext("{*}position"))
                require(1 <= position <= slots and position not in values, "POINT_POSITION")
                try:
                    value = float(point.findtext("{*}quantity"))
                    values[position] = math.isfinite(value)
                except (TypeError, ValueError):
                    values[position] = False
            # A03 declared blocks carry to the next position / period end;
            # A01 gaps remain absent. Never fill before an A03 first point.
            carried = None
            for position in range(1, int(slots) + 1):
                if position in values:
                    carried = values[position]
                valid = values.get(position) if curve == "A01" else carried
                stamp = first + dt.timedelta(minutes=15 * (position - 1))
                if START <= stamp < END and valid is not None:
                    require(stamp not in rows, "DUPLICATE_SOURCE")
                    rows[stamp] = valid
    return rows, "OBSERVATIONS"


def snapshot_rows(raw):
    require(isinstance(raw, bytes) and len(raw) <= SNAPSHOT_LIMIT, "SNAPSHOT_BOUND")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    require(reader.fieldnames is not None and {"timestamp", "load_mw"} <= set(reader.fieldnames), "SNAPSHOT_SCHEMA")
    rows = {}
    latest = None
    for count, row in enumerate(reader, 1):
        require(count <= 1_000_000, "SNAPSHOT_ROW_BOUND")
        stamp = utc(row["timestamp"])
        latest = stamp if latest is None else max(stamp, latest)
        if stamp not in TARGETS:
            continue
        require(stamp not in rows, "DUPLICATE_SNAPSHOT")
        try:
            rows[stamp] = math.isfinite(float(row["load_mw"]))
        except (ValueError, TypeError):
            rows[stamp] = False
    require(latest is not None, "EMPTY_SNAPSHOT")
    return rows, latest


def compare(source, snapshot, now, historical_start):
    observed, source_code = source_rows(source)
    stored, latest = snapshot_rows(snapshot)
    require(now.tzinfo is not None and historical_start.tzinfo is not None, "TIMEZONE_MISSING")
    end = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    start = max(historical_start, latest - dt.timedelta(hours=48))
    def state(rows, stamp):
        return "PRESENT" if rows.get(stamp) is True else "INCOMPLETE" if stamp in rows else "ABSENT"
    return {
        "status": "CHECKED", "source_code": source_code,
        "observed_at_utc": now.astimezone(UTC).isoformat(),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
        "query_start_utc": start.isoformat(), "query_end_exclusive_utc": end.isoformat(),
        "targets": [{"timestamp": stamp.isoformat(), "source": state(observed, stamp),
                     "snapshot": state(stored, stamp),
                     "normal_overlap_revisits": start <= stamp < end} for stamp in TARGETS],
        "historical_source_availability": "UNVERIFIED",
        "ingestion_cause": "UNVERIFIED",
    }


def sanitized_compare(source, snapshot, now, historical_start):
    """Only this result may leave the future host adapter; no raw exceptions."""
    try:
        return compare(source, snapshot, now, historical_start)
    except Exception as error:
        allowed = {"SOURCE_BODY_BOUND", "XML_DECLARATION", "SOURCE_ACK_FAILURE",
                   "DOCUMENT_TYPE", "PROCESS_TYPE", "SERIES_COUNT", "AREA", "UNIT",
                   "CURVE_TYPE", "PERIOD_COUNT", "RESOLUTION_MISMATCH", "PERIOD_GRID",
                   "PERIOD_BOUND", "POINT_COUNT", "POINT_POSITION", "DUPLICATE_SOURCE",
                   "SNAPSHOT_BOUND", "SNAPSHOT_SCHEMA", "SNAPSHOT_ROW_BOUND",
                   "DUPLICATE_SNAPSHOT", "EMPTY_SNAPSHOT", "TIMEZONE_MISSING"}
        code = str(error) if isinstance(error, EvidenceError) and str(error) in allowed else "MALFORMED_EVIDENCE"
        return {"status": "UNVERIFIED", "cause": code}


def request_source(secret_provider):
    """One fixed TLS GET. Future outer supervisor must impose total time bound.

    Never pass a production application import as provider in an elevated process.
    This function is not a remote runner or an approved credential bridge.
    """
    connection = None
    try:
        token = secret_provider("ENTSOE_API_KEY")
        require(isinstance(token, str) and 0 < len(token) <= 4096, "AUTH_UNAVAILABLE")
        params = {"securityToken": token, "documentType": "A65", "processType": "A16",
                  "outBiddingZone_Domain": AREA, "out_Domain": AREA,
                  "periodStart": "202611031500", "periodEnd": "202611031600"}
        connection = http.client.HTTPSConnection(HOST, timeout=5)
        started = time.monotonic()
        connection.request("GET", "/api?" + urllib.parse.urlencode(params))
        response = connection.getresponse()
        require(response.status == 200, "SOURCE_HTTP_FAILURE")
        size = response.getheader("Content-Length")
        require(size is None or (size.isdecimal() and int(size) <= BODY_LIMIT), "SOURCE_BODY_BOUND")
        require(response.getheader("Content-Encoding", "identity") == "identity", "SOURCE_ENCODING")
        chunks = []
        total = 0
        while True:
            require(time.monotonic() - started < 20, "SOURCE_DEADLINE")
            chunk = response.read1(min(16384, BODY_LIMIT + 1 - total))
            total += len(chunk)
            require(total <= BODY_LIMIT, "SOURCE_BODY_BOUND")
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), None
    except Exception as error:
        # Do not return HTTP exceptions, URLs, response contents or provider errors.
        allowed = {"AUTH_UNAVAILABLE", "SOURCE_HTTP_FAILURE", "SOURCE_BODY_BOUND",
                   "SOURCE_ENCODING", "SOURCE_DEADLINE"}
        code = str(error) if isinstance(error, EvidenceError) and str(error) in allowed else "SOURCE_REQUEST_FAILURE"
        return None, {"status": "REQUEST_FAILURE", "cause": code}
    finally:
        if connection is not None:
            connection.close()
