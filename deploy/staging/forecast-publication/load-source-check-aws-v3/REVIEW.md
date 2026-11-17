# V3 passive SDK verification — local preparation and authorization review

This is a separate SDK-verification-only companion. It does NOT continue to AWS
credentials or ENTSO-E even on PASS. V2 remains unchanged for any later separately
authorized source inspection. No remote action is executed during preparation.

## V2 failure information that was lost

The retained V2 result established SDK_VERIFICATION / SDK_DEPENDENCY_MISMATCH,
before backend selection, IMDSv2, secret access or ENTSO-E access. It did not retain
the current dependency key, substage or verified-file count. The historical failing
file cannot be recovered from that report. A local reproduction does not establish
the production cause.

V2's parent verification sequence is:

1. Check the trusted Python 3.14 binary's hash and metadata.
2. Anchor the fixed production site-packages directory with no-follow descriptors.
3. Inventory all code in the seven SDK namespaces. Reject symlinks, native files,
   unsafe directory owner/mode/access, excessive inventories and code-set mismatch.
4. Capture each of 215 lock entries using the shared capture helper, requiring a
   regular stable file, owner 0/1000, no group/world write, UID/GID-1000 readability,
   no-follow ancestry and read bounds.
5. Compare exact size/SHA-256, keeping the aggregate at or below 6 MB.

Inventory checks explicitly raising SDK_INVENTORY_MISMATCH are preserved by V2's
wrapper. Everything else below can collapse into SDK_DEPENDENCY_MISMATCH:

- Aggregate size >6 MB, a size mismatch OR a hash mismatch share one `need`.
- The capture helper's READ_METADATA combines type, owner, writable mode and
  pipeline readability. READ_BOUND and READ_DRIFT are also captured generically.
- Missing files/directories, denied opens, unsupported NOATIME, directory/symlink
  errors and other unexpected filesystem exceptions fall through `sdk_files()`'s
  catch-all wrapper, which drops the original operation and dependency identity.
- Subsequent V2 stages also use the same code for an oversized child envelope,
  child-envelope schema/inventory/hash mismatches and a Boto3 version check. Those
  are later than the observed parent failure and are not evidence of its cause.

V3 targets the parent SDK gate only. It cannot run those later stages and does not
silently reinterpret the historical failure as a version mismatch.

## New bounded sanitized detail

Each report includes runtime_verified, status, aws_attempted=false,
source_attempted=false, and sdk_verification with exactly:

- dependency_id: a lock-relative approved filename/directory, a fixed
  SDK_PACKAGE:<approved-root> identifier, SDK_SITE, SDK_INVENTORY or PYTHON_RUNTIME.
- category: FILE_MISSING, FILE_TYPE_MISMATCH, PERMISSION_MISMATCH, OWNER_MISMATCH,
  HASH_MISMATCH, SYMLINK_OR_PATH_VIOLATION, SDK_VERSION_OR_LAYOUT_MISMATCH or
  OTHER_VERIFICATION_FAILURE.
- stage: fixed enumeration identifying runtime, site anchoring, code inventory,
  file parent/metadata/open/read/stability/integrity or completion.
- verified_files: count incremented only after a complete accepted file hash;
  range 0..215. Inventory failures occur before file hashes and report zero.

Unknown inventory entry names never enter output. For unapproved extras, the
identifier is masked to its approved package root or SDK_INVENTORY. Exception
strings/filenames, actual versions, ownership values, modes, file contents and
observed hashes are not emitted. A changed METADATA Version field is recognized
only for classification; its observed value is never reported or accepted.

The verifier stops at the first failure, with stable code-root order, sorted
directory entries and sorted locked-file hash order. Multiple defects do not cause
it to skip a missing entry, continue to credential lookup or read arbitrary paths.
The reported first failure is the first failed verification check, not proof of
the historical first exception or upstream cause.

## Acceptance and security rules

The SDK lock is referenced directly from immutable V2, SHA-256
`da19f5a81c7741d19333e7bfcc25004c50fe2c83e31642c9f39c828518de35c4`.
No SDK lock generator is executed and no installed hash is adopted. All 215 files
must retain their exact size/hash. Empty approved Python files remain valid.
Per-file read bound remains 2 MB; aggregate remains 6 MB. Wrong type/owner/modes,
missing readability, unexpected code/native extensions, symlinks and drift still
fail closed. Python caches remain ignored because no bytecode is loaded.

Root runtime verification reuses V2's exact `_root_runtime` body and constants,
including `/usr/bin/python3.14` and its previously bound binary hash. It checks
that execution path passively; V3 never starts Python 3.14 or imports SDK code.
The original selected no-follow capture helper is used only for that OS binary.
V3's SDK captures retain all V2 checks and add pre-open metadata/stability checks
to identify type/path substitution without following targets. Source and metadata
bytes remain in memory only and are discarded after verification.

SDK traversal uses anchored descriptors, O_NOFOLLOW/O_DIRECTORY and NOATIME on
Linux. Only approved SDK directories are inventoried; no unapproved file contents
are read. Every emitted identifier is validated against the unchanged SDK lock or
fixed sentinel set, including all failure paths. Runtime/site ancestor errors use
stable identifiers and never disclose the private host path component.

No configuration/.env/process-environment/load CSV/database/model/receipt reads,
worker/Prefect queries, secret-provider execution, SDK imports, child execution,
HTTP, IMDSv2, AWS APIs, ENTSO-E requests, service operations or file writes are
reachable in the remote payload. Local builder/evidence writes are not remotely
assembled. Ordinary SSH authentication/access logging may occur.

## Immutable package and supervisor

V3 binds V2 manifest
`caafdcadedaa3fc899cd63e5005bd0f803990bea05ddba477c4f56815011c0e2`, every V2
artifact, the unchanged SDK lock and the new runner/inspector/builder/review/tests.
Full dependency inventories, sizes and SHA-256 hashes are checked before loading
helpers or connecting. Only selected capture/runtime source is remotely compiled;
V2's SDK module, provider, child runner and main dispatcher are not included.
Payload, SSH helpers, supervisor and output validator use retained verified bytes.
Python 3.9/3.14 assembly uses original source segments rather than unparse output.

The existing pinned connection-profile/target/known-host hashes and identity
metadata checks remain intact. StrictHostKeyChecking, BatchMode, IdentitiesOnly,
IdentityAgent=none, no forwarding/multiplexing/ambient SSH config and
ConnectionAttempts=1 are unchanged. There is no arbitrary command/path argument.

Exact remote command:

```
sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -
```

One SSH attempt, remote 60 seconds, local 90 seconds, five-second escalation,
16 KiB cap per stream, no retry or polling. Evidence is sanitized through an exact
schema before local storage under the existing ignored private preflight root,
`sdk-verification-v3-*/assessment.json`, directory 0700/file 0600. Raw stdout/stderr
is never retained. All-package PASS means only that the SDK verification passed;
backend selection, IAM rights and source availability remain UNVERIFIED.

## Local validation and future execution

Offline temporary fixtures cover missing files, changed content, unsafe permissions
and ownership, links and substitutions, unexpected layout/native files, metadata
version differences, multiple mismatches, unknown OS errors, approved identifiers,
progress counts and zero network access. Matching fixtures return the identical
held-file bytes from V2 and V3. Existing V2 tests protect its unchanged Python 3.14
SDK execution path and provider semantics. Linux identity/NOATIME behavior and the
actual production mismatch remain unverified locally.

Proposed future command; NEW separate remote authorization is required:

```
venv/bin/python -I -B deploy/staging/forecast-publication/load-source-check-aws-v3/run.py --manifest-sha256 <V3_MANIFEST_SHA256>
```

`--local-check` verifies locally and cannot connect. No invocation was executed
remotely during this task. No package installation, dependency refresh, policy or
permission change, production/staging write, publication or Git operation occurs.
