# A03 parser correction and two-quarter historical recovery

LOCAL PREPARATION ONLY. No remote commands or source acquisition have run.

## Scope and evidence

The old parser ignores TimeSeries/curveType and emits only explicit positions.
A03 positions are block starts: each value applies up to the next position or
period end, at the declared resolution. No interpolation or cross-period filling
is permitted. Missing curveType retains legacy explicit A01 semantics. Missing
A01 points remain missing and fail existing hourly completeness checks.

The production inspection at 2026-10-31 14:20 UTC found 93 explicit A03 positions
covering 96 quarters, including omitted block starts at 11:45 and 12:15 UTC on
2026-10-24. This package allows adding ONLY those two timestamps. It does not
assume that any other historical gap has this cause. LOCAL-AUDIT.json records
why the local historical CSV cannot establish the broader production extent.

## Reviewed code

Only production code change: src/ingestion/fetch_entsoe_data.py. No dependency,
model, feature contract, schedule, freshness or transformation changes.
Parser diagnostics report declared/decoded coverage, A03 block expansion and
missing A01 points. Existing forecasting errors continue to distinguish missing
feature windows; malformed XML/blocks raise ValueError rather than fabricated data.

MANIFEST.json binds each local artifact and the last verified production parser
hash. That baseline is historical evidence, not a claim of current remote state.
Verify every hash locally before transferring any approved payload. No credentials,
XML response, production CSV, backup or database is included in this package.

## Execution boundaries requiring separate approval

1. One bounded read-only preflight + one authenticated ENTSO-E A44/DE-LU request
   for 2026-10-24T11:00Z through 13:00Z. ENTSO-E can return the full market-day
   period; decode the full period then restrict to these two hours. Authenticate
   through the existing secret mechanism; never put keys in argv/logs or persist
   credential-bearing URLs. Verify TLS, no redirects/retries, request timeout
   5/20 seconds and total 60 seconds; cap XML at 2 MB. Record response SHA-256.
2. Guarded parser-only installation, with a private original-file backup and
   exclusive new candidate file, fsync, hash verification and atomic os.replace.
3. Offline dry-run and candidate creation, followed by separately approved atomic
   replacement of prices.csv ONLY after reviewing exact additions and hashes.
   May be grouped with step 2 after the fresh dry-run has explicit approval.

These are preparation instructions, not authorization to execute. Do not use
historical ingestion mode: it could overwrite unrelated source history.

## Mandatory remote preflight before ANY writes

- Verify account/host/strict known-host identity, current parser baseline and all
  package hashes. Abort drift; do not update approved hashes automatically.
- No active Prefect flow/task or ingestion/forecast process; verify :45 schedule,
  concurrency 1 and enough idle time. Check again immediately before replacement.
  STOP if scheduler could start during the window. External writer exclusion is
  mandatory: the repair tool does not lock out the scheduled pipeline.
- Source prices.csv must be a regular non-symlink file, expected owner/group/mode;
  record SHA, inode, bytes, mtime and source schema; record database/service/routing
  preservation baselines without reading secrets.
- >=768 MiB available RAM and >=2 GiB free AFTER backups/candidate files; inspect
  swap and abort unexpected pressure. Max source size 32 MiB for offline tool.
- Private approved recovery directory absent, parent real and safely owned.
  Source hash must remain identical through candidate preparation and install.
- Read-only source audit and captured XML must show complete eight-quarter window,
  exact agreement with all existing overlapping prices AND source_resolution.
  Abort revisions/conflicts, malformed/partial A01 or A03, unexpected missing slots.

## Exact offline preparation commands (future approved private paths)

Run from /home/ec2-user/Electricity_Trading_Pipeline with the corrected parser
installed, or in a separately approved isolated repository copy with that parser.
Keep the package at deploy/staging/a03-price-recovery/ so its repository-relative
imports resolve correctly; do not relocate repair.py on its own. These
commands are NOT executed by this local task. SOURCE_SHA and XML_SHA must be
actual verified hashes approved after preflight, never placeholders in execution.

```sh
.venv-prod/bin/python -B deploy/staging/a03-price-recovery/repair.py \
  --source data/raw/entsoe/prices.csv --xml /APPROVED-PRIVATE/response.xml \
  --source-sha256 "$SOURCE_SHA" --xml-sha256 "$XML_SHA"
```

Default is dry-run: prints metadata/counts/hashes only, no files or source writes.
After approving exact report, use the same command plus:

```sh
--output /APPROVED-PRIVATE/new-repair-candidate
```

Output directory must not exist; mode 0700, files 0600. original.csv is the exact
source-byte backup; candidate.csv preserves every existing source byte and appends
only missing allowlisted quarters; report.json binds original/XML/candidate hashes.
No-op is byte-identical when already repaired. No source CSV is ever replaced by
the tool. It creates no journals, database backups, checkpoints or pipeline outputs.

## Atomic installation protocol (must be hash-bound in execution approval)

A production execution runner is intentionally NOT included: fresh source/XML
hashes and approved private paths are still unknown. Before approval, bind these
into the runner and review it; do not improvise shell cp/mv commands on EC2.

For each parser/CSV replacement: verify no writers and baseline again; exclusively
create same-filesystem sibling temporary file, preserve expected owner/group/mode,
write approved bytes, fsync, hash-check, recheck original inode/hash/mtime and
no-overlap, os.replace once, fsync parent, verify installed SHA and semantic diff.
Never replace CSV if source drifted after preparation. Avoid cross-filesystem mv.
Parser and CSV require independent verified originals; no automatic rollback.
Preserve all partial artifacts on failure and report exact stage. Do not restart
services, rebuild Silver/Gold, change pointers, or invoke ingestion/forecasting.

## Rollback

Separately authorize rollback. Parser rollback restores only the exact verified
original source bytes atomically with same checks. CSV rollback is permitted ONLY
if installed SHA is still exactly the candidate SHA and no writer has run; restore
original.csv atomically. If scheduled ingestion advanced the CSV, STOP: full-file
rollback could lose genuine new observations. Prepare a narrow reviewed reverse
merge instead. Never delete backups/partial artifacts without separate approval.

## Post-change acceptance

- Installed parser and repaired CSV match approved hashes; exactly two additions,
  no existing observation/value/resolution changed; original backups verify.
- clean_prices and existing feature helper now provide price_lag_168h at
  2026-10-31 11:00 and 12:00 UTC using the corrected historical observations.
- Preserve services, routing, database identities, schedule/concurrency.
- Observe the NEXT NATURAL :45 run without triggering it. Confirm actual returned
  forecast outcome, current completeness and three-hour freshness, 24 finite hourly
  targets, authentic schema-v1 31-feature receipt, correct internal/Prefect run
  association and all reciprocal hashes. Full publication validation uses actual
  current UTC; do not call an expired forecast valid.
- A successful historical repair does not guarantee all current load/weather/etc.
  gates pass. Staging publication is a distinct later authorization.
