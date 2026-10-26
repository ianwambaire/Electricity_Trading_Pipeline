# Phase 5D.2 — proposals, not execution authorization

`read-only-recovery-inventory.sh` is the first proposed host-inspection batch.
It has NOT run on EC2. The owner must approve this exact script and SHA-256.
It emits fixed-path existence/type/size/mode/UID/GID, allocated directory bytes
and filesystem capacity. Directory `du` traverses filesystem metadata but reads
no file bodies; its raw filenames/errors are never emitted. No SQL, key reads,
configuration/secret contents, account access, sudo, writes or service actions.

Missing/denied candidate paths are UNKNOWN, not proof a database/artifact is absent.
A database size does not establish a consistent backup or restoration readiness.
See frontend/docs/phase5d2-recovery-and-infrastructure-remediation.md.

`backup-operational-sqlite.sh` is a distinct, NOT approved production-write batch.
It creates exactly one new private local backup root, pins the reviewed recovery
helper hash, rejects existing destinations and sources >128MiB including WAL,
reserves25%filesystem space, and imports no dotenv/app configuration. It performs
no upload/restore/service action and does not prove off-host recoverability.
The reviewed helper scans operational database text for obvious credential-like
values and refuses them; this heuristic is not a guarantee of de-identification.
Real backups must be treated as confidential, never copied into the repository.

Both proposals use isolated standard-library Python (`-I -S -B`) to avoid
user-site initialization, Python environment path overrides and bytecode writes.
Recompute/review the SHA-256 if either script changes; previous approval would
not authorize a different payload. Final hashes are recorded in the Phase5D.2 report.


A2 preparation (not authorized/executed): `restore-operational-sqlite.py` is a
self-contained standard-library payload to send to the existing Python interpreter
through SSH stdin under `/usr/bin/timeout`. It pins the accepted A1 artifact and
creates one new private restore directory only. It never imports the A1 recovery
helper, reads live production databases, deletes artifacts or overwrites outputs.
Full integrity, separate FK/schema/count checks, source preservation, read-only
queries, sizes and timings are reported. See the final A2 execution review for
its SHA-256, exact SSH command,90s/120s+5s bounds and all approval prerequisites.
No source data or script needs uploading/installing; a missing timeout/runtime
is a stop condition, not permission to install or weaken bounds.
