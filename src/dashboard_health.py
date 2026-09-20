import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd
import streamlit as st


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

    text = " ".join(str(text).split())
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
    environment = os.environ if environment is None else environment
    configured = all(
        str(environment.get(key, "")).strip()
        for key in ALERT_ENVIRONMENT_KEYS
    )
    return "Configured" if configured else None
