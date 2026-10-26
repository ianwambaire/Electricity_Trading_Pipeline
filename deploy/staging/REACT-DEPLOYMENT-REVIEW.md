# React staging execution review — LOCAL proposal, not executed

Release: `phase-staging-https-ready-20261026`; Mac candidate `/private/tmp/powerflow-react-stage-review-dudwnuhr/candidate`; 68 files, 1,271,788 bytes. Manifest SHA256 `50be8e7a20c462eb8850d9bf61b77bb655f687f85c725cbd3d903b7ff14aad27`. Static assets are unchanged from the verified staging-origin build. Package verifier checks every file, exact inventory and public OIDC configuration. No datasets, databases, credentials, environment files, recovery artifacts, venv or model binaries are packaged.

## Confirmed checkpoint and remaining Linux gate

Authorized cgroup diagnostic passed: cgroup2 at `/sys/fs/cgroup`, memory advertised/enabled, `system.slice` high/max/swap interfaces readable. Missing hierarchy-root limits are expected interface placement, not absence of descendant support. Host interface compatibility is CONFIRMED; effective candidate limits/BPF are UNVERIFIED. No resource protection is relaxed.

The immutable candidate remains unchanged. Existing macOS CPython3.14.7 dependency/import checks pass, but local Linux amd64 Python3.14.7 image/runtime is now verified by immutable digest, but the corrected approved offline attempt PASSED: all26 exact pins installed with no index/network, pip check and compiled imports passed, and8 Linux regressions passed (0 failures/errors) in13.939seconds. Completed venv202,856KiB, wheelhouse37,472KiB, sampled workspace peak246,091,776bytes. Host/container ProtectHome path static review passed, but EC2 base interpreter accessibility, libc compatibility and effective unit protections remain UNVERIFIED. See `LINUX-DEPENDENCY-REVIEW.md` and `LINUX-DEPENDENCY-RESULTS.json`. System3.9.25 cannot satisfy the lock. Base interpreter accessibility under ProtectHome must be verified before new venv installation.

## Hard gates before any installation authorization

- Fresh bounded host inspection: candidate unit/user/paths and port8010 unused; no symlink ancestors; no existing objects may be overwritten; record original API8000/Streamlit/Prefect/PostgreSQL identities and production Nginx/cert baseline hashes. Previously observed capacity is not current evidence.
- Verify actual Linux interpreter and a clean API-only lock installation. Never copy the Mac venv, update `.venv-prod`, or install/upgrade production Python. The version-pinned lock is NOT hash-locked. Prefer a separately verified Linux wheelhouse and offline installation; Python version/ABI and wheelhouse digest must be approved before exact install commands are executable.
- A separately reviewed, immutable publication manifest is required for `/srv/powerflow/published`: legitimate market observations, public model/evaluation metadata and a coherent standalone operational SQLite snapshot. Never mount the live DB, copy live WAL files individually, publish secrets/logs or use synthetic smoke fixtures. The local preflight snapshot helper is not a production publication authorization. Exact source files/hashes/size remain a blocker. Exclude unvalidated next24 forecast reports; do not rewrite production reports or withholding status.
- Verify `powerflow_safe`, `powerflow_api` and `/etc/nginx/powerflow/security-headers.conf` do not conflict with existing settings. Install reviewed http-context definitions ONLY if absent; hash-bind reusable existing ones. Existing staging HTTP ACME and production vhosts are never edited.
- Root-owned read-only code/static publication; service user `powerflow-api` with no login, sudo or instance-profile credentials. If this user exists, inspect identity before reusing it; do not change an existing account blindly.
- At least768MiB MemAvailable before start; at least2GiB free after installation plus conservative publication/venv/unpack allowance. Candidate max512MiB, high384MiB, no swap, one worker,32 concurrency,1 CPU. A separate approved capacity watcher must stop ONLY candidate on <256MiB available, OOM/restarts or production degradation. No benchmark/load test on shared host.

## Proposed install sequence after those gates, exact artifacts and transfer are approved

1. Transfer only the digest-verified candidate to a NEW private incoming directory. Verify manifest SHA256 and all68 file sizes/hashes on EC2 before privileged installation; refuse extras/symlinks. No `git pull`, production checkout edits or dependency downloads into shared environments. Transfer protocol, incoming directory and offline wheelhouse/publication hashes must be bound in the final installer.
2. Exclusively create `/opt/powerflow/releases/phase-staging-https-ready-20261026`; copy candidate `api/` CONTENTS into this directory (so `src/api` and `requirements/api.lock` sit at its root). Create `.venv-api` with the approved Linux interpreter; install only approved wheels matching `requirements/api.lock`; run `pip check` and offline import/lifecycle tests. Record venv disk usage; no service starts here.
3. Exclusively install candidate `static/` contents under `/var/www/powerflow-staging/releases/phase-staging-https-ready-20261026` (root-owned dirs0755/files0644). Root-owned backend directories0755/files0644, venv executables0755. No recursive chmod/chown outside the NEW release. No `.env` copied from production.
4. Install approved publication at `/srv/powerflow/published` as root-owned directories0750/files0640, group `powerflow-api`; verify traversal/read-only access as service user. Install `api.env.example` as `/etc/powerflow/react-api.env` root0600. It contains public identity/runtime settings only, no secrets. Keep MFA enrollment disabled and test subject empty. Install exclusive `/opt/powerflow/react-current` symlink to the new backend. Never alter old service8000's code, venv or unit.
5. Install `powerflow-candidate-api.service` root0644 at `/etc/systemd/system/`. Linux validation is mandatory:

```sh
systemd-analyze verify /etc/systemd/system/powerflow-candidate-api.service
systemctl daemon-reload
```

Neither command starts/enables candidate. Verify cgroup memory/swap and IPAddressDeny enforcement; inability to enforce IMDS isolation is a STOP, not permission to remove it.

6. Prepare NEW private control directory containing the hash-bound activation scripts/config at their expected relative `deploy/staging/` paths. Create `/var/lib/powerflow-staging` root0700. From the control directory, the activation operation is:

```sh
bash deploy/staging/activate-staging.sh phase-staging-https-ready-20261026
```

It requires the installed staging HTTPS placeholder hash `85ad4c7ec303b638033831cb7ebfd5b73b669c80b249926c8e1446ba70124396`, preserves it privately, replaces ONLY `/etc/nginx/conf.d/powerflow-staging-https.conf`, switches static pointer, tests Nginx, starts ONLY candidate, waits at most20 readiness requests then gracefully reloads Nginx once. Pre-install Nginx validation also occurs. No automatic repair/rollback/deletion. Candidate remains inactive until this step. Systemd's existing bounded restart policy is distinct from script retries; stop on any restart/OOM during acceptance.

7. Immediately verify health/ready on loopback with five-second request bounds and inspect effective candidate resource caps:

```sh
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/health
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/ready
systemctl show powerflow-candidate-api.service --property=MainPID,ActiveState,SubState,MemoryCurrent,MemoryHigh,MemoryMax,MemorySwapMax,NRestarts
```

Readiness genuinely probes required operational SQLite columns and identity configuration; it does NOT prove all datasets, freshness or Cognito reachability. Test separate market/model coverage, missing-data/withheld forecasts and network error UI. Confirm no production hash/service identity changes, and both HTTP/HTTPS ACME exact200/body remain. HTTPS hostname/chain must validate with normal trust, never `-k`.

8. Owner Terminal acceptance after separate Cognito approval:

```sh
venv/bin/python -B scripts/smoke_staging.py --origin https://staging.powerflowenergy.dev
```

Read-only smoke: seven entry routes/callback, API contract, unauthenticated401, all seven Analyst403, verified Admin/Analyst roles. Tokens entered privately by owner, never chat/argv/files. Separately inspect all seven rendered pages desktop/mobile, real Google Admin/native Analyst PKCE+MFA callbacks, profile retrieval, sign-out/fresh sign-in. Do not perform account writes or MFA/recovery operations as a deployment smoke test. A missing next24 report is acceptable; no unvalidated operational chart/prediction may appear.

## Separate Cognito approval

Only additive SPA callback `https://staging.powerflowenergy.dev/auth/callback` and logout `https://staging.powerflowenergy.dev/`. Preserve every existing URL/provider/scope/attribute/client setting and the Streamlit client. Fresh readback and exact additive update required; not included in deployment scripts. Static/API installation can precede this, but authenticated staging acceptance cannot pass without it.

## Explicit rollback (separate authorization; never automatic)

From the same immutable control directory:

```sh
bash deploy/staging/rollback-staging.sh phase-staging-https-ready-20261026
```

Requires installed config digest and saved placeholder digest; retains app config, restores ONLY placeholder, runs Nginx test, gracefully reloads once, stops ONLY candidate. Failure stops at that stage; no automatic repair. Leaves static/backend/publication/control/env/unit artifacts and static symlink for review. ACME/TLS continue, root returns404 again. No deletion, database restore/migration, production service changes, Cognito rollback or application-user cleanup. If candidate fails before Nginx reload, old placeholder remains live; on-disk changes still require approved rollback. Recovery from OOM, timeout or a missing rollback prerequisite requires a new bounded review.

## Resources and limits

No new EC2, certificate, EIP or permanently running backend. Temporary candidate on8010 alongside existing8000/8501. Static transfer1.27MB; venv, wheelhouse and real publication size remain unmeasured: provision conservatively and measure before approval, do not call1.27MB total deployment storage. No production ingestion/training. Existing storage/network charges apply; no incremental instance charge. Renewal timer installation is still separate and required before unattended long-term use. Apex cutover/Streamlit retirement are excluded.
