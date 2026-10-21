"""Read-only presentation parity; no model execution, report generation or writes."""
from __future__ import annotations

import csv
import hashlib
import math
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import Field
from .market_data import PublicModel, MarketCoverage, GENERATION_FIELDS, VALUE_FIELDS, WEATHER_FIELDS
from .anomalies import date_bounds


class WeatherPoint(PublicModel):
    timestamp: datetime
    temperature_2m: float | None
    wind_speed_10m: float | None
    gap_before: bool


class GenerationAverage(PublicModel):
    source: str
    average_mw: float | None
    observations: int


class MarketExploration(PublicModel):
    coverage: MarketCoverage
    matched_rows: int
    generation: list[GenerationAverage]
    weather: list[WeatherPoint]
    sampling: str = "Chronological first/last/temperature-min/temperature-max observations per bucket. Wind extrema are not guaranteed. Full-range generation means exclude missing values; chart points are not averages."


def market_exploration(store, start, end, max_points):
    date_bounds(start, end)
    with store._lock:
        store._refresh()
        db = store._connection
        where = " WHERE (? IS NULL OR timestamp>=?) AND (? IS NULL OR timestamp<=?)"
        a, b = start.timestamp() if start else None, end.timestamp() if end else None
        args = (a, a, b, b)
        count = db.execute("SELECT COUNT(*) FROM observations"+where, args).fetchone()[0]
        # Same eight sources as Streamlit; total wind does not double-count components.
        keys = [k for k in GENERATION_FIELDS if k not in {"wind_offshore_mw", "wind_onshore_mw"}]
        generation = []
        for key in keys:
            mean, n = db.execute(f"SELECT AVG({key}), COUNT({key}) FROM observations"+where, args).fetchone()
            if mean is not None and not math.isfinite(mean):
                raise HTTPException(503, "Market aggregates contain invalid values.")
            generation.append(GenerationAverage(source=key, average_mw=mean, observations=n))
        bucket = max(1, math.ceil(count / (max_points // 4)))
        rows = db.execute("""WITH ranked AS (
            SELECT timestamp, temperature_2m, wind_speed_10m, ROW_NUMBER() OVER(ORDER BY timestamp) rn
            FROM observations"""+where+"""), binned AS (SELECT *, (rn-1)/? bucket FROM ranked),
            selected AS (SELECT *, MIN(rn) OVER(PARTITION BY bucket) first, MAX(rn) OVER(PARTITION BY bucket) last,
            ROW_NUMBER() OVER(PARTITION BY bucket ORDER BY temperature_2m IS NULL,temperature_2m,timestamp) lo,
            ROW_NUMBER() OVER(PARTITION BY bucket ORDER BY temperature_2m IS NULL,temperature_2m DESC,timestamp) hi FROM binned)
            SELECT timestamp,temperature_2m,wind_speed_10m FROM selected WHERE rn=first OR rn=last OR lo=1 OR hi=1 ORDER BY timestamp""", (*args, bucket)).fetchall()
        weather, previous = [], None
        for stamp, temperature, wind in rows:
            gap = False
            if previous is not None:
                n = db.execute("SELECT COUNT(*) FROM observations WHERE timestamp>? AND timestamp<?", (previous, stamp)).fetchone()[0]
                gap = n < (stamp-previous)//3600-1
            weather.append(WeatherPoint(timestamp=datetime.fromtimestamp(stamp, timezone.utc), temperature_2m=temperature, wind_speed_10m=wind, gap_before=gap))
            previous = stamp
        return MarketExploration(coverage=store._coverage, matched_rows=count, generation=generation, weather=weather)


class ForecastContext(PublicModel):
    available: bool
    issue_time: datetime
    load_mw: float | None = None
    wind_total_mw: float | None = None
    solar_mw: float | None = None
    renewable_share: float | None = None
    price_eur_mwh: float | None = None
    price_rolling_mean_24h: float | None = None
    price_rolling_std_24h: float | None = None
    price_average_7d: float | None = None
    temperature_2m: float | None = None
    relative_humidity_2m: float | None = None
    wind_speed_10m: float | None = None
    cloud_cover: float | None = None
    shortwave_radiation: float | None = None
    provenance: str = "Exact issue-hour persisted Silver observations; complete contiguous windows only. Descriptive context, not a reconstruction of the fitted model's input vector. No nearest-hour substitution."


def forecast_context(store, issue):
    date_bounds(issue, issue)
    issue = issue.astimezone(timezone.utc)
    if issue.minute or issue.second or issue.microsecond:
        raise HTTPException(422, "Issue time must be an exact hour.")
    import pandas as pd
    from dashboard_data import build_model_input_context
    with store._lock:
        store._refresh()
        keys = (*VALUE_FIELDS, *WEATHER_FIELDS)
        rows = store._connection.execute("SELECT timestamp,"+",".join(keys)+" FROM observations WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp", (issue.timestamp()-167*3600, issue.timestamp())).fetchall()
    frame = pd.DataFrame(rows, columns=["timestamp", *keys])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True)
    return ForecastContext(**build_model_input_context(frame, issue))


class EvaluationMetrics(PublicModel):
    status: Literal["Available", "Insufficient data"]
    pair_count: int = Field(ge=0)
    mae: float | None
    rmse: float | None
    bias: float | None


class HorizonMetrics(EvaluationMetrics):
    horizon_hours: int = Field(ge=1, le=24)


class ReleaseEvaluation(PublicModel):
    model_release: str
    overall: EvaluationMetrics
    windows: dict[str, EvaluationMetrics]
    horizons: list[HorizonMetrics]
    target_dates: int
    first_target: datetime | None
    last_target: datetime | None
    performance_status: str
    performance_reason: str


class RealizedEvaluation(PublicModel):
    assessed_at: datetime
    report_sha256: str
    releases: list[ReleaseEvaluation]
    provenance: str = "Persisted next24h realized error pairs grouped by release; existing summarize_realized_performance rules: 20 pairs overall/window, 5 per horizon. Windows use target time, bias is predicted minus observed. Frozen one-hour evaluation is separate."


@lru_cache(maxsize=1)
def _realized_rows(path, version):
    from models.next24h_monitoring import REALIZED_COLUMNS
    if version[1] > 64*1024*1024:
        raise ValueError("Report size limit")
    rows, identities = [], set()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not set(REALIZED_COLUMNS).issubset(reader.fieldnames or []):
            raise ValueError("Missing evaluation fields")
        for i, row in enumerate(reader):
            if i >= 100000:
                raise ValueError("Evaluation size limit")
            times = {}
            for key in ("forecast_issue_time", "target_timestamp", "issued_at_utc"):
                dt = datetime.fromisoformat(row[key].replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    raise ValueError("Timezone required")
                times[key] = dt.astimezone(timezone.utc)
            h = int(row["horizon_hours"])
            if not 1 <= h <= 24 or (times["target_timestamp"]-times["forecast_issue_time"]).total_seconds() != h*3600:
                raise ValueError("Invalid horizon")
            release = row["model_release"]
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", release):
                raise ValueError("Invalid release")
            identity = (release, times["forecast_issue_time"], h)
            if identity in identities:
                raise ValueError("Duplicate forecast pair")
            identities.add(identity)
            numbers = {k: float(row[k]) for k in ("predicted_price_eur_mwh", "actual_price_eur_mwh", "absolute_error", "squared_error", "signed_error")}
            if not all(math.isfinite(n) for n in numbers.values()):
                raise ValueError("Nonfinite metric")
            error = numbers["predicted_price_eur_mwh"]-numbers["actual_price_eur_mwh"]
            if not all(math.isclose(numbers[k], n, rel_tol=1e-7, abs_tol=1e-7) for k,n in [("absolute_error", abs(error)), ("squared_error", error**2), ("signed_error", error)]):
                raise ValueError("Inconsistent evaluation")
            rows.append({**times, **numbers, "horizon_hours":h, "model_release":release})
    if len({r['model_release'] for r in rows}) > 20:
        raise ValueError("Release size limit")
    if (path.stat().st_mtime_ns, path.stat().st_size) != version:
        raise ValueError("Report changed")
    with path.open('rb') as handle:
        content = handle.read(64*1024*1024+1)
    if len(content)>64*1024*1024 or (path.stat().st_mtime_ns,path.stat().st_size)!=version:
        raise ValueError('Report changed or exceeded limit')
    return rows, hashlib.sha256(content).hexdigest()


def realized_evaluation(root: Path | None):
    if root is None:
        raise HTTPException(503, "Evaluation reporting is not configured.")
    path = root / "data/reports/next24h_realized_errors.csv"
    if not path.is_file():
        raise HTTPException(404, "Realized evaluation report is not available.")
    try:
        import pandas as pd
        from models.next24h_monitoring import summarize_realized_performance
        from dashboard_health import model_performance_state
        rows, digest = _realized_rows(path, (path.stat().st_mtime_ns, path.stat().st_size))
        now = datetime.now(timezone.utc)
        releases = []
        from .model_summaries import _summary
        model = _summary(root, 'next24h')
        test = next((e for e in model.evaluations if e.split == 'test'), None)
        # Unknown historic release cannot borrow the active release's evaluation baseline.
        for release in sorted({r['model_release'] for r in rows}):
            frame = pd.DataFrame([r for r in rows if r['model_release']==release])
            valid = frame.loc[(frame.forecast_issue_time < frame.target_timestamp) & (frame.issued_at_utc < frame.target_timestamp) & (frame.target_timestamp <= now)]
            result = summarize_realized_performance(frame, now=pd.Timestamp(now))
            baseline = {'test_metrics': {'rmse': test.rmse}, 'persistence_test_metrics': {'rmse': test.persistence_rmse}} if model.metadata_status == 'available' and model.version == release and test is not None and test.persistence_rmse is not None else {}
            health = model_performance_state(result, baseline)
            releases.append(ReleaseEvaluation(model_release=release, overall=result['overall'], windows=result['windows'], horizons=result['horizons'].astype(object).where(pd.notna(result['horizons']), None).to_dict(orient='records'), target_dates=result['target_dates'], first_target=valid.target_timestamp.min().to_pydatetime() if not valid.empty else None, last_target=valid.target_timestamp.max().to_pydatetime() if not valid.empty else None, performance_status=health['label'], performance_reason=health['reason']))
        return RealizedEvaluation(assessed_at=now, report_sha256=digest, releases=releases)
    except (OSError, ValueError, TypeError, KeyError, csv.Error, OverflowError):
        raise HTTPException(503, "Realized evaluation report is invalid or unreadable.") from None

class PriceComparison(PublicModel):
    latest_timestamp: datetime | None
    latest_price: float | None
    previous_24h_average: float | None
    seven_day_average: float | None
    provenance: str = 'Persisted raw ENTSO-E prices, aggregated only into complete hours by the original Streamlit helper. Windows end at the latest complete raw price hour, independently of joined Silver or any forecast issue. Historical observations, not live prices.'


@lru_cache(maxsize=4)
def _price_comparison(path, version):
    import pandas as pd
    from dashboard_data import summarize_clean_price_history
    if version[1] > 64*1024*1024:
        raise ValueError('Price source size limit')
    frame = pd.read_csv(path, usecols=lambda key: key in {'timestamp','price_eur_mwh','source_resolution'}, nrows=400001)
    if not {'timestamp','price_eur_mwh'}.issubset(frame.columns):
        raise ValueError('Required price fields missing')
    if len(frame)>400000:
        raise ValueError('Price source row limit')
    times = pd.to_datetime(frame.timestamp, utc=True, errors='raise')
    if times.isna().any() or times.duplicated().any():
        raise ValueError('Invalid price timestamps')
    prices = pd.to_numeric(frame.price_eur_mwh, errors='raise')
    if any(not math.isfinite(v) for v in prices):
        raise ValueError('Invalid price values')
    result = PriceComparison(**summarize_clean_price_history(frame))
    if (path.stat().st_mtime_ns,path.stat().st_size)!=version:
        raise ValueError('Price source changed')
    return result


def price_comparison(root):
    if root is None:
        raise HTTPException(503, 'Price reporting is not configured.')
    path=root/'data/raw/entsoe/prices.csv'
    if not path.is_file():
        raise HTTPException(404, 'Observed price history is not available.')
    try:
        return _price_comparison(path, (path.stat().st_mtime_ns,path.stat().st_size))
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        raise HTTPException(503, 'Observed price history is invalid or unreadable.') from None
