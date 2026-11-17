# Phase 5D.2 — A2 isolated restoration execution review

26 October 2026, Africa/Nairobi. **Historical execution review: subsequently approved and executed ONCE on 26 October 2026; A2 passed. No further execution is authorized.** A0/A1 remain accepted; their approvals do not authorize this payload. This review replaces the earlier generic A2 suggestion with a precise **same-host, disposable-directory restore test**, without off-host transfer or new resources.

## 1. Exact code and hashes

The complete proposed remote script is `deploy/remediation/restore-operational-sqlite.py`. Review that file in full. It is self-contained standard-library Python; it does **not** import `src/operational_recovery.py`, application configuration, dotenv, models, Prefect, AWS SDKs or any other project module. The expected core schema and counts are embedded in its reviewed bytes, not loaded from mutable production code.

| File | SHA-256 | Role |
|---|---|---|
|`deploy/remediation/restore-operational-sqlite.py`|`e0144438075b5219a2b03a7dad982bab14bde81d92d6c79cf11253c91284262c`|**Sole custom code executed on EC2**, through SSH stdin|
|`database/schema.sql`|`c8b042f9978ef5b07b5fbfcc99cb02e195f52190b3dfc87123fab34efa81bf8d`|Local provenance for embedded core contract; not read/executed on EC2|
|`tests/test_a2_restoration.py`|`2c6c077c7a4e231004adf5bc38bf25361c34c021763e8b24b448b97af8aed879`|Local fixture/regression tests only; not sent to EC2|

Existing OS SSH/GNU timeout and Python/SQLite standard-library binaries are prerequisites, not new project code. Their installed binary hashes/versions were not collected because additional SSH inspection is not authorized. The Python executable is the existing one used by A1. `/usr/bin/timeout` availability is not newly verified; if missing/unsupported, the proposed command fails without installing anything or falling back to an unbounded invocation. No A1 helper change is needed.

If payload bytes change, stop and obtain approval for the new hash. Approval must identify this payload, target, source and destination. Do not copy/install the script remotely.

## 2. Exact proposed SSH command

First locally verify the payload digest against the value above. This does not execute the script:

```sh
shasum -a 256 deploy/remediation/restore-operational-sqlite.py
```

**After separate explicit approval only**, send the unchanged reviewed bytes once:

```sh
ssh -F /dev/null -i /Users/iannganga/.ssh/powerflow-key.pem \
  -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none \
  -o StrictHostKeyChecking=yes -o UpdateHostKeys=no \
  -o UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts \
  -o ForwardAgent=no -o RequestTTY=no -o ConnectTimeout=10 \
  -o ServerAliveInterval=10 -o ServerAliveCountMax=3 \
  -T ec2-user@3.228.243.164 \
  '/usr/bin/timeout --signal=TERM --kill-after=5s 120s /home/ec2-user/Electricity_Trading_Pipeline/.venv-prod/bin/python -I -S -B -' \
  < deploy/remediation/restore-operational-sqlite.py
```

Target is the previously verified PowerFlow EC2 `i-059e63a35a022cd0f`, us-east-1f, using the existing ec2-user/key and strict pre-existing host-key trust. No key contents are displayed/read/copied by the agent. No alternate host/user, sudo, automatic retry, added diagnostics or host-key bypass. Missing interpreter/timeout or a changed key is a stop condition, not permission to install/repair anything. SSH keepalives are transport supervision, not extra host inspection.

Python accepts **no command-line path/hash/count overrides** and ignores Python environment path/user-site initialization (`-I -S -B`). The only remote command is the bounded interpreter invocation above. No source-code deployment or service definition is installed.

## 3. Fixed input and output

**Accepted immutable input identity:**

- Backup ID: `20261026T022230.137446Z`.
- Directory: `/home/ec2-user/powerflow-recovery-phase5d2-operational/20261026T022230.137446Z/`.
- Database: that directory's `electricity_trading.db`.
- Manifest: that directory's `manifest.json`.
- Required database SHA-256: `21fcb0e920ffaf13f214e39720e1176e012086d6ffa7b8a7ed736b6e4ab79690`.

**New disposable destination, exactly:**

`/home/ec2-user/powerflow-a2-restore-20261026T022230.137446Z/`

Only new output files:

1. `restored-electricity_trading.db` — a byte-identical copy of the validated, standalone A1 image.
2. `verification.json` — aggregate checks, exact sizes, hashes, timings and status; no raw rows/schema SQL/foreign-key row identifiers.

The destination is outside the production application, original backup tree, published API data and all live databases. It is still on the **same host, same OS identity and existing unencrypted root volume**, not a sandbox VM or independent disaster-recovery site. It is disposable by intended use, **not authorized for deletion**.

Refuse an existing directory/file/symlink at the destination. Input paths must be canonical, regular, owner-private files; backup directory and destination parent ownership/modes must meet the script's checks. Refuse source/destination ancestry overlap or overlap with the production application tree. No parent creation, live-file chmod or privilege workaround.

PostgreSQL, both live/candidate Prefect stores, MLflow, models, data pipelines, reports and configuration are outside this restore test. The operational production DB is **never opened** by A2. Any additional legacy tables already inside this accepted A1 database are copied intact, not filtered out or queried for row contents.

## 4. Ordered execution and verification checklist

### Before creating the destination

- Establish90-second in-process deadline and restrictive umask077. Confirm paths, no destination, parent ownership/no group-or-other write, and owner-private backup directory/files; no symlink traversal.
- Refuse any `-wal`, `-shm` or `-journal` file at the **A1 backup DB** path, even if empty. The accepted artifact must be a standalone frozen image. Do not checkpoint/delete sidecars or read the live operational DB as an alternative.
- Open input files read-only/no-follow; cap database at128MiB and manifest at1MiB.
- Validate manifest backup filename, expected SHA and integer file size. Stream-hash the actual original DB and require the accepted digest **before restoration or destination creation**.
- Open only the frozen backup using SQLite `mode=ro&immutable=1`, query_only and trusted_schema protections. [SQLite documents immutable reads as bypassing locking/change detection](https://www.sqlite.org/uri.html); this is appropriate only for this frozen artifact, never a live writer DB. SQLite extensions are never enabled; where the binding exposes its toggle, explicitly disable it. Temporary query storage is memory-only; cache hint4MiB per connection.
- Require the four reviewed core table column/type/nullability/default/primary-key contracts and six core indexes, including key order/direction. Compare all manifest-recorded table/index/view objects against the accepted backup's schema. Capture all non-internal table/index/view/trigger objects for restored parity; do not execute their SQL.
- Run the destination-filesystem free-space guard below. Any failure so far stops without deliberately creating an A2 output directory; OS access times can change from reads.

The core contract is derived from the current reviewed repository schema, not freshly inspected production contents. A legitimate older deployed schema can therefore cause a safe refusal. No migration, automatic compatibility relaxation or new input selection is authorized. Additional non-core legacy tables/views/triggers are allowed and preserved, with exact source-to-restored parity.

### Restore and validate the new copy

- Create the one new directory0700 and DB using exclusive/no-follow creation0600. Stream-copy the validated standalone image; refuse a changed source size, flush/fsync the new file. No SQLite restore into a live database, no `--force`, no overwrite, no VACUUM or checkpoint.
- Record copy+file-fsync duration with a monotonic clock. Measure exact restored bytes and require its SHA-256 to equal the accepted original digest.
- Open the restored DB through `mode=ro&immutable=1`, with query_only. Run **full `PRAGMA integrity_check`**, requiring exactly`ok`.
- Run **`PRAGMA foreign_key_check`** separately: [SQLite integrity_check does not cover foreign-key errors](https://www.sqlite.org/pragma.html#pragma_integrity_check). Report violation count, completed/error/not_run status and declared foreign-key constraint count. Do not expose offending table names/row IDs or repair anything. A zero result with zero declared constraints is explicitly not evidence of relationships that were never constrained.
- Require restored core schema and all non-internal table/index/view/trigger definitions to match the original snapshot; require manifest-backed object parity. SQLite internal state is preserved by byte-identical copy, not independently certified beyond integrity/hash checks.
- Query required table counts through that read-only connection and compare exactly:

| Table | Expected A1 count |
|---|---:|
|pipeline_runs|891|
|data_quality_results|16,525|
|operational_incidents|1,485|
|pipeline_stage_timings|11,561|

- Report successful read-only queries, schema/object counts, exact size/hash and durations. No raw data rows, messages, exception text or SQL definitions are emitted.
- Recheck original DB digest, original manifest digest and input file identity/size/modification/change timestamps; exclude access time because reads can update it. Recheck absence of sidecars and output private permissions. No deliberate write to original backup/manifest occurs.
- A pass requires integrityok, foreign-key violations0, exact counts, schema parity, digest agreement and unchanged inputs. Write a new0600`verification.json` with exclusive creation; fsync it. Return sanitized JSON on stdout; exit0 only on pass. Existing result files are never replaced.

## 5. Disk and permission budget

Let `S` be actual validated A1 backup bytes, measured during this approved-later payload. **A1 did not return numeric backup size**, so do not substitute A0's source size as actual backup size.

Guard: `0 < S <= 134,217,728bytes`; reserve workspace `3*S + 67,108,864bytes` and require:

`destination_available_bytes - workspace >= floor(destination_filesystem_total_bytes / 4)`.

The restored image should be **exactlySbytes**; no compaction/rewrite occurs. The extra allowance covers metadata and safety margin, not an expected extra triple copy. Manifest is read but not copied, and result JSON is small. SQLite temporary query work stays in memory. At the128MiB source ceiling, workspace allowance is448MiB.

For illustration only, using A0's historical13,213,696-byte live source and same filesystem totals gives101.8047MiBworkspace and5,455,531,008bytes minimum free, versus A0's12,805,435,392available. Actual A2 evaluates the real backup and destination filesystem at runtime. It does not provide continuous disk monitoring or guarantee capacity against concurrent growth.

Output directory0700 and DB/result0600. Refuse unsafe input modes/owners rather than chmod them. Do not modify existing directories. Root/the same account can still access these files; permissions do not encrypt them. No off-host transfer, S3, EBS, KMS or new paid allocation. Existing hosting/storage charges continue unchanged.

## 6. Bounded execution, failure and rollback

- **Internal:**90-second elapsed deadline, signal alarm, explicit copy/hash checks and SQLite progress interruption. SIGTERM/keyboard interruption yields a fixed interrupted status when handling is possible.
- **External:**GNU timeout sendsTERM at120seconds andKILL after5more seconds if necessary, limited to this invocation's process group. This protects even startup/final-report phases outside an inner query deadline. Never signal a production service. Kernel-level uninterruptible I/O can delay signal delivery; do not claim a hard real-time guarantee during a host/kernel failure.
- Monitor this single SSH attempt; do not leave an unexpectedly silent/stalled operation unattended. No retry, fallback without timeout, new diagnostics or service intervention. Capture remote exit status;124/137/SSH failure or missing structured success is **not a pass**. See [GNU timeout status/signal semantics](https://www.gnu.org/software/coreutils/manual/html_node/timeout-invocation.html).
- Input/precondition failure leaves originals untouched. If new output creation has begun, preserve every created artifact. Report partial bytes where measurable, failed stage, null/not_run/error distinctions and aggregate violations/count mismatch. No raw SQLite errors or data contents. An unchanged-input flag leftfalse on an incomplete attempt means its final attestation did not complete, not proof the input was modified.
- If possible, write the failure result to the newly created result file. Hard termination can leave a partial DB, incomplete JSON, empty directory or no result; report unknown state, do not infer success from file presence. A result-write failure makes stdout/status a failure even if an incomplete on-disk record contains earlier fields.
- **No artifact deletion anywhere in the payload.** No unlink/rm/recursive cleanup, retention job, overwrite or rename-over-existing. A later retry cannot reuse the destination. Cleanup must separately name this exact directory and artifacts after result review; no cleanup is approved now.
- No production rollback is necessary because no production state is changed. Never restore the test copy over production, delete originals, repair schema/FKs or restart services in response to failure. The original A1 backup remains the authoritative input. Additional testing with revised code/path needs a new review/hash/approval.

## 7. Expected production effect and acceptance limits

No production DB connection, application import, HTTP request, pipeline run, model operation or service start/stop/restart/reload. No Cognito, Nginx, DNS, TLS, IAM, AWS resource or Git change. I/O is limited to reading the frozen accepted backup/manifest and writing/verifying its new local copy. Normal SSH audit records and finite host CPU/read/write activity occur; no guarantee of zero transient contention. Do not add a production health/log/permission inspection to this approval.

Success establishes that this exact accepted **operational SQLite snapshot** can be restored and queried with the listed checks on the existing host. It does not establish full application recovery, independent/off-host durability, PostgreSQL/Prefect/MLflow recovery, future backup freshness, staging capacity or production cutover readiness. The result explicitly keeps off-host/full-application recovery flagsfalse. Copy duration is not disaster-recoveryRTO; total includes local preflight/checks but not obtaining a replacement host/secrets/runtime.

## 8. Local preparation validation

Only disposable local fixtures were used. No original A1 backup/manifest was read; no SSH or AWS operation ran. Fixture DBs exercise the exact accepted count totals but have their **own synthetic digests**, never the production digest. No fixture result is a live A2 result.

- Focused recovery tests:55passed,2.88s. Includes24A2 cases: success/read-only enforcement, same bytes/counts/schema, existing file/directory/symlink refusal, wrong digest/manifest, sidecars, strict schema/index, low space, FK violation versus checker error, partial writes, timeouts/interruption with preserved artifacts, permissions/size guards, allowed legacy objects/triggers and isolated CLI override refusal.
- Full backend regression suite: **683 passed, 32.86s** on the final run.
- `git diff --check`: passed.
- Local initial failures caught a missing optional SQLite extension-toggle binding and one incorrect expected index direction; both corrected, with final fixture checks enforcing the real repository schema. No production compatibility claim follows.
- Frontend application code/dependencies untouched; frontend tests/lint/build not rerun for this backend-preparation-only change. Nginx/systemd/remote GNU timeout/production SQLite execution remain untested here; no package was installed.

Commands from repository root:

```sh
venv/bin/python -m pytest -q tests/test_a2_restoration.py tests/test_recovery_preparation.py tests/test_recovery_tooling.py
venv/bin/python -m pytest -q
```

Do **not** run the payload itself against its fixed paths as a local test. It has no environment/CLI test mode; tests import its restore function with disposable paths. Only the no-arguments override-rejection path is exercised in an isolated interpreter subprocess.

Changed files this preparation: the new remote proposal and new test file above, this review, the Phase5D.2 report link/status update and the remediation README. The A0/A1 payloads and original recovery helper remain unchanged. No local synthetic output is a production restore artifact.

## 9. Execution completed — stop here

The user approved the exact payload/hash and bounded SSH command above. It executed once at 03:03:59.557160 UTC on 26 October 2026 and passed (exit 0). SSH wall time: 4.842914 seconds; payload: 0.308794 seconds; restoration: 0.026977 seconds. Restored database: 12,115,968 bytes, approved SHA-256 unchanged. Integrity `ok`, zero foreign-key violations (zero declared constraints), schema/index parity, all four A1 counts and read-only queries passed. Original backup and manifest were confirmed unchanged; verification record written. See the [Phase 5D.2 actual result](phase5d2-recovery-and-infrastructure-remediation.md#a2--same-host-isolated-restoration-passed-once) for full evidence and limitations.

No retry, additional SSH inspection, cleanup or broader step followed. Artifacts remain on the unencrypted source host. Off-host backup, further production inspection, infrastructure remediation or staging deployment require separate approval. This historical command is not permission to execute again.
