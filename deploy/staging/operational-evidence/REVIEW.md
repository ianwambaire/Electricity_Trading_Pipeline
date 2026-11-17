# Terminal operational evidence — checkpoint 3 (LOCAL ONLY)

No execution or installation authorization. Nothing in this directory provisions
paths, installs sudoers, changes deployment variables, schedules work or activates
delivery. The generated launcher/rule/TOOLS.json are code-only review artifacts.
Do not execute the launcher from the checkout or reuse old deployment approvals.

## Actual lifecycle and integration

Reviewed installed local Prefect 3.7.2 flow_engine.py SHA-256:
`bf8fa8953752b9cbb16297db92f8de51a94e0c57c6d2df7a9d0d2a9039fc1548`.
Both sync and async set_state propose the state to the server before calling
hooks, and update local state fields without refreshing local end_time. Therefore
hook argument end_time is not an authoritative completion timestamp. The helper
re-reads that exact flow from Prefect and requires a persisted terminal state ID,
actual start/end timestamps, approved deployment and natural auto_scheduled flag.
No timestamp is derived from callback time or inferred from a successful return.

The existing flow decorator now registers the same isolated wrapper for
on_completion and on_failure. It is disabled unless
POWERFLOW_OPERATIONAL_EVIDENCE_ENABLED=true. No new scheduler, Prefect run, worker
service or retry is introduced. Cancellation/crash hooks are not registered: they
are engine-dependent and may run before terminal durability. Forced termination,
worker loss and failures before durable pipeline metadata remain explicit capture
gaps; no run history or success is fabricated for them.

The pipeline's flow context contributes prefect_flow_run_id and deployment ID to
its existing JSON summary. The forecast task contributes its authoritative task
context UUID to the existing result; the pipeline persists that ID and its explicit
committed inference receipt ID in the same summary. No SQLite columns or schema
change. The summary writer explicitly commits/closes; the stage writer commits through
its transaction context. Total pipeline is committed in finally before terminal
state proposal (connection closure is not used as the durability proof). A very early
failure outside that persistence path cannot be joined and capture fails closed.

## Identity, timing, retry and concurrency

The two-second temporal join was not justified as a universal guarantee: the stage
wrapper starts BEFORE invoking the Prefect task, so task queueing and retries can
make stage/task boundaries differ by more than two seconds. Live terminal capture
requires stable_identity=True. It joins the flow UUID in exactly one persisted
summary, internal UUID, and persisted forecast task ID, then validates the unique
stage and enclosing intervals. No expanded proximity tolerance is used. Old
inspection callers retain the existing legacy branch; terminal delivery NEVER uses
it or silently upgrades older summaries without stable IDs.

Generated/withheld task results must match the persisted task UUID. A failed task
without a returned result may be associated only through its unique failed/crashed
task within the same authenticated flow plus the stable flow/internal summary;
missing inference details stay UNKNOWN. Task retries with a unique final task ID,
valid enclosing stage and final committed receipt are supported. Flow retries
(run_count > 1), duplicate tasks/stages/summaries, overlapping conflicting IDs or
missing times fail closed. Timestamp precision/order conflicts are rejected;
format-equivalent UTC values are accepted. There is no SQL migration.

Source capture uses one exact flow GET, one read-only task filter POST, and a final
flow recheck. Origin is fixed loopback Prefect http://127.0.0.1:4200, matching the
existing reviewed local deployment. No proxies, auth lookup, redirects, arbitrary
methods, endpoint, query, request body or external hosts. Each connection has a
3s timeout; HTTP bodies are bounded1MB and duplicate/nonfinite JSON is rejected.
There is no polling/retry and no state/deployment update request.

Only the fixed production SQLite and explicitly named committed receipt directory
are read. Descriptor-anchored no-follow access, owner/mode/size checks, O_NOATIME,
read-only immutable SQLite, absent/empty journal gates and unchanged inode/metadata
checks surround capture. SQLite authorizer permits only the three required tables,
SELECT, query_only read and substr. Extension loading is explicitly disabled where
the trusted Python build supports it; SQL functions other than substr are denied
regardless. Source summary and association queries have progress budgets; the
launcher provides the outer wall-clock deadline. Receipts require exactly five
regular private files with reciprocal hashes and frozen31-feature/24-target checks.
No directory scanning for alternate/older receipts; absence is a failure.

Concurrent writes/journals cause explicit rejection rather than an unsafe immutable
read. The final state recheck rejects retry/state changes during capture. Delayed
persistence produces capture failure with no automatic retry or older fallback.
No forecast API/pointer selection is used to infer operational status. Historical
PUBLISHED remains distinct from current forecast eligibility. Exact publication
time remains null because the existing publisher does not persist it.

## Privilege and immutable dependency boundary

Worker notification accepts only flow/state UUIDs, passes no evidence, SQL, root,
path or arbitrary command; stdin is closed. It invokes one fixed sudo executable
with public-key/SSH entirely out of scope. Child env is PATH=/usr/bin:/bin, output
bounded16KiB, worker deadline40s and bounded termination escalation. Errors are
fixed sanitized categories, never stderr or exception text. The hook logs its
independent outcome and never changes the flow state, inference or forecast status.

Proposed installed launcher: /usr/local/sbin/powerflow-publish-operations,
root-owned0755, hash-bound NOSETENV sudo rule with anchored UUID argument regex.
No unrestricted sudo or shell command arguments. It clears the environment and
runs fixed /usr/bin/timeout (30s plus5s escalation), /usr/bin/python3 -I -S -B and
/opt/powerflow/operational-evidence-v1/bootstrap.py. This versioned root-owned code
closure is separate from worker-writable source and existing forecast tools.
Bootstrap checks every ancestor for root ownership/no writable group/world/no
symlinks, verifies the exact seven-file closure against root-owned TOOLS.json,
then imports only the verified bytes in a fresh isolated process. No worker path,
SDK, model or application module is imported with root privileges.

TOOLS.json is a local code integrity inventory, not a deployment manifest or proof
of installation/authorization. A future guarded transaction must pin its exact hash,
launcher, sudo rule, worker source closure, trusted OS Python/SQLite runtime and
actual installed Prefect semantics BEFORE installation. No general installer or
new deployment framework is added here. Linux visudo syntax/regex compatibility
and actual sudo invocation remain untested locally; no real sudo was executed.

## Store and independent failure behavior

Only /srv/powerflow/operational-publications is writable through the installed CLI.
Root and releases must already be root:9920750 with the operational contract marker;
all store ancestors must be root-owned and non-writable by the worker. Candidate
API UID/GID992 receives read/traverse only. Provisioning and service mount namespace
verification require separate authorization. No automatic mkdir/chmod/chown repair.
The forecast store and original historical snapshot are never delivery targets.

publish_terminal makes schedule ordering, same-run identity/content and duplicate
checks under the existing lock. Identical terminal payloads ignore a later observation
time and return SKIPPED_DUPLICATE without pointer/release/age renewal. Older slots
return SKIPPED_OLDER_RUN. Conflicting same-slot/run data fails; newer fresh evidence
uses immutable release activation and retains previous bytes for explicit recovery.
Current readers still get a pinned complete old/new publication, and public/Admin
projections use existing guards. Operational90-minute freshness is unchanged.

Capture failures return FAILED/CAPTURE_UNVERIFIED and do not invoke the store.
Store failures return FAILED/OPERATIONAL_STORE_UNCERTAIN: activation might have
occurred before a sync error, so never automatically retry/clean up/restore. Retained
releases and an independently inspected current hash support the existing explicit
freshness-checked recovery primitive, which is NOT exposed by this launcher.
A failed scheduled flow remains failed even if operational evidence is delivered;
a successful flow is not rewritten as failed when this independent hook fails.

## Validation and old binding boundary

Tests use synthetic source records, temporary SQLite/files and mocked Prefect HTTP
only. No Prefect engine/flow execution, source request, SSH, sudo or live publication.
Linux /proc descriptor opening is mapped to an isolated immutable fixture URI on
macOS: this tests query/association/permissions logic, NOT production procfs/NOATIME,
root:992 access or Linux durability. Python3.9 grammar is checked, not executed;
worker runtime is Python3.14.7 locally. Real installed runtime compatibility remains
a deployment precondition.

The original automation source-manifest assertion now fails on the intentionally
changed scheduled_pipeline.py bytes. It and the original manifest remain unchanged;
DO NOT refresh them. The historical installed forecast-tool closure is unchanged.
A new regression confirms the old continuation-v2 verifier rejects the new source
at artifact_hash before any remote capability. The final functional run explicitly
excludes only test_automation_source_manifest_and_installed_closure_are_exact; its
previous observed failure is reported as the remaining deployment-binding blocker.
A fresh reviewed deployment package is required before these sources can be deployed.

Final local results: 48 focused terminal cases passed; 417 selected functional
regression cases passed with the one explicitly named historical source-manifest
assertion deselected. Its initial failure was retained as a known binding blocker,
not fixed/waived in the original test or manifest. Negative old-runner hash rejection
passed. Seven-file TOOLS.json, launcher and sudo rule regeneration matched exactly.
TOOLS.json SHA-256: 0f1c16bb3acb0ef0fdfc6d5b5309b640b5f101dcedd3eaf32f29d12524005c4e.
No actual OS privilege, sudoers installation, server request or Prefect run was used.
