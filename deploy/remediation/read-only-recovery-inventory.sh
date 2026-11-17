#!/bin/bash
# PROPOSAL ONLY. Requires separate explicit approval before running over SSH.
# Fixed path metadata and allocated directory bytes; no file contents, secrets,
# SQL connections, logs, process arguments, sudo, writes or service changes.
set -eu
python3 -I -S -B - <<'PY'
import json
import os
from pathlib import Path
import stat
import subprocess

root = Path('/home/ec2-user/Electricity_Trading_Pipeline')
files = {
    'operational_sqlite': root/'database/electricity_trading.db',
    'mlflow_sqlite_candidate': root/'mlflow.db',
    'legacy_prefect_sqlite_candidate': Path('/home/ec2-user/.prefect/prefect.db'),
}
result = {'scope': 'fixed-path metadata only; missing/denied is not evidence of absence elsewhere', 'files': {}, 'allocated_bytes': {}}
for label, path in files.items():
    for suffix, kind in [('', 'database'), ('-wal', 'wal'), ('-shm', 'shm')]:
        name = label + '_' + kind
        try:
            info = os.stat(str(path) + suffix, follow_symlinks=False)
            result['files'][name] = {'status': 'observed', 'regular_file': stat.S_ISREG(info.st_mode), 'symlink': stat.S_ISLNK(info.st_mode), 'bytes': info.st_size, 'mode': oct(stat.S_IMODE(info.st_mode)), 'uid': info.st_uid, 'gid': info.st_gid}
        except FileNotFoundError:
            result['files'][name] = {'status': 'not_found_at_fixed_path'}
        except OSError:
            result['files'][name] = {'status': 'unverified'}
for label, path in {
    'operational_database_directory': root/'database',
    'market_and_reports_directory': root/'data',
    'frozen_artifacts_directory': root/'artifacts',
    'mlflow_artifact_candidate': root/'mlruns',
    'postgres_data_candidate': Path('/var/lib/pgsql/data'),
}.items():
    try:
        process = subprocess.run(['du', '-sx', '-B1', '--', str(path)], capture_output=True, text=True, timeout=8)
        first = process.stdout.split(maxsplit=1)[0] if process.stdout else ''
        result['allocated_bytes'][label] = {'status': 'observed', 'bytes': int(first)} if process.returncode == 0 and first.isdigit() else {'status': 'unverified'}
    except (OSError, subprocess.TimeoutExpired):
        result['allocated_bytes'][label] = {'status': 'unverified'}
fs = os.statvfs(str(root))
result['checkout_filesystem'] = {'total_bytes': fs.f_blocks*fs.f_frsize, 'available_bytes': fs.f_bavail*fs.f_frsize}
print(json.dumps(result, indent=2))
PY
