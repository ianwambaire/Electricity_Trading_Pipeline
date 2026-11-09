# Parent traversal diagnostic V2 — tooling-only continuation

Local preparation only. No remote execution authorized by this document.
Release: phase-realized-parent-traversal-diagnostic-20261108-v2.
Parent V1 manifest:41ebe0af3a0f9533af40e618c77be0238caa4d194366178ac1c7fd613a8ed4d6.
Reporting release V1 and all prior diagnostics/evidence remain unchanged.

## Evidence and supported findings

Retained V1 assessment contains only remote exit0, DIAGNOSTIC_OUTPUT_UNVERIFIED,
report:null and one SSH attempt; no report bytes or failed validation rule remain.
Therefore the exact historical parse/schema/exit mismatch cannot be recovered.
Forty legal success-report serialization variants round-trip through V1 locally.
Do not claim the historical failure was permission denial, group membership,
Python startup or any particular malformed field based on this evidence.

Two confirmed tooling defects are corrected:

1. V1 child_result can emit six fixed supervisor/startup outcomes not in
   CHILD_CODES, but its report validator requires producer_probe in CHILD_CODES.
   Consequently valid timeout, output-limit, interpreter-execution, privilege-drop,
   Python-startup and unexpected-output observations are rejected generically.
   These outcomes require BLOCKED, never PASS. This defect does not explain the
   historical remote exit0; the missing response prevents that attribution.
2. The blanket parse/schema/exit exception handler discards the exact failed
   validation stage. V2 retains only fixed stages/codes/approved field identifiers,
   byte counts and fully sanitized candidate observations on exit mismatch.

## Strict wire contract

The unchanged coordinator report is wrapped in exactly one JSON object with
protocol_version:2, diagnostic_id:<source-bound SHA-256>, report:<same report>.
The identifier binds the exact V1 payload plus the new protocol implementation;
manifest binds the full new payload, runner, builder and transitive V1 closure.
SSH host-key/public-key verification authenticates transport; this identifier
identifies reviewed code and is not an independent signature or historical proof.
No banners, extra objects, unknown keys, duplicate JSON keys, non-finite values,
invalid UTF-8, oversized or missing output are accepted. Exit status must agree.
The schema is tightened with status/result/stage/identity/mode consistency checks.
Actual X_OK remains authoritative; mode-bit predictions do not override ACL-granted
access. The supervisor/startup enum is expanded ONLY to the exact values emitted
by the reviewed V1 coordinator, and can never grant a successful traversal result.

Only field identifiers from the approved schema, fixed validation codes, sanitized
metadata, flags and byte counts may be retained. Raw responses/errors, unapproved
field names/values, transport banners, credentials, paths and stack traces are
never stored. A structurally validated candidate with an inconsistent exit is
private and explicitly UNACCEPTED; CLI report remains null and execution fails.

## Unchanged remote action and security boundaries

Every V1 coordinator/probe function and subprocess whitelist remains byte-for-byte
or AST-identical; only final serialization is wrapped. One metadata query plus
one UID/GID1000 saved-ID probe, no supplementary groups, NNP1, no capabilities.
No root traversal fallback, alternate group, permission/ACL change, application
import, deployment, service action, Prefect run, publication, AWS or source call.
Same pinned destination/identity/host key; same no-agent/no-proxy/public-key-only
SSH and process-group bounds:20s remote,40s local,5s escalation,8192-byte streams,
one attempt/no retries. Preparation/tests execute no SSH or privileged operations.
Private sanitized evidence remains directory0700/file0600 under the existing
ignored staging-preflight evidence root. No original artifacts or hashes refresh.

Future separately authorized command:
`venv/bin/python -I -B deploy/staging/realized-parent-traversal-diagnostic-v2/run.py --manifest-sha256 <reviewed-manifest>`

Another read-only inspection is needed to obtain authenticated current host
observations; no application/permission correction is justified yet. PASS proves
current producer traversal only. It cannot reconstruct the lost V1 response.
