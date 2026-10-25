"""Pure health classifications; identical thresholds for API and Streamlit."""
import pandas as pd
from shared.forecast_evaluation import HORIZON_MIN_PAIRS, MONITORING_MIN_PAIRS

MODEL_HEALTH_MIN_PAIRS = 100
MODEL_HEALTH_MIN_TARGET_DATES = 7

def forecast_freshness_state(
    issue_time,
    *,
    now: pd.Timestamp | None = None,
    maximum_age_hours: float = 3.0,
    withholding_known: bool = False,
) -> str:
    if withholding_known:
        return "Withheld — source/input problem"
    if issue_time is None or pd.isna(issue_time):
        return "Unavailable"
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    issue = pd.Timestamp(issue_time)
    issue = issue.tz_localize("UTC") if issue.tzinfo is None else issue.tz_convert("UTC")
    age = current - issue
    return "Fresh" if pd.Timedelta(0) <= age <= pd.Timedelta(hours=maximum_age_hours) else "Stale"

def source_freshness_state(
    timestamp,
    *,
    source_kind: str,
    now: pd.Timestamp | None = None,
) -> str:
    if timestamp is None or pd.isna(timestamp):
        return "Unavailable"
    if source_kind == "historical_weather":
        return "Archive history"
    if source_kind in {"silver", "gold"}:
        return "Historical dataset"
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    value = pd.Timestamp(timestamp)
    value = value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")
    age = (current - value).total_seconds() / 3600
    if age < 0:
        return "Future timestamp"
    if age <= 3:
        return "Fresh"
    return "Warning" if age <= 6 else "Stale"

def latest_quality_state(history: pd.DataFrame) -> dict[str, int]:
    if history.empty or not {"check_name", "status"}.issubset(history):
        return {"failed": 0, "warnings": 0}
    # Continuity and forecast availability are assessed from the latest run's
    # current metadata; old warning rows remain history, not active state.
    current_checks = history.loc[
        ~history["check_name"].astype(str).str.startswith("entsoe_incremental_continuity:")
        & ~history["check_name"].astype(str).str.startswith("s3_sync:")
        & history["check_name"].astype(str).ne("next24h_forecast_freshness")
    ]
    latest = current_checks.drop_duplicates("check_name", keep="first")
    status = latest["status"].fillna("").str.upper()
    return {
        "failed": int(status.isin({"FAILED", "FAILURE", "ERROR"}).sum()),
        "warnings": int(status.eq("WARNING").sum()),
    }

def assess_operational_health(
    *,
    latest_run_status,
    latest_success_time,
    core_source_timestamps: dict,
    forecast_issue_time,
    forecast_withheld: bool,
    quality_state: dict,
    unresolved_gap_count: int,
    required_artifacts_available: bool,
    now: pd.Timestamp | None = None,
    forecast_max_age_hours: float = 3.0,
) -> dict[str, str]:
    """Classify hourly production health using observable operational conditions.

    Degraded: failed latest run, missing release/core source, failed current
    quality check, or success/core market data older than six hours.
    Warning: a success or core source older than two/three hours, forecast
    stale/withheld, or current quality/continuity warnings. Expected archive
    weather latency is intentionally excluded from live freshness checks.
    """
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")

    def hours_old(value):
        if value is None or pd.isna(value):
            return None
        stamp = pd.Timestamp(value)
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
        return (current - stamp).total_seconds() / 3600

    status = str(latest_run_status or "").upper()
    success_age = hours_old(latest_success_time)
    source_ages = [hours_old(value) for value in core_source_timestamps.values()]
    if status in {"FAILED", "FAILURE", "ERROR"}:
        return {"label": "Degraded", "level": "error", "reason": "The latest pipeline run failed."}
    if not required_artifacts_available or any(age is None for age in source_ages):
        return {"label": "Degraded", "level": "error", "reason": "A required production release or core ENTSO-E source is unavailable."}
    if quality_state.get("failed", 0):
        return {"label": "Degraded", "level": "error", "reason": "A latest data-quality check failed."}
    if status != "SUCCESS" or success_age is None or success_age > 6 or any(age > 6 for age in source_ages):
        return {"label": "Degraded", "level": "error", "reason": "Pipeline success or core ENTSO-E data is more than six hours old or unavailable."}
    forecast_state = forecast_freshness_state(
        forecast_issue_time, now=current,
        maximum_age_hours=forecast_max_age_hours,
        withholding_known=forecast_withheld,
    )
    if (
        success_age > 2 or any(age > 3 for age in source_ages)
        or forecast_state != "Fresh"
        or quality_state.get("warnings", 0) or unresolved_gap_count
    ):
        return {"label": "Warning", "level": "warning", "reason": "A forecast, source, run, or quality condition needs review."}
    return {"label": "Healthy", "level": "success", "reason": "The hourly pipeline, core market inputs, and production forecast are current."}

def monitoring_coverage_explanation(summary: dict) -> str:
    """Explain existing monitoring coverage gates without changing them."""
    overall = summary.get("overall", {})
    seven_day = summary.get("windows", {}).get("7d", {})
    reasons = []
    if overall.get("pair_count", 0) < MODEL_HEALTH_MIN_PAIRS:
        reasons.append(
            f"{overall.get('pair_count', 0)} matched pairs are available; "
            f"the health assessment requires {MODEL_HEALTH_MIN_PAIRS}"
        )
    if summary.get("target_dates", 0) < MODEL_HEALTH_MIN_TARGET_DATES:
        reasons.append(
            f"coverage spans {summary.get('target_dates', 0)} distinct target dates; "
            f"the health assessment requires {MODEL_HEALTH_MIN_TARGET_DATES}"
        )
    if seven_day.get("status") != "Available":
        reasons.append(
            f"the 7-day window has {seven_day.get('pair_count', 0)} matched pairs; "
            f"window metrics require {MONITORING_MIN_PAIRS}"
        )

    horizons = summary.get("horizons")
    if isinstance(horizons, pd.DataFrame) and not horizons.empty:
        eligible = int(horizons["status"].eq("Available").sum())
        horizon_detail = (
            f"Per-horizon coverage: {eligible} of 24 horizons meet the minimum "
            f"{HORIZON_MIN_PAIRS} realized forecasts."
        )
    else:
        horizon_detail = "Per-horizon coverage is unavailable."
    if not reasons:
        return horizon_detail
    return "; ".join(reasons).capitalize() + ". " + horizon_detail

def model_performance_state(summary: dict, manifest: dict | None) -> dict[str, str]:
    """Conservative operational review heuristic, never an automatic retrain."""
    overall = summary.get("overall", {})
    seven_day = summary.get("windows", {}).get("7d", {})
    if (
        overall.get("pair_count", 0) < MODEL_HEALTH_MIN_PAIRS
        or summary.get("target_dates", 0) < MODEL_HEALTH_MIN_TARGET_DATES
        or seven_day.get("status") != "Available"
    ):
        return {
            "label": "Insufficient data",
            "reason": monitoring_coverage_explanation(summary),
        }
    baseline = (manifest or {}).get("test_metrics", {})
    persistence = (manifest or {}).get("persistence_test_metrics", {})
    try:
        model_rmse = float(baseline["rmse"])
        persistence_rmse = float(persistence["rmse"])
        recent_rmse = float(seven_day["rmse"])
    except (KeyError, TypeError, ValueError):
        return {"label": "Monitoring", "reason": "Live error is monitored; a comparable approved baseline is unavailable."}
    if recent_rmse > max(1.5 * model_rmse, persistence_rmse):
        return {"label": "Review recommended", "reason": "Seven-day live RMSE exceeds both 1.5× approved test RMSE and the approved persistence-test RMSE; compare data regimes before any controlled re-evaluation."}
    return {"label": "Monitoring", "reason": "The conservative review threshold has not been crossed."}
