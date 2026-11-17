# Permanent next24 recovery review — local proposal only

One read-only inspection completed at2026-10-29 08:07UTC. Evidence: ORPHAN-TIMING-RESULTS.json. No production state, schedule, data or service was changed.

## Two independent problems

1. **Orphan metadata:** Flow01a0c4e9-92ac-7772-8e1d-2ab939191545 and task01a0c58d-ece5-75b0-95fd-5230d239413f remain RUNNING sinceSeptember21. The recorded infrastructure PID is absent; no matching engine/ingestion process exists. Last log activity wasSeptember21 20:00:38UTC. The current worker startedOctober16, is ONLINE and heartbeats every30seconds; the deployment is READY and polled. The host boot predates the run, so a host reboot is not established as its cause. The original process disappeared without a terminal-state update; the precise termination mechanism is unproven. Evidence strongly supports orphan reconciliation after immediate revalidation, not cancellation of a live job.

The manual recovery guard blocks any RUNNING/PENDING/CANCELLING/PAUSED run in this deployment; it therefore blocks on this old record even though recent hourly runs complete normally. Do not bypass that guard or ignore records solely because of age.

2. **Schedule versus provider latency:** All24 inspected hourly runs withheld forecasting, with complete load about181.8–182.96minutes old at run completion. UTC issue-time age is computed correctly; there is no demonstrated DST/arithmetic defect. At08:02 the newest complete load05:00 was just beyond180minutes. The05:30/05:45 quarters arrived upstream between the07:00 scheduled retrieval and the positive07:45 provider check, then were ingested at08:00. The same lag pattern moved to06:30/06:45. The exact source publication instant is not known. Archive-weather latency does not explain this raw-load gate.

## Smallest operational proposal

After exact orphan reconciliation, change the existing hourly UTC schedule from00 to45 minutes, rather than adding runs or changing freshness. The07:45 availability check supports this conservative offset, but one positive source check is not a provider SLA. At a hypothetical08:45 run, complete06:00 load is2h45 old; completeness and all31 features must still pass using actual new observations. Offsetting the schedule without receiving new data does not help. Delays/outages must continue to withhold forecasts.

**New live finding:** Deployment concurrency_limit and concurrency_options are null, despite local prefect.yaml specifying1. Propose setting this deployment's concurrency_limit to1 as part of the separately approved scheduling change, after the orphan is reconciled. Preserve work pool, queue, parameters, storage backend, worker service and all other settings. Do not rely on a manual CLI invocation to inherit deployment concurrency. Do not alter worker/systemd/AWS configuration. No local or production schedule was changed; exact current/proposed values are in SCHEDULE-PROPOSAL.json.

## Separately approvable execution

A. Revalidate both exact September21 records, worker health, absent PID/process and no new activity. Privately retain before-state evidence. Submit the two exact Prefect set_state requests in RECONCILIATION-PROPOSAL.json: task first, then flow, typeCRASHED, forcefalse. Require ACCEPT and CRASHED readback at each step. Stop on any rejection/drift; no retry/force, cancellation signal, process termination or unrelated record changes. Preserve partial reconciliation for review. Reconciliation does not claim the original run succeeded and must not be rolled back to false RUNNING.

B. With no real active/pending execution, re-read and preserve deployment/schedule settings; PATCH only concurrency_limit1 and the exact existing schedule's cron45 UTC (IDs in proposal). Inspect already queued occurrences for duplicates; do not delete or modify queued runs without approval. If the Prefect version does not automatically reconcile pending scheduled occurrences, stop for a bounded queue-management approval. Verify only intended settings changed. Observe the next normal scheduled run; require current raw source completeness, unchanged three-hour freshness, weather/model validation and legitimate24-target outputs. No immediate manual run is part of this proposal. Revert cron/concurrency only with explicit rollback approval; no data deletion or threshold adjustment.

Next authorization can group A and B only with these exact metadata/configuration boundaries and hard stops. The next scheduled run naturally executes the existing pipeline; no manual ingestion, retraining command, inference call, staging publication or infrastructure change is included.

## Local verification

Targeted regressions cover exact3-hour acceptance, rejection two minutes beyond, continued rejection at45 minutes with unchanged incomplete data, acceptance only after genuine fixture quarters arrive, and rejection beyond3hours again. Proposal tests lock exact orphan IDs, CRASHED-only transitions, forcefalse, hourlyUTC schedule, concurrency1 and unchanged freshness. Existing diagnostic/model tests included. No application/model/pipeline code changed.
