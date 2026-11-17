# Pipeline/window-only diagnostic — LOCAL preparation, not remote authorization

The consumed apply approval does not authorize this new payload. No reviewed runner
previously exposed this exact scope and exact guard evaluation time/subconditions.
This additive package leaves the deployment package, original preflight/release/tools
manifests, A03 and unrelated diagnostic directories unchanged.

## Exact scope

Load retained, verified preflight helper definitions under a non-main name; invoke
ONLY the unchanged pipeline() guard. Observe its existing API responses and its
actual datetime.now evaluation (return the original clock value unchanged). Restore
local namespace instrumentation even on failure. No alternative freshness/window
calculation is used to grant PASS: observed conditions must match the guard result.

Existing reads only: known deployment GET, active-flow filter POST, scheduled-flow
filter POST, bounded /proc mount/argv marker scan. No Prefect state transition,
schedule/concurrency update, pipeline trigger, cancellation, pause, ingestion,
inference, SQL, service action, publication, installation or full preflight. No
application imports or candidate interpreter. Only trusted system Python stdlib.

Approved baseline: one enabled45 * * * * UTC schedule, known deployment unpaused,
concurrency1/active and original null collision options. No RUNNING/PENDING/
CANCELLING/PAUSED flow, no detected ingestion/engine process, active_slots==0,
and STRICTLY MORE THAN600 seconds to BOTH the next nominal hourly :45 and every
returned scheduled run. Exactly600 seconds FAILS. No threshold is relaxed.

Report actual evaluation UTC, local clock UTC offset, next nominal :45, nearest
returned queued timestamp, available window in integer microseconds, original guard
facts, active-state counts and individually failed conditions. No run identifiers,
parameters, process argv, environment values, private connection paths or logs print.
Machine timezone offset does not prove clock synchronization/NTP correctness.

Service-unit configuration baseline remains UNVERIFIED: this focused guard checks
Prefect deployment/schedule/concurrency, not full worker/server unit configuration.
The past apply cause remains UNVERIFIED because the old job did not persist its
subcondition facts. A current failure may differ from that historical failure.
A successful diagnostic does not reserve resources or a deployment window.
If schedule matches, ordinary eligible intervals can exist after each :45 run ends
and before :35 (strict >10min), subject to all queued/run/process/slot gates. No
specific future opportunity is promised without observed completion and fresh gates.

## Proposed future invocation — do NOT execute until separately authorized

```sh
venv/bin/python -I -B deploy/staging/pipeline-window-diagnostic/run.py \
  --manifest-sha256 APPROVED_PIPELINE_DIAGNOSTIC_MANIFEST_SHA256
```

Append --local-check for local hashes/bindings only, zero remote attempts. Manifest
binds runner/job/review/tests plus both retained preflight/SSH helper sources and
assembled stdin payload. Keep the owner's approved manifest and payload hashes
independent of files. No arbitrary host/command/input/capture path option exists.

The existing private connection profile and target/known-host hashes are reused
from verified wrapper bytes: strict host-key verification, BatchMode, no agent,
-F/dev/null, ConnectTimeout10, ConnectionAttempts1. Fixed remote command:

sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 120s /usr/bin/python3 -I -S -B -

One SSH attempt, no retries. Local180s with5s escalation, each stream capped131072
bytes during production. Private0600 captures inside ignored0700 pipeline-window-*
local directory; no remote files written. Raw stderr/exception text are not printed.
Exit0 means the exact guard currently passes; exit1 can be a completed blocked or
unverified observation. Transport errors stop; no repair or apply retry follows.

## Next authorization boundary

Manually commit this package, then authorize its exact runner/manifest/assembled
payload hashes. If the gate proves transient, the existing committed deployment
package may be used unchanged only under a NEW deployment authorization and fresh
apply guards. Persistent drift requires a separately scoped correction; never
change the threshold or configuration merely to make this diagnostic pass.
