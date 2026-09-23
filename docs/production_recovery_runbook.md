# PowerFlow production recovery and presentation runbook

This runbook applies to the persistent Amazon Linux 2023 deployment at
`/home/ec2-user/Electricity_Trading_Pipeline`. Run commands from that directory
with `.venv-prod` activated unless a command uses `sudo`.

PowerFlow preserves the most recent valid production forecast and clearly identifies stale or unavailable forecasts rather than fabricating replacement market data.

## Normal startup and restart

The PostgreSQL, Prefect server, Prefect worker, and Streamlit services are
enabled for reboot persistence. Check them after a reboot:

```bash
cd /home/ec2-user/Electricity_Trading_Pipeline
source .venv-prod/bin/activate
sudo systemctl is-active postgresql.service powerflow-prefect-server.service \
  powerflow-prefect-worker.service powerflow-streamlit.service
curl --fail --silent http://127.0.0.1:4200/api/health
```

Restart the PowerFlow application services after reviewed code or configuration
changes:

```bash
sudo systemctl restart powerflow-prefect-server.service
./scripts/setup_prefect_ec2.sh
sudo systemctl restart powerflow-prefect-worker.service powerflow-streamlit.service
```

Do not expose PostgreSQL or the Prefect API publicly. Streamlit listens on port
8501 and should be restricted to the intended operator network in the EC2
security group.

## Operational verification

Inspect service status and logs:

```bash
sudo systemctl status postgresql.service powerflow-prefect-server.service \
  powerflow-prefect-worker.service powerflow-streamlit.service
sudo journalctl -u powerflow-prefect-worker.service --since "2 hours ago"
sudo journalctl -u powerflow-streamlit.service --since "2 hours ago"
```

Verify PostgreSQL, Prefect, the latest PowerFlow pipeline state, and the latest
saved forecast without generating a new forecast:

```bash
sudo -u postgres psql -d prefect -tAc "SELECT current_database();"
.venv-prod/bin/prefect work-pool inspect electricity-pool
.venv-prod/bin/prefect deployment inspect \
  'PowerFlow ENTSO-E Pipeline/powerflow-entsoe-pipeline'
PYTHONPATH=src python src/check_pipeline_status.py
python -c "import pandas as p; f=p.read_csv('data/reports/next24h_forecast.csv'); print(f[['forecast_issue_time','target_timestamp']].tail(1).to_string(index=False))"
```

The dashboard should display stale or unavailable status when freshness checks
fail. Do not increase the three-hour next24h freshness threshold to make a
presentation appear current.

## Back up operational SQLite

Create a consistent SQLite backup using SQLite's online backup API:

```bash
python scripts/backup_operational_state.py
```

The command prints the new UTC-stamped directory under
`backups/operational/`. It contains only the SQLite database and `manifest.json`.
The manifest records its SHA-256, size, Git commit, and table list. The utility
refuses obvious unredacted credential strings and never reads `.env`.

Validate the exact directory printed by the backup command:

```bash
python scripts/validate_operational_backup.py \
  backups/operational/YYYYMMDDTHHMMSS.ffffffZ
```

Validation checks the hash, file size, SQLite integrity, expected operational
tables, and row counts. It opens the backup read-only and never touches the
production database.

## Restore operational SQLite

Prefer restoring to a separate path for inspection:

```bash
python scripts/restore_operational_state.py \
  backups/operational/YYYYMMDDTHHMMSS.ffffffZ \
  --destination /tmp/powerflow-operational-restore.db
```

The restore command refuses an existing destination. Replacing the production
database requires the explicit `--force` flag and first creates a separate
pre-restore backup:

```bash
sudo systemctl stop powerflow-prefect-worker.service powerflow-streamlit.service
python scripts/restore_operational_state.py \
  backups/operational/YYYYMMDDTHHMMSS.ffffffZ \
  --destination database/electricity_trading.db \
  --force
sudo systemctl start powerflow-prefect-worker.service powerflow-streamlit.service
```

Validate the selected backup before any restore and retain its manifest.

## S3 recovery readiness

PowerFlow uses the EC2 IAM role. Do not set `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, or `AWS_SESSION_TOKEN` for these checks.

```bash
python scripts/check_s3_recovery_readiness.py
```

This performs only `HeadBucket`, versioning, encryption, lifecycle, and
single-object prefix reads. It makes no S3 writes or configuration changes.
Each result is reported independently as `configured`, `not_configured`,
`permission_unavailable`, or `error`; an unavailable permission is never
interpreted as evidence that the bucket feature is disabled.

Complete read-only recovery inspection requires these IAM actions:

- `s3:GetBucketVersioning`
- `s3:GetEncryptionConfiguration`
- `s3:GetLifecycleConfiguration`
- `s3:ListBucket`

An administrator may grant the following bucket-scoped policy to the EC2 role
after review. The repository does not apply this policy automatically:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PowerFlowRecoveryReadOnlyInspection",
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketVersioning",
        "s3:GetEncryptionConfiguration",
        "s3:GetLifecycleConfiguration",
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::powerflow-data-ian-2026-870755688674-us-east-1-an"
    }
  ]
}
```

Recommended production controls:

- Enable S3 Versioning so accidental overwrites and deletions remain recoverable.
- Keep default server-side encryption enabled, using SSE-S3 or a managed KMS key.
- Define a reviewed lifecycle policy for noncurrent versions and incomplete
  multipart uploads. Retention must cover the presentation and assessment period.
- Keep IAM least-privilege permissions for normal pipeline writes and restrict
  version deletion/configuration changes to an administrative role.

Prefix responsibilities:

| Prefix | Recovery contents |
| --- | --- |
| `raw/` | Source ENTSO-E and Open-Meteo working datasets |
| `silver/` | Aligned hourly market dataset |
| `gold/` | Feature-engineered model dataset |
| `reports/` | Predictions, monitoring, anomaly, and evaluation reports |
| `models/releases/` | Frozen one-hour and next24h production releases |

Verify versions for a specific object without restoring it:

```bash
aws s3api list-object-versions \
  --bucket powerflow-data-ian-2026-870755688674-us-east-1-an \
  --prefix reports/predictions/next24h/next24h_forecast.csv
```

Download a selected version to a new local inspection path:

```bash
aws s3api get-object \
  --bucket powerflow-data-ian-2026-870755688674-us-east-1-an \
  --key reports/predictions/next24h/next24h_forecast.csv \
  --version-id VERSION_ID \
  /tmp/next24h_forecast.recovered.csv
```

Validate the recovered file before deliberately replacing a local working file
or uploading it as the current S3 version. Never restore an entire prefix when a
single known object version is sufficient.

Versioning, encryption, and lifecycle are account-level operational decisions.
The repository documents them but does not change bucket configuration.

## Create presentation evidence

Capture the latest available approved reports and SQLite summaries:

```bash
python scripts/create_presentation_snapshot.py
```

The unique directory under `presentation_snapshots/` contains only approved
existing reports, recent sanitized incident/timing summaries, latest successful
run metadata, and a hash manifest. Missing optional reports are listed rather
than fabricated. The snapshot is historical production evidence, not live data.

Before presenting, inspect and retain the snapshot path printed by the command:

```bash
python -m json.tool \
  presentation_snapshots/YYYYMMDDTHHMMSS.ffffffZ/snapshot_manifest.json
```

## If ENTSO-E is unavailable during a presentation

1. Do not fabricate, interpolate, or manually edit market observations.
2. Show the dashboard's current warning or stale state and the retained last
   valid forecast.
3. Show the most recent successful pipeline metadata and continuity incident.
4. Use the pre-created presentation snapshot as fallback evidence from a real
   successful production run.
5. Explain that automatic overlap ingestion will retry recent late-arriving
   observations after the upstream source recovers.
6. After service recovery, verify Prefect history, source timestamps, forecast
   freshness, and S3 synchronization before describing the system as current.
