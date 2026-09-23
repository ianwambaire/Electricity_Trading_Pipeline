import sqlite3
import json
import re
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone


DATABASE_PATH = Path("database/electricity_trading.db")
SCHEMA_PATH = Path("database/schema.sql")


def initialize_database():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)

    with open(SCHEMA_PATH, "r") as schema_file:
        schema = schema_file.read()

    connection.executescript(schema)
    connection.commit()
    connection.close()


def store_clean_data(data: pd.DataFrame):
    """Store data for the legacy EIA pipeline; unused by the ENTSO-E flow."""
    connection = sqlite3.connect(DATABASE_PATH)

    data.to_sql(
        "clean_market_data",
        connection,
        if_exists="replace",
        index=False
    )

    connection.close()


def log_pipeline_run(status: str, records_processed: int, message: str):
    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO pipeline_runs
        (run_time, status, records_processed, message)
        VALUES (?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            status,
            records_processed,
            message
        )
    )

    connection.commit()
    connection.close()


def log_data_quality_result(check_name: str, status: str, message: str):
    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO data_quality_results
        (check_time, check_name, status, message)
        VALUES (?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            check_name,
            status,
            message
        )
    )

    connection.commit()
    connection.close()


_SENSITIVE_KEY = re.compile(r"password|secret|token|credential|api.?key|access.?key|authorization", re.I)
_SENSITIVE_VALUE = re.compile(
    r"(?i)(password|secret|token|credential|api.?key|access.?key|authorization)"
    r"\s*[:=]\s*([^\s&,;]+)"
)


def _safe_incident_value(value):
    if isinstance(value, dict):
        return {
            str(key): _safe_incident_value(item)
            for key, item in value.items()
            if not _SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_incident_value(item) for item in value[:20]]
    if isinstance(value, str):
        safe = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", value)
        return _SENSITIVE_VALUE.sub(r"\1=[REDACTED]", safe)[:500]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:500]


def log_incident(
    severity: str,
    component: str,
    event_type: str,
    status: str,
    message: str,
    details: dict | None = None,
    *,
    dedupe_minutes: int = 60,
) -> bool:
    """Persist a safe event; suppress identical repeats within one hour."""
    if severity not in {"INFO", "WARNING", "ERROR"}:
        raise ValueError("Incident severity must be INFO, WARNING or ERROR.")
    if dedupe_minutes < 0:
        raise ValueError("Incident dedupe interval cannot be negative.")
    recorded_at = datetime.now(timezone.utc)
    safe_message = _safe_incident_value(str(message))[:300]
    safe_details = json.dumps(_safe_incident_value(details or {}), sort_keys=True)
    with sqlite3.connect(DATABASE_PATH) as connection:
        prior = connection.execute(
            """
            SELECT timestamp_utc FROM operational_incidents
            WHERE component = ? AND event_type = ? AND status = ?
              AND message = ? AND details_json = ?
            ORDER BY id DESC LIMIT 1
            """,
            (component, event_type, status, safe_message, safe_details),
        ).fetchone()
        if prior and recorded_at - datetime.fromisoformat(prior[0]) < timedelta(minutes=dedupe_minutes):
            return False
        connection.execute(
            """
            INSERT INTO operational_incidents
                (timestamp_utc, severity, component, event_type, status, message, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recorded_at.isoformat(), severity, component, event_type,
                status, safe_message, safe_details,
            ),
        )
    return True


def incident_is_active(component: str, event_type: str) -> bool:
    with sqlite3.connect(DATABASE_PATH) as connection:
        row = connection.execute(
            """
            SELECT status FROM operational_incidents
            WHERE component = ? AND event_type = ?
            ORDER BY id DESC LIMIT 1
            """,
            (component, event_type),
        ).fetchone()
    return bool(row and row[0] == "ACTIVE")


def failure_alert_cooldown_active(
    fingerprint: str,
    cooldown_hours: float,
    *,
    now: datetime | None = None,
) -> bool:
    """Check the last successfully sent email for a safe failure fingerprint."""
    current = datetime.now(timezone.utc) if now is None else now
    if current.tzinfo is None:
        raise ValueError("Alert cooldown time must be timezone-aware.")
    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            """
            SELECT timestamp_utc, details_json
            FROM operational_incidents
            WHERE component = 'email alerts'
              AND event_type = 'failure_alert_sent'
              AND status = 'RECORDED'
            ORDER BY id DESC
            """
        ).fetchall()
    for timestamp_utc, details_json in rows:
        try:
            details = json.loads(details_json or "{}")
            sent_at = datetime.fromisoformat(timestamp_utc)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if details.get("fingerprint") == fingerprint:
            return current - sent_at < timedelta(hours=cooldown_hours)
    return False


def log_stage_timing(
    run_id: str,
    stage_name: str,
    start_timestamp_utc: str,
    end_timestamp_utc: str,
    duration_seconds: float,
    status: str,
) -> None:
    if not run_id or duration_seconds < 0 or status not in {"SUCCESS", "FAILED", "WITHHELD"}:
        raise ValueError("Invalid pipeline stage timing.")
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            INSERT INTO pipeline_stage_timings
                (run_id, stage_name, start_timestamp_utc, end_timestamp_utc,
                 duration_seconds, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, stage_name, start_timestamp_utc, end_timestamp_utc,
             float(duration_seconds), status),
        )
