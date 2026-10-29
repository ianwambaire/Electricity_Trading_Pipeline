# Next24 staging diagnosis — 2026-10-29

One read-only SSH inspection completed successfully at 07:19 UTC. No publication, inference, pipeline execution, service changes or deployment occurred. Sanitized evidence: `deploy/staging/NEXT24-DIAGNOSTIC-RESULTS.json`. Raw captures remain private locally. An initial local supervisor argument error started no SSH process; its corrected invocation made the one authorized connection.

## Confirmed findings

- Staging is the approved immutable historical publication, not a live pipeline view. Its latest Silver observation is October 25 21:00 UTC; its operational database ends October 26 02:01 UTC. The published generation data's last complete hour is October 25 21:00; biomass ends October 25 22:30 and solar 22:45. Those partial hours cannot satisfy completeness checks.
- Production continues updating. Latest recorded pipeline run: October 29 07:02:26 UTC, SUCCESS with next24 WITHHELD and the recorded reason “Forecast withheld because required recent market history is incomplete.” Latest complete raw hours: prices 06:00, load 04:00, generation 05:00 UTC. Latest finite biomass observation: 05:45. Production Silver reaches October 28 23:00; Gold October 28 22:00. A successful pipeline run does not imply a forecast passed its quality gate.
- Both `/forecast/context` and `/market/price-comparison` return 500. Reproduction under candidate UID 992 confirms `ModuleNotFoundError: processing`, originating at `shared/market_context.py:4`. The release contains API/shared modules but excludes pipeline processing modules.
- `/health` and `/ready` return 200; `/forecast/next24` returns 404 because its report is absent from the staging publication.
- Next24 latest/history/provenance and both monitoring reports exist in production but are absent from staging. Their omission is explicit in the publication inventory, pending separate validation. Existence does not establish freshness or operational validity. Model and feature-contract binaries exist in production but are deliberately absent from the API publication; inference belongs in the pipeline, not the API.

## Workflow and gates

`scheduled_pipeline.py`: ingest ENTSO-E and weather → complete-hour Silver → validated Gold → frozen model verification → `_run_next24h_stages` → `next24h_production.run_next24h_forecast` → validated latest/history/provenance → monitoring. Withholding is recorded separately from pipeline success.

The existing frozen 24-output Histogram Gradient Boosting release verifies its model/feature-contract hashes and exact 31-feature order. Operational assembly uses independent complete raw price/load histories, current generation, and current operational weather. It requires exact price lags 1/24/168, load lags 1/24, contiguous 24-hour rolling windows, complete generation including biomass, and five weather fields. It rejects unfinished hours and non-finite/missing features. The default freshness allowance is three hours; the deployed override was not read. No interpolation, fabricated biomass or historical-weather substitution is appropriate.

Weather is required: temperature, humidity, wind speed, cloud cover and shortwave radiation. Operational weather is fetched into memory from Open-Meteo; historical archive data is not an operational substitute. Prospective weather-vintage storage exists in production. This inspection accidentally checked `weather_data.csv`; the actual archive filename is `open_meteo_weather.csv`, so that reported absence is **not evidence of missing weather**. Current provider availability and exact archive freshness remain unverified.

The production incident table uses `details_json`; the bounded diagnostic did not project that column. Consequently the exact missing lag/window or technical subreason was **not recovered**. Latest watermarks alone cannot prove complete histories. No additional SSH inspection was attempted. Production model hashes, forecast issue/target timestamps, live weather availability and monitoring report contents still require bounded verification before operational publication.

## Local fix and verification

The API now imports a pure shared price-aggregation helper instead of the excluded pipeline module. The helper preserves the pipeline's aggregation/completeness implementation; the pipeline itself is unchanged. Parity tests cover complete, incomplete, null, legacy/hourly, duplicate, mixed-resolution and unsupported-resolution inputs. A fresh-process API regression now rejects any `processing` import while exercising both affected routes.

85 targeted tests passed: API aggregation, Streamlit decoupling, feature parity, dashboard context, next24 production and next24 model tests. Python syntax validation passed. No frontend assets, immutable release, models or forecasting rules were changed.

## Next authorization

1. Deploy a newly hash-bound API-only release containing the shared helper fix, with candidate restart and health/route/preservation checks; do not silently edit the immutable installed release.
2. Separately verify the production withholding incident's `details_json`, exact recent lag/window completeness, model hashes, operational weather availability and report freshness. This is a diagnostic validation step, not authorization to issue forecasts.
3. Only after quality gates pass, approve a coherent atomic publication of validated forecast/provenance and allowlisted monitoring summaries. Keep historical staging data explicitly historical. Existing production forecast files must not be relabeled live solely because they exist.

No evidence currently requires a new model or retraining. The existing workflow is implemented, but operational next24 availability cannot responsibly be asserted from this inspection.
