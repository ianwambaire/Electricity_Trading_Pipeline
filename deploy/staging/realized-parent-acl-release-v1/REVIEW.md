# Reporting-parent search-only ACL transaction

Prepared locally; **no remote action authorized by this package**. Release
`phase-realized-parent-acl-20261108-v1`, fixed transaction
`6b59b34d211a4d7286e598137a512e8e`.

## Sole target and policy

Prior source-bound V3 observation: `/srv/powerflow` root:992, 0750;
worker primary UID/GID 1000, not an API-reader group member. Preserve those
identities, every mode bit, all unrelated access entries and the complete default
ACL. Add only `user:1000:--x`. Keep an existing mask unchanged; for a minimal ACL,
add an explicit mask equal to its existing owning-group permissions (r-x).
No mask recalculation, group additions, recursive ACLs, chmod or chown of the
target. Existing target-user permissions must be absent or zero.

Root coordinator enumerates **only immediate names** to require the three known
protected roots: published, forecast-publications, operational-publications.
It reads only directory ownership, mode and ACL metadata, not contents. Each
boundary must retain root:992 0750 and deny UID1000 all access, both with cleared
supplementary groups and actual worker groups. Default ACL, if present, must
also deny this producer for future root:992 objects. Unexpected names, links,
ACLs, ownership, permissions, group992 membership or ineffective isolation block
before mutation. This does not authorize a future reporting-store installation.
Future directories under this newly traversable parent require their own review.
The UID gains search by known name, **not listing**, read, or write. Existing
protected files remain behind denied child-directory boundaries. No access is
granted to another UID; unchanged mask/entries preserve their existing rights.

## Read-only preflight

Standalone preflight payload excludes the mutation module and ACL setter.
Linux x86_64 Python >=3.9 coordinator root, trusted OS tools and libacl; no
application/SDK imports. Pinned profile/key metadata/host-key and immutable parent
chain are verified locally before connecting. `StdinNull=no` preserves payload
transport. Existing scheduling gate verifies the fixed Prefect deployment,
concurrency1, no active pipeline/Prefect processes and strictly >600seconds to
next execution. The private backup parent must have at least4MiB available and
eight free inodes. Only read-only deployment/run-filter queries are used.

`acl_get_fd`, ACL xattrs and numeric ACL parsing must work. Missing/unsupported
libacl/ACLs, read-only mount, unsafe metadata, non-NOATIME support or mismatched
observations stop. No write-and-revert ACL support test is performed. OS library
is loaded only from a root-owned, non-writable, fixed /usr/lib64 libacl target,
held by FD and hashed for transaction drift, **not an independent OS binary
attestation**. An unsupported distro layout blocks, rather than searching paths.

Producer probe uses setpriv --no-new-privs --reuid=1000 --regid=1000 --clear-groups,
then isolated stdlib Python. Saved IDs, empty groups, zero effective/permitted/
ambient capabilities and NoNewPrivs are verified. Before change X/R/W must all be
false; afterwards X only true, directory read open must still fail, and all three
protected boundaries must deny R/W/X and directory read. No report/data reads.

## Guarded apply and rollback (separate authorization)

Apply repeats fresh gates twice, advisory-locks target directory, and snapshots
inode/device, numeric complete access/default ACL text, exact ACL xattr bytes or
absence, ownership/mode, protected-boundary ACLs, worker groups and libacl identity.
Creates a new root:root0700 transaction directory beneath the existing trusted
`/var/lib/powerflow-staging`. Writes and fsyncs two independently allocated,
root:root0600 backup files, checks bytes, SHA256, distinct inodes, journal identity
and plan before the setter. No existing directory mode changes. Fresh idle/state
comparison immediately precedes the sole `acl_set_fd` on the pinned parent FD.
No `setfacl` mode fallback. Permission changes are restricted to that one ACL;
only approved private backup/journal files are additionally written.

Post-change full-state, mask, isolation, cleared-identity and stability checks
must pass. On failure stop with phase/changed status, retain backups, **no retry
or automatic rollback**. Advisory locking cannot stop independent root ACL
administrators; do not overlap such changes. Drift before/after fails closed.

Explicit rollback requires exact transaction, independent matching backups,
unchanged target inode/owner/group/mode/default/child ACLs/library/worker groups,
and current ACL exactly original or exactly planned. Restore only original
access-xattr bytes (or remove extended access ACL if originally absent), preserving
original default ACL and mode. Verify exact complete snapshot and denied producer
probe. Unknown partial states block; no forced recovery or overwriting other ACL
administrators' work. A later reporting-store installation is intentionally new
inventory and must be reviewed/reverted before this rollback can run. Backups and
journal remain private for audit. No service restart is involved.

## Bounds and evidence

One pinned SSH attempt per separately authorized action; no retries/polling.
Remote/local deadlines: preflight30/60s; apply and rollback45/75s; TERM then5sKILL;
8192-byte output limits. JSON binds exact action/release/transaction/source digest,
strict fields/types/exit status; sanitized fixed identifiers only. Raw stderr is
not persisted. Local assessment0600 in existing Git-ignored private preflight
folder. Backups contain only permitted filesystem ACL metadata, no credentials,
application data, environment values or logs. No AWS, source requests, publishing,
Prefect triggering, deployment or authentication changes.

## Runtime limits

macOS validation uses fixtures and mocked libacl/kernel operations. Actual Linux
libacl presence, POSIX ACL support, current parent inventory/ACLs, effective access,
OS security policy and scheduling window remain read-only preflight conditions.
Support for read-only ACL introspection does not guarantee a later setter will
succeed under every kernel/LSM condition; apply fails closed without chmod fallback.

Primary references: [ACL FD reading](https://man7.org/linux/man-pages/man3/acl_get_fd.3.html),
[FD-bound setting](https://man7.org/linux/man-pages/man3/acl_set_fd.3.html),
[mask semantics](https://man7.org/linux/man-pages/man5/acl.5.html),
[setfacl fallback and masks](https://man7.org/linux/man-pages/man1/setfacl.1.html).
