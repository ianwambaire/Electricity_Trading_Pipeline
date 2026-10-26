#!/usr/bin/env python3
"""Exercise existing SQLite recovery with disposable synthetic data only.

No source/destination database argument, cloud calls, production data or services.
Temporary artifacts are private and removed, including on failure. Timings are
local fixture timings, never a production RPO/RTO or recoverability claim.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from operational_recovery import (  # noqa: E402
    backup_operational_database,
    restore_operational_database,
    sha256_file,
    validate_operational_backup,
)


def run_rehearsal() -> dict:
    with TemporaryDirectory(prefix='powerflow-disposable-recovery-') as directory:
        scratch = Path(directory)
        scratch.chmod(0o700)
        source = scratch / 'synthetic.db'
        with closing(sqlite3.connect(source)) as db:
            db.executescript((ROOT / 'database/schema.sql').read_text())
            db.execute(
                'INSERT INTO pipeline_runs(run_time,status,records_processed,message) VALUES(?,?,?,?)',
                ('2026-01-01T00:00:00+00:00', 'SUCCESS', 3, 'Synthetic recovery drill'),
            )
            db.commit()
        source.chmod(0o600)
        source_digest = sha256_file(source)
        started = perf_counter()
        backup = backup_operational_database(
            source, backup_root=scratch / 'backups', project_root=scratch,
        )
        backup_seconds = perf_counter() - started
        validated = validate_operational_backup(backup)
        restored = scratch / 'restored' / 'synthetic.db'
        started = perf_counter()
        restore_operational_database(backup, restored, project_root=scratch)
        restore_seconds = perf_counter() - started
        # Immutable avoids creating sidecars while checking the restored copy.
        with closing(sqlite3.connect(restored.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
            rows = db.execute('SELECT run_time,status,records_processed,message FROM pipeline_runs').fetchall()
        if integrity != 'ok' or rows != [('2026-01-01T00:00:00+00:00', 'SUCCESS', 3, 'Synthetic recovery drill')]:
            raise ValueError('Synthetic restored rows failed verification')
        if sha256_file(source) != source_digest:
            raise ValueError('Synthetic source changed during rehearsal')
        overwrite_refused = False
        try:
            restore_operational_database(backup, restored, project_root=scratch)
        except FileExistsError:
            overwrite_refused = True
        if not overwrite_refused:
            raise ValueError('Existing restore destination was not protected')
        return {
            'scope': 'disposable local synthetic operational SQLite only',
            'status': 'passed',
            'production_recovery_verified': False,
            'production_rpo_rto_verified': False,
            'synthetic_backup_seconds': round(backup_seconds, 6),
            'synthetic_restore_seconds': round(restore_seconds, 6),
            'integrity_check': integrity,
            'restored_pipeline_rows': len(rows),
            'backup_sha256': validated['sha256'],
            'source_unchanged': True,
            'existing_destination_refused': overwrite_refused,
            'postgresql_mlflow_volume_restore_verified': False,
        }


if __name__ == '__main__':
    if len(sys.argv) != 1:
        raise SystemExit('This disposable drill accepts no production paths or arguments.')
    try:
        print(json.dumps(run_rehearsal(), indent=2))
    except Exception:
        # Never print arbitrary database content, exception text or file paths.
        print(json.dumps({'status': 'failed', 'scope': 'synthetic local drill', 'production_recovery_verified': False}))
        raise SystemExit(1) from None
