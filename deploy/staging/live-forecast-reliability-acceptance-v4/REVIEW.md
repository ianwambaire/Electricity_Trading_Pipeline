# Live Forecast Reliability acceptance V4 — local preparation only

Targets APPLIED deployment transaction 565437b5103a45d3b6192ecd70498f78.
Binds and verifies unchanged V3 acceptance and the independently executed
component inspection manifest 8cba57746328cd4dcc5434dc29a19f9468d884560aa793d3f7caf9cae03b0339.
No deployed/application files or previous immutable packages change.

Exact immutable API/static trees, pointers, runtime/sandbox, helper, deployment
policy/schedule/concurrency, environment and Nginx remain protected. Production's
opaque fingerprint is replayed with ONLY the two independently reconstructed
historical pipeline-output hashes, reusing the inspected verifier. All actual
reads still run. Every other file/service/certificate/parser hash must match the
original baseline. No observed host hashes are accepted as new expected values.

Forecast namespace ownership/modes remain equal; original baseline bundle and
receipt must remain intact. Only publication pointer/bundle identity may advance.
Original operational inventory must cryptographically reconstruct as a retained
subset; all current evidence files still pass existing hash/permission/contract
validation. Missing, corrupt, unknown or inconsistent state fails closed.

Public forecast/Operations API checks, original UTC/natural origin validation and
receipt capture remain strict. Explicitly bind the active pointer hash, receipt,
issue and execution to the matching natural-run evidence. If the latest run is
withheld/duplicate, an earlier CURRENT publication can remain live only after its
persisted PUBLISHED operational evidence and exact natural Prefect execution are
independently recaptured and verified. Never select another forecast pointer or
fall back to historical forecast data when current is missing, invalid or expired.
Latest-run outcome remains distinct; such a case reports backend PARTIAL.

One bounded descending page of <=20 started runs; reject invalid order, duplicate
identities, ambiguous selection or a full page with no natural run. No pagination,
polling or retries. Latest nonterminal run yields WAITING/PARTIAL. Fresh/stale
operational evidence is reported honestly. API returns all24 immutable forecast
rows; report future and elapsed counts separately (strict target_time > UTC now),
expiry at issue+24h and delayed refresh at issue+3h. Actual browser exclusion of
elapsed actionable rows still requires owner-assisted acceptance.

Initial and final exact snapshots detect concurrent publication/config changes.
Pipeline idleness, existing scheduling (>600s), capacity and bounds remain active.
One separately authorized pinned SSH attempt; remote90s/local150s/grace5s.
Sanitized assessment only; no raw responses, secrets, credentials or logs retained.
No mutation entrypoints are assembled. No secret lookup, manual runs, publisher,
installation, rollback, service changes or authentication operations.

Overall PARTIAL remains until owner browser and authenticated Analyst403 checks.
backend_status PASS requires latest COMPLETED/PUBLISHED with current matching
publication and VALID operational evidence. No exact publication time is invented.
