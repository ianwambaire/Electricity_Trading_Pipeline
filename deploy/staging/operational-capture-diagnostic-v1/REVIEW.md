# Read-only capture-stage diagnostic

Exact target: 01a1b4fd-6f22-7738-8410-7df4e9e73e60 / pipeline
3dd2ddfda3b34b1c982a0d7c5342b222, natural 2026-11-07 08:45 UTC run.

Reuses the verified V5 acceptance assembly, which strips operational store imports
and omits helper main/deliver_terminal. Installed immutable helper hashes are
checked before capture. Never loads the terminal hook or invokes a publisher.
A fixed function-call boundary rejects publisher/installer entrypoints if reached.
No flow triggering, environment or credentials reads, service operations or writes.

The only capture inputs are exact-run loopback Prefect metadata, its read-only
immutable SQLite snapshot (existing SELECT authorizer), and its committed receipt
artifacts using existing inode/no-follow/ownership/permission/hash guards. Source
values and file content remain transient; only fixed gate codes, approved relative
source/function locations, exception classes, errno/SQLite numeric error codes and
file metadata are returned. No exception messages, payloads or private paths.

A bounded Python trace observes validations without changing their outcomes.
Pipeline UUID association is checked before any receipt-file read. Capture is
replayed against actual current time; historical state is not fabricated and no
freshness window is extended. Current replay findings cannot recover the erased
historical exception; deterministic source/contract defects can be reproduced
locally after the observed gate is identified.

Exactly one pinned SSH; 90 seconds remote,150 local,5 escalation; no retries.
Private sanitized evidence only. V5 and previous diagnostics are unchanged.
