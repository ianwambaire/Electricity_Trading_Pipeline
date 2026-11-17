# Corrected inference-evidence capture deployment package

**LOCAL CORRECTION ONLY — NOT DEPLOYED.** The earlier authorization was blocked before SSH. This task performs no production access, service operation, forecasting, publication, AWS call or Git command. The old manifest `bd70f27d2821fc1a6c0d0728cb9b39dbd6d5f4b8796c823352310b33138174c1` is superseded and must not be used to approve this corrected packet.

Final manifest SHA-256: `32dde4620abb1a9fba4629427a4c43ad40523e5616cf004a0e6cc71b722c7e12`.
Payload SHA-256: `81f2620e5da581fc5e81bdca4683b97491cdf28f97410f6a02e1b3a15beb16a7`.
Runner SHA-256: `9c425a63e552dbc66e851f3bd457112819f75b0f598a158cf70a351b733fa3f8`.
Unchanged supervisor SHA-256: `9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40`.

## Historical production evidence — not refreshed

The single previously authorized inspection returned exit0 at **2026-10-31 10:47:04 UTC / 13:47:04 Nairobi**. Preserve `PREFLIGHT-RESULTS.json` and `BASELINE-COMPARISON.json` as historical evidence; none of their data was remeasured in this local task.

- Production `main`: `b165c8db5a208e8954058fac8cc415d7dfd53446`. Local feature branch revision then: `19784139e406b66e1a0e504275d3ec1ecbf158ed`. Revision was read directly from HEAD/ref metadata, without Git commands.
- Reconstructed pre-capture source hashes exactly matched both installed inference files. Existing cleaners, weather module, ordered feature definition, scheduled pipeline and promoted model metadata matched locally. New helper/receipt root were absent.
- Python3.14.7; pandas2.3.3, NumPy2.4.6, joblib1.5.3, scikit-learn1.8.0. No dependency installation or model change is proposed.
- MemAvailable782.16 MiB, swap used1.0134 GiB, free disk11.3894 GiB. RAM exceeded the768 MiB minimum by only14.16 MiB. Source CSVs totaled54,248,926 bytes; capture adds transient source bytes and parsing memory, so actual new-run peak remains unmeasured.
- Parent directories real, UID/GID1000,0755; existing code0644. The future capture root can be owned by the existing ec2-user identity, with no new user/group.
- One enabled `45 * * * *` UTC schedule, concurrency1 active/slots0, collision policy null, deployment READY/unpaused. No active runs then; the next queued occurrence then was11:45 UTC. This is NOT a claim about the next run at a future deployment time.
- Nginx configuration, production public certificate and three legacy forecast hashes stayed unchanged. The old inspector's `services_unchanged=false` was inconclusive because dynamic MemoryCurrent was included. The corrected installer uses only stable service fields and requires every expected service active/running. It does not retroactively change the old result.

## Exact code/filesystem scope

Only three production code files change under `/home/ec2-user/Electricity_Trading_Pipeline`:

| File | Existing SHA-256 | Reviewed replacement SHA-256 |
| --- | --- | --- |
| `src/models/next24h.py` | `6708af30d05d8f3f22cd7af0ad52de160c905fc40c25e586bcacded58a8fb4fd` | `222c708d3a296cd31187efa7471c0c894076df4dc15a6e4a61168e0dd8c178fe` |
| `src/models/next24h_production.py` | `403b20f8ad0d167848931a08117c4e6aea11455c2b39a10b258eab8799532419` | `65c1514e96cc32360d7af462fc990a6c0d21d41f2dad69c9330c664c9901d65c` |
| `src/models/inference_evidence.py` | must be absent | `30f314fbc9cc2927e739f8f3fb8482c768331e5e0ed0aefaefae28c31769fbbb` |

All three source byte payloads, model identity, feature contracts, freshness thresholds and inference behavior are UNCHANGED by this package-correction task. `deploy-capture.py` embeds exactly those bytes, source/dependency hashes and previous hashes. No datasets, databases, credentials, environment files, model binaries or frontend assets are embedded.

The only proposed mutation paths remain:

1. `/home/ec2-user/powerflow-inference-evidence-backup-20261031-v1/`: new0700 ec2-user:ec2-user code backup directory; original two source files and code/guard-only deployment metadata0600. Backup hashes are read back and permissions checked before any source replacement and again afterward. No database/forecast/environment backup or copying is included.
2. `/home/ec2-user/Electricity_Trading_Pipeline/data/reports/next24h_inference`: new0700 ec2-user:ec2-user private receipt root. **The installer writes no inference receipts.** Future natural inference can write reviewed UUID/partial directories and0600 receipt files here. Synthetic receipt size24,216 logical bytes/run, roughly33.3 MiB for60days of hourly runs before filesystem overhead. Actual size, peak memory and runtime behavior are unverified. No automatic retention cleanup.
3. Narrow temporary `src/models/.evidence-<UUID>.tmp` files and atomic replacements of the exact three code names, ec2-user:ec2-user0644. Helper first, optional-callback helper second, production inference file last. No incoming directory, scp or script installation: reviewed bytes arrive through SSH stdin.

The sole elevation is the existing fixed `sudo -n /usr/bin/sha256sum` command over `/etc/nginx/conf.d/powerflow.conf`, `/etc/nginx/conf.d/powerflow-staging-https.conf` and `/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem`. It reads hashes of configurations/public certificate, never a private key, and performs no privileged writes. All deployment writes run as UID/GID1000, not root. Nothing writes application databases, data CSVs, Nginx, systemd, Cognito, IAM or S3. Normal read-only HTTP/SSH/sudo checks can generate ordinary access/audit logs; “no preflight modifications” means no installer-managed directories/files/source/service changes, not suppression of normal logging.

## Mandatory guards now implemented

| Guard | Pre-write behavior | Post-write behavior |
| --- | --- | --- |
| Local integrity | Runner verifies payload/supervisor, exact manifest artifact/source inventories, every artifact/source hash and test hash before SSH/capture creation. External command below pins the manifest itself. | Installed source hashes are returned and compared to reviewed values. |
| Production compatibility | Exact production revision, Python patch/package versions, unchanged supporting-module hashes, parent/source ownership/group/modes and destination absence. Compile payload in memory; no imports/inference from replacement code. | Re-read all installed source hashes. |
| Independent process check | Scan `/proc/self/mountinfo` to establish unrestricted proc visibility, then bounded visible-PID command lines across UIDs for fixed ingestion/pipeline-engine markers. Fail on hidepid, inaccessible argv, oversized/incomplete scans or any match. No argv/environment is printed or persisted; only PID/UID/category/counts. This is independent of Prefect state. Repeat in every idle guard before a replacement. | Repeat the same independent check; report absent ingestion. |
| Prefect/non-overlap | Exact deployment/schedule identity; one enabled hourly:45 UTC schedule; concurrency1 active/slots0; original null collision policy. No RUNNING/PENDING/CANCELLING/PAUSED run. No queued run within10minutes or duplicate queued times; at least10minutes before:45. Recheck immediately before first write and each replacement. | Recheck exact schedule/concurrency/collision and compare with preflight configuration. Return next actual queued run and next cron occurrence. |
| Resources | Read MemTotal/MemAvailable/SwapTotal/SwapFree and disk total/used/available. Reject malformed counters. Enforce768 MiB MemAvailable and2 GiB disk minimum as the last capacity gate before first filesystem mutation. Swap usage is measured; no unapproved maximum-swap threshold is invented. | Return the same RAM/swap/disk counters and enforce the same capacity guards. Low post-capacity means verification failure with installed state retained, not automatic rollback. |
| Private storage/backups | Original two source hashes and readback-verified backups; backup directory0700/files0600. Verify receipt UID1000/GID1000/mode0700/non-symlink immediately after creation. | Re-read receipt ownership/group/mode/type and both backup ownership/group/modes/hashes. |
| Availability | Require HTTP200/expected payload for production API `127.0.0.1:8000/health`, candidate `:8010/health` and `/ready`, Streamlit `:8501/_stcore/health`; trusted staging HTTPS root with React root/hashed JS entry and nonempty entry asset; staging HTTPS `/api/health`. | Repeat all availability checks. Fail on HTTP/payload/TLS errors without restart or repair. |
| Stable preservation | Require all five existing production services PLUS `powerflow-candidate-api.service` active/running with nonzero PIDs. Record stable identity/state properties only; no memory counters. Record live routing/public-certificate/legacy-forecast hashes. | Require stable identities, routing/public-certificate and forecast hashes unchanged. Healthy endpoint results are included. |

HTTPS checks connect to127.0.0.1:443 with hostname/SNI `staging.powerflowenergy.dev`, default trusted CA verification and matching Host header. No DNS change, external provider call, authentication interaction, TLS bypass, redirect following or certificate issuance. GET probes only; Prefect POSTs are bounded read-only filter queries, never state mutations.

Storage mapping/sync files have explicit local expected hashes in the installer; those two remote hashes were NOT obtained by the earlier inspection. They must match before any write; stop on mismatch. Local code maps explicit files rather than recursively publishing private receipts. No new S3 mapping is added.

## Failure, atomicity and rollback boundaries

All preflight checks finish before the first backup mkdir. Failed preflight returns `NOT_STARTED`, with no installer-managed remote modifications. Individual source replacements use exclusive no-follow temporary writes, hash readback, fsync and atomic replace. The three-file set is NOT one atomic filesystem transaction: idle-window guards and compatible installation order reduce the race. Coordinate no manual pipeline triggers during the bounded window; no schedule is paused or modified.

Failures stop immediately. Never retry, auto-rollback, delete, repair or weaken a gate. Reports include stage, installed filenames, created directories, potential retained temporary paths and one of:

- `NOT_STARTED`: no installer mutation occurred.
- `PREPARATION_ARTIFACTS_ONLY`: backup/receipt preparation may be partial; source installation has not completed a replacement.
- `PARTIAL_SOURCE_INSTALL`: some source replacements completed.
- `SOURCE_INSTALLED_VERIFICATION_FAILED`: all three replacements completed but post-verification failed.
- Corresponding explicit rollback states for a separately approved rollback.

If SSH fails/times out or no valid JSON returns, remote installation state is `UNKNOWN`, never assumed unchanged. Private stdout/stderr are preserved. No follow-up inspection is automatic. Source/backup/receipt artifacts remain for separately authorized diagnosis.

Rollback is **separately authorized**, not part of apply. It uses the same fixed packet with action `rollback`, checks current installed hashes and original backups, and applies all idle/process/capacity/availability/preservation checks. Restore old production inference file FIRST, then old shared prediction helper. Retain the unused new helper, backup/receipt directories and completed/partial receipts; delete nothing and restore no old database/forecast. Running processes that already imported code are not changed by source rollback; do not cancel/restart them under this procedure.

## Exact future command — do not execute without new approval

From the local repository root, first verify the NEW manifest and all packet artifacts:

```sh
venv/bin/python -B - apply <<'PY'
import hashlib, json, runpy
from pathlib import Path
p = Path('deploy/staging/inference-evidence-deployment')
raw = (p/'MANIFEST.json').read_bytes()
assert hashlib.sha256(raw).hexdigest() == '32dde4620abb1a9fba4629427a4c43ad40523e5616cf004a0e6cc71b722c7e12'
m = json.loads(raw)
for name, digest in m['files'].items():
    assert hashlib.sha256((p/name).read_bytes()).hexdigest() == digest
for name, entry in m['sources'].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == entry['new_sha256']
assert hashlib.sha256(Path('deploy/remediation/a3-bounded-local.py').read_bytes()).hexdigest() == m['supervisor_sha256']
runpy.run_path(str(p/'run-deployment.py'), run_name='__main__')
PY
```

The approved entry point after that hash verification is:

```sh
venv/bin/python -B deploy/staging/inference-evidence-deployment/run-deployment.py apply
```

Exactly one strict-host-key SSH stdin execution is used, with10-second connection timeout/one attempt, existing ec2-user and existing key. Remote bound remains90seconds, TERM then5second escalation. Local supervisor remains180seconds plus5second escalation, outer190seconds. Individual API/HTTP/process/subprocess reads are bounded. No automatic retries. Corrected runner hash: `9c425a63e552dbc66e851f3bd457112819f75b0f598a158cf70a351b733fa3f8`; corrected remote payload hash: `81f2620e5da581fc5e81bdca4683b97491cdf28f97410f6a02e1b3a15beb16a7`.

Remote command, unchanged in identity/paths/timeouts:

```text
ssh -i /Users/iannganga/.ssh/powerflow-key.pem -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts -o ConnectTimeout=10 -o ConnectionAttempts=1 -o ServerAliveInterval=10 -o ServerAliveCountMax=2 -o LogLevel=ERROR ec2-user@3.228.243.164 '/usr/bin/timeout --signal=TERM --kill-after=5s 90s /home/ec2-user/Electricity_Trading_Pipeline/.venv-prod/bin/python -I -B - apply'
```

## Acceptance and remaining blockers

After a successful apply, observe the next NORMAL scheduled flow—do not trigger it. Verify actual task/run success, module loading into the flow engine, one complete private receipt, ordered31 real feature values, reciprocal hashes, unchanged model identity,24 aligned finite predictions, source completeness and actual current3-hour freshness. Observe peak memory/swap impact. UUID identifies inference, not Prefect run; correlate using actual timing and output. Code caching/no receipt requires diagnosis, not an implicit worker restart.

Local correction regression result: **254 targeted Python (80 package safety) tests**, including independent root/other-UID process detection, exited/inaccessible/hidden processes, RAM/disk boundaries and invalid swap counters, source drift, no-write failed preflight, directory/backup permissions and hashes, failed availability/TLS checks, schedule/concurrency/collision drift, service preservation, real isolated local partial installs, retained artifacts, post-resource reporting and unknown remote state after transport failure. No test accesses production. No inference code or frontend source changed in this correction.

Current blockers are fresh deployment-time guard results and a new explicit approval for this manifest. Proc visibility, sudo hash access, live staging TLS/availability, unverified remote storage-module hashes and narrow memory headroom can fail closed. None is claimed reverified here. No deployment, service restart, forecasting, staging publication or AWS change is authorized by this local preparation.
