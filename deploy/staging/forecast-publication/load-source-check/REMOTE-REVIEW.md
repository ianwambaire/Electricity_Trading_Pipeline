# Fixed load-source check: remote adapter authorization review

Local preparation only. No remote attempt or ENTSO-E request has been executed.
This NEW `REMOTE-MANIFEST.json` leaves the preceding local-only `MANIFEST.json`,
its core/tests/review, all deployment packages and private evidence unchanged.
The builder is local tooling, not part of the remote payload.

## Exact operation and credential boundary

The remote payload imports only the trusted OS Python standard library. It is
started with `/usr/bin/python3 -I -S -B -`: no site hooks, application imports,
production interpreter startup, native third-party extensions or bytecode writes.
All non-stdlib executed sources are retained bytes bound by the new manifest.

Production ingestion calls `load_dotenv(PROJECT_ROOT / '.env')` before its stages,
and the ENTSO-E client obtains `ENTSOE_API_KEY` through `powerflow_secrets.get_secret`.
The adapter reuses that provider's bound source, removing only its eager boto3
import. No provider function is rewritten. It uses the exact python-dotenv 1.2.2
parser and interpolation source, copied with its license into `vendor/`, rather
than importing the host's writable SDK/site-packages or executing the shared .env.
The small parsing dependency closure is stdlib only and explicitly manifest-bound.

Effective configuration is reconstructed from the running approved Prefect worker's
environment, the fixed deployment's `job_variables.env`, then shared `.env` with
dotenv's override=False/interpolation semantics. The worker's UID/GID, service PID,
working directory, known Prefect worker source hash, process pool, entrypoint and
environment template are checked. Nonempty pool env defaults, command/directory
overrides, malformed variables and configuration drift fail closed. Per-flow
overrides and an earlier run's exact environment are NOT reconstructed; this is
a source diagnostic using current deployment configuration, not historical replay.

The worker's raw process environment and shared `.env` are read only into memory
for provider/interpolation semantics. They are never logged, hashed into reports,
passed as command arguments, persisted or returned. No credentials are read from
the local Mac. No alternative token/backend is tried.

**Backend limitation:** the existing env provider is executable without SDK code.
If the configured backend is SSM or Secrets Manager, the adapter stops before the
source request with `AUTH_BACKEND_REQUIRES_VERIFIED_SDK`. It does not use an env
fallback token. The current effective EC2 backend is not established by this local
task. AWS SDK dependency execution is deliberately unsupported by this version;
a verified SDK closure would be needed if that gate is encountered. This is an
explicit runtime prerequisite, not a claim that the host uses env authentication.

Before parsing secrets or querying ENTSO-E, root permanently drops all three UID
and GID values to 1000, clears supplementary groups and verifies the result. It
clears its own in-memory environment to PATH/LANG only; configured credential
values remain in an explicit mapping passed to the existing provider. This does
not change files, services or any other process. Default TLS roots cannot be
overridden through inherited certificate/proxy configuration.

## Fixed read allowlist

Production root is fixed in source, with no command-line path inputs:

- Five implementation files: `src/powerflow_secrets.py`, `src/scheduled_pipeline.py`,
  `src/ingestion/fetch_entsoe_data.py`, `src/ingestion/incremental_utils.py`,
  `src/ingestion/historical_range.py`: metadata, bytes and exact source hashes only;
  production copies are never executed.
- `.venv-prod/lib/python3.14/site-packages/prefect/workers/base.py`: hash only,
  matched to the previously reviewed deployed worker implementation.
- `.env`: at most 64 KiB, UID 1000, private permissions; provider configuration only.
- `data/raw/entsoe/load.csv`: at most 32 MB and one million rows; held snapshot
  bytes are passed to the unchanged comparison core. No load values are output.
- `/proc/<verified service MainPID>/environ` and `status`: bounded reads for the
  current worker environment and numeric UID/GID checks; never returned.

Every ancestor and file is opened with no-follow descriptors. Persistent files use
NOATIME on Linux. Regular-file type, owner and no group/world write permissions
are required; secret sources additionally require no group/world permissions.
Held-file metadata and named-file identity are checked. The service PID, inherited
configuration, deployment overrides, `.env` identity and load snapshot identity are
rechecked before source access. Drift stops the check. Configuration or data can
still change after the final check; evidence describes the captured snapshot,
not a transactional historical view of the pipeline or upstream service.

## Command and network allowlists

One fixed systemctl metadata argv (twice for drift protection), never a shell:

```
/usr/bin/systemctl show powerflow-prefect-worker.service --no-pager --property=ActiveState,SubState,User,Group,MainPID,WorkingDirectory
```

Two exact local Prefect HTTP GET shapes, repeated once for configuration stability:

- `http://127.0.0.1:4200/api/deployments/47e5ef51-26d0-44b6-b119-2c40d0e77397`
- `http://127.0.0.1:4200/api/work_pools/electricity-pool`

Each has a 3-second socket timeout, 100,000-byte response bound, no proxy or
redirects. No POST/PATCH/DELETE, task execution, publication or configuration writes.

At most ONE external GET to `https://web-api.tp.entsoe.eu/api`, using verified TLS
and OS trust roots, no proxies, redirects or retries. Fixed parameters:

```
documentType=A65
processType=A16
outBiddingZone_Domain=10Y1001A1001A82H
out_Domain=10Y1001A1001A82H
periodStart=202611031500
periodEnd=202611031600
securityToken=<in-memory configured provider value; never emitted>
```

The unchanged core enforces a 2 MB response bound, five-second socket timeout and
twenty-second read deadline. The outer remote bound includes DNS, configuration,
credential lookup and request time. A source-present/snapshot-absent result does
not establish ingestion omission or original withholding-time source availability.
The three target timestamps and whether they remain in the captured 48-hour
incremental overlap are reported, with no raw market values.

## Immutable bytes, SSH and execution bounds

The runner accepts only `--manifest-sha256` and `--local-check`. It verifies exact
manifest schema, artifact inventory, every file size/SHA-256 and assembled payload
before loading a helper or consulting the private pinned connection profile.
The SSH wrapper, supervisor, remote payload and local output validator execute
from retained verified bytes. No executable path is reopened after verification.
The old preflight module contributes only its AST-extracted `bounded_run` function,
not its inspection dispatcher or service/file functions.

The existing pinned wrapper verifies private connection-profile and known-hosts
hashes, target identity and private key metadata. Strict host-key verification,
IdentitiesOnly, BatchMode, ConnectionAttempts=1, ConnectTimeout=10, no forwarding,
no SSH agent, no control socket and no ambient SSH config remain in force.
No host, user or key location is embedded in new tracked files.

The ONLY remote command is:

```
sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -
```

One SSH attempt, remote 60 seconds, local supervisor 90 seconds, five-second
termination escalation. No retry or polling. Each stream is capped at 16 KiB.
Noninteractive sudo may fail if this fixed inspection command is not permitted;
there is no privilege fallback, repair or policy change.

Private local output is `preflight/load-source-*/assessment.json` under the
existing ignored release evidence root, directory 0700/file 0600. Raw stdout and
stderr are NOT persisted or printed. Only exact-schema sanitized results or fixed
transport failure categories are saved. Unexpected fields, free-form errors,
response contents and unknown causes are rejected. PASS means the comparison
completed, not that all observations exist or that forecasting is eligible.

## Future invocation — NOT executed during preparation

Replace `<REMOTE_MANIFEST_SHA256>` with the reported, independently verified hash:

```
venv/bin/python -I -B deploy/staging/forecast-publication/load-source-check/run.py --manifest-sha256 <REMOTE_MANIFEST_SHA256>
```

Local-only verification adds `--local-check`; it never calls SSH. Separate explicit
authorization must cover the one SSH attempt AND authenticated ENTSO-E read.
No deployment, repair, ingestion, merge, forecasting, publication, service operation,
AWS/Cognito write or Git operation is part of this package.

## Validation and platform limits

Tests use synthetic secrets, memory transports, temporary files and captured code
namespaces; no real credentials or source traffic. They cover provider precedence,
AWS no-fallback rejection, source protocol, drift, permission/symlink rejection,
strict SSH flags, bounds, output sanitization, no retries, dependency mismatches,
retained-byte execution and Python 3.9 grammar. Local Python 3.9.6 and 3.14 both
verify the same assembled payload hash; held payload imports, the existing env
provider, dotenv expansion and comparison were also executed offline on 3.9.6.
OS stdlib, system Python, systemctl,
sudo, Linux procfs and UID changes remain trusted host dependencies, not vendored
or falsely claimed to be verified Linux execution. They fail closed if unavailable.

The earlier macOS abort occurred in Matplotlib's native macOS GUI backend during
an unrelated prediction-plot test, after the core fixtures passed. This diagnostic
imports neither Matplotlib nor the prediction/model code. Re-running that isolated
existing test with MPLBACKEND=Agg checks the plotting explanation without changing
application code. Native Linux UID/procfs/NOATIME behavior remains a live precondition.
