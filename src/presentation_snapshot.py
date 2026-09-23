"""Create a truthful, hash-verifiable PowerFlow presentation evidence bundle."""

from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from operational_recovery import git_commit, sha256_file, utc_timestamp


APPROVED_REPORTS = (
    "data/reports/next24h_forecast.csv",
    "data/reports/next24h_forecast_provenance.json",
    "data/reports/next24h_performance.csv",
    "data/reports/final_holdout_metrics.csv",
    "data/reports/actual_vs_predicted.csv",
    "data/reports/detected_anomalies.csv",
    "data/reports/feature_importance.csv",
)
NEXT24H_MANIFEST = "artifacts/models/releases/next24h/next24h_release_manifest.json"
ONE_HOUR_MANIFEST = "artifacts/models/final_model_release_manifest.json"
ONE_HOUR_MODEL = "artifacts/models/final_gold_model.joblib"
_SENSITIVE_KEY = re.compile(
    r"password|secret|token|credential|api.?key|access.?key|authorization", re.I
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)(password|secret|token|credential|api.?key|access.?key|authorization)"
    r"[\"']?\s*[:=]\s*[\"']?(?!\[REDACTED\])([^\s\"'&,;}]+)"
)


def _safe_value(value):
    if isinstance(value, dict):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
            if not _SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [_safe_value(item) for item in value[:100]]
    if isinstance(value, str):
        safe = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", value)
        return _SENSITIVE_VALUE.sub(r"\1=[REDACTED]", safe)[:2000]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:2000]


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(_safe_value(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_only_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def operational_summaries(database_path: Path, *, limit: int = 25) -> dict:
    """Read recent operational evidence without mutating SQLite."""
    database_path = Path(database_path)
    if not database_path.is_file():
        return {"available": False, "incidents": [], "stage_timings": [], "latest_successful_run": None}
    with _read_only_connection(database_path) as connection:
        incidents = []
        if _table_exists(connection, "operational_incidents"):
            rows = connection.execute(
                """
                SELECT timestamp_utc, severity, component, event_type, status,
                       message, details_json
                FROM operational_incidents ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            for timestamp, severity, component, event_type, status, message, details in rows:
                try:
                    parsed_details = json.loads(details or "{}")
                except (TypeError, json.JSONDecodeError):
                    parsed_details = {}
                incidents.append(
                    _safe_value(
                        {
                            "timestamp_utc": timestamp,
                            "severity": severity,
                            "component": component,
                            "event_type": event_type,
                            "status": status,
                            "message": message,
                            "details": parsed_details,
                        }
                    )
                )

        stage_timings = []
        if _table_exists(connection, "pipeline_stage_timings"):
            columns = (
                "run_id", "stage_name", "start_timestamp_utc",
                "end_timestamp_utc", "duration_seconds", "status",
            )
            rows = connection.execute(
                """
                SELECT run_id, stage_name, start_timestamp_utc,
                       end_timestamp_utc, duration_seconds, status
                FROM pipeline_stage_timings ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            stage_timings = [_safe_value(dict(zip(columns, row))) for row in rows]

        latest_successful = None
        if _table_exists(connection, "pipeline_runs"):
            row = connection.execute(
                """
                SELECT run_time, status, records_processed, message
                FROM pipeline_runs WHERE status = 'SUCCESS'
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            if row:
                message = row[3]
                try:
                    message = json.loads(message)
                except (TypeError, json.JSONDecodeError):
                    pass
                latest_successful = _safe_value(
                    {
                        "run_time": row[0],
                        "status": row[1],
                        "records_processed": row[2],
                        "message": message,
                    }
                )
    return {
        "available": True,
        "incidents": incidents,
        "stage_timings": stage_timings,
        "latest_successful_run": latest_successful,
    }


def _latest_forecast_issue(path: Path) -> str | None:
    if not path.is_file():
        return None
    with path.open(newline="", encoding="utf-8") as handle:
        values = [
            row.get("forecast_issue_time")
            for row in csv.DictReader(handle)
            if row.get("forecast_issue_time")
        ]
    return max(values) if values else None


def _reject_credential_content(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    if re.search(r"(?i)\bBearer\s+(?!\[REDACTED\])\S+", text) or _SENSITIVE_VALUE.search(text):
        raise ValueError(f"Credential-like content detected in approved file: {path.name}")


def create_presentation_snapshot(
    project_root: Path,
    *,
    output_root: Path,
    database_path: Path,
    now: datetime | None = None,
) -> Path:
    """Create a unique evidence directory from approved existing artifacts only."""
    project_root = Path(project_root).resolve()
    snapshot_dir = Path(output_root) / utc_timestamp(now)
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    snapshot_dir.chmod(0o700)
    included = []
    missing = []
    try:
        for relative in APPROVED_REPORTS:
            source = project_root / relative
            if not source.is_file():
                missing.append(relative)
                continue
            if source.is_symlink() or project_root not in source.resolve().parents:
                raise ValueError(f"Approved report must be a regular project file: {relative}")
            _reject_credential_content(source)
            destination = snapshot_dir / source.name
            shutil.copy2(source, destination)
            destination.chmod(0o600)
            included.append(destination)

        summaries = operational_summaries(database_path)
        if summaries["available"]:
            generated = {
                "operational_incidents_summary.json": summaries["incidents"],
                "pipeline_stage_timings_summary.json": summaries["stage_timings"],
                "latest_successful_pipeline_run.json": summaries[
                    "latest_successful_run"
                ],
            }
            for filename, value in generated.items():
                destination = snapshot_dir / filename
                _write_json(destination, value)
                destination.chmod(0o600)
                included.append(destination)
        else:
            missing.extend(
                [
                    "operational_incidents_summary.json",
                    "pipeline_stage_timings_summary.json",
                    "latest_successful_pipeline_run.json",
                ]
            )

        next24h_manifest = _read_json(project_root / NEXT24H_MANIFEST)
        one_hour_manifest = _read_json(project_root / ONE_HOUR_MANIFEST)
        one_hour_model = project_root / ONE_HOUR_MODEL
        latest_run = summaries.get("latest_successful_run")
        manifest = {
            "created_at_utc": (
                datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
            ).isoformat(),
            "git_commit": git_commit(project_root),
            "files_included": [
                {
                    "name": path.name,
                    "sha256": sha256_file(path),
                    "file_size_bytes": path.stat().st_size,
                }
                for path in sorted(included)
            ],
            "missing_optional_files": sorted(missing),
            "next24h_release_id": next24h_manifest.get("release_id"),
            "one_hour_release": {
                "release_type": one_hour_manifest.get("release_type"),
                "model_name": one_hour_manifest.get("model", {}).get(
                    "selected_model"
                ),
                "feature_count": one_hour_manifest.get("model", {}).get(
                    "feature_count"
                ),
                "model_sha256": sha256_file(one_hour_model)
                if one_hour_model.is_file()
                else None,
            },
            "latest_forecast_issue_time": _latest_forecast_issue(
                project_root / "data/reports/next24h_forecast.csv"
            ),
            "latest_successful_pipeline_time": latest_run.get("run_time")
            if latest_run
            else None,
            "market_zone": "DE-LU",
            "evidence_note": (
                "Historical production evidence captured from an existing successful "
                "state; this snapshot is not live data."
            ),
        }
        manifest_path = snapshot_dir / "snapshot_manifest.json"
        _write_json(manifest_path, manifest)
        manifest_path.chmod(0o600)
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise
    return snapshot_dir
