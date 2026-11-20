"""Live DE–LU seasonal baseline using only complete, elapsed price hours."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import hashlib
import re
import os
from pathlib import Path
import tempfile

import pandas as pd

from shared.price_aggregation import aggregate_hourly_prices

MODEL_RELEASE = "fallback-price-only-seasonal-median-v1"
MAX_PRICE_AGE = timedelta(hours=3)
MAX_SNAPSHOT_AGE = timedelta(minutes=15)
MAX_ISSUE_AGE = timedelta(hours=3)
CACHED_HISTORY_POLICY = "LATEST_PRICE_HISTORY_V1"


def build(price_path, now):
    issue = now.replace(minute=0, second=0, microsecond=0)
    prices = pd.read_csv(price_path)
    timestamps = pd.to_datetime(prices.pop("timestamp"), utc=True, format="mixed")
    recent = timestamps.between(issue - timedelta(days=14), issue, inclusive="left")
    prices.index = timestamps
    if not recent.any():
        return None
    hourly = aggregate_hourly_prices(prices.loc[recent.to_numpy()])["price_eur_mwh"]
    hourly = hourly[hourly.map(math.isfinite)]
    if hourly.empty or now - (hourly.index[-1] + timedelta(hours=1)) >= MAX_PRICE_AGE:
        return None
    medians = hourly.groupby(hourly.index.hour).median()
    counts = hourly.groupby(hourly.index.hour).count()
    if len(counts) != 24 or (counts < 7).any():
        return None
    return {
        "issue_time": issue.isoformat(),
        "completed_at": now.isoformat(),
        "latest_price_hour": hourly.index[-1].isoformat(),
        "values": [float(medians[(issue + timedelta(hours=h)).hour]) for h in range(1, 25)],
    }


def load(path, now):
    snapshot = read_snapshot(path, now)
    return snapshot["forecast"] if snapshot is not None else None


def read_snapshot(path, now):
    try:
        with path.open("rb") as file:
            raw = file.read(4097)
        if len(raw) > 4096:
            return None
        document = json.loads(raw)
        if not isinstance(document, dict):
            return None
        if document.get("availability_policy") == CACHED_HISTORY_POLICY:
            return materialize(document, now)
        issue, completed, price_hour = (
            datetime.fromisoformat(document[key])
            for key in ("issue_time", "completed_at", "latest_price_hour")
        )
        values = document["values"]
        if (
            any(stamp.utcoffset() != timedelta(0) for stamp in (issue, completed, price_hour))
            or issue != completed.replace(minute=0, second=0, microsecond=0)
            or not issue <= completed <= now < expires_at(issue, completed, price_hour)
            or price_hour != price_hour.replace(minute=0, second=0, microsecond=0)
            or price_hour >= issue
            or not isinstance(values, list)
            or len(values) != 24
            or any(type(value) not in (float, int) or not math.isfinite(value) for value in values)
        ):
            return None
        return {
            "forecast": (issue, completed, expires_at(issue, completed, price_hour), values),
            "availability_policy": "PRICE_ONLY_FALLBACK_V1",
        }
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return None


def expires_at(issue, completed, price_hour):
    return min(
        issue + MAX_ISSUE_AGE,
        completed + MAX_SNAPSHOT_AGE,
        price_hour + timedelta(hours=1) + MAX_PRICE_AGE,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prices", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    document = build(args.prices, datetime.now(timezone.utc))
    if document is None:
        args.output.unlink(missing_ok=True)
        print("Price-only fallback withheld because recent complete prices are unavailable.")
        return
    fd, pending = tempfile.mkstemp(prefix=".forecast-", dir=args.output.parent)
    try:
        with os.fdopen(fd, "w") as file:
            os.fchmod(file.fileno(), 0o640)
            json.dump(document, file, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(pending, args.output)
    finally:
        Path(pending).unlink(missing_ok=True)


def build_cached_history(price_path, now):
    """Fit the seasonal median to the latest collected complete price history."""
    if now.utcoffset() != timedelta(0):
        raise ValueError("Forecast calculation requires UTC.")
    prices = pd.read_csv(price_path)
    timestamps = pd.to_datetime(prices.pop("timestamp"), utc=True, format="mixed")
    issue = now.replace(minute=0, second=0, microsecond=0)
    prices.index = timestamps
    elapsed = prices.loc[prices.index < issue]
    if elapsed.empty:
        return None
    hourly = aggregate_hourly_prices(elapsed)["price_eur_mwh"]
    hourly = hourly[hourly.map(math.isfinite)]
    if hourly.empty:
        return None
    end = hourly.index[-1] + timedelta(hours=1)
    hourly = hourly.loc[hourly.index >= end - timedelta(days=14)]
    counts = hourly.groupby(hourly.index.hour).count()
    if len(counts) != 24 or (counts < 7).any():
        return None
    medians = hourly.groupby(hourly.index.hour).median()
    source = [[stamp.isoformat(), float(value)] for stamp, value in hourly.items()]
    return {
        "availability_policy": CACHED_HISTORY_POLICY,
        "calculated_at": now.isoformat(),
        "latest_price_hour": hourly.index[-1].isoformat(),
        "history_start": hourly.index[0].isoformat(),
        "source_sha256": hashlib.sha256(
            json.dumps(source, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest(),
        "hourly_medians": [float(medians[hour]) for hour in range(24)],
        "minimum_hour_samples": int(counts.min()),
    }


def materialize(document, now):
    """Run seasonal inference for current future hours from cached statistics."""
    required = {
        "availability_policy", "calculated_at", "latest_price_hour",
        "history_start", "source_sha256", "hourly_medians", "minimum_hour_samples",
    }
    if (set(document) != required or now.utcoffset() != timedelta(0)
            or document['availability_policy'] != CACHED_HISTORY_POLICY):
        return None
    calculated, price_hour, start = (
        datetime.fromisoformat(document[key])
        for key in ("calculated_at", "latest_price_hour", "history_start")
    )
    values = document["hourly_medians"]
    samples = document["minimum_hour_samples"]
    if (
        any(stamp.utcoffset() != timedelta(0) for stamp in (calculated, price_hour, start))
        or not start <= price_hour < calculated.replace(minute=0, second=0, microsecond=0)
        or calculated > now
        or any(stamp != stamp.replace(minute=0, second=0, microsecond=0) for stamp in (price_hour, start))
        or price_hour - start >= timedelta(days=14)
        or not isinstance(document["source_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", document["source_sha256"]) is None
        or type(samples) is not int or not 7 <= samples <= 14
        or not isinstance(values, list) or len(values) != 24
        or any(type(value) not in (float, int) or not math.isfinite(value) for value in values)
    ):
        return None
    issue = now.replace(minute=0, second=0, microsecond=0)
    forecast = [values[(issue + timedelta(hours=h)).hour] for h in range(1, 25)]
    return {
        "forecast": (issue, now, issue + timedelta(hours=1), forecast),
        "availability_policy": CACHED_HISTORY_POLICY,
        "source_latest_at": price_hour + timedelta(hours=1),
        "source_age_seconds": (now - (price_hour + timedelta(hours=1))).total_seconds(),
        "source_snapshot_at": calculated,
        "source_sha256": document["source_sha256"],
    }


if __name__ == "__main__":
    main()
