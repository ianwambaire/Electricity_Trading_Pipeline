# Phase 4E — optional TOTP application and account-security implementation

21 October 2026, Africa/Nairobi. Branch `feature/react-frontend`, starting commit `9093d5c`. No staging, commits, pushes, merges or deployment were performed.

## Status

Only the two explicitly approved Cognito settings were applied. Backend and React enrollment/status support is implemented and tested against isolated provider/DOM fixtures. **The enrollment release gate remains false by default. No existing account was enrolled, no MFA secret generated against live Cognito, and no live account-recovery operation performed.** Live enrollment, code verification, login with TOTP and recovery are not certified by mocked tests.

Email changes, factor disabling/replacement/removal, backup codes, lost-authenticator recovery, device inventories and user-administration functions are not implemented. These are intentionally unavailable, not simulated controls. Existing password management, profile editing, logout and group-based authorization remain in place.

The [capability/security audit](phase4e-account-security.md) records the previous settings and provider documentation. Its pre-approval statements are historical; this document records the applied state.

## Approved AWS change and preservation evidence

Applied at **17:23:21 Africa/Nairobi / 14:23:21 UTC** to pool `us-east-1_NLoYFRvex`, region `us-east-1`:

```json
{
  "MfaConfiguration": "OPTIONAL",
  "SoftwareTokenMfaConfiguration": {"Enabled": true}
}
```

Preflight confirmed the pool's ARN account/region matched the active STS account and expected pool ID. The current MFA configuration was exactly `{"MfaConfiguration":"OFF"}`. Configuration was recaptured immediately before mutation and compared to the protected preflight snapshot; drift would have aborted the call. `SetUserPoolMfaConfig` was used instead of a broad `UpdateUserPool` request.

Read-back confirmed the exact two intended values. Comparing the complete pool before/after, excluding only MfaConfiguration and provider LastModifiedDate, found no unrelated changes. Complete configuration fingerprints matched for **both SPA and original Streamlit clients**, Google identity-provider configuration and group definitions. Account/region stayed the same. No email policy, password/recovery policy, user, client, callback, OAuth scope, identity mapping, group membership, MFA preference or production Streamlit file was updated by this change.

Only a default AWS CLI profile was available and it used the root identity. That identity was used for the narrowly approved operation after disclosure; no IAM access was created or expanded. This remains an operational concern: use a separately provisioned short-lived least-privilege operator role for future work. Application account APIs use only the authenticated user's access token and never root/IAM credentials. No account number, ARN, raw token or provider secret was included in the report.

Optional MFA is pool-wide. It does not automatically enroll native users. Once a user enrolls, hosted sign-in through any client—including Streamlit—can challenge them. Google sign-in delegates MFA to Google and does not gain a Cognito factor. Saved Streamlit **authentication configuration** preservation is verified; an end-to-end production Streamlit MFA challenge is not tested or claimed.

## Protected backup and rollback

Prepared before mutation, Git-ignored directory:

`/Users/iannganga/Desktop/electricity-trading-pipeline/backups/cognito-mfa-20261021T142235Z/`

Directory mode 0700 and files 0600. Contents: complete non-secret pool/MFA snapshots in `before.json` / `after.json`, hashes of related client/provider/group configurations, `approved-request.json`, `rollback-request.json`, `ROLLBACK.txt`, `update-result.json`, `verification.json` and final read-back evidence. Provider/client secrets were not saved; related configurations were hashed in memory. No user record export was made.

Rollback is **prepared, not executed**, and needs explicit approval because it disables MFA pool-wide:

1. Re-describe MFA, pool and both clients/Google/groups. Compare against the saved after state. Stop on drift; do not overwrite concurrent administrator changes.
2. Coordinate any users who might have enrolled since the change. Do not assume turning policy off erases a registered secret or resets a user preference.
3. Only after approval:

```sh
aws cognito-idp set-user-pool-mfa-config --region us-east-1 \
  --cli-input-json file:///Users/iannganga/Desktop/electricity-trading-pipeline/backups/cognito-mfa-20261021T142235Z/rollback-request.json \
  --no-cli-pager
```

The prepared request contains only UserPoolId, `MfaConfiguration: OFF`, `SoftwareTokenMfaConfiguration: {Enabled:false}`. Original software-token configuration was absent; AWS may retain an explicitly disabled object, so verify equivalent disabled behavior as well as unchanged unrelated fields. No user factor reset/removal is part of rollback. Repeat sign-in compatibility checks without making account changes.

## Implemented capability matrix

| Capability | Implementation / release state |
| --- | --- |
| Native TOTP status | Reads GetUser's activated factors; unknown/malformed provider evidence fails closed |
| Native TOTP enrollment | Implemented, feature-gated; requires verified email, confirmed PASSWORD capability, valid own-account token/self-service scope, fresh auth_time (10 minutes), no linked IdP and no activated factor |
| Enrollment verification | Strict six ASCII digits; Cognito verification must return SUCCESS before enabling; re-reads enabled/preferred status before confirming success |
| Google security | Provider-managed guidance; no Cognito enrollment controls/routes available to federated identities |
| Password/profile/sign-out | Existing working flows retained; MFA enrollment cannot grant Admin or edit another account |
| Email changes | Read-only; verification-before-effect pool policy remains unchanged and unapproved |
| Removal/replacement / lost-device recovery | Deferred; no disable switch, administrative reset or recovery bypass exposed |
| Live acceptance | Google basic login and logout passed after policy change; native owner-entry sign-in passed; enrollment/recovery require separate approval |

## Backend boundaries

New routes (all authenticated; no user-selected target or cookie auth):

| Route | Behavior |
| --- | --- |
| `POST /account/mfa/setup` | Fresh eligible native account only; starts Cognito association, returns bounded setup key and opaque ticket with maximum five-minute lifetime |
| `POST /account/mfa/verify` | Requires same subject/auth_time and valid setup ticket; verifies code, enables preferred TOTP, confirms state with live GetUser |
| `POST /account/mfa/cancel` | Discards only ephemeral metadata belonging to the authenticated subject; never calls a provider factor-disable API |

The enrollment/verification routes additionally require `POWERFLOW_ACCOUNT_TOTP_ENABLED=true`. It is a deployment release gate, not permission to modify the pool or enroll accounts. Default false ensures the current local development workflow cannot accidentally enroll an existing user. A future approved isolated acceptance run must intentionally enable it on a controlled server. The flag does not change Cognito policy and does not prevent token holders from calling supported Cognito self-service APIs directly.

The gateway adds only AssociateSoftwareToken, VerifySoftwareToken and enable-only SetUserMFAPreference. It defensively rejects extra fields, account targets, alternate factor writes and disable requests. Existing signature/issuer/client/expiry/scope validation and live subject/activity checks apply. No MFA recovery route or privilege-bearing IAM credential is added.

Setup metadata is bounded to 1,000 active subjects, five verification attempts and a five-minute lifetime, coordinated with locks. It contains an opaque random ticket, subject key, auth_time, monotonic expiry, attempt count and verification/busy flags—**no access token, TOTP key or code**. Concurrent starts/verification fail safely. A preference failure after successful verification can be retried at the API within the same setup without verifying/replacing again. Provider timeouts or uncertain completion must be reconciled by a fresh status read. Responses use no-store; code/ticket fields are SecretStr and input errors omit submitted values. No request/response body logging was added.

This ephemeral store is **single-process**. Restart/worker mismatch expires setup rather than allowing a bypass. Run one API worker for initial isolated acceptance. Multi-worker production use needs a separately reviewed coordination strategy for these non-secret short-lived records (or equivalent session affinity), not ad hoc storage of TOTP secrets. Provider account rate limits supplement the bounded local attempts; this is not a global distributed abuse-control system.

## React behavior and secret handling

My Profile's Security area uses the established white/blue design and shows real factor status separately from management availability. Native setup includes an explicit confirmation, manual authenticator setup key, accessible numeric code field, verification status, safe errors and reauthentication action. It uses existing authenticated API client behavior: 401 expires the session; 403 preserves it. No fabricated MFA state or fake toggle exists.

No new production dependency was added. Manual key entry works with standard authenticator apps; **QR generation is not implemented** and no external QR service receives a secret. The setup key/ticket live only in component memory/DOM; code input is cleared after submission. Key display is removed after completion, cancellation, tab hiding, navigation/unmount or five minutes. In-flight requests are aborted on teardown; late responses cannot restore the key. Network/confirmation uncertainty drops setup material and requests status refresh instead of optimistically declaring success. Clearing JS references is not a guarantee of physical memory zeroization or protection from browser extensions/devtools/XSS; production hardening remains necessary.

Setup cancellation closes local metadata, not a verified provider factor. An unverified association can remain pending at Cognito until superseded; the application does not promise provider deletion. GetUser lists activated factors, not every dormant secret. A new setup must not be marketed as recovery or safe replacement of an old authenticator. Release is blocked pending live acceptance and a reviewed lost-device support policy.

Test-only development dependencies: Testing Library for real form interactions, jsdom for DOM/focus behavior and tsx for TSX test loading. The Node test loader initializes the DOM before React DOM feature detection. No test account is represented as a real authenticated user in the product.

## Validation and actual evidence

- AWS exact read-back and unrelated-setting comparison: passed after mutation. Final read-only recheck also matched the complete saved after snapshot, both client fingerprints, Google and groups. Evidence: protected `final-readback.json`.
- Backend suite: **614 passed** in 31.51 s; one existing Starlette/httpx TestClient deprecation warning. New isolated cases cover setup/verification/readback, wrong code/attempt bounds, default release denial, native/federated eligibility, verified recovery requirement, strict schemas/redaction, JWT/scope/freshness/revocation failures, concurrency/expiry/owner binding, partial preference failure and all seven Analyst Admin-route denials after simulated enrollment.
- Frontend: **54 passed**, lint and production build passed. Actual DOM interaction tests cover confirmation, code validation/focus, duplicates, cancellation, fresh-auth action, network uncertainty, hiding/unmount/late responses, expiry and provider/unknown/disabled capabilities. Existing analytics/auth/routing regressions remain included. `git diff --check` passed. Dependency installation reported zero vulnerabilities.
- Responsive isolated UI review: 390×844, 768×1024 and 1440×1000 inspected; confirmation text/actions and provider guidance fit and reflow. No live account, provider request or TOTP secret was used. Temporary fixture removed and viewport reset. This does not replace full real enrollment UX acceptance.
- Live Google: normal Code+PKCE sign-in returned the existing Google identity and server-derived Admin, with no MFA enrollment prompt; normal sign-out returned to the sign-in gate. No profile attribute update was submitted. Three-scope ordinary login correctly requested explicit account reconnection before self-service; it was not misreported as a full four-scope profile acceptance check.
- Live native: owner reported successful email/password sign-in after the policy change. Browser verification confirmed the authenticated dashboard and My Profile showing the designated native identity, Nganga, and server-derived Analyst role. No enrollment was required or performed. This verifies ordinary sign-in compatibility, not fresh four-scope account-management or TOTP challenge acceptance.
- Production Streamlit: configuration fingerprints match; no deployment or production interaction performed.
- Live enrollment, TOTP challenge, disabling/removal, lost-device recovery and email change: **not performed**. Owner approval is required for live enrollment/recovery. Earlier Phase 4D password/recovery acceptance remains historical and is not repeated or rebranded as Phase 4E MFA evidence.

Commands run: `venv/bin/python -m pytest -q` from repository root; `npm test`, `npm run lint`, `npm run build` from frontend. Logs: `/tmp/powerflow-phase4e-full-backend-final.txt`, `/tmp/powerflow-phase4e-ui-final3.txt`, `/tmp/powerflow-phase4e-lint.txt`, `/tmp/powerflow-phase4e-build.txt`. The initial DOM harness needed JSX configuration/DOM initialization corrections; final runs passed without those harness failures. Temporary responsive fixtures were removed before the final runs.

## Local commands and acceptance boundary

Start the API with the existing server identity configuration (no root/IAM credentials required at runtime), keeping enrollment disabled:

```sh
# repository root; requires existing non-secret POWERFLOW_API_COGNITO_* configuration
POWERFLOW_ACCOUNT_TOTP_ENABLED=false venv/bin/python -m uvicorn api.app:app \
  --app-dir src --env-file .env --host 127.0.0.1 --port 8000
```

The `--app-dir src` option resolves the existing `api.app` module. Do not expose a development API publicly. React:

```sh
cd frontend
npm install
npm run dev -- --host localhost --port 5175 --strictPort
```

Use the already allowed callback `http://localhost:5175/auth/callback`. Do not change Cognito callbacks or attempt another origin to bypass configuration. In a fresh native session, basic sign-in was sufficient for the completed compatibility check; do not start enrollment or recovery. No feature flag needs enabling for basic sign-in verification.

After a **separate, explicit approval naming a designated test account**, enable the release flag for a controlled one-worker API, complete fresh four-scope native login and verify setup/TOTP sign-in. Owner enters authenticator codes personally. Never send a secret, QR, password or code in chat, screenshot or log. Verify recovery/support behavior separately, without changing any group or bypassing MFA; Google Admin cannot be used as a native test substitute.

The initial [audit acceptance plan](phase4e-account-security.md#manual-acceptance-plan-after-approved-configuration-and-implementation) lists the broader production prerequisites. No production readiness claim is made before those checks pass.

## Files created or changed

- `.env.example`: disabled-by-default enrollment release flag.
- `src/api/app.py`: bounded enrollment store, release flag and route registration.
- `src/api/account_routes.py`: live MFA status/management capability in own-profile response.
- `src/api/account_service.py`: narrowly allowlisted token-only MFA calls and sanitized provider errors.
- `src/api/mfa_service.py`, `src/api/mfa_routes.py`: ephemeral coordination and guarded enrollment routes.
- `tests/test_account_management.py`, `tests/test_mfa.py`: regression fixture extension and isolated MFA/security tests.
- `frontend/src/api/client.ts`, `frontend/src/api/profile.ts`, `frontend/src/api/mfa.ts`: typed contracts, safe errors and authorized calls; legacy profile compatibility fails closed.
- `frontend/src/pages/ProfilePage.tsx`, `frontend/src/components/account/MfaSettings.tsx`, `frontend/src/index.css`: shared account-security UI and responsive styles.
- `frontend/package.json`, `frontend/package-lock.json`, `frontend/tests/register-tsx.mjs`, `frontend/tests/dom-environment.ts`, `frontend/tests/mfa.test.tsx`: development-only interaction-test tooling and tests.
- `frontend/docs/phase4e-account-security.md`, this report: historical audit and applied/implementation evidence.

Protected backup files are ignored and must not be staged. No Streamlit, model, pipeline, market calculation or deployment source was edited.
