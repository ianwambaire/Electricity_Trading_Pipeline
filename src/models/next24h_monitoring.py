"""Match issued next24h forecasts to later observed ENTSO-E hourly prices."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from shared.forecast_evaluation import (
    summarize_realized_performance, MONITORING_MIN_PAIRS, HORIZON_MIN_PAIRS, REALIZED_COLUMNS,
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


def match_realized_forecasts(
    history: pd.DataFrame,
    observed: pd.DataFrame,
    *, now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if history.empty or observed.empty:
        return pd.DataFrame(columns=REALIZED_COLUMNS)
    current=pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    if current.tzinfo is None:raise ValueError('UTC scoring time required.')
    current=current.tz_convert('UTC')
    issued = history.copy()
    actual = observed.copy()
    issued["forecast_issue_time"] = pd.to_datetime(
        issued["forecast_issue_time"], errors="raise", utc=True
    )
    issued["target_timestamp"] = pd.to_datetime(
        issued["target_timestamp"], errors="raise", utc=True
    )
    if "issued_at_utc" not in issued.columns:
        # Legacy rows have no auditable issuance time, so cannot be scored safely.
        return pd.DataFrame(columns=REALIZED_COLUMNS)
    issued["issued_at_utc"] = pd.to_datetime(
        issued["issued_at_utc"], errors="raise", utc=True
    )
    actual["target_timestamp"] = pd.to_datetime(
        actual["target_timestamp"], errors="raise", utc=True
    )
    if actual["target_timestamp"].duplicated().any():
        raise ValueError("Actual hourly price timestamps must be unique.")
    for key in ('horizon_hours','predicted_price_eur_mwh'):issued[key]=pd.to_numeric(issued[key],errors='raise')
    actual['price_eur_mwh']=pd.to_numeric(actual['price_eur_mwh'],errors='raise')
    if issued.duplicated(['model_release','forecast_issue_time','horizon_hours']).any():raise ValueError('Duplicate forecast identity.')
    if not np.isfinite(issued[['horizon_hours','predicted_price_eur_mwh']].to_numpy(dtype=float)).all() or not np.isfinite(actual['price_eur_mwh'].to_numpy(dtype=float)).all():raise ValueError('Invalid forecast or observed value.')
    if not (issued['horizon_hours'].between(1,24)&(issued['horizon_hours']%1==0)&((issued['target_timestamp']-issued['forecast_issue_time'])==pd.to_timedelta(issued['horizon_hours'],unit='h'))).all():raise ValueError('Invalid forecast target alignment.')
    actual=actual.loc[actual.target_timestamp+pd.Timedelta(hours=1)<=current]
    issued = issued.loc[
        (issued["forecast_issue_time"] < issued["target_timestamp"])
        & (issued["issued_at_utc"] < issued["target_timestamp"])
    ]
    matched = issued.merge(
        actual[["target_timestamp", "price_eur_mwh"]],
        on="target_timestamp", how="inner", validate="many_to_one",
    ).rename(columns={"price_eur_mwh": "actual_price_eur_mwh"})
    matched = matched.loc[
        matched["predicted_price_eur_mwh"].notna()
        & matched["actual_price_eur_mwh"].notna()
    ].copy()
    matched["signed_error"] = (
        matched["predicted_price_eur_mwh"] - matched["actual_price_eur_mwh"]
    )
    matched["absolute_error"] = matched["signed_error"].abs()
    matched["squared_error"] = matched["signed_error"] ** 2
    return matched.loc[:, REALIZED_COLUMNS].sort_values(
        ["target_timestamp", "forecast_issue_time", "horizon_hours"]
    ).reset_index(drop=True)


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
