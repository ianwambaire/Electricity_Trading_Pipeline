# Current operational evidence — checkpoint 1

Status: local contract and offline store tests only. No live producer, API switch,
privilege rule, deployment package or authorization is introduced here. Existing
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

## Producer integration — next checkpoint, not implemented

Extend the existing natural scheduled pipeline finalization/completion lifecycle.
Use actual Prefect scheduled origin/deployment/flow/task metadata, internal pipeline
UUID and its committed summary, matching incident (if any), receipt and delivery
outcome. Reuse the reviewed association/receipt checks; do not merely trust a flag
or accept arbitrary caller IDs. Actual flow completion must already be recorded;
a callback before that fact is persisted must report missing evidence rather than
substitute its own wall clock. Confirm the exact Prefect lifecycle hook offline
before deployment. Include failure outcomes when persisted; inability to publish
operational evidence must not rewrite inference success or fail a successful run.
No new scheduler, forecast execution or publication attempt is needed.

No producer extractor is implemented in this checkpoint: the contract validates
relationships, not live Prefect authenticity. Restricted publisher privilege design,
source association, dependency binding and Linux identity tests remain prerequisites.

## Consumer integration — next checkpoint, not implemented

Introduce one configured operational-root selector shared by all three API readers.
Resolve one selection per request and expose identical evidence_id, observed_at,
scheduled_at and evidence status. Public projection contains only execution times,
execution/inference/delivery outcomes and fixed provenance. Admin projection adds
IDs and recognized incident detail ONLY behind the existing require_admin guard.
The admin=True library parameter is not authorization and must never come directly
from an HTTP query. Selection/projection schema allows offline role-separation tests.

Executive Overview and Pipeline Operations should consume that same public object;
Admin Operations consumes the same selection plus Admin fields. Across separate
requests a publication can change: compare evidence_id and refetch rather than mix
IDs. Current execution fields must be blank/unavailable for non-VALID evidence.
Old SQLite history/timings may remain in a distinctly named historical section,
never used to fill current fields. V1 includes the latest execution only; it cannot
invent last-success time, source watermarks, quality checks, full run history,
incidents or timings. Those remain explicitly unavailable or historical until
separately supported. Forecast availability stays sourced from select_publication,
not inference/delivery history. Existing live forecast schema/expiry stays intact.

No active API response schema or frontend behavior changes in this checkpoint.
Existing role checks and historical routes are unchanged. The next checkpoint must
add API integration and tests proving the configured current path never falls back,
then update React consumers with type/schema tests. No deployment before review.

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
