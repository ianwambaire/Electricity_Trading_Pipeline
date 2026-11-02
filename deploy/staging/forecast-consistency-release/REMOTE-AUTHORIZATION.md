# Exact read-only authorization request — no execution yet

This instruction sheet is not an executable dependency. Approval must name the
three hashes below; do not authorize an unspecified latest version. No prior
remote authorization covers this revised payload. Local verification is distinct
from observed Linux/staging behavior. No deployment is proposed here.

## Bound package

- Payload SHA-256: `3421bceb00fcfb6077a4106397b8ba231c4ade5ae6d11706ca327f5f914fb7f8`
- Wrapper SHA-256: `0598ec061225a70fbe8f418f337299afaf242e4d463780d34e6b594aa8e0a48a`
- New review-manifest SHA-256: `9a37a1403283b28d1dc8f83ae71466bf4fbaba02cc744a3f19a200fcbd4d6455`
- Preserved release-manifest SHA-256 (unchanged): `9dc8ce31f1b294c43239824ffa544a76f4fdf6ba334ea8fd72b9431365ed5c19`
- Original tools-manifest SHA-256 (unchanged): `5dbb4a5665c9c76c4daa510f98e85152dfb291b1afd5ceac477edda13bba271b`

Local executable closure: wrapper plus its retained verified payload, including
report validation and bounded process supervision. Only trusted system/local
Python stdlib/OS executables are prerequisites; candidate Python/packages do not
execute. The old supervisor is an additionally verified historical reference,
not an executed helper. Current source/test/review sizes and hashes are in the
new review manifest. The preserved release and tooling copies are checked without
regeneration. No production data, secrets or model binaries are embedded.

## One proposed invocation — DO NOT EXECUTE WITHOUT EXPLICIT APPROVAL

```sh
/Users/iannganga/Desktop/electricity-trading-pipeline/venv/bin/python -I -B \
  /Users/iannganga/Desktop/electricity-trading-pipeline/deploy/staging/forecast-consistency-release/run_preflight.py \
  --review-sha256 9a37a1403283b28d1dc8f83ae71466bf4fbaba02cc744a3f19a200fcbd4d6455
```

Before invoking, independently verify wrapper/payload/new manifest hashes above.
Any mismatch requires renewed local review, not a refreshed approval hash. The
wrapper then verifies all dependencies and private bindings before transport.
For LOCAL integrity only, append `--local-check`; this cannot invoke SSH.

The approved host/login/key are obtained only from the already privately retained,
Git-ignored connection profile. No arbitrary host, command, payload or destination
argument is accepted. Profile/target/known-host hashes are pinned in the wrapper.
Do not display profile values, private key contents, raw stderr or environment files.

## Proposed authorized scope

Exactly ONE SSH stdin invocation on the previously approved target. Strict pinned
host-key checking; existing private key, no agent/config change; noninteractive
sudo; ConnectTimeout10 and ConnectionAttempts1. Local supervisor:180s execution,
TERM then KILL after5s. Fixed remote command:

```text
sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 120s /usr/bin/python3 -I -S -B -
```

Only the allowlisted read-only operations in PREFLIGHT-REVIEW.md: service metadata,
release pointers, file hashes/ownership, passive installation and publication-chain
metadata, capacity, effective candidate process/cgroup/BPF evidence, known Prefect
read-only queries/process markers, fixed loopback health/TLS probes, before/after
preservation fingerprints including all13 frozen publication files. No candidate
interpreter/imports, SQL, model inference, production data writes, AWS calls,
uploads, permission changes, nginx validation/reloads, service operations, pipeline
trigger, publication, repair, retry, rollback or deployment. Ordinary SSH/sudo/HTTP
logging and read-related kernel accounting may occur.

## Host prerequisites and stop conditions

Existing audited host trust/profile/key permissions and read-only privileged
inspection permission must already be available. The client narrows its sudo
request; this does not establish least-privilege sudoers on the host. If a password,
TTY, installation, configuration change or expanded command scope is needed, stop.
Do not repair it or change sudoers. System Python3.9+ stdlib, timeout/systemctl,
Linux x86_64 cgroup-v2 and permitted BPF queries are prerequisites. Missing tools,
permission failures, layout drift, resource pressure, transport errors or preservation
drift require reporting, not fallback or another attempt. Private local evidence
storage needs adequate capacity; capture/report failures also block success.

## Exact report interpretation

Sanitized summary: actual `exit_status`, `report_produced`, fixed `failure_category`
and validated schema1 report (`status` plus fixed check names/facts). Caps:131072
bytes for each captured stream. No raw diagnostics are echoed; private0600 captures
and sanitized report are retained under an ignored0700 local inspection directory.
On timeout or output overflow, retained prefixes are bounded and the actual reaped
status is preserved. No failed command is retried.

| Evidence | Meaning after the read-only inspection |
|---|---|
| Identity, pointers, env, services, sandbox, cgroup, BPF, capacity, preservation | Observed PASS/FAIL/UNVERIFIED safety facts; any missing critical assurance blocks deployment preparation |
| Installation metadata | Version/lock/file metadata consistency only; not executable integrity or native ABI/import proof |
| Publication metadata | Safe active chain/container hash and passive permissions only; not forecast freshness or effective candidate-user access |
| Pipeline | Current schedule/concurrency/non-overlap/window observation, not a reserved installation window |
| Health/TLS | Fixed unauthenticated loopback responses and trusted staging SNI; not browser OAuth or authenticated role acceptance |
| Runtime, effective publication access | Intentionally UNVERIFIED; must be demonstrated later through a separately approved safe runtime acceptance procedure |

Because required deferred checks remain UNVERIFIED, the aggregate report is
expected to be BLOCKED/exit1 with CHECKS_BLOCKED even if all observable checks pass.
This is not a transport failure and must not cause a retry or weakened gate.
A completed inspection can still supply evidence for a later narrowly scoped
staging deployment/acceptance design; it never grants permission to deploy.

After this one inspection, report the real facts and stop. Only then may a later
local deployment procedure be prepared using those facts; activation, uploads,
pointer/env changes, candidate restart, forecast publication and rollback require
separate exact approval. Production Streamlit remains in place. A03 remains separate.
