"""Safe backup, validation, and restore helpers for PowerFlow operational SQLite."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
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
OPERATIONAL_BACKUP_PREFIX = "backups/operational"
_BACKUP_ID = re.compile(r"^\d{8}T\d{6}\.\d{6}Z$")
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


def _source_relative_path(source_db: Path, project_root: Path) -> str:
    try:
        return source_db.relative_to(Path(project_root).resolve()).as_posix()
    except ValueError:
        return source_db.name


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
            "source_db_relative": _source_relative_path(source_db, project_root),
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


def _safe_backup_id(value: str) -> str:
    backup_id = str(value).strip()
    if not _BACKUP_ID.fullmatch(backup_id):
        raise ValueError("Operational backup ID must be a UTC timestamp directory name.")
    return backup_id


def _s3_not_found(error: Exception) -> bool:
    response = getattr(error, "response", {})
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404


def _s3_precondition_failed(error: Exception) -> bool:
    response = getattr(error, "response", {})
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"PreconditionFailed", "412"} or status == 412


def _s3_object_exists(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as error:
        if _s3_not_found(error):
            return False
        raise


def _put_new_s3_object(
    client,
    bucket: str,
    key: str,
    source: Path,
    *,
    metadata: dict[str, str],
) -> None:
    try:
        with Path(source).open("rb") as body:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentLength=Path(source).stat().st_size,
                Metadata=metadata,
                IfNoneMatch="*",
            )
    except Exception as error:
        if _s3_precondition_failed(error):
            raise FileExistsError(
                f"Operational backup object already exists: s3://{bucket}/{key}"
            ) from None
        raise


def upload_operational_backup(
    backup_dir: Path,
    *,
    bucket: str,
    client,
    prefix: str = OPERATIONAL_BACKUP_PREFIX,
) -> dict:
    """Upload a locally validated backup without replacing any S3 object."""
    if not str(bucket).strip():
        raise ValueError("An S3 bucket is required for operational backup upload.")
    validation = validate_operational_backup(backup_dir)
    backup_dir = Path(validation["backup_dir"])
    backup_id = _safe_backup_id(backup_dir.name)
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup_db = Path(validation["backup_db"])
    normalized_prefix = str(prefix).strip("/")
    base_key = f"{normalized_prefix}/{backup_id}"
    objects = {
        "database": f"{base_key}/{backup_db.name}",
        "manifest": f"{base_key}/manifest.json",
    }

    # Validation deliberately precedes every S3 operation. Both this explicit
    # check and If-None-Match protect timestamped backups from replacement.
    existing = [
        key for key in objects.values() if _s3_object_exists(client, bucket, key)
    ]
    if existing:
        raise FileExistsError(
            "Timestamped operational backup already exists in S3: "
            + ", ".join(existing)
        )

    shared_metadata = {
        "backup-timestamp": backup_id,
        "database-sha256": str(manifest["sha256"]),
        "database-size-bytes": str(manifest["file_size_bytes"]),
        "source-db-relative": str(manifest["source_db_relative"]),
    }
    _put_new_s3_object(
        client,
        bucket,
        objects["database"],
        backup_db,
        metadata={**shared_metadata, "artifact": "sqlite-database"},
    )
    _put_new_s3_object(
        client,
        bucket,
        objects["manifest"],
        manifest_path,
        metadata={**shared_metadata, "artifact": "backup-manifest"},
    )
    return {
        "status": "uploaded",
        "bucket": bucket,
        "prefix": normalized_prefix,
        "backup_id": backup_id,
        "sha256": validation["sha256"],
        "objects": objects,
    }


def list_operational_backups(
    *,
    bucket: str,
    client,
    prefix: str = OPERATIONAL_BACKUP_PREFIX,
) -> list[dict]:
    """List complete timestamped operational backup object sets."""
    normalized_prefix = str(prefix).strip("/")
    query_prefix = f"{normalized_prefix}/"
    keys: list[str] = []
    continuation = None
    while True:
        arguments = {"Bucket": bucket, "Prefix": query_prefix}
        if continuation:
            arguments["ContinuationToken"] = continuation
        page = client.list_objects_v2(**arguments)
        keys.extend(item["Key"] for item in page.get("Contents", []))
        if not page.get("IsTruncated"):
            break
        continuation = page.get("NextContinuationToken")
        if not continuation:
            raise RuntimeError("S3 backup listing was truncated without a continuation token.")

    grouped: dict[str, list[str]] = {}
    for key in keys:
        relative = key.removeprefix(query_prefix)
        parts = relative.split("/", 1)
        if len(parts) == 2 and _BACKUP_ID.fullmatch(parts[0]):
            grouped.setdefault(parts[0], []).append(key)
    return [
        {"backup_id": backup_id, "objects": sorted(object_keys)}
        for backup_id, object_keys in sorted(grouped.items(), reverse=True)
        if f"{query_prefix}{backup_id}/manifest.json" in object_keys
        and len(object_keys) >= 2
    ]


def download_operational_backup(
    backup_id: str,
    *,
    bucket: str,
    client,
    download_root: Path,
    prefix: str = OPERATIONAL_BACKUP_PREFIX,
) -> dict:
    """Download one explicit S3 backup and validate it before making it visible."""
    backup_id = _safe_backup_id(backup_id)
    normalized_prefix = str(prefix).strip("/")
    base_key = f"{normalized_prefix}/{backup_id}"
    download_root = Path(download_root).resolve()
    destination = download_root / backup_id
    if destination.exists():
        raise FileExistsError(f"Downloaded backup destination already exists: {destination}")
    download_root.mkdir(parents=True, exist_ok=True)
    temporary = download_root / f".{backup_id}.downloading-{uuid.uuid4().hex}"
    temporary.mkdir(mode=0o700)
    try:
        manifest_path = temporary / "manifest.json"
        client.download_file(bucket, f"{base_key}/manifest.json", str(manifest_path))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        backup_name = manifest.get("backup_db")
        if not isinstance(backup_name, str) or Path(backup_name).name != backup_name:
            raise ValueError("Downloaded backup manifest contains an unsafe database path.")
        client.download_file(bucket, f"{base_key}/{backup_name}", str(temporary / backup_name))
        validate_operational_backup(temporary)
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    validation = validate_operational_backup(destination)
    return {
        "status": "downloaded_and_validated",
        "bucket": bucket,
        "backup_id": backup_id,
        "backup_dir": str(destination),
        "sha256": validation["sha256"],
    }


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


def restore_operational_database_from_s3(
    backup_id: str,
    destination_db: Path,
    *,
    bucket: str,
    client,
    download_root: Path,
    force: bool = False,
    pre_restore_root: Path | None = None,
    project_root: Path = Path("."),
    prefix: str = OPERATIONAL_BACKUP_PREFIX,
) -> dict:
    """Download and validate an explicit S3 backup before restoring SQLite."""
    backup_id = _safe_backup_id(backup_id)
    destination_db = Path(destination_db).resolve()
    if destination_db.exists() and not force:
        raise FileExistsError(
            "Restore destination exists; pass --force to permit an overwrite."
        )
    cached_backup = Path(download_root).resolve() / backup_id
    if cached_backup.exists():
        validation = validate_operational_backup(cached_backup)
        downloaded = {
            "backup_id": backup_id,
            "backup_dir": validation["backup_dir"],
            "sha256": validation["sha256"],
        }
        reused_cached_backup = True
    else:
        downloaded = download_operational_backup(
            backup_id,
            bucket=bucket,
            client=client,
            download_root=download_root,
            prefix=prefix,
        )
        reused_cached_backup = False
    result = restore_operational_database(
        Path(downloaded["backup_dir"]),
        destination_db,
        force=force,
        pre_restore_root=pre_restore_root,
        project_root=project_root,
    )
    result.update(
        s3_bucket=bucket,
        s3_backup_id=downloaded["backup_id"],
        downloaded_backup=downloaded["backup_dir"],
        reused_cached_backup=reused_cached_backup,
    )
    return result
