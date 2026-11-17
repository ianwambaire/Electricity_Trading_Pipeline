# Staging API context hotfix — execution review

Prepared only; not deployed. Read-only installed verification passed: all 22 original API/lock hashes, original current symlink, absent hotfix destination/helper, active UID992 candidate, Python3.14.7, FastAPI0.136.3, pandas2.3.3, uvicorn0.48.0, MemoryMax512MiB/MemorySwapMax0. Evidence: INSTALLED-VERIFICATION.json. No environment contents or credentials retrieved.

## Exact code change

- src/shared/market_context.py: import standalone shared aggregator instead of processing.build_silver_dataset.
- src/shared/price_aggregation.py: equivalent pure price aggregation; duplicate/mixed/unsupported resolution rejection, timestamp alignment, complete quarter counts and null handling preserved. Pipeline code, forecast gates, API contracts and dependencies unchanged.

MANIFEST.json records both code hashes and execution payload hashes. Its SHA256 is `24284baf32424366c9c413794904b158237f6ce20e0257342cd6abfb4f35edcf`.

## Execution scope and stop conditions

One strict-known-host SSH connection to ec2-user@3.228.243.164; existing key, noninteractive sudo. Remote180s timeout +5s escalation, local210s +5s escalation, no retry. The root payload is streamed over stdin; not installed remotely.

Before writes: verify all original code/lock hashes and safe root-owned ancestry; expected current pointer; no new destination; at least768MiB available RAM and2GiB free disk. Capture only production service identities and hashes of existing Nginx configurations, candidate unit and public production certificate.

Create ONLY `/opt/powerflow/releases/phase-staging-https-ready-20261026-context-hotfix-20261029/` containing verified copied API source/lock plus the two patched files, a symlink to the unchanged original virtualenv, and root-private `.preservation.json`. Code directories0755/files0644; baseline0600. No dataset, environment-file, static-asset or virtualenv copy/install. Original immutable release stays untouched.

Run both fixed helpers read-only against the existing publication as UID/GID992 in an isolated child. Abort before pointer change if this fails. Atomically replace `/opt/powerflow/react-current` via the exclusive temporary symlink `/opt/powerflow/react-current.context-hotfix-pending`. Restart ONLY powerflow-candidate-api.service once. No systemd unit edit or daemon-reload. Allow a three-second startup interval, then require health, readiness and both fixed routes200 plus effective cgroup memory.max512MiB and memory.swap.max0. Verify production API/Streamlit/Prefect/PostgreSQL identities, Nginx/certificate/unit hashes unchanged. No Nginx command/reload, AWS or Cognito operation.

Any gate failure stops; retain all artifacts and private captures. No automatic retry, repair, cleanup or rollback. Atomic pointer replacement does not mean zero downtime: the candidate-only restart briefly interrupts staging API requests. Existing systemd restart policy is not changed. Forecast404/WITHHELD remains appropriate; this hotfix does not restore forecast availability.

## Exact execution command — separately authorize APPLY

From the repository root:

```sh
python3 -I -B - <<'PY'
import hashlib,pathlib,runpy,sys
root=pathlib.Path('deploy/staging/api-hotfix').resolve()
assert hashlib.sha256((root/'MANIFEST.json').read_bytes()).hexdigest()=='24284baf32424366c9c413794904b158237f6ce20e0257342cd6abfb4f35edcf'
assert hashlib.sha256((root/'execute.py').read_bytes()).hexdigest()=='738aedabaebb95327617892748afd66da707e51563f8eae9bd8f95ed8f6c05df'
sys.argv=[str(root/'execute.py'),'apply']
runpy.run_path(str(root/'execute.py'),run_name='__main__')
PY
```

The runner verifies the manifest's payload hashes, existing SSH-options runner and supervisor hashes before transport, and retains stdout/stderr in a private local directory.

## Rollback — separate explicit authorization if required

Use the exact command above with `sys.argv=[str(root/'execute.py'),'rollback']`. This validates both releases, original environment binding and saved production baseline, requires the current pointer to resolve to the hotfix, atomically restores the original pointer and restarts ONLY the candidate once. Require health/readiness200 and unchanged production baselines. It intentionally restores the known context/comparison defect. It does not delete artifacts or undo unrelated changes; unexpected drift stops rollback for review. A failure before pointer replacement requires no pointer rollback; leave the unused partial release in place for review. Do not rerun apply against an existing destination.

## Local validation

89 targeted tests passed, including unchanged aggregation semantics, standalone API routes rejecting pipeline imports, next24 quality gates, two-file payload/hash validation, atomic switch/rollback/conflict behavior and symlink rejection. All three package scripts passed Python syntax/AST validation. No frontend rebuild or release rebuild. Effective execution of the new release remains an approval-time gate; no deployment claimed.
