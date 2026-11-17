# Parent Traversal Diagnostic V3 — stdin delivery correction only

Local preparation/testing only. No live SSH attempt or remote change is authorized
by this document. Release:phase-realized-parent-traversal-diagnostic-20261108-v3.
Parent V2 manifest:303af3ff285c1628081bec69bd28dd3502e0bc0994765c753a3800b3a3e6ab05.

## Confirmed defect

V1 and V2 reused EXTRA_OPTIONS from the connectivity-only /usr/bin/true checker.
That tuple contains StdinNull=yes. The approved SSH wrapper itself did not set it;
the diagnostic added it while constructing the real SSH argv. OpenSSH documents
StdinNull as preventing stdin reads (equivalent to -n). The bounded supervisor
pipes the immutable Python payload into the SSH process, but this option discards
that channel. The fixed remote `python3 ... -` consequently receives EOF, runs an
empty program, exits0 and emits no stdout/stderr. No diagnostic report, metadata
query or producer check is executed by that empty program. This matches the
retained V2 observation exactly; its EMPTY_STDOUT rejection was correct.

The supervisor writing bytes into a pipe is not proof the recipient consumed them.
This is a client-side command-construction defect, not evidence of a directory
permission problem, interpreter startup problem or successful producer traversal.
The reporting V1 preflight did not import these EXTRA_OPTIONS; its original
REPORT_PARENT_TRAVERSAL failure remains unverified and still needs this inspection.

## Minimal correction and unchanged safeguards

Construct the exact held verified V2 command, then replace its one StdinNull=yes
option IN PLACE with StdinNull=no. Do not append a conflicting setting: OpenSSH
uses the first obtained configuration value. Reject missing/duplicate/different
StdinNull settings and SSH -n/-f flags before connection. Keep sudo -n unchanged.
This permits immutable code on stdin, not interactive authentication: public-key
only, BatchMode, no password prompts, no TTY, no agents/forwarding/proxy, pinned
identity/destination/host key and -F /dev/null all remain unchanged.

V2's complete remote payload is byte-identical, including the permanent UID/GID1000
cleared-group/no-capability producer probe, exact metadata scope, command whitelist,
source-bound frame identifier and strict report validator. Both prior packages,
the original reporting release, all expected hashes and retained evidence remain
unchanged. No permission, ownership, ACL, service, scheduling or architecture
change. No deployment or manual report publication.

One future SSH attempt, no retry;20s remote/40s local,5s escalation,8192-byte streams.
Same safe validation-rule capture, private evidence directory0700/file0600. No raw
stdout/stderr, credentials, authentication material or unapproved paths retained.
A missing/malformed/wrongly bound response still blocks; an exit0 alone never passes.

## Offline reproduction

Tests use the real command constructors and verified bounded supervisor with a
local simulated SSH executable (Python, never /usr/bin/ssh). Connection profile
values are synthetic; no key or known-host file is opened by the simulator. It
models StdinNull and first-option precedence and runs only a local Python stdin
interpreter. The complete unchanged V2 payload is supplied through the actual
supervisor pipe. The interpreter deliberately denies the Linux host guard, so it
cannot run systemctl, setpriv, inspect real host directories or change identities.

StdinNull=yes reproduces exactly exit0/zero stdout/zero stderr. StdinNull=no delivers
the identical bytes, and the payload emits its real source-bound BLOCKED host-guard
response, which the unchanged strict V2 decoder accepts as a diagnostic result.
This proves delivery/response behavior, not Linux or staging acceptance. Malformed
responses and identity failures stay blocked. No SSH, network, privilege change or
live host observation occurs during testing.

Future separately authorized command:
`venv/bin/python -I -B deploy/staging/realized-parent-traversal-diagnostic-v3/run.py --manifest-sha256 <reviewed-manifest>`

Current /srv/powerflow producer traversal remains unknown. A separately authorized
V3 read-only inspection is required; do not change server access based on V2's
empty output or attempt a reporting preflight/deployment automatically.
