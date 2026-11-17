# Guarded automatic forecast publication activation

LOCAL PREPARATION ONLY. No network operation, deployment, inference or publication
is performed by building or testing this package. Apply and rollback each require
separate explicit authorization. There is no implicit rollback or retry.

## Exact change scope

The original first-setup manifest274bf50c731bc5ff074d8dae28b87126055e70db663081b4ee3d68165d9217b7
and tools archivefaeec014b4cde838fcffb3c285eef1995f38547d443162e529fa90ec7209a6b3
are preserved. The old installed tools lack automatic delivery/monotonic issue
protection. They are verified unchanged, never overwritten.

Install five NEW tools at /opt/powerflow/forecast-publication-automation/:
automatic.py, prepare.py, publish.py, shared/__init__.py and
shared/forecast_publication.py plus automation-manifest.json. Directories root:root
0700, files0600. The new JSON manifest contains exactly installed_tools from the
source manifest. New publisher reuses the same bundle schema and atomic current
mechanism. Existing API tests verify the contract; actual deployed API acceptance
remains mandatory. No model or dependency installation is included.

Install /usr/local/sbin/powerflow-publish-next24 root:root0755 and
/etc/sudoers.d/powerflow-publish-next24 root:root0440. The rule is digest-bound to
that launcher with anchored UUID-only arguments. NOSETENV, no root shell/Python
command grant, no caller-supplied command/path. System Python -I -S -B, clean env,
30s timeout/5s escalation; root-private executable dependencies verified from held
bytes. Receipt files are data, never executable code. Producer UID1000, root,
trusted OS binaries and local Prefect remain trust boundaries. The rule adds no
unrestricted grant and does not remove or constrain any pre-existing administrator
sudo rights. Do not claim the entire account lacks broader existing privileges.

Replace only production src/scheduled_pipeline.py (UID/GID1000,0644) and create
src/shared/forecast_delivery.py (1000:1000,0644). Historical reviewed pipeline hash
571e3b56c34bc17a38dc13bad066def40c9c711bf51f74aff466014b9afcce8b
is a mandatory live precondition, not a claim of freshly observed source state.
Drift aborts before any write; never refresh it automatically.

Enable only POWERFLOW_AUTO_PUBLICATION_ENABLED=true in the EXISTING Prefect
DEPLOYMENT job_variables.env. The patch sends only job_variables, preserving all
other entries and all schedule/concurrency settings. No shared secret .env, worker
unit or running process environment is edited; no service restart is needed.
Local installed Prefect DeploymentUpdate supports this field; its process worker
merges current deployment env into each flow subprocess at preparation time.
The exact worker-base source hash is pinned in CONFIG and must match production
passively before apply. Work pool must be process/electricity-pool, unpaused and
have the expected env template; queued run overrides cannot mask the flag. Unknown
versions/semantics fail closed as WORKER_ENV_MERGE_UNVERIFIED. This is a live
compatibility gate, not already established Linux acceptance.

The local receipt association now accepts the observed natural flow start15ms
before scheduled time. Scheduled occurrence must still be :45 and not future;
flow/task/receipt chronology, unique completed task, UUIDs, deployment identity,
source completeness, model and freshness gates remain unchanged. This corrects
an association defect; no model or forecast freshness threshold changes.

## Fresh preflight and transaction

One fixed transaction is embedded in MANIFEST.json. No command accepts arbitrary
host, command or transaction. Existing transaction/tools/launcher/rule/delivery-file
conflicts abort. Existing paths are never chmod/chown repaired or overwritten.

Reuse exact manifest-bound staging guard library for zero active Prefect runs,
zero ingestion/engine processes and occupied slots, schedule45 * * * * UTC,
concurrency1/original collision policy and >600s before EVERY relevant next run.
Require >=768MiB available RAM and >=2GiB disk after allowance. Recheck immediately
before install and activation. Require current backend/static pointers to the
known phase-api-body-bound-20261102-v2 targets, candidate UID/GID992, one worker,
MemoryHigh384MiB/MemoryMax512MiB/MemorySwapMax0, effective cgroup/BPF/sandbox and
loopback binding. Require candidate health/readiness, staging TLS homepage,
production API health and Streamlit health. Verify A03 hotfix hash and production
preservation fingerprints. No historical service PID baseline is substituted for
current before/after evidence. Original tools and root:992 publication paths are
verified before and after apply.

Before candidate/pipeline changes, create root-private0700 transaction directory
/var/lib/powerflow-staging/publication-automation-<transaction>/ and durably save
record.json0600 with exact pipeline bytes, owner/group/mode/hash, original full
job_variables and unchanged configuration projection. Job variables may contain
private values: the record must never be printed or committed. The backup is
read back before install. Validate proposed sudoers from stdin and the existing complete configuration before
ANY write; retain and recheck the proposed rule with visudo-cf before installing
it; validate the full sudo configuration afterward. Unsupported regex syntax stops
before transaction creation or activation; no rule weakening is permitted.

Apply installs code, verifies exact hashes/modes, then enables the one env flag LAST.
Read back env and unchanged schedule/config projection; recheck runtime/health and
production fingerprints. No helper call, receipt transfer, inference or pointer
switch is performed by apply itself. The NEXT eligible NATURAL run performs delivery
under the new configuration. Approval of activation must explicitly authorize
those subsequent validated automatic publications, not just the installer writes.
The installer does not poll/wait for future runs.

## Bounds and exact future commands

Run --local-check now to verify source closure, retained payload, profile and host
key without connecting. All remote execution is root system Python via the existing
strict pinned SSH wrapper; sudo-n, one attempt, no forwarding, no retry. Apply remote
120s/local180s; rollback remote90s/local150s; TERM/KILL5s, output131072 bytes per stream.
Captures are private under the existing ignored evidence root. Both payload hashes
and every source size/hash are in MANIFEST.json. Executable bytes remain retained
from verification through SSH stdin; no post-check executable path reopen.

After manual commit/review and separate authorization:

    venv/bin/python -I -B deploy/staging/forecast-publication/automation-deployment/run.py apply --manifest-sha256 <APPROVED_MANIFEST_SHA256>

Independent rollback, only with authorization:

    venv/bin/python -I -B deploy/staging/forecast-publication/automation-deployment/run.py rollback --manifest-sha256 <SAME_APPROVED_MANIFEST_SHA256>

## Failure and rollback

Preflight failure returns BLOCKED/changed=false with a sanitized cause; no remote
writes. After transaction creation any failure returns PARTIAL, phase and transaction;
no implicit retry/cleanup/rollback. Process termination may leave the private report
absent: never infer no mutation from absent output. Inspect the transaction before
recovery. A failure before record.json is durable may leave only a private empty
transaction directory; no pipeline mutation is possible before backup verification.

Rollback requires current idle/window/isolation/health guards, exact transaction,
valid original source backup, unchanged deployment configuration and job_variables
matching exactly old or installed values. Current modified files must be either
verified original or approved replacement; unexpected content/symlink drift aborts
before rollback writes. Disable by restoring the original full job_variables FIRST,
then restore exact original pipeline bytes/metadata, remove only the verified new
delivery source, sudoers rule and launcher, validate sudoers and recheck health and
production preservation. The before/after preservation baseline is fresh for rollback;
legitimate intervening natural forecast updates are not compared with old data hashes.
Root-private inactive tools, backups and transaction records are retained. Existing
published forecasts are NOT removed/restored by code rollback; normal expiry still
withholds them. A separate exact-current publication withdrawal is independently
reviewed if needed. No forced cleanup or expired forecast restoration is allowed.

## Minimum live acceptance after separate activation approval

Observe the next naturally scheduled flow, verify actual GENERATED outcome and
explicit committed receipt UUID, 31 ordered features,24 finite aligned UTC targets,
model69a3fa10f45c18c4733b3f8e12792e36ec9b209b7afd5e94a9932315e4dde0ed,
contract1d6554e469a869613dd91d820b0537b4562321ea69e8827ecb83137950078a88,
reciprocal hashes and persisted prediction binding. Verify separate PUBLISHED task
status and root-owned immutable bundle/current pointer. Record issue, completion,
publish time, cutoff and remaining seconds; never extend expiry. Observed09:45
run left12m33.66s after completion. The latest completed-only receipt inspection
could not establish10:45 run state; deployment is not conditioned on guessing it.
Fresh idle/window gates decide whether installation can proceed.

Require API200/no-store and exact24 matching values, operations VALID, React chart,
UTC times/model/provenance and24 horizons versus remaining-future count. Verify the
next eligible natural run advances issue monotonically. Existing deterministic
regressions cover concurrent/duplicate/older/invalid/expired inputs, so do not inject
fake live data for negative tests. At natural expiry require503 FORECAST_WITHHELD/
no-store and hidden stale current-chart/export. Maintain Analyst/Admin permissions,
seven historical pages and production Streamlit. If withheld, missing or failed,
report the exact publication status separately; do not call inference failure from
COMPLETED/FAILED publication state alone.

## Remaining assurance boundaries

Local unit tests model privileged OS operations; no local root or real sudo changes
are made. Linux visudo parsing, actual worker version/env merge, live ownership,
resource costs and natural end-to-end publication remain UNVERIFIED until guarded
activation/acceptance. Root helper history read is bounded64MB; larger history fails
closed. There is no unrestricted root command, no new scheduler, no inspector
extension, no frontend deployment, no original archive/release/model/data rewrite.
