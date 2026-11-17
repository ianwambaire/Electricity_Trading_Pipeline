# API_BODY_BOUND correction — new immutable staging release

LOCAL PREPARATION ONLY. No deployment, rollback, ingestion or publication is
approved by this document. Previous transaction 3b6717574fe046c9a0d23ec046b03513
is consumed and MUST NOT be reused. Historical transaction/control records and
all retained installations remain untouched.

## Findings and evidence limits

The saved failed assessment contains BACKEND_ACTIVATION/API_BODY_BOUND and no
endpoint/HTTP metadata. Its separately authorized rollback completed successfully.
It does not prove the exact remote response size. No new remote inspection ran.

Local reproduction using the original retained API and the existing local
historical CSV: GET /forecast/one-hour, no query parameters, HTTP200,
application/json, Content-Length1694070, measured1694070 bytes, 14878 records.
Other local historical probes returned557 bytes (coverage),100 (pipeline),2750
(models). These are LOCAL measurements, not fresh EC2 observations. The remote
frozen publication may differ in row count/size. The old endpoint ignores query
parameters: merely adding limit=24 to the old deployment would not fix it.

## Minimal application correction

- /forecast/one-hour now supports limit1..2000 (default500), offset0..2000000.
- Pagination counts backward from the newest target timestamp; each page is
  returned in chronological order. All original rows are validated before slicing.
- row_count counts returned records. total_rows, limit, offset and has_more expose
  pagination. A valid empty page past the end remains distinguishable from an empty
  or invalid source report (existing404/503 behavior).
- React requests limit500/offset0 and labels exports as displayed recent history.
- Acceptance requests /forecast/one-hour?limit=24&offset=0, requires HTTP200 and
  internally consistent pagination metadata/counts. Ignored limits fail closed.
- The 1000000-byte body limit remains unchanged on EVERY acceptance request;
  read stops at1000001 bytes. Truncated JSON is never parsed as success.
- API_BODY_BOUND now includes only fixed endpoint/query-scope labels, status,
  JSON/OTHER content-type classification, numeric Content-Length when safe,
  configured limit and measured lower bound. No response contents are reported.
  The local runner independently validates every additional diagnostic field.
- Existing next24 exact503 FORECAST_WITHHELD/no-store, operations MISSING_PUBLICATION,
  historical separation and anonymous Admin401 checks are unchanged.

## Immutable artifacts and transaction

Release: phase-api-body-bound-20261102-v2.
Private local package:
data/backups/private-staging-releases/phase-api-body-bound-20261102-v2/release/
Release manifest SHA256:
dc2fd9aa9cb0e961fd3859aa63b946a307c43f8a31ed6d8ac0ef4529c32f2045

71 entries:26 API/lock files,37 static files and8 review-only proposals.
Only api/src/api/app.py differs in the API inventory from the original release.
No dependency pin changes. Only the63 API/static entries can be installed.
Total manifest inventory1299305 bytes. No data, credentials or model binaries.

Fresh transaction: f2f195174eda43daa8e5593087fbe1d3.
Private remote control/backup directory (created only after future approval):
/var/lib/powerflow-staging/forecast-consistency-transactions/f2f195174eda43daa8e5593087fbe1d3/

The original phase-forecast-consistency-20261101-v1 release is NOT changed.
Its manifest remains9dc8ce31f1b294c43239824ffa544a76f4fdf6ba334ea8fd72b9431365ed5c19.
The original tools manifest and the separately preserved frontend follow-up are
unchanged. The runner verifies every original release entry as well as every new
release entry before assembling any executable payload from retained verified bytes.

## Why this requires apply rather than another reactivation

The retained old API does not implement pagination. It cannot safely be edited in
place or treated as corrected. Reuse the existing install-tree/apply implementation
for the new release, not a new deployment architecture. The apply runner action is
now exposed with the existing one-shot bounds and transaction selection.

The existing apply path now writes a transaction-bound record, independently backs
up the exact environment bytes, verifies the old legacy record is ROLLED_BACK and
matches current original pointers/environment, then installs NEW release paths.
Collision, unsafe control-directory permissions and legacy-backup drift stop before
new writes. It does not modify the legacy record or old retained releases.

Do NOT run reactivate against the new package before installation. It will fail
closed: the new retained paths/legacy association are not installed. No attempt
has been made to install them remotely in this task.

## Future apply scope and gates (separate authorization required)

1. Verify MANIFEST.json's separately approved SHA, all8 source/dependency hashes,
   original/new immutable packages, assembled apply/rollback hashes, connection
   metadata, exact approved identity and pinned known-host key. No path reopen of
   unverified executable bytes. No arbitrary remote command override.
2. Verify original backend/static pointer hashes and exact candidate environment
   baseline,26 input API/lock files and37 input static files; reject existing NEW
   destinations and transaction directory. Original source and static fingerprints
   remain the previously reviewed baselines; no refreshing drift protection.
3. Require zero active Prefect runs, ingestion/engine processes and occupied slots;
   strictly more than600 seconds before EVERY relevant scheduled occurrence.
4. Require MemAvailable>=768MiB and free disk>=2GiB plus pending installation size.
   Check existing one-worker loopback8010 identity, effective384MiB memory-high,
   512MiB maximum, zero swap, sandbox and BPF restrictions. No weakening.
5. Require stable production services, routing, certificates, frozen models and
   existing report/data fingerprints. Additionally require the exact approved
   deployed A03 parser SHA8800f34a2d0e3db4056e921a7b6629847402f37c20ff9b3e81d50f3c1d77865f
   before mutation and on EVERY preservation check, including rollback. No parser
   writes are permitted. Prior remote evidence is not a fresh PASS.
6. Create only the new private transaction/control records (root0700/files0600),
   durably write and read-back verify exact original candidate environment bytes,
   original pointers/service state and production fingerprint before activation.
7. Install ONLY the new root-owned0755 directory/0644 file trees:
   /opt/powerflow/releases/phase-api-body-bound-20261102-v2/
   /var/www/powerflow-staging/releases/phase-api-body-bound-20261102-v2/
   Reuse the existing verified virtualenv via the established .venv-api symlink.
   No dependencies, user, service unit, Nginx or TLS changes. Retain old hashed assets.
8. Recheck capacity, pointer/environment drift, runtime isolation and production
   preservation. Add ONLY POWERFLOW_FORECAST_PUBLICATION_ROOT=/srv/powerflow/forecast-publications
   to /etc/powerflow/react-api.env; do NOT create that publication root.
9. Atomically switch /opt/powerflow/react-current; restart ONLY the candidate
   service. Readiness, runtime security, forecast/operations/auth/history acceptance
   MUST pass before /var/www/powerflow-staging/current switches.
10. Verify staging HTTPS index and asset hashes, API health, denied public readiness,
    ACME handling and unchanged production preservation. Save terminal transaction.

No Nginx reload, production restart, data update, model inference, forecast
publication, Cognito or AWS change. Remote apply300s/local360s; rollback180s/240s;
TERM then KILL after5s, bounded private captures131072 bytes per stream, one SSH
attempt per independently authorized operation, strict pinned host identity,
noninteractive sudo, system Python -I -S -B. No automatic retry or rollback.

## Exact future invocations

Obtain the approved manifest SHA from the final local report. Replace the literal
placeholder below with that reviewed hash; do not automatically trust a new hash.

```
venv/bin/python -I -B deploy/staging/forecast-consistency-deployment/run.py apply --manifest-sha256 <APPROVED_MANIFEST_SHA256>
venv/bin/python -I -B deploy/staging/forecast-consistency-deployment/run.py rollback --manifest-sha256 <APPROVED_MANIFEST_SHA256>
```

For local verification ONLY, append --local-check. That verifies artifacts and
connection configuration without connecting. The command without --local-check
requires explicit fresh remote authorization.

## Independent rollback boundaries

Only with separate or explicitly conditional approval, use THIS transaction's
verified state.json and previous-api.env. Restore its independent original backend
and static pointers, exact environment bytes and original active service state;
restart ONLY the candidate; verify runtime controls, restored HTTPS hash and all
production fingerprints including approved A03 hash. No use of old transaction
records, cleanup, deletion, data restore or blind retry. Keep installed new release
files and all history for review. Failed backup/drift guards stop rollback.

A preflight failure needs no rollback. After partial installation/activation retain
all artifacts; status PARTIAL and the sanitized reason must be reviewed. The runner
does not automatically execute a rollback merely because apply fails.

## Local verification and remaining acceptance

Synthetic >1MB historical report, valid and invalid pagination, ignored limits,
body-bound diagnostics/redaction, original forecast503/no-store, Admin authorization,
A03 preservation, fresh transaction installation/rollback, collision and failed
preflight guards are covered by deterministic tests. No private artifacts are
required by these test fixtures. Python3.9 syntax checks cover executable tooling.
The frontend tests/lint and supported staging-origin release build are local proof,
not EC2/Linux/browser acceptance.

Production run01a19b6f-28b3-7dd9-831b-13c16cfa9b8e scheduled2026-11-02T11:45Z
must be inspected only after execution via an approved read-only interface. No
inspection/forecast generation/publication occurred in this task. A successful
flow is not proof of HGB inference: verify actual outcome, recovered Nov1 17:15
price300.44, current load/generation/price windows,31 ordered features, frozen
model/contract hashes,24 finite predictions and authentic reciprocal receipt hashes,
issue time and expiry. Do not publish expired or withheld forecasts.

After future installation, remaining checks include live seven-page HTTPS/browser
acceptance and owner-assisted Analyst/Admin sessions. Real current forecasts require
independent fresh production validation and separately authorized publication.

Final local results:355 focused Python tests passed before the manifest-only test;
100 frontend tests passed, ESLint passed and the supported staging release build
passed. One intermediate parallel frontend run had an MFA test-worker failure;
its isolated12 tests and the subsequent complete100-test run passed without source
changes. This remains a test-flakiness observation, not proof of a runtime MFA bug.
The actual local fixed endpoint returned200/application-json,24 of14878 records,
2848 bytes, versus1694070 bytes before correction. No live response size is claimed.
Actual system Python3.9.6 compiled/loaded both tooling modules in isolated mode and
executed the pure pagination check successfully. Frozen model and feature-contract
hashes matched their approved identities without model execution.
