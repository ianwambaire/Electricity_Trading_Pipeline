# Continuation v2 — correct the manifest binding and identify preflight paths

LOCAL PREPARATION ONLY. No network, deployment, repair, publication or Git action.
New manifest/transaction; the original48a17404aa82c2fc16ab961311a7007224e1ee7016ecbc6ca5de04bed8aed389
and prior62b03da0c79211714777aa0d6f20bf97d12b2b54b6e4ca069fb4ed82ee1778a4
packages, source closures and transaction evidence remain unchanged.

## Confirmed defect and limits of historical evidence

The prior build.py first assigned a five-file hash map to `original`, then reassigned
that variable to verify_original()'s ENTIRE configuration dictionary. It serialized
that entire config into config.original_tools. The immutable62 manifest confirms
its keys are files, installed_tools, original_packet, original_tools,
pipeline_before, transaction and worker_base_sha256. The first sorted key is files.
The intended keys are prepare.py, publish.py, shared/__init__.py,
shared/forecast_publication.py and tools-manifest.json, each with a SHA256 string.

The prior verifier deterministically attempts <approved-original-tools-root>/files
if initial host checks and tool-directory checks pass. A native temporary-file
reproduction using the exact prior job/manifest raises FileNotFoundError/errno2
and produces the original PREFLIGHT/NONE report. This is a PROVEN package bug,
not a missing production resource to create. Do NOT create a file named files.

The saved remote stdout has only MISSING_PATH/errno2/PREFLIGHT/NONE; stderr is empty.
Initial fresh() and original_tools() ran before the first step label. payloads()
does no path lookups. Thus the historical failure was in initial host checks OR
original-tool verification; it predates src/shared handling. The malformed lookup
is established, but the captures cannot exclude an earlier host missing path as
the historical first exception. No historical cause is invented.

## Exact minimal corrections

- Builder uses distinct original_config data and takes ONLY its original_tools map.
- Local verification requires equality with the original48 manifest's correct map
  BEFORE SSH. Remote original_tools() checks exact five-key/64-hex schema before
  any directory or file lookup. No required path is skipped or repaired.
- Label initial host/original-tool calls and nested capacity, model, pointer,
  candidate runtime, HTTP and preservation phases. FileNotFoundError.filename is
  mapped to a closed source-derived safe path ID. Known ancestors are derived only
  from approved paths, not from exception text. Unknown paths become
  UNMAPPED_REQUIRED_PATH. No raw filename or exception message is output.
- Add `preflight`, a read-only check of ONLY the two initial groups that could have
  produced the observed failure. It does not enter apply(), create a transaction,
  inspect later private backup records, or perform installation/activation/rollback.
  INITIAL_PREFLIGHT_PASS is NOT full deployment approval. Full apply still reruns
  ALL prior preconditions, backups, directory journaling and activate-last steps.

No change to the publisher, root privilege rule, old/retained tools, source payload,
directory ownership policy, model, expiry, receipt contract, thresholds, scheduling,
concurrency, .env or rollback semantics. Existing directory handling is inherited
unchanged. Source is copied into this v2 package; old executables are not edited.

## Path-lookup trace (all before mutation)

| Stage | Required IDs/paths | Existence handling / absence semantics |
|---|---|---|
| Initial capacity/window | PROC_MOUNTINFO, PROC_MEMORY; /proc entries; CAPACITY_OPT/WEB/STATE; SYSTEM_SYSTEMCTL | required; /proc processes disappearing during documented scans are ignored; uncaught required ENOENT fails |
| Frozen verification | FROZEN_MODEL and FROZEN_CONTRACT plus ancestors | required; safe/lstat/read; no permissive existence fallback |
| Pointer resolution | BACKEND_POINTER/RELEASE and STATIC_POINTER/RELEASE, parents | required strict resolution; any missing target fails |
| Candidate runtime | CANDIDATE_PROC_STATUS/CMDLINE/CWD/FD; PROC_TCP/TCP6; CANDIDATE_CGROUP and CGROUP_MEMORY_* | required; disappearing individual fd links are explicitly ignored; required process/cgroup files fail |
| TLS/HTTP health | SYSTEM_CA_BUNDLE variants when selected by trusted OS TLS | HTTP health required; no CA override/bypass; unapproved OS path hidden as UNMAPPED_REQUIRED_PATH |
| Preservation | PRODUCTION_ROUTING, STAGING_ROUTING, STAGING_ACME_CONFIG, CANDIDATE_UNIT, PRODUCTION_PUBLIC_CHAIN and approved archive chain, PRODUCTION_PARSER, production forecast/provenance/release manifest, PUBLISHED_SNAPSHOT_00..12 | required files, no optional fallbacks; hashes read only |
| Original tools | ORIGINAL_TOOLS_DIRECTORY; ORIGINAL_TOOL_PREPARE/PUBLISH/INIT/CONTRACT/MANIFEST; PUBLICATION_ROOT/RELEASES and parents | required; correct hash-map schema validated before lookup |
| Later retained/source checks | RETAINED_TOOLS, PRODUCTION_SRC; SYSTEM_* executables; PREFECT_WORKER_SOURCE; original transaction record; PIPELINE_SOURCE | required; strict metadata/source/worker/version checks unchanged |
| Later expected absence | PRODUCTION_SHARED, delivery module, launcher, sudoers leaf, NEW transaction leaf | shared absence is allowed and journalled later; valid existing shared is preserved; other specified leaf conflicts fail; required parents still fail |

All listed groups precede missing shared-directory CREATION. The observed NONE label
narrows the historical exception to the initial groups; later groups already had
labels. Missing shared is expected and is not reclassified as a preflight failure.

PUBLISHED_SNAPSHOT indices follow the exact retained BASE.fingerprints list:
00 silver;01 gold;02 prices;03 load;04 generation;05 historical weather;
06 actual-vs-predicted;07 anomalies;08 holdout metrics;09 feature importance;
10 one-hour release manifest;11 next24 release manifest;12 frozen operational DB.
No data rows, source values, env values or private connection information are output.

## New bindings and future commands

New transaction: `bdfea3e3ac6449f5a74d316f6f0f7a2e`. No remote collision or
eligibility assertion is made locally; apply retains the live collision guard.

build.py --transaction creates only this new manifest locally. It pins original48
and prior62 source closures. A new transaction must differ from both old identities.
All executable bytes are retained after hashing and before compilation/transmission.
No arbitrary host, path, command or action argument beyond preflight/apply/rollback.

First authorize ONLY the initial read-only check:

    venv/bin/python -I -B deploy/staging/forecast-publication/automation-continuation-v2/run.py preflight --manifest-sha256 <NEW_APPROVED_MANIFEST_SHA256>

Remote60s/local120s; TERM/KILL5s; one pinned SSH attempt, no retry. It executes the
same initial capacity/window/runtime/preservation and original-tool checks, with
required-path errors now labelled. If active work/window fails, it stops normally;
there is no alternate safety threshold. No transaction or private error file is
created on the host. Captures remain local/private under the existing ignored root.
Original code contains mutation helpers, but the fixed preflight branch calls only
fresh()/original_tools() and read-only reachable helpers; failure logging skips
remote writes while CHANGED=false. Tests verify this boundary.

Future apply/rollback (NOT authorized by a read-only check):

    venv/bin/python -I -B deploy/staging/forecast-publication/automation-continuation-v2/run.py apply --manifest-sha256 <SAME_NEW_MANIFEST_SHA256>
    venv/bin/python -I -B deploy/staging/forecast-publication/automation-continuation-v2/run.py rollback --manifest-sha256 <SAME_NEW_MANIFEST_SHA256>

Apply120/180s and rollback90/150s, five-second escalation, captures131072 bytes per
stream, separate authorizations, no retry or automatic rollback. Same prior guards,
new independent backup transaction, original restored-state verification, exact
source hashes, source directory handling, retained-tool reuse and activation-last.
No bypass of any missing required path. A new unexpected missing path requires
separate evidence and approval, not an installer mkdir/chmod fallback.

## Tests and runtime limits

Local native fixtures reproduce the prior bad files lookup and unchanged old error;
new tests check correct dictionary schema/binding, specific safe IDs, unknown-path
redaction, required absence failing closed, expected shared absence, read-only
preflight and unchanged temporary apply/rollback behavior. Linux root metadata is
simulated in non-root fixtures; this dictionary/lookup defect is Python/platform
independent. Python3.9 grammar/compile is checked; no real Linux/root run or
production cause confirmation is claimed. Existing code/model/preservation tests
remain required. No live inference or scheduling diagnostic was extended.

Local validation: 540 selected backend/deployment/publication/authentication tests
passed, including 16 new focused cases. The mocked wrapper checks one attempt,
60/120-second preflight bounds, five-second escalation, held payload bytes,
specific missing-path reports, SSH failure and rejection of absent success scope.
Python3.9 grammar/compile checks cover the 16 manifest-bound Python sources and
all three assembled payloads; the available test runtime is Python3.14, not an
actual Python3.9 or privileged Linux run. The unchanged sudoers rule parses with
local visudo; this does not establish Linux/root installation compatibility.
All three --local-check actions must pass without remote connections. Original48
and prior62 manifest hashes and their complete recorded source closures are checked
by the new runner. New-file whitespace checks do not invoke Git.
