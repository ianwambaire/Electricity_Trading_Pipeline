# Forecast-consistency preflight — Checkpoint 1

LOCAL PREPARATION ONLY. This document does not authorize SSH or deployment.
The preserved staging release and its original tools/release manifests are unchanged.
Checkpoint 2 comprehensive verification must follow the owner's manual commit and
explicit instruction. A new remote authorization package is Checkpoint 3; no old
remote authorization applies to these changed bytes.

## Invocation and bindings (future, not executed)

After separate approval of the exact new PREFLIGHT-REVIEW.json hash:

```sh
venv/bin/python -I -B deploy/staging/forecast-consistency-release/run_preflight.py \
  --review-sha256 APPROVED_NEW_REVIEW_MANIFEST_SHA256
```

Adding `--local-check` verifies local bindings only, with zero transport attempts.
The wrapper validates the new manifest's exact artifact set, hashes and sizes;
all preserved release payload files and preserved tooling copies; private profile,
approved target and existing known-host hashes. Connection paths and target values
exist only in ignored `preflight/connection.json` and `preflight/known_hosts` below
the private preserved-release parent, files0600/directory0700. Private-key contents
are never read. No arbitrary host, remote command, payload or capture destination
argument exists. A clean clone needs these separately retained private inputs.

Executable bytes are retained from the SAME reads whose hashes/sizes passed.
The remote stdin payload is never reopened. The validator and bounded IO/supervisor
helper are compiled from those same retained bytes under a non-main module name;
there is no dynamic file import. The old a3-bounded-local.py remains a hash-checked
historical review reference, but is no longer executed: it cannot enforce streaming
output caps. The new local supervisor is `bounded_run`, embedded in the verified
payload. This avoids nested process groups escaping cleanup and introduces no
additional mutable executable file or helper dependency. Trusted local Python/OS
and the initially invoked reviewed wrapper remain prerequisites.

## Exact command and network allowlist

One SSH invocation, strict pinned known-host verification, no user SSH config,
agent forwarding, local commands, host-key update, shared connection or retry.
ConnectTimeout10, ConnectionAttempts1; noninteractive sudo requests exactly:

```text
sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 120s /usr/bin/python3 -I -S -B -
```

The local bounded supervisor directly launches that fixed SSH argv in its own
process group with a180-second execution deadline, TERM then KILL after5 seconds.
It also kills surviving descendants even when the leader exits during escalation.
No retries, automatic repairs, rollback, upload or remote report writes.
The server account must already have the appropriate sudo permission; this client
restriction does not prove the host's sudoers policy is least privilege.

The root payload uses only system Python stdlib (-I -S -B), fixed bounded reads,
and these approved inspection operations:

- Exact systemctl-show query for production API, Streamlit, Prefect worker/server,
  PostgreSQL and candidate, at beginning and end. No service action or config test.
- Root-owned safe release-pointer ancestry and static index hashes. Privately read
  the single candidate env file (root0600), reject duplicate keys and compare only
  approved public identity/data/publication/TOTP-pilot settings. Never print values.
- Candidate UID/GID992, one worker, owning loopback8010 listener, process security
  status, unit sandbox settings and effective cgroup-v2 high384MiB/max512MiB/swap0.
- Existing effective ingress/egress BPF attachments via x86_64 BPF_PROG_QUERY
  only (syscall321/command16); no load, attach, update or packet-level IMDS probe.
- Passive installed API/lock hashes, interpreter stat/hash, bounded pyvenv.cfg and
  dist-info/METADATA parsing, all26 locked versions and startup-hook presence.
  No candidate interpreter, namespace helper, third-party module, native extension,
  model or application import executes. Versions are not executable-integrity proof.
- MemAvailable>=768MiB; report swap; disk>=2GiB plus twice the reviewed release
  size. These are observations, not reserved resources or measured install overhead.
- Fixed loopback Prefect4200 deployment GET and two read-only /flow_runs/filter
  POSTs; one enabled :45 UTC schedule, concurrency1, original null collision
  options, active/queued counts, ten-minute window; bounded /proc argv marker scan.
  Never print argv, environment, task records or parameter values.
- Fixed loopback health GETs on8000/8010/8501. HTTPS443 uses loopback transport,
  staging hostname/SNI and system certificate trust: root, one referenced hashed
  JS/CSS asset, /api/health, /api/ready(expected404), unauthenticated Admin provenance
  (401) and existing /.well-known/acme-challenge/preflight-probe (expected200). No redirects, DNS/provider/Cognito requests, credentials or tokens.

## Streaming bounds and failure behavior

One selector-based helper services stdin/stdout/stderr concurrently. Each output
stream is capped at131072 bytes as it is produced, both locally and for systemctl
queries (8-second deadline). Reads use8192-byte chunks; buffered output cannot grow
past the cap. Stdin is the already size-bounded verified payload. Exceeding either
stream cap initiates TERM/KILL escalation, retains bounded prefixes and reports
OUTPUT_LIMIT regardless of any child success status. Timeout reports TIMEOUT.
Both preserve the actual reaped returncode (including signal termination).
Only capped output is written to private local files; there is no unbounded log
file. Explicit file reads enforce the limit during the read, not via a prior stat.

Private capture/report files use exclusive no-follow0600 creation under0700.
Capture errors report CAPTURE_FAILURE; report-write errors REPORT_WRITE_FAILURE;
local prerequisite errors LOCAL_VERIFICATION_FAILURE. They never print exception
text or raw stderr. Once execution returned, capture/report errors preserve its
actual exit status. Malformed/contradictory JSON is rejected; SSH/host-key/sudo
failures use fixed classifications. Failure to write evidence itself blocks success.
No raw traceback, connection path, secret, feature vector or configuration contents
is intentionally included in stdout. A broken output sink causes failure, not a
fallback to printing private captures.

## Publication-chain evidence

The existing contract is root/releases/<64hex>/bundle.json, selected by the exact
relative `current -> releases/<64hex>` symlink. Inspect every root ancestor without
following symlinks; require root ownership and no group/world writes. Root,
releases and selected release must be real root:992 directories0750. The sole
permitted symlink is root-owned current, with exact grammar; absolute, escaped,
alternate or nested-symlink targets fail. The bundle must be a real root:992 file0640,
bounded to2MB, hash-matching its release name and JSON schema version1. Re-read
only the pointer target to detect concurrent switching; no pointer changes occur.
Missing, unreadable, malformed, mismatched or unsafe evidence fails closed.
This verifies passive chain/container metadata, NOT the full forecast contract,
freshness, ACL/SELinux behavior or effective service-namespace access.
Those remain UNVERIFIED; no root-readability substitution is accepted.

## Preservation contract (exactly13 frozen files)

Before/after bounded SHA fingerprints cover these published relative paths:

- data/processed/silver_electricity_market_data.csv
- data/features/gold_model_features.csv
- data/raw/entsoe/prices.csv
- data/raw/entsoe/load.csv
- data/raw/entsoe/generation.csv
- data/raw/weather/open_meteo_weather.csv
- data/reports/actual_vs_predicted.csv
- data/reports/detected_anomalies.csv
- data/reports/final_holdout_metrics.csv
- data/reports/feature_importance.csv
- artifacts/models/final_model_release_manifest.json
- artifacts/models/releases/next24h/next24h_release_manifest.json
- database/electricity_trading.db — HISTORICAL A1 snapshot, not live state

SQLite is hashed as an opaque regular file (max64MiB), never opened through SQLite,
decoded, queried, checkpointed or migrated. No records are printed. Also fingerprint
fixed production/staging Nginx files, candidate unit, public production certificate,
production next24 release manifest/current forecast/provenance and service PID/state.
This records unchanged-during-inspection evidence, not an absent older signed baseline
or all production/model binary contents. Normal scheduled changes can block it.

## Report semantics and remaining assurances

Schema1 has a fixed set of check/fact names, typed boolean/integer/hash values and
PASS/FAIL/UNVERIFIED/NOT_RUN statuses. PASS requires complete evidence and true
required booleans, exact HTTP statuses and cgroup limits, capacity thresholds,
zero active ingestion/pipeline counts, matching preservation hashes and no claimed
runtime/effective-access success. Overall PASS cannot override a failed or
unverified required check. Installation metadata and publication metadata are separate
from runtime and effective access: the latter always remain UNVERIFIED in this
passive design, so the overall report is BLOCKED pending deferred acceptance design.
This does not make the read-only inspection itself unsafe or authorize deployment.

Linux behavior, actual host state, live auth roles/OAuth, all seven UI pages,
forecast receipts/freshness and native ABI/importability remain unmeasured locally.
BPF attachment is not bytecode or packet-level verification. SSH/sudo/HTTP can
produce ordinary access/audit logs; metadata/kernel accounting may change as part
of reads. Explicit remote reads use NOATIME. No nginx -t/-T, Certbot, installation,
permission change, service restart, database write, inference or publication occurs.

Checkpoint1 tests use synthetic fixtures and harmless LOCAL subprocesses only.
Stop for the owner's selective manual commit. Do not begin Checkpoint2 until told.
