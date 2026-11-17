> Phase 4C update (21 October 2026): the user approved closing the legacy monitoring exposure. Both `/monitoring/*` routes are now deprecated Admin-only aliases returning the same bounded allowlists as `/admin/monitoring/*`. Anonymous 401, Analyst 403. `/admin/operations` adds safe bounded operational history. No production rollout has occurred. The current complete access matrix, compatibility/rollback plan and acceptance instructions are in [Phase 4C](../frontend/docs/phase4c-parity.md). Historical Phase 4B validation below describes that earlier stage and is superseded where it says legacy routes remain public.

# Phase 4B — FastAPI Cognito access-token verification and authorization

Implemented locally on `feature/react-frontend`. No deployment, AWS/Cognito changes, client-secret use, Streamlit changes, model execution, pipeline changes, dataset writes, commits or pushes occurred. Earlier React authentication and blue/white theme work are preserved.

## Architecture

React signs in through its existing public Cognito SPA client with Code + PKCE. Its existing client sends **access tokens**, never ID tokens, to same-origin `/api`. New FastAPI dependencies verify the signature with trusted Cognito public JWKS, validate claims, then derive a minimal principal and role. No AWS credentials are needed.

`joserfc==1.7.7` is now a direct pinned requirement. It was already installed transitively with Authlib, so no package installation or environment upgrade was needed. This maintained Authlib JOSE successor avoids the deprecated `authlib.jose` interface. Cryptographic verification is performed by `joserfc`, not custom code. See [joserfc JWT documentation](https://jose.authlib.org/en/guide/jwt/) and [AWS Cognito verification requirements](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html).

### Verification policy

- Exactly one Bearer Authorization header, bounded compact JWT (16 KiB).
- Only RS256 and a public RSA signing key of at least 2048 bits. Embedded keys, alternate key URLs and unexpected JOSE headers are rejected; the unverified `kid` is only a key-selection hint.
- JWKS URL derives exclusively from validated **server configuration**, not token issuer/header URLs. HTTPS certificate validation stays enabled; redirects and environment-derived proxies are disabled.
- Signature verification precedes use of identity, role or scopes. Required typed claims include exact issuer, `token_use=access`, allowed `client_id`, Cognito UUID subject, `exp`, `iat`, and `scope`. ID tokens are rejected even if correctly signed by the same pool.
- Expiration is enforced with no configurable relaxation. Issued-at/not-before checks use the library validators. `openid` is required for this interactive-user API; optional additional required scopes are conjunctive, never a substitute for `openid`.
- Existing SPA tokens are not resource-bound: their client binding is `client_id`, **not an assumed ID-token audience**. When no resource audience is configured, an unexpected `aud` is rejected. If a resource audience is explicitly configured, an exact string match is required. No wildcard clients/audiences or unverified role headers/parameters are accepted. See [AWS access token claims](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html).
- A verified `cognito:groups` array containing exactly `powerflow-admins` grants Admin. Missing, unrelated or malformed groups remain Analyst. No role is taken from request query/body, browser storage, email domains or frontend ID-token role labels.
- Missing/invalid/expired authentication is generic HTTP 401 with `WWW-Authenticate: Bearer`. A valid Analyst attempting Admin reporting receives 403. Unavailable/invalid identity configuration or a JWKS retrieval failure returns generic 503 for requests needing verification; it never opens a route or silently accepts expired cached keys.
- Identity/report success responses and authentication/authorization errors carry no-store headers. Tokens, raw claims, credentials and detailed verification exceptions are never intentionally logged or returned.

### JWKS availability and rotation

Each API process caches at most 16 public signing keys for five minutes. A lock provides single-flight refresh. An unknown valid-shaped `kid` can trigger one forced refresh per 30 seconds; arbitrary unknown IDs do not create an unbounded negative cache. This permits rotation while limiting unauthenticated fetch amplification. A newly rotated key can briefly be rejected during the unknown-key cooldown; retry after 30 seconds rather than weakening verification.

Requests use a two-second connect timeout and five-second HTTP read/write/pool timeout, a 64 KiB response cap and a fixed trusted URL. Failed retrieval has a five-second retry backoff. An expired cache never falls back to stale keys. A still-valid cached known key remains usable during an unknown-key lookup failure until its normal cache expiry; this is bounded trusted-key caching, not acceptance of unverified tokens. Cache state is per worker and contains no users or tokens.

## Endpoint inventory and access-control matrix

The inventory was reported before implementation. Streamlit's checked dashboard/auth/data/health modules read local reports and SQLite directly; no call to these FastAPI URLs was found. Repository inspection cannot establish whether **external** consumers use the already-deployed unauthenticated endpoints. Existing regression tests explicitly assert those public contracts. Therefore this phase is additive.

| GET route | Access after Phase 4B | Compatibility / purpose |
| --- | --- | --- |
| `/health` | Public | Unchanged service response |
| `/pipeline/status` | Public | Unchanged minimal recorded run/forecast status |
| `/forecast/next24` | Public | Unchanged persisted forecast, including existing missing/invalid behavior |
| `/forecast/one-hour` | Public | Unchanged historical forecast contract |
| `/market/coverage` | Public | Unchanged safe coverage |
| `/market/history` | Public | Unchanged bounded observations |
| `/market/summary` | Public | Unchanged whole-range statistics |
| `/market/chart` | Public | Unchanged bounded chart samples |
| `/models/summary` | Public | Existing approved public release/metric allowlist |
| `/anomalies/summary` | Public | Unchanged active historical anomaly summary |
| `/anomalies/events` | Public | Unchanged bounded historical events |
| `/operations/summary` | Public | Existing approved public-safe summary; no detailed operational history/configuration |
| `/monitoring/forecast-vintages` | **Admin; deprecated authenticated alias** | Same safe allowlisted response as Admin counterpart; no raw-report fallback |
| `/monitoring/exogenous-readiness` | **Admin; deprecated authenticated alias** | Same safe allowlisted response as Admin counterpart; no raw-report fallback |
| `/auth/me` | Any verified authenticated user | Own Cognito subject, server-confirmed Admin/Analyst, optional email/name only when actually present in the access token |
| `/admin/monitoring/forecast-vintages` | Admin | New bounded allowlist: known sources/statuses, timestamps and available coverage/revision/failure counts; no paths/raw reasons/messages |
| `/admin/monitoring/exogenous-readiness` | Admin | New bounded allowlist: generated time, engineering readiness/counts and recorded leakage-check boolean; no dataset path or arbitrary nested reports |
| `/admin/models/linear-feature-influence` | Admin | New bounded 31-feature one-hour report, signed coefficients and absolute magnitudes, known feature identifiers and explicit provenance limitations |

All other application routes are absent; no administrative or data-writing action was added. FastAPI's standard docs/OpenAPI endpoints remain public discovery surfaces and describe the Bearer scheme. Obscurity is not an access-control measure.

### Important unresolved legacy exposure

The two legacy monitoring routes return arbitrary persisted report fields after **key-name-based** redaction. That does not guarantee removal of paths, free-text secrets, internal identifiers, or operational information nested under innocent keys. Adding protected counterparts **does not secure those legacy URLs**, and restricting React's UI does not fix that exposure. This risk is deliberately documented, not treated as a completed security migration.

Safe migration proposal, requiring consumer confirmation and a separately approved deployment:

1. Inventory deployed consumers/access logs under the existing operational process; do not collect/log bearer headers. This implementation did not access production.
2. Switch React to the new protected paths (done locally), and migrate any other approved consumer to verified access tokens and appropriate permissions.
3. If only public readiness is needed, define an explicitly allowlisted public status contract and migrate consumers to it. Do not reuse full report JSON as a public contract.
4. Approve authentication or retirement for the two old URLs; then remove their public report bodies. Unknown external compatibility cannot be presumed away. Streamlit's file-based dashboard needs no API token merely to keep its present behavior.
5. Verify the production proxy forwards Authorization and existing Streamlit service/callback behavior remains correct. No Nginx, AWS, Cognito or deployment configuration changed here.

Until this migration is completed, do not describe the **whole API** as secured or expose new sensitive detail through legacy paths. Original pipeline-status fields also remain a legacy public contract; this phase adds no raw messages there.

## Restricted report boundaries

Admin monitoring responses are explicitly typed and bounded. Unknown fields, filesystem paths, raw messages/reasons, infrastructure identifiers, credentials and arbitrary nested dictionaries are not returned, including to Admin. Reports are read from existing fixed paths with a 1 MiB JSON cap. Missing report is 404 after authorization; malformed/unreadable report is sanitized 503. Authorization runs before file access, so unauthenticated/Analyst requests cannot probe availability.

Linear influence reads only the existing CSV with a 64 KiB/31-row cap and a frozen 31-identifier allowlist. It requires consistent one-hour release metadata, finite signed coefficients, absolute magnitudes equal to their absolute coefficients, and exactly one of each expected feature. It never loads an ML model, imports a fitting script, fits a detector, or regenerates reports. Tests compare the identifier allowlist with the existing frozen feature definition and compare the endpoint with actual persisted values.

The existing report has **no cryptographic report-to-model binding or recorded report generation timestamp**. The response explicitly states association by the existing one-hour writer and includes the metadata fingerprint without pretending that it attests to the coefficient file. These are standardized Linear Regression associations, not causal effects and not HGB feature importance. A stronger artifact-bound report provenance workflow remains separate work; models/report generation were not changed.

Detailed execution history, internal timings, incidents, full operational messages and configuration still have **no new endpoint**. Their restoration needs separately designed bounded schemas and the now-available Admin dependency. No public bypass was introduced to restore them.

## React changes

The existing session lifecycle now wraps a server-account provider. `/auth/me` is loaded after OIDC authentication, refreshed on session changes and every 60 seconds, and matched to the signed-in subject. A previous user's role never survives a session change/error. Navigation, profile and authorization-sensitive status text use the server role; an unavailable server check yields “Role unavailable”, not an ID-token Admin fallback.

Monitoring calls use only `/admin/monitoring/...`; there is no fallback to legacy public routes on 401/403/404. Existing API handling clears local authentication and prompts explicit reauthentication on 401; 403 is an access-denied state; 503 preserves the session and offers retry. No automatic sign-in redirect loop is added. Public analytics/forecast pages and all seven routes remain in place. Sign-in/logout, PKCE configuration, session storage and the blue/white CSS are unchanged.

The coefficient endpoint is available for authorized use, but its React chart/table restoration is intentionally deferred. Its section now distinguishes server-confirmed Admin access from pending UI restoration, instead of falsely claiming server authentication is still absent.

## Environment and exact local startup

Added non-secret examples to the root `.env.example`:

- **Required:** `POWERFLOW_API_COGNITO_ISSUER=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_NLoYFRvex`
- **Required:** `POWERFLOW_API_COGNITO_CLIENT_IDS=4t8s6a673a18qhbauqac8rhdcf` (comma-separated explicit allowlist if additional approved API clients are needed; not `*`). The Streamlit confidential client is not automatically added.
- Optional `POWERFLOW_API_REQUIRED_SCOPES`: space-separated **additional** required scopes. Do not add scopes that the existing SPA client does not actually receive. `openid` always remains required.
- Optional `POWERFLOW_API_COGNITO_AUDIENCE`: exact intended resource audience, only when tokens are explicitly resource-bound. Leave unset for the present SPA tokens; setting it does not modify Cognito or request a new resource from React.

FastAPI does not silently load root `.env`. Export these public values into the process environment. Missing/invalid config keeps protected requests closed without disabling old public routes. No production environment file/service was modified. Local clock must be accurate for JWT expiry/not-before validation.

Terminal 1:

```sh
cd /Users/iannganga/Desktop/electricity-trading-pipeline
export POWERFLOW_API_COGNITO_ISSUER=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_NLoYFRvex
export POWERFLOW_API_COGNITO_CLIENT_IDS=4t8s6a673a18qhbauqac8rhdcf
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./venv/bin/python -B -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```sh
cd /Users/iannganga/Desktop/electricity-trading-pipeline/frontend
npm run dev -- --host localhost --port 5175 --strictPort
```

Use existing frontend `.env.local`/`.env.example` from Phase 4A; no frontend Cognito setting changes are needed. If the API is already running, restart that **local** process with the exported public settings. Do not alter production services. Open `http://localhost:5175/`; Vite preserves its existing `/api` prefix stripping to FastAPI. No new CORS configuration is needed.

## Local Admin/Analyst verification

1. Start the configured API and React as above. Without Authorization, `/auth/me` and every `/admin/...` route must return 401 even if a report is missing. `/health` must still return 200.
2. Sign in normally with a real existing Analyst account (not in `powerflow-admins`). My Profile/navigation should show the **server-confirmed** Analyst role; public market/forecast views remain functional. Protected monitoring should show Access denied (403), including when directly requested. No frontend role edit or `?role=Admin` can change that result.
3. Sign out using the existing flow; sign in with a real existing member of `powerflow-admins`. Verify server-confirmed Admin. Admin monitoring returns available allowlisted evidence, or a truthful 404 for absent local reports. A 404 here does not mean authorization failed.
4. For the new coefficient endpoint, while signed in as Admin use the browser's own authenticated request context without copying tokens: open the browser developer console on the local app and run the expression below. It reads no token from storage and uses the app's existing access-token-aware client. Do not log raw Authorization headers or token values.

```js
(await import('/src/api/client.ts')).request(
  '/admin/models/linear-feature-influence', value => value
).then(report => console.table(report.features))
```

This is a **local Vite development** inspection command, not a production integration API. For Analyst it must reject with 403; for Admin with the legitimate report it returns the 31 actual persisted rows. The future UI must not attribute them to HGB.

5. Inspect `/auth/me` in the browser Network panel: it returns your own subject/role and nullable optional attributes, never tokens. Do not copy/share request headers, raw JWTs or sensitive account screenshots. Do not paste real JWTs into shell commands, chat, URLs, test fixtures or reports.
6. Use offline tests for expired/forged/wrong-client tokens. Do not modify real tokens or Cognito settings for testing. If a real API session receives 401, React should show sign-in; JWKS/configuration 503 must not silently downgrade to a public restricted-report fetch. If a configured real session is rejected, verify issuer/client/scope/audience configuration without disabling checks.
7. Production Streamlit remains on its existing independent authentication flow and file-backed dashboard; this work does not change it or require an API bearer token for those existing reads.

## Validation and remaining limitations

Automated tests use local generated RSA keys and mocked JWKS/HTTP responses. No automated test requires AWS credentials, a live JWKS request or real user token. They cover valid/missing/expired/forged/wrong-issuer/wrong-client tokens, ID-token rejection, algorithm/key-source restrictions, scopes/audience, exact Admin membership, Analyst denials, bounded JWKS network handling, unknown-key rotation/throttling, cache expiry/outage/backoff and concurrent reads, configuration failure, safe report schemas, source immutability and existing public contracts. Existing auth/API/dashboard/observability/deployment regression tests remain unchanged.

Frontend tests cover server account parsing, access-token header use, safe 401/403 behavior and protected monitoring URLs without a legacy fallback, alongside all existing forecast/data/auth tests. Validation passed: **178 Python regression tests** (42 new security cases plus existing authentication/API/market/dashboard/observability/deployment tests), **24 frontend tests**, frontend lint with no warnings, and production build. Python emitted only the existing Starlette/httpx TestClient deprecation warning.

Reproduce from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_api_security.py tests/test_api.py tests/test_public_market_api.py tests/test_phase5_restoration.py tests/test_auth.py tests/test_api_deployment.py tests/test_dashboard_market_context.py tests/test_operational_observability.py
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
``` Real Cognito end-to-end Admin/Analyst acceptance is a manual check; this phase does not claim it was completed with real account tokens.

Offline JWT verification does not detect Cognito revocation/group changes instantaneously: an already-issued signed token can remain valid until expiry; cached keys remain trusted for their bounded cache lifetime. Stronger revocation/session policies, rate limits at the approved infrastructure boundary and production deployment review remain separate work. No global public-endpoint authentication switch or development bypass exists.

Next: complete the documented legacy monitoring migration; restore the authorized coefficient UI and bounded operational detail panels; strengthen coefficient report provenance if required; verify real accounts and token renewal; then separately approve production environment/proxy/hosting/deployment changes. Do not claim full restricted-feature parity or production readiness yet.

## Files changed in Phase 4B

Backend/config/docs:

- `.env.example` — public API identity examples; existing settings preserved.
- `requirements.txt` — direct `joserfc==1.7.7` pin.
- `src/api/security.py` — new verifier/cache/principal and dependencies.
- `src/api/restricted_reports.py` — new explicit bounded account/Admin report contracts/readers.
- `src/api/app.py` — additive protected routes and fail-closed auth configuration.
- `tests/test_api_security.py` — new offline security, compatibility and report-parity tests.
- `docs/api_authentication.md` — this architecture, matrix and runbook.

Frontend:

- `frontend/src/api/account.ts` — new runtime-validated server account response.
- `frontend/src/api/client.ts` — `/auth/me` and protected monitoring URLs.
- `frontend/src/auth/serverAccountContext.ts` — new limited server-account context/hook.
- `frontend/src/auth/ServerAccountProvider.tsx` — new session-bound server role lifecycle.
- `frontend/src/auth/AuthenticationRoot.tsx` — compose server-account provider with existing token binding.
- `frontend/src/components/layout/AppLayout.tsx` — server-confirmed role label.
- `frontend/src/components/data/ApiPanel.tsx` — explicit Access denied title for 403.
- `frontend/src/pages/ProfilePage.tsx` — server-confirmed role and verification retry.
- `frontend/src/pages/ModelsPage.tsx` — permission status and honest UI restoration state.
- `frontend/src/pages/PipelinePage.tsx` — restricted-detail/monitoring boundary explanation.
- `frontend/tests/serverAccount.test.ts` — new parsing and protected-path tests.
- `frontend/README.md` — Phase 4B runbook link and current security boundary.

No CSS/font/chart-data changes, no Streamlit files, no ML/pipeline files and no deployment files were modified by this phase.

## Legacy monitoring production migration gate — Option 1

Both legacy URLs are deprecated authenticated aliases. They use the **same**
`require_admin` dependency and response models/readers as their `/admin` counterparts:

| Legacy URL | Anonymous | Verified Analyst | Verified Admin |
|---|---|---|---|
| `/monitoring/forecast-vintages` | 401 | 403 | Allowlisted `VintageDiagnostics` only |
| `/monitoring/exogenous-readiness` | 401 | 403 | Allowlisted `ReadinessDiagnostics` only |

Streamlit continues reading its local reports directly; its implementation is
unchanged. Repository evidence cannot establish whether unknown external production
consumers call these URLs. Such consumers will lose anonymous access, and even
verified Admin consumers will no longer receive arbitrary/raw report fields.

**A separate production migration review and explicit deployment approval are
required before deploying this change.** Approval of Option 1 authorizes these
local code changes, not a production rollout. The review must inventory consumers,
assess compatibility, notify owners, define legitimate client migration, verify
401/403/Admin-only projections in staging, and approve a rollback that retains the
security boundary. Never restore anonymous raw access as a compatibility fallback.
No deployment is performed by this task.

Dedicated regression cases in `tests/test_api_security.py` assert dependency/model
identity, anonymous 401, Analyst 403, permitted Admin top-level and nested fields,
unknown-field exclusion, identical protected-route responses, no-store headers and
source immutability using ephemeral signing keys and mocked JWKS.
