# Guarded automation continuation — local preparation only

This is a NEW package and transaction. The failed deployment, manifest48a17404aa82c2fc16ab961311a7007224e1ee7016ecbc6ca5de04bed8aed389,
transaction73080d9ca8fd4c3f9f143fd4ae84a123 and its rollback/evidence remain untouched.
No remote operation, publication, inference, installation or Git operation is
performed by building/testing this package. Fresh apply and rollback authorizations
are independently required. There is no automatic retry, rollback or repair.

## Evidence and focused correction

The authorized metadata inspection at2026-11-03T12:32:23Z found production src to
be a real1000:1000 directory0755, src/shared absent, and all six retained automation
files exact/root-owned0600 under root:root0700 tool directories. These are current
post-rollback observations. They support the reproduced missing-parent mechanism;
the historical first exception is still unverified and is not invented here.

The continuation validates src and src/shared BEFORE any write. A present shared
must be a real1000:1000 directory0755. Symlink, file, unexpected owner/mode, unsafe
ancestor, parent drift or an existing delivery module stops without mutation.
No chmod/chown repair of existing paths and no recursive permission operations.

If absent, create ONLY the approved src/shared as1000:1000,0755. Before creation,
journal intent in the fresh private record. Use an anchored no-follow src directory
fd; mkdir shared0700, open no-follow, durably record its device/inode and initial
owner/mode, then fchown/fchmod only that fd to1000:1000,0755 and record completion.
Creation is a transaction-owned mutation. A crash between mkdir and inode journaling
is explicitly UNRECORDED_SHARED_DIRECTORY: rollback cannot claim/delete an unknown
directory. No inferred ownership or force cleanup is permitted.

Before mutation, verify and REUSE /opt/powerflow/forecast-publication-automation.
Exactly five source files plus automation-manifest.json; directories root:root0700,
regular single-link files root:root0600. Bounded two-directory inventory, <=8 entries,
exact original hashes. Never reinstall, overwrite, chmod/chown or delete retained
tools. Recheck before activation and normal installed-file acceptance. Original
manual tools/archive remain independently verified and untouched.

## Original safety controls retained

- Verify the new manifest, payloads, full source/dependency closure and the original
  immutable manifest/closure before SSH. Retain executable bytes through transmission.
- Fixed pinned SSH target/key/identity, sudo-n, no forwarding or command/host override.
- Original transaction record must be root-private, hash-valid and ROLLED_BACK;
  current deployment variables must match that original restored state. Original
  record contents may contain private configuration: never output them.
- New transaction directory must not exist. Launcher/rule/delivery must be absent.
  Exact original pipeline hash571e3b56c34bc17a38dc13bad066def40c9c711bf51f74aff466014b9afcce8b
  and1000:1000/0644 are rechecked. No automatic hash refresh.
- Same worker/source pin, process-pool env semantics, schedule45 * * * * UTC,
  concurrency1/original collision policy, zero active work/processes/slots,
  strictly >600 seconds before every relevant next run, >=768MiB available RAM
  and >=2GiB post-install disk allowance. Existing worker privileges unchanged.
- Same current staging pointers, UID/GID992, one worker,384/512MiB high/max,
  zero swap, effective cgroup/BPF/sandbox, loopback binding and service health.
  Same production API/Streamlit/routing/certificate/data and A03/model fingerprints.
- Fresh independent source/metadata and complete deployment-variable backups,
  durably read back before installation. Source manifest, model, feature ordering,
  three-hour expiry, receipt validation, lock/CAS and duplicate/older-issue rules
  remain unchanged. No shared .env, schedule or service restart.

Only source-directory handling, verified retained-tool reuse and bounded failure
reporting differ from the original installation sequence. The publisher launcher
and digest-bound UUID-only sudoers rule are IDENTICAL to the prior reviewed package.
No general shell/Python sudo grant; pre-existing administrator rights are unchanged.

## Exact proposed writes and sequence

1. Create only /var/lib/powerflow-staging/publication-automation-<NEW-TRANSACTION>/
   (root:root0700) and record.json/sudoers.new (root:root0600). Backups include exact
   original pipeline bytes/owner/mode, deployment variables, src/shared existence,
   directory identities and controlled creation states. Original record untouched.
2. Create src/shared only if absent as above. Never write an __init__.py to a
   pre-existing directory. The new stdlib-only module supports a Python namespace
   shared package; local isolated import is tested. Live interpreter acceptance
   remains required. Source namespace conflicts in the real environment are not
   silently bypassed.
3. Install root:root0755 /usr/local/sbin/powerflow-publish-next24; install ONLY
   src/shared/forecast_delivery.py and src/scheduled_pipeline.py1000:1000/0644;
   install /etc/sudoers.d/powerflow-publish-next24 root:root0440. Validate sudoers
   from stdin before ANY write and full sudo configuration after installation.
4. Verify exact installed hashes/modes and unchanged retained tools. Recheck live
   guards. Enable ONLY POWERFLOW_AUTO_PUBLICATION_ENABLED=true in existing Prefect
   deployment job_variables.env LAST, preserving all unrelated entries/settings.
5. Read back exact env/config projection; health and preservation checks; mark the
   NEW record APPLIED. No helper invocation, manual run or publication by installer.
   Activation authorization must cover subsequent eligible NATURAL publications.

Atomic source writes use narrowly scoped same-directory temporary files; transaction
record updates use the same durability checks. No ingestion, model execution or
forecast data transfer occurs. No frontend/candidate release files are modified.

## Failure evidence

INSTALL operations have bounded operation/path identifiers: shared creation/metadata,
launcher, delivery, pipeline, sudoers and installed/retained verification. Public
errors contain phase, cause, error_category, operation, path_id and errno only.
No raw paths, env values, tokens, receipt feature vectors or exception messages.
Detailed bounded traceback/errno is saved as failure-<action>-<nonce>.private.json0600 (exclusive creation; never overwrites an
earlier apply or rollback failure) inside the
NEW root-private transaction when available. Captures stay private locally. A kill
or disk failure may prevent final evidence; never infer no mutation from absent
output. No speculative cleanup, retry or fallback is performed.

## Independent rollback

Fresh live guards and exact new record/backup hashes required. Reject current
source/env/directory conflicts BEFORE rollback mutation. Restore old deployment
variables first, restore exact pipeline bytes/metadata, remove only verified new
module/rule/launcher. The directory's device/inode, owner and mode must match its
transaction record (including narrowly journalled partial creation states).

A pre-existing shared directory is NEVER removed. A transaction-created directory
is removed only with non-recursive rmdir when empty and metadata matches; otherwise
retain it and report RETAINED_NONEMPTY. Preserve unrelated files and legitimate
__pycache__ entries; no recursive deletion. Metadata/inode drift or unrecorded
creation blocks rollback before mutation. Repository owner UID1000 is the existing
trusted producer; deployment excludes active pipeline work and also requires the
owner not to mutate the repository concurrently. No root code executes from that
writable repository. Root-private retained tools and all old/new control evidence
are preserved. Restore health/preservation and mark only the new record ROLLED_BACK.
Existing publications are not changed or restored by rollback; expiry still applies.

## Bounds and commands (future authorization only)

Apply remote120s/local180s; rollback remote90s/local150s; TERM/KILL5s. One SSH attempt
per explicitly authorized action, no retries. Bounded private captures131072 bytes
per stream; no arbitrary action/path/transaction option. --local-check never connects.

    venv/bin/python -I -B deploy/staging/forecast-publication/automation-continuation/run.py apply --manifest-sha256 <NEW_APPROVED_MANIFEST_SHA256>

    venv/bin/python -I -B deploy/staging/forecast-publication/automation-continuation/run.py rollback --manifest-sha256 <SAME_NEW_APPROVED_MANIFEST_SHA256>

Do not invoke the old failed apply, overwrite the old transaction or delete retained
artifacts to satisfy a guard. A preflight timing block with changed=false does not
consume the new transaction; any later attempt still requires explicit authorization.

## Acceptance and limitations

After separately authorized apply, observe a natural flow and explicit receipt/
PUBLISHED result:31 ordered finite features,24 finite aligned UTC predictions,
frozen model/contract, all integrity/persistence gates and actual-time expiry.
Require API200/no-store, operations VALID and matching React values/provenance.
Observe a later strictly newer issue and natural503/no-store expiry; never relax
freshness or fabricate inputs. Report issue/completion/publication/cutoff times.

Local workflow tests model privileged metadata. Directory creation, inode journal,
permissions, empty/nonempty cleanup and namespace import exercise real native
filesystem calls under the local UID. This is not proof of Linux root/DAC/SELinux
behavior. Use disposable local Linux only if the engine is already available;
current Docker Unix socket is unavailable. No daemon start or image pull is needed.
Actual Linux ownership/imports and natural-run delivery remain live acceptance gates.
