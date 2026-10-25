"""Read-only, versioned Silver snapshots for public market observation queries.

The persistent dataset is never modified. A compact in-memory SQLite index is
built by streaming the CSV once per file version, avoiding pandas/Streamlit
imports and full-history parsing on each request.
"""
from __future__ import annotations

import csv
import hashlib
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Generation(PublicModel):
    biomass_mw: float | None
    lignite_mw: float | None
    gas_mw: float | None
    hard_coal_mw: float | None
    hydro_mw: float | None
    nuclear_mw: float | None
    solar_mw: float | None
    wind_offshore_mw: float | None
    wind_onshore_mw: float | None
    wind_total_mw: float | None


GENERATION_FIELDS = tuple(Generation.model_fields)
WEATHER_FIELDS = ("temperature_2m", "wind_speed_10m", "relative_humidity_2m", "cloud_cover", "shortwave_radiation")
VALUE_FIELDS = ("price_eur_mwh", "load_mw", *GENERATION_FIELDS)


class MarketObservation(PublicModel):
    timestamp: datetime
    price_eur_mwh: float | None
    load_mw: float | None
    generation: Generation
    renewable_generation_mw: float | None
    renewable_share: float | None


class MarketCoverage(PublicModel):
    source: str = "Persisted hourly Silver market observations"
    market_area: str = "DE-LU"
    resolution: str = "hourly"
    snapshot_id: str
    row_count: int
    first_observation: datetime | None
    latest_observation: datetime | None
    missing_hours_in_span: int
    renewable_definition: str = (
        "Solar + total wind + biomass + run-of-river hydro. Share divides this "
        "by the sum of these sources plus lignite, gas, hard coal and nuclear; "
        "this is the selected-source mix, not all national generation. Missing "
        "components remain null; no observation is imputed."
    )


class MarketHistory(PublicModel):
    coverage: MarketCoverage
    start: datetime | None
    end: datetime | None
    matched_rows: int
    row_count: int
    limit: int
    offset: int
    next_offset: int | None
    observations: list[MarketObservation]


def _timestamp(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timezone required")
    dt = dt.astimezone(timezone.utc)
    if dt.minute or dt.second or dt.microsecond:
        raise ValueError("Exact hours required")
    return dt


def _number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Nonfinite observation")
    return number


class MarketStore:
    def __init__(self, path: Path | None):
        self.path = path
        self._version = None
        self._connection: sqlite3.Connection | None = None
        self._lock = RLock()
        self._coverage: MarketCoverage | None = None

    def close(self):
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            self._version = None

    def _refresh(self):
        connection = None
        try:
            if self.path is None or not self.path.is_file():
                raise HTTPException(404, "Market observations are not available.")
            info = self.path.stat()
            version = (info.st_mtime_ns, info.st_size)
            if self._connection is not None and self._version == version:
                return
            if info.st_size > 512 * 1024 * 1024:
                raise ValueError("Snapshot size limit")
            connection = sqlite3.connect(":memory:", check_same_thread=False)
            connection.execute(
                "CREATE TABLE observations (timestamp INTEGER PRIMARY KEY, "
                + ", ".join(f"{name} REAL" for name in (*VALUE_FIELDS, *WEATHER_FIELDS)) + ")"
            )
            with self.path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if not {"timestamp", *VALUE_FIELDS}.issubset(reader.fieldnames or []):
                    raise ValueError("Missing observation columns")
                def rows():
                    previous = None
                    for i, row in enumerate(reader):
                        if i >= 2_000_000:
                            raise ValueError("Snapshot row limit")
                        timestamp = int(_timestamp(row["timestamp"]).timestamp())
                        if previous is not None and timestamp <= previous:
                            raise ValueError("Unordered or duplicate timestamp")
                        previous = timestamp
                        yield (timestamp, *(_number(row.get(name)) for name in (*VALUE_FIELDS, *WEATHER_FIELDS)))
                connection.executemany(
                    "INSERT INTO observations VALUES (" + ",".join("?" for _ in range(1 + len(VALUE_FIELDS) + len(WEATHER_FIELDS))) + ")", rows()
                )
            after = self.path.stat()
            if version != (after.st_mtime_ns, after.st_size):
                raise ValueError("Source changed while reading")
            count, first, last = connection.execute("SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM observations").fetchone()
            coverage = MarketCoverage(
                snapshot_id="silver-" + hashlib.sha256(f"{version}".encode()).hexdigest()[:16],
                row_count=count,
                first_observation=datetime.fromtimestamp(first, timezone.utc) if first is not None else None,
                latest_observation=datetime.fromtimestamp(last, timezone.utc) if last is not None else None,
                missing_hours_in_span=((last - first) // 3600 + 1 - count) if count else 0,
            )
            if self._connection is not None:
                self._connection.close()
            self._connection, self._coverage, self._version = connection, coverage, version
        except HTTPException:
            if connection is not None:
                connection.close()
            raise
        except (OSError, ValueError, KeyError, TypeError, csv.Error, sqlite3.Error):
            if connection is not None:
                connection.close()
            raise HTTPException(503, "Market observations are invalid or temporarily unreadable.") from None

    def coverage(self) -> MarketCoverage:
        with self._lock:
            self._refresh()
            return self._coverage.model_copy()

    def history(self, start: datetime | None, end: datetime | None, limit: int, offset: int) -> MarketHistory:
        for dt in (start, end):
            if dt is not None and not 1970 <= dt.year <= 2100:
                raise HTTPException(422, "Date filters must be between 1970 and 2100.")
            if dt is not None and (dt.tzinfo is None or dt.utcoffset() is None):
                raise HTTPException(422, "Date filters require an explicit timezone.")
        if start is not None:
            start = start.astimezone(timezone.utc)
        if end is not None:
            end = end.astimezone(timezone.utc)
        with self._lock:
            self._refresh()
            coverage = self._coverage
            end = end if end is not None else coverage.latest_observation
            start = start if start is not None else (end - timedelta(days=7) if end else None)
            if start is not None and end is not None:
                if start > end or end - start > timedelta(days=366):
                    raise HTTPException(422, "Use an ordered date range of at most 366 days.")
            if end is None:
                return MarketHistory(coverage=coverage, start=start, end=end, matched_rows=0, row_count=0, limit=limit, offset=offset, next_offset=None, observations=[])
            # Numeric epoch bounds preserve fractional-second filter semantics.
            bounds = (start.timestamp(), end.timestamp())
            matched = self._connection.execute("SELECT COUNT(*) FROM observations WHERE timestamp BETWEEN ? AND ?", bounds).fetchone()[0]
            rows = self._connection.execute("SELECT * FROM observations WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp LIMIT ? OFFSET ?", (*bounds, limit, offset)).fetchall()
            observations = []
            for row in rows:
                values = dict(zip(VALUE_FIELDS, row[1:]))
                required = [values[name] for name in ("solar_mw", "wind_total_mw", "biomass_mw", "hydro_mw")]
                renewable = sum(required) if all(n is not None for n in required) else None
                conventional = [values[name] for name in ("lignite_mw", "gas_mw", "hard_coal_mw", "nuclear_mw")]
                total = renewable + sum(conventional) if renewable is not None and all(n is not None for n in conventional) else None
                if (renewable is not None and not math.isfinite(renewable)) or (total is not None and not math.isfinite(total)):
                    raise HTTPException(503, "Market observations contain invalid derived totals.")
                observations.append(MarketObservation(
                    timestamp=datetime.fromtimestamp(row[0], timezone.utc),
                    price_eur_mwh=values["price_eur_mwh"], load_mw=values["load_mw"],
                    generation=Generation(**{name: values[name] for name in GENERATION_FIELDS}),
                    renewable_generation_mw=renewable,
                    renewable_share=renewable / total if total is not None and total > 0 else None,
                ))
            return MarketHistory(coverage=coverage, start=start, end=end, matched_rows=matched, row_count=len(observations), limit=limit, offset=offset, next_offset=offset + len(observations) if offset + len(observations) < matched else None, observations=observations)


class MarketChartPoint(PublicModel):
    timestamp: datetime
    price_eur_mwh: float | None
    load_mw: float | None
    wind_solar_mw: float | None
    gap_before: bool


class MarketSummary(PublicModel):
    coverage: MarketCoverage
    matched_rows: int
    latest_observation: MarketChartPoint | None
    mean_load_mw: float | None
    minimum_price: float | None
    maximum_price: float | None
    average_price: float | None
    sample_price_std: float | None
    recent: list[MarketChartPoint]


class MarketChart(PublicModel):
    coverage: MarketCoverage
    matched_rows: int
    row_count: int
    sampling: str = "Per chronological bucket: first, last, minimum-price and maximum-price observations; exact original values, no averages."
    points: list[MarketChartPoint]


def _chart_point(row, gap=False):
    if row[3] is not None and row[4] is not None and not math.isfinite(row[3] + row[4]):
        raise HTTPException(503, "Market observations contain invalid derived totals.")
    return MarketChartPoint(timestamp=datetime.fromtimestamp(row[0], timezone.utc), price_eur_mwh=row[1], load_mw=row[2],
                            wind_solar_mw=row[3] + row[4] if row[3] is not None and row[4] is not None else None,
                            gap_before=gap)


def market_summary(store: MarketStore, start=None, end=None) -> MarketSummary:
    from .anomalies import date_bounds
    date_bounds(start, end)
    with store._lock:
        store._refresh()
        where = "WHERE (? IS NULL OR timestamp >= ?) AND (? IS NULL OR timestamp <= ?)"
        a, b = start.timestamp() if start else None, end.timestamp() if end else None
        args = (a, a, b, b)
        connection = store._connection
        count, mean_load, lo, hi, mean_price = connection.execute(
            "SELECT COUNT(*), AVG(load_mw), MIN(price_eur_mwh), MAX(price_eur_mwh), AVG(price_eur_mwh) FROM observations " + where, args
        ).fetchone()
        # Centered second pass avoids cancellation from E[x²] - E[x]².
        n, squared = connection.execute("SELECT COUNT(price_eur_mwh), SUM((price_eur_mwh-?)*(price_eur_mwh-?)) FROM observations " + where, (mean_price, mean_price, *args)).fetchone()
        if any(value is not None and not math.isfinite(value) for value in (mean_load, mean_price, squared)):
            raise HTTPException(503, "Market summary contains invalid derived values.")
        recent = connection.execute("SELECT timestamp, price_eur_mwh, load_mw, wind_total_mw, solar_mw FROM observations " + where + " ORDER BY timestamp DESC LIMIT 10", args).fetchall()
        return MarketSummary(coverage=store._coverage, matched_rows=count, latest_observation=_chart_point(recent[0]) if recent else None,
                             mean_load_mw=mean_load, minimum_price=lo, maximum_price=hi, average_price=mean_price,
                             sample_price_std=math.sqrt(squared/(n-1)) if n > 1 else None, recent=[_chart_point(row) for row in recent])


def market_chart(store: MarketStore, start=None, end=None, max_points=1600) -> MarketChart:
    from .anomalies import date_bounds
    date_bounds(start, end)
    with store._lock:
        store._refresh()
        where = "WHERE (? IS NULL OR timestamp >= ?) AND (? IS NULL OR timestamp <= ?)"
        a, b = start.timestamp() if start else None, end.timestamp() if end else None
        args = (a, a, b, b)
        connection = store._connection
        count = connection.execute("SELECT COUNT(*) FROM observations " + where, args).fetchone()[0]
        bucket_size = max(1, math.ceil(count / max(1, max_points // 4)))
        rows = connection.execute("""
            WITH ranked AS (
              SELECT timestamp, price_eur_mwh, load_mw, wind_total_mw, solar_mw,
                     ROW_NUMBER() OVER (ORDER BY timestamp) AS rn FROM observations
            """ + where + """), binned AS (
              SELECT *, (rn-1)/? AS bucket FROM ranked
            ), selected AS (
              SELECT *, ROW_NUMBER() OVER (PARTITION BY bucket ORDER BY price_eur_mwh IS NULL, price_eur_mwh, timestamp) AS lo,
                        ROW_NUMBER() OVER (PARTITION BY bucket ORDER BY price_eur_mwh IS NULL, price_eur_mwh DESC, timestamp) AS hi,
                        MIN(rn) OVER (PARTITION BY bucket) AS first,
                        MAX(rn) OVER (PARTITION BY bucket) AS last FROM binned
            ) SELECT timestamp, price_eur_mwh, load_mw, wind_total_mw, solar_mw, rn FROM selected
              WHERE lo=1 OR hi=1 OR rn=first OR rn=last ORDER BY timestamp
            """, (*args, bucket_size)).fetchall()
        points = []
        previous = None
        for row in rows:
            gap = False
            if previous is not None:
                gap = (row[0] - previous[0]) // 3600 > row[-1] - previous[-1]
            points.append(_chart_point(row[:5], gap))
            previous = row
        return MarketChart(coverage=store._coverage, matched_rows=count, row_count=len(points), points=points)
