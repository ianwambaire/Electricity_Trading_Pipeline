import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd
import streamlit as st

from powerflow_secrets import secret_is_configured


PIPELINE_HISTORY_COLUMNS = [
    "id",
    "run_time",
    "status",
    "records_processed",
    "message",
]
DATA_QUALITY_HISTORY_COLUMNS = [
    "id",
    "check_time",
    "check_name",
    "status",
    "message",
]
INCIDENT_COLUMNS = [
    "id", "timestamp_utc", "severity", "component", "event_type",
    "status", "message", "details_json",
]
STAGE_TIMING_COLUMNS = [
    "id", "run_id", "stage_name", "start_timestamp_utc",
    "end_timestamp_utc", "duration_seconds", "status",
]
ALERT_ENVIRONMENT_KEYS = (
    "ALERT_EMAIL_SENDER",
    "ALERT_EMAIL_PASSWORD",
    "ALERT_EMAIL_RECEIVER",
)


def _file_mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _empty_history(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _open_read_only_database(path_string: str) -> sqlite3.Connection:
    database_uri = f"{Path(path_string).resolve().as_uri()}?mode=ro"
    return sqlite3.connect(database_uri, uri=True)


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return (
        connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            LIMIT 1
            """,
            (table_name,),
        ).fetchone()
        is not None
    )


@st.cache_data(show_spinner=False)
def _load_recent_pipeline_history_versioned(
    path_string: str,
    modification_time_ns: int | None,
    limit: int,
) -> pd.DataFrame:
    if modification_time_ns is None:
        return _empty_history(PIPELINE_HISTORY_COLUMNS)

    try:
        with closing(_open_read_only_database(path_string)) as connection:
            if not _table_exists(connection, "pipeline_runs"):
                return _empty_history(PIPELINE_HISTORY_COLUMNS)
            return pd.read_sql_query(
                """
                SELECT id, run_time, status, records_processed, message
                FROM pipeline_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                connection,
                params=(limit,),
            )
    except (OSError, sqlite3.Error, pd.errors.DatabaseError):
        return _empty_history(PIPELINE_HISTORY_COLUMNS)


def load_recent_pipeline_history(
    path: Path,
    limit: int = 10,
) -> pd.DataFrame:
    """Read recent pipeline runs from SQLite without opening it for writes."""
    path = Path(path)
    return _load_recent_pipeline_history_versioned(
        str(path),
        _file_mtime_ns(path),
        max(1, min(int(limit), 100)),
    )


@st.cache_data(show_spinner=False)
def _load_recent_data_quality_history_versioned(
    path_string: str,
    modification_time_ns: int | None,
    limit: int,
) -> pd.DataFrame:
    if modification_time_ns is None:
        return _empty_history(DATA_QUALITY_HISTORY_COLUMNS)

    try:
        with closing(_open_read_only_database(path_string)) as connection:
            if not _table_exists(connection, "data_quality_results"):
                return _empty_history(DATA_QUALITY_HISTORY_COLUMNS)
            return pd.read_sql_query(
                """
                SELECT id, check_time, check_name, status, message
                FROM data_quality_results
                ORDER BY id DESC
                LIMIT ?
                """,
                connection,
                params=(limit,),
            )
    except (OSError, sqlite3.Error, pd.errors.DatabaseError):
        return _empty_history(DATA_QUALITY_HISTORY_COLUMNS)


def load_recent_data_quality_history(
    path: Path,
    limit: int = 20,
) -> pd.DataFrame:
    """Read recent quality checks from SQLite without opening it for writes."""
    path = Path(path)
    return _load_recent_data_quality_history_versioned(
        str(path),
        _file_mtime_ns(path),
        max(1, min(int(limit), 100)),
    )


@st.cache_data(show_spinner=False)
def _load_latest_successful_run_time_versioned(
    path_string: str,
    modification_time_ns: int | None,
) -> str | None:
    if modification_time_ns is None:
        return None

    try:
        with closing(_open_read_only_database(path_string)) as connection:
            if not _table_exists(connection, "pipeline_runs"):
                return None
            row = connection.execute(
                """
                SELECT run_time
                FROM pipeline_runs
                WHERE UPPER(status) = 'SUCCESS'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
    except (OSError, sqlite3.Error):
        return None

    return row[0] if row else None


def load_latest_successful_run_time(path: Path) -> str | None:
    path = Path(path)
    return _load_latest_successful_run_time_versioned(
        str(path),
        _file_mtime_ns(path),
    )


def parse_operational_metadata(message) -> dict | None:
    if not isinstance(message, str):
        return None
    try:
        parsed = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def redact_operational_text(value) -> str:
    """Mask common credential forms in legacy free-text operational messages."""
    text = str(value)
    text = re.sub(r"(?i)\bBearer\s+[^\s&,;]+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)\b(password|secret|token|api[_-]?key|access[_-]?key|authorization)"
        r"\s*[:=]\s*[^\s&,;]+",
        r"\1=[REDACTED]",
        text,
    )
    return re.sub(r"(?i)(://)[^\s/:@]+:[^\s@]+@", r"\1[REDACTED]@", text)


def concise_history_message(message, max_length: int = 160) -> str:
    """Render operational messages without exposing bulky JSON arrays."""
    metadata = parse_operational_metadata(message)
    if metadata is not None:
        text = metadata.get("message")
        if not text and "first_unresolved_timestamp" in metadata:
            missing_count = metadata.get("missing_count")
            first_unresolved = metadata.get("first_unresolved_timestamp")
            parts = []
            if missing_count is not None:
                parts.append(f"{missing_count} missing timestamps")
            if first_unresolved:
                parts.append(f"first unresolved {first_unresolved}")
            text = "; ".join(parts) or "Source continuity warning recorded."
        if not text:
            text = "Operational metadata recorded."
    else:
        text = str(message or "No message recorded.")

    text = " ".join(redact_operational_text(text).split())
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1].rstrip()}…"


def prepare_pipeline_history(history: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for record in history.to_dict(orient="records"):
        metadata = parse_operational_metadata(record.get("message")) or {}
        rows.append(
            {
                "Run Time": record.get("run_time"),
                "Status": record.get("status"),
                "Rows": metadata.get(
                    "new_rows_ingested",
                    record.get("records_processed"),
                ),
                "Message": concise_history_message(record.get("message")),
            }
        )
    return pd.DataFrame(rows, columns=["Run Time", "Status", "Rows", "Message"])


def prepare_data_quality_history(history: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {
            "Check Time": record.get("check_time"),
            "Check Name": record.get("check_name"),
            "Status": record.get("status"),
            "Message": concise_history_message(record.get("message")),
        }
        for record in history.to_dict(orient="records")
    ]
    return pd.DataFrame(
        rows,
        columns=["Check Time", "Check Name", "Status", "Message"],
    )


def count_quality_statuses(history: pd.DataFrame) -> dict[str, int]:
    if "status" not in history.columns:
        return {"passed": 0, "failed": 0, "warnings": 0}
    statuses = history["status"].fillna("").astype(str).str.upper()
    return {
        "passed": int(statuses.isin({"PASSED", "SUCCESS"}).sum()),
        "failed": int(statuses.isin({"FAILED", "FAILURE", "ERROR"}).sum()),
        "warnings": int(statuses.eq("WARNING").sum()),
    }


def derive_system_health(
    latest_run_status,
    failed_quality_checks: int,
    quality_warnings: int,
    continuity_warnings: int,
) -> dict[str, str]:
    status = str(latest_run_status or "").upper()
    if status in {"FAILED", "FAILURE", "ERROR"} or failed_quality_checks > 0:
        return {
            "label": "Attention required",
            "level": "error",
            "reason": (
                "The latest pipeline run failed or at least one recent "
                "data-quality check failed."
            ),
        }
    if status == "SUCCESS" and (quality_warnings > 0 or continuity_warnings > 0):
        return {
            "label": "Operational with warnings",
            "level": "warning",
            "reason": (
                "The latest pipeline run succeeded, but recent quality or "
                "source-continuity warnings remain."
            ),
        }
    if status == "SUCCESS":
        return {
            "label": "Operational",
            "level": "success",
            "reason": (
                "The latest pipeline run succeeded with no failed recent "
                "quality checks or unresolved source warnings."
            ),
        }
    return {
        "label": "Status unavailable",
        "level": "info",
        "reason": "No recent pipeline status is available to evaluate.",
    }


def alert_configuration_status(environment=None) -> str | None:
    """Return only a non-secret configuration state for failure email alerts."""
    configured = all(
        secret_is_configured(key, environment=environment)
        for key in ALERT_ENVIRONMENT_KEYS
    )
    return "Configured" if configured else "Not configured"


@st.cache_data(show_spinner=False)
def _load_incidents_versioned(path_string, modification_time_ns, limit):
    if modification_time_ns is None:
        return _empty_history(INCIDENT_COLUMNS)
    try:
        with closing(_open_read_only_database(path_string)) as connection:
            if not _table_exists(connection, "operational_incidents"):
                return _empty_history(INCIDENT_COLUMNS)
            return pd.read_sql_query(
                """
                SELECT id, timestamp_utc, severity, component, event_type,
                       status, message, details_json
                FROM operational_incidents ORDER BY id DESC LIMIT ?
                """, connection, params=(limit,),
            )
    except (OSError, sqlite3.Error, pd.errors.DatabaseError):
        return _empty_history(INCIDENT_COLUMNS)


def load_recent_incidents(path: Path, limit: int = 100) -> pd.DataFrame:
    path = Path(path)
    return _load_incidents_versioned(
        str(path), _file_mtime_ns(path), max(1, min(int(limit), 500))
    )


def filter_incidents(
    history: pd.DataFrame,
    *,
    severity: str = "All",
    component: str = "All",
    period: str = "All",
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if history.empty:
        return history.copy()
    visible = history.copy()
    if severity != "All":
        visible = visible.loc[visible["severity"] == severity]
    if component != "All":
        visible = visible.loc[visible["component"] == component]
    if period != "All":
        duration = {
            "24 hours": pd.Timedelta(hours=24),
            "7 days": pd.Timedelta(days=7),
            "30 days": pd.Timedelta(days=30),
        }[period]
        current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
        current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
        timestamps = pd.to_datetime(visible["timestamp_utc"], errors="coerce", utc=True)
        visible = visible.loc[timestamps >= current - duration]
    return visible


@st.cache_data(show_spinner=False)
def _load_stage_timings_versioned(path_string, modification_time_ns, limit):
    if modification_time_ns is None:
        return _empty_history(STAGE_TIMING_COLUMNS)
    try:
        with closing(_open_read_only_database(path_string)) as connection:
            if not _table_exists(connection, "pipeline_stage_timings"):
                return _empty_history(STAGE_TIMING_COLUMNS)
            return pd.read_sql_query(
                """
                SELECT id, run_id, stage_name, start_timestamp_utc,
                       end_timestamp_utc, duration_seconds, status
                FROM pipeline_stage_timings ORDER BY id DESC LIMIT ?
                """, connection, params=(limit,),
            )
    except (OSError, sqlite3.Error, pd.errors.DatabaseError):
        return _empty_history(STAGE_TIMING_COLUMNS)


def load_recent_stage_timings(path: Path, limit: int = 200) -> pd.DataFrame:
    path = Path(path)
    return _load_stage_timings_versioned(
        str(path), _file_mtime_ns(path), max(1, min(int(limit), 1000))
    )


def summarize_pipeline_timings(timings: pd.DataFrame) -> dict | None:
    if timings.empty or not {"stage_name", "run_id", "duration_seconds", "status"}.issubset(timings):
        return None
    totals = timings.loc[timings["stage_name"] == "Total pipeline"]
    if totals.empty:
        return None
    latest = totals.iloc[0]
    current = timings.loc[timings["run_id"] == latest["run_id"]]
    successful = totals.loc[totals["status"] == "SUCCESS"].head(10)
    forecast = current.loc[current["stage_name"] == "Next24h forecast generation"]
    stages = current.loc[current["stage_name"] != "Total pipeline"]
    slowest = stages.sort_values("duration_seconds", ascending=False).iloc[0] if not stages.empty else None
    return {
        "run_id": latest["run_id"],
        "latest_total_seconds": float(latest["duration_seconds"]),
        "recent_average_seconds": float(successful["duration_seconds"].mean()) if not successful.empty else None,
        "latest_forecast_seconds": float(forecast.iloc[0]["duration_seconds"]) if not forecast.empty else None,
        "slowest_stage": str(slowest["stage_name"]) if slowest is not None else None,
        "latest_run_timings": current,
    }


def age_label(timestamp, *, now: pd.Timestamp | None = None) -> str:
    if timestamp is None or pd.isna(timestamp):
        return "Unavailable"
    try:
        value = pd.Timestamp(timestamp)
    except (TypeError, ValueError):
        return "Unavailable"
    value = value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    minutes = (current - value).total_seconds() / 60
    if minutes < 0:
        return "Future timestamp"
    if minutes < 60:
        return f"{minutes:.0f} min ago"
    if minutes < 48 * 60:
        return f"{minutes / 60:.1f} hours old"
    return f"{minutes / 1440:.1f} days old"


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


def model_performance_state(summary: dict, manifest: dict | None) -> dict[str, str]:
    """Conservative operational review heuristic, never an automatic retrain."""
    overall = summary.get("overall", {})
    seven_day = summary.get("windows", {}).get("7d", {})
    if overall.get("pair_count", 0) < 100 or summary.get("target_dates", 0) < 7 or seven_day.get("status") != "Available":
        return {"label": "Insufficient data", "reason": "Insufficient realized forecasts for production performance assessment."}
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
