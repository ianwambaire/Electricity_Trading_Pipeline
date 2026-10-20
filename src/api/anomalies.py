"""Public observations from the active persisted detector; never import its script."""
from __future__ import annotations

import csv
import statistics
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import HTTPException

from .market_data import PublicModel, _number, _timestamp


class AnomalyEvent(PublicModel):
    timestamp: datetime
    price_eur_mwh: float
    load_mw: float


class AnomalySummary(PublicModel):
    report_status: Literal["available", "empty"]
    count: int
    total_report_rows: int
    first_event: datetime | None
    last_event: datetime | None
    minimum_price: float | None
    maximum_price: float | None
    average_load_mw: float | None
    method: str = "Isolation Forest; price and load; contamination 0.01; seed 42"
    provenance: str = "Active persisted historical anomaly report; detector not executed by this API"
    limitation: str = "No numeric anomaly score or generation time is recorded. Events are statistical outliers, not verified faults, manipulation, trades, or forecast errors."


class AnomalyEvents(PublicModel):
    matched_rows: int
    row_count: int
    offset: int
    limit: int
    next_offset: int | None
    order: Literal["price_desc", "time_asc", "time_desc"]
    events: list[AnomalyEvent]


def date_bounds(start, end):
    for value in (start, end):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None or not 1970 <= value.year <= 2100):
            raise HTTPException(422, "Use timezone-aware dates between 1970 and 2100.")
    if start is not None and end is not None and start > end:
        raise HTTPException(422, "Start must not be after end.")
    return start, end


@lru_cache(maxsize=4)
def _read(path: Path, version: tuple[int, int]) -> tuple[AnomalyEvent, ...]:
    if version[1] > 64 * 1024 * 1024:
        raise ValueError("Report too large")
    result = []
    seen = set()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"timestamp", "price_eur_mwh", "load_mw", "anomaly"}.issubset(reader.fieldnames or []):
            raise ValueError("Invalid report schema")
        for i, row in enumerate(reader):
            if i >= 100_000 or row.get("anomaly") != "-1":
                raise ValueError("Invalid active report")
            timestamp = _timestamp(row["timestamp"])
            price, load = _number(row["price_eur_mwh"]), _number(row["load_mw"])
            if timestamp in seen or price is None or load is None:
                raise ValueError("Invalid event")
            seen.add(timestamp)
            result.append(AnomalyEvent(timestamp=timestamp, price_eur_mwh=price, load_mw=load))
    after = path.stat()
    if version != (after.st_mtime_ns, after.st_size):
        raise ValueError("Report changed during reading")
    return tuple(sorted(result, key=lambda row: row.timestamp))


def filtered_events(path, start=None, end=None):
    date_bounds(start, end)
    try:
        if path is None or not path.is_file():
            raise HTTPException(404, "The active anomaly report is not available.")
        stat = path.stat()
        rows = _read(path, (stat.st_mtime_ns, stat.st_size))
        return rows, [row for row in rows if (start is None or row.timestamp >= start) and (end is None or row.timestamp <= end)]
    except (OSError, ValueError, TypeError, KeyError, csv.Error):
        raise HTTPException(503, "The active anomaly report is invalid or unreadable.") from None


def anomaly_summary(path, start=None, end=None):
    all_rows, rows = filtered_events(path, start, end)
    return AnomalySummary(report_status="available" if all_rows else "empty", count=len(rows), total_report_rows=len(all_rows),
                          first_event=rows[0].timestamp if rows else None, last_event=rows[-1].timestamp if rows else None,
                          minimum_price=min(row.price_eur_mwh for row in rows) if rows else None,
                          maximum_price=max(row.price_eur_mwh for row in rows) if rows else None,
                          average_load_mw=statistics.mean(row.load_mw for row in rows) if rows else None)


def anomaly_events(path, start, end, order, limit, offset):
    _, rows = filtered_events(path, start, end)
    if order == "price_desc":
        rows.sort(key=lambda row: (-row.price_eur_mwh, row.timestamp))
    elif order == "time_desc":
        rows.reverse()
    page = rows[offset:offset + limit]
    return AnomalyEvents(matched_rows=len(rows), row_count=len(page), offset=offset, limit=limit, order=order,
                         next_offset=offset+len(page) if offset+len(page) < len(rows) else None, events=page)
