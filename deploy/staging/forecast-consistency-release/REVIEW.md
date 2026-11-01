# Forecast consistency staging release — local preparation only

No SSH, server access, AWS change, activation or real forecast publication.
This uses scripts/prepare_web_release.py and the existing immutable release roots.
The source consistency fix requires no new dependencies or persisted schema.

## Reproduce locally

Use a NEW private canonical parent outside the repository. Do not overwrite an
existing release or reuse the old 70-file candidate. Set only the public authority,
domain and client ID from release-settings.json in the build process environment.
The build.py wrapper supplies these public values directly to the supported npm
release builder, so a fresh clone does not depend on personal .env.local settings.
Never include ingestion .env, credentials, private reports or A03 artifacts.

```sh
venv/bin/python -B deploy/staging/forecast-consistency-release/build.py \
  --out-dir /NEW-PRIVATE-PARENT/dist
venv/bin/python -B deploy/staging/forecast-consistency-release/prepare.py \
  --dist /NEW-PRIVATE-PARENT/dist --release-id phase-forecast-consistency-20261101-v1 \
  --write /NEW-PRIVATE-PARENT/release
venv/bin/python -B scripts/prepare_web_release.py --verify /NEW-PRIVATE-PARENT/release
```

The supported build enforces the exact staging origin, /auth/callback and / logout,
root-relative assets and /api base. The manifest contains every relative path,
size and SHA-256; its identity is reported separately. Packaging refuses overwrite,
missing selector, wrong origin, fixture/static secrets, symlinks and unexpected
files. A second supported build is compared byte-for-byte during this preparation.
The completed local release is sealed directories0500/files0400. Hashes detect
modification; this does not protect against a privileged actor rewriting it.

The package includes all src/api and src/shared modules, API lock/constraints and
complete static assets/fonts. Only reviewed deployment PROPOSALS accompany it.
Do NOT execute its old install/activation/rollback proposals: they are not a new
approved mutation runner and may assume outdated pointers. No deployed/private environment files,
model binaries, datasets, tests, private diagnostics or A03 code are packaged.
The public api.env.example is a review-only proposal, never a copied runtime env.

`previous_release:null` intentionally avoids inventing the installed state.
Fresh read-only preflight must establish independent backend/static targets.
Local build success is not proof of Linux, Nginx, Cognito or actual UI acceptance.

## Independently approvable boundaries

1. READ-ONLY preflight only: installed targets, hashes, configuration, permissions,
   resource/security enforcement, health and production-preservation baselines.
2. A later bounded transfer/install/activation window: immutable code/static
   release, private control/backup paths below, optional one-key candidate env
   addition, at most one candidate restart and staging pointer switches. Requires
   a fresh hash-bound execution runner and explicit approval; this document alone
   does not authorize it. No service/unit/Nginx/TLS/Cognito changes are necessary.
3. Real forecast publication is independent and NOT part of code activation.
   Missing/expired publication must remain safely WITHHELD. A03 recovery stays separate.
4. Rollback/critical-pressure candidate-only stop must be explicitly approved
   separately or named precisely in the eventual deployment window. No automatic
   retry, repair, rollback, cleanup, or change to production services is proposed.

## Fresh preflight — mandatory before any target writes

- Record canonical /opt/powerflow/react-current and
  /var/www/powerflow-staging/current targets separately and verify full inventories.
  Both current releases must be retained; their IDs need not match.
- Record private /etc/powerflow/react-api.env exact bytes, SHA, root ownership/mode.
  Validate configuration by allowlisted keys only; never log the file. Check data
  root remains /srv/powerflow/published, existing issuer/client binding, MFA gate
  remains false, and current overlay configuration. Reject duplicate/contradictory
  overlay keys. Preserve every unrelated byte and setting.
- If needed, propose only POWERFLOW_FORECAST_PUBLICATION_ROOT=/srv/powerflow/forecast-publications.
  If absent, enable this key ONLY with explicit path/config approval. Existing root and
  releases directories must be root-owned0750, bundle files0640, group powerflow-api,
  candidate UID992 read-only. Missing current pointer is a legitimate unavailable
  publication, not permission to insert synthetic or expired data. Test effective
  service-namespace access; do not loosen permissions or sandboxing to make it pass.
- Verify candidate unit hash, actual UID/GID992, one worker, localhost8010 only,
  existing Python3.14.7 base and venv accessibility under ProtectHome; pip check,
  imports and exact lock match. Reuse the existing venv; do not reinstall into it.
- Require MemAvailable>=768MiB; report swap and memory pressure. Require >=2GiB
  free AFTER new release/control/temporary copies; measure the actual release size
  and filesystems. MemoryHigh384MiB/MemoryMax512MiB/MemorySwapMax0, sandbox and BPF
  protections must remain effectively enforced. No load testing on the shared host.
- Save identities and states of production API8000, Streamlit8501, Prefect worker/
  server, PostgreSQL and candidate; hashes of production/staging Nginx, unit and
  public certificates; historical publication/forecast/model baselines as approved.
  Do not infer a separate MLflow service identity if one has not been verified.
- Candidate health/ready must return200 locally; public /api/ready stays404.
  Check staging HTTPS, root/assets/API, certificate hostname/trust, time sync,
  no installation/control/temp destination conflicts and no symlinked ancestry.
- Verify existing staging routing forwards new provenance query parameters. All
  paths already exist; no DNS, Nginx reload, new certificate or Cognito update.

## Proposed installation and activation sequence (NOT executable approval)

1. Transfer only the hash-bound release to a new private incoming path. Verify
   all hashes before privileged copy. Reject extras, symlinks, existing targets.
2. Create ONLY new immutable candidate/backend and staging/static release dirs:
   /opt/powerflow/releases/phase-forecast-consistency-20261101-v1/
   /var/www/powerflow-staging/releases/phase-forecast-consistency-20261101-v1/
   Reuse the verified venv through a reviewed link, preserving interpreter access.
   Code/static owner root, directories0755/files0644. Do not install proposal units.
3. Create one new private control directory:
   /var/lib/powerflow-staging/forecast-consistency-20261101-v1/ (root0700).
   Save previous-api, previous-static, previous-api.env, baseline and rollback.json
   as root0600, using exclusive creation. Hash and verify exact env backup. Use
   rollback_state.py's schema: independent old/new targets, old/new env hashes,
   backup path and original root0600 ownership. No real record is fabricated locally.
4. Run candidate imports/lifecycle/synthetic contract checks offline as UID992;
   no provider calls, receipt creation or production-data writes. Validate data
   readability/non-writability and resource headroom before switch.
5. Recheck baselines. If explicitly approved and necessary, install a candidate-env
   copy with only the overlay key added atomically, preserving root0600. No other
   env changes. Save both old/new hashes privately.
6. Atomically switch ONLY the backend pointer through an exclusive sibling symlink;
   restart ONLY powerflow-candidate-api.service once. Use bounded health/readiness
   probes; check limits/sandbox/BPF/listener and production preservation. Stop on
   failure and retain artifacts. No Nginx command or production service restart.
7. Switch ONLY staging's static pointer after backend checks pass. No reload needed.
   Verify manifest-bound HTML/assets/build config and all seven page routes. Retain
   both original targets; do not assume a shared release ID for rollback.
8. Complete approved read-only acceptance below. Require no OOM/restart, no producer
   or service interference. A <256MiB available-memory/OOM/production degradation
   response must be explicitly bounded to candidate-only safety action in approval.

An immutable atomic pointer is not a zero-downtime transaction: API restart can
briefly interrupt staging and the two pointers are independently switched. API is
backward-compatible, so backend-first avoids new UI against old provenance logic.

## Stale-tab policy — safe reload recovery, not asset copying

Old immutable releases remain for rollback, but are NOT silently merged into the
new manifest. Current Nginx root follows current/, so an old tab may request a lazy
chunk absent from the new release. The existing ErrorBoundary shows a generic
accessible Reload PowerFlow action; it does not render exception text, predictions
or a fake page. A fresh reload retrieves uncached current index and coherent assets.
The local regression rejects an old synthetic lazy import then verifies a fresh
application mount recovers. Actual browser reload/history/session behavior remains
an explicit staging test. Do not claim seamless old-tab compatibility or blindly
copy arbitrary previous assets into the immutable release.

## Acceptance (future read-only requests, not run here)

Use the updated scripts/smoke_staging.py with an explicitly observed expected state:

```sh
venv/bin/python -B scripts/smoke_staging.py \
 --origin https://staging.powerflowenergy.dev --expected-publication MISSING_PUBLICATION
```

Replace the state ONLY after independently verifying it; never choose a state to
excuse an unexpected response. The tool prompts access tokens only in the owner's
TTY, never chat/argv/files/logs; sign-in passwords/codes remain in Cognito/browser.
No identities are created. No retries/redirect following. 503 requires exact
FORECAST_WITHHELD + no-store for forecast AND Admin provenance, with matching
operational publication state. No 503 exception applies to other Admin reports.
401/403 for all seven routes remain mandatory. VALID requires 24 finite/aligned
rows, current issue/expiry, matching provenance and historical status labels.
409 is allowed ONLY when explicitly supplying a known older issue/completion via
--previous-issue/--previous-completed, proving that pair differs from current.
Any normal 409, unexpected503, HTML proxy response or state conflict is a failure.

- Seven routes: direct URL, navigation, refresh, browser history and no missing
  current assets. HTML smoke alone does not prove populated React behavior.
- Overview: historical KPIs/coverage and recorded health stay separate from publication.
- Analytics: existing filters, pagination, generation/weather charts, tables/export.
- Forecast: valid issue/24 targets, same-bundle Admin provenance, null unknown
  watermark, matching expiry and no fallback. Publication changes may cause409;
  refresh forecast, never combine mismatched evidence. Natural expiry removes
  values/chart/download. Invalid/missing tests use isolated synthetic local data,
  not live artifact tampering; real publication needs its own approval.
- Anomalies: historical markers/top-price ranking/pagination/export unchanged.
- Models: HGB/Linear Regression releases and metric provenance unchanged; coefficients Admin-only.
- Pipeline: historical snapshot (including accepted A1) not live; SUCCESS != generated.
- Profile/auth: real Google/native sign-in, existing enrolled TOTP if applicable,
  callback/session expiration/sign-out. No new MFA enrollment, password change,
  recovery or user attribute mutation is implied by this release acceptance.
- All seven Admin routes: unauthenticated401, Analyst403, Admin state-appropriate
  allowlisted response. Public market endpoints remain intentionally public.
- APIs: public health200, private ready200, proxy ready/docs404, no-store, safe
  errors, correct provenance query forwarding and no leaked tokens/input vectors.
- Cross-release: leave a tab open before switch, navigate to lazy route, verify
  generic recovery then reload loads current route/sign-in correctly on real browser.
- Shared host: production service/routing/cert/model/data preservation and candidate
  resource limits. Historical report absence is not fabricated into a pass.

## Independent rollback — new explicit approval required

1. Validate rollback.json using rollback_state.py. Verify current backend/static
   targets and candidate env SHA equal the installed values; refuse external drift.
   Verify original targets/inventories and backup SHA; do not guess directory names.
2. Frontend-only rollback: atomically restore recorded previous-static. No API
   restart/env change. Check old assets; new API remains backward-compatible.
3. Backend rollback: if the new UI is active, restore previous-static first; restore
   previous-api.env EXACT bytes/owner/mode atomically, then previous-api pointer;
   restart ONLY candidate once. Verify original env SHA, both independent pointers,
   health/ready/resources and production preservation. Never derive previous static
   target from previous backend ID or use switch-candidate.sh as a full rollback.
4. Retain all old/new releases, publication bundles, private control and captures.
   No deletion, database restore, forecast withdrawal or A03 action. If a previous
   forecast is expired it remains unavailable; rollback cannot make it fresh.
   Partial activation or drift requires a narrower review, no automatic repair.

No rollback record/backup/pointer is created on EC2 by this local package. A future
hash-bound transfer/activation executor still requires preparation after preflight.

## Completed local verification

Release ID: phase-forecast-consistency-20261101-v1.
Release manifest SHA-256: 9dc8ce31f1b294c43239824ffa544a76f4fdf6ba334ea8fd72b9431365ed5c19.
71 payload files / 1,298,524 bytes:26 API files,37 static files,8 review-only proposals.
The new selector is present; all API/shared source and static digests verify.
Two separately invoked supported staging-origin builds produced byte-identical
static files and the same release manifest. Local directories are sealed read-only.
No new Python dependency pins or model release changes.

319 backend/tooling tests,97 frontend tests, lint, staging production-build checks,
syntax and package verification passed. The API package passed a cold Python3.14.7
process on Darwin arm64 with network and UI/research imports blocked: all seven
Admin denials, absent-publication503 and unavailable-operations handling passed.
A local in-process seven-route HTTP rehearsal used ONLY synthetic disposable data,
with next24 unavailable, and passed. These are NOT Linux/systemd/BPF/Nginx/browser
or real Cognito acceptance results; no EC2 was accessed.

The existing requirements lock retains SHA-256
b1d8bbbec84a08b651b7bdc0b96e5bb94bf6c527297e037357702de00bcc84e3.
Its prior Linux dependency verification is historical evidence, not execution of
this new source release on EC2. The existing venv must be checked before reuse.

READY for a separately reviewed, bounded READ-ONLY staging preflight. Not a
transfer/deployment/real-publication approval. Prepare the mutation executor only
after fresh baseline/permissions/configuration evidence; bind every artifact and
all independent rollback state before requesting that next authorization.
