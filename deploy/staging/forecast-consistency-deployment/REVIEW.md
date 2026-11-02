# Controlled forecast-consistency staging deployment — NOT executed

LOCAL preparation only. Separate apply and rollback authorizations are required.
No previous read-only approval covers either operation. Stop for manual commit.

## Immutable inputs and retained conventions

Release ID phase-forecast-consistency-20261101-v1, original release-manifest SHA256:
9dc8ce31f1b294c43239824ffa544a76f4fdf6ba334ea8fd72b9431365ed5c19.
The runner verifies all71 original payload files but embeds ONLY26 api/ and37 static/
files into a deterministic SSH-stdin payload. All8 proposals are excluded. It does
not rebuild/rewrite the private release, transfer datasets, install packages, copy
models or publish a forecast. The existing root-owned isolated venv is reused by
link inside the new backend release. Current API/lock hashes must match the known
pre-hotfix/post-market-context baseline in the reviewed preflight helper.

The manifest binds all executable project dependencies: job, runner, existing
preflight/SSH helper definitions, pure rollback-record validator, smoke tool,
this review and new tests. All code is retained as verified bytes; no executable
path is reopened for execution. Existing deployment unit/Nginx proposals are NOT
installed. No additional full backend or instance is launched.

## Future commands — do not run without new explicit approval

Local validation only, zero connections:

```sh
venv/bin/python -I -B deploy/staging/forecast-consistency-deployment/run.py apply \
  --manifest-sha256 APPROVED_DEPLOYMENT_MANIFEST_SHA256 --local-check
```

ONE deployment attempt, after explicit apply authorization:

```sh
venv/bin/python -I -B deploy/staging/forecast-consistency-deployment/run.py apply \
  --manifest-sha256 APPROVED_DEPLOYMENT_MANIFEST_SHA256
```

ONE separately approved rollback attempt:

```sh
venv/bin/python -I -B deploy/staging/forecast-consistency-deployment/run.py rollback \
  --manifest-sha256 APPROVED_DEPLOYMENT_MANIFEST_SHA256
```

The exact manifest and assembled apply/rollback hashes are printed in the review
response. The manifest cannot self-hash. Runner reuses approved private identity,
strict pinned host-key settings, -F/dev/null and noninteractive sudo. One SSH stdin
connection, no retries. Apply remote timeout300s/local360s; rollback remote180s/
local240s. TERM then KILL after5s; stdout/stderr each capped131072 bytes. Exact root
command is sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s <bound>s
/usr/bin/python3 -I -S -B -. A3/IAM/Cognito/DNS/TLS are outside scope.

## Exact writes requiring authorization

- New root-owned API directory:
  /opt/powerflow/releases/phase-forecast-consistency-20261101-v1/
  (directories0755/files0644), .venv-api symlink to the verified retained venv.
- New root-owned static directory:
  /var/www/powerflow-staging/releases/phase-forecast-consistency-20261101-v1/
  (directories0755/files0644).
- New root0700 control directory:
  /var/lib/powerflow-staging/forecast-consistency-20261101-v1/;
  conditional parent /var/lib/powerflow-staging/ root0700 if absent. Exact env
  backup previous-api.env and atomic state.json are root:root0600. State records
  independent old/new targets, env hashes, service state, baseline and asset hashes.
- Replace ONLY /etc/powerflow/react-api.env with exact original bytes plus one
  newline-delimited POWERFLOW_FORECAST_PUBLICATION_ROOT=/srv/powerflow/forecast-publications.
  Owner root:root0600; original SHA must equal the inspected baseline
  ee1ea96ebd2aa9b1c15891fd4cb9adf1c6ee7d06d6177b99bb1f375419b36704.
- Switch ONLY /opt/powerflow/react-current and /var/www/powerflow-staging/current,
  independently. Atomic temporary .forecast-consistency-<UUID> siblings are used
  below those pointer parents, the candidate-env parent and private control dir.
- Restart ONLY powerflow-candidate-api.service (already active is required).
  Rollback likewise restarts only this unit to restore its original active state.

The publication root is NOT created. A missing root is supported by the API and
is the initial acceptance state. No bundle, cache, DB or model path is written.
No Nginx edits/reloads or production-service actions are included. The failed
attempt's partial/new/temp artifacts are retained; there is no automatic deletion,
repair, full redeployment retry or rollback.

## Apply gates and ordered activation

1. Verify all incoming file hashes/sizes/paths and exact release scope before any
   remote writes. Reject pre-existing new release/control paths, unsafe ancestors,
   unexpected publication root, env drift or old code/lock drift. Independent pointer
   target digests must match the saved successful preflight; no guessed target names.
2. Check current candidate runtime restrictions and passive dependency metadata;
   do not run a root/UID probe importing application code. Require actual active
   candidate/current paths, verified root-owned venv and no installation need.
3. Require >=768MiB MemAvailable and >=2GiB free AFTER predicted copies on relevant
   filesystems. Verify known Prefect schedule/concurrency, no active ingestion/run
   and >10min window. Recheck immediately before pointer/env activation.
4. Capture production service PID/state and exact configuration/public certificate,
   historical publication/model-metadata/forecast fingerprints. They must remain
   identical throughout. The candidate PID is intentionally excluded, but its unit
   and all protections must remain unchanged.
5. Save exact env bytes and rollback state BEFORE pointer/env changes. Backup files
   and containing directories are fsynced before activation. Reuse the
   pure existing rollback-state schema validator; never infer prior target IDs.
6. Install only immutable API/static content and venv link. Retain existing root-owned
   public hashed assets (assets/*.js, *.css, *.woff2 only) in the installed static
   directory, with a separately recorded baseline inventory. Existing asset names
   must match bytes or abort. This installed union does not modify the preserved
   release. Old index/build config never replace new content. Inventory is bounded
   to160 files/8MiB; retained files are hash checked before copying.
7. Recheck capacity/window/preservation; atomically add the single env key, switch
   backend pointer and restart only candidate. Startup observation is explicitly
   bounded: at most10 health/readiness observations,1s apart, each request<=3s.
   These observations are not retries of deployment or ingestion.
8. Verify actual candidate PID/cwd, UID/GID992, one worker, sole owning loopback8010
   socket, full existing sandbox properties, capabilities/seccomp, IMDS deny,
   effective384/512MiB and zero swap limit/current, ingress/egress BPF attachments.
   Successful app startup occurs INSIDE the actual existing unit, with no separate
   unsandboxed import/lifecycle process or second backend.
9. Require /health200 and /ready200; forecast endpoint503 exact FORECAST_WITHHELD
   with no-store; operations200 MISSING_PUBLICATION and historical/unavailable health.
   Require one-hour/coverage/pipeline/models historical APIs200 and unauth Admin401.
   This proves missing-root behavior in the service, not future bundle readability.
10. Only after backend acceptance switch static pointer. Verify HTTPS index bytes,
    all root-referenced entry assets, /api/health200, private /api/ready404 and
    unchanged ACME200. Verify production preservation again; record COMPLETE.

## Frontend, roles and full acceptance

After activation, separately approved interactive acceptance uses existing tooling:

```sh
venv/bin/python -B scripts/smoke_staging.py \
  --origin https://staging.powerflowenergy.dev \
  --expected-publication MISSING_PUBLICATION
```

The owner enters access tokens only into the tool's private TTY prompt, never chat,
argv, files or logs. It verifies all7 routes /, /analytics, /forecasting, /anomalies,
/models, /pipeline, /profile plus callback HTML, API integration, server roles,
all7 Admin-route401/Analyst403 denials, Admin provenance503 with no-store and the
missing-publication operations contract. Do not run this without authorization for
real authenticated requests. Google/native sign-in/sign-out require manual owner
participation; no credentials are automated. HTTP shell delivery is not equivalent
to a fully rendered browser test; inspect all pages and browser console manually.

409 changed-publication behavior and expired/valid/malformed contracts are tested
locally using synthetic fixtures. A genuine live409 needs an independently approved
valid publication and stale issue/completion query; do not manufacture a bundle to
obtain it during this deployment. Existing stale-tab tests cover controlled recovery;
retained old public assets additionally avoid chunk404 from the installed old release.
Historical operations are NOT live pipeline/forecast health. /ready200 alone never
establishes forecast availability or inference receipt authenticity.

## Rollback verification and limits

Rollback is NOT automatic or part of an apply authorization. Reverify current
production baseline, retained old API/static inventories, exact backup env digest,
root0700 control permissions, approved target scope and current pointers/env matching
either recorded old/new state. Abort on unrelated drift. Restore static pointer,
backend pointer and exact original env independently, restart only candidate,
verify health/ready, original runtime security and original HTTPS index hash,
then verify production preservation. A zero systemctl exit alone is insufficient.
Retain new releases and all control/partial/temp artifacts for review. Do not delete
anything. Restoring files cannot undo external requests or a changed producer;
this package performs no producer action. Capacity/window gates may themselves
block rollback; emergency candidate-stop or permission repair is NOT authorized
and requires a separately bounded owner decision. No guaranteed zero downtime:
staging API restart briefly interrupts staging; production routing is unaffected.

## Local versus live evidence

Synthetic tests validate filesystem install/switch/rollback, no-write preflight
failures, post-switch failure stops, drift rejection and missing-publication contract.
Linux kernel enforcement, resource peaks, old-tab/live OAuth behavior and actual
installed Python imports remain real acceptance gates. Prior preflight resource
measurements are historical; never substitute them for fresh activation gates.
Stop on memory pressure/failed gates; do not raise caps or install dependencies.
This is preparation only, not a claim of activation or runtime acceptance success.
