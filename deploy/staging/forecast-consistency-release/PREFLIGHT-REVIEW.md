# Forecast consistency — separate read-only preflight authorization

LOCAL preparation only. This is a new inspection package, not an addition to the
preserved release/tools manifests. Neither original manifest is regenerated.
No remote execution is authorized by this document. Obtain approval of the exact
PREFLIGHT-REVIEW.json digest, both script digests and the command below first.

## Exact future invocation (DO NOT execute without separate authorization)

From the repository root, substitute the reviewed SHA-256 of this NEW manifest:

```sh
venv/bin/python -I -B deploy/staging/forecast-consistency-release/run_preflight.py \
  --review-sha256 APPROVED_PREFLIGHT_REVIEW_SHA256
```

Safe local-only integrity rehearsal (never launches SSH):

```sh
venv/bin/python -I -B deploy/staging/forecast-consistency-release/run_preflight.py \
  --review-sha256 APPROVED_PREFLIGHT_REVIEW_SHA256 --local-check
```

The wrapper verifies itself, the exact payload, the unchanged bounded supervisor,
this review and its tests. It also verifies all preserved release files and all
preserved tooling copies against the original approved manifests. No old installer,
activation or rollback script is executed. The review JSON contains sizes/hashes;
its own digest must be supplied from the independently approved review response.

## Connection binding and local evidence

Connection details exist ONLY in the ignored private preserved-release sibling
`preflight/connection.json` (0600), with pinned `preflight/known_hosts` (0600),
under a 0700 directory. They are not release contents. The wrapper pins the profile,
approved target and existing trusted known-host bytes by digest. It never reads
private-key contents; it checks key ownership/type/permissions only. A changed
profile, host key or identity needs fresh local review and a newly hashed wrapper.
No arbitrary command, host, payload, SSH config or output-directory option exists.
A clean clone needs the separately retained private release and connection profile;
the source/tests themselves contain no personal connection paths or credentials.
Never commit the private profile, public-host-key binding copy or private captures.

Exactly one SSH invocation, no retry. Fixed SSH options disable user config,
agent forwarding, connection sharing, local commands and host-key updates;
strict known-host checking uses the pinned local file. Noninteractive sudo invokes
only this fixed remote command; payload bytes are supplied on stdin:

```text
sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 120s /usr/bin/python3 -I -S -B -
```

The reviewed unchanged local supervisor bounds SSH at 180 seconds and terminates
its process group with TERM then KILL after five seconds. The wrapper has a 190s
outer malfunction deadline (not an extended SSH execution budget). Both layers
have no retry. Remote sudo permission must already exist; no sudoers change is
made. This client restriction does not claim the server account has least-privilege
sudo rights. Existing audited host trust is retained, not newly accepted.

## Exact allowlist

- Linux stdlib root payload; O_RDONLY/NOFOLLOW/NONBLOCK/NOATIME bounded reads.
  No writable DB connections, filesystem changes, package installs or app imports.
- Metadata/canonical safe ancestry for the two existing current-release symlinks.
  SHA fingerprints of targets, static index, installed API/lock sources (23 known
  source/lock hashes from the prior baseline + reviewed two-file hotfix).
- One exact `systemctl show` query for production API, Streamlit, Prefect worker,
  Prefect server, PostgreSQL and candidate. Privately parse selected properties;
  never emit ExecStart, environment-file contents or process argv.
- Candidate UID/GID 992, one worker, actual owning loopback TCP8010 socket;
  NoNewPrivs/Seccomp/capability status; configured sandbox, address-family and IMDS
  deny settings. Read effective cgroup-v2 memory.high=384MiB, memory.max=512MiB,
  memory.swap.max=0. Query existing effective BPF attachments using BPF_PROG_QUERY
  only (x86_64 syscall321 command16); never attach/load/update a program.
- Privately read the single candidate environment file: exact root0600, staging,
  data-root, public issuer/client and disabled TOTP pilot baseline. Duplicate keys
  fail. Report only SHA and match/presence booleans, never values. Publication root
  may be absent/unconfigured; that does not become a working publication claim.
- Verify installed code baseline before runtime probe. `nsenter` joins only the
  existing candidate mount namespace; clears supplementary groups, switches to
  UID/GID992, runs its existing isolated Python with -I -B and a minimal nonsecret
  environment. Check Python3.14.7, all26 exact locked distribution versions,
  compiled imports (NumPy/pandas/pydantic-core/cryptography/cffi), read/nonwrite
  access to the frozen data and optional publication root. Block sockets in the
  child; do not import application/model/ingestion code. No new interpreter/venv.
- MemAvailable>=768MiB, swap-use measurement; /opt filesystem available bytes
  >=2GiB + twice the reviewed release size. This does not reserve capacity or
  include unmeasured future control/backup overhead.
- Fixed loopback Prefect4200 read-only deployment GET and two `/flow_runs/filter`
  POST queries (reads only). Verify the known deployment, one enabled hourly
  :45 UTC schedule, concurrency1 and original null collision options; inspect
  active/scheduled counts and ten-minute window. Bounded /proc argv scan for
  fixed ingestion/engine markers; no argv/environments printed.
- Fixed loopback GETs: API8000/health; candidate8010/health and /ready;
  Streamlit8501/_stcore/health; HTTPS443 with staging SNI/hostname, system trust
  validation and no DNS lookup: `/`, one root-referenced hashed JS/CSS asset,
  `/api/health`, `/api/ready`(404), unauthenticated Admin provenance(401), and
  `/.well-known/acme-challenge/preflight-probe`(200). No redirects followed,
  credentials, JWKS, Cognito, external provider or metadata-service requests.
- Before/after SHA fingerprints of fixed production/staging Nginx configs,
  candidate unit, production PUBLIC fullchain certificate, all13 frozen published
  files, production next24 release manifest and current forecast/provenance;
  service PID/state fingerprint. Certificate private keys are never read.
  Source-data records, model binaries and feature vectors are never output.

## Reports, hard stops and prerequisites

Sanitized stdout schema: `schema_version:1`, `status:PASS|BLOCKED`, fixed named
checks each with `status:PASS|FAIL|UNVERIFIED|NOT_RUN` and explicitly allowlisted
boolean/integer/hash facts. UNKNOWN text, additional keys, malformed JSON or
secret-like string facts are rejected, not echoed. Wrapper adds actual exit status,
report_produced and a fixed safe failure category (hash/local validation, SSH,
host-key, sudo, timeout, unexpected output or checks blocked). Raw stderr is never
printed. Private local 0700 inspection directory retains 0600 stdout/stderr and
sanitized.json. No remote report file is written.

Identity/preservation prerequisites fail before deeper inspection. Missing tools,
read errors, drift, unsupported namespace/interpreter/cgroup layouts, inability
to prove protection or access become UNVERIFIED/BLOCKED, never inferred success.
Any required check not PASS blocks deployment readiness. An absent overlay is
honestly reported and requires later path/config approval; never publish fixtures.
No automatic repair, fallback, retries, cleanup, rollback, service action or writes.

Prerequisites: original preserved package, trusted private profile, Python3.9+
stdlib on host, existing noninteractive sudo/timeout/systemctl/nsenter, Linux
x86_64 cgroup-v2/BPF query permission, existing isolated runtime, readable reviewed
files and functioning services. Imports remain bounded at20s; systemctl8s;
individual HTTP requests3s, all inside the120s remote deadline.

## Limits and later acceptance

This observes one instant, not a reservation or deployment approval. Start/end
fingerprint drift can be caused by normal scheduled activity; stop and review it.
Existing historical bytes are not live operational evidence. Baselines collected
here establish preservation during this inspection, not equivalence to an absent
older signed baseline. Model manifest fingerprinting is not model deserialization
or a comprehensive model-binary audit. No database records/SQL are inspected.
Only candidate systemd metadata, process state, namespace access and cgroup/BPF
attachment evidence are checked; this is not formal verification of kernel BPF
bytecode, packet-level IMDS denial or every syscall restriction. nsenter child is
not in the service's BPF cgroup, so its socket block proves no such network claim.
Third-party compiled imports use the existing reviewed runtime; versions do not
prove every installed wheel byte. Unknown interpreter layouts fail closed.
Live token-authenticated Admin/Analyst checks, all seven UI pages, browser OAuth,
forecast freshness/receipt validity and future publication require separate
acceptance. No claim about A03 deployment or production forecast eligibility.

HTTP requests may generate normal access logs, sudo/SSH normal audit records;
NOATIME is required for explicit file reads. Python import machinery may read
library metadata; bytecode writes are disabled. No guarantees about incidental
kernel counters/access accounting. No nginx -t/-T, Certbot or external requests.
