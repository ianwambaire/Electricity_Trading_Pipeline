# Automatic staging forecast delivery — local implementation, not deployment approval

## Current boundary

No setup, publication, privilege change, service operation or code deployment was
performed. The one authorized read-only receipt inspection returned SSH 255 /
SSH_FAILURE without a report; it was not retried. The newest genuine receipt is
therefore UNVERIFIED. The last verified receipt (issue 2026-11-02 09:00 UTC,
cutoff 12:00 UTC) is expired. No current bundle or new production hash is approved.
An elapsed cutoff is never extended. Current UTC must be checked at execution.

The existing FIRST-SETUP-MANIFEST.json remains exactly
274bf50c731bc5ff074d8dae28b87126055e70db663081b4ee3d68165d9217b7.
Its 6,470-byte code-only archive remains
faeec014b4cde838fcffb3c285eef1995f38547d443162e529fa90ec7209a6b3.
It installs the ORIGINAL manual publisher, not this new automatic publisher. The
private archive, original tools manifests and all preserved releases are unchanged.
Do not rebuild that archive or silently substitute working-tree publish.py for it.
FIRST-PUBLICATION-REVIEW.md governs that separate setup and first manual publication.
The already deployed staging selector/environment needs no restart for a new bundle.

## Implemented path

1. The existing inference task returns its authentic committed receipt UUID explicitly.
2. A Prefect task with retries=0 calls shared.forecast_delivery only when
   POWERFLOW_AUTO_PUBLICATION_ENABLED=true. Default is disabled. WITHHELD is skipped;
   absent or malformed receipt/flow identifiers fail closed without invoking sudo.
3. Worker argv is fixed to sudo -n /usr/local/sbin/powerflow-publish-next24
   --receipt <canonical-UUID> --flow-run <canonical-UUID>. No caller-controlled
   command, path, host, environment values, shell interpolation or stdin is accepted.
4. The root-owned launcher clears the environment and uses trusted system Python
   -I -S -B, timeout 30 seconds, TERM/KILL escalation 5 seconds. The worker has a
   40-second deadline and 16 KiB combined output limit. Output is a single allowlisted
   status; stderr, feature vectors, paths and exception details never enter reports.
5. automatic.py accepts only those two UUID arguments. It reads only the fixed
   committed receipt directory (five files, including integrity.json), the fixed
   persisted forecast history and fixed local Prefect flow/task metadata. Redirects
   and proxies are disabled; HTTP reads have 5-second/100 KiB bounds. No remote API,
   application imports, model deserialization, inference or production write occurs.
6. Receipt ancestors/files are anchored with O_NOFOLLOW descriptors. Private receipt
   owner UID1000, directory0700 and files with no group/world access are required.
   History permits existing read-only sharing but rejects group/world write. Files
   are bounded and checked for changes during reading; integrity binds all four
   artifacts. Root-owned installed tool bytes are held after SHA verification,
   compiled from those bytes and never reopened for imports. No production checkout
   is placed on root Python's import path.
7. The flow must be the configured auto-scheduled :45 deployment, RUNNING or COMPLETED.
   Exactly one completed next24 forecasting task must bracket the receipt execution.
   Prefect UUID and inference UUID remain distinct. The flow can still be RUNNING
   because this publication task executes after inference inside that flow.
8. The existing builder verifies the full schema-v1 receipt, ordered 31 features,
   frozen model/contract identities, reciprocal hashes, input completeness and 24
   finite aligned targets. All 24 predictions must also match persisted history.
   Receipt/source contents are retained, not reconstructed or re-fetched. Expiry
   is checked at actual UTC, inside the existing lock and immediately before switch.
9. Under the same exclusive publication flock, duplicate digest or same issue is
   SKIPPED_DUPLICATE; an older issue is REJECTED_OLDER_ISSUE. A newer issue can replace
   an expired structurally valid current bundle. Invalid current data blocks updates.
   A concurrent writer fails without retry. Existing immutable release bytes are
   reused only if identical, supporting recovery after an interrupted pointer switch.
10. Only root-owned releases/<sha>/bundle.json and the atomic current pointer are
    written, with directory0750/file0640 and group992. No frozen historical files,
    model, database or production forecast is modified. A failure may retain a
    private partial release or inactive completed release; nothing is deleted.

Publication status is recorded separately in pipeline storage metadata. A failure
records a sanitized publication incident and preserves the inference outcome.
PUBLISHED, SKIPPED_WITHHELD, SKIPPED_DUPLICATE, SKIPPED_EXPIRED, REJECTED_OLDER_ISSUE,
REJECTED_INFERENCE, DISABLED and FAILED are distinguishable. A completed Prefect flow
or publication task is never sufficient proof of a new forecast.

## Privilege release B — requires an independently reviewed installer and approval

AUTOMATION-SOURCE-MANIFEST.json binds local sources and the exact five root tool
bytes. It is NOT an executable installation package or remote authorization.
An installer must atomically install these NEW tools separately at
/opt/powerflow/forecast-publication-automation (root:root0700, files0600, shared0700),
write automation-manifest.json as exactly its installed_tools map, and install the
launcher at /usr/local/sbin/powerflow-publish-next24 (root:root0755). Verify system
Python/timeout ownership and non-writability. Do not replace old manual tools.

The only prospective sudoers grant is for the verified fixed launcher to the
verified pipeline identity (currently expected UID1000), never for Python, a shell,
install, chmod, timeout or arbitrary paths. The launcher validates exact arguments;
its root-private code is not writable by that identity or candidate UID992. The
installer must validate the narrow rule with visudo before enabling it, back up any
existing exact rule/launcher/tool configuration, reject unexpected conflicts and
verify denied arbitrary commands. Do not grant candidate UID992 write privileges.
No sudoers file or installer is deployed by this task.

Producer UID1000, local Prefect and root/system binaries remain trust boundaries.
Hashes cannot prove upstream authenticity against a compromised producer able to
rewrite the entire receipt/history/Prefect set. This uses the same trusted production
inference boundary as the existing publication contract. Root execution is limited
by fixed paths, bounded data and time, but is not the candidate's systemd sandbox.
History capture is bounded at64 MB; practical helper memory/latency must be measured
on Linux before activation. Larger history fails closed and needs a separate design.

## Independently reversible release sequence

A. **Infrastructure setup:** separately authorize unchanged run_first_setup.py with
   the manifest above. Create only missing reviewed directories/tools; verify root:992
   0750 and actual candidate UID992 read/traverse/no-write in its mount namespace.
   It creates no forecast or current pointer. Leave exact setup artifacts intact.
   Future command (not executed here):

       venv/bin/python -I -B deploy/staging/forecast-publication/run_first_setup.py --manifest-sha256 274bf50c731bc5ff074d8dae28b87126055e70db663081b4ee3d68165d9217b7

   First manual publication additionally requires a fresh, separately verified
   receipt and approved bundle hash, expected-current=none, freshness recheck, atomic
   publication and actual candidate/API readback. No expired candidate is prepared.
B. **Privilege setup:** review/install new tools and narrow launcher rule separately
   as above. Verify installation hashes, argument rejection, ownership, available
   memory/disk and rollback record. No inference scheduling or candidate restart.
C. **Pipeline integration:** back up and hash only src/scheduled_pipeline.py and new
   src/shared/forecast_delivery.py; install in an idle >600s deployment window using
   existing guarded conventions. Preserve schedule45 * * * * UTC, concurrency1,
   collision policy, parser hotfix, databases, models, service identities and routing.
   Enable the opt-in only after B has passed Linux tests. Determine the existing
   worker's reviewed environment delivery/restart requirements before approval;
   do not assume editing a file changes an already running worker environment.
   Observe the next NATURAL run. No manual inference, backfill or forced schedule.
   Disable only the opt-in to stop delivery; roll back these exact code/environment
   backups if separately authorized. Never roll back inference data or the model.
D. **MFA release:** gated independently by the conditions below, not by A–C.
E. **Chart/copy release:** existing commit0e85a0b includes the API demand-series
   sampler and coordinated React changes. Build a NEW immutable staging-origin
   API/static release; preserve old backend/static pointers and exact environment
   independently. Reuse guarded deployment/rollback conventions, at least768 MiB available
   RAM and at least2 GiB post-install free disk, candidate512 MiB
   max/zero swap and all sandbox/BPF and production-preservation checks. API change
   must precede frontend demand query. Never edit a preserved immutable release.

After A/B/C, require actual /forecast/next24 HTTP200, no-store, identical24 predictions,
issue/cutoff/model/receipt/bundle identities, operations VALID, React provenance and
all24 horizons versus remaining-future count. After expiry require503
FORECAST_WITHHELD/no-store and masked stale charts/downloads. Anonymous/Admin/Analyst
boundaries remain unchanged. If publication fails, diagnose its status without
changing input quality gates. Existing manual rollback/withdraw CLI is separately
approved, uses exact expected-current CAS and refuses to restore an expired bundle.
Stopping automation does not erase published history; expiry still applies.

## MFA release gate and owner-assisted acceptance

Commit74afaff explicitly introduced an independent deployed-runtime enrollment
release boundary during backend hardening. Code/history proves that intent, not a
Cognito policy change. Current deployed startup deliberately rejects
POWERFLOW_ACCOUNT_TOTP_ENABLED=true. Flipping that flag alone would prevent startup.
The gate remains unchanged. Existing enrollment routes are suitable only for a
native, password-capable Cognito account with verified recovery email, live own-user
access token, aws.cognito.signin.user.admin scope, fresh auth_time<=600s and no
unknown/existing factor. They use bounded five-minute, five-attempt, single-worker
owner-bound tickets; verification precedes preference change and live readback.

Actual pool MFA OFF/OPTIONAL/REQUIRED, software-token policy, affected-user enrolled/
preferred factors, remembered devices and fresh native challenge behavior remain
UNVERIFIED. No approved current live configuration report establishes them. A prior
Google Admin session is not a native TOTP challenge test. Hosted UI owns native
challenge handling; Google sign-in is provider-managed and this application cannot
claim Cognito TOTP is automatically enforced on federated authentication.

Smallest secure D design: first approve read-only pool/client/user-factor/device
metadata inspection, without secrets; verify intended issuer/client and supported
factor/recovery policy. Retain current blocked gate until that evidence and separate
release approval exist. Then review an explicit staging-only, subject-allowlisted
release gate (not a generic flag-only removal), preserving every current token,
fresh-auth, native-account, attempt, rate, recovery and role check. Confirm single
worker/in-memory ticket behavior, TLS/no-store/redaction, rate protection and no
secret retention in logs, traces, analytics or browser storage. No live release is
implemented or authorized merely by this design; no remote identity is changed.
A lost authenticator is not recovered by password reset or canceling setup.

Owner acceptance after that separately reviewed change: sign out, use a private
browser, choose native email/password (not Google), reconnect Profile with prompt=login
and account-management scope, enroll TOTP in trusted UI, deliberately test one invalid
code then a correct code, confirm enabled/preferred readback, sign out and perform a
fresh native login. Confirm actual challenge and denial for invalid/missing code.
Owner enters all secrets/codes in the UI, never chat. Separately test Google behavior
and Analyst/Admin routes with their real authorized sessions; verify no role gain,
expired/revoked-session rejection and documented lost-device administrator recovery.
If native challenge is absent, inspect policy/device/session evidence; do not infer
MFA is disabled or weaken authentication. Hosted UI may support policy-driven MFA
setup already; inspect that before releasing custom enrollment unnecessarily.

## Local verification and remaining live evidence

Tests use synthetic fixtures and RecordingModel outputs; none are current predictions.
New coverage exercises authentic-boundary capture/builder compatibility, expiry,
missing/tampered receipts, persisted mismatch, duplicate/older issues, concurrent
writers, interrupted switch, privilege errors, helper output/timeout bounds, explicit
receipt propagation and separate inference/publication status. Existing API tests
cover503/no-store, source consistency, authorization and missing publication. Existing
MFA tests cover enrollment, wrong/expired codes, preference failures, fresh/revoked
sessions, native/federated distinction, recovery and Analyst/Admin separation.

Current runtime, newest receipt, directory/tool existence and effective publisher/
candidate access still need authorized live verification. Linux helper installation,
sudo confinement, actual resource usage, Prefect response semantics and naturally
scheduled publication must pass acceptance before automation is called operational.
No production cutover or Streamlit retirement is included.
