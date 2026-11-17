# Helper-only operational capture correction — local preparation

Release: phase-operational-capture-helper-20261107-v2
Transaction: 13ee1fecc7214ba789feb78af43f28b4
No remote execution, installation, activation or rollback is authorized by this
package. Every action requires separate owner authorization. No automatic retries.

## Scope and source

Bind operational-capture-correction-v1 manifest
435a85e89aaba277097d022ba640bc8195bd861121f0a58219669daff6d24298.
Retain original operational-evidence-release-v5 and its full source closure.
Install eight files into new root-owned 0700 /opt/powerflow/operational-evidence-v2:
the corrected producer, bootstrap adjusted only to the new immutable root, the
five byte-identical runtime modules, and the new seven-entry TOOLS.json.

Only two existing files change: the operational launcher (0755 root:root) and its
sudoers rule (0440 root:root). The rule changes only the executable SHA-256 digest;
its executable path, NOSETENV restriction and exact UUID arguments are unchanged.
New helper files are root:root 0600, directories root:root 0700. No writable code
or alternate dependency lookup enters the elevated path. No root shell arguments.
Do not overwrite v1 code or modify its TOOLS.json. The unchanged forecast validator
is part of the helper's closed runtime, not a forecasting deployment.

No React/API/Nginx rebuild, reinstall, pointer switch, reload or service restart.
No worker/source changes, Prefect PATCH, schedule/concurrency/environment changes,
manual inference, publication, auth changes or operational-store writes.

## Fresh read-only preflight

Verify exact manifest, all artifacts/payloads, correction candidate and V5 bindings
locally, then pinned SSH identity/host key. The preflight payload does not include
the transaction implementation. All artifact data is verified before its memory
import probe; no main/capture/publisher is invoked. Python >=3.9 system runtime,
Linux x86_64, root/procfs/O_NOATIME, identities and immutable dependency metadata
must pass. No dependency installation or worker SDK import as root.

Require V5 APPLIED journal, active V5 API/static hashes and pointers, exact Nginx
and API environment hashes, worker source and Prefect3.7.5 hashes, work-pool env
semantics, original helper/privilege hashes, both enabled feature flags, unchanged
deployment schedule/concurrency, no queued overrides, pipeline/helper idleness,
strictly >600seconds before the next run, and existing RAM/disk guards.
Verify candidate sandbox, public/Admin routing, production health and existing
forecast tools/model contracts. Snapshot operational/forecast publications without
changing them. Accept valid existing/stale publications; never require an empty
store or substitute historical execution evidence as current. Unexpected partial
store contents fail closed. Require new helper/control destinations absent.

## Guarded apply (not authorized)

Repeat fresh preflight twice and compare stable preservation facts before writes.
Create a private root:root0700 transaction journal. Independently save each old
privilege file twice (0600, distinct inodes, exact hashes); verify all backups
before installation. Install only the new immutable helper closure; record its
created inode identity. Verify its exact inventory/permissions/hashes and execute
only isolated bootstrap.load() import checks (never main/capture/publisher).

Recheck idle window, preservation, backups and candidate sudoers syntax. Install
the new hash-bound sudo rule, run visudo -c, then replace the launcher LAST as the
activation step. The short intermediate digest mismatch denies execution; it does
not grant broader privilege. Idle-window guards prevent active hook overlap.
Feature flags remain enabled throughout; only the launcher selects the new code.
Verify activated hashes, import closure, role routing, health, unchanged policy,
production/forecast/store fingerprints and APPLIED journal. Do not manufacture an
operational publication or trigger Prefect. Failure stops in place with bounded
sanitized phase/function/exception evidence; no automatic rollback or repair.
Limits:90s remote/150s local preflight;120s remote/180s local apply/rollback;5s grace.

## Independent rollback (separate authorization)

Before writes: validate exact transaction/config identity, both backup copies,
new-root creation identity, all present immutable files, current privilege hashes
(old/new only), fresh idle window and preservation guards. Unexpected drift stops.
Restore old launcher first, old hash rule last; verify visudo and health. No store
or forecast pointer is reverted, and valid publications produced since apply are
preserved. Retain the inert v2 tree and transaction evidence. Old helper remains
configured/enabled but retains its known timestamp limitation. No other config or
service changes. A failure during initial backup may leave only an inert private
transaction directory; no existing executable is changed before verified backups.

## Acceptance and runtime limits

After authorized deployment, require a later genuine natural run and matching
committed operational record/public endpoints, authenticated Admin/Analyst checks
and React provenance/freshness consistency. PUBLISHED forecasts remain independent
from operational validity. Schema, issue matching, receipt/model/31-feature hashes,
bundle hashes, freshness, monotonic lock and atomic publication are unchanged.
Offline Linux-path fixtures cannot establish actual sudo policy, procfs, filesystem
atomicity/fsync durability or deployed system Python compatibility. The read-only
Linux preflight and guarded apply gates remain mandatory; no live success claimed.

## Manual review and commit

These commands select only this release and its release tests. The referenced
correction candidate/diagnostics must already be reviewed and committed separately.
Never stage private data/backups evidence. The builder refuses to refresh any
existing output whose bytes differ; changed reviewed inputs require a new release.

```sh
git diff -- deploy/staging/operational-capture-helper-release-v2 tests/test_operational_capture_helper_release_v2.py
git add -- deploy/staging/operational-capture-helper-release-v2 tests/test_operational_capture_helper_release_v2.py
git diff --cached --check
git diff --cached -- deploy/staging/operational-capture-helper-release-v2 tests/test_operational_capture_helper_release_v2.py
git commit --only -m "Prepare guarded operational capture helper release" -- deploy/staging/operational-capture-helper-release-v2 tests/test_operational_capture_helper_release_v2.py
git push
```

## Reporting-only replacement of prepared helper release v1

The old exception dispatcher used OP.InvalidEvidence outside the HELPER namespace,
where OP was never bound. Use HELPER.OP.InvalidEvidence in the same type check.
No guard, allowed reason, validation, helper byte, privilege binding or transaction
implementation changes. Only release/transaction identity and the test binding
change alongside this fix. V1 and V5 manifests, payloads and sources stay intact.

Regression tests execute the complete assembled preflight dispatch and the real
preflight_report -> fresh -> common -> idle -> V5 idle_capacity guard chain with
mocked Linux identity and pipeline metadata. Both an unsafe scheduling window and
an active pipeline retain PIPELINE_OR_WINDOW_GATE. The existing guard deliberately
uses the same identifier for these two conditions; the replacement does not invent
a different diagnosis or relax the >600-second/idleness requirements. Additional
full-dispatch cases cover the contract exception namespace and unknown-message
redaction. No browser, network, SSH or live filesystem changes occur in these tests.
