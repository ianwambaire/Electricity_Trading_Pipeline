# First genuine forecast publication — preparation, not execution approval

Two independent operations: SETUP (no forecast) and PUBLICATION (requires fresh,
separately hash-bound data). No API/static deployment, restart, inference, model
change, database copy, Prefect schedule change or Streamlit change is required.
No remote write or publication has been executed during this preparation.

## Current evidence and hard stop

The newest inspection attempt returned SSH255/SSH_FAILURE with no report, no retry.
Do not infer its transport phase or promote any unobserved fact to PASS.
The last successful inspection at2026-11-02T12:09:19Z identified naturally scheduled
flow01a19b6f-28b3-7dd9-831b-13c16cfa9b8e (11:45 run; completed11:47:17.591858Z).
Receipt a7ac89e6-c9f2-4b5c-a788-23000023b87e passed schema v1,31 ordered features,
complete inputs,24 finite aligned targets, model identity, reciprocal hashes and
persisted-history binding. Issue09:00Z; cutoff12:00Z. It is EXPIRED and MUST NOT
be prepared/transferred/published as a current candidate. No bundle SHA is approved.

Historical receipt hashes below are identification evidence ONLY, not publication
approval or hashes to reuse for the next run:

- forecast.csv:988ad7bf3a138a9a3ae06d01bceea6758ea50f5208aeb54d85118f9d2b7a13ba
- provenance.json:c4db84421274d8cb529f29565215c793e098a89f3eb2e7d5d9ad8a4bb33ea4ba
- model.json:fc98c4dceef006b3e92bb518af341b5a5d67c9be12b3f89359b92944813d415e
- evidence.json:01910818c90234e0fcb7464d66820ce9c5351cbaa687b954f36c3af2191134d9

The next nominal natural run after that evidence was12:45UTC/15:45Nairobi on November2, under the last verified
active45 * * * * UTC schedule, concurrency1. Do not wait indefinitely, trigger it,
or assume it generated a new eligible issue. It became due during local preparation;
its current outcome has NOT been inspected after the failed SSH attempt. Select the actual completed run
and authentic receipt, not merely a COMPLETED task. Recheck actual current UTC.

## Existing tools and executable dependency closure

Exact code-only packet6470 bytes:
faeec014b4cde838fcffb3c285eef1995f38547d443162e529fa90ec7209a6b3

Exactly five regular members, no extraction of unverified tar paths:

- prepare.py:1f24db3f7ea3069a70b71939fd9e90984c4d2a63f8347c44e8a7a17c9c877d14
- publish.py:cacc6116944269bed260af5034c8e1bd4066ea126850a2a94c45c465f94a053a
- shared/__init__.py:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- shared/forecast_publication.py:264f3e33be1b2887174899473b7f955cc6fa8206ce1e0d7b0961da958eea5395
- tools-manifest.json:must exactly bind the four preceding files; packet SHA binds it.

A byte-identical private durable copy is retained under
 data/backups/private-staging-releases/forecast-publication-tools-<packet-sha>/tools.tar.gz
(root of that local directory0700, archive0400; no credentials or forecast data).
The runner binds its size/hash and retains the verified bytes. The original tools,
release manifests, deployed application and old execution packages are unchanged.
Tests use synthetic code packets and do not depend on this private archive/profile.

## One-time setup package — NEW separate review and authorization required

Files:setup_first.py,run_first_setup.py,FIRST-SETUP-MANIFEST.json and this review.
This is a narrow installer for the existing publisher, NOT a new diagnostic or
forecasting framework. It never invokes the publisher/builder or reads forecasts.
The existing approved publication diagnostic does not inspect tools installation
and deliberately cannot establish candidate-user access. Those facts currently
remain UNVERIFIED; the setup guard checks them without guessing or overwriting.

Before ANY creation, verify all manifest/source/packet/payload hashes, pinned SSH
profile/key, root-owned safe ancestors, trusted OS executable metadata, candidate
unit User/Group/state/MainPID and actual UID/GID992. Verify existing tool inventory
and bytes if present. Reject malformed/symlinked/writable/incorrectly owned paths,
existing current/other root contents, nonempty releases, tool drift or extra files.

Probe parent traversal from the candidate's MOUNT namespace with the SAME live PID,
trusted /usr/bin/python3 -I -S -B, UID/GID992 and EMPTY supplementary groups. No
candidate interpreter, application imports, startup hooks, tokens or environment
contents are used. Directory probes cannot prove bundle-file readability before
such a file exists; this remains explicitly UNVERIFIED_NO_BUNDLE.

If all guards pass, create ONLY missing paths:

- /opt/powerflow/forecast-publication-tools (root:root0700), if absent;
- /opt/powerflow/forecast-publication-tools/<packet-sha>/ and its shared/ directory
  (root:root0700), with exactly the five verified code files root:root0600;
- /srv/powerflow/forecast-publications and its releases/ directory
  (root:9920750).

Never chmod/chown/overwrite an existing path to make it pass. Existing exact tools
and empty directories may be reused after verification. Archive bytes are verified
once and retained; install individual held, allowlisted members, never tar.extract.
Use exclusive no-follow file creation, exact hashes and fsync/readback checks.
Verify root publisher write/traverse access and actual candidate directory read/
traverse but NOT write access in the candidate mount namespace. Recheck same PID.
The candidate's full cgroup/BPF/process sandbox is not inherited by this helper;
only its filesystem namespace/identity is probed. Actual API bundle acceptance
remains mandatory after publication. No claim of full service enforcement is added.

No current pointer, forecast bundle, lock file, incoming artifact, environment file,
service unit or production file is created/modified by SETUP. On failure retain
partial setup files and report BLOCKED or PARTIAL; no retry, repair or cleanup.

Future invocation, after reviewing the separately reported manifest/payload hashes:

```
venv/bin/python -I -B deploy/staging/forecast-publication/run_first_setup.py --manifest-sha256 <APPROVED_FIRST_SETUP_MANIFEST_SHA256>
```

Append --local-check for local verification only. Live command needs NEW explicit
setup authorization. One SSH attempt, strict pinned identity, sudo-n, remote60s,
local120s, TERM/KILL5s, bounded private captures131072 bytes per stream. Each fixed
metadata/namespace child is bounded8s with5s escalation. No arbitrary command/host
option. No ordinary dependency installs or service restarts.

## Fresh data preparation — currently BLOCKED, no candidate artifact

After the next successful natural inference, verify exact Prefect/task association,
committed UUID receipt, persistence, model and contract hashes, all31 finite ordered
features, raw input completeness and all24 issue-relative targets. Validate freshness
against actual UTC; do not fabricate/backdate evidence or extend the three-hour gate.

Obtain ONLY the four matching receipt files through a separately approved bounded
read-only transfer, record their exact SHA values, retain private files with safe
ownership/mode, and build locally using existing prepare.py. No production DB,
model binary or unrelated data may be copied. The receipt verifier currently emits
metadata/hashes, NOT the four file contents: this transfer is an explicit remaining
capability/authorization requirement, not an action silently performed here.

```
PYTHONPATH=src venv/bin/python -B deploy/staging/forecast-publication/prepare.py \
 --forecast "$VERIFIED_RECEIPT/forecast.csv" --forecast-sha256 "$FRESH_FORECAST_SHA" \
 --provenance "$VERIFIED_RECEIPT/provenance.json" --provenance-sha256 "$FRESH_PROVENANCE_SHA" \
 --model "$VERIFIED_RECEIPT/model.json" --model-sha256 "$FRESH_MODEL_METADATA_SHA" \
 --evidence "$VERIFIED_RECEIPT/evidence.json" --evidence-sha256 "$FRESH_EVIDENCE_SHA" \
 --out "$NEW_PRIVATE_BUNDLE"
```

All variables MUST come from the newly reviewed authentic receipt and named private
paths. No currently known expired hash is a substitute. Validate the resulting
bundle with BOTH the current deployed contract and the archived publisher contract,
record its SHA/size/issue/cutoff, and transfer only that exact bundle through a
separately reviewed bounded receiver to ONE root-owned0600 incoming file under
/srv/powerflow/forecast-publications/.incoming-<approved-bundle-sha>.json.
The incoming transfer/receiver is NOT provided by the SETUP runner and needs a
fresh hash-bound review. Do not widen that runner or invent an unsupported mode.

Do not run archived prepare.py as root directly on UID1000 receipt files: safe_file
correctly rejects that ownership. The local builder operates on privately owned
verified copies. Alternatively a separately reviewed held-bytes root snapshot
receiver could provide approved root-owned inputs; never relax safe_file ownership.

## First publication — NEW data-bound authorization required, not runnable yet

Set TOOLS to the fixed verified directory above and bind APPROVED_INCOMING_BUNDLE,
APPROVED_BUNDLE_SHA to the fresh reviewed packet. Reverify exact code/permissions
and actual source bundle hash, validity/expiry and ABSENT current immediately
before execution. No argument may be filled with an expired receipt or guessed hash.

```
sudo -n /usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/timeout --signal=TERM --kill-after=5s 30s \
 /usr/bin/python3 -S -B "$TOOLS/publish.py" publish \
 --source "$APPROVED_INCOMING_BUNDLE" --sha256 "$APPROVED_BUNDLE_SHA" --expected-current none
```

-S disables startup site hooks; env-i clears PYTHONPATH/environment; only the verified
private root-owned script directory and trusted OS stdlib supply imports. Do not
use -I with this script form: it excludes its shared package from sys.path.

The EXISTING publisher enforces expected-current CAS under its exclusive writer
lock, creates/fsyncs a private partial release, verifies hashes/expiry, renames to
releases/<bundle-sha>/bundle.json (directory root:9920750/file root:9920640), then
checks expiry immediately before atomic current replacement. No existing release
is overwritten. The incoming file, .publication.lock, releases/.partial-UUID,
releases/<sha>/bundle.json, .pointer-UUID and current are the explicitly proposed
publication write scope. No other dataset/environment/service state changes.

For publication verification note: publish.py verify itself opens/creates the writer
lock; it is NOT a strictly read-only diagnostic. It may be included in future
publication authorization, never silently used for a read-only inspection.

An independently authorized first-publication withdrawal may use existing
publish.py withdraw --sha256 <this-current-sha>. It must guard the exact current,
retain releases/withdrawn pointer evidence and cause API503 again. No automatic
rollback or cleanup is authorized by this document.

## Live acceptance after separate publication

- Candidate mount-namespace UID992 can open/hash the actual bundle (no permissions
  widened); then REAL API acceptance proves the actual service can read it.
- GET /api/forecast/next24:200, exact no-store directive,24 finite aligned predictions,
  correct frozen model, issue/completion/cutoff and no raw input-vector disclosure.
- Admin provenance pins the SAME displayed issue/completion; operation forecast
  status VALID, while frozen historical operational evidence stays labeled historical.
- React Forecast Intelligence: real prices,24 issue-relative UTC targets, correct
  model identity, explicit count of STILL FUTURE targets (not24 by default), honest
  historical comparisons. Confirm charts/tables/export match API values.
- At real expiry:API503 FORECAST_WITHHELD/no-store; React suppresses current forecast
  chart/statistics/export. Do not change host time or wait indefinitely to test it.
- Preserve seven-page historical behavior and anonymous/Admin authorization;
  Analyst-specific acceptance still requires an authorized owner session.

## Subsequent automation — PLAN ONLY; do not implement/deploy now

Reuse _run_next24h_stages in src/scheduled_pipeline.py after genuine forecast success.
next24h_forecast_task currently returns GENERATED/UNCHANGED, issue and provenance
but does NOT return forecast.attrs['inference_receipt_id']; minimally propagate that
exact committed receipt UUID. Do not confuse it with Prefect or internal pipeline IDs.
Do not discover a receipt by taking an arbitrary latest directory.

Add one named post-success publication task in the SAME existing flow. Require
GENERATED/UNCHANGED with an authentic complete receipt and independently persisted
matching output; WITHHELD/failed/incomplete tasks never publish. Run existing builder
and publisher, preserving schedule/model/feature/freshness contracts. Publication
failure is a SEPARATE operational outcome/incident, not a false successful publication
or a rewrite of the inference outcome. Record PUBLISHED/SKIPPED_EXPIRED/
SKIPPED_DUPLICATE/REJECTED_OLDER_ISSUE/FAILED through existing status/incident interfaces.

The current publisher has expected-current CAS but NO monotonic issue guard and NO
idempotent duplicate success. Add the SMALL issue comparison/duplicate guard INSIDE
its existing exclusive lock: identical bundle is no-op; same/older issue preserves
current and reports a skip; only a strictly newer fresh issue may advance current.
Handle an expired previous bundle for comparison without treating it as eligible for
reactivation. Recheck expiry immediately before switch. Test concurrent writers,
repeated runs, differing receipts for the same issue and older otherwise-fresh data.

The existing CLI requires root. Do NOT run Prefect as root or grant arbitrary sudo.
Separately review a fixed root-owned publication entrypoint restricted to the receipt
root, approved code/model hashes and staging publication root, or an equivalently
narrow privilege boundary. No competing scheduler, arbitrary paths/commands or
application imports as root. This privilege integration and automation code require
separate local implementation/tests and deployment authorization AFTER first publication.

## Local validation

Synthetic tests cover first setup/idempotent reuse, malformed hashes/inventory,
missing identity/access, UID/GID drift, symlinks/modes, existing publications,
modified/extra tool files, retained verified bytes, strict output schemas, command
timeouts, one-attempt SSH failures and sanitized capture errors. All fixtures are
local temporary directories and synthetic code packets; no live setup occurred.
The final validation command covers138 Python tests, including32 setup tests plus
existing publication/source-selection/authorization regressions. System Python3.9
syntax/module/probe compilation and local integrity checks are separate local proof.
No frontend code changed; prior live React acceptance is not rerun or overstated.
