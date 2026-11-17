# First automatic-publication acceptance — LOCAL PREPARATION ONLY

No remote inspection/deployment/publication is authorized by this package.
This is a focused companion to inference-evidence-validation/inspect-template.py;
old inspectors, deployment transactions and original manifests are unchanged.

## Correlation and fail-closed interpretation

Select at most20 COMPLETED auto_scheduled runs of the exact existing deployment,
with scheduled :45 UTC timestamps and start/schedule after2026-11-03T14:56:20.355989Z.
This is the successful apply's local evidence timestamp, a conservative lower bound;
it is not fabricated as the exact remote activation timestamp. Re-read the chosen
flow; require an unchanged record, canonical IDs, completed forecast/publication
tasks and intervals contained in that flow. Never equate Prefect UUID, internal
PowerFlow UUID or inference UUID. Do not fall back to pre-activation/manual runs.

Map the unique Next24h forecast generation SQLite stage within2seconds of the
exact forecast task (existing reviewed association tolerance). Match that INTERNAL
run ID to exactly one successful pipeline_runs record in the flow interval. Read
ONLY next24h_publication_status, generated/status/issue metadata; never print raw
messages, storage configuration or credentials. Match issue, unique task-bracketed
receipt, full reciprocal receipt hashes, persisted history and active bundle hash.
Recheck deployed pipeline/delivery source hashes from the successful activation
manifest. A feature flag, COMPLETED task or active pointer alone never proves PUBLISHED.

Supported raw delivery values are exactly the deployed worker set: PUBLISHED,
SKIPPED_WITHHELD, SKIPPED_EXPIRED, SKIPPED_DUPLICATE, REJECTED_OLDER_ISSUE, DISABLED,
REJECTED_INFERENCE, FAILED. Missing and unknown values are explicit gaps; there is
no invented generic SKIPPED/WITHHELD outcome. Do not infer a receipt for withholding.
An unchanged older active bundle after a skipped/failed delivery is PARTIAL, not a
false PUBLISHED claim or deployment failure. A PUBLISHED outcome with a different
active receipt/bundle fails the association check. Missing receipt/publication
evidence stops dependent checks and reports them as unverified, never successful.

## Reused code and executable closure

run.py retains every hash/size-verified dependency before assembly or execution.
The manifest pins the successful53fcc9... activation manifest and exact installed
pipeline, delivery and automation-validator source hashes. It binds its own sources,
review/tests, existing trusted preflight core/pinned SSH wrapper, read-only publication
diagnostic, original contract/builder/automatic sources and database schema/store
source for review. No installed application module is imported/deserialized.

Only imports + build() are AST-extracted from prepare.py; its CLI/main/file writer
is absent. Only imports + require/stamp/capture/persisted are extracted from
automatic.py; deliver/tools/query/publisher entrypoints are absent. Held receipt
bytes replace safe_file during the IN-MEMORY builder call. sys.modules temporarily
contains the held contract for its import, then previous entries are restored.
Publication diagnostic/metadata and contract are reused, not reimplemented.
No publish.py code, publisher lock, publish verify CLI or deployment job is executed.

The unchanged contract verifies schema-v1 ordered31 features/values, source
completeness, exact frozen model/contract hashes, authentic reciprocal receipt
bindings and24 finite aligned UTC predictions. The same builder creates expected
bundle BYTES IN MEMORY ONLY, compared byte-for-byte by SHA with the active bundle.
For an expired receipt, full original validation runs at actual UTC; only its
ExpiredPublication exception is classified separately after structural validation.
Nothing is backdated, published or treated as eligible following expiry.

## Read-only IO and bounds

- Fixed production receipt/history paths and exact deployment only. At most512
  receipt entries, five allowlisted files/100KB each; history64MB/1million rows.
- Descriptor-anchored O_NOFOLLOW ancestor and file reads; symlinks/unsafe ownership,
  receipt permissions, path escapes, changed files and ambiguous identities fail.
- SQLite: only fixed pipeline_runs/pipeline_stage_timings SELECTs; descriptor-anchored
  /proc/self/fd URI with mode=ro&immutable=1, query_only, SELECT/table/function
  authorizer, progress budget and bounded rows/messages. Reject nonempty journals
  (including WAL/SHM), symlinks and before/after database identity/metadata drift.
  Never use immutable mode to ignore a live journal or import store_data.
- Existing read-only publication diagnostic checks root:9920750 directories,
  current->releases/<sha>/bundle.json, root:9920640 file, full hash/contract and
  pointer stability. Match receipt UUID via execution.run_id and exact bundle bytes.
- Exactly two fixed anonymous GET routes through staging HTTPS with trusted CA/SNI:
  /api/forecast/next24 (5seconds), /api/operations/summary (10seconds).
  No proxy, redirect-following, tokens or Admin endpoint. JSON body262144bytes max.
- API200 must match all24 values/horizons/model/UTC timestamps and publication
  issue/expiry/completed_at. Exact no-store directive, case-insensitive header name.
  API503 must have the exact FORECAST_WITHHELD contract; expiry is classified,
  not reported as deployment failure. Unexpected eligible withholding fails acceptance.
  Operations VALID/EXPIRED must agree; valid reason must name matching issue/cutoff.
  Pointer recheck follows both requests; switches or expiry boundaries preclude PASS.
- One SSH attempt; pinned profile/destination/host key and identity metadata via
  unchanged reviewed wrapper. -F /dev/null, strict host keys, no agent/forwarding,
  BatchMode, ConnectTimeout10, ConnectionAttempts1. Fixed sudo -n command only.
  Trusted system Python -I -S -B: no startup hooks/candidate/third-party imports.
  Remote90seconds/local150seconds, TERM/KILL5seconds; no retries.
- Only LOCAL private evidence is written: existing ignored evidence root,
  directory0700/files0600. stdout/stderr each bounded65536bytes; allowlisted
  report32768bytes. Remote stdout has IDs, times, statuses, hashes and safe codes,
  never raw vectors/data/messages/headers/paths/exceptions. Error paths redact.
  Ordinary SSH/sudo/HTTP access logging may occur during future authorized reads.

## Timing and assurance limits

Exact publication timestamp is NOT persisted by the deployed pipeline/publisher.
Do not reinterpret inference completed_at, bundle mtime, task completion or pointer
mtime as publication time. For an associated PUBLISHED result, report the completed
publication task's start/end interval, signed publication-minus-FLOW-completion
latency bounds (normally negative: publication happens before flow completion),
and expiry-minus-publication bounds. If the task crosses expiry, timing is
UNVERIFIED; inspection crossing expiry is PARTIAL rather than false success.

The current public API intentionally lacks receipt/bundle UUID/hash fields.
API association is all24 values + model + issue + expiry + execution completion,
with the validated active pointer unchanged around readback. Operations exposes
status/reason, not bundle UUID; same-issue/cutoff and stable pointer are the available
binding. These limitations are explicit; no API/data-contract change is needed.
Root/producer and existing Prefect are trust boundaries; metadata cannot prove the
absence of all manual root activity. This inspector never performs such activity.
Duplicate/older protections remain existing publisher tests, not a live write test.

PASS means the inspected natural run actually PUBLISHED a matching, currently valid
bundle and both public APIs agree. PARTIAL identifies expiry, skipped/missing
receipt/outcome/publication evidence; FAILED means an observed mismatch/invalid
contract; BLOCKED means no completed eligible natural run. Browser acceptance is
ALWAYS PENDING_BROWSER, even for PASS; it requires separately authorized Chrome
navigation, chart/table/provenance/value checks and observed expiry behavior.
No continuous polling or waiting is built in. A pass is point-in-time evidence.

## Local build, verification and future invocation

    venv/bin/python -I -B deploy/staging/forecast-publication/automatic-acceptance/build.py

This creates ONLY the new local MANIFEST.json. Review its exact hash, payload,
runner and source hashes. The original successful deployment package is not rebuilt.

Future command, NOT executed remotely during preparation:

    venv/bin/python -I -B deploy/staging/forecast-publication/automatic-acceptance/run.py --manifest-sha256 <APPROVED_NEW_MANIFEST_SHA256>

Append --local-check for dependency/hash/pinned-profile verification without SSH.
Requires separate authorization for one execution after a natural run completes.
Do not invoke the publisher, synthesize a run or change policies to make acceptance
pass. Non-PASS returns exit1 with a sanitized structured report; transport failure
has no interpreted acceptance report and is never retried.

Tests use synthetic fixtures and isolated local SQLite. macOS SQLite tests map the
Linux /proc/fd URI to an already isolated fixture read-only URI while asserting the
exact requested URI/mode; descriptor semantics on Linux remain unverified locally.
Linux/root UID metadata is simulated only where required; real no-follow symlink
rejection and file stability are tested natively. Python3.9 grammar is checked;
this does not claim an unavailable Python3.9/Linux runtime or live acceptance.

Local results:514 selected backend, deployment, publication, inference-evidence,
source-consistency, authorization and diagnostic tests passed, including55 focused
acceptance cases. Synthetic/mocked tests do not establish production publication,
actual staging availability or browser acceptance. Python3.9 grammar/compilation
is checked for13 manifest-bound Python files, both extracted helper blocks and
the assembled payload, using the available Python3.14.7 runtime. Manifest closure,
successful deployment closure preservation, whitespace and --local-check must pass.
No original manifest, installed release, model or successful transaction is modified.
