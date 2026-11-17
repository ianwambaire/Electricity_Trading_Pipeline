# Parser-only production hotfix — preparation, NOT deployed

## Fixed scope and evidence

Only deploy `/home/ec2-user/Electricity_Trading_Pipeline/src/ingestion/fetch_entsoe_data.py`.
Original verified baseline hash: ee1d225895fbf929127a577ca4f85a6855643186a7590cda5eaa27ac6aa21a2a.
Replacement hash: 8800f34a2d0e3db4056e921a7b6629847402f37c20ff9b3e81d50f3c1d77865f.
The corrected source already exists; no parser is rewritten here. Git baseline
cb256bd exactly reconstructs the previously verified production hash. AST comparison
proves the rest of the module is unchanged: only parse_price_observations,
query_price_observations and import math differ. The query keeps day-ahead contract
A01/sequence1 and DE_LU; diagnostic output reports curve coverage. A03 positions are
block starts; A01 remains explicit-point data. Invalid/overlapping/ambiguous periods
still fail closed. No interpolation, feature/model or freshness changes.

November2 read-only production inspection established that the deployed parser
DIFFERS from corrected local source; it did not measure the old full hash anew.
Therefore ee1d... is a historical baseline, NOT a fresh assertion. Apply independently
requires that exact full-file hash, owner/group1000 and0644 on the actual host.
Any drift stops without backup creation or replacement; no hash refresh is allowed.
The original October24 recovery directory, its private final package and prior
rollback evidence are neither dependencies nor write targets of this package.

## Exact future execution — separate explicit authorization

Transaction: 932c5f6e758b42ecb9ee6363c2611440
New private control path:
/var/lib/powerflow-staging/a03-parser-hotfix/932c5f6e758b42ecb9ee6363c2611440/

```sh
venv/bin/python -I -B deploy/staging/a03-parser-hotfix/run.py apply   --manifest-sha256 APPROVED_MANIFEST_SHA256
```

Read-only LOCAL verification: append --local-check. There is no inspect mode,
remote command override, source override, transaction override or automatic retry.
A manifest hash, exact dependency inventory, size/hash of every artifact, source hash
and assembled payload hash are verified before SSH. The existing retained SSH
wrapper verifies private profile/target/key permissions and pinned known-host bytes;
-F/dev/null, BatchMode, IdentitiesOnly, strict host verification, ConnectionAttempts1,
ConnectTimeout10. Both actions use one fixed sudo-n system-Python -I-S-B stdin
invocation: remote120s, local180s, TERM/KILL5s, each capture<=131072 bytes. No production
venv startup, application/native-package import or credential read is used by this job.
Verified executable/source bytes remain in memory; nothing is reopened for execution.

## Mandatory live gates and ordered changes

1. Verify target real-file/ancestry/owner/group/mode, exact old source hash, corrected
   source hash and syntax, unused transaction path and safe private backup parent.
2. Existing pipeline guard must PASS: exact deployment identity/single enabled
   45 * * * * UTC schedule/concurrency1/original collision setting, zero active flows,
   zero ingestion/engine processes and occupied slots; STRICTLY more than600 seconds
   before nominal and every returned scheduled execution. No producer is paused.
3. Require MemAvailable>=768MiB and at least2GiB plus temporary source headroom on
   source/control filesystems. Swap is measured, not used to invent a new threshold.
4. Fingerprint existing service identities (including staging), routing/TLS/candidate
   unit, published reports, production raw/Silver/Gold sources, forecasts, operational
   DB and both frozen HGB binaries. Require service active/running and frozen hashes.
   These are read-only hashes, not database connections or private-key reads.
5. Create only a missing root:root0700 hotfix parent, unique root:root0700 transaction,
   original.py and state.json root:root0600. Fsync/hash/read back backup and state
   BEFORE changing the source. No historical record can be overwritten.
6. Repeat capacity, idle/window, preservation, exact old source and metadata checks.
   Write/fsync an EXCLUSIVE sibling `.powerflow-a03-parser-932c5f6e758b42ecb9ee6363c2611440` under
   src/ingestion; preserve1000:1000/0644; recheck old source immediately before atomic
   os.replace. Only that source path changes. Fsync its directory. No cleanup/retry.
7. Verify installed exact hash/metadata and compile source without executing/importing
   it or writing bytecode. Verify backup, production fingerprints, scheduling/idle and
   post-change resources; persist APPLIED in the NEW record. No service restart,
   ingestion, inference, CSV repair, forecast publication, AWS or Nginx operation.

Do NOT install while a flow is active: an old process may already hold imported
function objects. A quiet slot before a naturally scheduled fresh flow process is
required; its actual subsequent results must establish use of corrected decoding.
This is a guarded point-in-time check, not a lock against an unapproved manual launch.
No downtime/restart is required by this one-file change. Do not run two maintenance
or manual pipeline operations concurrently. A gate failure is not permission to repair.

## Independent rollback — NEVER automatic

```sh
venv/bin/python -I -B deploy/staging/a03-parser-hotfix/run.py rollback   --manifest-sha256 APPROVED_MANIFEST_SHA256
```

Separate authorization required. Fixed transaction only; verify record schema,
identity and installed/backup hashes, root-private metadata, unchanged preservation,
capacity and idle/window. Require live source still equals corrected hash, then
atomically restore original bytes with1000:1000/0644, verify restoration and preservation,
and mark ROLLED_BACK. Never restore datasets, forecasts, models, environments or
services. Retain all backups/records/partial files. Pipeline activity or data drift
can block rollback; no override. A timeout is UNKNOWN until separately inspected.
PARTIAL/source_may_have_changed is conservative; do not infer rollback is needed
merely because a private backup directory was created. No rollback after an untouched
preflight failure. Restoring old code reintroduces the A03 defect; it does NOT undo
later scheduled data inserts. Any such data recovery is a separate operation.

## Protecting the48-hour source overlap

Known source gap:2026-11-01T17:15Z; authentic A03 block17:00..17:30=300.44EUR/MWh.
Private genuine-response SHA256:
bf5066783811700ab0db7bab07afca4c363005220372cbb32f7cbefb7c536ec0.
The response contains multiple sequences. Use ONLY day-ahead sequence1, as the
existing query does; never combine overlapping sequence1/2 curves or change geography.

Incremental price retrieval starts at latest_stored_price.floor(h)-48hours.
The gap stays covered while that anchor is<=2026-11-03T17:00Z. At an anchor of
November3 18:00 or later the gap is outside the default overlap. This depends on
actual stored watermark, not simply wall time. The observed November2 08:45 watermark
and the next normal incremental run retain ample overlap. No backfill is authorized.

Normal ingestion is sufficient ONLY IF corrected code is loaded, provider/credentials
work, that overlap contains17:15, source overlap comparisons/validation pass and the
pipeline persists the recovered quarter. Verify it, not just a COMPLETED task state.

If the overlap is lost: prepare a SEPARATE hash-bound one-hour recovery17:00..18:00Z.
Use authenticated original XML (or reverify revised XML), exact sequence1, PT15M and
all four quarter boundaries. Bind a fresh production CSV snapshot hash/backup; require
existing17:00/17:30/17:45 values agree, allow insertion ONLY of missing17:15=300.44,
preserve every existing record byte/order, dry-run, verify idempotence, capacity,
non-overlap, atomic install and independent rollback. Do not execute or repurpose the
October24 repair (its allowlist and hashes are different). That future repair needs
its own fresh source hash and authorization; this package contains NO dataset writer.

## Naturally scheduled HGB acceptance — separate read-only verification

Verify the next completed :45 flow and actual returned forecast outcome. Check:
- Nov1 17:15 source-resolutionPT15M and value supported by the authenticated block;
  all required complete price hourly windows, not just max(timestamp).
- Complete load/generation quarters for an eligible issue, including biomass.
  At November2 10:25 the latest complete load/generation hour was07:00 and08:00
  remained incomplete. An upstream load read timed out; no upstream cause is proven.
- All31 ordered finite features; price lags1/24/168, rolling24 mean/sample std,
  load lags1/24/rolling24, current generation and issue-hour operational weather.
- Actual UTC issue age<=3hours; correct frozen model/contract hashes;24 unique
  horizon1..24 UTC target times and finite EUR/MWh predictions. No retraining.
- A complete authentic schema-v1 receipt from that exact inference UUID, actual
  scheduled/internal-run association (never assume Prefect UUID equality), reciprocal
  evidence/provenance/output hashes and publication contract at ACTUAL UTC time.
A COMPLETED task may validly return WITHHELD. Parser success does not establish
fresh load/generation or a valid forecast. Never publish an expired receipt.

## Independent React completion

Existing transaction08c3e397c7764dc1a69c6c9692ec5c09/manifest
77ce07eec1a4ed6107940ebdf65068a2545af6cf7b9ff6aabb9cda307e1869c1
remains separate and unchanged; prior timing blocks did not mutate it. Authorize one
reactivation in a freshly idle >600s window, with its reviewed conditional rollback.
Then accept seven pages/API and owner-assisted native Analyst/Google Admin sign-in,
callback/logout, anonymous401/Analyst403/Admin state-dependent provenance.

Follow-up phase-hgb-integration-20261102-v1 is privately preserved and sealed;
manifest66af5a65c48bebcbe27d2c4b692900384b16a0dcd23859620a137e278d1a81fa.
All26 backend files equal the original release; review a minimal static-only update
for37 static files, preserving old assets/independent pointer rollback, without an
extra API restart. No follow-up deployment is authorized here.

Missing overlay is expected503/FORECAST_WITHHELD/no-store, MISSING_PUBLICATION,
never historical fallback. Separately approve publisher/root/group992 access and
fresh verified receipt transfer/four-file bundle preparation. Then separately approve
atomic current->releases/<bundle-hash>/bundle.json publication and verify24 real HGB
predictions, issue/completion/expiry, matching provenance, operations and seven pages.
The API never trains/runs HGB. Root creation/publication and source-code/static
rollback are independent boundaries; no bundled cutover or Streamlit retirement.
