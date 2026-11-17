# Read-only V3 acceptance overlay

Targets the APPLIED V2 transaction 565437b5103a45d3b6192ecd70498f78.
Preserves and verifies the complete V2 manifest/dependency closure before execution.
No deployment actions are exposed. Only the original read-only acceptance payload
is assembled, with a corrected natural-run selection boundary.

The prior failure is at acceptance.py line 60: strict timestamp(NULL). Prefect's
FlowRunFilterStartTime uses coalesce(start_time, expected_start_time), so a future
scheduled run with null start_time can pass after_. The original probe reproduces
TIMESTAMP for this valid unstarted record. Exact historical field contents were
not captured, so the specific remote value is not independently retained.

Request is_null_=False, and defensively ignore only SCHEDULED natural records with
null actual start. Null terminal starts and malformed/non-UTC actual timestamps
still fail closed. No clock-derived completion, invented timestamps or relaxed
contract validation. Task, receipt, publication, operational association and
forecast API checks are unchanged. No application files or V2 artifacts change.

One separately authorized invocation; pinned SSH; remote 90s/local 150s/grace 5s;
no retries. Private sanitized evidence under the existing private preflight root.
No secrets, AWS, inference, publication, service changes or filesystem writes on
EC2. Existing immutable readonly assembly and no-follow checks are retained.

Acceptance may report no postactivation natural run (WAITING/PARTIAL). API coverage
checks alone do not establish postactivation natural-run provenance or browser
rendering. Existing frontend elapsed-hour filtering requires owner-assisted real
browser acceptance. Analyst 403 acceptance remains pending.

Future command (substitute the generated manifest hash):
venv/bin/python -I -B deploy/staging/live-forecast-reliability-acceptance-v3/run.py --manifest-sha256 HASH
