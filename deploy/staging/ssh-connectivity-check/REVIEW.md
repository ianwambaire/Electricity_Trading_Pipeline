# One bounded SSH connectivity-only diagnostic

Local preparation only. No SSH, PowerFlow inspection or external request has run.
This package is separate from the immutable load-source-check package and does
not change its manifest, runner or failed-attempt evidence.

## Prior failure evidence

The exact failed attempt's private assessment contains exit 255,
`SSH_FAILURE`, and a null report. That directory has no raw transport capture.
This does not establish DNS, TCP, host-key, authentication or remote-command phase,
and does not prove whether the old source request began. Older evidence cannot
establish the phase of that particular attempt.

Local profile review confirms that the pinned destination is a numeric address;
forward DNS resolution of that destination is therefore unnecessary. No address,
username or key location is included here. This narrows the required connection
path but does not establish which phase failed in the earlier attempt.

## Sole remote operation

The remote command is exactly `/usr/bin/true`, with no arguments, stdin, sudo,
payload, interpreter, application imports, source reads, database calls, credential
provider access, ENTSO-E requests, deployment or service operations. SSH's ordinary
authentication/session logging may occur. Normal SSH server/shell startup behavior
is trusted host configuration; the client does not modify it or run inspection code.

Invocation template (private values are deliberately omitted):

```
/usr/bin/ssh -F /dev/null -T -i <pinned-identity> <reviewed -o options> <pinned-target> /usr/bin/true
```

`run.py:ssh_argv` constructs the exact argv from the existing pinned wrapper:

- BatchMode=yes, IdentitiesOnly=yes, StrictHostKeyChecking=yes.
- The exact pinned UserKnownHostsFile, GlobalKnownHostsFile=/dev/null.
- ConnectTimeout=10, ConnectionAttempts=1.
- ServerAliveInterval=10, ServerAliveCountMax=2.
- ForwardAgent=no, ClearAllForwardings=yes, PermitLocalCommand=no.
- ControlMaster=no, ControlPath=none, IdentityAgent=none.
- AddKeysToAgent=no, UpdateHostKeys=no.

Only LogLevel changes from ERROR to DEBUG1 for in-memory transport milestones.
These additional restrictions are explicit:

```
PreferredAuthentications=publickey
PubkeyAuthentication=yes
PasswordAuthentication=no
KbdInteractiveAuthentication=no
GSSAPIAuthentication=no
HostbasedAuthentication=no
NumberOfPasswordPrompts=0
RequestTTY=no
StdinNull=yes
ForwardX11=no
ProxyCommand=none
ProxyJump=none
```

No interactive authentication, agent, connection multiplexing, proxy, forwarding,
host-key update/acceptance, arbitrary destination, command or output-path option
exists. The runner accepts only the manifest hash and `--local-check`.

## Identity, immutable bytes and bounds

The existing connection.json hash, destination hash, known-hosts bytes/hash,
restrictive private-file permissions and identity-file metadata are verified through
the unchanged reviewed profile function. This identifies the approved key path;
the private key contents are never opened by Python. SSH itself reads the key as
part of its normal authentication. No private connection identifiers are embedded
in new tracked files or printed in reports.

MANIFEST.json binds the exact runner, local builder, review, tests, original SSH
wrapper and original bounded supervisor source by relative path, byte size and
SHA-256. Unexpected dependencies or any mismatch fail before connection. The
existing wrapper/supervisor also have explicit pinned source hashes in the runner.

Only the original `bounded_run` function is extracted from the preflight module;
none of its inspection/service functions is loaded. Original source text is used
to keep assembly identical on Python 3.9 and 3.14. The wrapper and new command
constructor/classifier execute from held verified bytes. No executable content
is reopened after verification. The private pinned profile is freshly revalidated
immediately before execution.

One SSH process only. Connect timeout 10 seconds; supervisor deadline 20 seconds,
then TERM with five-second KILL escalation. Each stream has a 32 KiB cap; overflow
terminates the process group. No retry, polling or subsequent probe exists. There
is no remote timeout helper or sudo: the only remote command remains true.

## Sanitized evidence

The classifier examines bounded client stderr in memory, then discards raw stdout
and stderr. It does not persist excerpts, redacted text, addresses, usernames,
paths, fingerprints, banners, key material or hashes of raw secret-bearing output.
Only fixed category/event strings, observed-stage enums, return code, byte counts
and UTC completion time enter local evidence.

Recognized categories include DNS_RESOLUTION_FAILURE, CONNECTION_TIMEOUT,
CONNECTION_REFUSED, NETWORK_UNREACHABLE, NETWORK_ACCESS_DENIED,
HOST_KEY_VERIFICATION_FAILURE, IDENTITY_FAILURE, AUTHENTICATION_FAILURE,
SSH_HANDSHAKE_FAILURE, SSH_HANDSHAKE_TIMEOUT, REMOTE_COMMAND_OR_SESSION_FAILURE,
SUPERVISOR_TIMEOUT, OUTPUT_LIMIT and UNCLASSIFIED_SSH_FAILURE. A local OS error
starting SSH is separately saved as LOCAL_SSH_START_FAILURE with numeric errno
only; exception messages and private paths are discarded.
NETWORK_ACCESS_DENIED does not identify whether a local sandbox, OS policy or
network control caused the denial. It is diagnostic evidence, not an AWS finding.

Known client DEBUG1 milestones establish TCP connection, completed key exchange,
matched pinned key, successful public-key authentication, fixed command request
and received exit status. Missing milestones remain UNVERIFIED. A command request
does not prove execution. SSH exit 0 for the fixed command verifies its completion
and preceding transport stages; unexpected stdout yields PARTIAL and is discarded.
SSH milestone text is operational evidence, not an independent server audit.

Only `assessment.json` is written under the existing private ignored root:
`preflight/ssh-connectivity-*/`, directory 0700, file 0600. No raw captures are saved.
The runner prints the same sanitized report. Capture/verification errors produce
only LOCAL_VERIFICATION_OR_CAPTURE_FAILURE and never cause a second attempt.

## Local validation and future authorization

Tests replace the SSH supervisor entirely. Fixtures cover exact argv, strict host
key and public-key-only authentication, each transport category, phase uncertainty,
secret redaction, one-attempt behavior, private evidence permissions, executable
closure, mismatch rejection, retained bytes and a local-only supervisor timeout.
No application, database, AWS, credentials or source endpoints are involved.

Local results: 40 offline tests passed. Both Python 3.9.6 and 3.14 validate the
same manifest and extracted supervisor bytes. Python 3.9.6 also executed the
classifier against synthetic transport failures and constructed the fixed argv,
with zero remote attempts. Git diff whitespace checks passed. Real SSH transport
and remote command execution remain unverified until separately authorized.

Local-only integrity verification:

```
venv/bin/python -I -B deploy/staging/ssh-connectivity-check/run.py --manifest-sha256 <MANIFEST_SHA256> --local-check
```

Proposed future live command, NOT executed during preparation:

```
venv/bin/python -I -B deploy/staging/ssh-connectivity-check/run.py --manifest-sha256 <MANIFEST_SHA256>
```

Separate explicit authorization must bind the final manifest and runner hashes
and permit exactly one connectivity-only SSH attempt. It does not authorize the
load-source diagnostic or any further remote action. No Git commit/push is performed
by this package or by the preparation task.
