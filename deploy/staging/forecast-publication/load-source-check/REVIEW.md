# Fixed-scope genuine load source check — local preparation

This is an offline-tested comparison core, **not a remote executable package**.
No SSH command is approved or supplied. No source request has been made.
`MANIFEST.json` binds local files and the source reviewed for ingestion semantics;
it does not authorize remote access or attest installed EC2 dependencies.

## Existing ingestion contract

`src/ingestion/fetch_entsoe_data.py` uses `DE_LU`, `query_load` (A65/A16),
`data/raw/entsoe/load.csv`, UTC and an exclusive completed-hour end. The incremental
start is `max(configured historical start, latest stored timestamp - 48 hours)`.
`fetch_timestamp_range` clips each result to `[start, end)` even though the client
parser truncates inclusively. Missing data is not fabricated. Recent genuine
observations are merged by `_append_load_safely`/`merge_generation_rows`; changed
CSV bytes are written to a temporary file and replaced atomically. Recent gaps
are warnings and can be repaired by a later normal run. Confirmed late values
outside the revision window remain subject to the existing protected-history policy.

The scheduled flow ingests prices, load and generation before raw synchronization,
weather, transformation and inference. A later successful flow alone does not prove
the three observations were repaired. Verify the stored quarters and complete hour.

The three November 3 15:15/15:30/15:45 UTC quarters are revisited only while each
lies inside that actual start/end range. This is conditional, not an indefinite
guarantee. No source, feature, model, publication or scheduling code is changed.

## Exact proposed source request

One TLS-verified GET to `https://web-api.tp.entsoe.eu/api`, no redirects, proxy
environment or retries. Parameters:

- documentType=A65; processType=A16.
- outBiddingZone_Domain=10Y1001A1001A82H; out_Domain=10Y1001A1001A82H.
- periodStart=202611031500; periodEnd=202611031600.
- securityToken supplied in memory by the existing configured ENTSOE_API_KEY
  provider, never included in output, CLI arguments, evidence or exception text.

The installed entsoe-py implementation rounds time parameters to the hour. This
one-hour request avoids ambiguous quarter-hour request rounding. The core reports
only the three required quarter timestamps. It verifies A65/A16, DE_LU, MAW units,
PT15M, timezone-aware timestamps, aligned periods, unique positions and bounded
periods. A01 omitted positions remain absent; A03 explicitly declared block values
extend to the next position / period end, never before the first point. Conflicting
series, resolution mismatch or malformed XML fail closed, without averaging or
interpolation. A provider no-matching-data acknowledgement is separate from an
authentication/error acknowledgement. Reports contain presence states and hashes,
never raw load values. Nonfinite values are INCOMPLETE.

## Bounds and read-only behavior

Only stdlib imports; importing the core performs no I/O. No filesystem, database,
SSH, application, publisher, inference or persistence entrypoints are imported.
The fixed request has a five-second socket timeout, a twenty-second monotonic
read budget, a 2 MB body cap and no retry. A blocked read can exceed the read
budget by one socket timeout. DNS and credential-provider time are not bounded
by this core: a future reviewed outer process must enforce a hard 30-second
remote / 90-second local limit and five-second escalation. Without that outer
adapter the core must not be executed remotely.

The future adapter must capture the exact load snapshot with existing no-follow,
owner/mode and before/after stability protections, then pass held bytes (32 MB /
one million rows maximum) and the verified configured historical start to the core.
Source and snapshot capture are not atomic together; record capture times and
reject snapshot drift. Current provider availability does not establish availability
at 16:47:04 UTC. Even source-present/snapshot-absent is not proof of an ingestion
bug: the natural run may have queried before the provider supplied the data.

## Remaining execution blocker

The existing reviewed metadata inspectors deliberately do not obtain credentials
or contact ENTSO-E. The historical price-history child obtains secrets by importing
production code/SDKs and loading `.env`; it is not reused as a trusted elevated
dependency. The configured provider supports env, SSM and Secrets Manager with
explicit non-fallback semantics. This task has not verified the installed provider
and SDK executable closure or current effective provider configuration on EC2.

Before a remote command can be bound, extend an existing reviewed runner with a
fixed, unprivileged pipeline-identity credential bridge to that exact configured
provider. Disable Python startup hooks, bind all executed helper/SDK bytes, keep
credentials in process memory, do not import writable application code as root,
and retain pinned SSH, stable snapshot capture, output validation and outer bounds.
Do not substitute a token from another backend or introduce ad-hoc AWS signing.
The local callback in `request_source` is an integration interface, not proof that
this bridge is implemented. A new payload/runner/manifest review and separate
one-attempt authorization are required; the old feature inspector authorization
does not permit an external source request.

Smallest next step: complete and bind that credential/host adapter locally, using
the existing provider and runner conventions. No remote execution is ready yet.

## Validation

Run local fixtures only:

```
MPLBACKEND=Agg venv/bin/python -I -B -m pytest -q -p no:cacheprovider tests/test_load_source_check.py tests/test_incremental_pipeline.py -k 'load or overlap'
```

Tests cover source/auth request shape, UTC normalization, A01/A03, partial and
missing responses, invalid quantities, resolution/duplicate rejection, bounds,
redirect refusal, sanitized provider failures, deadline/no retries, overlap aging,
exclusive end and absence of write/import side effects. Existing incremental
fixtures exercise real merge behavior without production datasets or credentials.
Python 3.9 grammar is checked; execution uses the available local Python runtime,
not a verified Linux/Python 3.9 runtime. Neither source availability nor effective
remote credential access has been tested.
