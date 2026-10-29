# Specific source-drift resolution — R2 proposal, NOT executed

One read-only SSH inspection exited0 at 2026-10-26T13:34:50.723650+00:00. All13 files were stable through hashing, validation and full-set rehash. No snapshot, publication, account, directory, installation or service change was performed. Normal SSH/sudo audit records may be generated. Private captures: `/private/tmp/powerflow-source-drift-tmgwfmvq/`.

## Exact content drift

### data/processed/silver_electricity_market_data.csv

- Previous SHA-256: `a9c925c6cb020a467d3152d441d1a181d8ec927af2ebb9cab11eb9e1ad7de3c7`
- Current verified SHA-256: `127cb37b85ab35bd5519a12aae3ffac44d4d7ef5f9e7469f917dde972acd6330`
- Bytes: 11618469 → 11618483
- UTC mtime: `2026-10-26T12:02:14.709497+00:00` → `2026-10-26T13:02:21.444045+00:00`

### data/raw/entsoe/prices.csv

- Previous SHA-256: `776c20a0ef8135622bdb41f605eda1a0568088a5f21c7604ca96678992325cc6`
- Current verified SHA-256: `64964fe588b2cd3a0802ab9d81ce5409c8139fa5535afb85d6d5fa420c4e8df4`
- Bytes: 3224893 → 3225047
- UTC mtime: `2026-10-26T12:00:29.759048+00:00` → `2026-10-26T13:00:29.923593+00:00`

### data/raw/entsoe/load.csv

- Previous SHA-256: `1d5558249ca70d7e05f05b0045c9aa711190949c1a92a0fbe2338025669871ce`
- Current verified SHA-256: `781ce49798296d0ad58aa73a9179666bfc44a95d0a3dfbbd3b48ad59fb423859`
- Bytes: 9695097 → 9695251
- UTC mtime: `2026-10-26T12:00:50.699141+00:00` → `2026-10-26T13:00:51.893677+00:00`

### data/raw/entsoe/generation.csv

- Previous SHA-256: `bad847a7103c93521b0d55c34a094f0546a0cb02353e3601638aa0d2305c2271`
- Current verified SHA-256: `da34e965703f661b45e46abf92fcfa3fef100c54695736ce3dd8f54038b915aa`
- Bytes: 41207456 → 41208037
- UTC mtime: `2026-10-26T12:01:12.889237+00:00` → `2026-10-26T13:01:18.523780+00:00`

### data/reports/detected_anomalies.csv

- Previous SHA-256: `ea5b46f8c0aef021f7e7602a5fcc9770bceb7ec93266ef54f94e46608f2db609`
- Current verified SHA-256: `a765bcf21bd56078281cbfcec1087997b6f9429405fef597f38a50f0d5cb051b`
- Bytes: 113133 → 112875
- UTC mtime: `2026-10-26T12:02:31.539572+00:00` → `2026-10-26T13:02:39.774122+00:00`

Eight files are byte-identical. Gold and feature_importance also have newer mtimes with identical bytes. All ownership/modes match the prior approved values. The complete13-file comparison, including all prior/current hashes, sizes and mtimes, is in `../PUBLICATION-DRIFT-RESULTS.json`.

## Interpretation and consistency

Prices/load/generation gained exactly4 rows each; latest timestamps advanced one hour to12:45/11:15/12:15UTC. Silver remains68,411 rows through Oct25 21:00UTC but is14 bytes larger. Anomalies changed685→684 rows, latest event still Sep22 17:00UTC. Gold still ends Oct23 10:00UTC; one-hour predictions end Oct23 11:00UTC. These are historical/stale cutoffs, not live forecasts.

Changes align with the13:00–13:02 hourly production update pattern. Local `src/scheduled_pipeline.py` runs Silver build and anomaly detection; `src/models/anomaly_detection.py` refits IsolationForest(contamination0.01, seed42) and rewrites its report, so reclassification is plausible. **This is an inference:** prior source bytes are not retained, production execution logs were not accessed, and exact Silver value changes/anomaly membership differences were not reproduced. No unexpected metadata, invalid timestamps or sensitivity-header/key flags were found; that is not a full value/security audit.

A1 is unchanged: SHA21fcb0e920ffaf13f214e39720e1176e012086d6ffa7b8a7ed736b6e4ab79690,12,115,968bytes. Read-only immutable connection: full integrity_check=ok, zero foreign-key violations, required tables/counts891/16525/1485/11561 pass, no WAL/SHM/journal. Live SQLite was not opened. Historical A1 cutoff remains02:22UTC.

An immutable staging byte snapshot can be created with the existing exclusive atomic publisher, provided the proposed exact hashes are accepted and remain stable at execution. All13 hashes are checked before copying, immediately before each copy and across the entire set afterward. This provides an exact stable publication set, **not proof of one simultaneous producer transaction**. Differing source cutoffs are recorded; no cross-file ML forecast is enabled. A stable copy may occur between scheduled updates; any further drift still aborts. No producer stop, locks, backup or source modification is proposed.

## Minimal local changes / next authorization

The original approved bundle/manifest is retained. R2 changes five source hashes/sizes and freshness/provenance from verified read-only observations; source set, immutable68-file application release, wheels, systemd, Nginx, publisher and resource/security checks are unchanged. The only remotely executed code change is the incoming directory suffix `-r2` in bootstrap/installer; the local runner uses the same suffix. This preserves the previously transferred directory rather than overwriting it. Builder accepts an explicit observation report. Targeted tests assert the source set, permission/stability/SQLite validation and that no other installer behavior changed.

- New private incoming path requiring approval: `/home/ec2-user/powerflow-staging-incoming-phase-staging-https-ready-20261026-r2/`.
- Backend/static release ID, publication, unit/env, control/audit and all other destinations stay as originally reviewed. No data paths or privilege scope are expanded.
- R2 local bundle: `/private/tmp/powerflow-install-bundle-ojjp9f0y`.
- R2 bundle SHA-256: `1a716274b69348a204cbc2300400b65a4485d33505ea4518c4bf7df4d5e815d8`.
- R2 local runner SHA-256: `89c9621ff8cce664fc5f59993c4ae7f60bd74ac38b6bf99c87aeca8aab43ddd4`.
- R2 bootstrap SHA-256: `f5150eccae5247c57efd4a16a42c769e5ac7a0e552ab408e4ab6d4a6854f1445`.
- Full artifact/source hashes: `BUNDLE-MANIFEST-R2.json`, `BUILD-RESULTS-R2.json`.
- Publication source bytes:102,895,837 (+645). Capacity gate:3,752,865,508bytes free minimum; memory gate768MiB. Not remeasured by this source-only inspection; must pass during installation.

**Requested next authorization:** one execution of R2 transfer→install→activate with the five proposed source changes and the single new private incoming path above, using all original hard stops and preservation boundaries. No automatic retry, hash refresh, security relaxation, Cognito change or cleanup. Cognito remains separately authorized. Further source drift requires another stop.

## Exact proposed launcher (do NOT run until authorized)

Use actions `transfer`, `install`, `activate` sequentially, stopping after any nonzero result. Each is a separate invocation of the unchanged bounded wrapper mechanism; use the following launcher, changing only the action argument. No action ran while preparing R2.

```sh
python3 -I -B - transfer <<'PY'
import hashlib,pathlib,runpy,sys
p=pathlib.Path('/Users/iannganga/Desktop/electricity-trading-pipeline/deploy/staging/install-package/execute-approved.py')
assert hashlib.sha256(p.read_bytes()).hexdigest()=='89c9621ff8cce664fc5f59993c4ae7f60bd74ac38b6bf99c87aeca8aab43ddd4'
action=sys.argv[1]; sys.argv=[str(p),action,'--bundle','/private/tmp/powerflow-install-bundle-ojjp9f0y','--sha256','1a716274b69348a204cbc2300400b65a4485d33505ea4518c4bf7df4d5e815d8']
runpy.run_path(str(p),run_name='__main__')
PY
```

Local validation:47 targeted tests passed (10 new drift tests,14 installation tests and existing execution/preflight tests); one existing AnyIO deprecation warning. Diagnostic hash/source-scope checks, CSV fixtures, syntax and R2 artifact verification passed. No dependency reinstall or frontend rebuild was needed. No remote mutation or Git operation ran.
