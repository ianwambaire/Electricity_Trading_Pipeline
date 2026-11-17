# Reporting parent traversal — read-only diagnostic candidate

**LOCAL PREPARATION ONLY. A separate authorization is required for execution.**
Release: `phase-realized-parent-traversal-diagnostic-20261108-v1`.
The original Realized Performance V1 release and its manifest/payloads/evidence
remain unchanged. This does not correct, bypass or weaken REPORT_PARENT_TRAVERSAL.

## Exact existing prerequisite and local evidence

V1 `guards.py:parent_access` starts `/usr/bin/setpriv --no-new-privs --reuid=1000
--regid=1000 --clear-groups /usr/bin/python3 -I -S -B -c <fixed-script>` and requires
UID/EUID1000 plus `os.access('/srv/powerflow', os.X_OK)`, exit0, no timeout/output
failure and exact `PARENT_ACCESS_PASS` stdout. The parent is not the new report
store; it is the existing `/srv/powerflow` ancestor. Five-second timeout,1024-byte
output limit, five-second escalation. Every startup, identity, permission, timeout
or unexpected-output failure is collapsed into the one reported gate.

V1 already verifies the named producer account's UID/GID1000 and the Prefect worker
unit's configured User/Group. These passing prerequisites reduce, but do not
eliminate, an identity/setup explanation. It does not retain the child's actual
failure or compare the worker's runtime supplementary groups with --clear-groups.

The current local install-package/install.py source specifies root:powerflow-api
0750 for this parent. However, that source does NOT match the retained R2 bundle's
install.py hash. It is an unverified historical clue, not an approved host baseline.
No historical artifact or expected hash is changed or accepted. A restrictive
root:API-reader0750 layout would explain this denial for the cleared producer;
current host metadata, ACLs and the original child failure remain unverified.
A worker with group992 could have a different access context; this diagnostic
never adds that group or treats privileged access as a successful producer check.

## Minimum remote scope

- Linux/std-Python root coordinator for metadata observation and permanent child
  privilege drop only. Root access is NEVER evidence of producer traversal.
- One fixed read-only `systemctl show powerflow-prefect-worker.service` request
  for User,Group,MainPID. Read only that process's kernel Uid/Gid/Groups metadata;
  no environ, command line, logs, application config, tokens or credentials.
- Metadata only for `/`, `/srv`, `/srv/powerflow`, anchored/no-follow directory
  descriptors. No directory enumeration, contents, report/receipt/data reads,
  ACL changes, permission changes, writable opens or application imports.
- One permanently unprivileged UID/GID1000 child, saved IDs1000, no supplementary
  groups, NoNewPrivs1 and zero effective/permitted/ambient capabilities. Read only
  its own kernel identity/security metadata, then test exactly X_OK along the same
  fixed path. No alternate identity, added group or root fallback is permitted.
- Verify OS tool metadata. Interpret mode bits separately from observed access;
  don't claim an ACL/SELinux cause without evidence. Metadata must remain stable.

Only approved path identifiers, ROOT/PRODUCER/API_READER/OTHER ownership classes,
permission modes, safe booleans, fixed reasons/stages and recognized errno codes
are reportable. Raw paths, PIDs, usernames, group lists, inode identifiers,
exceptions, stdout/stderr and unrelated filesystem information are discarded.

Specific results distinguish privilege-drop/interpreter/Python startup failure,
timeout/output limit, malformed probe output, identity mismatch, unsafe/symlink
paths, basic mode denial, group-context difference and access denied despite
apparently sufficient mode bits. PASS means current cleared-producer traversal
works, not that the historical failure has been explained or release approved.

## Transport and bounds

Reuse the independently verified connectivity package's pinned profile and
bounded supervisor. Original reporting manifest:
`a3dceba7641ceaa9030709b1b7d4ce59460b54f5123b7e89f15d95bba39b0a83`.
Connectivity manifest:
`89c54b9b34a25dde2325659bebc0d7b5c29e2c5b5f472ef07bdd15a6c56a48e3`.
No private key content is read by Python. Strict host key, public-key-only,
noninteractive, no-agent/no-proxy/no-forwarding SSH, one connection only.
Fixed remote command: `sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 20s
/usr/bin/python3 -I -S -B -`. Local deadline40s, escalation5s, output8192bytes.
The command supervisor permits exactly one service metadata query and one fixed
producer child; no other subprocess, retries, polling, preflight or deployment.

Only sanitized assessment.json is retained under the existing private ignored
preflight root, directory0700/file0600. No raw transport/probe output is retained.
The payload imports no PowerFlow, SDK or source-access code and cannot execute
apply, rollback, publication, forecasting or scheduling operations. No AWS/SSH
runs occur during local tests/build/verification.

## Future execution — NOT authorized or executed yet

`venv/bin/python -I -B deploy/staging/realized-parent-traversal-diagnostic-v1/run.py --manifest-sha256 <reviewed-manifest>`

Preserve the V1 prerequisite. After the bounded inspection, choose a correction
only from actual evidence and obtain any needed separate authorization. No access
change or reporting architecture change is part of this diagnostic.
