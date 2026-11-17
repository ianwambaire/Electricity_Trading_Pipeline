# Realized next24h reporting (local candidate, not deployed)

The scheduled monitoring stage already generated realized-error CSVs, but the
staging API consumed those CSVs through its separately published historical
snapshot. Forecast publication does not refresh that snapshot. This candidate
adds a small derived-report publisher to the existing monitoring stage; it does
not change inference, live forecast selection, operational reporting or auth.

## Scoring and provenance

- Only frozen HGB forecasts whose committed inference receipt passes the existing
  full receipt/model/feature/input/hash validator can enter the report. Forecast
  history rows must match receipt issue, target, horizon, model and value exactly;
  history issuance must be between receipt completion and five minutes later.
- Issuance must precede the target hour. Only complete observed ENTSO-E price
  hours whose entire hour has elapsed are matched, by exact UTC target. Existing
  ingestion resolution/completeness rules are reused. No interpolation/backfill.
- This evaluates authentic generated forecasts, not proof they reached the web
  before target. A receipt's validity for historical evaluation does not make it
  eligible for current live forecast delivery.
- Sample: last 30 target days at generation. Same target across distinct issue
  vintages is intentionally multiple forecast pairs. No duplicated vintage/horizon.
  MAE=mean(abs(predicted-observed)); RMSE=sqrt(mean(error²)); bias=mean(error).
  Negative/zero prices remain valid. Minimum 20 pairs overall/window, 5 per horizon;
  otherwise metrics are null and status is `Insufficient data`.
- Rolling 24h/7d/30d windows use target timestamps relative to API assessment time.
  Report generation and newest complete observation times are separate. Report
  freshness is 90 minutes (hourly producer plus 30 minutes allowance), not forecast
  expiry. Stale reports are visibly historical and never silently replaced.

## Producer and read-only consumer

Default disabled. A future guarded staging release must provision a **separate**
`/srv/powerflow/realized-performance` namespace containing `contract` with exact
bytes `powerflow-realized-performance-v1\n` and `releases/`. Intended root/releases:
producer UID 1000, API reader GID 992, mode 2750; verify actual deployed IDs before
approval. Producer writes immutable SHA-addressed report files (0640) and activates
only their hash via an atomic regular-file `current` pointer, after validation and
fsync. Exclusive lock, nonregressing generation and pointer compare prevent races.
Prior valid releases remain intact; no automatic rollback. Partial writes never
activate. Root must not be writable by the API. API receives a read-only mount.
Marker, no-follow access, owner/permission checks, source-size limits and public
field projection fail closed. No database access or raw feature values in reports.

Producer opt-in: `POWERFLOW_REALIZED_REPORT_ENABLED=true` and
`POWERFLOW_REALIZED_REPORT_ROOT=/srv/powerflow/realized-performance` in the existing
scheduled monitoring process. It reuses its existing reports/raw-price paths and
`data/reports/next24h_inference` receipts. Candidate API opts in using the same
root variable. This is separate from operational evidence/forecast pointers.

When configured, missing pointer/root => 404 `REALIZED_REPORT_MISSING`; missing
inputs => 503 `REALIZED_INPUTS_MISSING`; generation failure => 503
`REALIZED_REPORT_FAILED`; invalid bytes/pointer/integrity => 503
`REALIZED_REPORT_INVALID`. No fallback to historical CSV. A valid zero/small sample
is HTTP 200 with `INSUFFICIENT_DATA`; stale valid documents have `STALE`. Unconfigured
legacy CSV responses are explicitly `LEGACY_UNVERIFIED`, never current performance.

Bounded producer: 64MiB/source, 100,000 history rows, 400,000 raw observations,
10,000 receipt directories and at most the latest 1,024 receipts discovered by
mtime (32-day scan bound). Every scored receipt is independently verified; absent
receipts exclude rows and coverage exposes the exclusion. Report <=25,000 pairs /
16MiB. Limits must be checked against production before activation. Artifact
hashes identify exact source snapshots; they are not an upstream arrival-time audit.

## Required staging authorization and acceptance

Prepare/review an immutable guarded release binding all new modules and existing
transitive validators, provision namespace and read-only API mount, preserve
existing services/configuration, then separately authorize preflight and apply.
No new dependency, schema migration or manual Prefect execution is required.
Observe the next genuine scheduled monitoring execution: report hash, generation,
source hashes, receipt coverage, sample counts, metrics and API response must agree.
Then owner-assisted React acceptance must verify sufficient/insufficient/stale/
missing states, timestamps, units and CSV export on desktop/mobile. This candidate
has only synthetic offline acceptance; no claims about current production metrics.

Outstanding unrelated security closure remains unchanged: genuine Analyst HTTP
403 acceptance PENDING (browser investigation closed); Admin MFA capability
inspection BLOCKED pending approved least-privilege AWS access. No root access.

## Selective manual review/commit

Existing files also contain earlier accepted work. Review/stage their relevant
hunks rather than staging the whole workspace:

```sh
git add src/shared/realized_report.py src/shared/realized_report_store.py src/models/realized_reporting.py src/api/realized_reporting.py tests/test_realized_reporting.py frontend/tests/realizedReporting.test.tsx frontend/docs/realized-performance-reporting.md
git add -p src/models/next24h_monitoring.py src/api/app.py src/api/feature_parity.py frontend/src/api/parity.ts frontend/src/api/client.ts frontend/src/components/data/ForecastEvidence.tsx
git diff --cached --check
git diff --cached
git commit -m "Add receipt-verified realized next24h performance reporting"
git push
```
