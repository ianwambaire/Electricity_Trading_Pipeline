# Complete staging installation package — approval required, NOT executed

> **Execution stopped at approved_source_drift; original bundle is historical and must not be retried.** [R2 specific resolution](DRIFT-REVIEW-R2.md) records one authorized read-only inspection, the exact five changed source hashes and the separately proposed R2 bundle. No R2 execution is authorized yet. Original review/hashes below are retained.

Prepared 2026-10-26. This is the consolidated execution review, superseding the older partial installation sequence in `../REACT-DEPLOYMENT-REVIEW.md`. It does not authorize cloud access. Existing Streamlit, API8000, Prefect, PostgreSQL, MLflow, production databases and production routing remain untouched by this LOCAL preparation.

## Decision and approval boundaries

Approve **A (transfer + isolated installation)** and **B (candidate start + staging routing)** together as one bounded execution window if desired, with a hard stop between commands on every failure. They are explicit separate actions, with no workflow retry or automatic rollback. Approval must include the additional write paths below. **C (additive Cognito SPA URLs)** remains an independently authorized AWS operation. Authenticated browser acceptance depends on C. No public-domain cutover, retirement, backup transfer or renewal-timer activation is included.

This package creates a new `powerflow-api` system identity only if both user and group are absent. It is a non-login, locked-password system account, with no home, mail spool, sudo, supplementary group membership, keys or credentials. Existing identities are never repurposed. Root/privileged OS administrators retain access to private publication; ordinary access is limited to this dedicated service group. The runtime has no production home-directory visibility, no AWS credentials, and configured IMDS denies; effective cgroup/BPF checks are mandatory before routing.

## Immutable artifacts and exact bindings

Release ID: `phase-staging-https-ready-20261026`.

Private LOCAL transfer directory: `/private/tmp/powerflow-install-bundle-y4rh7gp1/` (38,127,690 bytes; code, built assets, metadata and approved wheels only). No database, source dataset bytes, model binaries, credentials or private backup are in this bundle or repository. Preserve the temporary directory until execution; do not add it to Git.

| Artifact | SHA-256 |
|---|---|
| bundle.json / repository BUNDLE-MANIFEST.json | `e0d86d94984a9f2ead63e3cbe087c11ebf7e52400bbe0304f002cc13ae1c02c1` |
| bootstrap.py | `39a3e19020f2b6aca5abc36537de55a274528d595b344d6de8bcfd19ea6cd303` |
| install.py | `56bfa7463593f4a070c638a02a1befd4ace4a364f9457a8445475565831cd5ae` |
| publisher.py | `9fe702f963c85817783697a595ff7ce4cc0264e04f31e92b9eef93af1fbcab01` |
| cgroup_bpf.py | `79282e3493e0cf447a13193ffa487ff3c3d7c7202ed9de136c7f5a2202084fb7` |
| release.tar.gz | `8a32da48575760f42b04043f249edeff7459c36212cf1d4eb09fbfb3e1479f3e` |
| wheels.tar.gz | `d71db0518421463fa78edd1bcd8d6db8cc3bf6008ed62972be5affdfe9161e97` |
| execute-approved.py (local runner) | `14ce9301baf6b79069a4c9b9b60d287309a79b10d8eb7ee3cd6e6d58b726926a` |
| existing local supervisor | `9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40` |

Full inventories, every source/destination pair, size, UID/GID/mode, freshness and SHA are in `BUNDLE-MANIFEST.json`. `BUILD-RESULTS.json` records all additional code/artifact hashes. Release archive contains the original68 files plus original manifest; no asset rebuild. Original manifest SHA `50be8e7a20c462eb8850d9bf61b77bb655f687f85c725cbd3d903b7ff14aad27`; lock SHA `b1d8bbbec84a08b651b7bdc0b96e5bb94bf6c527297e037357702de00bcc84e3`. All26 exact pins, including python-dateutil3.0.0, are unchanged. Wheel manifest SHA `1ae7da081a467988380614e346c01f256601369fd17196d635c6e71c7035693b`.

No source snapshot is transferred from Mac. Only the exact verified production sources are read on EC2. Any hash, ownership, permissions, size, inode or change-time drift aborts; this procedure cannot adopt new sources automatically.

## Required write paths — explicitly include these in approval

**Within requested installation scope:**

- `/srv/powerflow/published/` (new atomic publication, root:powerflow-api, directories0750/files0640).
- `/srv/powerflow/.published-phase-staging-https-ready-20261026/` (exclusive partial publication;0700 while copying; no automatic deletion).
- `/opt/powerflow/releases/phase-staging-https-ready-20261026/` including new `.venv-api`; no production venv use/modification.
- `/var/www/powerflow-staging/releases/phase-staging-https-ready-20261026/`.
- `/etc/systemd/system/powerflow-candidate-api.service` root0644; `/etc/powerflow/react-api.env` root0600, public configuration only.

**Additional paths required; no use until explicitly approved:**

- New parents `/srv/powerflow`, `/opt/powerflow`, `/opt/powerflow/releases`, `/var/www/powerflow-staging`, `/var/www/powerflow-staging/releases`, `/etc/powerflow`. Existing safe root-owned parents are reused where allowed; `/srv/powerflow` must be entirely absent to avoid changing another publication's permissions.
- New private incoming directory `/home/ec2-user/powerflow-staging-incoming-phase-staging-https-ready-20261026/` owned by ec2-user0700; ten exact public transport files,0600 by private source/remote umask.
- `/var/lib/powerflow-staging-install/phase-staging-https-ready-20261026/` and private parent: root0700, control payloads, extracted wheels/release, copied baseline placeholder, metadata/results, and private stdout/stderr captures0600. No private key is copied. This is a deployment audit directory, not an additional backup.
- New symlinks `/opt/powerflow/react-current` and `/var/www/powerflow-staging/current`; existing links cause STOP rather than replacement.
- OS account database writes/locks/normal automatic backup files associated with `groupadd --system powerflow-api` and `useradd --system --no-log-init --no-create-home --no-user-group --gid powerflow-api --home-dir /nonexistent --shell /sbin/nologin powerflow-api`: `/etc/{passwd,shadow,group,gshadow}` and their tool-managed lock/backup files. No existing account is edited; no login records are initialized. [System user creation semantics](https://raw.githubusercontent.com/shadow-maint/shadow/4.13/src/useradd.c).
- Synthetic, automatically disposable regression fixtures under the OS temporary directory; venv/pip's normal temporary unpack files there. No production data is placed there. The installation uses no dependency network access.
- B only: new `/etc/nginx/conf.d/00-powerflow-staging-support.conf`; new `/etc/nginx/powerflow/security-headers.conf` and parent; replace ONLY existing `/etc/nginx/conf.d/powerflow-staging-https.conf`, using exclusive `.phase-staging-https-ready-20261026.new` temporary file. Explicit rollback may create the corresponding `.rollback` file. Support definitions are reviewed `powerflow_safe` log format and `powerflow_api` limit zone; global `server_tokens` is not duplicated.
- B only: normal Nginx access/error log files `/var/log/nginx/powerflow-safe.log` and `/var/log/nginx/powerflow-error.log`, runtime Nginx/systemd state, candidate cgroup and journal. Safe access format excludes query strings/authorization; critical-only error logging minimizes URI exposure. Syntax checks/reload/requests may produce normal OS/service audit records. No raw tokens/credentials enter commands or captures.

No production virtual host, certificate, staging HTTP ACME configuration, existing application unit, production data file, DNS or AWS setting is written. MLflow is not started/stopped/queried; no MLflow content is read. Original production API/Streamlit/Prefect/PostgreSQL MainPID and state are compared throughout; no verified MLflow unit identity was available, so no claim of a separate MLflow service-identity comparison is made.

## A — transfer, identity, atomic publication, isolated installation

The exact source set is12 production files from `PUBLICATION-PREFLIGHT-RESULTS.json` plus the accepted A1 SQLite image:13 data files,102,895,192 bytes before the new provenance document. No live SQLite, WAL/SHM, forecasts-next24, joblib, environment files or logs. Expected A1 SHA `21fcb0e920ffaf13f214e39720e1176e012086d6ffa7b8a7ed736b6e4ab79690`,12,115,968 bytes; counts891/16525/1485/11561.

Publisher verifies every source before first publication write, immediately before copying, after copying and again before exclusive atomic rename. No symlink ancestors accepted. Linux O_NOATIME prevents read-atime updates; failure is fatal, without a silent fallback. A1 source sidecars cause STOP. Only the copied A1 image is opened through read-only immutable SQLite; full integrity check and exact counts must pass. WAL-mode header causes STOP, never conversion. Hashes of all final files must match approved sources. Files become visible at the fixed candidate root together using Linux renameat2(RENAME_NOREPLACE); no existing destination is overwritten. Failure retains a private partial directory and requires review.

`_publication.json` labels A1 **HISTORICAL, snapshot cutoff2026-10-26T02:22:00Z, not current operational state** and records per-file freshness. These sources have different producer cutoffs; this is an exact approved byte set, not a simultaneous cross-dataset pipeline transaction. The UI's existing stale/historical timestamps remain in effect; the package does not fabricate or relabel current data. This provenance file is not exposed as a new API endpoint.

Guards before installation: production Nginx/ACME hashes, root-private existing certificate baseline, placeholder, original service active identities, tools, Python3.14.7/x86_64 paths outside ProtectHome, no user/group/unit/port8010/destination conflicts, strict archive inventories and read-only BPF query capability. Root-owned private control staging may already exist if a later guard fails; it is retained.

Minimum MemAvailable768MiB. Free disk on each relevant filesystem must exceed **3,752,864,863 bytes** at preflight (conservative planned usage plus2GiB remaining and1GiB temporary reserve). Previously measured923.20MiB/11.895GiB are evidence only; checked afresh during execution. Measured Linux venv198.10MiB; wheelhouse36.59MiB. Publication98.13MiB. The conservative pre-reserve install budget is about507MiB, including multiple artifact copies/unpack space and300MiB runtime allowance. No new AWS resource/monthly service is introduced; retained root-volume files consume existing disk capacity.

Create new venv at final release path using `/usr/bin/python3.14 -I -S -B -m venv`; exact verified wheels offline `--no-index --only-binary=:all:`; pip check, compiled imports,8 offline synthetic lifecycle/JWT regressions run as actual service UID. Verify publication readable and non-writable as that user. Install root-owned code/static/env/unit, run systemd-analyze verify. Record actual venv/publication size. **Do not start, enable or daemon-reload candidate during A.**

### Exact owner command sequence (DO NOT RUN until approved)

Run from the repository. The following Python launcher verifies the exact local runner hash before any transport. Replace only the action on the final line as shown; all paths/hashes are fixed.

```sh
cd /Users/iannganga/Desktop/electricity-trading-pipeline
python3 -I -B - transfer <<'PY'
import hashlib, pathlib, runpy, sys
p=pathlib.Path('/Users/iannganga/Desktop/electricity-trading-pipeline/deploy/staging/install-package/execute-approved.py')
assert hashlib.sha256(p.read_bytes()).hexdigest()=='14ce9301baf6b79069a4c9b9b60d287309a79b10d8eb7ee3cd6e6d58b726926a'
action=sys.argv[1]
sys.argv=[str(p),action,'--bundle','/private/tmp/powerflow-install-bundle-y4rh7gp1','--sha256','e0d86d94984a9f2ead63e3cbe087c11ebf7e52400bbe0304f002cc13ae1c02c1']
runpy.run_path(str(p),run_name='__main__')
PY
```

After transfer exit0, run the same launcher with `python3 -I -B - install <<'PY'` (all enclosed Python identical). After install exit0 and review of private result, B uses `activate`; separately authorized rollback uses `rollback`. These are independent commands, not an automatic chained script.

For clarity, the runner's substantive transport operations are:

```sh
# Common options, reproduced exactly by the runner (no reading key contents):
ssh -i /Users/iannganga/.ssh/powerflow-key.pem -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts -o ConnectTimeout=10 -o ConnectionAttempts=1 -o ServerAliveInterval=10 -o ServerAliveCountMax=2 -o LogLevel=ERROR ec2-user@3.228.243.164 "umask 077; test ! -e '/home/ec2-user/powerflow-staging-incoming-phase-staging-https-ready-20261026' && test ! -L '/home/ec2-user/powerflow-staging-incoming-phase-staging-https-ready-20261026' && mkdir -m 700 '/home/ec2-user/powerflow-staging-incoming-phase-staging-https-ready-20261026'"
# scp uses identical identity/host options and exactly the ten bundle filenames.
# Install: verified bootstrap.py is SSH stdin, never copied into a production checkout:
sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 660s /usr/bin/python3.14 -I -S -B - e0d86d94984a9f2ead63e3cbe087c11ebf7e52400bbe0304f002cc13ae1c02c1
```

Use the runner, not bare illustrative SSH: it verifies all local hashes, captures output privately and applies the supervisor. Transfer: one bounded30s directory SSH + one120s SCP connection; installation: one660s remote/700s local SSH, five-second TERM→KILL escalation, inner installer600s. No retries/cleanup. Transfer failure leaves the new private incoming directory; do not overwrite/retry without approval. All server hashes are independently verified before privileged copying/execution; root-private copies prevent the incoming owner changing privileged payloads afterward.

## B — effective candidate validation and staging routing only

Same hash-verifying launcher, action `activate`: one300s remote/340s local SSH; no transfers. The root-private bundle and installer hashes are verified again before execution. Effective-memory watch begins with cold start and continues through acceptance/routing. Stop ONLY candidate if <256MiB MemAvailable, OOM, restart or original service-identity change is detected. This safety stop is distinct from rollback. Normal workflow failures retain artifacts; no repair/reload retry. The reviewed unit's bounded Restart=on-failure remains unchanged; any observed restart fails acceptance.

Exact major commands inside verified install.py:

```sh
systemctl daemon-reload
systemctl start powerflow-candidate-api.service
# Both must return200; readiness checks real required local SQLite schema + identity wiring:
# GET http://127.0.0.1:8010/health ; GET http://127.0.0.1:8010/ready
systemctl show powerflow-candidate-api.service --property=User,Group,MainPID,ActiveState,SubState,MemoryHigh,MemoryMax,MemorySwapMax,NRestarts,ControlGroup,IPAddressDeny,ProtectHome,ProtectSystem,NoNewPrivileges,PrivateTmp,PrivateDevices,CapabilityBoundingSet
# Kernel checks: /sys/fs/cgroup/system.slice/powerflow-candidate-api.service/{memory.high,memory.max,memory.swap.max,memory.events}
# Read-only BPF_PROG_QUERY for effective ingress + egress attachments, no load/attach:
# Require configured IMDS denies AND nonempty effective attachments. This is not formal bytecode/traffic proof.
/usr/sbin/nginx -t
# Install only support/headers + reviewed staging vhost, from verified immutable archive.
/usr/sbin/nginx -t
systemctl reload nginx
```

Baseline Nginx syntax test actually runs before candidate start; second runs after staging-only replacement and before the one reload. Reuse unchanged corrected strict include reviewer, including its exact safe root-owned Let's Encrypt options-file exception. Fail on name/listener/include conflicts and existing support definitions. The original staging HTTP ACME config is never edited. Certificate SAN must be exactly staging.powerflowenergy.dev, expiry Jan24 07:38:12 2027GMT, >30days valid and trusted. No private key contents are read by scripts; Nginx itself accesses its existing configured key normally.

Effective unit checks require one loopback8010 listener belonging to MainPID;384MiB high,512MiB max,zero swap both systemd and kernel; protected home, strict filesystem, private temp/devices, NoNewPrivileges, empty capabilities. [Linux BPF query interface](https://raw.githubusercontent.com/torvalds/linux/v6.1/include/uapi/linux/bpf.h). Unsupported/denied query is STOP, not a weakened unit. Candidate never enabled at boot in this package.

Verify public coverage/model/anomaly/one-hour endpoints200, next24404 (intentionally unavailable), seven restricted endpoints401 without tokens. Offline signed-token tests verify all seven Analyst403; real-account acceptance is separate. A60s low-overhead observation window precedes routing. No load tests. HTTPS with normal trust/SNI must return200 for all seven page entry URLs plus callback and /api/health; /api/ready404; HTTP and HTTPS ACME200 with exact probe body. HTML route200 proves routing, not successful rendered/OIDC interactions. Preservation compares original services, production configuration/public certificate and staging HTTP ACME hashes before/after.

Real Google Admin/native Analyst/MFA sign-in, role verification, seven Analyst403, read-only page rendering desktop/tablet/mobile, profile retrieval, sign-out and fresh sign-in must be checked after C. Use existing `scripts/smoke_staging.py`; tokens only through its private interactive input, never chat/argv/files. Do not modify accounts/passwords/MFA as deployment smoke tests. Next24 remains absent/unvalidated, not operational.

## Candidate-only rollback — separate explicit action, no cleanup

Same launcher action `rollback`: one120s remote/160s local SSH. Hash-verified saved original placeholder is restored only if current vhost is still the approved candidate/placeholder; unknown changes STOP. Validate nginx, reload once only if restoration needed, then stop ONLY candidate if loaded. Compare original service identities/config/cert/ACME again. No original application service is restarted or old data restored. Support includes, stopped candidate unit/env/identity/publication/releases and audits are retained. No `rm`, user deletion, link cleanup or unit disabling is performed. Nginx rollback validation failure leaves saved/installed artifacts and requires separate review. Installation failures before B leave production routing unchanged; no rollback is normally needed, and cleanup is separate authorization. A killed process, partial installer, resource failure or transport timeout must never be retried automatically.

## C — separate additive Cognito approval

Public URLs only: add callback `https://staging.powerflowenergy.dev/auth/callback` and logout `https://staging.powerflowenergy.dev/` to SPA client4t8s6a673a18qhbauqac8rhdcf in poolus-east-1_NLoYFRvex, account870755688674/us-east-1. Do not touch Streamlit client/provider/scopes/attributes/token policies/MFA. No AWS call is in the deployment runner.

After separate approval, exact bounded procedure: private local directory (`umask077`); one STS account check; one Describe; local `prepare-cognito.py` transform retaining all recognized settings; manual exact additive diff; one Update; one readback. Stop on any unknown field/client secret/identity mismatch/error. Set AWS_MAX_ATTEMPTS=1, connect timeout10/read timeout20, no retries. Do not run until approved:

```sh
umask 077
COGNITO_REVIEW_DIR=$(mktemp -d /private/tmp/powerflow-staging-cognito-XXXXXXXX)
AWS_MAX_ATTEMPTS=1 aws sts get-caller-identity --region us-east-1 --cli-connect-timeout 10 --cli-read-timeout 20 --no-cli-pager > "$COGNITO_REVIEW_DIR/identity.json"
# Parse identity.json locally; require Account exactly870755688674, otherwise STOP.
AWS_MAX_ATTEMPTS=1 aws cognito-idp describe-user-pool-client --user-pool-id us-east-1_NLoYFRvex --client-id 4t8s6a673a18qhbauqac8rhdcf --region us-east-1 --cli-connect-timeout 10 --cli-read-timeout 20 --no-cli-pager > "$COGNITO_REVIEW_DIR/before.json"
python3 -I -B deploy/staging/install-package/prepare-cognito.py "$COGNITO_REVIEW_DIR/before.json" "$COGNITO_REVIEW_DIR/update.json"
# STOP for exact two-list additive comparison, all other writable fields unchanged.
AWS_MAX_ATTEMPTS=1 aws cognito-idp update-user-pool-client --cli-input-json "file://$COGNITO_REVIEW_DIR/update.json" --region us-east-1 --cli-connect-timeout 10 --cli-read-timeout 20 --no-cli-pager > "$COGNITO_REVIEW_DIR/applied.json"
AWS_MAX_ATTEMPTS=1 aws cognito-idp describe-user-pool-client --user-pool-id us-east-1_NLoYFRvex --client-id 4t8s6a673a18qhbauqac8rhdcf --region us-east-1 --cli-connect-timeout 10 --cli-read-timeout 20 --no-cli-pager > "$COGNITO_REVIEW_DIR/after.json"
# Compare saved result to update.json excluding only server timestamps.
```

The commands are sequential gated steps, NOT a script to paste without checking the indicated STOP points. A separate exact reviewed AWS wrapper is required when C is approved; no unattended chain or unspecified IAM creation is implied. Rollback would remove only newly added URLs if no intervening client changes; do not blindly restore stale whole-client configuration. Requires its own authorization. Native/Google identity behavior and settings are not changed by this local transform.

## Local validation and remaining limits

-103 targeted Python tests passed, including14 new package tests. One existing Starlette/AnyIO deprecation warning; no failures.
- Syntax compilation of all package Python files passed. Bundle exact inventory/hash verification passed; original68-file release and wheels independently matched immutable manifests.
- Disposable pinned Linux3.14.7 AMD64 container, network disabled/no host mounts/capabilities dropped: real renameat2 success and existing-destination refusal passed with synthetic files only.
- Existing measured Linux26-pin installation, compiled imports, pip check and8 regressions remain the baseline; no dependency reacquisition or candidate rebuild this phase.
- No frontend sources or built assets changed; frontend tests/build not rerun unnecessarily. Earlier85-test/build result is prior evidence, not a new run.
- No SSH, AWS, production command, account creation, publication, service change or Git operation executed. No claim of live deployment or full host systemd enforcement.

Outstanding execution gates: explicit approval of additional paths/identity and A/B; current source hashes may drift and must abort rather than refresh; fresh capacity; host BPF-query/systemd/actual service-user permissions and compiled imports; separate C and real browser acceptance. Root volume remains unencrypted, and A3 off-host recovery is outside this staging scope. No additional EC2 or AWS resource is proposed.
