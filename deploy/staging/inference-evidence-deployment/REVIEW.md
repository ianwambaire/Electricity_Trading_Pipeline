# Capture-only production deployment review — 2026-10-31

**PREPARED, NOT DEPLOYED.** Exactly one authorized read-only SSH inspection completed (exit 0); no retry, remote files written, deployment, Git commands, inference, service action or AWS call. Private capture: `/private/tmp/powerflow-inference-preflight-9wzge_vz`. Full allowlisted facts are in `PREFLIGHT-RESULTS.json`.

## Verified findings

Observed at **2026-10-31 10:47:04 UTC / 13:47:04 Nairobi**:

- Production `main` revision: `b165c8db5a208e8954058fac8cc415d7dfd53446`; local `feature/react-frontend` revision: `19784139e406b66e1a0e504275d3ec1ecbf158ed`. These are read from HEAD/ref files, not Git commands. A revision alone is not proof of working-file contents.
- The exact pre-capture versions reconstructed locally match both installed inference file hashes. See `BASELINE-COMPARISON.json`. The new helper is absent. Thus the proposed replacements differ only by the reviewed capture changes, not unrelated source drift.
- Existing cleaners, operational weather code, ordered feature definition, scheduled pipeline and promoted model manifest match local SHA-256 exactly. No model, dependency installation, feature logic or scheduling update is needed.
- Production Python **3.14.7**, pandas **2.3.3**, NumPy **2.4.6**, joblib **1.5.3**, scikit-learn **1.8.0**. Capture adds only stdlib use and existing pandas. No pip or production virtualenv writes are proposed.
- MemAvailable **782.16 MiB**; swap used **1.0134 GiB**; free disk **11.3894 GiB**. Current 768 MiB / 2 GiB guards pass, but RAM margin is only **14.16 MiB**. These are point-in-time measurements, not a peak-memory guarantee.
- Source CSV sizes total **54,248,926 bytes** (51.74 MiB). The new snapshot bytes plus additional parsing allocate transient memory beyond prior inference. Actual new-run peak remains unmeasured. Do not weaken memory checks; abort if the deployment-time capacity guard fails. Natural-run verification must check resource impact.
- `data`, `data/reports`, `src/models`: real directories, UID/GID1000, mode0755. Existing code files UID/GID1000,0644. The new receipt directory is absent. The existing worker runs as ec2-user (1000), so it can own/create a private0700 child without elevating the write operation.
- All five inspected production services were active/running. Production/staging Nginx and production public-certificate hashes, and all three legacy forecast file hashes, remained unchanged.
- **Inspection limitation:** `services_unchanged=false` is an inconclusive comparison because the original inspector included dynamic `MemoryCurrent`. It did not retain the second service snapshot. This does NOT establish a restart, nor does it prove unchanged identities. The proposed installer compares only stable service identity/state fields before/after; no second remote inspection was executed.
- One enabled `45 * * * *`, UTC schedule; concurrency1 active, slots0; original collision configuration remains null. Deployment READY, unpaused, no active/PENDING/CANCELLING/PAUSED runs. Queued occurrences11:45/12:45/13:45 UTC, one each. Next observed queued ID `01a19122-c2c3-74dc-b8f1-c50878686a66`, **11:45 UTC / 14:45 Nairobi**. This snapshot must be revalidated at deployment; never treat it as permanent idle permission.

## Minimal files and integrity

Only these production code files change:

| Path under production repository | Existing SHA-256 | Proposed SHA-256 |
| --- | --- | --- |
| `src/models/next24h.py` | `6708af30d05d8f3f22cd7af0ad52de160c905fc40c25e586bcacded58a8fb4fd` | `222c708d3a296cd31187efa7471c0c894076df4dc15a6e4a61168e0dd8c178fe` |
| `src/models/next24h_production.py` | `403b20f8ad0d167848931a08117c4e6aea11455c2b39a10b258eab8799532419` | `65c1514e96cc32360d7af462fc990a6c0d21d41f2dad69c9330c664c9901d65c` |
| `src/models/inference_evidence.py` | must be absent | `30f314fbc9cc2927e739f8f3fb8482c768331e5e0ed0aefaefae28c31769fbbb` |

`deploy-capture.py` embeds exactly those three source byte payloads and their hashes; it contains no forecast, credentials, database, model binary or environment file. `MANIFEST.json` binds scripts/results and the tests. The separate API/shared/React publication changes are NOT in this production packet.

Two additional read-only application guards (`src/storage/mappings.py`, `src/storage/sync.py`) use explicit local expected hashes in the installer. Their hashes were NOT retrieved in this inspection; they must match before any write in a future apply. Local storage code uses explicit mapped artifact paths, not recursive receipt upload. No new S3 mapping is added; abort on mismatch rather than relaxing or assuming equivalence.

## Exact proposed filesystem effects

Repository: `/home/ec2-user/Electricity_Trading_Pipeline`.

1. Create **only** `/home/ec2-user/powerflow-inference-evidence-backup-20261031-v1/`, ec2-user:ec2-user0700, with exact existing `next24h.py`, `next24h_production.py` and code/guard-only `deployment.json`, files0600. No database, forecast or environment backup is made because none is changed. Backups are hash-readback verified and fsynced before code changes.
2. Create `/home/ec2-user/Electricity_Trading_Pipeline/data/reports/next24h_inference`, ec2-user:ec2-user0700. **The deployment writes no receipts.** Future normal inference creates private UUID/partial directories and0600 receipt files here using the reviewed capture code. Synthetic receipt measurement:24,216 logical bytes/run, approximately33.3 MiB for1,440 hourly runs/60days before filesystem overhead. Actual numeric formatting/count and disk allocation differ; no cleanup is automatic.
3. Write narrow temporary `.evidence-<UUID>.tmp` files only under `src/models`, fsync, then replace/install only the three approved code names as ec2-user:ec2-user0644. Install helper first, optional-callback helper second, operational activation file last. No separate uploaded incoming directory is required; bytes arrive through SSH stdin. This is not an atomic multi-file transaction: guards enforce an idle window and compatibility order; failures retain partial state and require review.
4. No .pyc creation (`-B`), package install, service start/stop/restart/reload, Git operation, symlink switch, Nginx edit, AWS operation, staging/frontend publication, model/data/database writes or manual forecasting.

The sole elevation in the proposed apply is `sudo -n /usr/bin/sha256sum` of the exact two Nginx configurations and production **public fullchain certificate** listed in the script, for preservation checks. It never reads a private key. Code/backup/receipt directory writes run as UID1000, not root. Normal SSH/sudo audit records can be created. Separate deployment approval must include this fixed read-only elevation.

## Guards, sequence and stop behavior

1. Hash-verify all local packet files, embedded source bytes and unchanged supervisor.
2. One strict known-host SSH call;10-second connect timeout, one attempt. Remote90-second TERM bound plus5-second escalation; local180-second supervisor plus5-second escalation. No retry.
3. Revalidate production revision, Python/package versions, installed/support hashes, safe parent/file ownership and modes, and absence of helper/backup/receipt destinations. Compile source bytes in memory, never infer.
4. Recheck exact schedule/concurrency/collision settings, no active runs, no queued run within10minutes and at least10minutes before :45. Recheck idle conditions before each code replacement. No schedule is paused or changed. A simultaneous external manual trigger cannot be excluded by an advisory inspection; coordinate no manual triggers during the bounded window. Abort if a run appears.
5. Require at least768 MiB MemAvailable and2 GiB disk available. Record fresh stable service/configuration/certificate/legacy-forecast baselines at execution time; do not pin the October31 forecast hashes indefinitely because normal scheduling legitimately updates them.
6. Create/verify code backups, create private receipt root, install only the three files in compatible order, verify installed hashes, then check stable service identities, routing/certificates and unchanged legacy forecast bytes.
7. On any failure, stop. **No automatic rollback/repair/retry/deletion.** Report completed stages and installed filenames. If connection/timeout interrupts reporting, preserve partial artifacts and require separately authorized inspection. Never infer that failure means no changes.

## Exact future execution command — NOT EXECUTED

From the local repository root, after explicit approval of the final manifest/hash:

```sh
venv/bin/python -B - apply <<'PY'
import hashlib, json, runpy
from pathlib import Path
p = Path('deploy/staging/inference-evidence-deployment')
expected = 'bd70f27d2821fc1a6c0d0728cb9b39dbd6d5f4b8796c823352310b33138174c1'
raw = (p/'MANIFEST.json').read_bytes()
assert hashlib.sha256(raw).hexdigest() == expected
m = json.loads(raw)
for name, digest in m['files'].items():
    assert hashlib.sha256((p/name).read_bytes()).hexdigest() == digest
for name, entry in m['sources'].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == entry['new_sha256']
assert hashlib.sha256(Path('deploy/remediation/a3-bounded-local.py').read_bytes()).hexdigest() == m['supervisor_sha256']
runpy.run_path(str(p/'run-deployment.py'), run_name='__main__')
PY
```

The reviewed runner invokes exactly one SSH stdin command:

```text
ssh -i /Users/iannganga/.ssh/powerflow-key.pem -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts -o ConnectTimeout=10 -o ConnectionAttempts=1 -o ServerAliveInterval=10 -o ServerAliveCountMax=2 -o LogLevel=ERROR ec2-user@3.228.243.164 '/usr/bin/timeout --signal=TERM --kill-after=5s 90s /home/ec2-user/Electricity_Trading_Pipeline/.venv-prod/bin/python -I -B - apply'
```

It sends `deploy-capture.py` only through stdin under the unchanged local supervisor, with private stdout/stderr captures. No scp or script installation.

## Rollback and post-deployment acceptance

Rollback requires **separate explicit approval**. Use the exact same hash-verifying local command with `rollback` instead of `apply`. It rechecks revision/dependencies, schedule/idle/capacity, exact newly installed hashes and private backup hashes. Restore operational production file FIRST, then the shared prediction helper via guarded atomic file replacement. Retain the unused new evidence helper, receipt directory, completed/partial receipts, backup and metadata; **delete nothing** and restore no old forecast/history/database. No service action is included. If installed hashes drift, idle window is unavailable or backup validation fails, stop instead of forcing restoration. A live engine that already imported code is not changed by a source rollback; inspect/wait for its normal completion, never cancel it under this procedure.

After apply, wait for the next **normal scheduled** flow—do not trigger it. Existing worker is not restarted; loading the new source in that flow's engine remains an actual-runtime acceptance requirement. Verify completed task/run state, one complete private receipt, exact31-value ordered matrix, reciprocal hashes, original model identity,24 aligned finite predictions, source completeness and current3-hour publication freshness. UUID identifies inference, not a Prefect run; correlate against actual run/task timing and outputs. Check peak memory/swap impact and existing application health. If code is cached and no new receipt appears, stop for diagnosis; no implicit restart is authorized. The initial deployment cannot claim live evidence acceptance until this natural-run check passes.

All174 capture/API Python tests and92 frontend tests/builds passed at the preceding checkpoint. This package adds7 local/mocked safety tests; no local test invokes SSH or production writes. Staging activation/publication, cleanup, retention policy changes and any service reload require different approvals.

**Next approval requested:** one `apply` of the exact final manifest-bound capture-only packet, including its two new private paths, narrow code temporary paths, source replacements, code backups, read-only guards and fixed baseline-hash sudo command. Rollback is not included automatically.
