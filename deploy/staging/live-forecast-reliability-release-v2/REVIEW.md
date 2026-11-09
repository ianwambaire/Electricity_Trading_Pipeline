# Guarded Live Forecast Reliability staging release V2

Release: `phase-live-forecast-reliability-20261107-v2`.
Transaction: `565437b5103a45d3b6192ecd70498f78`.
Local preparation only; **execution_authorized=false**. Each remote preflight,
apply, acceptance or rollback requires separate explicit authorization. The runner
never chains actions or automatically rolls back/retries.

V2 corrects only the import probe's module layout. V1 manifest
`e184215a3959c61dbd41e66e47a78af7951c90bb903d30f4ebb6a2d28ee6aa19`
and its failed evidence remain unchanged. Every API/static payload and retained
asset binding is required to equal V1 byte-for-byte. Only release destinations,
transaction identity, probe metadata and regression tests change.

The old loader assigned `<verified-candidate>` to every __file__, so application
`Path(__file__).resolve().parents[2]` failed from the real supervisor cwd `/`.
The new loader assigns each module its exact future absolute candidate source
path, sets spec.origin/has_location and package __path__/search locations, and
compiles the same approved bytes under that path without writing source files.
The probe asserts that api.app.PROJECT_ROOT resolves to the candidate API root.
Tests run from `/`, including reproduction of the original IndexError. Linux
UID/GID behavior remains simulated offline and must pass the real preflight.

## Exact baseline and scope

Verified immutable parents: operational-evidence V5 manifest
`cdd828defc52ea258852b88aa852d1d470ca915d098021d6ff8fd2be9b05223b` and
operational capture helper V2 manifest
`c677691a8e75e2ae09fb9eea8f60aefe1b71fcdc5e289109ed649b4b1f3b4262`.
Parent runners, payloads, original release bytes and dependency bindings are
reverified locally before every action. Actual installed state must still pass
fresh Linux preflight; local assembly is not a claim of host compatibility.

Only four API files differ from V5: `api/app.py`, `api/forecast_source.py`,
`api/operations_summary.py`, and new `shared/forecast_availability.py` (under src).
Every other API file comes from exact V5 release bytes. The new staging-origin
React build preserves V5's exact public authentication build configuration and
same-origin API base. All V5 hashed assets are retained by approved source/hash,
with collisions rejected; no unsupported historical archive supplies a baseline.

Apply writes only a new versioned API tree, new static tree, this transaction's
private journal/backups, and the two existing staging symlink pointers. It then
restarts only `powerflow-candidate-api.service`. It does not modify Nginx, API env,
sudo rules, launchers, existing releases, worker code, Prefect deployments/schedule,
flags, authentication, datasets, model/feature contracts or publication stores.
Existing operational and automatic forecast delivery remain enabled unchanged.

## Preflight, Linux compatibility and privilege boundary

The preflight payload excludes apply/rollback/publisher/terminal-hook entrypoints.
It reuses the reviewed pinned SSH connection and read-only V5/helper guard closure.
It checks actual idleness and the existing strictly >600-second scheduling window,
capacity, source/model/publisher/helper hashes, service sandboxes, procfs, Nginx and
API routing, unchanged operational store, V5 APPLIED journal, helper V2 APPLIED
journal and independent backups, environment hash and enabled delivery flags.

The API venv must match the V5-recorded complete dependency/executable closure.
Linux Python 3.14.7 candidate imports execute as UID/GID 992, no-new-privs, in the
existing API mount namespace, with `-I -B`, clean supervisor environment and
in-memory source loader. An audit guard rejects network connections, subprocesses
and filesystem writes during that probe. The bootstrap/payload grammar supports
Python 3.9; actual Linux identity/procfs/mount behavior is deferred to preflight.
No SDK, dependency installation or new privileged publication capability is added.

Execution limits: one SSH connection per action; remote 90 seconds for preflight
or acceptance, 120 for apply/rollback; local 150/180 seconds respectively; five-second
TERM/KILL escalation. Output is bounded/sanitized, detailed evidence private 0600.
The candidate startup check has bounded read-only readiness observations, not a
repeat install/restart or deployment retry.

## Apply and rollback readiness

Fresh guards run twice before any mutation. The old code/static trees remain
immutable and verified. Two independently written, inode-distinct 0600 backups
record the exact previous staging pointer targets. These are pointer backups,
not duplicate API trees or credentials. The prior trees are the verified rollback
content; unexpected old-tree drift is a stop, never overwritten from a guess.

Installation uses exclusive immutable files, explicit root ownership/modes,
fsync and post-write hashes. New root inode identities are journaled. Import,
preservation, backups and idle guards pass before pointers change. After the single
candidate restart, pointer/routing/runtime/sandbox checks, new API policy/value
readback, operational consistency and production/publication preservation must pass.
Failure leaves evidence and exact phase, without automatic rollback or cleanup.

Independently authorized rollback validates journal/binding, both backups, all
partial/new file hashes and creation identity, both old trees, current pointers,
idle window and preservation state before restoring only the two old pointers.
It restarts the candidate API only if the API pointer had changed. Natural forecast
and operational publications may advance between deployment and rollback; their
then-current bytes/pointers are preserved, never restored to a historical snapshot.
Versioned new trees and evidence remain for investigation. Any unexpected drift
stops rollback before mutation. A broken/missing journal or backup is not bypassed.

## Availability policy and acceptance

The privileged publisher's original validator remains byte-identical, with its
three-hour issue-age admission and duplicate/older issue controls. The API adapter
reuses full validation at actual UTC; only typed admission-age expiry, classified
after integrity checks, can enter the separate remaining-horizon rule. Completion
after issue+3h is rejected. Nothing backdates validation or resets the deadline.

An already admitted current bundle is available only before issue+24h. API metadata
attests `ISSUE_HORIZON_V1`, expiry issue+24h and refresh due issue+3h. All 24 original
rows/horizons remain intact; elapsed targets are reference-only and the UI labels
an older issue refresh-delayed. This is not a new 24 hours after reading or a claim
of equal accuracy to a freshly issued forecast. At the final target the API withholds
with 503/no-store and Operations EXPIRED. Missing, unsafe or corrupt bundles never
fall back to a historical CSV/release. Operational evidence's 90-minute rule stays.

Post-apply readback may legitimately observe 503 if no eligible forecast exists;
it is not a failed deployment by itself. Separately authorized read-only `accept`
checks current bundle/HTTP values/model/timestamps/pointer and operational agreement,
then actual post-activation natural Prefect terminal state and persisted association
through the reviewed read-only capture subset and V2 timestamp correction. It never
triggers a run, hook, inference or publication. No natural run is inferred from time.

Required genuine acceptance remains: a natural eligible run and PUBLISHED receipt;
24 matching finite aligned predictions; HTTP 200/no-store and matching Operations;
availability beyond the old issue+3h cutoff marked refresh-delayed; newer eligible
issue replaces it; issue+24h gives 503/EXPIRED. Do not manufacture these with a manual
run/publication, altered time or synthetic staging data.

Owner-assisted real React acceptance must cover Overview, Forecast Intelligence
and Pipeline/Admin Operations at desktop 1440x900 and mobile 390x844: matching issue,
completion/expiry, model, values, future/elapsed table/chart labels, delayed refresh,
expiry after suspended-tab focus, no historical-as-live data or contradictory
statuses, navigation, console/network errors and role separation. Authenticated
Analyst `/api/admin/operations/current` HTTP 403 acceptance stays **PENDING**; this
package does not reopen DevTools testing or declare that check passed.

## Historical failure and command pattern

The old automation-source manifest pins `scheduled_pipeline.py` before the V5 hook
integration. The current bytes equal the immutable V5 worker binding, as regression
tested; this release does not touch that file, historical manifest or assertion.
Installed original publisher tools still match all original hashes. The pre-existing
broad-suite failure is reported, not deselected, suppressed or refreshed.

After separate authorization only:
`venv/bin/python -I -B deploy/staging/live-forecast-reliability-release-v1/run.py ACTION --manifest-sha256 APPROVED_SHA256`.
Actions are `preflight`, `apply`, `accept`, `rollback`. `--local-check` verifies
assembly/identity bindings without SSH; it does not confer remote authorization.
The final report supplies the exact manifest SHA and proposed preflight command.
