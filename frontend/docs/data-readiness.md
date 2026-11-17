# Phase 3: local data readiness and public read APIs

This investigation uses this checkout only. No production service, AWS object, configuration or model was accessed or changed.

## Why the existing routes return 404

These are implemented routes, not router or `/api` proxy failures. `APISettings.from_root()` resolves paths relative to the repository, not the shell working directory. The read-only API deliberately does not load `.env`.

| Public URL | Local report expected | Writer | Local finding |
| --- | --- | --- | --- |
| `/api/forecast/next24` | `data/reports/next24h_forecast.csv` | `models.next24h_production.run_next24h_forecast()` → `save_forecast()` | File absent; `_read_csv_rows()` returns 404. No claim of a current local forecast is possible. |
| `/api/monitoring/forecast-vintages` | `data/reports/monitoring/forecast_vintage_health.json` | `monitoring.forecast_vintage_health.write_forecast_vintage_health_report()` through `scheduled_pipeline.forecast_vintage_health_task()` | File absent; `_read_json_report()` returns 404. |
| `/api/monitoring/exogenous-readiness` | `data/reports/monitoring/next24h_exogenous_silver_quality.json` | Offline `processing.build_next24h_exogenous_silver.build_next24h_exogenous_silver()` | File absent; `_read_json_report()` returns 404. This offline builder is not invoked by the scheduled flow. |

Malformed/unreadable report contents return 503. Missing or empty one-hour reports also have documented 404 conditions. Missing next24h report data alone does **not** establish a WITHHELD status: that is a separate pipeline metadata field.

Current local Silver has 67,486 hourly rows from 2019-01-01 00:00 UTC to 2026-09-12 21:00 UTC. Gold has 67,317 feature rows, through 2026-09-12 20:00 UTC. The legacy SQLite market tables are not the authoritative DE-LU dataset: `database/schema.sql` assigns the primary database to operational metadata. The new API uses the same Silver source as Streamlit Market Intelligence. It does not change Silver, Gold, or pipeline validation.

## Legitimate ways to obtain local reports

No report-generation commands were executed in this phase.

1. **next24h:** use an approved existing local evidence/backup bundle containing authentic latest/history/provenance files, preserving timestamps and release identifiers. Treat old targets as historical. Alternatively, when genuine complete recent market observations and operational weather are available, the existing inference command `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./venv/bin/python -B -m models.next24h_production` can produce a report under the existing release and freshness gates. That command requests weather and writes local reports; it is an optional future action, not part of serving this API. This September checkout cannot generate a fresh October forecast. Do not use stale overrides, zero-filled Biomass, candidate example CSVs, or fabricated reports.
2. **vintage health:** an actual monitoring assessment can be generated locally from the files that exist (and should report failed/missing sources when those files are absent). From the repository root, the existing writer can be invoked explicitly:

   ```sh
   PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./venv/bin/python -B -c 'from pathlib import Path; from monitoring.forecast_vintage_health import write_forecast_vintage_health_report; write_forecast_vintage_health_report(project_root=Path.cwd())'
   ```

   This writes a real assessment, not synthetic collection evidence. It does not fetch missing vintages. Accurate collection-cycle context requires genuine collection records.
3. **exogenous readiness:** this requires observed Silver and all genuine prospective ENTSO-E load, wind/solar, total-generation, and operational-weather vintage files. The expected load and weather files are absent locally. Once legitimate inputs are provided, run `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./venv/bin/python -B -m processing.build_next24h_exogenous_silver`. Its isolated dataset and quality report do not promote or replace the production model. Missing required source files currently cause the builder to fail, not create successful readiness evidence.

Use an approved export/backup supplied for local development if needed. This phase neither connects to production nor downloads from AWS. A historical report can support a historical demo, never a current-availability claim.

## New public read endpoints

Backend URLs below are unprefixed; Vite's existing `/api` proxy strips the public prefix.

- `GET /market/coverage`: source label, DE-LU area, hourly resolution, exact row count, first/latest stored observation, missing hours within the stored span, and opaque snapshot identifier. An empty existing dataset returns zero rows and null timestamps; a missing file returns 404.
- `GET /market/history?start=<timezone-aware-ISO>&end=<timezone-aware-ISO>&limit=1000&offset=0`: ascending exact hourly observations, prices (EUR/MWh), load/generation (MW), derived selected-source renewable generation/share, full coverage and pagination. Bounds are inclusive. Default is latest observation minus seven days through latest observation, so an inclusive complete range contains 169 points. Limits are 1–2,000 rows, offsets 0–2,000,000, date filters 1970–2100 and ranges at most 366 days. Empty ranges return 200 with no observations. Invalid filters return 422. Invalid/unreadable source snapshots return sanitized 503.
- `GET /models/summary`: exactly two public model slots, independently marked metadata available/missing/invalid. Returns actual names, recorded versions (null if absent), release kinds, horizons, feature count, metadata creation time, provenance/fingerprint, artifact availability, and release-specific metrics/periods. Invalid or conflicting metadata yields no metrics for that slot. No model artifact is deserialized and no inference is performed.

## Data access and semantics

`api.market_data.MarketStore` streams a CSV once per `(mtime_ns, size)` version into an indexed **in-memory** SQLite snapshot. Subsequent queries use a timestamp index and SQL limits; no disk database, migration or dataset rewrite is performed. A lock serializes rebuild/query access per application instance; a changed invalid source is rejected rather than serving an older cached snapshot. File version is checked before/after building. Source caps are 512 MiB and two million rows; larger datasets require a future storage design. This is a single-process read cache, not a distributed scalability claim.

Price/load/generation values are copied from Silver. The selected renewable sum matches the documented Gold feature formula: solar + total wind + Biomass + run-of-river hydro. The denominator adds lignite, gas, hard coal and nuclear. Offshore/onshore wind are not added again on top of total wind. This is not a claim of complete national generation coverage. Unlike helper paths that zero-fill missing nuclear values, this public observation API leaves any missing component null and does not impute generation or alter source-validation rules. Nonfinite observations, duplicate or unordered timestamps fail closed.

Charts show the returned page only, preserve missing values and break lines across missing hours. Exact values are available in an HTML table. Pagination does not downsample or average away spikes. Date filtering/pagination were checked against real local observations (including 1,512 matching rows paged as 1,000 + 512).

## Model evidence

- Production next24h: Histogram Gradient Boosting, `next24h-hgb-2026-09-21-v1`, h+1…h+24. Test MAE 31.119582687156257, RMSE 44.18332312010295, R² 0.5894226492568126; 77,136 issue–horizon pairs. Validation/test starts are issue-time boundaries; the manifest does not record evaluation end timestamps, which remain null. Next24h artifact and feature-contract SHA-256 values are checked, with hash results cached by file version.
- Separate one-hour release: Ordinary Linear Regression, `final_2025_holdout_evaluation`; no explicit version ID is recorded. Holdout MAE 10.786919023250146, RMSE 18.88568551202895, R² 0.8794442554637898, 6,552 target hours between 2025-01-01 00:00 UTC and 2025-09-30 23:00 UTC. Manifest metrics and period are checked against the persisted final-holdout CSV when present. Model/feature artifact presence is reported without claiming integrity verification because this manifest lacks artifact hashes.
- Metrics are not a comparison across equal tasks/periods. The linear coefficient-importance CSV belongs only to the one-hour model. It is not exposed as HGB feature importance. Artifact availability is not forecast availability.

## Safety and validation

The new schemas expose only market observations and public model summaries. Paths, credentials, environment settings, raw logs, Git/MLflow IDs and unrecognized manifest fields are omitted by construction. There are no write/admin endpoints or new authentication behavior. Existing endpoints and deployment configuration remain unchanged.

Run from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_api.py tests/test_api_deployment.py tests/test_public_market_api.py tests/test_dashboard_market_context.py tests/test_model_metadata.py
```

From `frontend/`, run `npm test`, `npm run lint`, and `npm run build`. Tests cover source parity, bounded pagination/date filters, nulls, negatives, missing/invalid sources, cache invalidation, metrics conflicts, artifact integrity/missing artifacts, safe fields and GET-only behavior. The optional real-data parity test skips when the ignored local Silver dataset is not present; isolated fixtures always run.
