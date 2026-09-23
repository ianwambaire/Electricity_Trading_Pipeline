from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from operational_recovery import (
    backup_operational_database,
    restore_operational_database,
    sha256_file,
    validate_operational_backup,
)
from presentation_snapshot import create_presentation_snapshot, operational_summaries


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (PROJECT_ROOT / "database/schema.sql").read_text(encoding="utf-8")


def make_operational_db(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO pipeline_runs (run_time, status, records_processed, message) "
            "VALUES (?, 'SUCCESS', 7, ?)",
            ("2026-09-23T06:00:00+00:00", '{"message":"completed"}'),
        )
        connection.execute(
            "INSERT INTO operational_incidents "
            "(timestamp_utc, severity, component, event_type, status, message, details_json) "
            "VALUES (?, 'WARNING', 'ENTSO-E', 'source_gap', 'ACTIVE', ?, ?)",
            (
                "2026-09-23T05:00:00+00:00",
                "One interval missing",
                '{"missing_count":1}',
            ),
        )
        connection.execute(
            "INSERT INTO pipeline_stage_timings "
            "(run_id, stage_name, start_timestamp_utc, end_timestamp_utc, "
            "duration_seconds, status) VALUES (?, ?, ?, ?, ?, 'SUCCESS')",
            (
                "run-1",
                "ENTSO-E ingestion",
                "2026-09-23T05:59:00+00:00",
                "2026-09-23T06:00:00+00:00",
                60.0,
            ),
        )
    return path


def test_sqlite_backup_is_valid_independent_and_manifest_hash_matches(tmp_path):
    source = make_operational_db(tmp_path / "database/electricity_trading.db")
    source_before = source.read_bytes()
    backup_dir = backup_operational_database(
        source,
        backup_root=tmp_path / "backups/operational",
        project_root=PROJECT_ROOT,
        now=datetime(2026, 9, 23, 6, tzinfo=timezone.utc),
    )
    validation = validate_operational_backup(backup_dir)
    manifest = json.loads((backup_dir / "manifest.json").read_text())
    assert validation["status"] == "valid"
    assert validation["row_counts"]["pipeline_runs"] == 1
    assert manifest["sha256"] == sha256_file(Path(validation["backup_db"]))
    assert source.read_bytes() == source_before
    with sqlite3.connect(source) as connection:
        connection.execute("DELETE FROM pipeline_runs")
    assert validate_operational_backup(backup_dir)["row_counts"]["pipeline_runs"] == 1


def test_backup_refuses_live_credentials_and_never_collects_env(tmp_path):
    source = make_operational_db(tmp_path / "database/electricity_trading.db")
    (tmp_path / ".env").write_text("ENTSOE_API_KEY=never-copy\n")
    with sqlite3.connect(source) as connection:
        connection.execute(
            "INSERT INTO data_quality_results VALUES (NULL, ?, ?, ?, ?)",
            ("2026-09-23T06:00:00+00:00", "test", "FAILED", "token=secret-value"),
        )
    with pytest.raises(ValueError, match="Credential-like content"):
        backup_operational_database(
            source,
            backup_root=tmp_path / "backups/operational",
            project_root=tmp_path,
        )
    assert not list((tmp_path / "backups/operational").rglob(".env"))


def test_validation_rejects_tampered_backup(tmp_path):
    source = make_operational_db(tmp_path / "operational.db")
    backup_dir = backup_operational_database(
        source, backup_root=tmp_path / "backups", project_root=PROJECT_ROOT
    )
    manifest = json.loads((backup_dir / "manifest.json").read_text())
    with (backup_dir / manifest["backup_db"]).open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        validate_operational_backup(backup_dir)


def test_restore_requires_force_and_creates_pre_restore_backup(tmp_path):
    source = make_operational_db(tmp_path / "source.db")
    backup_dir = backup_operational_database(
        source, backup_root=tmp_path / "backups", project_root=PROJECT_ROOT
    )
    destination = make_operational_db(tmp_path / "production.db")
    before = destination.read_bytes()
    with pytest.raises(FileExistsError, match="--force"):
        restore_operational_database(backup_dir, destination)
    assert destination.read_bytes() == before
    result = restore_operational_database(
        backup_dir,
        destination,
        force=True,
        pre_restore_root=tmp_path / "pre-restore",
        project_root=PROJECT_ROOT,
    )
    assert Path(result["pre_restore_backup"]).is_dir()
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0] == 1


def make_snapshot_project(root: Path) -> tuple[Path, Path]:
    reports = root / "data/reports"
    reports.mkdir(parents=True)
    (reports / "next24h_forecast.csv").write_text(
        "forecast_issue_time,target_timestamp,predicted_price_eur_mwh\n"
        "2026-09-23T06:00:00+00:00,2026-09-23T07:00:00+00:00,50\n"
    )
    (reports / "final_holdout_metrics.csv").write_text("metric,value\nmae,10.7\n")
    (reports / "not_approved.csv").write_text("should,not,copy\n")
    release = root / "artifacts/models/releases/next24h"
    release.mkdir(parents=True)
    (release / "next24h_release_manifest.json").write_text(
        '{"release_id":"next24h-test-v1"}\n'
    )
    models = root / "artifacts/models"
    (models / "final_model_release_manifest.json").write_text(
        '{"release_type":"final","model":{"selected_model":"Linear Regression","feature_count":31}}\n'
    )
    (models / "final_gold_model.joblib").write_bytes(b"frozen-model")
    database = make_operational_db(root / "database/electricity_trading.db")
    return root, database


def test_presentation_snapshot_whitelist_hashes_and_operational_summaries(tmp_path):
    project, database = make_snapshot_project(tmp_path / "project")
    snapshot = create_presentation_snapshot(
        project,
        output_root=tmp_path / "snapshots",
        database_path=database,
        now=datetime(2026, 9, 23, 7, tzinfo=timezone.utc),
    )
    manifest = json.loads((snapshot / "snapshot_manifest.json").read_text())
    names = {item["name"] for item in manifest["files_included"]}
    assert "next24h_forecast.csv" in names
    assert "final_holdout_metrics.csv" in names
    assert "not_approved.csv" not in names
    assert {
        "operational_incidents_summary.json",
        "pipeline_stage_timings_summary.json",
        "latest_successful_pipeline_run.json",
    }.issubset(names)
    for item in manifest["files_included"]:
        assert item["sha256"] == sha256_file(snapshot / item["name"])
    assert manifest["latest_forecast_issue_time"] == "2026-09-23T06:00:00+00:00"
    assert manifest["latest_successful_pipeline_time"] == "2026-09-23T06:00:00+00:00"


def test_snapshot_handles_missing_optional_files_and_excludes_credentials(tmp_path):
    project, database = make_snapshot_project(tmp_path / "project")
    (project / ".env").write_text("ENTSOE_API_KEY=never-copy\n")
    (project / "credentials.pem").write_text("never-copy\n")
    snapshot = create_presentation_snapshot(
        project, output_root=tmp_path / "snapshots", database_path=database
    )
    manifest = json.loads((snapshot / "snapshot_manifest.json").read_text())
    assert "data/reports/next24h_performance.csv" in manifest["missing_optional_files"]
    assert not (snapshot / ".env").exists()
    assert not (snapshot / "credentials.pem").exists()


def test_operational_summary_redacts_secrets(tmp_path):
    database = make_operational_db(tmp_path / "operational.db")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO pipeline_runs (run_time, status, records_processed, message) "
            "VALUES (?, 'SUCCESS', 1, ?)",
            ("2026-09-23T07:00:00+00:00", "token=do-not-expose"),
        )
    summaries = operational_summaries(database)
    assert "do-not-expose" not in json.dumps(summaries)
    assert "[REDACTED]" in json.dumps(summaries)


def test_scripts_resolve_paths_from_repository_root():
    scripts = (
        "backup_operational_state.py",
        "validate_operational_backup.py",
        "restore_operational_state.py",
        "create_presentation_snapshot.py",
        "check_s3_recovery_readiness.py",
    )
    for script in scripts:
        result = subprocess.run(
            [sys.executable, f"scripts/{script}", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_s3_readiness_checker_is_read_only(monkeypatch):
    script = PROJECT_ROOT / "scripts/check_s3_recovery_readiness.py"
    spec = importlib.util.spec_from_file_location("s3_readiness", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class ReadOnlyS3:
        def __init__(self):
            self.calls = []

        def head_bucket(self, **kwargs):
            self.calls.append(("head_bucket", kwargs))
            return {}

        def get_bucket_versioning(self, **kwargs):
            self.calls.append(("get_bucket_versioning", kwargs))
            return {"Status": "Enabled"}

        def get_bucket_encryption(self, **kwargs):
            self.calls.append(("get_bucket_encryption", kwargs))
            return {
                "ServerSideEncryptionConfiguration": {
                    "Rules": [
                        {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                    ]
                }
            }

        def get_bucket_lifecycle_configuration(self, **kwargs):
            self.calls.append(("get_bucket_lifecycle_configuration", kwargs))
            return {"Rules": [{"ID": "retain", "Status": "Enabled"}]}

        def list_objects_v2(self, **kwargs):
            self.calls.append(("list_objects_v2", kwargs))
            return {"KeyCount": 1, "Contents": [{"Key": kwargs["Prefix"] + "item"}]}

    client = ReadOnlyS3()
    result = module.check_s3_recovery_readiness("bucket", "us-east-1", client=client)
    assert result["read_only"] is True
    assert result["versioning_status"] == "Enabled"
    assert set(result["prefixes"]) == set(module.PRODUCTION_PREFIXES)
    assert {name for name, _ in client.calls} <= {
        "head_bucket",
        "get_bucket_versioning",
        "get_bucket_encryption",
        "get_bucket_lifecycle_configuration",
        "list_objects_v2",
    }
