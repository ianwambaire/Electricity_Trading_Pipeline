#!/bin/bash
# PROPOSAL ONLY: one private operational SQLite backup, no upload or restore.
# Production execution requires a SEPARATE explicit approval after inventory.
set -eu
umask 077
/home/ec2-user/Electricity_Trading_Pipeline/.venv-prod/bin/python -I -S -B - <<'PY'
import hashlib
import json
import os
from pathlib import Path
import sys

root = Path('/home/ec2-user/Electricity_Trading_Pipeline')
source = root/'database/electricity_trading.db'
output = Path('/home/ec2-user/powerflow-recovery-phase5d2-operational')
expected = 'c2bc8f38158db4331220a0658e2b58bddccb73bf374d65df5b87d1907c532bc5'
try:
    if hashlib.sha256((root/'src/operational_recovery.py').read_bytes()).hexdigest() != expected:
        raise ValueError('Unreviewed recovery implementation')
    if source.resolve() != source or not source.is_file() or output.exists() or output.is_symlink():
        raise ValueError('Unexpected source or existing destination')
    size = source.stat().st_size
    wal = Path(str(source)+'-wal')
    if wal.is_symlink():
        raise ValueError('Unexpected WAL source')
    if wal.is_file():
        size += wal.stat().st_size
    if size > 128*1024*1024:
        raise ValueError('Source exceeds the narrowly approved first-backup size budget')
    fs = os.statvfs(str(output.parent))
    available = fs.f_bavail*fs.f_frsize
    reserve = fs.f_blocks*fs.f_frsize//4
    if available - (size*3 + 64*1024*1024) < reserve:
        raise ValueError('Insufficient safe backup workspace')
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    sys.path.insert(0, str(root/'src'))
    # Import only the reviewed standard-library recovery helper, not CLI/app config.
    from operational_recovery import backup_operational_database, validate_operational_backup
    backup = backup_operational_database(source, backup_root=output, project_root=root)
    checked = validate_operational_backup(backup)
    print(json.dumps({'status': 'private_local_backup_created', 'backup_id': backup.name, 'sha256': checked['sha256'], 'row_counts': checked['row_counts'], 'off_host_backup_verified': False, 'production_restore_verified': False}))
except Exception:
    print(json.dumps({'status': 'stopped', 'reason': 'Backup prerequisite or validation failed; operator review required. No raw diagnostics emitted.'}))
    raise SystemExit(1) from None
PY
