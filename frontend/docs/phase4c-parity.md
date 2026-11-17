# Phase 4C: source-backed parity audit and acceptance matrix

Audit baseline: 21 October 2026, feature/react-frontend. Sources inspected: src/dashboard.py (six page branches and imported dashboard_data/dashboard_health/auth helpers), all seven React pages/components/hooks/API parsers, api/app.py, market_data.py, operations_summary.py, model_summaries.py, restricted_reports.py, security.py, database/schema.sql, report writers, existing API/security/restoration tests. No production system or credentials were inspected. Existing uncommitted Phase 4B and UI changes are preserved.

Each row describes a behavior, not merely a page. Public means a deliberately backward-compatible non-sensitive API; the React workspace itself requires sign-in. Admin always means verified access-token group powerflow-admins, never a frontend role claim. Baseline statuses below are retained to make the audit reviewable; final outcomes are recorded separately.

| Streamlit behavior | React at audit | Persisted evidence / API | Access | Gap and proposed implementation | Verification criterion |
|---|---|---|---|---|---|
| Overview latest historical price and timestamp | Complete | Silver; /market/summary | Public | Preserve historical label | Exact last persisted row |
| Whole-history mean load, row count, anomaly count | Complete | Silver + detected_anomalies.csv; summary endpoints | Public | Preserve full-history basis | Compare CSV aggregates |
| Price chart; load versus wind+solar | Complete | /market/chart | Public | Preserve sampling/gap captions and distinct units | Original observations, bounded chart |
| Latest ten observations | Complete | /market/summary recent | Public | Preserve newest-first table | Exact persisted rows |
| Dataset coverage and system health | Complete safe summary | /market/coverage; /operations/summary | Public | Preserve unknown versus zero and success versus issuance | Missing/stale fixtures |
| Market min/max/average/sample volatility | Backend only | /market/summary | Public | Add all-history statistics clearly separate from paginated charts | ddof=1, whole selected range |
| Generation-average eight-source bar | Missing | Silver generation columns | Public | SQL full-range averages, bounded summary/chart endpoint | Means ignore missing values like Streamlit |
| Temperature and wind-speed histories | Missing | Silver weather columns | Public | Extend cached index with optional weather, bounded chart | Exact units/nulls/UTC |
| Price/load/generation/renewable exploration | Complete improved | /market/history | Public | Keep date filters and pagination; add CSV for displayed page | No sampled/full-range confusion |
| 24-hour forecast timeline and table | Complete, local report absent | next24h_forecast.csv; /forecast/next24 | Public | Preserve elapsed/future separation | 24 ordered exact horizons |
| Availability, stale/historical/withheld warnings | Complete | pipeline_runs + report issue time | Public | Never equate success to issuance | Withholding overrides retained report |
| Average/median/extrema/negative/elevated hours and CSV | Complete | Displayed next24 report | Public | Preserve classification in export | Negative numbers retained |
| Exact issue-hour market/weather context and complete 24/168-hour baselines | Missing | Silver; dashboard_data.build_model_input_context | Public observations | New bounded exact-hour context; never nearest-hour substitution | Missing hour/window gives null |
| Realized next24 overall/24h/7d/30d/per-horizon error metrics | Missing; local file absent | next24h_realized_errors.csv; summarize_realized_performance | Public aggregate | Expose per-release summaries using existing thresholds | 20 aggregate/window and 5/horizon, pre-target issuance only |
| Model performance health/review advice | Missing; no local realized evidence | dashboard_health.model_performance_state | Public aggregate | Reuse existing rules where evidence exists; do not manufacture diagnosis | Minimum pair/day/horizon coverage |
| Frozen one-hour actual/predicted | Complete | actual_vs_predicted.csv; /forecast/one-hour | Public | Preserve historical status, add displayed export | Original precision/time range |
| Frozen one-hour metrics and next24 release evaluation | Complete improved | manifests + final_holdout_metrics; /models/summary | Public safe summary | Keep models/periods separate; no ranking across different tasks | Persisted values match release |
| Top-15 coefficient chart and full 31-feature table | Missing UI | feature_importance.csv; /admin/models/linear-feature-influence | Admin | Signed bars, magnitude/name sorting, full table/export | All 31 values equal report; Analyst 403 |
| Coefficient interpretation and provenance | Partial | Existing writer + frozen metadata | Admin | Show signs, noncausal and scale caveats, metadata/report hashes | No HGB attribution or cryptographic-binding claim |
| Latest run, successful run, forecast status/reason | Complete safe summary | pipeline_runs; /pipeline/status + /operations/summary | Public | Keep recorded evidence timestamps | Successful run may have unavailable forecast |
| Source ingestion freshness/counts, Silver/Gold coverage | Complete | Raw/Silver/Gold cached CSV summaries | Public | Preserve archive/weather semantics | Stale versus incomplete distinct |
| Model artifact/data product availability | Complete | validated /models/summary + file-presence summary | Public | Link model verification, do not treat file presence as valid report | Invalid artifact distinction |
| Full run history, mode/ingested rows/prediction counts | Missing | pipeline_runs | Admin | Bounded safe projected history; no raw messages/config | Max 100; no secrets/paths |
| Quality check history | Partial | data_quality_results | Public safe / Admin | Public labels preserved; bounded Admin structured history | Unknown checks labeled safely |
| Operational incident filters and timeline | Missing; table absent locally | operational_incidents | Admin | Severity/component/period on bounded recent history, static event descriptions | Missing table != zero incidents |
| Stage durations and recent performance | Missing; table absent locally | pipeline_stage_timings; existing timing helper | Admin | Bounded duration records, latest total/forecast/slowest and recent mean | No invented durations, missing != zero |
| Forecast-vintage and exogenous readiness | Partial UI; missing reports | protected monitoring endpoints | Admin | All allowlisted coverage/revision/failure/leakage fields | Missing/null differs from 0/false |
| Legacy monitoring URLs | Public raw reports: security gap | /monitoring/* | Must become Admin | User approved restricting both aliases to Admin, same allowlist | No unauthenticated alternate route |
| Dataset filesystem paths, raw incidents/messages, storage/config details | Intentionally omitted | Internal operational metadata | Never public | Keep off browser even for Admin; expose logical categories | Poisoned free text never returned |
| Admin-only Streamlit Model Insights page | Intentionally changed | Safe summaries public, coefficients protected | Mixed | Retain useful public model summaries; enforce report boundary server-side | Client role spoofing cannot retrieve coefficients |
| Cognito sign-in/out, profile, responsive accessible navigation | Complete, extra versus old pages | Cognito + /auth/me | Authenticated | Preserve behavior/design, verify regression suite | No ID-token API authorization |
| What-if/zoom/pan/training/admin write actions | Not parity requirements | None | Excluded | Do not add scientific/product scope | No write or training routes |

## Security migration decision

Repository search found no HTTP consumer of /monitoring/* in Streamlit; it reads reports directly. Nginx proxies API but is not changed. External consumers cannot be inventoried from repository evidence. The user explicitly approved restricting both legacy URLs to Admin on 21 October 2026. Preserve their URLs as deprecated authenticated aliases returning the SAME allowlisted response models as /admin/monitoring/*. Anonymous requests become 401; Analysts 403; malformed reports 503; missing reports 404 after authorization. No anonymous compatibility switch or raw-response fallback. Production rollout/consumer notification remains a separate approval/deployment step.

## Implementation order

1. Protect legacy aliases and verify JWT/role boundary tests.
2. Restore coefficients with strict runtime parsing and accurate provenance.
3. Add bounded read-only Admin operations and typed views, distinguish absent instrumentation.
4. Restore market summary/generation/weather, exact forecast context and realized evaluation using original calculation helpers.
5. Shared safe CSV exports, validation and accessibility; full tests/build; record actual limitations and acceptance instructions.

No model, pipeline, Streamlit, Cognito, dataset or deployment changes are needed. Existing operational instrumentation already writes incident/timing tables on instrumented runs; do not create tables or execute a flow merely for a UI demonstration.

## Final feature outcomes

The missing UI features in the baseline matrix are now implemented: signed top-15 Linear Regression coefficient chart, all-31 table and sorting/export; market-wide price statistics, eight-source generation-average bar/table, temperature and wind-speed charts; exact latest-persisted and forecast issue-hour context, complete-window raw-price comparisons, same-period one-hour persistence improvement and Admin-only issuance/weather provenance; realized next24h evaluation by release/overall/window/horizon; bounded Admin execution history, incident filtering and measured stage performance; expanded forecast-vintage counts and readiness/leakage diagnostics. Shared CSV serialization preserves numeric negatives/missingness and neutralizes spreadsheet formula text. All seven routes and the existing white/blue design remain.

### Deliberate differences and unresolved evidence

- Raw incident messages/details, run messages, infrastructure/storage configuration and filesystem paths are intentionally not restored. A verified Admin role is not justification for rendering arbitrary stored text/secrets; structured allowlisted categories retain useful incident exploration. Unknown stages/components/events are explicit generic categories, not leaked free text.
- The existing coefficient writer extracts the 31 coefficients from the frozen StandardScaler + LinearRegression pipeline. Metadata identity and report-content SHA-256 are shown separately. There is **no persisted cryptographic binding** between the coefficient report and model artifact; no stronger guarantee is claimed. No artifact is unpickled, fitted or executed by these APIs.
- The one-hour release has no explicit version identifier. Its real model name, release type, creation time and metadata fingerprint identify the available evidence; no invented version is assigned.
- Local next24h_forecast.csv, next24h_realized_errors.csv, forecast_vintage_health.json and next24h_exogenous_silver_quality.json are absent. The new UI and APIs support those reports but cannot provide genuine successful demonstrations without legitimately generated evidence. Tests use temporary fixtures only. Missing reports remain 404 after authorization, not fake empty successes.
- Local operational_incidents and pipeline_stage_timings tables are absent. Existing instrumentation in scheduled_pipeline.py/store_data.py already collects them on an instrumented execution. No schema/data migration or forced flow run was added. No duration or incident was invented. An empty existing table is distinct from a missing table.
- Operational history is deliberately bounded to the newest 100 runs/incidents and 200 timing records. Incident filters apply to that fetched history. The latest measured total and up-to-ten successful total-row mean are computed exactly like Streamlit within this bounded sample; missing total rows never imply a sum is the true pipeline duration. Tables scroll within bounded panels.
- Realized evaluation is separated by recorded release. It uses the unchanged 20-pair overall/window and five-pair horizon rules; the original 100-pair/seven-target-day health coverage checks remain. Only a matching validated active release can use its approved persistence/test baseline; historical/unknown releases never borrow another model's baseline. There is no automatic retraining.
- The frontend's conservative existing three-hour display-recency classification remains explicitly unverified; it does not attest to current backend eligibility. No withholding/freshness or scientific forecasting rule was changed.
- Market statistics/means use the full applied range (all history when dates are blank), while exact detail charts retain their existing latest-week default and 1,000-row pagination. Scope labels distinguish those views. Sampled weather exports identify sampling and the source snapshot; they do not imply full-history export or preserved wind extrema.
- Operational/configuration detail suppression and safe model summaries are deliberate security/usability changes from the original Admin-only Streamlit page, not missing public features. Zoom/pan and a What-if Lab remain excluded enhancements rather than claimed parity.

## Endpoint access-control matrix (GET only)

FastAPI serves the paths below directly. React uses `/api` and Vite strips that prefix before forwarding to port 8000. Production proxy configuration is unchanged.

| Endpoints | Anonymous | Valid Analyst access token | Valid Admin access token | Bounds / purpose |
|---|---|---|---|---|
| `/health` | 200 | 200 | 200 | Reachability, public service time |
| `/pipeline/status`, `/operations/summary` | Allowed | Allowed | Allowed | Existing safe status; last 20 public quality labels and logical product/source summaries |
| `/market/coverage`, `/market/summary`, `/market/chart` | Allowed | Allowed | Allowed | Existing UTC range validation; chart 4–2,000 points |
| `/market/history` | Allowed | Allowed | Allowed | At most 366 days, 1–2,000 rows (React 1,000), bounded offset |
| `/market/exploration` | Allowed | Allowed | Allowed | UTC date range, 4–2,000 sampled weather points, eight full-range source means/counts |
| `/market/price-comparison` | Allowed | Allowed | Allowed | Complete-hour observed price summary, cached by source version; 64 MiB/400,000 raw rows cap |
| `/anomalies/summary`, `/anomalies/events` | Allowed | Allowed | Allowed | Historical persisted events; validated range/order/limit/offset |
| `/forecast/next24`, `/forecast/one-hour` | Allowed | Allowed | Allowed | Existing public persisted prediction contracts retained |
| `/forecast/context` | Allowed | Allowed | Allowed | Required timezone-aware exact `issue_time`; at most 168 exact Silver hours read; no nearest substitution |
| `/forecast/realized-evaluation` | Allowed | Allowed | Allowed | Public aggregate metrics only; 64 MiB/100,000 pair cap, 20 releases, 24 horizons, three windows |
| `/models/summary` | Allowed | Allowed | Allowed | Existing safe release/evaluation metadata, no model deserialization |
| `/auth/me` | 401 | Own minimal identity, Analyst | Own minimal identity, Admin | Verified access token only, no-store |
| `/admin/models/linear-feature-influence` | 401 | 403 | Allowed | Exact allowlisted 31-feature report, 64 KiB cap, two fingerprints |
| `/admin/forecast/provenance` | 401 | 403 | Allowed | Current-report-bound complete issuance cycle and safe weather/market evidence only; 100,000 history-row cap |
| `/admin/operations` | 401 | 403 | Allowed | Up to 100 executions, 100 structured incidents, 200 timing records; no raw messages/details/configuration |
| `/admin/monitoring/forecast-vintages` | 401 | 403 | Allowed | At most 12 known sources; explicit diagnostic allowlist |
| `/admin/monitoring/exogenous-readiness` | 401 | 403 | Allowed | Readiness/counts and recorded leakage boolean only |
| Deprecated `/monitoring/forecast-vintages`, `/monitoring/exogenous-readiness` | **401** | **403** | Same safe response as Admin counterpart | No raw report or anonymous alternate route remains |

“Allowed” is not a promise of a successful report response: missing data 404; invalid/unreadable evidence 503; invalid query input 422. Invalid signature/expired/ID token/wrong issuer/client/scope returns 401 for protected resources. Missing server verification configuration fails closed (503 with a credential, 401 without). Public market/report routes intentionally retain the Phase 4B public-safe contract. Server-verified `cognito:groups` membership is the sole Admin authority; client query/role fields cannot grant it.

## Legacy monitoring assessment and rollout/rollback

The former recursive redaction filtered sensitive *keys* but allowed filesystem strings, source/revision/incident fields and arbitrary nested values through. It duplicated information intentionally separated into protected reports, so preserving anonymous raw access was not defensible. Both old URLs now run the same require_admin dependency and same bounded response projection as the protected versions and are marked deprecated in OpenAPI. Authorization runs before report reads.

Streamlit is untouched and reads its local reports/SQLite through dashboard_data/dashboard_health, not these HTTP endpoints; tests exercise that independence. External production consumers remain unknown; no production deployment has occurred. Before a future approved rollout: inventory API/proxy access logs through the authorized operations process, notify owners, migrate them to the protected URLs and legitimate approved OAuth clients/scopes, verify Admin 200/Analyst 403/anonymous 401, then deploy only under separate approval. The URL is preserved but anonymous access and raw fields intentionally are not. No token should be pasted into documentation or committed.

Rollback must preserve the security boundary: roll back frontend presentation independently, retain authenticated allowlisted aliases, or temporarily disable detailed routes. Do **not** restore the anonymous raw readers. Streamlit's file-based path provides compatibility independent of the API migration. No Nginx, Cognito or AWS changes are needed for these code changes.

## Visualization provenance

| Visualization / data view | Actual source and transformations |
|---|---|
| Signed coefficient bars/table | data/reports/feature_importance.csv; unchanged signed coefficients and absolute values, top 15 by absolute magnitude; all 31 retained; frozen one-hour metadata fingerprint separately validated |
| Market statistics | Same cached Silver SQLite snapshot as existing market API; full-range SQL min/max/mean and centered sample variance, no sampled metrics |
| Generation means | Eight original Streamlit source columns in Silver; full-range SQL averages exclude nulls; each valid observation count shown; total wind not added to component winds |
| Weather histories | Optional Silver temperature_2m/wind_speed_10m; original observed values, UTC, bounded chronological bucket sampling; real missing hours break lines |
| Admin forecast issuance/provenance | Matching current next24 report versus persisted forecast history (all 24 horizons, exact values/release, one pre-target issuance time); safe issue-bound provenance JSON fields only; missing history never becomes an inferred generation time |
| Exact input/latest observed context | At most 168 original indexed Silver hours; dashboard_data.build_model_input_context unchanged; strict complete windows; no model-input-vector reconstruction claim |
| Price comparisons | Raw ENTSO-E prices; dashboard_data.summarize_clean_price_history and original complete-hour aggregation, cached by source version |
| Realized next24h metrics | Persisted next24h_realized_errors.csv, validated error consistency/horizons/unique release-issue-horizon keys; original summarize_realized_performance and model_performance_state helpers; report SHA-256 |
| Execution/incident/performance tables | SQLite read-only connection, schema-based bounded SQL queries; allowlisted categories, original measured durations; no raw messages or user records |
| Vintage/readiness diagnostics | Existing persisted JSON paths and protected projection functions; no regeneration or weakening of completeness |

## Local startup and manual Admin/Analyst acceptance

Use two terminals from the repository root. Public settings below identify the already-approved SPA client; they are not secrets. Do not source arbitrary dotenv files into a shell or put a client secret in Vite.

```sh
cd /Users/iannganga/Desktop/electricity-trading-pipeline
export POWERFLOW_API_COGNITO_ISSUER=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_NLoYFRvex
export POWERFLOW_API_COGNITO_CLIENT_IDS=4t8s6a673a18qhbauqac8rhdcf
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./venv/bin/python -B -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

```sh
cd /Users/iannganga/Desktop/electricity-trading-pipeline/frontend
npm run dev -- --host localhost --port 5175 --strictPort
```

Open **http://localhost:5175/**, matching the existing SPA callback origin. Preserve existing frontend public OIDC settings; no OAuth callback or configuration changes were made. If these development servers are already running, reuse them. The API was restarted locally for validation only and left running with optional `--reload --reload-dir src` development flags. The commands above work without reload.

1. Anonymous: `curl -i http://127.0.0.1:8000/monitoring/forecast-vintages` and `curl -i http://127.0.0.1:8000/admin/operations` must return 401 with no report contents. Public `/health` remains reachable.
2. Sign in as an actual Admin using the existing Cognito flow. Profile must show server-verified Admin. Model Insights must show 31 coefficient rows; sort by name/magnitude; confirm the signed price_eur_mwh and price_lag_1h values against the persisted CSV; export and inspect all 31 rows and fingerprints.
3. Pipeline Operations: inspect success versus separate forecast status, recorded row count versus new ingested/prediction rows; inspect last-100 history. Missing local incident/timing tables must say unavailable, not zero. With genuine instrumented records, filter severity/component/recent period and inspect measured stages.
4. Sign out and sign in with a genuine Analyst account. Profile must show server-verified Analyst. No coefficient/Admin operation request should be initiated by these gated panels. A direct request with that Analyst's access token to any seven detailed/alias routes must return 403. Use an authorized API client; never put real JWTs into screenshots, chat, URLs or saved scripts.
5. Expired/malformed/ID token/wrong issuer/client/scope requests must return 401. JWKS outage/invalid server verification configuration must fail closed; no anonymous fallback. Automated tests cover these with ephemeral RSA keys and mocked JWKS.
6. All seven routes: check active navigation, browser back/forward, 390px mobile drawer and desktop collapse; page tables should scroll locally without page overflow. Check missing-report and retry states, UTC filters including an empty range, market pagination, generation source selection and real chart tooltips.
7. Exports: exact displayed market page, historical one-hour report, displayed anomaly page, coefficient report, bounded execution/filtered incident views and per-release realized metrics; numeric negatives remain numeric, absent values blank, units/provenance/sampling where relevant explicit.
8. When legitimate next24/monitoring/realized evidence becomes available, restart/retry without fabricating files. Verify 24 exact target hours, unavailable/withheld overrides, exact issue hour/window nulls, and insufficient versus available realized metrics. Existing report generation prerequisites are in data-readiness.md; no flow was run in this task.

## Changed files in this phase (pre-existing Phase 4B/UI edits preserved)

Backend: `src/api/app.py`, `src/api/market_data.py`, `src/api/operations_summary.py`, `src/api/restricted_reports.py`, new `src/api/admin_operations.py`, new `src/api/feature_parity.py`.

Backend tests: `tests/test_api.py`, `tests/test_api_security.py`, new `tests/test_phase4c.py`.

Frontend: `frontend/src/api/client.ts`, `frontend/src/api/contracts.ts`, new `frontend/src/api/parity.ts`, new `frontend/src/api/csv.ts`; new `frontend/src/components/data/AdminOperations.tsx`, `CoefficientChart.tsx`, `LinearInfluence.tsx`, `ExplorationCharts.tsx`, `MarketExploration.tsx`, `ForecastEvidence.tsx`; `frontend/src/pages/AnalyticsPage.tsx`, `AnomaliesPage.tsx`, `ForecastingPage.tsx`, `ModelsPage.tsx`, `PipelinePage.tsx`; `frontend/src/index.css`; new `frontend/tests/parity.test.ts`.

Documentation: new `frontend/docs/phase4c-parity.md`, `docs/api_authentication.md`, `frontend/README.md`.

No package, lockfile, authentication implementation, Cognito settings, MLflow, trained artifact, dataset, forecasting science, Prefect flow, Streamlit, production proxy or deployment changes. No new dependencies. No commit/push/merge/deployment.

## Final validation results

- Full backend suite: **526 passed**, no failures, 27.65 seconds. Includes 19 new Phase 4C acceptance cases alongside the original API/JWT/Streamlit/scientific/pipeline regression suites. Ephemeral RSA signing keys and mocked JWKS exercise real verification for Admin, Analyst, missing token, wrong issuer/client, ID-token, expired and insufficient-scope cases. Existing Starlette/httpx TestClient deprecation warning remains; no dependency change was introduced to suppress it.
- Frontend: **33 passed**, zero failures/skips; `npm run lint` and `npm run build` pass. New tests cover coefficient identity/sign/value/count/provenance/sorting, runtime validation, null/zero distinctions, safe CSV negatives/formula escaping, Admin client routes and denial, readiness diagnostics, observed-price contracts, and same-evaluation baseline improvement.
- Persisted-data checks compare generation means and sampled weather values to actual Silver records and coefficients to the actual 31-feature CSV. Source hashes remain unchanged in those checks. Context/rolling windows and realized summaries are compared against the original Streamlit helpers on temporary fixtures, including missing hours, 4/5 and 19/20 sample boundaries, duplicate pairs, post-target issuance and multiple releases. Explicit source-resolution completeness is preserved for raw observed prices.
- Browser: existing **real Cognito Admin session** retrieved the actual protected coefficient report and bounded execution history after local API restart. All 31 row names/signs appeared; name/magnitude sorting worked. Actual full-history market statistics, generation means and weather charts rendered. All seven routes rendered at 1512px desktop and 390px mobile; document width matched viewport on every route; mobile drawer navigation worked and temporary viewport override was reset. Profile/server role remained functional. Chart and table reading order/sign labels were inspected. The original white/blue design remains.
- Browser download observation could not be confirmed: automation timed out waiting for the native coefficient CSV download event. Serialization tests pass; manually verify the downloaded file as instructed above. No fabricated success is claimed for that browser download. A chart preview was saved to `/tmp/powerflow-phase4c-coefficients.jpg`.
- Real Analyst login and a new real Cognito login/logout cycle were **not** performed in this phase. Analyst denial and invalid/expired token cases are automated with mocked JWKS; existing OIDC/logout regression tests pass. Genuine successful next24/monitoring/realized reports and populated incident/timing views cannot be demonstrated locally until legitimate evidence is supplied; fixture tests cover their supported behavior.
- Final local HTTP checks (without credentials): `/health` and `/market/price-comparison` returned 200; `/admin/operations`, `/admin/forecast/provenance`, coefficient report and both legacy monitoring aliases returned 401.
- `git diff --check` passes. Only code, tests and documentation were changed in this phase. Existing Phase 4B and UI working-tree changes were preserved. No commit, push, merge, infrastructure modification or deployment occurred.

## Recommended next phase

Conduct the documented manual dual-account acceptance review and confirm browser CSV downloads. Then perform an approved local evidence-readiness exercise using existing pipeline/report writers and legitimate source inputs, without changing completeness/withholding rules or retraining. Review coefficient report-to-artifact binding and operational history retention/instrumentation as separate hardening work. Inventory external legacy API consumers before any separately approved production rollout. The application code supports the restored views, but missing operational evidence and unperformed production/dual-account acceptance prevent a blanket claim of production readiness.
