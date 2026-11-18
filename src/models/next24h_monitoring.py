"""Match issued next24h forecasts to later observed ENTSO-E hourly prices."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from shared.forecast_evaluation import (
    match_realized_forecasts, summarize_realized_performance, MONITORING_MIN_PAIRS,
    HORIZON_MIN_PAIRS, REALIZED_COLUMNS,
)

from models.next24h_production import HISTORY_PATH, _atomic_csv
from processing.build_silver_dataset import aggregate_hourly_prices


RAW_PRICE_PATH = Path("data/raw/entsoe/prices.csv")
REALIZED_PATH = Path("data/reports/next24h_realized_errors.csv")
PERFORMANCE_PATH = Path("data/reports/next24h_performance.csv")
PERFORMANCE_COLUMNS = (
    "scope", "horizon_hours", "observations", "mae", "rmse", "bias",
    "rolling_window", "rolling_mae", "rolling_rmse", "rolling_bias",
)


def load_observed_prices(path: Path = RAW_PRICE_PATH) -> pd.DataFrame:
    prices = pd.read_csv(path)
    prices["timestamp"] = pd.to_datetime(prices["timestamp"], errors="raise", utc=True)
    if prices["timestamp"].duplicated().any():
        raise ValueError("Observed ENTSO-E prices contain duplicate timestamps.")
    hourly = aggregate_hourly_prices(prices.set_index("timestamp"))
    return hourly.reset_index().rename(columns={"timestamp": "target_timestamp"})


def performance_metrics(
    realized: pd.DataFrame,
    *,
    min_observations: int = 5,
    rolling_window: int = 168,
) -> pd.DataFrame:
    if min_observations < 1 or rolling_window < min_observations:
        raise ValueError("Monitoring sample thresholds are invalid.")
    if realized.empty:
        return pd.DataFrame(columns=PERFORMANCE_COLUMNS)
    rows = []
    for scope, horizon, frame in (
        [("overall", 0, realized)]
        + [
            ("horizon", horizon, group)
            for horizon, group in realized.groupby("horizon_hours", sort=True)
        ]
    ):
        frame = frame.sort_values(["target_timestamp", "forecast_issue_time"])
        if len(frame) < min_observations:
            continue
        recent = frame.tail(rolling_window)
        rows.append({
            "scope": scope,
            "horizon_hours": int(horizon),
            "observations": len(frame),
            "mae": float(frame["absolute_error"].mean()),
            "rmse": float(np.sqrt(frame["squared_error"].mean())),
            "bias": float(frame["signed_error"].mean()),
            "rolling_window": len(recent),
            "rolling_mae": float(recent["absolute_error"].mean()),
            "rolling_rmse": float(np.sqrt(recent["squared_error"].mean())),
            "rolling_bias": float(recent["signed_error"].mean()),
        })
    return pd.DataFrame(rows, columns=PERFORMANCE_COLUMNS)


def update_next24h_monitoring(
    history_path: Path = HISTORY_PATH,
    raw_price_path: Path = RAW_PRICE_PATH,
    realized_path: Path = REALIZED_PATH,
    performance_path: Path = PERFORMANCE_PATH,
) -> tuple[int, int]:
    history_path, raw_price_path = Path(history_path), Path(raw_price_path)
    import os
    if os.environ.get('POWERFLOW_REALIZED_REPORT_ENABLED')=='true':
        from models.realized_reporting import build
        from shared.realized_report_store import publish
        from shared.realized_report import failure
        import datetime as dt
        root=Path(os.environ.get('POWERFLOW_REALIZED_REPORT_ROOT','/srv/powerflow/realized-performance'))
        if not root.is_absolute() or '..'in root.parts:raise ValueError('Invalid realized report root.')
        now=dt.datetime.now(dt.timezone.utc)
        try:document=build(history_path,raw_price_path,history_path.parent/'next24h_inference',now=now)
        except Exception:document=failure('INVALID_INPUT',now)
        publish(root,document,now=now)

    if not history_path.exists() or not raw_price_path.exists():
        return 0, 0
    history = pd.read_csv(history_path)
    observed = load_observed_prices(raw_price_path)
    realized = match_realized_forecasts(history, observed)
    metrics = performance_metrics(realized)
    _atomic_csv(realized, Path(realized_path))
    _atomic_csv(metrics, Path(performance_path))
    return len(realized), len(metrics)
