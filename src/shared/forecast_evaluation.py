"""Pure realized-error summaries, without model loading or report writes."""
import numpy as np
import pandas as pd

REALIZED_COLUMNS = (
    "forecast_issue_time", "target_timestamp", "horizon_hours", "issued_at_utc",
    "predicted_price_eur_mwh", "model_release", "actual_price_eur_mwh",
    "absolute_error", "squared_error", "signed_error",
)

MONITORING_MIN_PAIRS = 20
HORIZON_MIN_PAIRS = 5

def summarize_realized_performance(
    realized: pd.DataFrame,
    *,
    now: pd.Timestamp | None = None,
    min_pairs: int = MONITORING_MIN_PAIRS,
    min_horizon_pairs: int = HORIZON_MIN_PAIRS,
) -> dict:
    """Summarize only pre-target issued, subsequently realized forecasts.

    Windows use observed target timestamps relative to ``now``, not a fixed
    number of rows. Small samples remain explicitly insufficient.
    """
    if min_pairs < 1 or min_horizon_pairs < 1:
        raise ValueError("Monitoring sample thresholds must be positive.")
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    windows = {"24h": pd.Timedelta(hours=24), "7d": pd.Timedelta(days=7),
               "30d": pd.Timedelta(days=30)}
    empty = {"status": "Insufficient data", "pair_count": 0,
             "mae": None, "rmse": None, "bias": None}
    if realized.empty:
        return {"overall": empty.copy(), "windows": {name: empty.copy() for name in windows},
                "horizons": pd.DataFrame(columns=["horizon_hours", "pair_count", "mae", "rmse", "bias", "status"]),
                "target_dates": 0}
    pairs = realized.copy()
    for name in ("forecast_issue_time", "target_timestamp", "issued_at_utc"):
        pairs[name] = pd.to_datetime(pairs[name], errors="coerce", utc=True)
    for name in ("signed_error", "absolute_error", "squared_error", "horizon_hours"):
        pairs[name] = pd.to_numeric(pairs[name], errors="coerce")
    pairs = pairs.loc[
        (pairs["forecast_issue_time"] < pairs["target_timestamp"])
        & (pairs["issued_at_utc"] < pairs["target_timestamp"])
        & (pairs["target_timestamp"] <= current)
        & np.isfinite(pairs[["signed_error", "absolute_error", "squared_error"]].to_numpy(dtype=float)).all(axis=1)
    ]

    def metrics(frame: pd.DataFrame, minimum: int) -> dict:
        result = {**empty, "pair_count": len(frame)}
        if len(frame) >= minimum:
            result.update({
                "status": "Available",
                "mae": float(frame["absolute_error"].mean()),
                "rmse": float(np.sqrt(frame["squared_error"].mean())),
                "bias": float(frame["signed_error"].mean()),
            })
        return result

    horizon_rows = []
    for horizon in range(1, 25):
        frame = pairs.loc[pairs["horizon_hours"] == horizon]
        horizon_rows.append({"horizon_hours": horizon, **metrics(frame, min_horizon_pairs)})
    return {
        "overall": metrics(pairs, min_pairs),
        "windows": {
            name: metrics(
                pairs.loc[pairs["target_timestamp"] > current - duration], min_pairs
            )
            for name, duration in windows.items()
        },
        "horizons": pd.DataFrame(horizon_rows),
        "target_dates": int(pairs["target_timestamp"].dt.date.nunique()),
    }
