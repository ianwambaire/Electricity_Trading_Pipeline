"""Safe backup, validation, and restore helpers for PowerFlow operational SQLite."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_OPERATIONAL_TABLES = frozenset(
    {
        "pipeline_runs",
        "data_quality_results",
        "operational_incidents",
        "pipeline_stage_timings",
    }
)
_SENSITIVE_FILENAME = re.compile(
    r"(^|[._-])(\.env|credentials?|secrets?|id_[rd]sa|.*\.pem|.*\.key)([._-]|$)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)(password|secret|token|credential|api.?key|access.?key|authorization)"
    r"[\"']?\s*[:=]\s*[\"']?(?!\[REDACTED\])([^\s\"'&,;}]+)"
)


def utc_timestamp(now: datetime | None = None) -> str:
    value = datetime.now(timezone.utc) if now is None else now
    if value.tzinfo is None:
        raise ValueError("Backup timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit(project_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def _read_only_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)


def sqlite_table_names(connection: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
    ]


def sqlite_schema_objects(connection: sqlite3.Connection) -> list[dict]:
    return [
        {"type": row[0], "name": row[1], "table": row[2], "sql": row[3]}
        for row in connection.execute(
            """
            SELECT type, name, tbl_name, sql FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%' AND type IN ('table', 'index', 'view')
            ORDER BY type, name
            """
        )
    ]


def _assert_no_live_credentials(connection: sqlite3.Connection) -> None:
    """Refuse to preserve obvious unredacted credentials in live text values."""
    for table in sqlite_table_names(connection):
        quoted_table = table.replace('"', '""')
        columns = [
            row[1]
            for row in connection.execute(f'PRAGMA table_info("{quoted_table}")')
        ]
        if not columns:
            continue
        quoted_columns = ", ".join(
            f'"{column.replace(chr(34), chr(34) * 2)}"' for column in columns
        )
        for row in connection.execute(
            f'SELECT {quoted_columns} FROM "{quoted_table}"'
        ):
            if any(
                isinstance(value, str) and _SENSITIVE_VALUE.search(value)
                for value in row
            ):
                raise ValueError(
                    f"Credential-like content detected in operational table {table}; "
                    "backup was refused."
                )


def _safe_backup_name(source_db: Path) -> str:
    name = Path(source_db).name
    if _SENSITIVE_FILENAME.search(name):
        raise ValueError("Operational database filename looks credential-related.")
    return name


def backup_operational_database(
    source_db: Path,
    *,
    backup_root: Path,
    project_root: Path,
    now: datetime | None = None,
) -> Path:
    """Create a consistent SQLite backup plus a hash-verifiable manifest."""
    source_db = Path(source_db).resolve()
    if not source_db.is_file():
        raise FileNotFoundError(f"Operational database not found: {source_db}")
    destination_dir = Path(backup_root) / utc_timestamp(now)
    destination_dir.mkdir(parents=True, exist_ok=False)
    destination_dir.chmod(0o700)
    destination_db = destination_dir / _safe_backup_name(source_db)
    temporary_db = destination_dir / f".{destination_db.name}.tmp"
    try:
        with _read_only_connection(source_db) as source:
            _assert_no_live_credentials(source)
            with sqlite3.connect(temporary_db) as destination:
                source.backup(destination)
                # Compact only the backup so deleted/free pages from the source
                # are not carried into the recovery artifact.
                destination.execute("VACUUM")
        os.replace(temporary_db, destination_db)
        destination_db.chmod(0o600)
        with _read_only_connection(destination_db) as connection:
            tables = sqlite_table_names(connection)
            schema_objects = sqlite_schema_objects(connection)
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite backup integrity check failed: {integrity}")
        manifest = {
            "backup_time_utc": datetime.now(timezone.utc).isoformat()
            if now is None
            else now.astimezone(timezone.utc).isoformat(),
            "source_db": str(source_db),
            "backup_db": destination_db.name,
            "sha256": sha256_file(destination_db),
            "file_size_bytes": destination_db.stat().st_size,
            "git_commit": git_commit(Path(project_root)),
            "tables": tables,
            "schema_objects": schema_objects,
        }
        manifest_path = destination_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest_path.chmod(0o600)
    except Exception:
        temporary_db.unlink(missing_ok=True)
        destination_db.unlink(missing_ok=True)
        (destination_dir / "manifest.json").unlink(missing_ok=True)
        try:
            destination_dir.rmdir()
        except OSError:
            pass
        raise
    return destination_dir


def validate_operational_backup(
    backup_dir: Path,
    *,
    expected_tables: frozenset[str] = EXPECTED_OPERATIONAL_TABLES,
) -> dict:
    """Validate a backup without opening or modifying the production database."""
    backup_dir = Path(backup_dir).resolve()
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Backup manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup_name = manifest.get("backup_db")
    if not isinstance(backup_name, str) or Path(backup_name).name != backup_name:
        raise ValueError("Backup manifest contains an unsafe database path.")
    backup_db = backup_dir / backup_name
    if not backup_db.is_file():
        raise FileNotFoundError(f"Backup database not found: {backup_db}")
    actual_hash = sha256_file(backup_db)
    if actual_hash != manifest.get("sha256"):
        raise ValueError("Backup SHA-256 does not match the manifest.")
    if backup_db.stat().st_size != manifest.get("file_size_bytes"):
        raise ValueError("Backup file size does not match the manifest.")

    with _read_only_connection(backup_db) as connection:
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"SQLite integrity check failed: {integrity}")
        tables = sqlite_table_names(connection)
        if sorted(manifest.get("tables", [])) != tables:
            raise ValueError("Backup table list does not match the manifest.")
        missing = sorted(expected_tables - set(tables))
        if missing:
            raise ValueError(
                "Backup is missing expected operational tables: " + ", ".join(missing)
            )
        row_counts = {
            table: int(
                connection.execute(
                    f'SELECT COUNT(*) FROM "{table.replace(chr(34), chr(34) * 2)}"'
                ).fetchone()[0]
            )
            for table in sorted(expected_tables)
        }
    return {
        "status": "valid",
        "backup_dir": str(backup_dir),
        "backup_db": str(backup_db),
        "sha256": actual_hash,
        "tables": tables,
        "row_counts": row_counts,
    }


def restore_operational_database(
    backup_dir: Path,
    destination_db: Path,
    *,
    force: bool = False,
    pre_restore_root: Path | None = None,
    project_root: Path = Path("."),
) -> dict:
    """Restore to an explicit destination, protecting existing files by default."""
    validation = validate_operational_backup(backup_dir)
    source_db = Path(validation["backup_db"])
    destination_db = Path(destination_db).resolve()
    pre_restore_backup = None
    if destination_db.exists():
        if not force:
            raise FileExistsError(
                "Restore destination exists; pass --force to permit an overwrite."
            )
        pre_restore_backup = backup_operational_database(
            destination_db,
            backup_root=pre_restore_root
            or destination_db.parent / "pre_restore_backups",
            project_root=project_root,
        )

    destination_db.parent.mkdir(parents=True, exist_ok=True)
    temporary_db = destination_db.with_name(f".{destination_db.name}.restore.tmp")
    if temporary_db.exists():
        raise FileExistsError(f"Restore temporary file already exists: {temporary_db}")
    try:
        with _read_only_connection(source_db) as source:
            with sqlite3.connect(temporary_db) as destination:
                source.backup(destination)
        with _read_only_connection(temporary_db) as restored:
            integrity = restored.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"Restored SQLite integrity check failed: {integrity}")
        os.replace(temporary_db, destination_db)
    finally:
        temporary_db.unlink(missing_ok=True)
    return {
        "status": "restored",
        "destination_db": str(destination_db),
        "source_backup": str(Path(backup_dir).resolve()),
        "pre_restore_backup": str(pre_restore_backup) if pre_restore_backup else None,
    }
