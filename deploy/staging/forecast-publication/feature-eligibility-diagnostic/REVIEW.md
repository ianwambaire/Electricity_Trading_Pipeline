# Fixed-run price/load feature eligibility — local preparation only

No remote authorization. Reuse exact-run withholding evidence from immutable
withholding-diagnostic0c7c781aec0d017097488872508e6ed94f6c74ee1f8e4e30f8a384b2a0eed26e.
Same pinned SSH/no-follow/read-only SQLite/90s remote/150s local/5s escalation,
no retry, private captures0700/0600, no generic host/run/path/SQL CLI arguments.
Original inspectors, approved manifests, evidence, production files remain intact.

First re-establish the exact natural flow, task/internal UUID, incident and recorded
latest-hour metadata. Require internal025ef1c9a1da4867a05aecb718028afa and gate
JOINT_PRICE_LOAD_HOUR. Then hash-read only three approved source files (parser,
cleaner, operational feature helper) without imports/execution; fail source drift.
Read two CURRENT price/load CSV snapshots through descriptor-anchored no-follow
capture, UID1000/non-writable metadata checks,32MiB each/1million-row limit. Recheck
both file hashes after analysis; any drift fails. No pandas, application import,
model deserialization, weather, credentials, upstream GET or receipt reads on EC2.
Standard-library CSV/time/finite-number analysis only. Output only required-hour
missing/null/nonfinite/off-grid/duplicate timestamps and counts; no market values
or raw feature vectors. Global duplicate timestamps/invalid dates or mixed/unknown
price resolution are rejected or marked source-invalid, consistent with cleaner.
Required-hour detail is bounded16points/hour; excessive/ambiguous input fails closed.
Report bound49152characters, stdout/stderr65536bytes each; no raw exception text.

## Exact requirements from bound source

clean_prices accepts declared PT15M four aligned quarters or PT60M one exact-hour
point, with no mixed resolutions/duplicates/nulls. Without declared resolution,
transition2025-09-30T22:00Z determines expected interval. clean_load requires four
non-null aligned quarter-hour load_mw observations. Feature helper reindexes EACH
source to a complete exact-hour timeline before shifts/rolling, then drops nonfinite
feature rows. There is no interpolation or filling missing market observations.
Price requires T,T-1,T-24,T-168 and rolling T-23..T (mean and sample std,24 points).
Load requires T,T-1,T-24 and rolling T-23..T (mean,24 points). The needed load hours
are therefore all25 consecutive hours T-24..T,100 quarter-hour observations.
14:00 load: Nov2 14:00 through Nov3 14:45 UTC. Rolling hours Nov2 15:00..Nov3 14:00.
15:00 load: Nov2 15:00 through Nov3 15:45 UTC. Rolling hours Nov2 16:00..Nov3 15:00.
Price additionally needs Oct27 14:00..14:45 or15:00..15:45 for its168h lag.

The raw hour must be finished (issue<current.floor(hour)). Existing freshness is
current-issue<=3hours. At recorded withholding16:47:04 both14:00 and15:00 pass
these temporal requirements; inference's exact earlier current timestamp was not
persisted in a receipt, so the recorded withholding clock is explicitly used.
Price/load eligible index intersection must be nonempty BEFORE generation/weather
joins; final newest issue is selected only after those joins and31 finite features.
Generation/weather/final eligibility are outside this diagnostic.

## Historical confidence

Recorded metadata proves latest complete price15:00, load14:00 at withholding,
not full lag/rolling eligibility for earlier hours. In particular load15:00 was not
complete then. Current CSVs may have been extended or repaired since. File hashes
and current snapshot timestamps are provenance, NOT per-observation arrival times.
Even a now-complete window cannot prove it was complete at16:47. Do not backdate
current data. Report current eligibility AT RECORDED CLOCK separately, never as a
current live forecast. Upstream publication versus ingestion cause remains unknown
without source/arrival history; no upstream queries or repair is included.

PASS means scoped current comparison succeeded, with historical-arrival limitations
still present; not a successful forecast or reconstructed historical snapshot.
All observations remain genuine source bytes; test fixtures are synthetic only.

Future separately authorized command (NOT executed here):

    venv/bin/python -I -B deploy/staging/forecast-publication/feature-eligibility-diagnostic/run.py --manifest-sha256 <NEW_APPROVED_MANIFEST_SHA256>

--local-check never connects. New manifest binds full prior immutable source closure
plus new inspector/runner/build/review/test and reference cleaner/parser sources.
Python3.9 grammar checked with host runtime; actual Linux/root execution unverified.

Validation:221 selected tests passed, including25 focused CSV eligibility/parity
cases against the native pandas cleaners and _historical_market_features helper.
Includes quarter gaps, null/nonfinite/off-grid/duplicate data, lag24, lag168,
rolling histories, freshness, immutable dependency closure, historical/current
separation and redacted failures. Existing withholding/v2-adapter/ingestion/A03
regressions passed. No production data or network was used. Unexpected timestamp
or resolution encodings outside the supported CSV forms fail closed rather than
being silently normalized. Source/manifest closure, Python3.9 grammar and whitespace
checks pass; --local-check makes zero remote attempts. Actual EC2 comparison and
the source-publication/arrival timing of missing observations remain unverified.
