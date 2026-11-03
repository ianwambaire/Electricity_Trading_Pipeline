# Exact 2026-11-03 16:45 run withholding diagnostic — local preparation only

Target only flow01a1a1e9-4922-757b-a031-6de577b518d5 and scheduled16:45UTC.
No remote execution is authorized by this package. No receipt absence is treated
as root cause. Deployed delivery returns SKIPPED_WITHHELD before invoking sudo or
publisher when forecast status WITHHELD/generated false. The technical reason is
operational_incidents.details_json for component next24h forecast/event
forecast_withheld, keyed by INTERNAL pipeline UUID. pipeline_runs.message records
that UUID, generic forecast status/time/latest-hours and next24h_publication_status.

Reuse the immutable automatic-acceptance-v2 Prefect adapter and SQLite guard.
Extract only imports, Stop and eight read-only helper functions from its pinned
inspect.py. Two AST substitutions, each required exactly once: add only
operational_incidents to the SQLite READ allowlist, and replace the existing return
projection with detail() while still inside its protected connection/snapshot.
No other reader behavior changes. Do not execute the original inspector main,
publisher, receipt scanner, application modules, model or deployment code.

Fixed GET flow UUID and POST task filter only, canonical identifiers, deployment
and natural-scheduled/completed/time binding. Unique forecast task -> stage timing
within existing2second tolerance -> internal UUID -> one successful pipeline record
-> one associated withheld incident. Validate WITHHELD/false/SKIPPED_WITHHELD,
incident/summary withholding timestamp and latest-hour agreement. Missing/ambiguous
or changed evidence fails closed. Later gates cannot be inferred to have passed.

Only three SQLite tables. Existing no-follow descriptor chain, mode=ro&immutable=1,
query_only, SELECT/function authorizer, progress budget, bounded records/messages,
active WAL/journal/SHM rejection and before/after inode/mtime/ctime checks retained.
New incident SELECT is bounded13 rows/262145characters with strict byte checks.
No database initialization, journal creation, backup, application import or write.
No source CSVs, receipt files, weather queries, logs, API dashboard probes or raw
feature vectors are read. Only fixed flow/task metadata and the associated database
records are requested; unrelated bounded candidate records are not emitted.

Output: PASS means the persisted specific reason/gate was established, NOT a
successful forecast. PARTIAL distinguishes missing/unrecognized/malformed evidence;
BLOCKED covers incomplete run. Known exact model error strings are allowlisted.
Dynamic exception details are redacted; unknown reason returns only SHA256 and
UNVERIFIED. Freshness messages parse only price/load, a valid UTC timestamp and
recorded numeric threshold. No expiry or threshold changes. Unknown reasons require
separate evidence review, not heuristic keyword guessing. Missing receipt is
EXPECTED for this confirmed pre-inference WITHHELD path, not independently scanned.

Manifest binds new source, runner/build/review/tests, current model reason source,
and complete original v2/v1/activation source closures. Original manifests/evidence
are never regenerated. Verified bytes are retained for AST extraction/compilation
and transmission. Same existing pinned SSH profile/host key, no arbitrary host,
flow, SQL or command CLI options. One SSH attempt, no retries. Fixed root trusted
system Python -I -S -B,90seconds remote/150seconds local, TERM/KILL5seconds.
Local captures only: existing ignored root,0700 directory/0600 files,65536bytes per
stream; sanitized report16384characters. Ordinary access logging may occur remotely.

Future command, NOT executed during preparation:

    venv/bin/python -I -B deploy/staging/forecast-publication/withholding-diagnostic/run.py --manifest-sha256 <NEW_REVIEWED_MANIFEST_SHA256>

--local-check verifies locally without SSH. A fresh explicit one-attempt authorization
is required. Exact production reason is UNKNOWN until that inspection succeeds.
Tests use synthetic records and existing isolated SQLite fixtures; no external
network. Python3.9 grammar/host compilation is checked, not actual EC2 runtime.

Local validation:206 selected tests passed, including25 focused diagnostic cases,
the v2 HTTP adapter regression suite, automatic delivery and incremental-pipeline
tests. Seven isolated SQLite cases exercise the extracted real snapshot/association
guard; Linux /proc/self/fd is mapped to a temporary read-only fixture URI on macOS,
and privileged UID metadata is simulated. The incident projection is tested with
bounded synthetic cursor rows; real Linux/EC2 execution remains unverified.
