# Live Forecast Reliability — local milestone, November 7, 2026

Implementation is local only. Nothing was deployed, published or run in Prefect.
The authenticated Analyst `/api/admin/operations/current` denial check remains
**PENDING**; no DevTools/browser authorization investigation was resumed.

## Cause and policy

The verified November 7 16:45 UTC execution used the 14:00 UTC issue hour and
completed at 16:47:51 UTC. Its previous API expiry was 17:00 UTC: only about
12 minutes of availability despite targets extending to November 8 14:00 UTC.
The admission-age rule was also being used as the serving lifetime. Complete
quarter-hour observations are not available until an issue hour has ended, and
normal source/ingestion latency consumes more of that three-hour allowance.
The hourly :45 schedule was not a promise of a new issue every hour.

The frozen model's manifest and `models.next24h` define 24 direct predictions at
issue+1 through issue+24 hours, not 24 hours after pipeline completion. No model,
feature, source, scheduling or issuance behavior changes in this milestone.

- New inference and publication admission retain the existing three-hour issue
  freshness rule, expiry revalidation and duplicate/older-issue protection.
- API readers can serve the **single already admitted current publication**
  while at least one target timestamp remains future: `now < issue+24h`.
- Inference completed after issue+3h remains ineligible. The serving deadline is
  never reset by completion, reads, restarts, duplicate attempts or late arrival.
- At issue+3h, the UI labels the older forecast **refresh delayed**, not newly
  refreshed/live next-24-from-now data. Future targets retain their original
  timestamps, values and horizons. Elapsed targets are explicitly reference-only.
- At issue+24h, the API returns 503/FORECAST_WITHHELD and Operations EXPIRED.
  Missing, corrupt, incomplete or unsafe active publications remain withheld;
  no previous release or historical CSV is substituted.
- Operational evidence has its independent 90-minute policy, unchanged.

This is an explicit availability-policy change, not evidence that a 20-hour-old
issue is as accurate as a newly issued forecast. No accuracy improvement is
claimed. A full upstream outage can still exhaust the available model horizon.

## Implementation

`shared.forecast_availability` is a read-only API adapter. It calls the **original
full validator at actual UTC**. Only the typed admission-age expiry, raised after
all integrity/completeness checks, may proceed to the separate horizon check.
It does not backdate validation, weaken the publisher, load a model, infer or
write any publication. Pointer selection is single-snapshot and concurrency-safe.
Exact historical activation time is not in V1 bundles and is not invented. The
trusted existing publisher/root permissions establish admission.

The pinned `shared.forecast_publication` remains byte-for-byte unchanged:
`a88906ef45688dbee98171376a53ff64a6b88e68a800a0a422a1a7375e452902`.
No privileged tools, launcher, sudoers, receipt format, model or feature-contract
hashes change. Previous immutable releases and manifests remain unchanged.

The API adds `availability_policy=ISSUE_HORIZON_V1` and `refresh_due_at` to the
publication metadata; `expires_at` is issue+24h. Operations exposes matching public
expiry/refresh timestamps. Forecast rows/bundle bytes are unchanged. The frontend
accepts the explicit new policy, retains conservative legacy three-hour support,
and rejects unknown/partial policies, shifted expiries and stale completion.

Overview, Forecast Intelligence and Pipeline Operations use consistent expiry
handling. Background-tab focus/visibility resynchronizes the UI clock. The chart
already separates elapsed/future lines; the exact table now labels every target.
Full-horizon statistics and CSV are explicitly distinguished from future-only
availability. Admin/provenance and role guards remain unchanged.

## Validation and readiness

- Broad backend: **423 passed, 1 pre-existing historical manifest assertion**.
  The failure is
  `test_automation_source_manifest_and_installed_closure_are_exact`, which pins
  `src/scheduled_pipeline.py` to `1eb95c4f…`; committed HEAD already contains
  `f275e1c3…` (the current hook integration). This milestone does not change that
  file, test or historical manifest. All installed publisher-tool hashes pass.
- Final affected backend run: **67 passed**, covering strict admission, horizon
  boundary, validation-time expiry, pointer races and missing/tampered data. The
  broad run also passed actual frozen-HGB inference through receipt/bundle/API
  using isolated synthetic sources and mocked weather, with no model substitution.
- Full frontend: **129 passed**. Relevant real React pages are exercised with
  synthetic API fixtures for valid, delayed-refresh, expired and missing states;
  exact 24-row table/value consistency and Analyst restrictions are checked.
- TypeScript, normal production build, explicit staging-origin release build and
  release asset guards passed: no source maps or test fixtures in the output.
- Python 3.9 grammar passed; execution tests ran on local Python 3.14.7. Linux
  runtime behavior and genuine deployed browser acceptance still need preflight
  and authorized post-deployment acceptance. No live availability claim is made.

Staging-origin frontend candidate (private local output, not a deployment runner):
`data/backups/private-staging-releases/live-forecast-reliability-20261107-v1/frontend`.
It uses the existing verified public Cognito configuration, same-origin `/api`,
and is marked releaseEligible for `https://staging.powerflowenergy.dev`. This does
not authorize installation. Never reuse V5 apply or an old three-hour acceptance
inspector for this changed policy.

Next release work: bind the new API module/import closure and changed frontend
to a new guarded staging transaction, preserve publisher/helper/Nginx/scheduling
baselines, then request authorization for fresh read-only Linux preflight and
guarded apply. After apply, use a genuine natural run to verify receipt/pointer,
200/no-store and matching values, delayed-refresh behavior past the old cutoff,
newer-issue replacement and withholding at the final target. Browser desktop/mobile
verification remains separate from the local DOM regression results.

## Selective manual Git commands

Review first: several API files contain earlier uncommitted operational work as
well as this change. File-level staging includes that work; don't use `git add .`
or stage private candidate outputs or unrelated DevTools artifacts.

```sh
git diff -- src/api/app.py src/api/forecast_source.py src/api/operations_summary.py frontend/src frontend/tests/forecastPublication.test.ts tests/test_forecast_publication.py tests/test_forecast_source_consistency.py tests/test_inference_evidence.py

git add -- src/shared/forecast_availability.py src/api/app.py src/api/forecast_source.py src/api/operations_summary.py frontend/src/api/contracts.ts frontend/src/api/forecastState.ts frontend/src/api/forecastPresentation.ts frontend/src/api/publicationState.ts frontend/src/api/operationalForecastState.ts frontend/src/api/restoration.ts frontend/src/components/data/ForecastChart.tsx frontend/src/components/data/ForecastSummary.tsx frontend/src/components/data/OperationalSummary.tsx frontend/src/hooks/useClock.ts frontend/src/pages/PipelinePage.tsx frontend/tests/forecastPublication.test.ts frontend/tests/liveForecastReliability.test.tsx tests/test_forecast_publication.py tests/test_forecast_source_consistency.py tests/test_inference_evidence.py tests/test_live_forecast_reliability.py frontend/docs/live-forecast-reliability.md

git diff --cached --stat
git diff --cached
git commit -m "Separate forecast admission freshness from remaining-horizon availability"
git push
```

No Git staging, commit or push was performed by the agent.
