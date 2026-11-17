# Publication preflight — observed read-only findings

Inspection UTC: `2026-10-26T12:28:44.413207+00:00`. One SSH invocation, exit0, no errors/retries. No remote files created/copied/published; no services/configuration changed. Original source inventory remains a LOCAL baseline; observed remote hashes below are not a copy authorization.

## Exact source inventory

Sources relative to `/home/ec2-user/Electricity_Trading_Pipeline`; destinations retain the same relative paths under `/srv/powerflow/published`. All12 files were regular, nonsymlink, UID/GID1000, readable to the root inspector, and stable during individual hash/summary reads.

| Relative path | Bytes | Mode | SHA256 | Latest observed UTC / note |
|---|---:|---|---|---|
| `data/processed/silver_electricity_market_data.csv` | 11618469 | 0o644 | `a9c925c6cb020a467d3152d441d1a181d8ec927af2ebb9cab11eb9e1ad7de3c7` | 2026-10-25T21:00:00+00:00 |
| `data/features/gold_model_features.csv` | 20934928 | 0o644 | `c12a041a1d40c47e81e434479e09a99130e8b950a1f7e3ea08d1dfed3448f53f` | 2026-10-23T10:00:00+00:00 |
| `data/raw/entsoe/prices.csv` | 3224893 | 0o600 | `776c20a0ef8135622bdb41f605eda1a0568088a5f21c7604ca96678992325cc6` | 2026-10-26T11:45:00+00:00 |
| `data/raw/entsoe/load.csv` | 9695097 | 0o600 | `1d5558249ca70d7e05f05b0045c9aa711190949c1a92a0fbe2338025669871ce` | 2026-10-26T10:15:00+00:00 |
| `data/raw/entsoe/generation.csv` | 41207456 | 0o600 | `bad847a7103c93521b0d55c34a094f0546a0cb02353e3601638aa0d2305c2271` | 2026-10-26T11:15:00+00:00 |
| `data/raw/weather/open_meteo_weather.csv` | 3170780 | 0o600 | `996b48c8085240cd505105688e75757d29f7f9e2ebd1acda7b2772724974c039` | 2026-10-25T23:00:00+00:00 |
| `data/reports/actual_vs_predicted.csv` | 806734 | 0o600 | `aa2a197537fce4fcc853093c3b8ace5e5e570ab8018f09ab1733b834883cf488` | 2026-10-23T11:00:00+00:00 |
| `data/reports/detected_anomalies.csv` | 113133 | 0o644 | `ea5b46f8c0aef021f7e7602a5fcc9770bceb7ec93266ef54f94e46608f2db609` | 2026-09-22T17:00:00+00:00 (latest event, NOT coverage cutoff) |
| `data/reports/final_holdout_metrics.csv` | 540 | 0o644 | `60c1830414df97f68c6a2de67c242305427014d5049bc2945bbd8f29e545d0ba` | not a time-series report |
| `data/reports/feature_importance.csv` | 1671 | 0o644 | `935e00ee045f485e607fd0429816747757ad4885d046d8e6bc062361c70fe466` | not a time-series report |
| `artifacts/models/final_model_release_manifest.json` | 2749 | 0o644 | `64939ce5317b5aa6cffb169e1f8b9bbc7304508c496b9bcc71d701bfeb2e7dd6` | not a time-series report |
| `artifacts/models/releases/next24h/next24h_release_manifest.json` | 2774 | 0o644 | `1b2d4ce56f178bc236de1bb93d4ce30a09f990d9116dadaa609f86c708131650` | not a time-series report |

Eight production hashes differ from the original local inventory; four frozen metadata/metrics/coefficient files match. No source was missing. Do not deploy Mac copies as current production data. Hash observations do NOT prove a coherent cross-file snapshot; a publication operation must recheck an approved consistent source set and fail if inputs change.

## Freshness and sensitivity

At inspection, raw prices/load/generation were approximately0.73/2.23/1.23hours behind the server clock; Silver15.48hours, Gold74.48hours, weather13.48hours. One-hour predictions ended2026-10-23T11:00UTC (~73.48hours old): historical, not live. Silver/Gold lag newer raw data. No pipeline validation/training or withholding rules were altered.

The anomaly report was regenerated today and contains685 events; the newest event is2026-09-22. This does not prove the detector input coverage is stale: event timestamps are not observation coverage. Frozen model/evaluation metadata is historical by design.

Bounded header/key/path checks found no obvious sensitive indicators in the12 sources; this is NOT a complete secrets/PII audit. Operational SQLite may contain sensitive messages/incidents and remains private. Raw files/manifests must never be served as static assets. Current raw/forecast sources0600 are not directly readable by a future different service UID; publish controlled copies with root:powerflow-api directories0750/files0640 rather than changing production permissions. No candidate-user accessibility was tested.

## SQLite

The existing A1 snapshot is12,115,968bytes, UID/GID1000,0600; SHA256 `21fcb0e920ffaf13f214e39720e1176e012086d6ffa7b8a7ed736b6e4ab79690` matches. After checking no WAL/SHM/journal sidecars, the standalone validated image was queried via `mode=ro&immutable=1`, query_only, one read transaction. Required schema probes passed; counts891/16525/1485/11561 match A1. File metadata unchanged and no sidecars created. No database records/messages were printed. No new backup or integrity-repair command was run.

The snapshot was captured2026-10-26T02:22UTC; it is historical operational state, older than the current market files. Live DB exists (13,651,968bytes), with no sidecars visible at the instant checked. No live DB connection was opened: sidecar absence alone does not ensure an active database remains safe/consistent to read without SHM interactions. A fresh operational snapshot needs separate write/backup authorization.

## Destination and capacity

Destination `/srv/powerflow/published` and its `/srv/powerflow` parent are absent; `/srv` is root-owned0755, not a symlink. No existing publication content conflicts. This is an observation, not installation permission.

Observed source footprint including A1: **102,895,192bytes (98.13MiB)**. Available disk **12,772,130,816bytes (11.895GiB)**; guard requiring publication + measured venv207,724,544bytes + wheelhouse38,371,328bytes +1GiB extra workspace +2GiB reserve totals**3,570,216,536bytes (3.325GiB)** and passes. MemAvailable**968,044,544bytes (923.20MiB)** exceeds768MiB. These are snapshots, not a capacity reservation or peak-RSS proof. Recheck immediately before any install/start.

## Interpreter and ProtectHome

EC2 CPython3.14.7, ABI `cpython-314-x86_64-linux-gnu`, glibc2.34. Actual base executable `/usr/bin/python3.14`, prefix `/usr`, stdlib `/usr/lib64/python3.14`; all outside `/home`, `/root`, `/run/user`, with publicly traversable/readable mode bits. The production venv path under `/home` must NOT be used by the sandboxed candidate; create the new venv at its final `/opt` path using the verified `/usr/bin/python3.14`. No existing Python/venv changed. ACLs, service-user execution and effective systemd sandbox enforcement remain untested.

Linux test image glibc2.36 differs from EC2 glibc2.34. Local wheel-tag review: cffi floor2.17, cryptography2.34, numpy2.27, pandas2.24, pydantic-core2.17. All tagged floors are <=observed EC2glibc2.34. This resolves the obvious wheel-tag floor concern, not actual installed-library/import testing on Amazon Linux.

## Next authorization boundary

Prepare and separately approve a hash-bound publication execution package: exact12 observed sources + existing A1 image (explicitly accept historical operational cutoff), exclusive private destination, consistent-source protocol/rechecks, root-owned restricted copies, full manifest verification, no production permission changes, no live DB/WAL copy. This inspection does not authorize that operation. If current operational state is required instead, obtain separate approval for a fresh consistent SQLite backup first. No silent replacement with live data.

Candidate runtime installation, account/group creation, systemd/unit enforcement, Cognito staging URLs, Nginx activation and real-account acceptance remain separate approved gates. Next read-only host inspection is not automatically authorized.

Private captures: `/var/folders/1j/fq1jzz6d5vv_y1xqd8z5lvb40000gn/T/powerflow-publication-preflight-bnuzb84b`. Local payload safety tests:4 passed; no Git operations.

## Publication execution request — stopped before remote execution

Owner explicitly accepts the existing A1 operational snapshot from2026-10-26 02:22UTC as HISTORICAL staging data. No fresh operational snapshot is requested. The12 observed source hashes and A1 hash remain the only permitted source set.

Local review found no reviewed production hash-bound atomic publisher implementation. `publication-preflight-readonly.py` cannot publish; `scripts/prepare_preflight_data.py` is local-only, includes additional files and is not a substitute. The last verified candidate identity `powerflow-api` was absent; this request does not authorize its creation. The publication parent was also absent at last inspection, so any parent/scratch path writes must be explicitly covered by the eventual implementation.

Per the owner's instruction to stop if a new script/identity/additional privileges are required, no publication SSH session was opened, no new publisher was written, and no remote directories, copies or permissions were changed. Next review must cover a concrete hash-bound publisher and the minimum non-login candidate identity/group setup (or verification of an independently created approved identity), including exact filesystem boundaries and final candidate-access/atomicity checks. No automatic source-hash refresh or broadening is allowed.
