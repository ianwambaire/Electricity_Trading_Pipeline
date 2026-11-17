"""Only disposable fixtures; no production, AWS or credential access."""
import importlib.util
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('recovery_drill', ROOT/'scripts/rehearse_operational_recovery.py')
drill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drill)


def track_temporary_directory(monkeypatch):
    locations = []
    def temporary(**kwargs):
        value = TemporaryDirectory(**kwargs)
        locations.append(Path(value.name))
        return value
    monkeypatch.setattr(drill, 'TemporaryDirectory', temporary)
    return locations


def test_disposable_drill_checks_actual_restored_rows_and_never_claims_production(monkeypatch):
    locations = track_temporary_directory(monkeypatch)
    result = drill.run_rehearsal()
    assert result['status'] == 'passed'
    assert result['source_unchanged'] and result['existing_destination_refused']
    assert result['restored_pipeline_rows'] == 1
    assert result['integrity_check'] == 'ok'
    assert result['synthetic_restore_seconds'] >= 0
    assert result['production_recovery_verified'] is False
    assert result['production_rpo_rto_verified'] is False
    assert result['postgresql_mlflow_volume_restore_verified'] is False
    assert 'source_db' not in result and 'backup_dir' not in result
    assert locations and all(not p.exists() for p in locations)


def test_tampered_disposable_backup_fails_closed_and_cleans_up(monkeypatch):
    locations = track_temporary_directory(monkeypatch)
    original = drill.backup_operational_database
    def corrupted(*args, **kwargs):
        backup = original(*args, **kwargs)
        (backup/'synthetic.db').write_bytes(b'corrupt fixture')
        return backup
    monkeypatch.setattr(drill, 'backup_operational_database', corrupted)
    with pytest.raises((ValueError, RuntimeError)):
        drill.run_rehearsal()
    assert locations and all(not p.exists() for p in locations)


def test_cli_refuses_source_or_production_destination_arguments():
    result = subprocess.run(
        [sys.executable, str(ROOT/'scripts/rehearse_operational_recovery.py'), '--source', '/not-a-database'],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert 'accepts no production paths' in result.stderr
    assert '/not-a-database' not in result.stderr


def test_proposed_inventory_is_syntax_valid_and_metadata_only():
    script = ROOT/'deploy/remediation/read-only-recovery-inventory.sh'
    result = subprocess.run(['bash', '-n', str(script)], capture_output=True, check=False)
    assert result.returncode == 0
    text = script.read_text()
    embedded = text.split("- <<'PY'\n", 1)[1].rsplit('\nPY\n', 1)[0]
    compile(embedded, '<unexecuted-approved-inventory-proposal>', 'exec')
    assert "['du', '-sx', '-B1', '--', str(path)]" in embedded
    assert 'timeout=8' in embedded and 'follow_symlinks=False' in embedded
    for forbidden in ('.read_text(', '.read_bytes(', 'sqlite3', 'sudo', 'aws ', 'shutil', 'write_text', 'write_bytes', 'os.environ', '/proc/', 'private_key'):
        assert forbidden not in embedded
    assert "'status': 'unverified'" in embedded


def test_proposed_production_backup_pins_helper_and_has_no_secret_autoload_or_upload():
    script = ROOT/'deploy/remediation/backup-operational-sqlite.sh'
    assert subprocess.run(['bash', '-n', str(script)], capture_output=True).returncode == 0
    text = script.read_text()
    embedded = text.split("- <<'PY'\n", 1)[1].rsplit('\nPY\n', 1)[0]
    compile(embedded, '<unexecuted-production-backup-proposal>', 'exec')
    assert 'c2bc8f38158db4331220a0658e2b58bddccb73bf374d65df5b87d1907c532bc5' in embedded
    assert "output.exists() or output.is_symlink()" in embedded
    assert '-I -S -B' in text
    assert 'size > 128*1024*1024' in embedded
    assert 'size*3 + 64*1024*1024' in embedded
    assert 'exist_ok=False' in embedded and 'mode=0o700' in embedded
    for forbidden in ('load_dotenv', 'upload_operational_backup', 'boto3', 'restore_operational_database', 'unlink(', 'rmtree(', 'os.environ'):
        assert forbidden not in embedded
    assert "'off_host_backup_verified': False" in embedded
