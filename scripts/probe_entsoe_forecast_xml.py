"""Read-only raw-XML metadata probe for ENTSO-E DE_LU forecasts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoeRawClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from powerflow_secrets import SecretConfigurationError, get_secret  # noqa: E402


COUNTRY_CODE = "DE_LU"
OUTPUT_DIR = PROJECT_ROOT / "artifacts/probes/entsoe_forecast_xml"
OUTPUT_PATH = OUTPUT_DIR / "metadata_summary.json"
ENDPOINTS = (
    ("load_forecast", "query_load_forecast", "A65", "A01"),
    ("wind_and_solar_forecast", "query_wind_and_solar_forecast", "A69", "A01"),
    (
        "intraday_wind_and_solar_forecast",
        "query_intraday_wind_and_solar_forecast",
        "A69",
        "A40",
    ),
    ("generation_forecast", "query_generation_forecast", "A71", "A01"),
)
DOCUMENT_XML_ELEMENTS = {
    "identifier": "mRID",
    "revision_number": "revisionNumber",
    "document_type": "type",
    "process_type": "process.processType",
    "created_at_utc": "createdDateTime",
    "sender_identifier": "sender_MarketParticipant.mRID",
    "sender_role": "sender_MarketParticipant.marketRole.type",
    "receiver_identifier": "receiver_MarketParticipant.mRID",
    "receiver_role": "receiver_MarketParticipant.marketRole.type",
    "time_interval": "time_Period.timeInterval",
}
SERIES_XML_ELEMENTS = {
    "identifier": "mRID",
    "business_type": "businessType",
    "psr_type": "MktPSRType/psrType",
    "period": "Period",
    "period_time_interval": "timeInterval",
    "resolution": "resolution",
    "point_position": "Point/position",
}
_ISO_RESOLUTION = re.compile(
    r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ElementTree.Element, *names: str) -> ElementTree.Element | None:
    wanted = set(names)
    return next(
        (child for child in element if _local_name(child.tag) in wanted),
        None,
    )


def _children(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in element if _local_name(child.tag) == name]


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _child_text(element: ElementTree.Element, *names: str) -> str | None:
    return _text(_child(element, *names))


def _utc_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if timestamp.tzinfo is None:
        return None
    return timestamp.tz_convert("UTC").isoformat()


def _utc_timestamp(value: Any, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"{name} must include an explicit timezone.")
    return timestamp.tz_convert("UTC")


def _duration(value: str | None) -> timedelta | None:
    match = _ISO_RESOLUTION.fullmatch(value or "")
    if not match:
        return None
    parts = {key: int(raw or 0) for key, raw in match.groupdict().items()}
    duration = timedelta(**parts)
    return duration if duration.total_seconds() > 0 else None


def _identifier(element: ElementTree.Element | None) -> dict[str, str | None]:
    return {
        "value": _text(element),
        "coding_scheme": element.attrib.get("codingScheme") if element is not None else None,
    }


def _domain_identifiers(element: ElementTree.Element) -> list[dict[str, str | None]]:
    domains = []
    for child in element:
        name = _local_name(child.tag)
        if name.endswith(".mRID") and ("Domain" in name or "BiddingZone" in name):
            domains.append({"xml_element": name, **_identifier(child)})
    return domains


def _time_interval(
    parent: ElementTree.Element,
    *container_names: str,
) -> dict[str, str | None]:
    container = _child(parent, *container_names)
    return {
        "start_utc": _utc_iso(_child_text(container, "start")) if container is not None else None,
        "end_utc": _utc_iso(_child_text(container, "end")) if container is not None else None,
    }


def _target_timestamp(
    period_start: str | None,
    resolution: str | None,
    position: int | None,
) -> str | None:
    if period_start is None or position is None or position < 1:
        return None
    delta = _duration(resolution)
    if delta is None:
        return None
    start = pd.Timestamp(period_start)
    return (start + (position - 1) * delta).isoformat()


def _parse_position(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _parse_period(period: ElementTree.Element) -> dict[str, Any]:
    interval = _time_interval(period, "timeInterval")
    resolution = _child_text(period, "resolution")
    positions = [
        _parse_position(_child_text(point, "position"))
        for point in _children(period, "Point")
    ]
    valid_positions = [position for position in positions if position is not None]
    first = min(valid_positions, default=None)
    last = max(valid_positions, default=None)
    return {
        "start_utc": interval["start_utc"],
        "end_utc": interval["end_utc"],
        "resolution": resolution,
        "point_count": len(positions),
        "position_min": first,
        "position_max": last,
        "duplicate_positions": len(valid_positions) - len(set(valid_positions)),
        "first_target_timestamp_utc": _target_timestamp(
            interval["start_utc"], resolution, first
        ),
        "last_target_timestamp_utc": _target_timestamp(
            interval["start_utc"], resolution, last
        ),
    }


def _parse_series(series: ElementTree.Element) -> dict[str, Any]:
    psr = _child(series, "MktPSRType")
    return {
        "identifier": _child_text(series, "mRID"),
        "business_type": _child_text(series, "businessType"),
        "psr_type": _child_text(psr, "psrType") if psr is not None else None,
        "domains": _domain_identifiers(series),
        "periods": [_parse_period(period) for period in _children(series, "Period")],
    }


def parse_forecast_xml(
    xml_text: str,
    *,
    endpoint: str,
    acquired_at_utc: str,
) -> dict[str, Any]:
    """Extract provenance metadata without retaining forecast quantities."""
    root = ElementTree.fromstring(xml_text)
    created_raw = _child_text(root, "createdDateTime")
    sender = _child(root, "sender_MarketParticipant.mRID")
    receiver = _child(root, "receiver_MarketParticipant.mRID")
    document_interval = _time_interval(
        root,
        "time_Period.timeInterval",
        "period.timeInterval",
    )
    time_series = [_parse_series(series) for series in _children(root, "TimeSeries")]
    revision_number = _child_text(root, "revisionNumber")
    created_at = _utc_iso(created_raw)
    acquired_at = _utc_iso(acquired_at_utc)
    if acquired_at is None:
        raise ValueError("acquired_at_utc must be a timezone-aware timestamp.")

    return {
        "endpoint": endpoint,
        "xml_root_element": _local_name(root.tag),
        "xml_namespace": root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else None,
        "document": {
            "identifier": _child_text(root, "mRID"),
            "revision_number": revision_number,
            "created_at_utc": created_at,
            "created_datetime_timezone_valid": created_at is not None,
            "process_type": _child_text(root, "process.processType"),
            "document_type": _child_text(root, "type"),
            "sender": {
                **_identifier(sender),
                "role": _child_text(root, "sender_MarketParticipant.marketRole.type"),
            },
            "receiver": {
                **_identifier(receiver),
                "role": _child_text(root, "receiver_MarketParticipant.marketRole.type"),
            },
            "domains": _domain_identifiers(root),
            "time_interval": document_interval,
        },
        "acquired_at_utc": acquired_at,
        "time_series_count": len(time_series),
        "time_series": time_series,
        "provenance_assessment": {
            "source_creation_time_exposed": created_at is not None,
            "revision_number_exposed": revision_number is not None,
            "multiple_revisions_observed_in_this_response": False,
            "multiple_revision_identity_supported": revision_number is not None,
            "created_datetime_is_source_document_creation_time": created_at is not None,
            "created_datetime_is_proven_api_publication_time": False,
            "safe_as_sole_vintage_identity": False,
            "store_source_created_at_utc": created_at is not None,
            "store_acquired_at_utc": True,
            "recommended_vintage_identity_fields": [
                "document.identifier",
                "document.revision_number",
                "document.created_at_utc",
                "acquired_at_utc",
            ],
        },
        "forecast_values_persisted": False,
        "raw_xml_persisted": False,
    }


def _safe_error_metadata(error: Exception) -> dict[str, Any]:
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    return {
        "error_type": type(error).__name__,
        "http_status_code": int(status_code) if status_code is not None else None,
        "error_message": (
            "ENTSO-E raw XML forecast query or parsing failed; "
            "details were omitted for safety."
        ),
    }


def probe_xml_endpoints(
    client: Any,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    country_code: str = COUNTRY_CODE,
    acquired_at_factory: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Query every endpoint independently and return only sanitized metadata."""
    start = _utc_timestamp(start, "start")
    end = _utc_timestamp(end, "end")
    if end <= start:
        raise ValueError("end must be later than start.")
    if country_code != COUNTRY_CODE:
        raise ValueError("The raw XML metadata probe is restricted to DE_LU.")
    now = acquired_at_factory or (lambda: datetime.now(timezone.utc))

    results: dict[str, dict[str, Any]] = {}
    for endpoint, method_name, document_type, process_type in ENDPOINTS:
        result: dict[str, Any] = {
            "status": "error",
            "method": method_name,
            "expected_document_type": document_type,
            "expected_process_type": process_type,
        }
        try:
            method: Callable[..., str] = getattr(client, method_name)
            xml_text = method(country_code, start=start, end=end)
            parsed = parse_forecast_xml(
                xml_text,
                endpoint=endpoint,
                acquired_at_utc=now().astimezone(timezone.utc).isoformat(),
            )
            result.update(status="success", **parsed)
        except Exception as error:  # endpoint isolation is intentional
            result.update(_safe_error_metadata(error))
        results[endpoint] = result

    return {
        "probe_type": "read_only_entsoe_forecast_raw_xml_metadata",
        "country_code": country_code,
        "query_start_utc": start.isoformat(),
        "query_end_utc": end.isoformat(),
        "generated_at_utc": now().astimezone(timezone.utc).isoformat(),
        "document_xml_elements": DOCUMENT_XML_ELEMENTS,
        "time_series_xml_elements": SERIES_XML_ELEMENTS,
        "forecast_values_persisted": False,
        "raw_xml_persisted": False,
        "endpoints": results,
    }


def _assert_sanitized(summary: dict[str, Any], secret_values: Iterable[str]) -> None:
    rendered = json.dumps(summary, sort_keys=True)
    lowered = rendered.casefold()
    prohibited_names = ("securitytoken", "security_token", "api_key", "api key")
    if any(name in lowered for name in prohibited_names):
        raise ValueError("Probe summary contains a prohibited credential field.")
    if any(value and value in rendered for value in secret_values):
        raise ValueError("Probe summary contains a protected value.")


def write_summary(
    summary: dict[str, Any],
    output_path: Path = OUTPUT_PATH,
    *,
    secret_values: Iterable[str] = (),
) -> Path:
    """Atomically write sanitized metadata only beneath the probe directory."""
    output_path = Path(output_path)
    approved = OUTPUT_DIR.resolve()
    resolved = output_path.resolve()
    if resolved != approved and approved not in resolved.parents:
        raise ValueError(
            "Probe output must remain under artifacts/probes/entsoe_forecast_xml/."
        )
    _assert_sanitized(summary, secret_values)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only ENTSO-E DE_LU raw forecast XML metadata probe."
    )
    parser.add_argument(
        "--start",
        help="Inclusive timezone-aware start; defaults to the current UTC day.",
    )
    parser.add_argument(
        "--end",
        help="Exclusive timezone-aware end; defaults to 48 hours after start.",
    )
    args = parser.parse_args()
    start = (
        _utc_timestamp(args.start, "start")
        if args.start
        else pd.Timestamp.now(tz="UTC").floor("D")
    )
    end = _utc_timestamp(args.end, "end") if args.end else start + pd.Timedelta(hours=48)

    load_dotenv(PROJECT_ROOT / ".env")
    try:
        api_key = get_secret("ENTSOE_API_KEY")
    except SecretConfigurationError as error:
        parser.error(str(error))
    client = EntsoeRawClient(
        api_key=api_key,
        retry_count=1,
        retry_delay=0,
        timeout=30,
    )
    try:
        summary = probe_xml_endpoints(client, start, end)
        path = write_summary(summary, secret_values=(api_key,))
    except KeyboardInterrupt:
        parser.error("ENTSO-E XML probe interrupted; request details were omitted.")
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Probe summary written to {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
