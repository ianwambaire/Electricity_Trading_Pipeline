# Automatic acceptance v2 — narrow read-only Prefect adapter correction

LOCAL PREPARATION ONLY. No SSH, deployment, publisher, inference or remote change.
The approved v1 package and evidence remain unchanged. Supersedes (does not edit)
v1 manifest0da25e6276f0a2589fb61ed08820dabf7163323e5e2e3801f18cd1a7277ebf11.
All unchanged acceptance semantics/limits are in ../automatic-acceptance/REVIEW.md,
which is hash-bound, along with the complete original package source closure.

## Proven defect and exact delta

v1 Remote.flow/tasks called BASE.api. Its request guard accepts only deployment
metadata and /api/flow_runs/filter at port4200; GET flow detail and POST task filter
are rejected as unapproved_probe before transport. The generic RUN capture cannot
prove which exception happened first. Local regression reproduces both rejections.
This does not establish that inference/publication failed on EC2.

Only inspect.py's new prefect_request() and three Remote delegations change. No
change to BASE or shared helper allowlists. An AST equivalence regression verifies
all remaining inspector logic unchanged. Runner/build changes only versioning,
new source/test paths and immutable v1/source bindings; SSH/supervisor behavior stays.

## Closed protocol contract

Origin is hardcoded http://127.0.0.1:4200/api, identical to BASE: no authorization
headers, ambient proxies, TLS downgrade or changed remote authentication. HTTPS
staging forecast/Operations readback is untouched. There is no host/origin/command
CLI argument and no configurable endpoint origin. No external request during tests.

Exactly these operations are accepted:

| Method | Path | Exact body |
|---|---|---|
| POST | /flow_runs/filter | exact deployment UUID, COMPLETED state filter, EXPECTED_START_TIME_DESC, limit20 |
| GET | /flow_runs/<canonical UUID> | absent |
| POST | /task_runs/filter | task_runs.flow_run_id.any_ containing exactly one canonical flow UUID, integer limit100 |

Prefect filters are read-only POST operations, not GETs. No state-transition,
deployment PATCH, trigger, cancellation, task-detail or unrelated endpoint is
allowed. Queries, fragments, alternate/absolute origins, path escapes, suffixes,
noncanonical UUIDs, other verbs and extra/malformed filter fields fail BEFORE a
connection. Returned run/task/deployment IDs are canonical and association-checked;
duplicate IDs, malformed record shapes and missing state/name evidence fail closed.

HTTPConnection constructs only the fixed loopback address, Content-Type JSON,
3-second timeout and approved method/path/body. It never follows redirects; every
3xx is rejected without forwarding data or reading Location. Only200 JSON accepted.
Read maximum1,000,001 bytes; over1,000,000 fails, preserving the original bound.
Lists are bounded20 flows and strictly fewer than100 tasks (avoid silent truncation).
Duplicate JSON keys, nonfinite constants, invalid UTF-8/JSON and malformed responses
fail with closed PREFECT_<operation>_<cause> codes. Timeout/transport/protocol errors
never expose response contents, URLs, exception messages or credentials.

No retry or fallback to a broad HTTP client. The inspector still selects only
completed post-activation naturally scheduled :45 runs, resolves internal UUIDs
independently, checks persisted delivery, authentic31-feature receipt/history,
active bundle/pointer and both staging APIs at actual UTC. Missing evidence remains
unverified; expired historical publication stays distinct from current availability.
No time/freshness/model/feature/authorization/publication policy changes.

## Execution and binding

New versioned directory automatic-acceptance-v2; new MANIFEST.json/version2 binds
all new files plus the original immutable manifest/source closure and existing
validators, builder, read-only helpers and deployment manifest. Old bytes are checked
from retained blobs, not re-opened for execution. The complete assembled payload
has a separate SHA256. No production application import or publisher entrypoint.

One pinned SSH attempt, no retries, original strict host-key/identity restrictions.
Fixed remote command: sudo -n timeout --signal=TERM --kill-after=5s 90s system Python
-I -S -B stdin. Local bound150s, escalation5s; sanitized report32768bytes, captures
65536bytes each, local private evidence0700/0600 in the existing Git-ignored root.
No deployment transaction, remote files, service state or configuration is changed.
Ordinary SSH/sudo/HTTP access logging may occur on a future authorized inspection.

Future invocation after reviewing newly reported hashes, NOT executed here:

    venv/bin/python -I -B deploy/staging/forecast-publication/automatic-acceptance-v2/run.py --manifest-sha256 <NEW_APPROVED_MANIFEST_SHA256>

Append --local-check for local verification only. A NEW separate authorization is
required before remote execution; old authorization/hash cannot authorize this payload.

## Local regression and remaining limits

The 55 existing acceptance cases are reused against v2 via temporary pytest fixture
bindings, without copying/editing old tests. New transport tests run the ACTUAL
HTTPConnection/request/response parser on in-memory sockets: no live TCP listener,
SSH or external API. They inspect wire methods, address, headers, JSON filters,
redirect/host rejection, IDs, body/list bounds, malformed data and sanitized errors.
Full mocked acceptance traverses all three real Prefect adapter methods to a
matching PUBLISHED receipt/bundle/API result. Static AST comparison checks that
non-adapter acceptance semantics are unchanged; original allowlists still reject
unsupported endpoints. Dependency drift and no-retry tests remain mandatory.

Python3.9 grammar/compile and local dependency/manifest checks are performed using
the available Python3.14 runtime. Real EC2/system-Python3.9 response/runtime behavior
remains unverified. Exact publication time is not persisted: task interval bounds
remain explicit. Public APIs omit receipt/bundle IDs: all24 values and timestamps
plus stable pointer remain the readback association. Browser React acceptance is
always PENDING_BROWSER; do not claim live publication from local fixture successes.

Validation:265 selected tests passed, including108 v2 cases (55 inherited acceptance
cases and53 new adapter/transport regressions). Installed local Prefect3.7.2 route
source confirms GET /flow_runs/{id:uuid}, POST /flow_runs/filter and POST
/task_runs/filter with the reviewed body parameter names. This is local source
evidence, not a remote availability claim. Python3.9 grammar/compile checks cover
17 manifest-bound Python files, the two extracted helper blocks and assembled
payload; the available executing interpreter is Python3.14. Original v1 closure,
new dependency/hash closure and whitespace checks pass without Git operations.
