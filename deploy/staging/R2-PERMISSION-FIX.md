# R2 PermissionError — confirmed cause and minimal proposed continuation

One read-only SSH diagnostic exited0. No remote file, permission, identity, service or routing change was made. Evidence: `R2-PERMISSION-DIAGNOSTIC-RESULTS.json`; private capture `/private/tmp/powerflow-r2-permission-diagnostic-a67t0ab2/`.

## Cause

The R2 installer sets umask077. Its mkdir_new_or_safe helper requested0755/0750 with mkdir, but did not chmod newly created directories afterward. Umask reduced these requested modes to0700. The first actual UID992 subprocess spawn, `candidate-offline-regressions`, therefore raised PermissionError while attempting to execute:

`/opt/powerflow/releases/phase-staging-https-ready-20261026/.venv-api/bin/python`

Last successful retained step is pip-check; linux-regression.py exists, but no candidate-offline-regressions capture exists. A read-only child running as powerflow-api UID/GID992 confirmed EACCES traversing the release hierarchy, while /usr/bin/python3.14 itself is readable/executable. The newly created release ancestry lacks traversal permission; the exact individual /opt ancestor modes were not included in the diagnostic capture and must pass guarded0700 checks before repair. `/srv/powerflow` is directly confirmed root:992 mode0700, separately blocking access to its otherwise correctly0750 published child. Static parent directories were created through the same defective helper and also require guarded validation.

The original main exception handler discarded the traceback and filename. There is no retained traceback to quote; failing operation is identified from source order, last successful capture and effective-access denial. No raw logs or database records were exposed.

## Completed / not completed

Completed: source/hash/capacity preflight; root-private control artifacts; dedicated UID/GID992 identity; atomic13-file publication plus metadata; exact backend/static release copies; Python3.14.7 venv;26-package offline installation; pip check; prepared regression script.

All expected API/static file hashes and all13 publication hashes match R2. Publication metadata also matches saved SHA. Snapshot files need no republishing. No partial publication directory remains.

Not completed: service-user regression execution/access checks; release symlinks; candidate environment/unit installation; installed.ok; daemon-reload/start; activation. Candidate unit is not-found/inactive/MainPID0.

Production API, Streamlit, Prefect worker/server and PostgreSQL identities exactly match saved pre-install MainPIDs/states. Production Nginx, production certificate, staging HTTP ACME and staging HTTPS placeholder match baselines. MLflow was not touched; no separate live MLflow-unit identity was available for comparison.

## Minimal local fix and reuse

Local install.py now explicitly chmods only newly created directories to their reviewed modes after mkdir; existing directories remain untouched. It also records sanitized subprocess-spawn errno/executable/UID/GID in private0600 evidence rather than discarding that failure context. Fixed local installer SHA256:

`aca403cc57cf6cbc7b716c3abc534dc0ffc8d4430afced7f1f876271a1d161e1`

This is a LOCAL correction only; the root-private R2 code and approved R2 bundle remain unchanged. Do not rerun the full installer or replace its private files.

Reusable pending verification: published immutable snapshot, backend/static release, isolated venv, identity and private control/wheels. No cleanup, deletion, retransfer, package reinstall, source-hash refresh or publication retry is needed. The venv must still pass the existing8 compiled-import/version/JWT/lifecycle regressions as UID992.

Prepared `resume-r2-install.py`, SHA256:

`feb5359d1e0aa2869fa337e281a8a13afb3e1261403786eff9a601b4010cd83b`

It verifies original R2 bundle/control/artifacts, release/publication hashes, saved production baselines, unchanged staging placeholder, unused candidate unit/links/environment and fresh capacity. Then, with a single exclusive resume marker, it validates all five expected root-owned0700 parents before any chmod:

- `/opt/powerflow`, `/opt/powerflow/releases`, `/var/www/powerflow-staging`, `/var/www/powerflow-staging/releases`: root:root0700→0755.
- `/srv/powerflow`: root:powerflow-api0700→0750.

Reject symlinks/unexpected ownership/modes. Do not chmod recursively or loosen publication/control contents. Recheck pip check, run original offline regressions and read-only publication access as UID992, then finish only the previously reviewed symlinks, non-secret environment, unit, systemd-analyze verify and installation markers. No dependencies installed; no database/source changed; no daemon-reload, service start, Nginx test/reload or activation. Stop on any failure, retain artifacts, no retries or rollback.

54 targeted local tests passed, including restrictive-umask0755/0750/0700 behavior, no permission change to existing directories, safe spawn-error evidence, all-five-before-any-chmod guard, reuse constraints and prior publication/execution tests. One existing AnyIO deprecation warning. Syntax passed. No remote repair or continuation has run.

## Next narrow authorization (NOT granted yet)

Approve one bounded SSH execution of the hash-bound resume payload to perform exactly the five guarded mode corrections and remaining installation validations/files above. Remote timeout240s, local supervisor300s with5s kill escalation; existing strict known-host identity; private captures. All existing source data and published bytes remain unchanged. Staging activation would require a subsequent explicit go-ahead after this succeeds.

Exact proposed command, not executed:

```sh
python3 -I -B - <<'PY'
import hashlib,json,os,runpy,subprocess,sys,tempfile
from pathlib import Path
root=Path('/Users/iannganga/Desktop/electricity-trading-pipeline')
p=root/'deploy/staging/resume-r2-install.py'
s=root/'deploy/remediation/a3-bounded-local.py'
r=root/'deploy/staging/install-package/execute-approved.py'
assert hashlib.sha256(p.read_bytes()).hexdigest()=='feb5359d1e0aa2869fa337e281a8a13afb3e1261403786eff9a601b4010cd83b'
assert hashlib.sha256(s.read_bytes()).hexdigest()=='9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40'
assert hashlib.sha256(r.read_bytes()).hexdigest()=='89c9621ff8cce664fc5f59993c4ae7f60bd74ac38b6bf99c87aeca8aab43ddd4'
options=runpy.run_path(str(r))['OPTIONS']
os.umask(0o077);capture=Path(tempfile.mkdtemp(prefix='powerflow-r2-resume-',dir='/private/tmp'))
command=['ssh',*options,'ec2-user@3.228.243.164','sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 240s /usr/bin/python3.14 -I -S -B -']
code='import runpy,sys; m=runpy.run_path(sys.argv[1]); raise SystemExit(m["run"](sys.argv[2:],seconds=300,grace=5))'
with p.open('rb') as source,(capture/'stdout.json').open('xb') as out,(capture/'stderr.private').open('xb') as err:
 result=subprocess.run([sys.executable,'-I','-B','-c',code,str(s),*command],stdin=source,stdout=out,stderr=err)
print(json.dumps({'exit_status':result.returncode,'private_capture_directory':str(capture),'retry':False}))
PY
```
