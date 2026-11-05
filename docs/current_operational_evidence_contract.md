# Current operational evidence — checkpoint 1

Status: checkpoint 1 contract plus checkpoint 2 local association/API/React integration.
No live producer activation, privilege rule, deployment package or authorization is introduced here. Existing
forecast validators, expiry, automatic delivery and immutable releases are unchanged.
The two new modules use only Python's standard library (Unix store uses flock).

## Source review and boundary

The existing snapshot publisher explicitly labels its operational SQLite cutoff
2026-10-26T02:22Z. APISettings.from_root reads that published DB for
operations_summary, _latest_pipeline_status and admin_operations. The active
forecast selector independently validates the next24 publication and overlays
forecast availability. Existing forecast delivery passes a committed receipt and
natural flow identity to a restricted publisher; its status is persisted in the
pipeline summary. Reuse that lifecycle and controlled immutable-store architecture,
not another scheduler, a database mount, or an arbitrary report copier.

## Version 1 wire schema

All keys below are mandatory; nullable values are explicit JSON nulls. Unknown
keys, raw exception strings, logs, credentials, filesystem paths, market values,
arbitrary metadata, duplicate JSON keys and nonfinite JSON are rejected. Maximum
UTF-8 document size: 16 KiB. Content SHA-256 is supplied by the release path and
verified before consumption. Integrity hashes are not signatures or proof of origin;
a trusted producer and protected store are required.

- `version`: integer 1.
- `observed_at`: actual evidence acquisition time, UTC.
- `execution`: canonical `flow_run_id`, `deployment_id`, 32-lowercase-hex
  `pipeline_run_id` or null; `scheduled_at`, `started_at`, `completed_at`; `outcome`.
  Scheduled/start/end come from authentic Prefect records, never from inference
  task times. Nullable start/end permit pending/running/cancelled observations.
  Outcomes: SCHEDULED, PENDING, RUNNING, COMPLETED, FAILED, CANCELLED, CRASHED.
- `inference`: `outcome`, canonical `task_run_id` or null, committed `receipt_id`
  or null, `issue_time` or null, `withholding` or null. Outcomes: NOT_RUN,
  GENERATED, UNCHANGED, WITHHELD, UNAVAILABLE, FAILED, UNKNOWN. A generated result
  requires the associated receipt; withheld results must not claim one.
- `withholding`: if recognized persisted evidence exists, fixed `reason` and
  `gate` enums from operational_evidence.py. JOINT_PRICE_LOAD_HOUR is supported.
  Unrecognized values map to UNKNOWN in the future producer; absent incident
  detail remains null. Never infer a gate from missing receipt or pass through
  incident text. Detailed gate/reason remains Admin-only.
- `delivery`: actual implementation outcome or NOT_RUN/UNKNOWN; `receipt_id`,
  `bundle_sha256`, `published_at`. Published requires the same committed receipt
  as inference and a bundle hash. Other generated-delivery outcomes also require
  the matching receipt. Exact published_at is null unless genuinely persisted:
  current task timing bounds must not be relabeled as exact publication time.
  DISABLED/FAILED are independent of successful inference. WITHHELD permits
  SKIPPED_WITHHELD, DISABLED or UNKNOWN, never PUBLISHED.
- `provenance`: fixed source PREFECT_AND_PERSISTED_PIPELINE, origin
  NATURAL_SCHEDULE, corroborating `flow_run_id`, `pipeline_run_id`, and
  `task_flow_run_id` (null only without associated task). Conflicting IDs fail.

UTC syntax is strict Z or +00:00; no naive/nonzero-offset timestamps. Chronology
is checked; observed time cannot be in the future. Execution COMPLETED is not an
inference or publication attestation. A later pipeline-stage failure can coexist
with a successful prior inference/publication.

## Operational freshness, independent of forecast expiry

VALID until the earlier of scheduled_at + 90 minutes and observed_at + 90 minutes;
STALE at the cutoff. The hourly schedule normally completes within minutes; this
allows a 30-minute grace beyond the next nominal slot, without allowing old runs
to remain current indefinitely. Re-observing an old run cannot renew its lifetime.
Policy is proposed, not activated. No forecast freshness constants are changed.

Reader states: VALID, STALE, MISSING, INVALID. Stale records retain only safe
observation/schedule/cutoff/hash metadata; current_execution is null. Missing,
malformed, conflicting, unsafe or incomplete records never query October 26 data.
Only the existing forecast selector assesses live availability. Every projection
states forecast_eligibility=NOT_ASSESSED until that independent selector is used.

## Atomic local store primitive

Proposed separate root: /srv/powerflow/operational-publications, NOT the original
snapshot or forecast roots. Provisioning remains a later reviewed deployment.
Root and releases must be real directories owned by root or the publisher, with
no group/world writes. A regular `contract` marker must contain exactly
`powerflow-operational-evidence-v1\n`. Writer/reader traverse ancestors via no-follow
anchored directory descriptors. SHA releases contain one evidence.json, mode0640;
release directories0750, group inherited explicitly from root. Production proposal
is root:992; API reader receives read/traverse only. Marker prevents using the
forecast store accidentally. Parent provisioning/ACLs and actual service namespace
access require later Linux verification.

Writer validates before writes, takes a nonblocking exclusive lock, checks expected
current pointer and schedule monotonicity, writes .partial-* exclusively, fsyncs,
reads back/verifies complete content, renames to releases/<sha256>, fsyncs releases,
then writes/fsyncs a temporary regular pointer (64 lowercase hex SHA plus newline),
rechecks freshness and atomically replaces current. Prior releases remain. Unlike
the forecast store, current is a regular file: concurrent readers pin its descriptor
and accept a just-unlinked old pointer inode. Pointer symlinks are rejected. This
avoids an observed intermittent macOS readlink EINVAL during concurrent replacement,
without changing the forecast store or requiring reader retries.
Same run cannot regress observation/start/terminal state or switch its identity.
Exact duplicates are idempotent under the lock. No retry or silent repair occurs.
Interrupted pre-switch writes leave old current intact and may leave inert partial
or unreferenced immutable directories. No automatic cleanup/deletion is provided.
An fsync failure AFTER pointer replacement is uncertain success, not guaranteed
rollback: independently inspect before any retry. A reader opens current once
and reads the retained immutable release; it sees old or new complete evidence.

Explicit restore requires the expected current pointer and a retained previous
hash, revalidates complete content AND operational freshness under the same lock,
and atomically switches the regular pointer. Expired evidence cannot be restored as current. This is
an offline library primitive, not authorization to run recovery on EC2.

## Checkpoint 2 producer integration (local only)

`shared.operational_evidence_producer` now provides latest_natural, associate and
from_snapshot. These functions do not call Prefect, open files, import model
execution, invoke the publisher or change pipeline behavior. They accept already
authenticated/bounded Prefect responses and committed receipt bytes from a trusted
producer, not HTTP arguments. Source capture and lifecycle invocation remain the
next separately reviewed boundary. No new scheduler is introduced.

Latest natural selection requires the expected deployment, auto_scheduled=True,
canonical IDs and the verified hourly :45 schedule. It does not substitute an
older completed execution if the latest observed due natural execution is still
running or incomplete. Actual start and completion times must exist; missing or
conflicting evidence fails closed, never using callback wall clock as completion.

A unique forecast task (including its actual Prefect-generated name suffix) maps
to exactly one persisted Next24h forecast generation stage within the existing
reviewed two-second timestamp tolerance. Its internal UUID selects exactly one
pipeline summary. Task/flow intervals, pipeline summary status and generated flag,
issue time and persisted stage outcome must agree. For early failure before a
forecast task, a unique Total pipeline stage and failed summary are required;
unknown forecasting/delivery outcomes stay UNKNOWN, not successful or NOT_RUN by
assumption. Cancelled/crashed executions without persisted summary/times cannot
currently be associated and remain explicitly unverified.

Generated outcomes require one matching five-artifact committed receipt with its
reciprocal integrity manifest. The adapter reuses verify_inference_receipt and the
existing full 31-feature/24-target forecast validator. A small in-memory assembly
mirrors the existing builder's wire format without invoking its file-writing CLI
or changing preserved deployment tools. Expired receipt structure can establish
historical inference/delivery facts; it cannot establish live forecast availability.
Raw features/market data never enter the operational publication. The persisted
PUBLISHED outcome and exact task order are required; no active-pointer or API
availability inference is made here. Exact published_at remains null because it
is not persisted by the current publisher.

WITHHELD needs a matching internal stage/summary and a real withholding timestamp.
When a matching incident exists, its UUID, timestamp, status and source-watermark
summary must agree. Only recognized fixed reason/gate categories are emitted;
unrecognized detail becomes UNKNOWN, absent detail remains null. Duplicate or
inconsistent incidents fail closed. Missing or unrecognized delivery status is
explicit UNKNOWN or a rejected inconsistency; no successful outcome is invented.

from_snapshot executes fixed bounded SELECTs only on a caller-owned query_only
connection with an active read transaction. It does not open or mount the writable
production database or accept an arbitrary query. The dedicated connection gets a two-second SQL progress budget (checked every
1000 SQLite VM instructions; callback budget also bounded), cleared on exit. The
producer's future capture layer must supply a consistent snapshot with existing
journal/no-follow/ownership protections and a bounded connection timeout. API modules never import this
producer or receive its connection. A hash authenticates bytes, not their origin;
trusted source capture and restricted root-owned store access remain prerequisites.

## Checkpoint 2 shared API and React consumers (local only)

Optional configuration: POWERFLOW_OPERATIONAL_PUBLICATION_ROOT, proposed separate
root /srv/powerflow/operational-publications. If unset, current evidence is MISSING.
No provisioned path or permission is changed by this code. Existing historical root
and forecast publication configuration/validators remain unchanged.

- GET /operations/current and GET /pipeline/current share current_selection.
- GET /admin/operations/current uses the same selection and existing require_admin.
- Each request reads the immutable store once, with shared projection and fixed
  public-field allowlist. Public projection omits IDs and detailed gate evidence.
  Admin/Analyst/anonymous boundaries and no-store are tested.
- VALID/STALE/MISSING/INVALID remain distinct. Current fields are null for every
  non-VALID result. No current endpoint consults SQLite, even when the root is
  missing, unconfigured or corrupt. No historical fallback parameter exists.
- Existing /operations/summary, /pipeline/status and /admin/operations are retained
  as historical sources. React labels their execution fields and history as such.
  The old Operations summary's forecast-publication overlay stays independent.

One CurrentOperationsProvider inside the protected workspace polls the public
endpoint, so Overview and Pipeline reuse the same response across navigation.
Both pages show the same scheduled/start/completion times and separate execution,
inference and delivery outcomes. Client-side operational cutoff also masks current
fields without waiting for another response. Admin association details are fetched
only in the server-confirmed Admin branch and displayed only when evidence_id and
current execution match the public response and remain fresh. Version mismatches
show an explicit refresh message rather than mixing IDs/times. Separate HTTP
requests are not globally atomic; hash comparison handles a legitimate intervening
pointer switch. No identity-provider or role changes are introduced.

V1 is latest execution only: it does not invent latest-success history, source
watermarks, quality checks, full history or measured durations. These stay in
clearly historical sections until separately supported. Existing next24 selection,
expiry, chart inputs and forecast API behavior are unchanged. PUBLISHED never
changes operational forecast_eligibility from NOT_ASSESSED.

## Remaining activation boundary

The adapter and consumers are connected in offline tests. No live Prefect hook,
source-reader transport, privileged operational writer launcher or publication
activation is installed/enabled. Next checkpoint should implement/test the terminal
Prefect lifecycle capture and restricted delivery boundary: actual flow end must
already be persisted, all source IDs/artifacts independently verified, and evidence
publication failure must not rewrite inference success. Reuse the current scheduler
and trusted publication lifecycle. Linux namespace/group992 access, ownership,
lock/durability semantics, deployment hashes and rollback require later review.

## Offline validation

Executed on macOS with Python 3.14.7: 294 selected cases passed, including 163
operational contract/store cases (100 concurrent-publication stress iterations),
existing forecast publication, automatic delivery, API and API authorization tests.
A deterministic old-pointer-unlink test verifies readers can finish from a pinned
old descriptor after replacement. Tests cover exact freshness cutoff, identities,
status consistency, withholding privacy, missing/invalid content, hash/permission/
owner/symlink failures, CAS/monotonicity, atomic failure before activation, uncertain
post-switch sync failure, explicit recovery and unchanged forecast-store bytes.
Python 3.9 grammar checks passed; no Python 3.9 execution was available. Linux
UID/GID 992, service mount namespace, ACL, durability and privileged installation
behavior remain unverified. No network, database, Prefect or model calls were made.

Checkpoint 2 final offline validation (Python 3.14.7/macOS, Node/JSDOM): 345
selected Python cases passed, including 51 new producer/API integration cases;
113 frontend tests passed, including 11 new current-evidence cases. ESLint,
TypeScript checking and Vite production build passed. New Python source/test
Python 3.9 grammar checks passed (not Python 3.9 execution). Synthetic end-to-end
coverage associates persisted records, activates only a temporary fixture store,
and reads identical public/Pipeline/Admin evidence; existing forecast publication
and authorization regressions remain passing. No browser/live API acceptance,
remote configuration check, operational activation or production mutation occurred.

## Checkpoint 3 local continuation

Terminal capture and the restricted delivery proposal now exist; see
`deploy/staging/operational-evidence/REVIEW.md` for lifecycle evidence, exact privilege
scope, stable-ID joins, idempotency, failure behavior and remaining Linux gates.
Checkpoint 2's proposed temporal association is not used by terminal delivery.
The flow hook remains disabled by default and no installed source/permission,
service environment or publication has changed. The old deployment bindings are
intentionally no longer executable against modified worker source; they remain
preserved rather than refreshed. No API/authentication/forecast-expiry changes.
