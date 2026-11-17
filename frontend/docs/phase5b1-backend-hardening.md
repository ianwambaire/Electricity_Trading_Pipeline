# Phase 5B.1 — production backend hardening

23 October 2026, Africa/Nairobi. Branch `feature/react-frontend`. **Local engineering only; Phase5B.2 is not started.** The pre-existing Phase5A audit is preserved. No AWS inspection was necessary this phase, and no infrastructure, production process, data, schema, Cognito client/pool/account, DNS/TLS or Git history was changed. No staging, commit, push or merge was performed.

## Recommendation

The backend is a **candidate for isolated staging validation**, not approved or proven ready for public production. A clean API lock replay, offline security regressions, local ASGI startup checks and configuration boundaries are now available. Linux x86_64 installation/systemd activation, actual proxy/TLS/permissions, resource budgets, restore evidence and live staging identity checks remain prerequisites. No remote deployment is implied. General-user MFA enrollment remains disabled; deployed modes refuse to start with enrollment enabled.

## 1. Dependency root cause — more than a single stale package

Initial local installed metadata:

| Package | Version | Relevant constraint |
|---|---|---|
| FastAPI |0.136.3|Starlette>=0.46.0|
| Starlette |1.6.0|Installed outside the full research requirement's0.52.1 pin|
| MLflow / MLflow-skinny |3.12.0|MLflow-skinny requires Starlette<1|
| Prefect |3.7.5|Requires Starlette>=1.0.1|
| HTTPX |0.28.1|Existing HTTP client/test dependency|
| joserfc / Pydantic / Uvicorn |1.7.7 /2.13.4 /0.48.0|Retained API direct versions|

The installed Prefect3.7.5 and MLflow3.12.0 constraints have **no Starlette intersection**. FastAPI itself can accept either framework version, subject to testing. Pinning Starlette0.52.1 alone fixes MLflow but breaks Prefect3.7.5: this intermediate attempt was tested, detected by pip check and superseded. No claim that a single pin solves all current production packages is made.

Repository requirements already distinguished full research `requirements.txt` (Prefect3.7.2, MLflow3.12.0, Starlette0.52.1) from `requirements-prod.txt` (Prefect3.7.5, no MLflow). Previous CI installed both into the same environment and could overwrite packages. Downloaded and inspected Prefect3.7.2 wheel metadata: it has no direct Starlette>=1 dependency and is compatible with the existing research constraints. Prefect3.7.5's installed metadata explicitly requires>=1.0.1.

### Chosen separation

- **API service:** new `requirements/api.in`, `api.lock`. Only FastAPI/Uvicorn/JWT/HTTP/Pydantic and NumPy/Pandas needed for persisted analytics. Starlette0.52.1 explicitly constrained and tested. No MLflow, Prefect, Streamlit, scikit-learn, training or AWS SDK in the service environment. This is deliberate service isolation, not removal of research functionality.
- **Research/full regression:** existing requirements retain MLflow3.12.0 and declared Prefect3.7.2/Starlette0.52.1; `requirements/shared.txt` prevents accidental incompatible resolution. Local venv was restored to this declared baseline (Prefect3.7.5→3.7.2; Starlette1.6.0→0.52.1). Other installed packages were not blindly upgraded. MLflow remains installed and exercised by the full suite. This local research adjustment is **not** a proposed production Prefect downgrade.
- **Orchestration/Streamlit runtime:** requirements-prod retains Prefect3.7.5 and every existing direct production version, adds `requirements/orchestration.txt` pinning Starlette1.6.0. It must not be merged with research requirements or have MLflow installed. A separate empty local environment was installed and tested successfully.
- **API test environment:** api-test.in/api-test.lock add pytest9.1.1 and its test dependencies to the API lock; pytest is not required by the deployed service. Three existing cross-layer tests import model packages to assert no model execution/deserialization; they are explicitly marked `model_runtime`. They run in the full suite, and are intentionally deselected in the minimal API environment rather than installing research packages into it.

CI now separates full research tests, minimal API/security tests, and production-orchestration import checks. It no longer installs incompatible requirement sets sequentially. These CI definitions were edited locally; no remote CI run is claimed.

### Reproducibility and security limits

The API inputs were resolved in a new empty CPython3.14.7 macOS environment, all resolved versions frozen, then the lock was replayed into a **second empty** local environment. API tests and pip check passed there. API runtime lock contains runtime packages only; api-test.lock contains test tools as well. Lock files pin exact versions but are not hash-locked supply-chain attestations. These are macOS-tested snapshots; **Linux x86_64 has not been tested live**. CI now defines that validation, but a definition is not execution.

The API lock is reproducible within the verified interpreter/platform scope. Orchestration direct versions/Starlette are constrained and a clean install was tested, but its entire transitive graph is not locked; it must not be called fully reproduced from a complete orchestration lock. Research environment consistency/full tests passed; a complete fresh install of all research requirements was not performed. Keep these evidence levels separate.

No blanket framework/MLflow upgrade was attempted, and no model/artifact was regenerated. Starlette0.52.1 matches the existing research pin and passed regression tests, but this phase does not certify absence of package CVEs or promise maintained security indefinitely. Review advisories/support and intentionally refresh locks before public release. No Python/container/OS vulnerability scanner was installed/run here. The clean API environment resolved newer transitive packages than the old local venv; their exact versions are recorded in the lock, not silently applied to production.

## 2. Runtime configuration and security changes

New `src/api/runtime.py` provides validated RuntimeSettings and safe ASGI middleware. `create_app` supports injected settings for offline tests while validating real environment configuration for launched services.

| Setting | Meaning / safe behavior |
|---|---|
|POWERFLOW_API_ENV|development(default), staging or production only; unknown values stop startup|
|POWERFLOW_API_ALLOWED_HOSTS|Comma-separated exact hostnames/IPs, no scheme/port/wildcard. Explicit list required in staging/production; development defaults localhost,127.0.0.1,testserver. IPv6 host literals are not supported by this initial validator.|
|POWERFLOW_API_DATA_ROOT|Absolute published snapshot root required for deployed launch. API reads database/data/public model metadata beneath this root. Relative overrides rejected. Explicit test APISettings remain injectable.|
|POWERFLOW_API_CORS_ORIGINS|Empty by default for same-origin proxy. If needed, explicit origins only, HTTPS in deployed modes, no wildcard/credentials/path/query/fragment. HTTP localhost allowed only in development.|
|POWERFLOW_API_COGNITO_ISSUER / CLIENT_IDS|Existing validated issuer and allowed SPA client IDs; missing/invalid deployed identity config aborts startup. Development keeps public legacy reads and fails protected authentication closed.|
|POWERFLOW_API_COGNITO_AUDIENCE|Optional exact resource binding, only for genuinely resource-bound tokens; no invented audience|
|POWERFLOW_API_REQUIRED_SCOPES|openid remains required; additional scopes configured as before|
|POWERFLOW_ACCOUNT_TOTP_ENABLED|Defaultfalse; staging/production reject enabled enrollment. Existing local test-only gates remain for separately approved cases.|

Additional issuer validation rejects a user-pool region inconsistent with the Cognito endpoint region. JWKS URLs remain constructed from trusted issuer configuration; no token-supplied URL, secret or arbitrary JWKS override is accepted. Signature/issuer/client/type/expiry/audience/scope checks, live Cognito current-user validation and exact signed Admin group enforcement remain in place.

Host validation uses TrustedHostMiddleware and does not trust X-Forwarded-Host from callers. The staging Uvicorn template trusts forwarded headers **only from127.0.0.1** and binds there; the HTTPS reverse proxy must preserve the approved Host. The app does not force HTTPS redirects behind a terminating proxy, avoiding loops. Production TLS/proxy configuration is not changed here.

CORS explicitly allows only GET/POST/PATCH, Authorization/Content-Type and configured exact origins, with credentials=false and X-Request-ID exposed. Disallowed origins receive no allow-origin header; preflight rejects disallowed origins. CORS is not authentication and does not protect the existing intentionally public report contract. Same-origin `/api` remains preferable. Public Swagger/ReDoc/OpenAPI routes are disabled in staging/production.

Generic request validation errors no longer echo submitted inputs. Unhandled route errors return a fixed500 body with correlation ID, no exception text/path/traceback. Existing own-account errors retain safe code allowlists. The exception boundary sits inside CORS so configured clients can read sanitized500s. Requests already streaming a response cannot be replaced with a new500; interrupted-response exceptions are replaced with fixed text rather than propagating sensitive exception messages.

No public endpoint was exposed on AWS. `/ready` is a new local application route awaiting any separately approved proxy deployment. Existing public analytics and seven Admin-only report routes retain their access policy; own-account changes remain authenticated. Authentication is not weakened for local convenience.

## 3. Health and readiness design

- **GET /health:** existing liveness contract unchanged; reports the process response, not data freshness or availability of every upstream.
- **GET /ready:**200 ready /503 not_ready; fixed checks for configured identity verifier/gateway and readable operational SQLite schema (required pipeline_runs/data_quality_results columns). It never creates the DB or schema. Missing/corrupt/locked/incompatible DB is unavailable; identity unavailability cannot be hidden by the DB cache.
- Readiness probes are serialized and cached for five seconds. They open a short read-only transaction and no-row SELECTs, not full history scans, source fetches, inference, backup or pipeline work. Bodies include only categorical checks, no paths/identifiers/secrets.
- `data_freshness: not_assessed` and `provider_connectivity: not_assessed` are explicit. This is **local service/dependency readiness**, not a Cognito availability attestation or guarantee of forecast issuance. Live provider/JWKS outages remain fail-closed request outcomes and require external/passive monitoring; polling health must not create a Cognito request storm.
- Empty persisted history and missing forecast reports can coexist with readiness. WITHHELD/stale/historical/missing product states remain separate from process restart decisions. No report was fabricated to make readiness pass.

## 4. Logging and observability

Each HTTP request receives a new random server-generated X-Request-ID. Caller IDs are not trusted/reflected. Structured JSON includes event, request ID, server route template (or `unmatched`), allowlisted method, HTTP status, duration, and fixed access outcome (401 rejected,403 forbidden,otherwise completed). Lifecycle startup/shutdown and fixed request_failed events are recorded. The design records failures without usernames, subjects, IPs, email or raw authentication reasons.

Never logs raw URL/query, body, headers, cookies, JWTs, provider payloads, exceptions or traceback text in the new application telemetry. Tests submit private fixture values in query/header/path/error/input and verify they do not appear in response or application logs. This is fixed-schema omission rather than a regex promising to recognize every possible secret. Correlation allows an operator to find the safe event without copying a token.

The new staging template disables raw Uvicorn access logs. Legacy proxy/journal/library logging remains a separate operational configuration review: do not enable HTTP debug logs or log callback query strings; configure retention/redaction before exposure. A startup config failure uses fixed messages and refuses launch. No external telemetry service was added. JSON uses a standard-library logger; no new runtime logging dependency.

## 5. SQLite and runtime reliability

New `src/api/database.py` centralizes a read-only snapshot context used by pipeline status, public operational summary and Admin operations:

- SQLite URI mode=ro prevents accidental DB creation; query_only=ON prohibits writes.
- Explicit BEGIN gives one consistent read transaction for multi-query summaries.
- Connection closes on success/error, releasing transactions and locks.
- A250ms busy timeout bounds contention rather than holding HTTP workers for defaultmulti-second waits. The API reports existing sanitized503s for SQLite errors; it does not retry writes or synthesize data.
- No journal-mode change, WAL conversion, schema creation or production data migration. The writer/pipeline was not modified. In-memory market indexing remains process-local and protected by its existing lock.

Tests cover missing/corrupt/schema-incompatible data, read-only write rejection, no persistent bytes changed,20 reads across8 threads, exclusive-writer lock failure within a bounded interval and recovery after lock release. The production service user/mount must actually have read permissions; the local test is not proof of installed ownership. If the real DB uses WAL, validate read-only sidecar permissions and coherent publication on staging; do not force immutable mode on a changing database or enable WAL during deployment without review.

Lifespan shutdown always closes the market snapshot in finally and emits a stop event. Single-worker policy remains deliberate because cached snapshots/JWKS/enrollment coordination are in-memory. Restarts invalidate pending enrollment state; no secret or code is persisted to recover it. Network-uncertain account operations require status refresh, not optimistic success or automatic mutation retries.

## 6. Production packaging proposal

New `deploy/staging/powerflow-api.service`, `api.env.example` and README are **uninstalled proposals**, preserving the original EC2 unit and Streamlit implementation. The old API deployment runbook now warns against installing the historical template unchanged for the new deployed runtime.

Proposed staging paths: root-owned versioned source/runtime under `/opt/powerflow`, `.venv-api`, dedicated non-root `powerflow-api` user/group, non-secret `/etc/powerflow/api.env`, read-only coherent published tree at `/srv/powerflow/published`. No ingestion .env, Streamlit secrets, client secret or administrative AWS credential belongs in the API process. Creating these users/files/permissions on AWS is not authorized by this local work.

Template binds loopback8000, one Uvicorn worker, loopback-only forwarded-header trust, no raw access logs, initial concurrency32/keepalive5s/graceful stop20s and systemd stop30s. NoNewPrivileges, read-only system/home/data, empty capabilities, private devices/tmp, restricted address families, tasks64, initial MemoryMax768M and CPUQuota100% provide staging guardrails. These are initial limits to validate, not measured safe capacity or HA. IMDS/instance-role reach and actual effective permissions still need infrastructure review; filesystem sandboxing is not IAM isolation.

No production container is introduced. Existing broad Docker/Compose configuration remains outside the chosen API deployment path and must not be presented as hardened. Future image work needs allowlisted context, no local secrets/backups, non-root runtime, immutable artifacts and platform/security verification. No API port security-group/proxy rule is added now.

A separate ephemeral local Uvicorn probe used schema-only temporary data and test identity settings, bound only127.0.0.1, made health/readiness reads, sent SIGTERM and verified lifespan stop. It made no Cognito/network-account request. Exact result is listed below. This is local ASGI verification, not Linux systemd or production deployment acceptance.

## 7. Tests, evidence and honest limits

Final command results are appended after execution. API synthetic issuer/client values exist only in offline tests/probes and are never a fake production auth fallback. Valid/invalid JWTs use generated fixture keys and mocked provider responses. No real account, MFA setup, password change, recovery, group or production endpoint was exercised.

Three cross-layer tests are marked model_runtime because their **test instrumentation** imports joblib/scikit-learn/model modules. They initially failed in the intentionally minimal environment due to absent research packages. They were not removed or silently skipped globally: all run in the full suite. The clean API command explicitly deselects them and its count records that boundary. The offline runtime checker blocks research package imports entirely, proving that application startup/health/basic routes do not require those packages.

Clean API testing reports an AnyIO BlockingPortal alias deprecation warning from Starlette's test client; it is test-tool compatibility debt, not a failed assertion. The full research suite with its existing transitive environment does not report that warning. Pip cache-permission warnings in the restricted sandbox do not justify sudo or changing cache ownership.

## 8. Remaining blockers and Phase5B.2 requirements

**No AWS changes are applied or approved here.** The backend can proceed to isolated staging planning, subject to:

1. Clean Linux x86_64/Python3.14 API lock installation, pip check, security/import tests and installed systemd validation. Local macOS success is not Linux evidence. Remote CI jobs must actually run and pass.
2. Explicit approval for staging EC2/EBS/network/IAM/service user/filesystem/configuration, resource limits and budget; preserve production Streamlit/Prefect/client untouched. Root CLI operational risk remains unresolved.
3. Approved encrypted persistent staging storage and separate production EBS remediation plan; recent off-host consistent backups and isolated restore evidence. No EBS/backup changes in this phase.
4. Independently valid TLS chain/certificate renewal, actual reverse-proxy routing/header/body/timeouts, host policy and log retention. No DNS/TLS/proxy changes here.
5. Accepted public market-data contract and bounded/report-size/rate-limit work before public exposure. This phase does not solve the legacy unbounded one-hour history contract or implement distributed abuse controls.
6. Approved staging hostname/SPA client/callback/public identity settings and designated live-test scope. No Cognito changes now; example client/host placeholders must be replaced, not blindly deployed. Readiness only checks configuration presence/shape, not that a client really exists or grants scopes.
7. Real snapshot/schema/data consistency and read-only permissions; observed memory/CPU/query and provider latency; source publication/read contention. Never run a second production pipeline or create schema as an implicit deployment step.
8. Package-advisory/container/OS review and intentionally refreshed locks before public use. Complete orchestration transitive locking remains future work; no claim of a vulnerability-free environment.
9. Lost-device recovery and cross-client containment remain unverified. Regular-user MFA enrollment stays off regardless of staging success.

## 9. Startup, verification and rollback instructions

Local-only reproducibility commands (use new dedicated directories; never overlay environments):

```bash
python3.14 -m venv /tmp/powerflow-api-verify
/tmp/powerflow-api-verify/bin/python -m pip install -r requirements/api-test.lock
/tmp/powerflow-api-verify/bin/python -m pip check
/tmp/powerflow-api-verify/bin/python scripts/check_api_runtime.py
/tmp/powerflow-api-verify/bin/python -m pytest -q -m 'not model_runtime' tests/test_api.py tests/test_api_security.py tests/test_account_management.py tests/test_mfa.py tests/test_backend_hardening.py tests/test_public_market_api.py
```

For manual local development launch, the existing dev public settings still work and protected endpoints stay closed until valid issuer/client settings are exported. For a staging-style **local** startup, export the approved non-secret environment fields from the proposal (environment files are not automatically loaded by Python), point DATA_ROOT at a legitimate absolute local published root, then:

```bash
PYTHONPATH=src /path/to/api-venv/bin/uvicorn api.app:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log --proxy-headers --forwarded-allow-ips=127.0.0.1
```

Never use this command to start another production service or expose0.0.0.0. Check health/readiness locally; unauthenticated restricted calls return401, configured Analyst fixtures403. Do not paste real bearer tokens into shells/chat. Real staging account tests require separate scope approval.

Rollback after a separately approved deployment retains previous reviewed source, lock, venv and non-secret service config. Stop/drain gracefully, switch release pointer and verify health/readiness/auth; no data restore or Cognito edits as a routine app rollback. No migrations require rollback here. Do not combine requirement sets or run unconstrained upgrades to undo a resolver failure. Local research venv now matches its declared Prefect3.7.2/Starlette0.52.1 baseline; do not reinstall Prefect3.7.5 alongside MLflow3.12.0. Production orchestrator continues to target3.7.5 in its separate environment. The user controls all Git operations.

## 10. Final validation results

| Command / environment | Actual result |
|---|---|
|`venv/bin/python -m pytest -q`|**646 passed**,34.41s, all model_runtime tests included. `/tmp/pf5b1-full-tests-final.log`|
|Clean API resolution: `pip install -r requirements/api.in`, then pip check|Passed in empty `/tmp/powerflow-api-5b1-clean`; no broken requirements|
|Second empty venv: `pip install -r requirements/api-test.lock`, then pip check|Passed in `/tmp/powerflow-api-5b1-replay`; confirms lock replay, not just resolver success|
|Replay API suite: `python -m pytest -q -m 'not model_runtime' tests/test_api.py tests/test_api_security.py tests/test_account_management.py tests/test_mfa.py tests/test_backend_hardening.py tests/test_public_market_api.py`|**185 passed,3 deselected**,4.28s; one AnyIO test-client alias deprecation warning. All three deselected cross-layer tests pass in the full646. `/tmp/pf5b1-replay-tests-final.log`|
|Clean API `python scripts/check_api_runtime.py`|Passed offline imports/lifespan/health/readiness/auth-closed/docs-disabled checks without model/orchestration packages. `/tmp/pf5b1-replay-start-final.log`|
|Local `venv/bin/python -m pip check`|**No broken requirements found**, with MLflow preserved and declared research Prefect3.7.2. `/tmp/pf5b1-final-local-check.log`|
|Separate empty orchestration venv: `pip install -r requirements-prod.txt`, pip check, `python scripts/check_production_imports.py`|All passed with Prefect3.7.5/Starlette1.6.0 and no MLflow; local macOS only. Streamlit emitted expected no-runtime cache warnings during the offline import check. `/tmp/pf5b1-orch-check.log`, `/tmp/pf5b1-orch-imports.log`|
|Local research `python scripts/check_production_imports.py`|Passed after correcting a requirements comment that the existing checker treated as a forbidden package name; no checker/model logic weakened. `/tmp/pf5b1-prod-imports-final.log`|
|Temporary loopback Uvicorn lifecycle probe|Passed health200, readiness200 with temporary schema-only fixture, lifespan startup/stop, graceful SIGTERM exit **-15**. No Cognito call; no public bind. `/tmp/pf5b1-uvicorn-result-final.json`|
|`cd frontend && npm test`|**60 passed**, zero failed,933.46ms. `/tmp/pf5b1-frontend.log`|
|`npm run lint`, `npm run build`|Passed; production TypeScript/Vite build266ms. `/tmp/pf5b1-lint.log`, `/tmp/pf5b1-build.log`|
|compileall for changed API/checker/test; CI YAML parse; API/test lock pin consistency; `git diff --check`|Passed. Remote GitHub Actions and Linux systemd were not executed.|

Intermediate failures were used diagnostically, not hidden: Starlette-only fix revealed the Prefect>=1 conflict; the minimal test environment initially failed three model-instrumented tests until test layers were explicitly classified; the first lifecycle probe's zero-exit assumption was corrected after observing successful shutdown with normal SIGTERM exit; sandbox initially blocked loopback binding and the isolated probe ran with the required local permission. No live security control was bypassed. The original production import checker was unchanged; its simplistic requirements text check required avoiding a research-package name in a comment.

No new real Cognito, Google, native password, account-recovery, MFA enrollment or production compatibility test was performed. Existing production acceptance remains historical. No restart of production services occurred. Local dependency versions have changed as described; existing local development processes may need a manual restart before their runtime reflects the new venv. That is not approval to restart production.

## 11. Files changed in this phase

Modified:

- `.github/workflows/ci.yml` — isolated research/API/orchestration checks.
- `requirements.txt`, `requirements-prod.txt` — explicit environment-specific constraints.
- `src/api/app.py` — validated deployment mode/data root, host/CORS/error middleware, readiness and lifespan events.
- `src/api/security.py` — issuer/pool region consistency check.
- `src/api/admin_operations.py`, `src/api/operations_summary.py` — shared read-only DB snapshots.
- `tests/test_api.py`, `tests/test_api_security.py`, `tests/test_public_market_api.py`, `pytest.ini` — identify three cross-layer tests without removing full-suite coverage.
- `docs/api_ec2_deployment.md` — historical-template warning and isolated staging reference.

Created:

- `requirements/api.in`, `api.lock`, `api-test.in`, `api-test.lock`, `shared.txt`, `orchestration.txt`.
- `src/api/runtime.py`, `database.py`, `readiness.py`.
- `scripts/check_api_runtime.py`.
- `deploy/staging/powerflow-api.service`, `api.env.example`, `README.md`.
- `tests/test_backend_hardening.py` —22 new production/security/DB/runtime cases counting parametrization.
- `frontend/docs/phase5b1-backend-hardening.md` — this report.

The already-untracked Phase5A report was preserved, not edited as part of this phase. No frontend application code, Streamlit/pipeline/model code, model artifacts, data, Cognito policy or existing production service unit changed. Local virtualenv/package and disposable `/tmp` test artifacts are not Git-staged changes.
