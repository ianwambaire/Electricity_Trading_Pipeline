# Local candidate: persisted issue-hour serialization boundary

The exact-run Linux diagnostic reproduced InvalidEvidence/TIMESTAMP in the
operational producer's persisted issue comparison (original source line195).
Run/pipeline association, source access, receipt integrity and receipt/task binding
had passed. The original historical exception was discarded; this is a current
replay of the same committed run, not a recovered historical traceback.

The active scheduled pipeline stores str(pandas.Timestamp) and the inference
receipt writer uses pandas.DataFrame.to_csv. Both serialize UTC issue hours with
a space date/time separator. The operational parser requires canonical T-form.
Offline tests invoke the real receipt writer and reproduce the old failure.

Minimal change: accept that single legacy separator at the persisted issue-time
boundary, then pass through the unchanged strict UTC timestamp parser. Compare
summary and receipt issue hours and canonicalize only the operational document's
issue time. Naive/non-UTC/malformed times and mismatched issues still fail closed.
The forecast bundle retains its original CSV strings: never rewrite its bytes or
change its hash. Tests compare against the unchanged reviewed bundle builder.

This versioned candidate deliberately does NOT replace src/shared's V5-bound
producer. V5, historical manifests/payloads, original TOOLS.json and installed
files remain unchanged. The candidate has no installer or activation command.
A separately reviewed helper-only immutable release must bind this module and
its full helper/launcher/sudoers closure before any remote change.

Unchanged controls: schema, role projections, natural-run and stable identity,
31-feature/frozen-model/receipt hashes, immutable read-only source snapshot,
forecast expiry and operational90-minute freshness, duplicate/older publication
protection and atomic activation. No schedule/auth/API/frontend change required.

Required live acceptance after separately authorized deployment: a subsequent
natural run delivers current operational evidence; public current endpoints
agree and exclude Admin fields; authenticated Admin/Analyst authorization and
React current-record freshness/provenance/identity agree across pages.
