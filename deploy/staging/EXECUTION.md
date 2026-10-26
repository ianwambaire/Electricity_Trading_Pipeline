# Bounded staging window — proposal, not executed

Use `https://staging.powerflowenergy.dev` with Vite base `/`, root React Router and `/auth/callback`. A path prefix would require router/auth/build changes; apex assets cannot be reused because their OAuth origin is embedded. One DNS record pointing at the existing EC2 and a separately issued staging certificate are required. No second EC2. Existing apex server, DNS and Streamlit client stay unchanged.

## Approval boundary 1: prerequisites

Approve separately the exact DNS record, staging certificate issuance/renewal and additive React SPA client callback/logout changes after readback. Preserve localhost callbacks, scopes, attributes, providers and every unrelated client setting. Add `https://staging.powerflowenergy.dev/auth/callback` and `https://staging.powerflowenergy.dev/`. Existing Streamlit client is untouched. TLS verification below must finish before choosing an issuance method; no speculative Certbot command is authorized.

## Build and isolated installation (one proposed deployment window)

Build on Mac, not 2 GiB EC2; use existing lockfile/dependencies. Public configuration only, using the existing issuer/domain/client. No `.env` or recovery files in releases.

```sh
cd frontend
npm run build:release -- --origin https://staging.powerflowenergy.dev --out-dir /private/tmp/powerflow-staging-dist
cd ..
```

Run existing `scripts/prepare_web_release.py` and `scripts/smoke_web_release.py` with their explicit settings/manifest checks before approving the resulting exact artifact hashes. Artifact transfer/install commands must bind the resulting release ID and hashes; these values cannot be invented before build. Never `git pull` over the production working tree or reuse its mutable virtualenv. Do not enable staging from an unverified artifact.

Install the validated candidate separately under `/opt/powerflow/releases/REVIEWED_ID`, isolated `.venv-api` with pinned dependencies, root-owned nonwritable code and `/opt/powerflow/react-current` symlink. Dedicated `powerflow-api` user, no instance-role credentials, read-only published data at `/srv/powerflow/published`, no ingestion `.env`. Publishing a consistent minimal snapshot requires its own reviewed artifact list and SQLite backup protocol; do not copy a live DB/WAL independently. No training, inference or pipeline runs during install. `POWERFLOW_ACCOUNT_TOTP_ENABLED=false`; keep recovery/enrollment unexposed.

Existing API on8000 is an older revision (`/ready`404). Temporarily retain it unchanged for rollback, run exactly one capped candidate worker on8010 using `powerflow-candidate-api.service`. This temporary second process is necessary to validate the replacement without interrupting existing API consumers. Do not add another full backend permanently. After validated cutover, retirement of the old service is a separate approval. Available898MiB RAM is a snapshot, not a capacity pass: require at least768MiB available before starting, 2GiB free disk after install; stop candidate if available falls below256MiB or services degrade. Candidate capped512MiB/no swap; no load tests on shared host. A reliable capacity monitor is a prerequisite for live window, not supplied by this static template.

After installation/prerequisites, these are the exact activation commands (root installation authority required, NOT executed here):

```sh
install -m 644 deploy/staging/powerflow-candidate-api.service /etc/systemd/system/powerflow-candidate-api.service
# Install reviewed nonsecret environment at /etc/powerflow/react-api.env, mode0600.
# Install reviewed safe-log http include and security headers after duplicate-name checks.
systemctl daemon-reload
bash deploy/staging/activate-staging.sh phase-staging-local-20261026
venv/bin/python scripts/smoke_staging.py --origin https://staging.powerflowenergy.dev
```

`REVIEWED_ID` must be replaced by the independently validated artifact ID. Activation refuses an existing staging virtual host/state directory. It validates Nginx before reload; readiness failure stops before reload. Failed/partial artifacts are retained. Rollback is explicit, never automatic deletion:

```sh
bash deploy/staging/rollback-staging.sh phase-staging-local-20261026
```

This removes only staging from Nginx via a private retained copy, validates then reloads, stops only candidate API. Existing API revision, virtualenv, service and production Streamlit remain unchanged throughout: restoring service8000 is unnecessary because it was never updated. For later candidate updates use `bash deploy/staging/switch-candidate.sh NEXT_RELEASE NEW_RECORD_ID`; it preserves the previous immutable link and touches only candidate8010. Explicit rollback uses the same script with the recorded previous basename and a new record ID, never automatic cleanup. Record `readlink /opt/powerflow/react-current` before switching; rollback that link to the recorded previous immutable release and restart ONLY candidate, validate loopback health/ready before any Nginx activation. Never guess the old API revision from its working directory or checkout.

## Acceptance before apex cutover

HTTP smoke tests are read-only, tokens prompted privately in owner Terminal, no redirects/retries. They verify seven SPA entry routes, API integration, verified server roles, seven Analyst403s and unauthenticated401s. Static HTML success alone does NOT prove rendered pages. Owner/browser acceptance must additionally inspect all seven rendered pages on desktop/mobile, chart/data states, native Analyst and Google Admin Code+PKCE callbacks, MFA challenge where applicable, profile retrieval, sign-out and fresh sign-in. Never print callback query strings/tokens. Verify withheld next24 has no operational prediction/chart when unvalidated; existing frontend/backend tests cover unavailable/withheld states. Do not generate forecast evidence for acceptance.

Apex cutover requires separately approved apex build/client URLs and exact Nginx diff, recovery coverage and restoration pass, renewable TLS, capacity and authorization acceptance. Reuse candidate backend8010; do not run another one. Preserve original apex Nginx config in private rollback directory and original8000/Streamlit services. `nginx -t` before reload; failure leaves old routing. Rollback restores the recorded original apex config then `nginx -t && systemctl reload nginx`. No Streamlit stop/decommission until separate approval. Prefect, PostgreSQL, SQLite, MLflow and models are outside deployment write scope.

Local validation 2026-10-26: staging-origin release built successfully at `/private/tmp/powerflow-phase-staging-candidate`, release guard passed, no maps/test sources. Existing apex candidate was not rebuilt or modified. Nginx/systemd executables are unavailable on this Mac: local structural/shell tests are not syntax/installation acceptance; Linux `nginx -t` and systemd verification remain mandatory.

Validated local staging candidate (not installed): `/private/tmp/powerflow-staging-review-5sywe_jc/candidate`, release ID `phase-staging-local-20261026`, 68 allowlisted files / 1,270,159 bytes, manifest SHA256 `dc93dacf69f9d69c17d3d7f906db186d9836dc2cb0d52d7f5810e4913142b6b0`. The packager selects staging proposals instead of apex Nginx/Cognito proposals for this exact staging origin. Revalidate hashes before transfer; this is not cloud authorization. The initial published snapshot must exclude unvalidated next24 reports; keep missing/withheld responses explicit. All other required genuine datasets need separate approved publication; neither the release artifact nor smoke fixtures are production market evidence.

Before activation, the separately approved installer must create `/var/lib/powerflow-staging` mode0700 and `/var/www/powerflow-staging/releases` with traversable root-owned static directories; transfer artifacts remain private until allowlisted static installation. The API dependency snapshot was tested on macOS CPython3.14, not the production Linux interpreter; clean Linux installation/imports and cgroup enforcement are hard gates, not implied by this build.
