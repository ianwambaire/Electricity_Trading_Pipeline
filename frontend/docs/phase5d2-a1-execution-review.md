# Phase 5D.2 — Final A1 execution review

26 October 2026, Africa/Nairobi. This pre-execution review was subsequently approved and **A1 completed once**. See the executed-result section in phase5d2-recovery-and-infrastructure-remediation.md. The payload below is retained unchanged for provenance, not permission to rerun it. No A2 or deployment approval follows.

## 1. Exact proposed execution

Execute the unchanged `deploy/remediation/backup-operational-sqlite.sh` once through SSH stdin; do not copy/install it on EC2. Its SHA-256 is:

`eb385dcc8afbe08c3f3bdf5f4ed05da4e6a3e9811fee500b05794ef997c87896`

The operator must recheck that hash locally immediately before execution and stop on any change. Target remains the previously verified EC2 `i-059e63a35a022cd0f`, `3.228.243.164`, region `us-east-1`; SSH account ec2-user. No AWS API operation is part of A1.

```sh
ssh -F /dev/null -i /Users/iannganga/.ssh/powerflow-key.pem \
  -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none \
  -o StrictHostKeyChecking=yes -o UpdateHostKeys=no \
  -o UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts \
  -o ForwardAgent=no -o RequestTTY=no -o ConnectTimeout=10 \
  -T ec2-user@3.228.243.164 'bash -s' \
  < deploy/remediation/backup-operational-sqlite.sh
```

Do not display/read/copy private-key contents, autoaccept host keys, use sudo or try another host/account. No automatic retry. This command was subsequently executed once under the separate A1 approval. Do not rerun it.

The complete unchanged remote payload is:

```bash
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
```

## 2. Sources, runtime and destination

| Purpose | Exact path / behavior |
|---|---|
|Sole database source|`/home/ec2-user/Electricity_Trading_Pipeline/database/electricity_trading.db`|
|Optional journal input|`/home/ec2-user/Electricity_Trading_Pipeline/database/electricity_trading.db-wal`; counted in the preflight budget if present; SQLite handles committed WAL pages during backup|
|SQLite coordination|The associated `electricity_trading.db-shm` may be used by SQLite; it is not copied as a separate recovery artifact|
|Existing interpreter|`/home/ec2-user/Electricity_Trading_Pipeline/.venv-prod/bin/python -I -S -B`; no installation, site initialization, Python environment-path override or bytecode writes|
|Reviewed helper|`/home/ec2-user/Electricity_Trading_Pipeline/src/operational_recovery.py`, exact required SHA-256 `c2bc8f38158db4331220a0658e2b58bddccb73bf374d65df5b87d1907c532bc5`|
|New backup root|`/home/ec2-user/powerflow-recovery-phase5d2-operational`; must not already exist, including a symlink|
|New backup set|`<new-root>/<UTC-backup-id>/electricity_trading.db` and `manifest.json`; ID format `YYYYMMDDTHHMMSS.microsecondsZ`, allocated at execution, not invented in advance|
|Temporary backup file|`<new-root>/<UTC-backup-id>/.electricity_trading.db.tmp`; the helper also uses SQLite temporary/journal workspace as needed|

Hash verification reads only the reviewed helper source before import. Installed helper hash, interpreter availability and destination nonexistence have not been verified remotely by A0: A1 checks/refuses these prerequisites when attempted. If any fail, stop; do not repair/install/edit anything. The helper also attempts read-only `git rev-parse HEAD` for private manifest provenance; it does not stage, commit, push or change history, and checkout HEAD does not identify loaded API code.

## 3. Included and excluded coverage

**Included:** the entire operational SQLite database as a consistent logical SQLite image, including all tables/indexes/views and any additional tables present. This is not a four-table-only export. Validation requires `pipeline_runs`, `data_quality_results`, `operational_incidents`, `pipeline_stage_timings`; output contains only their aggregate counts, backup ID and digest. No raw rows are printed.

**Excluded:** PostgreSQL/Prefect PostgreSQL, `/home/ec2-user/.prefect/prefect.db` and its WAL/SHM, MLflow metadata/artifacts, raw/Silver/Gold files, CSV/JSON forecast/anomaly/evaluation/monitoring reports, model binaries/contracts, Nginx/systemd/app configuration, secret files, TLS keys, EC2/EBS snapshots, S3 upload, off-host copy, permissions remediation and restoration. Any such information already embedded in the operational DB remains part of that DB; this is not a de-identification tool.

A1 is one small operational backup, **not a complete application or disaster-recovery backup**. No A2 transfer/restore or deployment follows automatically.

## 4. SQLite consistency and WAL handling

The helper opens the source through SQLite URI `mode=ro`, scans operational text for obvious credential-like values, and uses `sqlite3.Connection.backup()` into a new destination. SQLite coordinates locks/read consistency and includes committed data from a source WAL when present. The resulting image does not depend on copying source WAL/SHM files afterward. The pipeline can continue writing; the backup represents a consistent captured state, not necessarily the state at completion.

Only the **destination** is VACUUMed. There is no source VACUUM, checkpoint, migration, write SQL or file overwrite. Do not replace this procedure with `cp`/rsync of a busy DB or remove sidecars. Source SQLite can perform normal locking/shared-memory coordination; read-only SQL is not a guarantee of zero sidecar/OS metadata activity. The script does not independently inspect/change journal mode. A0's absent operational WAL/SHM was a point-in-time observation, not permission to assume they stay absent.

The credential scan and backup are separate source reads, not one frozen transaction: it is a heuristic check, not a guarantee that all confidential content or concurrent new secrets are excluded. Treat the resulting DB/manifest as confidential regardless.

## 5. PostgreSQL, Prefect and MLflow: known versus unknown

- Earlier approved service evidence showed PostgreSQL, Prefect server/worker, Streamlit and API active. This is historical running-service evidence, not a fresh availability test today.
- Source service configuration points toward local PostgreSQL database `prefect`; this does not prove which database the current Prefect process actually uses.
- A0 found Prefect SQLite base1,302,528bytes plus WAL4,132,392bytes and SHM32,768bytes at the fixed home path. Its current role is unresolved; WAL existence does not prove a live writer. Preserve it in recovery planning until separately established.
- `/var/lib/pgsql/data` directory usage was unverified. No SQL, credentials, profiles or environment were read; actual PostgreSQL directory, version, size and application use remain unknown.
- Code supports MLflow and defaults to local SQLite tracking in some research paths. A0 did not find checkout-root `mlflow.db`; candidate `mlruns` usage was unverified. This proves neither MLflow inactivity nor absence elsewhere. No tracking URI/environment/path search is approved.

A1 deliberately leaves these databases untouched and does not close their recovery gates.

## 6. Size, free-space guard and retention/cleanup

A0 observed operational DB **13,213,696bytes (12.6016MiB)**, no operational WAL/SHM at that moment; filesystem21,395,124,224bytes total and12,805,435,392bytes available (~11.926GiB). Expect a backup of roughly the same order as the13.2MB source, possibly smaller after compaction, plus a small manifest. Exact final size depends on live data/SQLite layout and is not yet measured.

At execution, define `S = current database bytes + current WAL bytes when present`. Refuse `S > 134,217,728bytes (128MiB)`. Require:

`available_bytes - (3*S + 67,108,864) >= floor(filesystem_total_bytes / 4)`

Using A0 sizes, workspace allowance is **106,749,952bytes (101.8047MiB)** and25%reserve is5,348,781,056bytes. Minimum available space under that snapshot is therefore **5,455,531,008bytes**. Observed free space exceeds that by7,349,904,384bytes. A1 repeats the guard; A0 is not a permanent free-space guarantee. This is a preflight allowance, not a hard output-size/runtime limit or continuous disk monitor; concurrent growth remains possible.

**Cleanup, clarified from the earlier general report:** the unchanged helper automatically removes only the temporary/final DB and manifest created by its own failed backup attempt, and attempts to remove that attempt's now-empty timestamp directory. It never removes pre-existing backups; the outer new root may remain empty. If backup creation succeeds but subsequent validation fails, or the process is interrupted/crashes, private artifacts can remain. No automatic recursive root deletion, retention schedule, repeat attempt or post-success cleanup is included. The existence guard prevents rerunning into that root. Any later cleanup or retry requires a separate decision; do not delete artifacts to make the script run.

## 7. Services, privileges and permissions

No stop/restart/reload, pipeline run, training, account/group, chmod of live data, package install or elevated privilege is included. It runs as existing ec2-user. Required existing read/traverse access and ability to create the new home directory are checked naturally; failure does not authorize sudo or permission changes.

`umask077`, new backup root/timestamp directory0700, backup DB/manifest0600. Existing source mode0644/UID:GID1000:1000 is unchanged. Ownership of new files is the executing user's normal ownership. No access to `.env`, secrets.toml, AWS credential files, private TLS keys or Cognito configuration is part of this payload. It avoids the old dotenv-loading backup CLI.

Private modes do **not** encrypt storage: the root EBS volume remains unencrypted, and root/the same account can access the backup. Authorizing A1 accepts a confidential local-only copy on that existing volume; no cloud upload or encryption remedy is implied. The manifest includes internal source paths, schema/table metadata and checkout revision, so keep it private too.

## 8. Verification and acceptance

The script first pins helper bytes, refuses unexpected source/destination/size/space, then creates the consistent backup. Verification is against the **backup**, not a newly queried live source:

- `PRAGMA quick_check` during creation and validation;
- SHA-256 and stored byte-size comparison against the private manifest;
- matching table-name list and required operational tables;
- aggregate row counts for the four required tables.

The manifest records schema objects, but this validator does **not** compare all recorded schema SQL or run full `PRAGMA integrity_check`/`foreign_key_check`. Counts are collected from the backup, not independently attested against live source counts. SHA-256 establishes byte agreement with its manifest, not external authenticity, off-host protection or recoverability. Those distinctions correct any stronger earlier generic wording.

Success output is exactly the fixed summary shape `private_local_backup_created`, returned backup ID/digest/counts, and **false** for off-host/production-restore verification. Capture actual start/end/duration without raw data/logs. A nonzero exit, absent success or validation failure is not a pass. No additional SSH commands, row dumps, full integrity scans or service-health calls are authorized merely by A1; the payload contains its complete validation scope.

## 9. Failure, rollback and restoration requirements

A precondition error stops before creating a backup set; some failures after the outer root is created may leave it behind. Helper failure cleanup is limited as described above. The top-level payload suppresses exception text and emits a fixed stopped message. Shell/interpreter/SSH failure may yield no JSON; classify failure and stop without printing credential-bearing diagnostics or retrying.

No source database mutation is intended, so there is no production database rollback to perform. Do not restore a backup over the live DB because a backup attempt failed. Do not kill/restart any service or relax the128MiB/free-space/hash guard. Ordinary read-lock/I/O contention is possible; there is no built-in overall runtime limit or service-health monitor. Unexpected contention/interruption requires reporting and a separately approved response, not improvisation.

A separately approved A2 must select this exact backup/digest, verify a protected off-host destination, restore into a new isolated DB, validate full integrity/foreign keys/schema/counts and representative safe semantics, and measure retrieval+runtime+restore+validation RTO and coherent capture-point RPO. No source credentials, pipeline writer or production restore. Existing synthetic local drill is not evidence of real production restoration. Broader PostgreSQL/Prefect/MLflow/configuration recovery remains necessary before infrastructure replacement or staging changes requiring rollback.

## 10. Cost and operational confirmation

No new EC2, EBS volume, snapshot, S3 object, KMS key, transfer or paid AWS resource/API is part of A1. New files consume existing provisioned root capacity; there is no incremental EBS allocation charge. Existing normal hosting/IPv4/storage charges continue. No cleanup cost saving or permanent retention policy is claimed.

The procedure is designed to leave **Streamlit, FastAPI, Prefect and PostgreSQL running**, with no configuration or process-control action affecting them. It cannot guarantee zero performance impact from a source read/backup scan, or certify today's uptime without an additional authorized check. No such service check or new host inspection was performed for this review. A0 only established metadata, not continuous service health.

## 11. Requested authorization boundary

If approved, authorize **one execution of the unchanged script/hash above**, through the stated existing strict SSH stdin method, including reading operational database contents for the scan/consistent backup, creating its one new private backup set, its backup-only checks and helper's limited own-attempt cleanup. No separate remote script installation or extra inspection commands.

**Executed once under separate explicit approval; successful result is recorded in the Phase5D.2 report.** A2, off-host transfer, actual restoration, any service/configuration/AWS change and deployment remain excluded. The approved script/helper bytes were not changed.
