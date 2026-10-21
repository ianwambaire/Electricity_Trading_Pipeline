# Phase 4E.2 — authentication hardening and recovery review

21 October 2026. Branch: feature/react-frontend. Baseline: 0fb2f08.

## Scope and evidence

This phase changes local application code and isolated tests only. Read-only Cognito inspection confirmed OPTIONAL MFA, software tokens enabled, PASSWORD first factor, verified-email then verified-phone recovery, no device configuration, and an empty AttributesRequireVerificationBeforeUpdate list. No AWS configuration, users, attributes, factors, groups, clients, federation mappings, Streamlit files or deployments were changed. No live sign-in, enrollment, recovery or production compatibility test was performed in this phase. Phase 4E.1 live acceptance remains historical evidence, not a fresh check.

The operator is the default AWS root identity. It is not an application runtime credential, but routine root use is an operational risk. Replace it with short-lived, separately approved least-privilege operator access before privileged recovery; no IAM changes were made here.

## Architecture and findings

React uses managed login, Authorization Code with S256 PKCE and nonce/state checking. OIDC storage is sessionStorage, protocol logging is disabled, callbacks are cleaned, and navigation requires a usable session. Access-token expiry or renewal failure removes the local session; sign-in requires an explicit user action, preventing automatic redirect loops. Refresh failure is treated conservatively, including transient failures; this can inconvenience users but does not silently preserve rejected sessions.

FastAPI verifies RS256 signatures against trusted issuer JWKS, issuer, expiration, access token type, client binding and required scopes. Roles come exclusively from verified Cognito groups; only the exact Admin group grants Admin. Authenticated requests also perform a live provider session check. Signature verification alone cannot establish token revocation. Profile operations use the current bearer token and authenticated subject, never caller-provided target accounts or administrative credentials.

Confirmed local defects fixed:

- A delayed 401 previously invoked the current global session handler, potentially signing out a replacement identity. Requests now capture their originating binding and token. Replaced bindings and refreshed tokens ignore obsolete rejection; repeated rejection is idempotent.
- Cancellation could discard busy enrollment metadata while verification was in flight. Cancellation now returns a conflict and preserves serialization.
- An externally enabled factor could make an unverified setup return success. Success reconciliation now requires this setup's prior provider verification and confirmed preferred TOTP status.
- Broad password error classification could mislabel disabled/rejected sessions as an incorrect password. Only explicit incorrect-password responses receive that message; other authorization failures expire the session.
- Expired codes, invalid codes and failed factor confirmation now have distinct sanitized errors. OAuth invalid-grant, service unavailability and consent errors have fixed actionable messages without echoing provider payloads.

Existing protections retained: bounded request/response sizes, strict account input schemas, no email/role/group/target-account writes, no response-cache storage, bounded five-minute setup tickets tied to subject and authentication time, limited verification attempts, fresh authentication for sensitive operations, no persistent TOTP secret storage, no public removal/recovery endpoint, and no automatic retry of account mutations. Google-managed fields and password-factor availability are provider-derived, not inferred from email.

Residual risks are distinguished from confirmed exploits: bearer-token/sessionStorage exposure following XSS; multi-process enrollment coordination (the store is single-process and must not be represented as distributed locking); uncertain results after network interruption; and pool-wide/shared-client recovery implications. No exploit against another account or privilege escalation was demonstrated. Deploying multiple API workers requires a reviewed shared coordination design before enabling enrollment.

## Account-security interface

The existing compact Security layout, native/Google distinction, keyboard-accessible forms and confirmation controls are preserved. Recovery copy now explains that forgotten-password recovery does not remove TOTP, and Google security is managed by Google. There is no fake recovery button, support address, MFA toggle or email editor. Enrollment remains disabled by default and must not be enabled for regular users pending recovery and Streamlit acceptance. No new visual layout or live desktop/tablet/mobile verification is claimed; existing responsive styles are unchanged.

## Lost-authenticator recovery: proposal, not implementation

A password reset does not remove an authenticator. Current TOTP users have no demonstrated alternate factor or self-service lost-device bypass. Verified recovery email enables password recovery, not proof sufficient to remove MFA. Google-federated MFA recovery belongs to Google. Do not conflate native and federated accounts sharing an email; duplicate-email identities were observed in the previous test phase.

AWS documents an IAM-authorized [AdminDeleteSoftwareToken operation](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminDeleteSoftwareToken.html), which removes a user's registered software token and its preference. [AdminSetUserMFAPreference](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminSetUserMFAPreference.html) changes preferences and is not secret deletion. Neither operation is exposed by PowerFlow. In this OPTIONAL pool, removal can permit password-only access; forced reenrollment must not be assumed. See [TOTP behavior](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-mfa-totp.html).

Proposed controlled procedure, requiring separate approval and a tested containment plan:

1. Identify exact pool, immutable subject and identity type independently; never select solely by email or user-supplied label. Record an incident and two-person approval. Verify ownership using evidence and trusted organizational/contact channels established before the incident. Email possession, password knowledge, a reset request or a newly supplied phone number is insufficient alone. Escalate if independent evidence is unavailable.
2. Review suspicious activity and recent identity changes; notify the owner through an established channel and apply a reviewed waiting period where appropriate. Store minimal incident evidence, approvers, timestamps, exact target and AWS request IDs; never passwords, tokens, codes, keys or raw provider logs.
3. Use short-lived least-privilege permissions on this pool: AdminGetUser, AdminListGroupsForUser, DescribeUserPool for review; AdminUserGlobalSignOut for approved revocation; AdminDeleteSoftwareToken only for the specifically approved recovery. IAM pool-resource scope does not restrict writes to one subject: a controlled operator workflow must enforce the approved target. Account disable/enable for containment requires separate approval and grants. Do not grant user deletion, group changes, identity linking, password setting, attribute verification overrides or pool/client writes.
4. Establish containment across React AND Streamlit before deletion. A React-only restriction cannot contain other consumers of the shared pool. If password-only access cannot be safely contained, stop. Supervise fresh enrollment and a new hosted MFA challenge, verify unchanged roles, revoke emergency sessions, close the incident and notify the owner.
5. There is no rollback that restores a deleted secret. Failure requires containment and escalation, never disabling pool MFA. No live administrative command or recovery was executed.

Revocation also needs live checks: [AWS notes](https://docs.aws.amazon.com/cognito/latest/developerguide/token-revocation.html) revoked JWTs can still pass signature-only verification. PowerFlow's live provider checks are preserved. Browser sign-out clears the local app session and redirects to Cognito; it does not promise revocation of copied tokens or all Google sessions. Global sign-out is a separate fresh-authenticated action.

## Streamlit compatibility

Source inspection shows src/auth.py validates the separate Cognito client/issuer configuration and calls Streamlit native OIDC st.login('cognito') and st.logout(). It does not implement Cognito direct password challenges. Architecturally, managed login completes password/TOTP before returning the authorization code, so an application-specific TOTP handler should not be necessary. This is a compatibility assessment, not proof of the deployed Streamlit runtime, callback processing, cookie lifetime or logout behavior.

Approval-required verification: use only the designated native MFA test account; sign in through the production Streamlit Cognito entry; confirm a hosted TOTP challenge, successful callback/session, Analyst role, restricted access and logout followed by fresh authentication. Do not capture credentials/codes or modify clients. Stop on callback/session failures. The shared pool means enrolled users encounter TOTP through other compatible clients even when React enrollment is disabled. Production testing remains unapproved and unperformed.

## Verified email changes: design only

Current pool policy does not require verification before replacing email. React deliberately reports email_editable=false and the account gateway does not allow email updates. Client write permission alone does not make email editing safe.

Proposal requiring pool-policy approval: preserve other settings and add email to UserAttributeUpdateSettings.AttributesRequireVerificationBeforeUpdate. A future authenticated fresh-sign-in native-only workflow would request UpdateUserAttributes(email), keep the existing verified email active pending verification, and confirm through VerifyUserAttribute(email, code). Never write email_verified, auto-link identities, change groups, or treat new email as a stable account identifier. Reject unsupported/federated flows; throttle resend/verification, clear codes promptly and notify old and new addresses through a separately reviewed mechanism. Current backend operation allowlists intentionally do not support these operations.

Pool-wide policy affects all clients, including Streamlit, and needs a separate compatibility review. Back up the complete policy/configuration before any approved change; read back only the intended delta. Rollback would restore the exact previous verification-before-update list while preserving unrelated settings. Pending updates and already verified email replacements require separate reconciliation; policy rollback does not reverse user changes. No email change or policy update occurred.

## Acceptance and remaining approvals

Isolated tests exercise native/federated capability handling, strict own-account inputs, denied cross-account/role changes, session revocation/expiry, JWT issuer/client/scope failures, Admin/Analyst restrictions, setup ownership/expiry/serialization, provider failures and password errors. Added regressions target the defects above. They do not substitute for hosted Cognito challenge tests.

Manual checks pending separate approval: Google Admin and native Analyst fresh login/sign-out; seven Analyst Admin-route denials; designated-account permitted editing; controlled wrong/expired-code behavior; revoked-session checks; responsive keyboard/screen-reader review; production Streamlit MFA compatibility. No live recovery should occur until ownership verification, containment, operator permissions and notifications are approved. Existing dedicated MFA enrollment is preserved.

Recommended next phase: approve and validate the controlled recovery and shared-client compatibility plan, then decide whether enrollment can be enabled. Email verification-before-update is a separate proposal. No AWS changes are needed for the local hardening in this report.

## Validation results

Results are recorded below after execution. No deployment, staging, commit, push or history changes were performed.

- `venv/bin/python -m pytest -q`: **624 passed**, one existing Starlette TestClient/httpx deprecation warning, 35.85 seconds. No dependency changes were made to suppress the warning.
- `cd frontend && npm test`: **59 passed**, zero failed on final rerun (823.64 ms). An earlier concurrent run reported a test-file-level failure in mfa.test.tsx after 48.7 seconds without an assertion/stack diagnostic; the preceding run and final rerun passed. The cause is not established; do not treat this as a proven fixed test-runner issue.
- `npm run lint`: passed.
- `npm run build`: passed (TypeScript and Vite).
- `git diff --check`: passed.

Modified files: frontend/src/api/accessToken.ts, frontend/src/api/client.ts, frontend/src/api/profile.ts, frontend/src/auth/authErrorMessage.ts, frontend/src/pages/ProfilePage.tsx, src/api/account_service.py, src/api/mfa_routes.py, src/api/mfa_service.py, tests/test_account_management.py, tests/test_mfa.py. Added frontend/tests/session-hardening.test.ts and this report. No dependency, AWS or deployment files changed.
