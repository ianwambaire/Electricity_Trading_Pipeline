# Candidate-bound load source check V4 — authorization review

LOCAL PREPARATION ONLY. No remote authorization is granted by this package.
No SDK is installed or repaired. V2/V3, original/candidate baselines, prior
inspection packages and failed-attempt evidence remain unchanged.

## Immutable reference and assembly

V4 pins independently sourced candidate manifest
`e169563689408ac806b097dc0b9e69e374fa82dea6b3a706a05bde802844d25d`, candidate SDK lock
`4ff10a67faafbe36031e960e0afbce696187b7e3928da396e248ffc7ffdb2421` and official reference wheel
`0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3`.
It merges and verifies every artifact from that manifest and unchanged V2/V3
manifests, rejecting conflicting overlap. The new manifest additionally binds
its runner/inspector/builder/review/tests and all three original manifests.

The wheel is hash/RECORD/metadata verified from retained bytes using the bound
candidate reference helper. The candidate lock is independently reconstructed
from the old lock's unchanged 178 entries and the wheel's 37 urllib3 entries and
must match exactly: 215 files, 194 Python sources, seven METADATA, 14 botocore data
files. No host hash can enter expected bindings. Local reference provenance limits
remain: reliance on official PyPI TLS assertion; no local Sigstore verification.

The exact unchanged V2 builder assembles the payload, with one guarded source
substitution in its version constraint: the sole urllib3 2.7.0 literal becomes
2.8.0. The builder is given explicit in-memory aliases for the candidate lock
and composed inspector. No V2 files are edited. No other builder statement,
provider, SDK, source request, child process or comparison logic is rewritten.
The version cannot be supplied by CLI or remote host. Full lock equality is
required before the builder is used. Python versions use exact retained source
segments, not ast.unparse, to preserve deterministic executable hashes.

New inspect.py executes the unchanged V2 workflow definitions and unchanged V3
verifier definitions in isolated namespaces, without their main entrypoints.
It substitutes only the SDK gate and extends the sanitized report with SDK
verification detail. V3's verifier is given the exact candidate lock. The actual
Python-3.14 child envelope also contains all 215 candidate records. The unchanged
child rehashes every held byte before any SDK import. No disk SDK import fallback.

## Host gate and retained-byte execution

All original source contract and Prefect-worker hash checks, runtime configuration
reconstruction, procfs checks, bounded snapshot captures/drift checks and OS runtime
identity/hash checks remain. No private evidence or configuration values enter output.

Before any SDK import or credential access:

1. No-follow anchor the fixed original production site-packages root. Check site
   owner/mode/read/traverse policy; bounded immediate-entry enumeration <=8192.
2. Require exactly the one expected urllib3-2.8.0.dist-info entry. Reject other
   urllib3- or urllib3.-prefixed layouts, old versions, symlinks, unsafe owner or
   mode and missing metadata directory. Unknown names never enter output.
3. V3 inventories all seven SDK code namespaces and rejects added Python/native
   code or links. All 215 approved files must be regular, stable, exact size/hash,
   owner 0/1000, no group/world write and readable by pipeline UID/GID 1000.
   Preserve no-follow ancestry, descriptor captures, Linux NOATIME, 2 MB per file,
   6 MB aggregate and deterministic first-failure detail. Do not skip a mismatch.
4. Hold accepted bytes in memory. Permanently drop supplementary groups and all
   UID/GID identities to 1000 using the exact reviewed V2/host mechanism.
5. Recheck the trusted /usr/bin/python3.14 inode/security state, then start only
   that approved interpreter with -I -S -B and held child code. It checks uid/gid,
   groups/capabilities and Python 3.14 before validating/importing the SDK envelope.

The parent Python-3.9-compatible bootstrap never imports SDK modules. Actual SDK
execution still requires the previously approved root-owned OS Python 3.14 hash
`ac1b8b9815ac3935d6708cbe8223458a19d9dee438ebe18e88378d61712da8d6`.
No runtime requirement, owner/mode policy or source freshness policy is relaxed.

## Authentication and exact source scope

Reuse original configured production provider semantics. Backend must be ssm or
secretsmanager in us-east-1, not env; no fallback token, profiles, alternate chains,
static AWS credentials or configured alternate endpoints. Only EC2 iam-role via
IMDSv2; IMDSv1 forbidden. At most one token/role/credentials resolution sequence,
and one configured secret read: SSM GetParameter with WithDecryption=True OR
Secrets Manager GetSecretValue. Never both. IAM permissions remain unchanged.
Do not retain secrets/identifiers, cached values or SDK debug/error text.
The production secret provider's cache remains unwrapped in the one-shot child.

AWS origin/method/target/body restrictions, TLS verification with controlled OS CA,
no proxy/redirect/retry, connect/read bounds, response byte/header bounds and the
child's 20-second bound are unchanged. No AWS call occurs before SDK verification
and permanent drop. The parent reports selected backend/IAM-role success only.

Reuse the exact reviewed source comparison core, with at most one TLS-verified GET
against web-api.tp.entsoe.eu /api, A65/A16, DE_LU (10Y1001A1001A82H), fixed period
202611031500..202611031600 UTC. No arbitrary host/date/parameter/token arguments.
No redirects/retries, 5-second socket bound, 20-second source bound, 2 MB body cap.
Read only the already approved bounded load snapshot (32 MB) and source/configuration
contracts; never persist or merge market data. Report availability only for Nov 3
15:15, 15:30 and 15:45 UTC, matching snapshot availability and current 48-hour
incremental-overlap eligibility. Source availability now does not establish its
availability at withholding time; ingestion causation stays UNVERIFIED.

## Transport, output and authorization boundary

Use the existing hash-bound pinned profile/identity/known-host checks. Preserve
strict host-key checking, noninteractive/public-key-only SSH, no agent/forwarding,
no multiplexing or ambient SSH config and ConnectionAttempts=1. Exactly one SSH
attempt, no polling/retries. Fixed command:

```
sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -
```

Remote 60 seconds, local 90 seconds, five-second escalation, 16 KiB per stream.
Payload, executable dependencies, supervisor and output validator are compiled from
retained verified bytes, without reopening executable content after verification.
Local-only CLI accepts manifest SHA and optional --local-check, never remote args.

Sanitized evidence extends V2's exact schema with sdk_verification: approved
relative dependency identifier, fixed category/stage, verified-file count 0..215.
NOT_STARTED does not claim verification. COMPLETE requires exactly 215; all source
attempts/IAM success/PASS require COMPLETE. Invalid output is rejected before local
storage. Use ignored private preflight/load-source-aws-v4-* directory 0700 and
assessment.json 0600. No raw stdout/stderr, market values or private host paths.

Remote payload has no install/repair, file/database/configuration writes, ingestion,
forecast, publication, Prefect run creation, service restart or IAM mutation path.
The Linux credential child and TLS/CA checks remain necessary; local compatibility
and metadata observation do not establish installed executable integrity.

## Offline validation and future operation

Tests populate isolated real temporary files from the exact candidate reference,
with simulated Linux owner IDs, then verify all 215 files. Faults must block before
identity drop, credential lookup and source requests. Exercise missing/changed files,
owners/modes/links, extra code, old/malformed metadata, alternate layouts, candidate
wheel/lock tampering, retained child-envelope bindings, sanitized progress details
and irreversible-drop ordering. Reuse established protocol/source/parser/snapshot
and supervisor tests; SDK operations use audited offline mocks only.

Local validation: 247 selected tests passed, including 25 V4 workflow/binding
cases and the 21 real SDK/urllib3-2.8.0 offline protocol cases. Python 3.9.6 and
3.14.7 local integrity/profile checks passed. Python 3.9 loads the assembled
definitions with only the main inspection entrypoint suppressed; no SDK import
or source request occurs. Manifest/source closure and whitespace checks pass.

No EC2, AWS, IMDSv2 or ENTSO-E calls during preparation. Actual Linux UID/capability,
procfs, NOATIME, installed hashes, IAM/CA and live upstream availability remain
unverified. Full host verification is mandatory on the next separately authorized
attempt; an installation mismatch is never repaired or refreshed automatically.

Future command requires separate explicit owner authorization:

```
venv/bin/python -I -B deploy/staging/forecast-publication/load-source-check-aws-v4/run.py --manifest-sha256 <V4_MANIFEST_SHA256>
```

No deployment/publication transaction is created or reused. No old package,
production/staging data, dependencies, source, schedules, services or model changes.
