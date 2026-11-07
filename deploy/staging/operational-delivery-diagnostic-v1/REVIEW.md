# Read-only operational delivery investigation

Targets only the natural 2026-11-07 08:45 UTC slot in the existing deployment,
after the V5 APPLIED transaction's recorded activation. V5 remains unchanged.

Reuses V5's entire verified dependency closure, pinned SSH profile, no-follow
readers and immutable read-only SQLite snapshot. No apply/rollback transaction
module is assembled. The diagnostic never calls terminal capture (receipt reads),
the installed helper, publisher, inference, deployment updates or service actions.

Additional Prefect request: fixed localhost POST /api/logs/filter, one flow UUID,
its start through end+120 seconds, text=operational, at most 63 records and 256KiB.
Semantics checked against the independently verified Prefect 3.7.5 reference wheel.
Messages are projected into fixed statuses/reasons, known exception classes and
approved source identifiers; raw logs are never returned or persisted locally.

Reads only matching pipeline summary, forecast-task metadata, approved installed
helper/worker hashes and immediate operational store metadata (max16 entries).
No dataset or receipt content is read. Store metadata cannot prove the full
history of attempted/rejected publication: absence is explicitly inconclusive.
One SSH, 90s remote, 150s local, 5s escalation, no retries. Private captures only.
No authorization for any repair, installation or publication is implied.
