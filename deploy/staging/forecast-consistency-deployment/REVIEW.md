# Guarded reactivation after successful rollback — local preparation only

Fresh manual commit and exact hash-bound authorization required. No remote action
has occurred for this revision. Original immutable release and manifests unchanged.

## Why reactivation, not apply or cleanup

Previous apply created these root-owned runtime directories and legacy control:
/opt/powerflow/releases/phase-forecast-consistency-20261101-v1/
/var/www/powerflow-staging/releases/phase-forecast-consistency-20261101-v1/
/var/lib/powerflow-staging/forecast-consistency-20261101-v1/
Rollback restored original active pointers/env/service and retained them. Original
apply correctly rejects these existing destinations. It remains strict; this runner
now exposes ONLY explicit reactivate and transaction-bound rollback, not apply.

Runtime API/static files can be reused ONLY after exact manifest/hash/owner/mode/
shape verification. They are immutable inputs to this operation: no reinstall,
chmod, deletion, refresh, asset merge or dependency install. The legacy control
contains mutable historical state/backup evidence, not runtime files; this new
operation reads it but NEVER writes/replaces any of its files. New-destination
installation would duplicate byte-identical files and still require fresh control
records; guarded reuse is smaller with exact rejection of drift.

## Inputs and executable closure

Preserved ID phase-forecast-consistency-20261101-v1, release-manifest SHA256:
9dc8ce31f1b294c43239824ffa544a76f4fdf6ba334ea8fd72b9431365ed5c19.
All71 original file hashes are verified locally; only26 API and37 static entries
are embedded. No8 proposal files, datasets, models or private diagnostics are installed.
Runner/job, retained preflight/SSH helpers, pure rollback target validator, smoke
tool, review and tests are bound by the NEW manifest. Code/data remain retained
verified bytes; no executable path reopen. Candidate Python/packages are never
executed by a root probe: startup occurs only through the existing candidate unit.

The new manifest binds one fresh32hex transaction_id. It is part of BOTH assembled
payload hashes and cannot be overridden in CLI/env/remote parameters. Each later
attempt needs a new transaction binding; existing transaction paths are a hard
collision. No latest/current transaction discovery or automatic reuse exists.

## Proposed commands — not authorized execution

Local-only integrity checks (zero connections):

```sh
venv/bin/python -I -B deploy/staging/forecast-consistency-deployment/run.py reactivate \
  --manifest-sha256 APPROVED_NEW_MANIFEST_SHA256 --local-check
venv/bin/python -I -B deploy/staging/forecast-consistency-deployment/run.py rollback \
  --manifest-sha256 APPROVED_NEW_MANIFEST_SHA256 --local-check
```

ONE separately approved activation:

```sh
venv/bin/python -I -B deploy/staging/forecast-consistency-deployment/run.py reactivate \
  --manifest-sha256 APPROVED_NEW_MANIFEST_SHA256
```

ONE separately/conditionally approved rollback, ONLY using that transaction:

```sh
venv/bin/python -I -B deploy/staging/forecast-consistency-deployment/run.py rollback \
  --manifest-sha256 APPROVED_NEW_MANIFEST_SHA256
```

Strict pinned host key/private profile/identity, -F/dev/null, BatchMode,
ConnectionAttempts1, ConnectTimeout10. Noninteractive sudo invokes fixed timeout
and system Python -I -S -B through SSH stdin. Reactivate remote300/local360 seconds;
rollback180/240 seconds. TERM/KILL5s escalation, each stream capped131072 bytes.
No retries, automatic rollback, cleanup, repair or secret-bearing output.

## Read-only reuse gates before any new record or candidate mutation

- Manifest, per-file source hashes, pointer target digests, env baseline ee1ea96ebd2aa9b1c15891fd4cb9adf1c6ee7d06d6177b99bb1f375419b36704.
- Legacy control root0700; state/env backup root:root0600; phase ROLLED_BACK,
  matching release targets, original active service state, original env digest,
  current restored original pointers and exact old static inventory/retained assets.
  Never accept a COMPLETE/PARTIAL or unrelated legacy record as successful recovery.
- Current old backend hashes, root-owned existing venv, dependency metadata, actual
  UID/GID992/one-worker loopback8010, sandbox,384/512MiB cgroup caps, zero-swap
  limit/current and effective BPF attachments. No weakening/no second backend.
- New API tree EXACT26 expected files plus the sole allowed .venv-api symlink to
  the verified original venv. Static tree EXACT37 release files plus separately
  recorded old public hashed JS/CSS/WOFF2 assets; conflicts must match bytes.
  Reject missing/modified/unexpected files, extra dirs, other symlinks, path escapes
  and wrong ownership/modes. Directory shape exact, bounded scan<=256 files.
- Recheck retained trees and immutable legacy record/backup digests again immediately
  before backend activation and before static switch. No writing to retained trees.
- Fresh >=768MiB MemAvailable, >=2GiB disk after transaction overhead; no active
  Prefect flow, ingestion/engine process or occupied slot; approved :45 UTC schedule,
  concurrency1 and strictly >600s window. Fresh production/config/cert/published
  historical data/model-metadata/forecast fingerprints, candidate PID excluded.

## Exact newly authorized write scope (future authorization must include it)

Create conditional parent root:root0700:
/var/lib/powerflow-staging/forecast-consistency-transactions/
Create ONE new root:root0700 child named by manifest.transaction_id. Existing
parent must already be safe0700; no permissions are altered to make it acceptable.
Inside that child save new exact previous-api.env (root:root0600) and state.json
(root:root0600) with independent backend/static targets, env hashes, original active
service state, fresh production baseline, old asset inventory, transaction ID and
legacy-record provenance hash. Files/directories are fsynced; backup bytes are
read/hash-verified before candidate changes. Legacy control is never overwritten.

Atomically replace ONLY /etc/powerflow/react-api.env, adding one newline-delimited
POWERFLOW_FORECAST_PUBLICATION_ROOT=/srv/powerflow/forecast-publications, preserving
all original bytes and root:root0600. Switch ONLY /opt/powerflow/react-current and
/var/www/powerflow-staging/current. Temporary .forecast-consistency-<UUID> siblings
are restricted to those pointer parents, env parent and NEW transaction directory.
Restart ONLY powerflow-candidate-api.service. No new publication root/bundle, unit,
venv, code/static file, Nginx/TLS/DNS/Cognito/AWS or production change.

## Ordered acceptance and failure handling

1. Read-only gates above; abort before writes on any mismatch or transaction collision.
2. Fresh unique transaction + durable verified backup/record. No candidate change
   before that point. If record creation fails, originals remain active and untouched.
3. Retained bytes + env/pointers + capacity/window + isolation + preservation recheck.
4. Switch candidate env/backend pointer and restart ONLY candidate once. Observe
   startup at most10 times1s apart (requests<=3s), not a deployment retry.
5. Require actual running cwd/new release, UID/GID992, worker/socket ownership,
   health200/ready200 and unchanged effective sandbox/cgroup/BPF protections.
6. Missing root must remain absent; forecast GET on direct loopback8010 must be503,
   exact FORECAST_WITHHELD and case-insensitive no-store directive token. Distinct
   STATUS_MISMATCH/BODY_MISMATCH/CACHE_MISMATCH; never echo raw bodies/headers.
   Operations200 MISSING_PUBLICATION with historical/unavailable health, no stale
   fallback; existing one-hour/coverage/pipeline/model endpoints200 and Admin401.
7. Only after backend acceptance, repeat fresh resource/security/preservation and
   retained-tree checks. Switch static pointer. Verify trusted staging HTTPS root
   hash, referenced JS/CSS assets, /api/health200, private /api/ready404, ACME200 and
   unchanged production fingerprint. Record COMPLETE in NEW transaction only.

On any failure, stop and retain all records/files. Partial state is reported with
phase/reason and automatic_rollback=false. Unknown timeout state needs separately
approved inspection; no guessing recovery. Same-window contingency may authorize
ONE separate rollback invocation only when this transaction mutated candidate state
and failed acceptance, with all rollback guards passing. It is never implicit.

Rollback selects ONLY the manifest-bound transaction directory, verifies matching
transaction identity, old/new target scope, exact new env backup hash, old release
inventories, current expected env/pointers, production baseline, capacity/window and
original active service state. Reject substituted records or an already rolled-back
transaction. Restore static/backend pointers and exact env independently, restart
only candidate, then verify health/readiness, original runtime restrictions, original
HTTPS index and production fingerprint. Preserve legacy AND new transaction evidence.
Memory/window/producer drift may block rollback; emergency stop/repair or gate
relaxation requires new authorization, not an override. No zero-downtime promise.

## Remaining actual acceptance

```sh
venv/bin/python -B scripts/smoke_staging.py --origin https://staging.powerflowenergy.dev \
  --expected-publication MISSING_PUBLICATION
```

Requires separate approval for real authenticated requests. Owner enters tokens only
in private TTY, never chat/files/argv. Verify seven routes/callback, UI rendering,
Google/native sign-in/out, server roles, seven Admin401/Analyst403 boundaries, missing
forecast503/provenance503/no-store, historical operations and static/stale-tab recovery.
Synthetic tests cover invalid/expired/409 contracts; live409 requires a separately
approved real valid publication, never a manufactured forecast. Missing-root behavior
in the actual unit proves no fallback, not future bundle readability or freshness.
Prior resource/evidence measurements are historical; fresh gates are mandatory.
Stop for manual commit and new exact-hash authorization. No server was accessed.
