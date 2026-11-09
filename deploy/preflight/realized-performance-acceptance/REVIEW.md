# Fixed-run Reporting V4 acceptance inspection

Local preparation only. No remote execution is authorized by this document.
This is one inspection extension, not a replacement deployment release.
Reporting V1–V4 and the application remain unchanged.

## Bound evidence and correction

Target natural flow `01a1bc5e-d54b-761c-88df-9d1a6571452c`, pipeline
`6dc962a38d9a4bd9b05d1b8d1931ec56`, scheduled2026-11-08T18:45:00Z,
Reporting V4 transaction `8415154bdaf94746a93adf6e380667a8`.

The task filter uses POST /api/task_runs/filter with exactly the target flow's
id filter, offset0, limit100 and **no sort**. Its server default ID_DESC is
verified against the independently sourced Prefect3.7.5 wheel, SHA256
214837b7cb1e10f8fec59018253cd8ef65c8b394b7df29c511b645b0ff5e4478.
START_TIME_ASC is not a TaskRunSort. That invalid request was a tooling defect;
its historical HTTP response was not retained, so its actual rejection and the
monitoring failure's cause remain unverified.

The official wheel's exact endpoint signatures, schema classes, nested filters,
response models, sort enums and LimitBody match the local3.7.2 test models used
by the offline transport simulation. There is no assumed cross-version parity.
The same approved installed3.7.5 metadata and worker/engine source hashes are
rechecked remotely before evidence access. No Prefect SDK code is imported there.

## Read-only request scope

- GET loopback Prefect /api/flow_runs/<fixed target>.
- POST loopback Prefect /api/task_runs/filter: flow relationship, limit100,
  offset0; no creation/state-setting/deletion endpoint. Exactly100 rows is
  incomplete evidence, never a successful complete selection.
- POST loopback Prefect /api/logs/filter: exact flow/task, at most20-minute
  window, limit50, offset0, TIMESTAMP_DESC. A full page is explicitly truncated
  and prevents a complete acceptance PASS. No second page or retry is issued.
- TLS-verified staging-host requests through local443, no redirects:
  GET /api/forecast/next24, /api/operations/current, /api/operations/summary,
  /api/forecast/realized-evaluation. No authenticated endpoints or credentials.

Each HTTP attempt retains only the fixed endpoint identifier, method, status,
byte count and fixed error. HTTP422 retains only approved field locations and
validation categories, never messages, inputs or context. Status is captured
before JSON/content checks; transport failures have a fixed category. Requests,
responses, state messages and task logs are never saved verbatim.

## Independent evidence sections

After mandatory identity, idle-window, backup and installed-integrity gates:

1. Exact natural flow identity/deployment/automatic scheduling, real terminal
   state, scheduled/start/end timestamps. No completion inferred from the clock.
2. Related inference, automatic publication and monitoring task IDs/states;
   unique monitoring selection. Wrong relationships/duplicates fail closed.
3. Actual monitoring state/name and timestamp; real task times or explicit nulls.
   Conditional NotReady/upstream skip evidence is distinct from failure.
4. Scoped task logs and state-message diagnosis: fixed exception classes/errno,
   approved project-relative stack module/function/line, recognized reasons and
   denied component. Unknown causes remain unknown. No raw trace/message/path.
5. Committed current operational document, hash, outcomes and target association.
   An advanced/different record is explicitly identified, never target proof.
6. Current report pointer/document metadata and hash, pure frozen contract,
   generation time, source hashes, coverage, completed-hour/issue/model checks.
   No pointer, MISSING_INPUTS, FAILED and READY remain distinct.
7. Independent forecast, operational-current, operational-summary and realized
   HTTP results. A monitoring failure never suppresses these checks.
8. Exact installed realized API evaluator compared at the actual HTTP assessment
   time (not a changed clock); generation must be inside actual target task times.
9. READY documents only: existing audited, pure receipt/metric reconstruction
   as UID/GID1000 with cleared groups. No producer publication or model calls.
   Current source hashes must still match; otherwise SOURCE_ADVANCED, never an
   invented historical reconstruction. Report rows/market values stay internal.
10. Original protected-state checks, production/configuration preservation,
    publication retention and final pointer stability/idleness.

Publication is the existing content-addressed report and pointer; no separate
receipt or publication timestamp is fabricated. Task success alone does not prove
publication, and a valid insufficient-input marker does not establish metrics.
A FAILED marker, missing publication, nonterminal/failed monitoring, truncated
logs or unverified association cannot produce full acceptance PASS. Safety and
identity failures block their dependents, while independent sections continue.

## Integrity, execution and evidence

BINDINGS.json binds these sources, tests/review, Reporting V4's complete immutable
closure, existing stdin-corrected pinned SSH supervisor and assembled payload.
The local verifier rejects missing, changed or symlink-substituted artifacts.
The existing reviewed read-only acceptance prefix is reused; its original
accept_report is defined but **never invoked**. Mutation entrypoints are absent.
No application/deployment package is rebuilt or modified.

One SSH connection, strict pinned host key/identity, public-key-only,
noninteractive/no agent/no forwarding, StdinNull=no. Fixed system Python isolated
stdin; remote90s, local150s, five-second termination escalation, output65536 bytes.
No retries/polling, writes, hooks, Prefect execution or report publication. Existing
source-bound child audit guards block writes/network/process side effects.
Only verified sanitized JSON is retained under the existing private staging
preflight evidence directory (directory0700/file0600). Raw stdout/stderr and
unverified output are discarded. All returned strings are source-allowlisted
constants, approved relative symbols, identifiers, timestamps or digests.

Run locally without connecting:

    venv/bin/python -I -B deploy/preflight/realized-performance-acceptance/run.py --bindings-sha256 <BINDINGS-SHA256> --local-check

Future one-shot command, **separate explicit read-only authorization required**:

    venv/bin/python -I -B deploy/preflight/realized-performance-acceptance/run.py --bindings-sha256 <BINDINGS-SHA256>

## Limitations

Real Linux/SSH responses remain unobserved in this preparation. Retained task logs
may be absent or omit the actual failure. Bounded queries may return incomplete
evidence; that is reported rather than silently paginating. If current pointers
have advanced, this tool does not invent historical target-publication links or
scan unrelated history. If source snapshots changed, receipt reconstruction is
blocked while other sections remain available. The original90-second remote
limit is unchanged; a hard transport/deadline failure may prevent a complete
report. Browser acceptance remains pending; genuine Analyst403 remains pending
and closed to further browser experiments. No application root cause is assumed.
