# Realized next24h Performance Reporting — guarded staging candidate

Release: `phase-realized-next24h-performance-20261108-v1`.
Transaction: `bcf8ed57934d4c2baed04b432f5726b1`.
**Local preparation only. No remote action is authorized by this document.**

## Immutable baseline and scope

Predecessor: accepted Live Forecast Reliability V2, transaction
`565437b5103a45d3b6192ecd70498f78`, manifest
`01b98fc094595b5ec626be8a0a254d57193ba63a8b25e1cc2a729f4c2752dba7`.
The accepted V4 component-preservation implementation is reused from manifest
`6ab3f093a22dd0940fefb871331f94e6803689168dbb1828461ed169fd26bd9f`.
Existing installed source and configuration are never accepted from host hashes.
The original monitoring module comes from repository commit
`221693a96525afa4b96a2289297aa84cb00c6418`; its exact hash must match the host
before apply. That equality is a preflight condition, not a claim already observed.

MANIFEST.json lists every exact API, static and reporting-worker destination,
SHA-256, size, embedded bytes or hash-bound retained-chunk source. All previous
hashed frontend assets remain present. Auth build-config must match the accepted
predecessor exactly; auth/security API modules come unchanged from its payload.
Only reporting API/settings, contract/store, reporting producer and monitoring
integration change. The original model, inference implementation, scheduling,
operational helper/launcher/sudo rules and authentication configuration remain
unchanged. No Nginx change/reload, dependency installation or migration.

Worker install scope: `models/next24h_monitoring.py`, `models/realized_reporting.py`,
`shared/realized_report.py`, `shared/realized_report_store.py`, and
`shared/operational_evidence_producer.py`. The latter is unchanged existing trusted
receipt-verification code; an existing host copy is allowed only if byte-identical.
Every other transitive project source is preservation-only and hash-verified.
Existing Python dependencies are reused; direct runtime versions and unprivileged
imports are verified before mutation. No forecasting/model functions are called
by import or acceptance probes. Python 3.14.7 execution, Python >=3.9 bootstrap.

## Read-only preflight

One pinned SSH connection using the established identity and known-host hash;
strict host-key/public-key/noninteractive/no-agent/no-forwarding configuration.
90s remote /150s local, five-second termination escalation, bounded sanitized
output; no retries. Preflight payload excludes transaction mutation entrypoints.

Verify accepted V2 installed files, pointers, independent retained backups,
helper V2 and operational store, runtime closure, Linux/procfs/UID/GID, actual
pipeline and Prefect idleness and **strictly >600s** until the next scheduled run,
capacity, fixed Prefect 3.7.5 source/metadata bindings, all worker dependencies,
source count/size bounds, Nginx and environment hashes, production/legacy health,
forecast integrity/expiry behavior, operational API scoping and anonymous Admin
401. Naturally advancing forecast/operational evidence uses the previously
accepted integrity/association/retention policy; immutable assets/config remain
exact. No role simulation or claim of genuine Analyst 403 acceptance.

Candidate imports execute from `/`, in memory with faithful deployment filenames,
as UID992 (API mount namespace) and UID1000 (worker), no writable bytecode, no
network/write/process side effects, no fallback project modules. The report
namespace must be absent and its parent trusted. Existing queued runs and shared/
service environments must not override reporting flags. Failed guards stop safely.

## Apply (separate authorization required)

Repeat all fresh gates twice before mutation and check equality. Create private
transaction control directory; independent inode-separated verified copies of API
environment, deployment variables, pointers and each replaced worker source, with
explicit absence records for new files. New API/static release trees preserve the
accepted runtime and all retained hashed chunks. Provision only
`/srv/powerflow/realized-performance` and its `releases/`, UID1000/GID992 mode2750,
marker UID1000/GID992 mode0640. This new derived-report namespace is the only
additional producer-writable store. The existing strict API sandbox makes it
read-only; effective API/producer access is checked without trial writes.

Install only the declared worker files, append the fixed report root to the
candidate environment, switch only staging pointers and restart only the staging
candidate API. Verify complete inventory, ownership, permissions, public API
routing/cache headers, operational consistency, anonymous Admin denial, original
live forecast selection, production preservation and rollback artifacts. Empty
report store MUST return 404 REALIZED_REPORT_MISSING, never historical fallback.

**Activate last**: PATCH only the existing deployment's job_variables by adding
POWERFLOW_REALIZED_REPORT_ENABLED=true and the fixed report root. Preserve every
other variable, schedule/concurrency/pool and policy field. No manual flow or
report generation. Journal APPLIED after verification; natural-run and browser
acceptance stay pending. Failure stops and preserves evidence; **no automatic
retry or rollback**. A separately authorized guarded rollback is available.

## Rollback

Verify exact journal, independent backups, declared source/config/pointer states,
runtime, schedule/idleness, helper, production and publication preservation.
Disable reporting by restoring only transaction-added deployment settings first,
then restore backed-up worker files/remove only verified transaction-added files,
restore exact environment and predecessor pointers. Restart candidate only when
necessary. Verify original operational/forecast endpoints and flags. Retain the
new release, journal, backups and all genuine report publications for recovery;
never delete report data or alter forecast/operational publications. Abort on
unexplained drift; no forced recovery or automatic rollback on failure.

## Post-deployment acceptance (separate authorization)

Use `accept` once after an actual terminal natural run started after activation;
no completion inferred from schedule. Correlate flow, forecast task/pipeline UUID
via existing read-only capture, committed operational evidence, and the actual
completed `Monitor next24h realized forecast errors` task. Require report generation
inside its real timing bounds, stable hash pointer, document/source hashes and
receipt/model integrity, complete observed-hour scoring, exact API metrics, UTC
timestamps and 90-minute reporting freshness. Twenty pairs overall/window, five
per horizon; insufficient samples have null metrics, not zeros. Missing/failed/
invalid reports remain explicit, no historical fallback. Insufficient verified
sample can pass report-delivery acceptance, never predictive-quality acceptance.

Owner-assisted React desktop/mobile: Forecast Intelligence report, dated MAE/
RMSE/bias in EUR/MWh, pair counts, horizon/time-window thresholds, provenance,
exports, refresh/resume stale transition; missing/failed/stale/insufficient states
must be honest. Verify accepted Overview/Pipeline operational and live-forecast
behavior remains consistent without reopening completed investigations. Synthetic
failure-state coverage is offline only; do not manufacture live failures.

Admin MFA BLOCKED pending least-privilege AWS access; genuine Analyst 403 PENDING
(browser investigation closed). No AWS, token/secret retrieval or browser workaround.

## Future commands (NOT executed)

`venv/bin/python -I -B deploy/staging/realized-performance-release-v1/run.py preflight --manifest-sha256 <exact-reviewed-manifest>`

The same runner has separately authorized `apply`, `rollback` and `accept` modes.
`--local-check` verifies hashes/pins only, makes zero connections. Manifest/payload
assembly refuses to overwrite any different existing immutable output. Retain the
private frontend build directory as an integrity-bound local prerequisite.
