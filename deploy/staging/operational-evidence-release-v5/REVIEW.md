# Operational evidence v5 — prepared locally, no deployment authorization

Release phase-operational-evidence-20261107-v5; transaction
4f6cf4afa15647b0b14d904b50379ef1. Preflight/apply/rollback/accept each require separate
owner authorization. No automatic retry or rollback. All original v1-v4 packages,
historical transaction records and private captures remain unchanged.

## Evidence and minimal routing correction

The authorized one-connection inspection at2026-11-07T07:20:44Z verified the fixed
/etc/nginx/conf.d/powerflow-staging-https.conf, root:root0644, SHA-256
ba9cc88e8a9b8f9401a713ccc2289f1c4375aa734745a6bfdbb431ce240e96ba.
It exactly matches the independently retained approved staging config. The main
configuration includes this file in http context, the expected Nginx master is
running, and all three operational-current routes are absent from its allowlist.
Each routed GET returns404 text/html,146bytes, a sanitized Nginx error page. This
reproduces the HTTP_BOUND content-type failure, not an oversized-body failure.
The original failed endpoint/response was not captured, so that historical detail
is unknown. Direct legacy probes retained /api prefixes and are not evidence of
the correctly stripped backend routes. EVIDENCE.json states that limitation.

The bound proposal changes exactly one allowlist line to add
/api/operations/current, /api/pipeline/current and /api/admin/operations/current.
Everything else is byte-identical: authentication forwarding, TLS, cache/headers,
rate limits, body limits, upstream, internal-route denials and unrelated settings.
Proposed config SHA-256:
ee2549fd1196f5691fb60627dc75d408e9dbc858225383d198945e4597f6d7b7.
Future preflight requires the exact observed main-config hash and original staging
config bytes/metadata. No dynamic hash refresh, arbitrary patch path or version
fallback. The helper's request/body guards remain enforced; failures now identify
the approved endpoint ID, status, content-type category and measured size without
response contents. JSON syntax/size failures never count as successful acceptance.

## Reuse after successful v4 rollback

The original v4 transaction321a9d8a1d7a483d923b84bc1917b0a9 is required to have a
valid ROLLED_BACK journal, matching original variables/pointers/backup identities.
Fresh preflight verifies this against its separately bound approved manifest.
Existing /opt/powerflow/operational-evidence-v1 is reused ONLY with exact eight-file
inventory, hashes, root0700 directories/0600 files and no unexpected entries.
Existing operational store and releases must be root:9920750, with the exact
root:9920640 namespace marker, no current pointer and empty releases. Its actual
candidate-namespace read/traverse/non-write access is tested as UID/GID992 with
no-new-privileges. Missing, modified, nonempty, symlinked or conflicting states
block before mutation. Apply never reinstalls/recreates these retained resources.
Retained v4 API/static trees and all evidence remain untouched.

## Reviewed write/service scope and activate-last transaction

MANIFEST.json lists129 destinations: the same128 v4 hashes plus this one Nginx
configuration. API/static are NEW immutable root0755/0644 trees, same code/build
bytes as v4, verified retained hashed assets copied only from the approved active
static tree. No dependency installation, API/frontend rebuild or model change.
Worker changes remain the three reviewed operational integration files1000:1000
0644; root-owned0755 launcher and0440 restricted hash/argument-bound sudo rule.
No shared .env edit or production dashboard/API restart. Operational delivery stays
disabled through installation and ALL routed acceptance.

Apply repeats fresh preflight twice. Create distinct-inode independent root0600
backups of original API env, pipeline and staging Nginx config, verify hashes and
metadata, then persist a transaction journal before installation. Reverify retained
helper/store without writing them. Record ROUTING before atomic config replacement.
The newly authorized service scope MUST explicitly include `/usr/sbin/nginx -t`
and ONE `systemctl reload nginx.service`; stop on errors/warnings, never retry.
Native syntax validation is deferred from read-only preflight because it can open/
create configured logs and read TLS private keys internally. No private-key bytes
or raw command output are exported. Only this staging configuration may change;
production/acme configs, public cert, datasets, models and services retain their
existing fingerprints. Hash the main config, immediate conf.d files and staging
security-header config before/after; normalize ONLY the exact approved old/new
staging-config digest when checking unchanged production fingerprints. Unexpected
hashes or other file/service changes still fail closed. No arbitrary exclusions.

Then switch staging API/static pointers, append only the operational root setting
to the exact saved candidate env, and restart ONLY the candidate API once. Require
direct health/readiness, sandbox/namespace/env checks, matching static index,
operations/current and pipeline/current200 JSON MISSING/no-store/equal public views,
anonymous Admin401, and existing forecast200/24VALID or503FORECAST_WITHHELD/no-store.
Validate production preservation. FINAL step enables only the operational flag in
the existing Prefect deployment job_variables.env, preserving forecast publication,
schedule, concurrency and other variables. No manual inference/publication/flow.

## Fresh gates, limits and rollback

Keep pinned SSH identity/host key, all immutable/dependency/private-artifact bindings,
Linux/procfs/NOATIME, reviewed Python/Prefect3.7.5 sources+metadata, exact62-file
historical static baseline, permissions, candidate isolation, routing, resource
capacity, model/feature contracts and original publisher guards. Require zero active
runs/ingestion/helper processes/slots, correct hourly:45UTC schedule/concurrency1,
and strictly>600s before every relevant execution. Preflight/accept remote90s/local150s;
apply/rollback remote120s/local180s; five-second TERM escalation; one SSH/no retries.
--local-check never connects. Private captures0700/0600. No AWS/source queries.

Rollback requires separate authorization and verifies journal, both independent
copies, original immutable trees, exact permissible old/new state, Nginx/pool/runtime,
idle window and fresh production/forecast preservation BEFORE mutation. Restore old
deployment variables first (disable operational delivery), original worker/env/Nginx
bytes/metadata and old staging pointers; restart candidate only. If routing was
attempted, syntax-test and reload Nginx ONCE after restoring the original config.
Verify original Nginx hash, candidate health/env, deployment policy, production and
forecast preservation. Remove only verified new worker/launcher/rule files; retain
immutable trees/helper/store/publications for evidence. Legitimate newer natural
forecast publications since apply are preserved. No automatic recovery/cleanup.

After authorized activation, accept requires a genuine completed post-activation
natural run, stable run/task/internal UUID association, persisted execution/inference/
delivery outcomes, operational release/pointer/hash/freshness and cross-API equality.
Live forecast validity remains independently assessed with unchanged expiry rules.
Owner-authenticated Admin/Analyst and real React acceptance remain pending; never
claim these from offline tests or publish to manufacture a passing result.

## Local test boundary

Offline tests use synthetic fixtures and isolated files, mocked Linux ownership,
systemd/Nginx/Prefect/HTTP boundaries. They do not prove native Nginx syntax, real
Linux metadata or fresh deployment conditions. No additional remote operation or
service change occurs during preparation. Historical integrity assertions and
original releases remain unchanged; no new release failure is deselected.

Final local validation: 759 selected Python cases passed, including93 v5 cases
and33 routing cases;113 frontend tests passed. The one unchanged historical
source-manifest assertion remains separately excluded because it intentionally
rejects newer scheduled-pipeline bytes; no v5 failure is deselected. Python3.9
grammar, local Python3.14.7 execution, all four payload bindings, prior immutable
release preservation and local pinned-profile checks passed. No API/frontend code
or build bytes changed, so no rebuild is claimed. Native Nginx syntax and fresh
Linux guards remain prerequisites for the separately authorized transaction.
