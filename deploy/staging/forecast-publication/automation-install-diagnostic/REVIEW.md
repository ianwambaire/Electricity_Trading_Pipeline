# One read-only automation installation-state diagnostic

Local implementation only; new explicit hash-bound authorization is required before
SSH. This is a separate diagnostic beside the original deployment, not an added
operation in the old runner. No original deployment source, manifest, payload,
apply/rollback operation, transaction record or retained tool is changed.

Original manifest48a17404aa82c2fc16ab961311a7007224e1ee7016ecbc6ca5de04bed8aed389
and transaction73080d9ca8fd4c3f9f143fd4ae84a123 are fixed in the new runner. Verify
all original artifact sizes/hashes before using the retained local supervisor and
pinned SSH wrapper. Original deployment code is parsed as AST DATA ONLY to extract
and check the exact original PRODUCTION and TOOLS literals; never compiled/imported
or sent to the host. The new diagnostic manifest binds its entire new source/test/
review closure; the original manifest transitively binds supervisor/wrapper code.

## Fixed permitted remote scope

- lstat-equivalent metadata for the production repository src and src/shared.
- Expected pipeline UID/GID1000 primary-group POSIX read/traverse calculation using
  directory metadata only. Effective process/ACL/supplementary-group/mount-context
  access remains explicitly UNVERIFIED. No identity switching or subprocess.
- Only /opt/powerflow/forecast-publication-automation, its shared directory and its
  six allowlisted code/manifest files. Five source hashes come directly from the
  original manifest. automation-manifest.json hash is derived from the exact JSON
  serialization used by the original installer, not guessed from a new archive.
- Ancestor metadata is read only to anchor traversal; no unrelated file contents.

The path is bound to the original transaction's approved job and manifest. There
is no arbitrary path/command/host option. This is not proof that every retained
file was historically created by that attempt. Remote backup record contents are
NOT read: they can contain private deployment variables. The diagnostic never
reads secrets, application data, databases, model binaries or process environments.

Every ancestor is opened with O_DIRECTORY/O_NOFOLLOW; inode checks bind directory
opens. Directory entries are inspected without following links. Unexpected names,
symlinks, special files, excessive inventory and changed file metadata stop safely.
No traversal into unexpected directories. Arbitrary filenames are not echoed.
Only approved regular code files are hashed, each <=200000 bytes; unsafe ownership,
mode or hard links suppress hashing and report UNVERIFIED metadata evidence.
Linux O_NOATIME is used for read descriptors; local macOS fixtures omit the absent
flag. No filesystem-write syscall is reachable. No subprocess/network/application
imports exist in the REMOTE payload. It imports trusted OS Python stdlib only.

Maximum24 inventory entries; six expected files; JSON output capped16384 bytes.
All output keys, enums, metadata types, names and hashes are validated locally from
retained code/data before exposure. Raw stderr stays private. Unknown failures use
sanitized cause codes, never exception text, user names, private paths or tokens.

## Findings and historical limits

OBSERVED means bounded observation completed, NOT deployment readiness. Missing
root/approved files report MISSING or INCOMPLETE. Hash/metadata mismatch reports
FINDINGS with exit1. Unsafe traversal, access errors or bounds report UNVERIFIED /
exit1. Missing src/shared is CONSISTENT_WITH_REPRODUCED_MISSING_PARENT; existence
now does not prove historical existence or exclude another failure. A missing
path now is not claimed as the historical first failing operation. The rollback
retained tools, removed selected components and restored source; no inference is
made about removed artifacts. No deployment retry or correction follows results.

## Future invocation — not executed

    venv/bin/python -I -B deploy/staging/forecast-publication/automation-install-diagnostic/run.py inspect-install-state --manifest-sha256 <NEW_REVIEWED_DIAGNOSTIC_MANIFEST_SHA256>

Append --local-check to verify all bindings and the pinned profile without network.
One SSH invocation, strict pinned target/host key/identity, noninteractive sudo for
this fixed inspection, no forwarding/agent/session reuse, ConnectTimeout10 seconds,
ConnectionAttempts1. Remote timeout30s, supervisor90s, TERM/KILL5s, captures32768
bytes per stream. Payload consists of held hash-verified bytes; no executable
reopen after validation. Only the inspection and data config are transmitted;
no installer, publisher, model, supervisor or rollback code reaches remote Python.

Reports and raw diagnostics go only to a new0700 directory under the existing
Git-ignored private staging evidence root; files0600. No retry, repair, setup,
publication, service command, Prefect/AWS/Cognito operation or rollback is reachable.
The shell command is only the fixed SSH sudo/timeout/system-Python launcher; no
remote shell interpreter receives caller-supplied arguments or config paths.

Local tests cover fixed bindings, no-follow metadata, missing/symlinked paths,
traversal rejection, complete/incomplete inventory, hashes, mode/ownership/hard-link
failures, bounds, sanitization, one-attempt error handling and held payload bytes.
Root ownership is simulated in local non-root fixtures; Linux effective access and
actual production state remain unverified until separately authorized execution.
