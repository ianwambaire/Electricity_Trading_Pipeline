# Phase 5C.1 — React production readiness and feature parity

25 October 2026, Africa/Nairobi. Branch `feature/react-frontend`, observed baseline `74afaff` plus existing uncommitted Phase5B work. **Conditionally ready for isolated staging; not approved for production cutover.** This phase changes local frontend reliability, tests, artifact checks and CI. No AWS, Cognito, production API, Streamlit, deployment, account, MFA or recovery change occurred. No new dependencies were installed, and no Git staging/history operation occurred.

The final target remains React + FastAPI exclusively at **https://powerflowenergy.dev**, on the existing EC2 if the [Phase5B.3 capacity/security/recovery gates](phase5b3-capacity-and-streamlit-decoupling.md) pass. Streamlit remains operational until separately approved validation, cutover and decommissioning.

## 1. Architecture findings and improvements

| Area | Finding and local action | Boundary |
|---|---|---|
|Routing / bundle|All seven page modules were eagerly imported. They now load via React.lazy; shared authenticated route tree is retained under ProtectedRoutes. Layout-level Suspense keeps navigation available while pages load.|No new application route or authentication bypass. `WorkspaceRoutes` is also exercised directly in isolated component tests.|
|Render failures|No React error boundary existed. Root and per-path boundaries now show a generic recovery message and reload action; focus moves to the recovery heading. Changing route resets the page boundary.|No raw exception body, token or stack is deliberately displayed/logged by these components. React/browser diagnostics and all third-party behavior still require staging observation. Chunk load failure requires reload, not a fake retry of a cached rejected lazy import.|
|API client|Typed parsers, same-origin `/api`, bearer binding, no cookies, no-store,15s ordinary/30s account timeouts already existed. Requests now reject unexpected redirects and discard successful responses when their originating session/token changes, including during body reading.|No contract/endpoint or server-side authorization change. Abort/unmount remains respected. A rejected API action is not automatically repeated.|
|Authentication lifecycle|Existing code/PKCE/state/nonce/sessionStorage/renewal/expiry/logout logic preserved. Subject changes remount the server-account subtree to prevent previous account UI/form data surviving an identity switch.|No custom password flow, new scope or Cognito setting. Refresh-token renewal for the same subject does not deliberately clear all page state.|
|Polling|setInterval could overlap slow requests. useApi now schedules the next automatic refresh only after the previous one completes and cancels pending work on dependency change/unmount.|During loading/error, previous data is cleared; no stale value is silently represented as current. Interval label explicitly says “after completion”.|
|Historical report|The full one-hour report was fetched every minute although the chart uses its last500rows. It now loads once per page mount with explicit manual refresh.|Full-history CSV remains available; no silent truncation, stale result cache or backend pagination claim. Large response still a production resource concern.|
|Downloads|Most CSV actions had no failure feedback;24h forecast used a separate implementation. All now use shared initiation/cleanup, a safe error announcement and dismiss control.|Browser download completion/save permission cannot be confirmed. UI never claims a file was saved. Forecast CSV preserves existing availability classification and columns.|
|Accessibility|Existing skip link, named landmarks, active navigation, main focus, labelled filters/native dialog retained. Scrollable tables are keyboard focusable; error recovery focus and download announcements added. Narrow account content can shrink/wrap.|No WCAG certification or full screen-reader/zoom claim. Successful data-filled chart/table acceptance remains a staging gate.|
|Production artifacts|Explicit sourcemap=false; public production environment example with blank client ID; build checker rejects maps/test/source directories and fixture sentinels, validates HTML-referenced static files and reports sizes.|Does not validate installed Nginx, inspect every potential secret, approve an OAuth client or create a deployable production configuration.|
|Continuous validation|Added frontend CI job using existing lock: npm ci/test/lint/build, artifact checks and high-severity audit threshold.|No deploy step, AWS permission, secret or identity access added. CI has been edited locally, not run by GitHub in this phase.|

No global state framework, query cache or chart framework was added. Existing local useState/useApi and centralized server-account context remain sufficient for this scope. Avoiding overlapping polls and reducing eager route code are supported by the observed behavior; speculative memoization/global caching was not introduced.

## 2. Seven-page Streamlit replacement matrix

“Implemented” below describes local source/test evidence, not installed production acceptance. Public API data visibility is intentional; protected React navigation alone is not server authorization. The backend retains seven Admin-only report routes (five `/admin/*` endpoints and two legacy monitoring aliases), plus separately authenticated own-account operations.

| Streamlit feature / React page | React functionality and FastAPI endpoints | Authentication / coverage | Remaining gap and readiness |
|---|---|---|---|
|Executive Overview → `/`|Historical price/load/row/anomaly KPIs, coverage, price/load–wind+solar charts, latest observations, health and forecast state. `/market/summary`, `/market/chart`, `/anomalies/summary`, `/operations/summary`, `/pipeline/status`, `/forecast/next24`, `/health`.|Protected UI; public-safe API observations. Route/error/focus/units-contract tests, historical KPI parity covered by backend tests.|Implemented; validate coherent installed publications and real data-filled responsive charts. Market coverage is not source completeness or live pricing.|
|Market Intelligence → `/analytics`|Price/load/source generation/renewable mix, weather, full-range statistics, UTC date filtering, exact paginated observations and scoped exports. `/market/coverage`, `/market/history`, `/market/summary`, `/market/exploration`.|Protected UI; public observations. Date/form, parser, source parity, pagination tests.|Implemented; detailed queries remain bounded and exports labelled displayed/sampled scope. Full-range export beyond displayed pages is not silently promised; owner must accept scoped export difference.|
|Forecasting → `/forecasting`|24h chart/statistics/table/availability-labelled CSV; observed-price comparison; exact issue-hour inputs; separate one-hour historical chart/export/evaluation; realized evaluation and Admin provenance. `/forecast/next24`, `/forecast/one-hour`, `/forecast/context`, `/forecast/realized-evaluation`, `/market/price-comparison`, `/models/summary`, `/admin/forecast/provenance`.|Public-safe forecast evidence; Admin provenance verified server-side.24row/horizon/negative-price/UTC/state/CSV tests; separate model identity and realized thresholds tested.|Implemented presentation; genuine local next24/evaluation reports missing, so live success/withholding publication must be stage-tested. Full historical response growth remains an API capacity/contract gate.|
|Anomaly Detection → `/anomalies`|Persisted Isolation Forest observations, summary, independently supplied markers, filters, exact events and paginated CSV. `/anomalies/summary`, `/anomalies/events`, `/market/chart`.|Protected UI/public historical observations; no model fitting or fabricated severity. Route/missing/empty/contract/source parity tests.|Implemented; validate real marker interactions, target-time alignment, keyboard-readable summaries and chart/table layouts under populated data.|
|Model Insights → `/models`|Distinct production HGB24h and separate Linear Regression1h metadata/evaluation/lineage; Admin coefficient influence. `/models/summary`, `/admin/models/linear-feature-influence`.|Public approved summary; server Admin coefficient permission. Model attribution/parsing/backend artifact and role tests.|Implemented; HGB feature importance is not invented from linear coefficients. Missing metadata remains explicit; deployed artifact versions must match.|
|Pipeline Summary → `/pipeline`|Source/quality/freshness/product states, pipeline status; Admin runs/incidents/filter/export/timings/vintages/readiness. `/operations/summary`, `/pipeline/status`, `/admin/operations`, `/admin/monitoring/forecast-vintages`, `/admin/monitoring/exogenous-readiness`.|Public-safe summary; all details server Admin. Analyst absence of Admin requests and Admin403display now component-tested; real JWT guard regressions run backend.|Implemented; raw messages/configuration deliberately withheld. Latest100runs/100incidents/200timings bounded. Local absent monitoring/timing evidence is not zero incidents or healthy pipeline; genuine publication required.|
|Account → `/profile` (React addition)|Human identity, supported profile edits, native password actions, federated guidance, explicit reconnection, current/all-device sign-out and eligible security status. `/auth/me`, authenticated `/account/*`.|Server-confirmed role/capabilities and own-subject tokens. Existing profile/native/federated/password/MFA tests retained; new route failure and session-race tests.|Implemented supported actions; email changes/general MFA enrollment/removal/lost-device recovery remain unavailable or deferred. No new live account changes performed.|

Safe operational summaries, bounded exports, read-only web analytics and separate account operations are intentional migration decisions. Reproducing sensitive raw Streamlit internals or allowing Analyst administrative access is not a parity requirement. No Streamlit feature/code was deleted. Existing Streamlit UI calculations and adapter tests remain intact from Phase5B.3.

## 3. Authentication and security review

Local source inspection includes AuthenticationRoot, runtime, oidcSettings, config, identity, ProtectedRoutes, ServerAccountProvider, accessToken, logout/signOutCurrentSession and account/MFA components; existing oidc-client-ts3.5 code was inspected for state/nonce checks.

- Code response type, S256 PKCE, library-owned one-use state and nonce binding remain. Sign-in and explicit account reconnection generate fresh nonce; account reconnect requests existing four scopes with prompt=login. Library tests verify verifier/challenge binding, state replay rejection, mismatched nonce and absence of a browser client secret.
- Local profile checks bind issuer/client/token_use/expiration for UI session usability. **FastAPI verifies signature/JWKS/issuer/client/token type/expiry and groups**; frontend claims never authorize an operation. UI role comes from `/auth/me`, is matched to session subject and clears on failure/change.
- Tokens/transactions remain in tab sessionStorage, not localStorage; library logging remains NONE. This reduces persistence but does not protect against XSS. Approved HTTPS/CSP/build integrity and least-privilege account/API controls remain required.
- Automatic silent renewal is configured; refresh token behavior depends on actual Cognito issuance, client settings and browser support. Expiry/renewal errors remove the user;401invalidates only the originating session;403preserves session and displays denied state. The new success guard also rejects late bodies from old sessions. Public requests without credentials can still succeed where intended.
- Hosted callback is restricted to `/auth/callback`; post-login destinations are an allowlist of seven local paths. Query code/state is removed after callback success/error. Web/proxy access logs must not retain raw callback query strings. Do not decode raw user tokens for authorization or copy callback URLs into logs.
- Sign-out stops renewal, removes local user/transactions and redirects through the existing Cognito logout. It is not a claim of global provider logout/revoking all access tokens. The separately supported all-device action remains explicit. Out-of-band/session revocation behavior must be retested on staging.
- Subject-keyed provider remounts clear account UI when identities change; useApi aborts prior queries; request completion/body reading checks current binding. No optimistic mutation retry was added. A network failure after an account mutation may have an uncertain outcome; refresh/reconfirm rather than replay it automatically.
- General-user enrollment remains disabled by backend deployed-mode controls. Existing dedicated-account native TOTP compatibility is historical acceptance, not retested live or broadened here. Google accounts are not assumed to possess a Cognito password. No recovery, password change, enrollment or group mutation occurred.

New role tests intentionally render a test-only authenticated context to examine visibility and server-denial handling. They are not real sign-in tests. A separate production route-gate test verifies no workspace request is started when signed out/expired/authentication-failed; missing Node test configuration fails closed. No claim is made that mocked tests validate current production Google/native/Cognito configuration.

## 4. Exact production configuration requirements — proposals only

The reviewed template is `frontend/.env.production.example`. It is public and does not load automatically. Client ID stays blank until separately approved production SPA client creation/configuration. Blank settings fail closed; the template alone is **not deployable authentication**.

```dotenv
VITE_COGNITO_AUTHORITY=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_NLoYFRvex
VITE_COGNITO_DOMAIN=https://us-east-1nloyfrvex.auth.us-east-1.amazoncognito.com
VITE_COGNITO_CLIENT_ID=<approved-production-public-SPA-client-id>
VITE_COGNITO_REDIRECT_URI=https://powerflowenergy.dev/auth/callback
VITE_COGNITO_POST_LOGOUT_REDIRECT_URI=https://powerflowenergy.dev/
```

The angle-bracket client value above is a documentation placeholder, not a valid configured client. Use process/build-environment public values to avoid an existing `.env.local` overriding the intended production values. Vite env values are compiled into JavaScript; changing server environment after build does not alter the bundle. Never use VITE_* for passwords, client secrets, provider secrets, AWS keys or tokens. Existing local/Streamlit clients remain unchanged. Required callback/logout URLs must be allowed on the approved new production client before testing; scope/attribute/provider decisions remain the exact approval packet in Phase5B.2.

API base is deliberately fixed to **relative `/api`**. There is no arbitrary remote API-origin environment override and no browser API credential. Deploy at domain root, HTTPS only; canonicalize www to apex before sign-in. The Vite dev proxy is local development only; `vite preview` is a static smoke-test server and does not supply the production API proxy. Do not run Vite/Node as the production web service.

### Required Nginx behavior (documented, not installed)

- Serve only a reviewed immutable **dist/** release, never repository/dev-server/test/source directories or environment files. Existing domain/IP/certificate may be reused if verified; no DNS change inherently needed.
- `/auth/callback` and seven SPA paths fall back to index.html. Missing hashed `/assets/*` files return404, not HTML. `/api/*` failures/unknown routes remain JSON/API errors, never the SPA.
- Proxy `/api/` to loopback8000 stripping the prefix, matching actual FastAPI routes. The port is already occupied: use an explicitly approved replacement/private-validation plan. Trusted Host/forwarding headers are proxy-controlled; no public8000, wildcard CORS or blind trust in client-supplied forwarded values.
- Keep `/api/ready` and slash variants private under management-only policy; do not accidentally publish through the broad proxy. Public health policy must be explicitly approved. Preserve all existing server-side authorization dependencies, including legacy monitoring aliases.
- index.html must revalidate/no-cache; hashed assets can be `public,max-age=31536000,immutable`. Keep previous hashed assets for rollback/older tabs; no service worker or hidden response cache was introduced. Source maps remain unpublished. API remains no-store. Review font/favicon cache separately (names are not all content-hashed).
- Use Phase5B.2 request body/timeouts/rate budgets after staged testing. API requests now reject redirects: do not make an API401redirect to a hosted login page. React owns sign-in.
- Preserve previous Streamlit routing/unit/client configuration for rollback; `/oauth2callback` is not React's callback. A cutover may require fresh sign-in. Do not stop Streamlit, reload Nginx or rotate certificates in this phase.

### HTTPS and CSP compatibility

Current production certificate/renewal/installed headers still need the Phase5B host review. Recommended controls are nosniff, frame denial, no-referrer and a reviewed CSP, initially Report-Only on the staging hostname. Do not enable broad HSTS includeSubDomains without ownership/compatibility review.

Candidate production CSP for testing (not a validated enforced policy):

```text
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self' https://cognito-idp.us-east-1.amazonaws.com https://us-east-1nloyfrvex.auth.us-east-1.amazoncognito.com; frame-src 'self' https://us-east-1nloyfrvex.auth.us-east-1.amazoncognito.com; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self' https://us-east-1nloyfrvex.auth.us-east-1.amazoncognito.com
```

Recharts/React use inline style properties, so an untested blanket style ban can break charts. No unsafe-inline/eval script allowance is proposed. Fonts are served locally. Verify actual OIDC refresh/iframe behavior, hosted navigation, lazy chunks, CSV blob downloads and chart styles under Report-Only before enforcing; candidate origins are not evidence of successful live provider connectivity. Do not copy development HMR/websocket CSP exceptions into production.

Proxy/HTTP telemetry must omit code/state query strings, Authorization, cookies, request bodies, raw provider errors and user-controlled callback details. Use fixed generated request IDs/status/timing, not raw full request URLs. No new analytics/third-party telemetry was added. The app handles API errors safely but cannot sanitize a misconfigured upstream access log by itself.

## 5. Performance evidence and limitations

Baseline built output from earlier local build before route splitting: entry458,339bytes, gzip134,535bytes; total JS876,351bytes in13chunks. Updated figures below use Node22.22.0 `gzipSync` default settings consistently; Vite prints slightly different compressed estimates.

| Artifact measurement | Baseline | Updated |
|---|---:|---:|
|Entry JavaScript|458,339 B|376,359 B (about17.9% smaller)|
|Entry gzip|134,535 B|114,072 B (about15.2% smaller)|
|All JavaScript, not all initial downloads|876,351 B|886,058 B (about1.1% larger)|
|JS chunks|13|30|
|Published source maps / test sources|No new baseline certification|0 /0, checked|

The entry alone is not total initial transfer (HTML/CSS/font/preloaded dependencies also load). Splitting defers page/account components; charts remain separate lazy chunks. The main chart dependency chunk is still about338.5KB raw/99.2KB Vite gzip. Total JS increased slightly with reliability controls and chunk overhead. No invented Lighthouse score, browser heap measurement, slow-network latency or EC2 responsiveness is reported.

Requests are parallel within pages; dependent context/provenance requests legitimately wait for source issue/role evidence. One server-account context handles role checks rather than each component creating a new session. No new request cache/dedup library was added; polling now cannot overlap and historical report automatic polling is off. The full14,878row historical API response remains about1.69MB uncompressed (Phase5B.3), even though chart points are capped500; approve bounded API/export evolution before scaling public exposure. Frontend changes do not solve backend memory limits.

Tables remain bounded/paginated (market1000, events100, administrative views100/200). Charts use bounded source points and explicit gaps; no virtualization framework was justified for this patch. React clock updates can still rerender time-dependent charts; no speculative memoization was added without profiling. Representative live-data browser CPU/heap/slow-network profiling remains staging work.

## 6. Interface, accessibility and browser checks

Established white sidebar, pale-blue navigation, blue actions, neutral background, white cards and Source Sans3 remain. No layout redesign/gradient/decorative animation was introduced. Existing reduced-motion handling, labelled chart descriptions/exact tables, UTC units, focus outline and native dialog remain.

Calculated contrast on white for existing tokens: action #0866F5 **4.97:1**, body #334155 **10.35:1**, secondary #64748B **4.76:1**, headings #152C49 **14.11:1**. This checks these text/background pairs only, not every disabled state, chart line, hover combination or rendered font size.

New keyboard-focusable table scroll containers permit horizontal keyboard scrolling. Download errors are announced and dismissible. Error boundaries focus a safe recovery heading. Existing labelled date filters reject partial/reversed ranges and use explicit UTC bounds. Existing route main-focus and active aria-current are regression-tested.

### Browser method and actual results

The local production preview on loopback4173 displayed the signed-out gate, including direct `/profile` refresh. Its build still used local callback settings, so4173correctly warned about the configured localhost5175origin; no real sign-in was attempted. This is SPA fallback/gate evidence, not production callback acceptance.

For protected-layout visual checks, `tests/browser/index.html` is an explicitly labelled development-only fixture. It uses a test Analyst context, blank Cognito client build override and503responses for every request. It contains **no real account, token or invented market values**, makes no real account/API mutation and is excluded from production dist by entry selection and artifact checks. It is not a supported application route or auth fallback. Never publish the source tree/dev harness.

All seven pages rendered their expected headings/error states at **390×900,768×900 and1280×900** (21checks). For every check, document scrollWidth equalled viewport width: no page-level horizontal overflow. Desktop account layout was visually inspected; the established sidebar/card/type hierarchy remained. Native mobile dialog at390×844opened and closed with Escape; focus returned to “Open navigation”. Temporary viewport override was reset. Development/preview servers were stopped after checking.

Limitations: this browser pass covers API-unavailable states, not populated Recharts/tooltips, native password/MFA flows, Admin data or full browser downloads. Native dialog behavior is browser-checked; JSDOM tests alone do not emulate top-layer focus trapping. Screen-reader announcements,200%zoom,320pxlayouts, Safari/Firefox and real slow-network/heap profiling were not exhaustively tested. These are explicit staging acceptance tasks, not passes inferred from source review.

## 7. Error and operational scenario coverage

| Scenario | Evidence / behavior |
|---|---|
|Backend unavailable / timeout|Client uses bounded signals and fixed safe network text; test injects TimeoutError, never surfaces private network diagnostics. All seven error-state pages browser-checked.|
|401 /403 / revoked or replaced session|Existing tests cover401expiry and403preservation; new tests discard late success/body responses and forbid old roles from controlling UI. Backend JWT/Admin regressions remain authoritative.|
|Signed out / expired / callback error|ProtectedRoutes returns loading/sign-in rather than starting page data requests. Library state/nonce tests plus gate tests; no new live provider acceptance.|
|Missing / empty / partial report|404distinct from malformed503; parsers reject partial bodies, counts, timestamps and nonfinite values. Existing empty/anomaly/market/evaluation tests remain. No substitution from another endpoint.|
|Stale / historical / withheld forecast|Existing recency and availability classifier preserved; withholding overrides retained reports. Recent report is explicitly unverified, not live. CSV includes displayed classification.|
|Pipeline failure|Public-safe status/reason and age shown separately from forecast values; execution success never proves issuance. Existing backend/contract tests retained.|
|Slow request / navigation|Next poll starts only after completion; retry/changed query/unmount abort old work. Late results ignored. No stale-data cache added.|
|Download failure|Object-URL/click errors produce shared safe alert; anchors removed and URLs revoked. Native saved-file completion is outside browser API guarantees.24hforecast now shares this path.|
|Chunk/render failure|Generic focused reload recovery; no exception text rendered. Route boundary resets on navigation. Actual mid-deploy stale chunk rollout still needs staged rehearsal.|
|Nested direct navigation|Actual preview `/profile` fallback/sign-in passed; isolated route tests cover all seven paths. Installed Nginx behavior still unverified.|

## 8. Validation commands and results

Run from frontend unless specified. No dependencies were installed locally; npm advisory requests were read-only. Node22.22.0/npm10.9.4/macOS arm64; JSDOM component tests. No fresh full651backend run claimed in this frontend-only phase; relevant backend subset ran below.

| Command | Result |
|---|---|
|`npm test`|**81passed**,0failed (60existing +21new readiness cases); final log `/tmp/pf5c1-tests-final-validation.log`|
|`npm run lint`|Passed; final log `/tmp/pf5c1-lint-final-validation.log`|
|`npm run build`|Passed, including `tsc -b`; final log `/tmp/pf5c1-build-final-validation.log`|
|`node scripts/check-build.mjs`|Passed asset references, no source maps/test fixture payload; outputs byte counts above|
|`npm audit --json`|**0known vulnerabilities** across reported342dependency nodes (84prod/182dev plus optional/peer categories); `/tmp/pf5c1-dependency-audit.json`. Registry results are time-scoped, not a comprehensive supply-chain/CVE certification.|
|Relevant backend subset below|**220passed**,7.77s; `/tmp/pf5c1-backend.log`|
|Browser UI checks|21fixture viewport/page checks plus signed-out nested fallback and native Escape/focus restoration; limits above|

Backend command from repository root:

```sh
venv/bin/python -m pytest -q tests/test_api.py tests/test_api_security.py tests/test_account_management.py tests/test_mfa.py tests/test_backend_hardening.py tests/test_public_market_api.py tests/test_phase4c.py tests/test_phase5_restoration.py
```

Frontend reproduction:

```sh
cd frontend
npm test
npm run lint
npm run build
node scripts/check-build.mjs
npm audit --json
npm run preview -- --host 127.0.0.1 --port 4173 --strictPort
```

Preview is static only, with no dev API proxy; it is not production. For the labelled error-state layout fixture use a separate local shell:

```sh
cd frontend
VITE_COGNITO_CLIENT_ID= npm run dev -- --host 127.0.0.1 --port 4174 --strictPort
```

Open `http://127.0.0.1:4174/tests/browser/index.html?route=%2Fprofile` (or another seven-page path). The blank process override prevents a real Cognito manager in this fixture. Stop servers after use. Real local sign-in requires the approved localhost5175origin and existing normal frontend environment, not this test harness.

The first new test run caught a too-strict handling of an already-rejected session: public unauthenticated reads were being rejected as a session change. Capture now distinguishes rejected/no-token requests from pending authenticated requests; existing auth tests pass again. One unused test import was removed after lint. Initial shell invocations from repository root had no package.json; all reported npm validations ran from frontend. A sandbox loopback-listen denial was resolved through approved local execution, not a security/configuration workaround. No unresolved test/lint/build failure remains.

## 9. Staging acceptance and cutover checklist

**Isolated staging is conditional** on the following, requiring separate change/test approval where applicable:

1. Clean Linux frontend/API builds with reviewed lockfiles, artifact digest, no secret-bearing VITE settings and no tests/source maps published; runtime API config/permissions validated under the dedicated service account.
2. Approved staging origin/client/scopes and exact callbacks/logout. Current production origin/client changes remain proposals. Sharing a pool does not isolate user accounts; no live mutation/recovery/MFA enrollment is implied.
3. Static HTTPS host with real seven-route refresh/history fallback, correct `/api` prefix/no-store/errors, private readiness, certificate trust/renewal, safe proxy logging and tested rate/body/timeouts.
4. Recent coherent publications and recoverable backups. Real next24success/withholding, realized evaluation, monitoring and incident/timing evidence validated without fabrication. Resolve full-history API exposure/performance decision.
5. Desktop/tablet/mobile **data-filled** charts, tables, filters, pagination, scoped CSV, keyboard/zoom/screen-reader checks; measured slow-network/API-failure behavior and chart CPU/heap/request waterfall.
6. Separately approved real Google Admin/native Analyst/already-enrolled TOTP checks: callback/state/expiry/refresh/sign-out; all seven Analyst Admin403s, unauthenticated401s and permitted own-account capabilities. No regular MFA enrollment or lost-device recovery claim.
7. Enforced CSP only after Report-Only review; no token/code/query leakage, unexpected network origins, redirect following, stale account display or permissions fallback. Verify returned session/client binding through FastAPI.
8. Measured EC2 headroom during scheduled pipeline plus API traffic, cold rebuild/restart and backup workspace; retain single writer and previously identified encryption/restore/identity gates.
9. Owner signs off Streamlit parity/deliberate safe differences before approving production cutover. Existing Streamlit remains unchanged throughout preparation.

For final **powerflowenergy.dev** cutover: approve exact Nginx/client/service/release changes; preserve known-good Streamlit API/proxy/client/runtime configuration and previous hashed assets; precheck private readiness and syntax; use approved graceful routing switch with a rollback operator and maintenance decision window. Monitor401/403/errors, callback loops, freshness/withholding, scheduled runs, memory/swap/disk, certificate/backup age and gross spend. Root-domain reuse does not authorize a DNS change.

Rollback restores the compatible previous static/API/proxy configuration and original Streamlit entry point as separately approved, with fresh sign-in if necessary. Do not roll back persisted databases just to change frontend code or delete old assets before the retention window. Streamlit stop/disable/dependency/client/secret removal occurs only after production acceptance, observation and **separate decommission approval**. No deployment was executed.

## 10. Files changed in Phase5C.1

- `frontend/src/App.tsx`: lazy authenticated route tree and loading boundary.
- `frontend/src/main.tsx`, `components/ui/ErrorBoundary.tsx`: root/page recovery.
- `frontend/src/components/layout/AppLayout.tsx`: persistent layout loading, per-path boundary, shared download alerts.
- `frontend/src/api/accessToken.ts`, `api/client.ts`, `auth/AuthenticationRoot.tsx`: current-session response guard, redirect rejection and subject remount.
- `frontend/src/hooks/useApi.ts`, `components/data/ApiPanel.tsx`, `pages/ForecastingPage.tsx`: sequential polling, accurate refresh labels, manual historical refresh.
- `frontend/src/api/csv.ts`, `components/ui/DownloadStatus.tsx`, `components/data/ForecastSummary.tsx`: common safe CSV initiation/error/cleanup without changing forecast CSV content.
- Keyboard-scrollable table containers: `frontend/src/components/data/{AdminOperations,ForecastChart,ForecastEvidence,LinearInfluence,MarketExploration}.tsx` and `frontend/src/pages/{AnalyticsPage,AnomaliesPage,MarketOverview,PipelinePage}.tsx`.
- `frontend/src/index.css`: narrow content wrapping/focus styling, established theme preserved.
- `frontend/index.html`, `vite.config.ts`, `.env.production.example`, `.gitignore`: production description, no maps, public approved-settings template exception only. Real env files remain ignored.
- `frontend/tests/readiness.test.tsx`, `tests/browser/{index.html,main.tsx}`: isolated component and labelled browser fixtures, excluded from production.
- `frontend/scripts/check-build.mjs`: local artifact assertions/size measurement.
- `.github/workflows/ci.yml`: frontend test/build/audit job, preserving earlier API job improvements.
- `frontend/docs/phase5c1-react-production-readiness.md`: this report.

Earlier Phase5A/5B documentation/backend/shared-helper files were already dirty at task start and remain untouched in this phase. No frontend dependency manifest/lock, FastAPI implementation, model, pipeline, Cognito setting, account or production service was changed. The final readiness classification is **conditionally ready for isolated staging**, with real data-filled/identity/installed-host acceptance still required before production replacement.
