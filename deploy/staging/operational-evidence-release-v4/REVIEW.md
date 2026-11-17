# Operational evidence release v4 — local preparation, not execution authority

Release: phase-operational-evidence-20261107-v4.
Transaction: 321a9d8a1d7a483d923b84bc1917b0a9.
Separate explicit authorization is required for each remote preflight, apply,
rollback or acceptance action. No remote operation was performed during preparation.
No automatic deployment retry or rollback. Original v1/v2/v3 and historical packages,
manifests, transaction records and captures remain unchanged.

## Correct historical baseline

baseline.py reads the exact private transaction-record.json whose approved SHA-256
is b37d5e173ab58a1690f9fee22c3a40d4dbb346427326772934617771fbac3e11.
It verifies exact bytes BEFORE interpreting the record, rejects duplicate JSON keys,
and verifies the completed original transaction f2f195174eda43daa8e5593087fbe1d3,
destination and pinned original predecessor identity. The approved 37-file static
release is independently bound by release-manifest SHA-256
dc2fd9aa9cb0e961fd3859aa63b946a307c43f8a31ed6d8ac0ef4529c32f2045.
All its locally archived file hashes are reverified. The 31 retained mappings are
derived from that record, not from observed host hashes. Six overlapping hashes
must agree, yielding exactly 62 sorted POSIX-relative entries. No unsupported
forecast-consistency archive is used. BASELINE.json is the sanitized projection;
the raw record remains private and Git-ignored. Changed/missing evidence fails closed.

The fresh frontend is built once into the new private candidate. The scheduled
pipeline, operational helper and API source are unchanged from the prior reviewed
implementation. Old hashed chunks remain accessible to existing browser tabs:
the apply copies every historically bound js/css/woff2 asset from the existing
immutable static release to the NEW tree, checking bytes against its historical
hash, root ownership/mode0644 and no-follow ancestry before any destination write.
No download or rebuild of old assets is needed. For 25 retained assets whose local
bytes/size are unavailable, the manifest states bytes=null and max_bytes=2000000;
it does NOT invent sizes. Capacity reserves that upper bound. The source tree has
an additional aggregate <8 MiB/160-file inventory bound in preflight. Every copy
reference is exact-root/exact-relative-path/hash validated; conflicts, traversal,
duplicate destinations or unverified mappings fail. Payloads carry only new local
bytes, never placeholder bytes for remote-copy entries. Runtime file hashes remain
mandatory, including copies. Original deployed trees are never written.

## Installation scope and activation

MANIFEST.json lists every source, destination, hash, UID/GID and mode. New immutable
API/static release trees are root-owned0755/0644. Reuse only the verified existing
API venv; install no dependencies. API clones the approved API release and overlays
the reviewed operational routes/selector/store and existing market sampling code.
The original API lock and forecast selector/expiry implementation remain unchanged.

Production worker scope: src/scheduled_pipeline.py, new
src/shared/operational_terminal.py and src/shared/operational_evidence.py,1000:1000/0644.
Operational root helper: /opt/powerflow/operational-evidence-v1, root-owned0700
directories/0600 files, exact seven-file code closure plus TOOLS.json. Launcher0755
and restricted hash-bound sudo rule0440 permit only anchored flow/state UUID args.
No unrestricted sudo or worker-writable elevated code. No shared .env edit.

Provision only /srv/powerflow/operational-publications and releases root:9920750,
contract marker root:9920640. No pointer or operational publication is manufactured.
Require absence before installation; do not adopt unexpected paths. Append only
POWERFLOW_OPERATIONAL_PUBLICATION_ROOT to the exact candidate API env baseline.
Switch staging pointers and restart ONLY the candidate API, once. Readiness checks
are bounded observations, not restart retries. No worker/Streamlit/production API
restart or routing edit. Operational delivery remains absent/disabled throughout
installation and candidate acceptance. The FINAL step sets only
POWERFLOW_OPERATIONAL_EVIDENCE_ENABLED=true in the existing Prefect deployment's
job_variables.env, preserving automatic forecast publication=true, schedule,
concurrency and all other variables. No manual flow, inference or publication.

## Fresh gates and execution bounds

The separate read-only preflight excludes transaction code and all mutation
functions. Verify pinned SSH identity/host key, root/Linux/x86_64, procfs/NOATIME,
UID/GID, filesystem paths/metadata, old pointers/API inventory, corrected 62-file
static inventory AND original historical record hash. Verify original forecast
tools/launcher/rule, A03 parser, frozen model/contract and existing forecast state.
Verify reviewed Prefect3.7.5 worker/engine source hashes and process-pool env
semantics; no queued/worker/shared-env flag overrides. Require zero active runs,
engines/helper processes/occupied slots, hourly :45UTC schedule/concurrency1 and
strictly >600s before every relevant execution. Check capacity, service isolation,
candidate runtime/import closure, API env, routing and health, sudo syntax and backup
prerequisites. Missing operational-root effective access is explicitly deferred
until provisioning. No AWS, credentials, source queries or writable execution DB.

One pinned connection per action, no retry. Preflight/accept remote90s/local150s;
apply/rollback remote120s/local180s; TERM escalation5s. Output and captures bounded;
local private evidence0700/0600. --local-check never connects. All hashes, immutable
source closure, retained private archives and raw historical record are verified
before any SSH. A missing local prerequisite stops rather than refreshing hashes.

## Backups, failure and rollback

Apply repeats fresh gates before mutation. Create independent private transaction
backups with distinct inodes, verified hashes/metadata, pointers and deployment
variables before installation. Record BACKUP/INSTALL/POINTERS/ACTIVATE/APPLIED phases.
Stop on drift or failed acceptance without retry/automatic rollback. If backup fails
before the journal exists, retain private evidence; do not infer rollback eligibility.

Separately authorized rollback checks the journal, both backup copies, permissible
old/new installed bytes/pointers, unchanged immutable releases/runtime, idle window
and preservation FIRST. Disable operational delivery by restoring original deployment
variables, restore original worker bytes/metadata/API env/pointers, restart candidate
only, remove only exact new worker/launcher/sudo-rule files. Retain new immutable
helper/API/static trees and operational store/publications as disabled evidence;
never delete forecast artifacts. Fresh forecast preservation allows legitimate newer
natural publications since apply; unexpected unrelated drift still blocks rollback.

## Acceptance and local validation boundary

The read-only accept action requires a completed genuinely natural post-activation
run and stable Prefect/task/internal UUID association. Reconstruct persisted terminal
execution/inference/delivery evidence, verify operational pointer/hash/freshness,
public/Pipeline equality/no-store and no October26 fallback. Verify live forecast
independently as valid200/24 actual targets or503 FORECAST_WITHHELD with matching
Operations state. PUBLISHED is not evidence of current eligibility after expiry.
Anonymous Admin rejection/same-source projection are machine checked; actual
authenticated Admin/Analyst and React Overview/Pipeline browser acceptance remain
owner-assisted and must not be claimed from backend fixtures. No manufactured run.

Offline tests use fixtures/mocks and temporary local files only. Linux ownership,
procfs, systemd/sudo, effective namespace access and genuine natural-run capture
remain fresh remote gates; macOS tests do not certify them. Historical source-hash
assertions remain unchanged and fail closed against the intentionally updated worker.
No deployment, activation or presentation-readiness claim follows from local tests.


## Independently verified Prefect compatibility correction

The one authorized read-only inspection observed Prefect3.7.5 in the fixed worker
.venv-prod installation. workers/base.py is unchanged from approved3.7.2;
flow_engine.py and METADATA match the independently downloaded official PyPI3.7.5
wheel exactly. This is a version difference, not evidence of modified inspected
files. Timing/actor of the dependency update is unknown and no other installed
Prefect files were inspected or attested. No version is accepted from host metadata
alone; the originalv2 remains blocked and its manifests are unchanged.

prefect_reference.py verifies the complete14,766,992-byte wheel against public
PyPI SHA-256 214837b7cb1e10f8fec59018253cd8ef65c8b394b7df29c511b645b0ff5e4478,
then verifies wheel RECORD entries for the two sources and METADATA. The wheel is
kept in ignored private local evidence and never installed/imported. Its safe
public projection is PREFECT-REFERENCE.json, bound in this release manifest.

The independent source diff contains only two additions marking subflow tracking
tasks; synchronous and asynchronous set_state/call_hooks ASTs are identical to
approved3.7.2. In each, propose_state precedes call_hooks, so the helper continues
reading authoritative terminal execution evidence, never inventing hook timestamps.
The entire worker-base file is byte-identical, preserving reviewed job_variables.env
merge/override behavior. Python compatibility remains3.10<=worker<3.15 (worker3.14.7);
systemPython3.9 is bootstrap-only and does not import Prefect.

New preflight requires both exact3.7.5 source hashes AND exact distribution METADATA
hash at the fixed package path; no fallback version or hash refresh exists. Failures
now distinguish PREFECT_WORKER_BASE_DRIFT, PREFECT_FLOW_ENGINE_DRIFT and
PREFECT_METADATA_DRIFT. Other guards, permissions, privileges, forecast validation,
transaction timeouts and activate-last behavior are unchanged. The previously built
API/static candidate bytes are reused after verifying every hash, with no frontend
or API source change, rebuild, dependency installation or remote operation.


## Minimal HTTP import correction

The authorized v3 diagnostic identified AttributeError in pool() at line181.
The module-level def http(...) overwrote the imported http package. The same
collision affects the HTTPS helper. V4 changes only the preflight import to
`import http.client as http_client` and its two constructor references. The public
http helper name, request allowlist, loopback routing, TLS context, timeouts,
response bounds, process-pool environment checks and all other guards are unchanged.
The old failure is reproduced offline; both corrected paths are exercised using
mocked transports, including policy rejection. No host state is accepted to bypass
this defect and no remote operation occurred during preparation.

New release identity, transaction, manifest and payloads are separate from v3.
All128 destination file hashes and candidate bytes are unchanged from v3; no API,
frontend, pipeline, privilege or publication implementation changes. No frontend
rebuild or dependency installation. Historical records and original release files
remain immutable. New manifest binds this review and all v4 source/tests.

Validation: 633 selected Python tests passed, including all69 v4 cases. The one
unchanged historical automation-source integrity assertion is excluded from this
functional aggregate because its old manifest rejects the intentionally changed
pipeline bytes; no v4 integrity failure is deselected. Python3.9 grammar, local
Python3.14.7 execution, all four payloads, candidate compatibility, original-release
immutability and pinned local profile verification passed. API/frontend bytes are
unchanged; their previously passing tests/build are not represented as new browser
or remote acceptance. No remote operation occurred during preparation.
