# Publication-only diagnostic — fresh approval required

LOCAL PREPARATION. No SSH has been executed for this new package. The existing
preflight wrapper has NO publication-only switch; do not invent or pass one.
A new runner independently verifies PUBLICATION-DIAGNOSTIC.json, its exact artifact
set, hashes/sizes, and the assembled remote stdin payload digest. It retains the
verified source bytes. Nothing in the old preflight/release/tools manifests changes.

## Scope

The assembled stdin program loads verified preflight helper definitions and the
exact shared forecast-publication contract under non-main names, then executes
ONLY publication_diagnostic.py. It does not call the full preflight, services,
health/network, Prefect, cgroup, ingestion, inference or production fingerprinting.
The shared contract is stdlib-only data validation, not application/model imports.
It checks the approved root, ancestors, current symlink, release and bundle using
existing sanitized phase/cause codes. No rejected include/escaped pointer is followed.
Missing paths report MISSING; unsafe/hash/contract failures INVALID; expired but
otherwise valid content EXPIRED. No backdated validation. Full contract checks
include24 finite aligned predictions, frozen model/feature identity, input/history
completeness, provenance and actual UTC freshness. This validates a published bundle,
not independent retrieval/association of original production inference receipts.

Candidate-user effective access is deliberately UNVERIFIED. This package does
NOT execute nsenter, candidate Python, package/native imports or startup hooks.
If no valid bundle exists, candidate-user probing would not establish forecast
availability anyway. A later trusted-system-Python UID992 mount-context access
check needs separate implementation/review/authorization; do not claim it ran here.

## Connection and bounds

The runner reuses the retained, hash-verified original wrapper's private profile
and fixed SSH argv. Approved target/identity/known-host hashes must match; key
contents are not read. StrictHostKeyChecking=yes, -F /dev/null, BatchMode=yes,
IdentitiesOnly=yes, ConnectTimeout10, ConnectionAttempts1; no agent or retries.
Remote: sudo -n timeout --signal=TERM --kill-after=5s 120s /usr/bin/python3 -I -S -B -
(exact absolute timeout path and flags are inherited from the unchanged wrapper).
Local: verified bounded_run helper,180s,5s escalation,131072 bytes per stream.
No arbitrary host, payload, remote command or destination option. Captures are
local0600 under a private0700 ignored publication-only-* directory. Invalid output,
transport failures and capture/report-write errors use sanitized categories.
No full stderr, values, predictions, feature vectors, private paths or tokens print.

## Future invocation — NOT authorized yet

From the repository root, after independently approving the NEW manifest hash:

```sh
venv/bin/python -I -B deploy/staging/forecast-consistency-release/run_publication_diagnostic.py \
  --manifest-sha256 APPROVED_PUBLICATION_DIAGNOSTIC_MANIFEST_SHA256
```

Append --local-check for a local-only verification with zero network attempts.
The new manifest records exact hashes of diagnostic, runner, shared contract,
retained helpers and review dependencies, plus the deterministic assembled payload.
The manifest's own digest must be taken from the review response. It cannot
self-hash. Host Python/OS/SSH trust and existing noninteractive sudo permission are
prerequisites, not newly established host-side least privilege.

Output includes exact fixed publication_state, chain/contract evidence, phase/cause,
prediction count0/24 and effective_candidate_access=UNVERIFIED. Exit0 only VALID;
exit1 also represents a successful diagnostic of MISSING/INVALID/EXPIRED/UNVERIFIED.
Any transport error stops without retry, repair, directory creation or publication.
HTTP probes are absent; normal SSH/sudo audit records may occur. Files are read with
NOATIME; pointers/directories are never changed. No SQL/production database access.

## Next boundary

Manually commit these additive files first. Then approve one specific assembled
payload, runner and manifest hash. No previous authorization applies. Only after
observed findings may a separate staging-only config/deployment plan be finalized.
The absent env key's proposed value remains /srv/powerflow/forecast-publications;
do not add it to the server or manufacture a forecast during this inspection.
