# Operational evidence staging release v1 — LOCAL PREPARATION ONLY

Release phase-operational-evidence-20261105-v1; transaction
9cab77d42df245c197e317a61906417f. No execution authorization. No remote operation
was performed to prepare this package. Historical manifests/packages remain unchanged.
Preflight must run under separate authorization; apply/rollback/accept each need
their own explicit authorization. No automatic rollback or deployment retry.

## Exact scope

MANIFEST.json contains every new file's SHA-256, source, destination, size and
UID/GID/mode. The private local candidate is code/static assets only, under
`data/backups/private-staging-releases/phase-operational-evidence-20261105-v1/release`.
No datasets, database, credentials, auth state, raw logs or private inspection
captures are copied. Payloads contain reviewed code/static assets only. Complete
old release manifests and every retained file are independently reverified from
unchanged approved hashes. No old manifest is refreshed to accept current source.

Production worker changes only src/scheduled_pipeline.py and two new modules:
src/shared/operational_terminal.py and src/shared/operational_evidence.py,
UID/GID1000:1000 mode0644. Existing forecast_delivery.py, forecast tools/launcher/
sudo rule, A03 parser, frozen model/contract, .env, schedules, concurrency and legacy
Streamlit/API/Nginx are preservation-only. No worker/server/production restart.

Install the separately versioned root helper at /opt/powerflow/operational-evidence-v1,
root:root0700 directories/0600 files, exact verified seven-file closure plus TOOLS.json.
Root-owned0755 launcher and0440 hash-bound anchored-argument sudo rule follow the
checkpoint3 review. No unrestricted sudo, mutable worker import or alternate args.
The old forecast publication mechanism is not used to write operational evidence.

New immutable API/static trees use root-owned0755 directories/0644 files. API clones
the approved26-file baseline and overlays app.py, market_data.py, current_operations.py
and operational contract/store. The market sampling change is required by the
current React load/wind request shape. Existing API lock/dependencies and forecast
selector/expiry bytes remain unchanged. Reuse the verified root-owned existing API
venv by exact recorded target; no package installation. Old hashed JS/CSS/woff2 assets
are retained in the NEW static tree for existing tabs. Original releases never change.

Only the staging candidate API is restarted, after source/pointer/environment checks.
No Nginx reload or routing edit. /etc/powerflow/react-api.env must match the exact
installed baseline SHA derived from the approved public proposal plus the existing
forecast-root line. Append only POWERFLOW_OPERATIONAL_PUBLICATION_ROOT with the
fixed operational path. No authentication/MFA or other settings change.

Provision only /srv/powerflow/operational-publications and releases, root:9920750,
and its exact operational namespace marker root:9920640. Preflight requires absence;
pre-existing paths fail rather than adopt or repair them. No current pointer or
publication is created by deployment. Effective API namespace read/traverse/non-write
access is tested after provisioning, not falsely certified before a missing root exists.

Operational delivery stays absent/disabled through installation and candidate
acceptance. The FINAL activation changes only the existing deployment job_variables.env
POWERFLOW_OPERATIONAL_EVIDENCE_ENABLED=true, preserving every existing variable and
POWERFLOW_AUTO_PUBLICATION_ENABLED=true. The feature flag is not written to .env.
Queued override, worker env, process-command, work-pool template and SDK-source gates
must pass. There is no ingestion, forecast invocation, publisher invocation or Prefect
run trigger in deployment. Subsequent authentic natural-run operational delivery is
the effect of separately approving that final activation step.

## Linux preflight

The preflight payload excludes transaction.py and all mutation functions from the
reused deployment guard. Its own operations are reads, fixed read-only HTTP and
bounded syntax/system-information commands. No transaction, directories, permission
changes, installs, restarts or PATCH. Root/Linux/x86_64/procfs/O_NOATIME, pinned SSH
identity/host key, fixed pointer/release inventory, source metadata and old pipeline
hashes, API dependency metadata, SDK worker/env source and engine hashes, identities,
service isolation/BPF/cgroups, resource capacity, routing and health are required.

It reuses the reviewed idle guard: zero active Prefect runs/ingestion engines,
zero occupied slots, exact hourly :45UTC schedule/concurrency1, >600 seconds before
every relevant queued/nominal execution. Additional operational-helper processes
also block. Exact known helper/publisher files, parser, frozen artifacts and current
forecast bundle are preservation checks. No AWS/IMDS/secret-provider/source requests.

System binaries must be trusted root-owned real targets. Actual candidate version
and dependency metadata must match the existing locked Python3.14.7 installation;
new standalone modules target system Python>=3.9. The installed worker source must
match reviewed Prefect3.7.2 hashes and process work-pool env semantics. The preflight
reports future operational-root access as DEFERRED_UNTIL_PROVISION. Linux execution,
visudo, true mount-namespace service access and runtime import/durability cannot be
certified by macOS offline tests. Stop on failure; never refresh hashes from host.

## Apply, backups, drift and rollback

Every action re-verifies the new manifest, retained closure, candidate artifacts,
assembled payload and original pinned connection profile before SSH. One connection,
no retry. Preflight/accept: remote90s/local150s; apply/rollback: remote120s/local180s;
TERM escalation5s. Private local captures0700/0600, bounded sanitized output. The
manifest execution_authorized=false prevents this preparation claiming owner approval;
explicit future action authorization remains required outside the code.

Apply repeats fresh preflight immediately before any writes. The first mutation is
a private root0700 transaction directory; changed=true means mutation attempted,
including uncertain filesystem failure at that boundary. Independent root0600
backup copies (distinct inodes), exact hashes/bytes/metadata, previous pointers and
unchanged deployment projection/variables are verified before installation. Record
phases identify BACKUP, INSTALL, POINTERS, ACTIVATE and APPLIED. If backup fails before
record creation, no application file has been changed: retained private artifacts
require inspection; no manual cleanup/retry is automatic. A valid record and both
backup copies are mandatory for restoring application state.

Stop on drift, source collision, invalid existing sudoers, wrong ownership, unknown
job-variable shape, secret-bearing job environment, service/routing/capacity/window
failure, or failed acceptance. No gate is weakened to compensate for old source
hash mismatch. Only the new transaction may accept the new file closure. Existing
forecast source-manifest test intentionally continues to reject changed worker source.

Rollback is independently manifest-bound and not automatic. Before mutation verify
transaction/backup identities and metadata, old immutable releases/venv, permissible
old/new source/env/pointers, restricted privilege files, idle gate and preservation.
Disable operational flag by restoring the exact saved deployment variables FIRST;
restore original worker bytes/metadata and API env, restore pointers and restart only
the candidate, remove only exact new launcher/rule/new worker files. Verify restored
bytes, role routes/health and unchanged policy/forecast artifacts. Unexpected drift
blocks rollback before writes. New helper/API/static trees and operational store/
publications remain retained and disabled for evidence; they are never recursively
deleted. Old releases and all forecast-publication artifacts are untouched.

Partial installation is reconciled only when declared mutable files are missing,
original or exactly installed, with valid backups. Failed atomic operations or
post-activation sync/PATCH uncertainty require evidence review before any retry.
No silently successful or automatic rollback/cleanup is inferred from exceptions.

## Natural-run acceptance

accept is a read-only separate action. Require APPLIED transaction and a completed
post-activation actual natural run (activation timestamp bounds are recorded, not
an invented exact time). Join fresh Prefect/task/persisted/receipt evidence using
checkpoint3's mandatory stable IDs. Validate operational release hash/pointer,
chronology,90-minute freshness and public/Pipeline equality/no-store. No historical
SQLite fallback. Verify active forecast independently:200 with24 genuine targets
or503 FORECAST_WITHHELD with matching Operations state; preserve normal expiry.
Admin anonymous rejection and same-source Admin projection are machine checked.
Authenticated Admin/Analyst HTTP and actual Overview/Pipeline Chrome acceptance
require owner participation; report PARTIAL/PENDING rather than invent browser or
session evidence. No tokens, test identities or fake runs are introduced.

## Local-only test boundary

Tests exercise manifest/hash/closure rejection, strict variables/environment policy,
read-only preflight and command restrictions, staged API imports in an isolated local
process, and native temporary-file apply/rollback control flow with mocked Linux
ownership/health/Prefect/sudo/service boundaries. They do NOT prove remote ownership,
Linux procfs/NOATIME, systemd/sudo or endpoint reachability. No remote call or service
operation is executed. The candidate production frontend build is origin-checked;
no dependency is installed and no release is deployed.

Additional explicit gates: all installed API site-packages are read/hash inventoried
within bounded root-owned/no-follow limits, and fixed imports run as UID/GID992 with
no-new-privileges in the existing candidate mount namespace (-I/-B, no app/source/
model import, no requests or caches). This establishes actual compatibility and a
fresh drift fingerprint of the unchanged trusted installed environment, not an
independent vendor attestation for every installed binary. Prior approved lock,
versions, ownership and installation provenance remain required. The same closure
must remain unchanged during rollback. Original first-publication tools are checked
alongside automatic-publication tools. API EnvironmentFiles and only the three
approved public root-path process settings are verified; unrelated environment
values are never printed, retained or transferred.

Old hashed static chunks are reused from the verified old immutable static tree
rather than transferring duplicate bytes; copy source and hash are explicit in
MANIFEST.json. This keeps the bounded apply payload below2MB without raising the
body/response limits or changing any original gate. The private candidate archive
and preserved original archives/profile must remain available for local reassembly;
missing artifacts fail closed. No private artifact directory should be Git-added.

A single candidate restart is followed by explicitly bounded read-only startup
observations (at most10,15s soft deadline plus current bounded HTTP call). These
are readiness observations, not another restart/deployment or SSH retry. Failure
stops before feature activation. The outer120s transaction limit remains final.
Rollback preservation is measured freshly at rollback start: legitimate natural
forecast updates after apply are retained rather than misclassified as drift.
Fixed model/tool/source/configuration invariants are still independently checked.

## Recorded offline validation

Final selected Python regression: 442 passed, 1 intentionally deselected historical
source-integrity assertion (25 release-package cases included). The old assertion
and its manifest remain unchanged and must continue rejecting the new worker source.
Frontend regression: 113 passed. The production TypeScript/Vite release build and
staging-origin artifact guard passed. All new source and assembled payloads are
checked against Python 3.9 grammar; execution tests used local Python 3.14.7.
Linux-specific gates and genuine post-activation/browser acceptance remain pending.
