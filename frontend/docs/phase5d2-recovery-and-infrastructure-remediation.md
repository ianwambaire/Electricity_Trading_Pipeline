# Phase 5D.2 — Recovery and infrastructure remediation

25 October 2026, Africa/Nairobi. Branch `feature/react-frontend`; observed local HEAD `36100e0`. Earlier Phase5D.1 work remains in the working tree. No staging, commit, push, merge or history changes were made.

**Status: A0 and separately approved A1 each completed once. A1 created one private local operational SQLite backup. Actual restoration, off-host protection, renewal automation and peak capacity remain unverified.** No broader production/configuration change or staging is authorized.

## 1. Target binding and fresh evidence

Narrow read-only AWS calls bound the previously known host and attached storage, rather than repeating a broad audit:

| Resource | Verified value |
|---|---|
| AWS account / region |`870755688674` / `us-east-1`|
| Production instance / AZ |`i-059e63a35a022cd0f` / `us-east-1f`, running t3.small|
| DNS/public address |powerflowenergy.dev → `3.228.243.164`|
| Elastic IP |`eipalloc-044c2865e3193a2ac`, association`eipassoc-00e689bb99ba24354`, attached to that instance|
| Root device / volume |`/dev/xvda` / `vol-097f44a4fdc5d1a00`|
| Root parameters |20GiB gp3,3000IOPS,125MiB/s, **unencrypted**, DeleteOnTermination=true|
| Additional attached data volumes |None returned in the instance mapping; databases currently depend on root storage unless owner evidence establishes an external store|
| Instance profile |`arn:aws:iam::870755688674:instance-profile/PowerFlowEC2Role`|
| CLI operator |Root identity; read-only use only. Future changes should use an approved least-privilege operator, not routine root credentials. No IAM identity/policy was changed.|

Executed calls: STS GetCallerIdentity; EC2 DescribeInstances filtered to the DNS address and then exact instance; DescribeVolumes for the attached root; DescribeAddresses for the existing IP. No object contents, secrets, accounts or production databases were accessed. Only the separately approved A0 and A1 stdin scripts ran over SSH, as recorded below. No additional remote diagnostic command ran. Revalidate these bindings immediately before a future write; stop on differences.

Public TLS at25Oct19:38:24UTC (22:38Nairobi): strict certifi trust verified hostname/chain, TLS1.3, SANs apex/www, expiry **24Dec2026 05:17:26UTC**. The local Python default trust store failed chain verification(code20), while the installed certifi bundle succeeded; verification was never disabled. This is a local trust-store discrepancy, not evidence of production expiry. Renewal mechanism/reload behavior remain unknown.

Carry forward only:8000listener belongs to powerflow-api.service; unit runs as ec2-user; checkout HEAD previouslyb165c8db5a208e8954058fac8cc415d7dfd53446; loaded process revision unproven. certbot-renew.timer was disabled/inactive; this does **not** rule out cron or another ACME mechanism. Idle RAM/swap/disk evidence is not peak capacity or restored-backup evidence.

## 2. Minimum backup coverage before staging

| Component | Classification / coverage | Minimum recovery evidence |
|---|---|---|
| EC2 root and system state |Persistent OS/config/data. OS packages can be rebuilt, but current configuration and data are not disposable.|Coherent application backups first; approved private root snapshot/encrypted recovery copy and boot mapping. A running-volume snapshot alone is only crash-consistent absent application coordination.|
| Operational SQLite |Persistent run/quality/incident/timing history at `/home/ec2-user/Electricity_Trading_Pipeline/database/electricity_trading.db`; include a consistent database image, not a loose WAL copy.|Online backup API, manifest/hash/schema/counts, restored integrity and semantic counts. Never copy a busy `.db` alone.|
| PostgreSQL / Prefect metadata |Persistent deployment/run/schedule state; actual data directory/version/roles still need owner verification. Source template points to local database`prefect`.|Logical consistent dump, compatible restore runtime, role/grant/extension plan and isolated restored catalog/run/deployment checks. A SQLite test does not cover it.|
| Legacy Prefect SQLite / PREFECT_HOME |Candidate older local state; determine whether still used. Profiles may contain credentials.|Inventory fixed DB metadata; retain only required state. Do not read/copy profiles or credentials into this audit.|
| MLflow metadata/artifacts |Potential persistent `mlflow.db` and `mlruns`; code defaults are candidates, not live configuration proof.|Consistent metadata backup with referenced artifact set and checksums; restore experiment/run-to-artifact references privately. No training/tracking server started.|
| Frozen models/contracts/manifests |Persistent release evidence; binary digests and feature order must survive.|Exact binaries, contracts/manifests and checksums. Validate loading only in isolated model runtime, never unpickle untrusted content or train replacements.|
| Raw/Silver/Gold, forecasts/anomalies/evaluation/monitoring reports |Raw and issuance/evaluation history may not be reproducible from upstream later. Some derived layers can rebuild, at nontrivial time/cost.|Approved coherent generation, timestamps, hashes and reference/model relationships. Preserve unavailable/withheld states. Do not regenerate data merely for this test.|
| Nginx/systemd/runtime |Persistent configuration; packages/releases/venvs reconstructible from reviewed source plus compatible locks.|Owner-protected known-good configurations, modes/owners, enabled-unit state, source/artifact hashes and interpreter/package versions. Configs can contain secrets; do not dump them to chat/repo.|
| Secrets / certificates |Required but excluded from agent content collection. Cognito clients, provider/group configuration remain unchanged.|Custodian attests recoverable secret-store identifiers/version references and recovery permissions. Never retrieve values, copy `.env`, private keys, secrets.toml, pgpass, AWS profiles or Certbot account keys here. A root snapshot would contain confidential files and needs explicit protected-snapshot approval.|
| Logs/cache/tmp/venvs/build outputs |Normally reconstructible/disposable; some retained incident records have audit value.|Agree retention; do not back up request logs blindly or delete anything in this phase. Preserve rollback release/assets/config until acceptance.|

Required secrets include ingestion credentials, any database/Prefect credentials, Streamlit/OIDC session/client secrets still needed for rollback, notification credentials and ACME key material. A fresh production SPA is public and has no client secret. Document only references/ownership, never values. If secrets exist only on the unencrypted root and cannot be restored safely by a custodian, full recovery remains blocked; do not claim source control recreates them.

For a non-invasive isolated API snapshot trial, operational SQLite, a coherent read-only market/report/model generation and verified runtime are the minimum data subset. Before any host replacement, production service change or cutover, PostgreSQL/Prefect, MLflow, root/configuration and secret recovery must also be covered. Keep this distinction explicit.

## 3. A — Recovery batches and executable first-backup proposal

### A0 — Approved and completed: read-only metadata, no backup creation

Review `deploy/remediation/read-only-recovery-inventory.sh`.

SHA-256: `fa5b45b84d228037832132ebac88973623f8f584571097411dc19a7ae8296f4c`.

Exactly: fixed-path DB/WAL/SHM existence/type/size/mode/UID/GID for operational SQLite, candidate mlflow.db and legacy Prefect SQLite; allocated directory bytes for database, data, artifacts, candidate mlruns and candidate`/var/lib/pgsql/data`; available filesystem bytes. `du` reads filesystem metadata without emitting traversed filenames/errors, stays on one filesystem, and times out after8seconds per directory. Missing, denied or timed-out paths are **unverified**, never evidence an external location is absent. No database query, file-body/secret/config/log/argv/environment read, sudo, service action, AWS write or backup/restore.

Execution approved by the owner and completed once, from this repository, using this unchanged command and reviewed script:

```sh
ssh -F /dev/null -i /Users/iannganga/.ssh/powerflow-key.pem \
  -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none \
  -o StrictHostKeyChecking=yes -o UpdateHostKeys=no \
  -o UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts \
  -o ForwardAgent=no -o RequestTTY=no -o ConnectTimeout=10 \
  -T ec2-user@3.228.243.164 'bash -s' \
  < deploy/remediation/read-only-recovery-inventory.sh
```

Do not display/read/copy the private key. Stop on an unknown/changed host key, wrong target or required privilege; no alternate username/host/sudo. Normal SSH audit records and bounded metadata I/O occur. No added AWS resource cost or intended downtime; rollback unnecessary because no configuration/data changes. Permission denial yields unknown evidence, not permission changes.

### A0 observed results — 25 October 2026

Execution: **23:02:15–23:02:19 Africa/Nairobi** (20:02:15–20:02:19UTC), one SSH attempt, exit0. SHA-256 matched the approved `fa5b45b84d228037832132ebac88973623f8f584571097411dc19a7ae8296f4c` before sending the exact bytes through `bash -s` stdin. Strict pre-existing host-key verification, existing ec2-user/key and no agent were retained. No script copy/install, sudo, retry, extra remote command or production write was performed. SSH stderr was present but not displayed; structured stdout parsed successfully. Directory-level failures are explicitly unknown despite the overall exit0.

**File sizes below are logical sizes; directory totals are allocated bytes. They are different measures and must not be added blindly.** UID/GID values are numeric observations, not newly resolved account names.

| Fixed path / file | Observed bytes | MiB | Mode / UID:GID | Result |
|---|---:|---:|---|---|
|`/home/ec2-user/Electricity_Trading_Pipeline/database/electricity_trading.db`|13,213,696|12.6016|0644 /1000:1000|Regular file, not symlink|
|Operational`electricity_trading.db-wal`|—|—|—|Not found at the fixed path at inspection time|
|Operational`electricity_trading.db-shm`|—|—|—|Not found at the fixed path at inspection time|
|`/home/ec2-user/Electricity_Trading_Pipeline/mlflow.db` and its`-wal`/`-shm`|—|—|—|All three not found at these fixed paths|
|`/home/ec2-user/.prefect/prefect.db`|1,302,528|1.2422|0644 /1000:1000|Regular file, not symlink|
|Legacy Prefect`prefect.db-wal`|4,132,392|3.9410|0644 /1000:1000|Regular file, not symlink|
|Legacy Prefect`prefect.db-shm`|32,768|0.0312|0644 /1000:1000|Regular file, not symlink|

No database was opened or queried. Missing operational sidecars do not prove a journal mode or that the DB is idle; online backup remains required. The Prefect candidate has WAL/SHM state, so do not classify it as disposable or copy only its base DB. WAL existence does not establish a live writer or prove which backend the current server uses. Confirm its role separately without dumping profiles/environments, and preserve it in the recovery coverage decision until resolved. Do not use the PowerFlow operational-table validator for a Prefect database.

Mode0644 has group/other read bits. Effective access also depends on uninspected parent-directory permissions and ACLs; A0 does not establish that arbitrary local users can traverse the paths. This is a confidentiality consideration for the later isolation/permissions review, not authorization to chmod live files. Any new backup is still proposed as private0700/0600; no permissions were changed.

| Fixed directory | Allocated bytes | MiB | Status |
|---|---:|---:|---|
|Checkout`database/`|13,639,680|13.0078|Observed|
|Checkout`data/`|104,177,664|99.3516|Observed|
|Checkout`artifacts/`|5,996,544|5.7188|Observed|
|Checkout`mlruns/` candidate|—|—|Unverified|
|`/var/lib/pgsql/data` candidate|—|—|Unverified|

The script deliberately suppresses raw `du` errors. An unverified directory may be missing, inaccessible, timed out or otherwise unreadable; the exact cause is unknown. Do not report MLflow artifacts or PostgreSQL data as absent, search for alternate locations or retry with privileges under A0. No source-data/model/report contents were inspected.

Filesystem: **21,395,124,224bytes total (19.9258GiB)** and **12,805,435,392bytes available (11.9260GiB;59.85% of total)** for the checkout filesystem. This is available-to-caller space at one instant, not a disk-growth or peak-I/O guarantee. No filesystem usage elsewhere was measured.

**Sizing implications for A1:** observed operational DB12.60MiB is below the proposed128MiB source+WAL ceiling. With no observed WAL, the script's conservative3×source+64MiB allowance is **106,749,952bytes (101.8047MiB)**. After reserving that workspace, available bytes would be12,698,685,440, exceeding the25%filesystem reserve(5,348,781,056bytes) by7,349,904,384bytes at this observation. A1 must repeat its size/free-space guards at execution; these arithmetic checks establish only current sizing feasibility. Installed helper hash/runtime, new destination availability, confidentiality/retention decision and explicit A1 approval remain prerequisites. This is not evidence of a backup, integrity check, schema/count verification or restoration.

The measured database/data/artifact directory totals inform a modest snapshot transfer, but they do not cover Prefect home state, inaccessible/unknown PostgreSQL/MLflow stores, system configuration, secrets, root filesystem or future growth. Do not treat their sum as the full recovery budget. A2 off-host destination/protection and A3 complete-store coverage remain unverified; no temporary resource is justified solely by these small partial totals.

Local metadata-only evidence: `/tmp/pf5d2-a0-observed.json` and `/tmp/pf5d2-a0-execution.json`. No production data or backups were copied into the repository.

### A1 — Separate production-write approval: one operational SQLite backup

Final review dated26October: see [phase5d2-a1-execution-review.md](phase5d2-a1-execution-review.md) for the complete unchanged payload, precise scope, verification limits and actual own-attempt cleanup behavior. That review supersedes stronger generic statements below. The subsequent separately approved one-time execution is recorded in the result section below.

Reviewed and subsequently **executed once with explicit approval**: `deploy/remediation/backup-operational-sqlite.sh`, SHA-256 `eb385dcc8afbe08c3f3bdf5f4ed05da4e6a3e9811fee500b05794ef997c87896`.

After A0, approve this exact script separately using the same strict SSH command with only the input file changed. Source is the operational SQLite path above; sole new destination root is `/home/ec2-user/powerflow-recovery-phase5d2-operational`, outside the checkout. Refuses an existing destination/symlink, source outside its expected canonical path, source+WAL>128MiB, insufficient workspace or less than25%filesystem reserve after a conservative3×source+64MiB allowance. It uses the existing `.venv-prod/bin/python`, disables bytecode writes, imports only the reviewed standard-library recovery helper, and creates one timestamped private backup+manifest. No new dependency or runtime installation.

The helper is pinned to SHA-256 `c2bc8f38158db4331220a0658e2b58bddccb73bf374d65df5b87d1907c532bc5`, matching the local file and its blob at the previously observed production checkout revision. **This is not a claim the installed file matches**: the script verifies it and stops on mismatch. No restart/pull/deployment is used to resolve drift.

Important correction to generic older commands: `scripts/backup_operational_state.py` currently autoloads `.env` in its CLI. This scoped proposal deliberately bypasses that CLI and calls `backup_operational_database`/`validate_operational_backup` directly. No `.env` or provider credential access is needed. The helper scans operational text for obvious credential-like content and refuses it; this heuristic is not proof the resulting backup contains no confidential information. Treat backup and manifest as confidential.

Source SQLite is opened read-only and backed up online, then **only the backup** is compacted/checked. The pipeline may legitimately write concurrently; never compare live DB byte hashes and call normal writes corruption. Record the returned backup ID, digest, count summary, actual duration and operator. No raw rows/incident messages are printed. Validation checks required/table-name lists, hash/size and quick_check; schema objects are recorded but not fully compared. No upload, restore or service action occurs. The helper may delete only artifacts created by its own failed attempt, as detailed in the final A1 review.

Preconditions: A0 fits budget, fixed source/helper/runtime verified, no conflicting maintenance, owner approves confidential private local backup on currently unencrypted root and follow-on protected off-host handling. No planned downtime; a read transaction/scan adds I/O and may retain WAL pages temporarily. Stop if normal application/pipeline latency or disk pressure degrades. Additional local storage is not a new EBS allocation; no new resource charge within current volume. Local-only copy is not disaster recovery. The helper may clean its own failed-attempt artifacts; validation/interruption can leave private artifacts. Do not perform additional cleanup or repeat into the same root automatically. Production source is never overwritten, so rollback is not a database restore.

### A1 executed result — 26 October 2026

**A1 approved and completed once. Do not rerun.** The owner's explicit approval covered the unchanged script/helper hashes, one strict SSH stdin execution and the limited private local backup only. Both local hashes matched before execution; remote helper verification is a prerequisite of the successful approved payload. No remote code was replaced or installed.

- Started **05:22:26 Africa/Nairobi** (02:22:26UTC); finished **05:22:31 Africa/Nairobi** (02:22:31UTC). Client-observed duration including SSH: **4.861seconds**; not a measured restorationRTO or backup-only duration.
- SSH exit **0**, one attempt, no retry, no extra remote command, no overall-deadline trigger/stall. Strict pre-existing host-key verification and the existing ec2-user/key were used. SSH stderr was present but not disclosed; no application error was reported in the structured success result.
- Backup ID: `20261026T022230.137446Z`.
- Backup directory: `/home/ec2-user/powerflow-recovery-phase5d2-operational/20261026T022230.137446Z`.
- Database: `/home/ec2-user/powerflow-recovery-phase5d2-operational/20261026T022230.137446Z/electricity_trading.db`.
- Manifest: `/home/ec2-user/powerflow-recovery-phase5d2-operational/20261026T022230.137446Z/manifest.json`.
- Backup SHA-256: `21fcb0e920ffaf13f214e39720e1176e012086d6ffa7b8a7ed736b6e4ab79690`.

| Required operational table | Aggregate backup rows |
|---|---:|
|pipeline_runs|891|
|data_quality_results|16,525|
|operational_incidents|1,485|
|pipeline_stage_timings|11,561|

**Validation:** success is emitted only after the pinned helper creates the backup and `validate_operational_backup` returns. This establishes that backup quick_check, manifest hash/byte-size agreement, table-name list/required-table checks and aggregate-count queries completed successfully. Raw integrity messages and backup data were not printed. Full integrity_check/foreign_key_check, schema-SQL parity, independent live-source row-count comparison and actual restoration were **not** performed or claimed.

**Exact backup byte size is not available from the authorized output.** The helper measured/stored it in the private manifest and validated it internally, but the unchanged A1 stdout omits it. A0's13,213,696-byte source measurement is historical source size, not this backup's size. No additional stat, manifest read or filesystem diagnostic was run. Reporting the numeric size would require separate approval for a fixed-path metadata check; do not infer it from A0, hashes or row counts.

**Artifacts and impact:** the payload reported success, so no failed or incomplete artifact was reported; no independent directory listing was authorized to attest to all temporary files. Expected final artifacts are the DB and manifest above. The reviewed script sets private0700directories/0600files; no extra permission stat was performed. No stop/restart/reload, pipeline trigger, source write SQL, live permission change or service configuration action was executed. The operation finished promptly with no stall/failure observed through this SSH result, but no additional production health/log check was authorized; continuous website/service availability or zero transient contention is not independently certified.

**Protection/recovery:** the backup remains solely in the approved private directory on the existing **unencrypted root volume**. No S3 object/snapshot/resource, upload/off-host copy, PostgreSQL/Prefect-SQLite/MLflow backup, actual restoration or deployment was executed. The result explicitly returned `off_host_backup_verified=false` and `production_restore_verified=false`. One local copy on the source host is not disaster-recovery protection. No cleanup/deletion was performed after success; retention/cleanup, metadata-size check and A2 each require separate approval.

Evidence retained locally outside the repository: `/tmp/pf5d2-a1-result.json` and `/tmp/pf5d2-a1-execution.json`, private mode0600, containing only the approved aggregate result and local execution metadata. No raw database, manifest or secrets were copied into the repository.

### A2 — Same-host isolated restoration passed once

On 26 October 2026, after explicit approval, the unchanged payload's local SHA-256 matched `e0144438075b5219a2b03a7dad982bab14bde81d92d6c79cf11253c91284262c`. The exact reviewed SSH command ran once through stdin, with strict host-key verification, the 90-second internal deadline and 120-second external timeout plus five-second kill escalation intact. No retry or additional SSH inspection ran. See [execution review](phase5d2-a2-execution-review.md).

Execution began **03:03:59.557160 UTC (06:03:59.557160 Africa/Nairobi)**. SSH exited **0**, payload status **passed**, stage **completed**. SSH wall duration was **4.842914 seconds**; payload total was **0.308794 seconds**; database copy/restoration was **0.026977 seconds**. Payload total excludes final result-record serialization; SSH wall duration includes transport and interpreter startup.

| Check | Actual result |
|---|---|
| Original SHA-256 before restoration | Verified against approved `21fcb0e920ffaf13f214e39720e1176e012086d6ffa7b8a7ed736b6e4ab79690` |
| Restored SHA-256 | `21fcb0e920ffaf13f214e39720e1176e012086d6ffa7b8a7ed736b6e4ab79690` |
| Original / restored database size | **12,115,968 bytes each** |
| Full `PRAGMA integrity_check` | **ok**, the required complete success result |
| `foreign_key_check` | Completed, **0 violations**; **0 declared foreign-key constraints**, so this does not establish application-level relational correctness |
| Schema and indexes | Core column/default/PK contract and six required indexes passed; all manifest objects matched; **4 tables / 10 noninternal schema objects** |
| `pipeline_runs` | **891** |
| `data_quality_results` | **16,525** |
| `operational_incidents` | **1,485** |
| `pipeline_stage_timings` | **11,561** |
| Count parity with A1 | All four matched |
| Read-only query verification | Passed using immutable, read-only SQLite connection |
| Original backup and manifest unchanged | Confirmed by payload's before/after hashes and metadata checks |
| Free-space guard | Passed; computed workspace allowance **103,456,768 bytes**, with required filesystem reserve |
| Result record | Written successfully |

Artifacts retained, with no deletion: `/home/ec2-user/powerflow-a2-restore-20261026T022230.137446Z/restored-electricity_trading.db` and `verification.json`, under the new private 0700 directory with 0600 files as enforced by the approved payload. No partial/failed artifact was reported; no independent listing was authorized. SSH emitted stderr bytes, but diagnostics were not retained or displayed to avoid exposing operational details; no diagnostic cause is asserted. Exit 0 and the structured result establish success, not the absence of transport warnings.

The live operational database was not opened; no production services/configuration were changed or restarted. No stall or production failure was observed through the execution result; no extra health check was authorized, so uninterrupted availability or zero transient disk contention is not independently certified. Both backup and restore remain on the existing **unencrypted root volume**. This verifies isolated database restoration, **not off-host protection or full application recovery**. PostgreSQL, Prefect and MLflow recovery remain outside this test.

Private local aggregate evidence: `/tmp/pf5d2-a2-result.json` and `/tmp/pf5d2-a2-execution.json`. No database contents, manifest contents, secrets or raw SSH diagnostics were copied into the repository. Earlier local preparation tests: 55 focused and 683 full backend tests passed; these were not rerun for this documentation-only result update.

#### Earlier off-host options — retained for future separate approval, outside this A2 request

The older options below are planning references only, not the selected execution procedure and not authorization to transfer, restore, overwrite or clean up anything. In particular, the old helper-based restore is superseded for this A2 request by the new self-contained, no-cleanup payload.


First choice: existing trusted owner workstation, **confirmed encrypted storage**, private0700 directory outside any repo/cloud sync; approved transfer of the selected operational backup only, not source credentials. No new EC2 cost. Existing private S3 backup prefix is an alternative; exact bucket, version IDs, encryption, access/retention and transfer charges must be bound before approval. Do not guess the bucket or use a script that autoloads secrets. Object versions and source-backup digest must be fixed in the ticket. Allow at most$1 incremental request/transfer/storage pending actual bytes; stop for revised approval if exceeded.

For a later **separately approved S3 option**, use explicit CLI operations rather than dotenv-loading application helpers: `s3api put-object` for the database and manifest with the verified bucket, unique `backups/operational/<backup-id>/` keys, `--server-side-encryption AES256` and `--if-none-match '*'`; record returned VersionIds. Retrieval uses `s3api get-object --bucket <verified-bucket> --key <approved-key> --version-id <recorded-version-id> <new-private-local-file>` for each object, followed by local manifest/hash validation. Bucket identity, account ownership, encryption/public-access settings, keys, version IDs, destination and exact transfer commands must be filled in and approved before use. Do not use unversioned “latest” download as proof of the selected backup or change bucket/IAM policy to make a transfer succeed. No S3 object operation was executed here.

No transfer or actual restore was performed. Separate approval must cover confidential data movement, destination encryption/access, selected backup ID/digest and no repository storage. If workstation protection cannot be established, propose temporary encrypted isolated EC2 rather than weakening protection: t3.small+20GiBgp3+IPv4 approximately$1.34/48h, plus variable storage/transfer, proposed total cap$3 and explicit cleanup. Reuse a later approved staging host if possible, not another permanently running instance.

After approval, validate the downloaded manifest/digest before using it. On the isolated trusted runtime, with `umask 077` and a newly created private destination parent:

```sh
python scripts/validate_operational_backup.py <approved-private-backup-directory>
python scripts/restore_operational_state.py <approved-private-backup-directory> \
  --destination <new-private-isolated-directory>/electricity_trading.db
```

Placeholders are not ready-to-paste arguments. Never use`--force`, restore to a production path or start a pipeline against the copy. Run `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, compare expected schema/table counts to the backup, and inspect only safe aggregate watermarks/status categories. A restored backup should match **its own** capture point, not a later live DB count. Record acquisition end, capture point, validation/restore/startup durations with a monotonic clock and operator timestamps. RTO includes retrieval/runtime/configuration/validation, not merely SQLite copy time; RPO derives from the last coherent backup and accepted data-loss window. The local synthetic drill proves neither.

Rollback/disposal: production untouched; leave private isolated artifacts until explicit retention/deletion approval. Returning a restored DB to production requires a separate incident plan, single-writer coordination and pre-restore backup; never do so for a frontend rollback.

### A3 — Complete PostgreSQL, MLflow, files and protected configuration recovery

Separate approval after locations/versions/permissions and storage budget are verified. PostgreSQL's actual data directory and application role are not established by a source template. Owner-operated read-only SQL can establish `SELECT version(), current_database();`, `SHOW data_directory;`, `SELECT pg_database_size(current_database());` through an already approved local connection; no password in command/chat, no arbitrary credential guessing or unapproved sudo.

Proposed logical backup operation once role/client/version are known: `pg_dump --format=custom --no-owner --no-acl --dbname=prefect --file=<private-new-dump>`. Select a compatible pg_dump major; no admin flag or connection URL with password. Custodian handles connection auth without exposing it. Do not dump role password hashes. Reconstruct required role/grants/extensions from a reviewed non-secret plan and custodian-held credentials. PostgreSQL makes a consistent per-database dump during normal writes, but this does not synchronize it with SQLite/files; record separate capture times or obtain an approved coordinated quiet window. [PostgreSQL guidance](https://www.postgresql.org/docs/current/app-pgdump.html).

Inspect the archive list only privately, then restore to a **new isolated database/cluster**, never the live Prefect DB: `pg_restore --exit-on-error --no-owner --no-acl --dbname=<isolated-database> <private-dump>`. Verify schema/extensions/counts/deployment/run relationships; scheduler/network write paths remain disabled. Do not boot a production clone with its original enabled Prefect worker/server or storage credentials: it can run jobs and mutate production. Full PG restore on the2GiB production host is not approved or assumed safe.

MLflow needs its real tracking URI/metadata/artifact roots established without dumping environments. For SQLite metadata use an online SQLite backup suitable for its schema, **not** the operational validator which requires PowerFlow tables. Match immutable artifact references and hashes; if artifacts can change, approve a quiet window or a versioned coherent manifest. Do not start training/tracking writes. Frozen model/artifact/data generations require manifests with byte counts, digests, model release/feature contract and observation/issue watermarks. A mutable multi-file copy is not automatically coherent. Required source data and historical forecasts/evaluation cannot be assumed reproducible upstream.

Nginx/unit/application configuration recovery is custodian-managed, protected and versioned; never dump configs that may embed credentials into chat/repo. Record only reviewed release/config hashes and ownership. Secret-store references and access recovery must be attested without retrieving values. Encrypted root recovery may retain confidential files with explicit approval; it does not substitute for tested logical restoration. A3 remains blocked until these locations and protections are known.

## 4. B — TLS scheduling verification, then conditional remediation

**B1 is a separate read-only host approval, not included in A0.** Proposed exact commands:

```sh
systemctl list-unit-files --type=timer 'certbot*' '*acme*' --no-pager --no-legend
systemctl list-timers --all 'certbot*' '*acme*' --no-pager --no-legend
systemctl show certbot.timer certbot-renew.timer crond.service --property=Id,LoadState,ActiveState,SubState,UnitFileState,NextElapseUSecRealtime,LastTriggerUSec
stat -c '%F|%s|%a|%U|%G|%n' -- /etc/cron.d/certbot /etc/cron.d/certbot-renew /etc/letsencrypt/renewal/powerflowenergy.dev.conf /etc/letsencrypt/renewal-hooks/deploy
openssl x509 -in /etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem -noout -dates -issuer -ext subjectAltName
```

The certificate path is a candidate, not an installed-path claim. Missing/denied files stop that check; no sudo, path search or key access is implied. List timers may show no matches. This covers known candidates, **not all cron jobs**.

Custodian-only additional evidence, separately approved: whether root/ec2-user/system cron/anacron or another ACME client schedules renewal; active job/service ownership and last successful result; selected Certbot renewal method/webroot/plugin; whether saved pre/post/deploy hooks or hook directories reload Nginx; correct reload command and failure handling. Do not run `crontab -l`, dump units/renewal configs or `nginx -T` to chat: they may contain credentials. Operator reports only sanitized schedule/method/hook-presence/validated reload status. Absence from two fixed cron filenames is not proof no alternative exists.

Neither `certbot certificates` nor `certbot renew --dry-run` is assumed read-only: Certbot can lock/write logs/account/challenge state. No Certbot operation ran. Current valid certificate plus disabled timer does not prove renewal works or fails.

**B2: separate controlled renewal rehearsal**, only after B1/private custodian review and a known supported installed Certbot version. Candidate command is `certbot renew --cert-name powerflowenergy.dev --dry-run --no-directory-hooks`, executed by the approved operator under its reviewed privilege method. It is not approved now and is not safe blindly: `--no-directory-hooks` does not negate every saved pre/post hook or authenticator reload; dry-run can execute configured hooks and validation actions. No`--run-deploy-hooks`,force-renewal,reinstall or new authenticator. If method needs stopping Nginx/standalone mode or any unexpected hook/config change, stop and seek a revised downtime/action approval. [Certbot hook semantics](https://eff-certbot.readthedocs.io/en/stable/using.html).

**B3: conditional scheduler fix.** Only if no effective alternative exists and B2 succeeds, propose `systemctl enable --now certbot-renew.timer` for the verified existing timer/service. This needs explicit approval covering possible immediate overdue renewal and reviewed hooks; do not install a second competing scheduler. Read back timer enabled/next/last state and verify the public certificate. If another mechanism already works, make no change. Disabling the newly enabled timer is rollback only when the prior schedule is restored and renewal coverage maintained; do not delete issued certificates or blindly disable existing working automation.

Nginx deploy hook should validate configuration before graceful reload, e.g. verified installed absolute Nginx path `nginx -t` then `systemctl reload nginx`, only in its own approved hook change. No restart required by this proposal. Real reload behavior is not verified by source templates. Proposed cost: certificate fee$0, no new resource; routine operations/monitoring budget applies. Downtime target none for a proven webroot/compatible plugin, but not guaranteed before method/hook verification. Rollback retains prior protected configs/certificate and reload mechanism; any issued certificate remains unless separately reviewed.

React routing must preserve the **actual** ACME method. A catch-all SPA response, redirects, hidden-file denial or new static root must not swallow `/.well-known/acme-challenge/` if webroot is used. The Phase5D.1 Nginx file is not installable until this is merged and syntax/rehearsal passes. No DNS/certificate/renewal/Nginx action is currently approved.

## 5. C — Running API identity, without restart or credential exposure

Already proven:8000is loopback uvicorn and matched powerflow-api.service PID; unit uses ec2-user and the production checkout working directory. A checkout revision, unit name or old source template does not establish loaded Python modules, runtime dependencies, dirty working tree or JWT implementation.

Separate proposed C1 read-only bundle:

```sh
systemctl show powerflow-api.service --property=Id,MainPID,User,Group,WorkingDirectory,FragmentPath,ActiveState,SubState,ExecMainStartTimestamp,MemoryCurrent
systemctl show powerflow-api.service --property=MainPID --value
ss -ltnp 'sport = :8000'
sha256sum /home/ec2-user/Electricity_Trading_Pipeline/src/api/app.py /home/ec2-user/Electricity_Trading_Pipeline/src/api/security.py /home/ec2-user/Electricity_Trading_Pipeline/src/operational_recovery.py
```

After the numericPID is verified against the listener, request exact per-PID approval for `readlink /proc/<verified-pid>/cwd /proc/<verified-pid>/exe` and `ps -p <verified-pid> -o lstart=,comm=,user=`. Do not guess/reuse a stalePID or inspect cmdline/environ/fullstatus. Read-only loopback `GET /health` can confirm compatibility, but never dump arbitrary response bodies or assume its name proves security. Further endpoint comparisons need a separately scoped list and sanitized status/schema output; no administrative access implied.

Custodian privately confirms sanitized ExecStart interpreter/module/venv and allowed environment-setting **names**, never values, plus release manifest and deployed file hashes/start provenance. No account token, process memory, unit content, secret/env file or raw log inspection. Existing code can change on disk after import: hashes/cwd/interpreter/start time narrow possibilities but **cannot prove the current process loaded those bytes**. If no trusted build/start manifest exists, record “unverified” rather than restarting to manufacture evidence.

Future candidate releases should carry immutable source/lock/artifact hashes and a root-owned deployment/start record; bind PID/unit to that manifest during an approved new-service start. No new public version/path endpoint is proposed. Existing8000consumers must be identified before replacement/retirement. C1 has no added resource cost or intended downtime; no rollback needed. Failure or uncertainty never authorizes restarting the oldAPI.

## 6. D — Minimum capacity evidence

Current evidence remains point-in-time:1909.74MiB RAM,1026.27MiB available,817.42MiB swap used,11.93GiB free disk;9fresh vmstat intervals no swap I/O. At25%reserve, incremental idle allowance~549MiB, not a peak bound. Selected systemd MemoryPeak fields were absent. Earlier local real-data benchmark~171.27MiB process high-water and~1.066s/eight threaded function calls is not EC2 concurrency/inference evidence.

**D1: propose passive observation of already scheduled work, no induced requests/run.** New host commands require their own approval. Minimal exact primitives:

```sh
free -b
vmstat -w 5 121
df -B1 --output=size,used,avail,pcent /
systemctl show powerflow-api.service powerflow-prefect-worker.service powerflow-prefect-server.service postgresql.service powerflow-streamlit.service --property=Id,ActiveState,SubState,MemoryCurrent,MemoryPeak,MemorySwapCurrent,MemorySwapPeak,TasksCurrent
```

The121-sample timing must be matched to a known normal pipeline schedule; the shown vmstat command provides ten minutes, not a new pipeline execution. First vmstat row is since-boot and excluded from interval rates. Propose repeating the selected systemd query every10seconds over that same window, timestamped and collected client-side; the exact sampler/repetition bundle must be approved before execution, not improvised after D1. Missing peaks remain unknown; sampled maxima can miss brief spikes. Privately available historical cgroup peaks may be conservative high-water values since unit start, not this window. No reset of peak counters.

Capture worker/server/PG/API/Streamlit separately without summing shared accounting as unique RAM. Include the actual already-scheduled forecast stage and backup overlap only if naturally present and approved; no training or source-data mutation. Correlate timing with sanitized normal-run metadata. No `iostat` installation if absent; use vmstat I/O/wait and, under separately explicit scope, read-only kernel memory/I/O-pressure counters. Do not read process args/logs to identify activity.

**D2: isolated replay**, preferably same temporary encrypted host later used for staging or protected existing workstation. Copied approved data/models, no production credentials/network write paths, no scheduler. API-only runtime handles cold/warm reads, full historical serialization, index replacement, missing/error responses and bounded concurrency; inference runs separately in its correct model environment. PostgreSQL/Prefect have separate requirements: a tiny API footprint does not size the whole stack. Measure simultaneous API/pipeline/backup memory and I/O in isolation before considering shared-host overlap.

Proposed objective gates, agreed before test:

- No OOM, unexpected restart, corruption, wrong role or pipeline disruption.
- At least25%physical MemAvailable throughout the observed representative window and25%filesystem free after retention/release/backup workspace; current caps do not reserve that capacity.
- No sustained swap-in/out across three consecutive fresh5-second intervals; occupied inactive swap alone is not failure. Investigate sustained I/O wait>10%for30seconds; neither metric alone proves performance acceptable.
- Candidate process/cgroup peak below its reviewed memory ceiling with cold-rebuild margin; if peak evidence is unavailable, capacity is still unverified.
- Proposed p95<2s ordinary bounded reads, no unexplained5xx; separately agree a large full-history payload budget. Historical one-hour response currently grows without UI pagination, a capacity limitation rather than permission to alter the contract here.
- Normal scheduled execution finishes without material regression; use measured prior-duration baseline, not invented SLA numbers.

D1 passive metadata has no added resource allocation/downtime; D2 uses approved lifetime/storage costs. Stop only the isolated test workload on failure; never kill pipeline/PG/Streamlit or resize automatically. Result supports capacity only for measured workload/data size. No active production load test, forecast trigger, backup or restart ran here.

## 7. E — Final service-isolation proposal

Retain Phase5D.1 candidate on **8010**, dedicated `powerflow-api` user/group, one worker and isolated `.venv-api`; existing8000and all pipeline/PG/Streamlit identities remain untouched. Templates remain `deploy/preflight/powerflow-react-api.service` and `api.env.example`.

| Target | Approved-later implementation proposal / prerequisite |
|---|---|
|Identity|Create system account with no shell/home/sudo only after reviewing local user/group collisions; never reuse ec2-user. Exact OS account command depends on installed nologin path.|
|Code/runtime|Root-owned immutable release, approved interpreter, pinned API-only dependencies; no Streamlit/Prefect/model runtime imported. ProtectSystem=strict,ProtectHome,PrivateTmp/Devices,NoNewPrivileges,empty capabilities.|
|Data|Separate coherent publication under `/srv/powerflow/published`, root:powerflow-api0750, files0640; publisher alone writes. Never chmod the live SQLite/PG/MLflow writer trees to fit API. API sees an online SQLite backup generation, not writer WAL.|
|Environment|Root-owned0600`/etc/powerflow/react-api.env`; systemd reads before privilege drop. Public issuer/client settings only; no ingestion/root/admin credentials.|
|Metadata/network|Disable SDK metadata and enforce IPv4/IPv6 metadata denial if cgroup/BPF supported; verify actual denial. Cognito HTTPS/DNS allowed. If unsupported, stop for approved alternative, no silent weakened service.|
|Caps|Proposed MemoryHigh384M/Max512M/SwapMax0,CPU100%,Tasks64,oneworker/concurrency32,StartLimit3per60s. Hypotheses until D2passes; may be too low or too much shared-host pressure.|
|Lifecycle|Graceful shutdown20s/stop30s, failure restart5s; bounded restart limit. Rehearse in isolation; no restart of currentAPI.|
|Logs|Sanitized journald fields, no query/body/token/access logs; restricted reader membership and bounded retention. Do not change global journal policy without impact review.|

E1 request must name the reviewed release ID, actual interpreter/install paths, free8010, package artifact hashes, unit/env/filesystem diff, account commands, client binding and rollback. Current unknowns prevent a safe ready-to-run production install bundle. `systemd-analyze verify <candidate-unit>` and `systemd-analyze security <candidate-unit>` are future isolated validation, not proof of enforced permissions. Run as the dedicated user to verify denied writer/home/secret/metadata access. No such user/permission/unit/install operation occurred.

Local inspection found an important packaging gate: `requirements/api.lock` is pinned but has **no per-artifact hashes** and is currently labelled macOS-resolved. The earlier `pip install --require-hashes -r requirements/api.lock` example cannot succeed as-is. Before Linux deployment, generate/review an actual Linux-compatible hashed wheel/lock set in an approved isolated build, or explicitly approve a different verified artifact-install policy. Do not remove hash enforcement silently, claim Linux installation tested, or install/rebuild packages on production in this phase.

Cost: no additional steady-state VM on same host, but overlap remains unapproved; user/permissions cost$0, retained runtime/releases/logs consume measured disk/RAM. Rollback removes only approved candidate exposure, stops its own service if approved, restores its release/env pointer and leaves all existing services/data intact. No source cleanup or oldAPI retirement is implied.

## 8. F — Encrypted root replacement, maintenance approval only

Affected resources are exactly instance`i-059e63a35a022cd0f`, root`vol-097f44a4fdc5d1a00`, device`/dev/xvda`, AZus-east-1f. EIP allocation`eipalloc-044c2865e3193a2ac` remains associated; no release/reallocation/DNS change is proposed. The replacement is20GiBgp3/3000IOPS/125MiB/s, matching the observed volume. Existing DeleteOnTermination=true must be captured and preserved for the new root, while the detached original is retained deliberately for rollback.

Preconditions: A1–A3 successful **real** backups/restores, private config/secret recovery attestation, compatible boot/runtime tests, exact IAM/KMS permissions, verified EIP association/startup behavior, approved maintenance and rollback operator. Snapshot/copy/volume IDs do not exist yet; capture actual returned IDs in the ticket, never guess them. All snapshots remain private in this account. Prefer AWS-managed`alias/aws/ebs` inus-east-1: no new customer key policy/monthly key administration; customer-managed key is an alternative only with separate approval/recovery policy. [AWS encryption behavior](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-encryption.html).

The following is a **future operation sequence**, not approved execution. Each captured-ID variable must be validated against account/region/source/tags before the next step. Revalidate the fixed source IDs too. No `--force`, skipped OS shutdown, emergency detach, Fast Snapshot Restore, time-based copy, resizing or default account encryption change.

```sh
# F1: separately approved maintenance; graceful OS shutdown, all apps unavailable.
aws ec2 stop-instances --region us-east-1 --instance-ids i-059e63a35a022cd0f
aws ec2 wait instance-stopped --region us-east-1 --instance-ids i-059e63a35a022cd0f
# Capture the returned snapshot ID; do not use a guessed value.
aws ec2 create-snapshot --region us-east-1 --volume-id vol-097f44a4fdc5d1a00 --description PowerFlow-5D2-pre-encryption
aws ec2 wait snapshot-completed --region us-east-1 --snapshot-ids "$pf5d2_source_snapshot_id"
aws ec2 copy-snapshot --region us-east-1 --source-region us-east-1 --source-snapshot-id "$pf5d2_source_snapshot_id" --encrypted --kms-key-id alias/aws/ebs --description PowerFlow-5D2-encrypted-recovery
aws ec2 wait snapshot-completed --region us-east-1 --snapshot-ids "$pf5d2_encrypted_snapshot_id"
aws ec2 create-volume --region us-east-1 --availability-zone us-east-1f --snapshot-id "$pf5d2_encrypted_snapshot_id" --volume-type gp3 --size 20 --iops 3000 --throughput 125 --encrypted --kms-key-id alias/aws/ebs
aws ec2 wait volume-available --region us-east-1 --volume-ids "$pf5d2_encrypted_volume_id"
# F2: only after readback proves the expected new volume/snapshot/encryption/AZ.
aws ec2 detach-volume --region us-east-1 --volume-id vol-097f44a4fdc5d1a00 --instance-id i-059e63a35a022cd0f --device /dev/xvda
aws ec2 wait volume-available --region us-east-1 --volume-ids vol-097f44a4fdc5d1a00
aws ec2 attach-volume --region us-east-1 --volume-id "$pf5d2_encrypted_volume_id" --instance-id i-059e63a35a022cd0f --device /dev/xvda
aws ec2 wait volume-in-use --region us-east-1 --volume-ids "$pf5d2_encrypted_volume_id"
aws ec2 modify-instance-attribute --region us-east-1 --instance-id i-059e63a35a022cd0f --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"DeleteOnTermination":true}}]'
aws ec2 start-instances --region us-east-1 --instance-ids i-059e63a35a022cd0f
aws ec2 wait instance-status-ok --region us-east-1 --instance-ids i-059e63a35a022cd0f
```

Do not paste this sequence now: no variables are assigned and **no maintenance is approved**. Before F2, use DescribeSnapshots/DescribeVolumes to prove IDs, source lineage, completion, encryption key, size/type/IOPS/throughput/AZ and private snapshot permissions. F1's initial snapshot of an unencrypted volume is itself unencrypted: it contains confidential root files, must remain private, and needs an explicit retention/removal decision after protected recovery is proven. Encryption is not retroactive to that original copy.

Stopping with ordinary OS shutdown improves filesystem/database consistency, but confirm clean database shutdown/restore checks; a stopped flag alone does not certify every application transaction. Keep the instance stopped from the final consistent snapshot through replacement. Resuming the writer while preparing a clone and later swapping to that older clone would lose newer writes; do not do it without a separately designed reconciliation process. Downtime includes shutdown, snapshot/copy completion, attach, boot and validation and can be lengthy. Rehearse actual duration before choosing a maintenance window. If the approved timeout is exceeded, restore the original mapping/start state; do not extend downtime indefinitely or proceed with stale data.

After start: strict existing SSH host key, expected EIP/domain, publicTLS, existing Streamlit authentication and read-only navigation, privateAPI health, PostgreSQL/Prefect status and metadata, SQLite integrity/counts/watermarks, model/report digests and scheduled-run continuity. No manual pipeline trigger, Cognito change or general MFA enrollment. Validate copied filesystem/PG state in isolation before declaring recoverability; never boot an unisolated production clone that might launch a duplicate worker.

Rollback before accepting new writes: stop gracefully, detach the new root, reattach`vol-097f44a4fdc5d1a00`to`/dev/xvda`, restore the captured root attribute and start/verify. After new writes have occurred, the old root is stale: rollback needs an approved data reconciliation/recovery plan, not an automatic reattach. Do not mount two same-UUID clones read/write or force detach. Retain original volume and both snapshots until explicit cleanup approval; no delete operation is proposed now.

Cost estimate: one additional retained20GiBvolume~$1.60/month; conservatively two separate20GB standard snapshot copies~$2/month at$0.05/GB-month, actual stored changed blocks may be lower. Reserve **up to$4 incremental first-month storage/requests** from existing contingency, reapprove if exceeded. No permanent second VM, cross-region transfer, archive minimum retention or accelerated snapshot/copy is selected. AWS-managed keys have no monthly key fee; usage requests may still be charged. [EBS pricing](https://aws.amazon.com/ebs/pricing/), [AWS-managed KMS keys](https://docs.aws.amazon.com/kms/latest/developerguide/concepts.html). Keeping old resources longer continues charges; cleanup is a separate named-resource approval.

## 9. G — Gates, cost and approval order

| Batch | Can be completed without infrastructure modification? | Current state / next approval |
|---|---|---|
|A0 metadata|Yes, observational SSH only; bounded I/O and normal login records|Approved; completed once via unchanged stdin script; observed evidence above|
|A1 one private SQLite backup|No: writes new private backup artifacts, not sourceDB|Separately approved; succeeded once, private local backup only; do not rerun|
|A2 isolated restore|Prepared same-host private-directory test, no new AWS resources; creates new files only after explicit approval|Executed once and passed under separate explicit approval; off-host protection remains separate|
|A3 PG/MLflow/full configuration recovery|Some sanitized evidence read-only; dumps/transfers/restores need approvals|Actual locations/version/grants/secret recovery attestation pending|
|B1 scheduling evidence|Yes, read-only; private custodian review for potentially sensitive configs|Separate exact command approval; alternative cron remains unknown|
|B2/B3 rehearsal/scheduler fix|No: Certbot writes/hooks, timer change and potentially due renewal|Only after mechanism/hook review; make no change if another mechanism already works|
|C1 process/release evidence|Yes, selected metadata/hashes only|Separate bundle/per-PID approval; loaded bytes may remain unprovable|
|D1 passive scheduled peaks|Yes, observational metadata; no induced workload|Approve exact sampler/window; peak capacity still unknown|
|D2 isolated replay|Existing protected host may suffice; new AWS host costs/installation need approval|No live load permitted; no Linux capacity claim|
|E1 service isolation|No: user/unit/runtime/permissions/publication changes|Needs restore/capacity/client/release/path evidence and exact OS diff|
|F1/F2 encryption|No: snapshots/copy/new volume, instance stop/attach/start|Maintenance/cost/secret-containing snapshot/rollback approval only after real recovery|
|G1 staging deployment|No: resources/config/runtime/client exposure|Blocked until preceding required recovery/TLS/isolation/capacity/Linux gates pass; request separately|

The objective is recovery evidence before deployment, not executing every batch together. A0 and A1 are complete. A2's protected destination/transfer/restore and any extra byte-size metadata check require new approval. B1/C1can be independently approved but are not bundled intoA0. No existing broad audit is reopened without a specific missing prerequisite.

Budget remains dated planning evidence: approximately$95.25credit,31.43/month single-host plan and74.27for two months plus14-day temporary stage. No new billing query or promised cash balance. Prefer no new compute for the first SQLite restore; a48h fallback~$1.34base is not added twice if the same staging host is reused. Reserve at most$1for first transfer/backup variable usage or a separately approved$3fallback host total, and up to$4for first-month encryption overlap. These are proposed caps, not spent amounts or guarantees; charge estimates must be bound to actual bytes/retention and credit eligibility before approval. Preserve~$20.98planned headroom where possible, reconcile gross charges and avoid permanent dual instances. No additional paid resource was provisioned.

## 10. Local implementation and validation

New files this phase:

- `scripts/rehearse_operational_recovery.py`: no input paths/arguments, no AWS/provider calls; generates a disposable synthetic operational DB, invokes existing backup/validation/restore, verifies actual restored values, refuses overwrite, measures fixture times, cleans temporary data on success/failure. Output explicitly refuses production recovery/RPO/RTO claims.
- `tests/test_recovery_preparation.py`: success/semantic verification, tamper rejection+cleanup, CLI path rejection and syntax/static safety gates for both unexecuted host proposals.
- `deploy/remediation/read-only-recovery-inventory.sh`, `backup-operational-sqlite.sh`, `README.md`: exact independent operational proposals, not deployment.
- This report. No production runtime/auth/model/pipeline/frontend application code was changed; earlier Phase5D.1 working-tree changes remain untouched.

Executed locally:

| Command | Result |
|---|---|
|`venv/bin/python scripts/rehearse_operational_recovery.py`|Passed; synthetic backup0.020501s,restore0.001089s,integrityok,1fixture row,source unchanged,overwrite refused. Not realRTO.|
|`venv/bin/python -m pytest -q tests/test_recovery_preparation.py tests/test_recovery_tooling.py`|31 passed, 1.64s on final focused run|
|`venv/bin/python -m pytest -q`|659 passed, 31.04s, including existing pipeline/model/Streamlit/API/auth regressions|
|`bash -n` for proposed shell bundles and in-memory compilation of their embeddedPython|Passed, also asserted by tests; host commands were **not** executed|
|`git diff --check`|Passed|
|Public strictTLS and narrow AWS target binding|Results section1; no writes/SSH/account operations|

The final proposed shell commands use isolated Python (-I -S -B): no user-site/site initialization, Python environment path overrides or bytecode writes. The final focused run verifies these flags, source-size guard and shell/embedded-Python syntax. No production executable was tested by running it on a different or real host. No frontend code changed in this phase, so frontend81tests/lint/build remain Phase5D.1 evidence, not newly claimed runs. Nginx/systemd/Linux runtime/renewal/PG/root restoration tests remain pending. No new dependencies were installed.

No secrets/config/body/credential/token/MFA material was collected. A0 collected only its approved metadata. The separately approved A1 backup and A2 isolated restore were created. No snapshot, service restart, permission/IAM/Cognito/DNS/TLS change, deployment, active load, Streamlit shutdown or Git write occurred.

## 11. Boundary after A2

A0, A1 and A2 each ran once under separate explicit approvals. A2 passed using the pinned payload and command; no further remote operation followed. No cleanup was performed or authorized. Do not rerun into the existing destination.

Stop here. Off-host backup, additional production inspection, infrastructure remediation, restoration of other stores and staging deployment each require separate explicit approval. No Git staging, commit, push, merge or history change was performed.

## A3 preparation — 26 October 2026

The [A3 off-host recovery approval package](phase5d2-a3-offhost-recovery-review.md) proposes S3 Standard/SSE-S3, restricted recovery-prefix access, only the accepted A1 DB/manifest pair, and independent Mac restoration with no new EC2. Storage/access, upload and restoration require separate A3.1/A3.2/A3.3 approvals. Bucket/principal bindings remain approval gates. No AWS/SSH inspection, upload or resource change ran during preparation. Local fixture tests:67passed in3.00s; live S3/IAM/recovery remain unverified. First requested action is only read-only STS identity and bucket-name inventory; no configuration approval is implied.
