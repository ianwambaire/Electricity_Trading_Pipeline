# Phase 4E.1 — controlled live TOTP verification

21 October 2026 (Africa/Nairobi). Branch `feature/react-frontend`. **Core live MFA acceptance passed, including post-login Analyst denials and sign-out. Account retention decision and explicitly untested scenarios are listed below.**

## Scope and account plan

Exactly one disposable native account: `iannganga11079@gmail.com`. The owner confirmed it did not exist and explicitly approved Cognito managed-login self-registration. The owner will choose/submit the password and email verification code in Cognito. No administrative CreateUser, group assignment, identity link, existing-account attribute/password/MFA mutation, pool/client/IdP configuration change or production authentication test is authorized. Existing Google Admin and native Nganga Analyst identities must not be used for enrollment.

Preflight used an exact email filter: zero matching accounts and no pagination token. No account was created by the agent. Account status, immutable subject and absence of Admin membership must be checked after creation and before enrollment. Store the subject only in protected local test configuration; do not publish it in this report.

## Preflight evidence

- Read-only live AWS inspection confirms the known AWS account matches the pool's saved account fingerprint, region `us-east-1`, pool `us-east-1_NLoYFRvex`, SPA `4t8s6a673a18qhbauqac8rhdcf`.
- MFA remains exactly OPTIONAL with SoftwareTokenMfaConfiguration.Enabled=true. Complete pool/configuration snapshot matches Phase 4E's protected after snapshot. Both SPA/Streamlit clients, Google provider and group configuration fingerprints match. No settings were changed.
- The active AWS CLI default profile is root; no alternate profile is configured. This is a known operational concern, not a runtime application credential. This phase will not create an operator role or other AWS resource.
- React uses Cognito-hosted authorization/login, Authorization Code + S256 PKCE, and a validated callback. Four-scope account reauthentication uses prompt=login. It does not use direct InitiateAuth or implement its own password/TOTP challenge response. Cognito must complete the native password/TOTP challenge before issuing the SPA authorization code.
- AWS documents managed-login post-password TOTP challenges and optional MFA behavior for enrolled users. This establishes supported architecture, not live acceptance of this disposable user yet. [TOTP hosted challenge](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-mfa-totp.html), [optional MFA](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_SetUserPoolMfaConfig.html).
- `src/auth.py` uses Streamlit's validated native OIDC `st.login('cognito')` against the same issuer, separate Streamlit client `5qa93km3lf2bbu3ffnrpea4r3g`; no custom Cognito challenge handler is required in the app. This supports compatibility in design. **Production Streamlit end-to-end MFA compatibility remains unresolved and is not tested without separate approval.** No Streamlit source/settings were modified.
- Self-registration is allowed by the audited unchanged pool. No Admin group is assigned by this plan. Native/federated accounts remain separate.

## Safety review and local changes before enrollment

Enrollment routes already require a verified own-account token, self-service scope, fresh auth_time, verified recovery email, confirmed native PASSWORD capability and no linked IdP. A per-user ticket/expiry/attempt limit coordinates setup. Keys/codes/tokens are not stored in the database or server setup metadata. Setup responses and errors use no-store and redacted schemas. Verification requires Cognito SUCCESS before enabling and authoritative status read-back.

A local-test subject restriction is added: `POWERFLOW_ACCOUNT_TOTP_TEST_SUBJECT` binds enrollment eligibility and profile controls to the dedicated immutable subject when set. It never uses editable email/name/role. An invalid subject disables enrollment rather than broadening it. Default release flag stays false and the test subject is empty. New isolated tests verify other subjects are excluded and a typo fails closed; 88 targeted backend tests passed before account creation/enrollment.

After native sign-in, read-only Cognito checks verified one CONFIRMED unlinked native identity for the test email, enabled with verified email, no activated MFA and no Admin group. Its exact username/subject is in ignored 0700/0600 backups/cognito-mfa-live-test/target.json. The localhost:8000 development API was restarted with enrollment true and the immutable test-subject restriction. The documented issuer/SPA client binding is preserved, AWS environment credentials were not injected, and access logging is disabled. The source/default flag remains false. No .env or AWS configuration changed. Restore enrollment false after testing; no unscoped server was started.

## Recovery and rollback — prepared before enrollment

Testing must not depend on the disposable user retaining access. Cognito has IAM-authorized `AdminDisableUser` and `AdminDeleteUser` operations independent of that user's password/TOTP. The separately authenticated AWS operator can target the exact disposable native username/subject in the known pool. These are not PowerFlow user APIs and cannot be invoked by an Analyst token. No administrative credentials are introduced into the application.

Before enrollment, confirm operator AWS session still works, read the exact disposable profile and group membership, and record its immutable target in an access-controlled ignored local file. Stop on an identity mismatch or unavailable operator session. These APIs have no no-op permission dry-run: no disable/delete has been executed merely to test permission. If an account lockout happens, stop and obtain explicit approval for the specific account action; never turn pool MFA off or alter another identity.

Account-specific options, each requiring separate explicit approval:

1. **Disable** the disposable account with `AdminDisableUser` (known pool + exact captured username) and retain it for diagnosis; no sign-in by that account is needed.
2. **Delete** only that disposable account with `AdminDeleteUser` if the owner chooses permanent cleanup; deletion cannot be undone and requires action-time approval.
3. Any administrator MFA reset/preference/recovery action needs its own exact proposal and approval; never silently lower MFA, link identities or reset existing users.

References: [AdminDisableUser](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminDisableUser.html), [AdminDeleteUser](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminDeleteUser.html). No executable cleanup command with a guessed username is prepared. The exact target is resolved only after the owner creates the one account.

Local rollback: stop the scoped development API, restart with `POWERFLOW_ACCOUNT_TOTP_ENABLED=false` and clear the optional local test-subject setting; preserve all other startup settings. This does not remove an enrolled provider factor or make a locked account recoverable. No pool-policy rollback is part of test cleanup.

## Live-test observation protocol

Before setup the agent may inspect the profile/role and confirm no factor is enabled. **The owner will click Continue setup, read the key, add it to their authenticator and submit the code. While key/code UI is present, no agent DOM/AX read, screenshot, network capture or logging inspection is permitted.** The owner must report success or a sanitized error with the key hidden/closed before browser inspection resumes. Never copy setup information to chat or evidence files. Manual instructions use a time-based, six-digit authenticator; no QR service is involved.

After enabled status is confirmed, use supported sign-out, begin a fresh SPA login, and let the owner complete password/TOTP personally. Inspect only a code-free challenge view if safe; do not observe filled fields. Confirm login success, Analyst role, real factor status and Admin-route denials. At most one deliberately expired-code check may be performed by the owner if approved in the live handoff; no generated guesses, repeated failures or brute force.

## Verification results

| Check | Result |
| --- | --- |
| AWS preflight / unchanged pool, clients, Google, groups | Passed |
| Dedicated target and self-registration method | Owner confirmed and approved |
| Exact target absence | Passed: zero matches, no pagination |
| Account creation, verification, native Analyst | Passed: owner-created confirmed native test identity; account-settings authentication/enrollment and subsequent MFA login completed. Server role/access check owner-confirmed Analyst; no Admin group verified read-only |
| Enrollment / authoritative enabled status | Passed: owner reports enabled UI after code submission; read-only exact native subject has SOFTWARE_TOKEN_MFA enabled and preferred, still no Admin group |
| Sign-out → TOTP challenge → successful login | Passed, owner performed supported sign-out, confirmed Cognito authenticator challenge, then explicitly confirmed return to Analyst profile |
| Live invalid/expired code | Not tested |
| Admin endpoint denials after live MFA | Owner confirmed the requested read-only check: server role Analyst and HTTP 403 on all seven Admin routes |
| Existing-account regression in Phase 4E.1 | Not repeated; Phase 4E Google Admin/native Analyst login evidence remains historical |
| Existing profile edit/sign-out | Prior evidence only; no existing-account attribute write authorized here |
| Production Streamlit MFA | Not tested; separate production-readiness requirement |
| Cleanup | Local enrollment runtime restored false; temporary access checker removed. Native test account remains MFA-enabled pending owner retention/cleanup decision; no disable/delete performed |
| Full automated regression / frontend lint/build | 616 backend passed; frontend subsequently 56 passed after pending-setup UI repair; lint/build and diff check passed. One existing backend deprecation warning |

## Remaining limitations

Single-process setup coordination; no lost-device self-service, backup codes, factor removal or email-change UI. Optional pool MFA does not protect all users and Google MFA remains provider-managed. A managed-login session cookie/refresh is not proof a fresh TOTP challenge was completed; acceptance requires actual sign-out, password prompt, TOTP challenge and successful return. No production readiness claim is made before that sequence and separately authorized compatibility/recovery tests.

No staging, commits, pushes, merges, deployments or Git history changes will be performed.

## Owner-registration handoff / isolation blocker

A fresh agent-created SPA tab restored the existing Nganga identity through the browser's shared Cognito session cookie. That was not a fresh disposable-account password login and is not counted as acceptance. Opening the existing profile's sign-in-options action was rejected by automatic approval review because it would initiate reauthentication/session changes for the existing Analyst, outside the approved isolation scope. The action was not retried or bypassed. No existing attribute, group, password or MFA mutation occurred, and no disposable account was created.

Continue through owner-led Cognito self-registration in a separate private browser session for exactly the approved test email. The owner enters/submits password and email code directly, then leaves that test account's authenticated PowerFlow session available. Enrollment is still off locally; no key or code has been generated or observed. Do not treat the automatic shared-cookie identity as the new test account.

Local changes in this stage: `src/api/mfa_service.py`, `src/api/app.py`, `src/api/account_routes.py`, `src/api/mfa_routes.py` add/use the optional immutable-subject enrollment scope; `.env.example` documents it; `tests/test_mfa.py` adds two scope/fail-closed cases; this report records preflight and pending evidence. Existing Phase 4E working-tree changes were preserved. No staging/commit/push.

Automated commands: `venv/bin/python -m pytest -q` (616 passed in 30.15s), frontend `npm test` (54 passed), `npm run lint`, `npm run build`; `git diff --check` passed. Logs: `/tmp/powerflow-phase4e1-backend.txt`, `/tmp/powerflow-phase4e1-frontend.txt`, `/tmp/powerflow-phase4e1-lint.txt`, `/tmp/powerflow-phase4e1-build.txt`. Responsive Phase 4E evidence remains historical; no new enrollment-layout check or live success is claimed at this pre-account handoff.

## Registration follow-up — native and Google identities found

The owner supplied a screenshot from a different Chrome profile. It showed the approved disposable email with Google-managed name/password and provider-managed two-step verification. A read-only exact-email lookup then returned **two** enabled, verified identities: one EXTERNAL_PROVIDER with Google linkage and one CONFIRMED native record with no linked identities; no further page of results. The original pre-registration lookup had returned zero. Account creation was owner-led; the agent created neither record.

The visible session is the Google identity, not a native TOTP acceptance session. Do not create another account, link the subjects, assign a password to the Google identity, or delete either record. Only the confirmed native record is eligible for the approved test. Its immutable subject must be selected and checked for no Admin membership before the local gate is enabled. The additional Google identity is an unexpected deviation from the one-account plan and is excluded from live mutations; any cleanup needs separate explicit approval.

Owner action requested: use supported sign-out for this test-email session, then Cognito's existing-account email/password fields instead of Google. Enter credentials only in Cognito. If native sign-in fails, report the sanitized error; do not start recovery, create a duplicate, or change another account. Local enrollment remains disabled, and no setup secret, code, factor or account setting has been modified by the agent.

## Native account ready / scoped local server

The owner supplied the native NewAnalyst profile screenshot for the approved test email. It shows Analyst and an account-settings reconnection requirement. Cognito read-only checks confirmed the exact native target. The Google identity sharing the email is excluded, as are Nganga and the original Google Admin. No TOTP key/code was generated, read, printed or captured.

Temporary API lifecycle helper: /tmp/powerflow-scoped-mfa-server.py. After completing or stopping tests, run `python3 /tmp/powerflow-scoped-mfa-server.py restore` (local process permissions may be required), then confirm health and that enrollment is unavailable. The helper checks the recorded local uvicorn process before acting, restores the enrollment-off state, and does not touch AWS or .env. Protected original/scoped supervisor records and startup logs are in backups/cognito-mfa-live-test/; do not publish them.

Historical owner handoff at this stage: use Sign in again on the dedicated native profile and complete Cognito email/password reauthentication to authorize account settings. Do not start setup before initial status is checked. This is not approval to enroll the Google identity or either original account.

## Account-settings reauthentication / enrollment handoff

Owner reported account-settings native reauthentication completed. The disposable Chrome profile is not exposed by the browser-control connector (only the original profile is listed); no attempt was made to operate the original profile or bypass the previous review rejection. UI evidence for the dedicated profile will therefore be owner-confirmed and distinguished from read-only provider evidence.

Immediately before enrollment, a fresh IAM-authorized read of the exact captured native username confirmed the immutable subject and email, no identities attribute, enabled/CONFIRMED status, verified email, no activated MFA factors and no Admin group. The operator read session is working. No enrollment mutation was performed by the agent.

Owner-only next step: in that dedicated native profile, use Set up authenticator → Continue setup, enter the displayed manual key into a time-based authenticator app, then enter/submit its six-digit code directly in PowerFlow. Never send or screenshot the key/code. No agent UI observation is permitted during this step. Await sanitized success/error report with the setup key hidden before reading provider state. Do not switch accounts or repeat enrollment after an uncertain result.

## Pending-setup failure and local UI repair

Owner reported adding the manual key to an authenticator but seeing only Continue setup/Cancel with MFA_SETUP_IN_PROGRESS; no code-entry form remained. A read-only lookup of the exact native test subject confirmed no activated factors, no preferred factor and the account still enabled. This is **not successful enrollment** and no subsequent MFA login is claimed.

Source inspection found a reproducible defect: visibilitychange-to-hidden cleared the entire setup state and opaque ticket while the backend retained its five-minute enrollment reservation. Returning and starting again could therefore hit the in-progress guard. The actual browser event was not captured, so this is a reproduced causal path matching the symptom, not a claim of having observed the owner's hidden-page event. No secret-bearing UI, key, code, token or runtime process memory was inspected. No administrative factor reset or repeated provider association was performed by the agent.

The UI now clears only the displayed setup key and typed code on hiding, retaining the memory-only opaque ticket, code form and original expiry. It does not persist the ticket/key/code in browser storage. Returning does not redisplay the key or extend the lifetime. Unmount, cancel, success and expiry still clear setup state. An in-progress error without a ticket now offers status refresh, not a repeated Continue setup action. Backend own-account, freshness, rate/expiry and subject gates are unchanged.

Regression tests reproduce hide/return/verification with the same ticket, ensure the key is absent, typed code cleared, one association request only, and expiry timer not extended. Another case covers the abandoned-setup error. **56 frontend tests, lint, production build and diff check passed**. Backend code was unchanged in this repair; the Phase 4E.1 full backend result remains 616 passed. Logs: /tmp/powerflow-phase4e1-pending-ui-tests.txt, /tmp/powerflow-phase4e1-pending-lint.txt, /tmp/powerflow-phase4e1-pending-build.txt.

Controlled retry handoff: reload the dedicated test profile, allow at least five minutes since the last Continue setup attempt, then start exactly once. A new association generates a new key; owner must update only the unverified disposable-test authenticator entry and use its new code. If the code field is absent or an error recurs, stop and report only the message; do not keep restarting. If freshness expired, complete native account reauthentication first. Never send setup screenshots or secrets. Local runtime remains restricted to the exact disposable native subject; other identities and AWS policies are unchanged.

## Live enrollment confirmed

Owner reported “Authenticator enabled for native sign-in” after completing the setup in the authenticated UI, and confirmed the setup now works. A read-only AdminGetUser/AdminListGroupsForUser check of the captured native subject verified SOFTWARE_TOKEN_MFA is activated and preferred, account remains enabled, no linked identities, and no powerflow-admins membership. Sanitized evidence is protected in backups/cognito-mfa-live-test/enrollment-verification.json; no key/code/token was inspected or saved.

Enrollment was subsequently followed by the full supported sign-out → Cognito authenticator challenge → successful return to the Analyst profile, explicitly confirmed by the owner. No authentication prompt or code-filled field was captured. This is owner-observed interactive evidence, corroborated by read-only activated-factor/group state; no raw authentication event/token was extracted.

The local enrollment gate was restored to false successfully before the subsequent-login check; backups/cognito-mfa-live-test/restored-server.json records the restored loopback process. This affects only local setup availability, not the account's Cognito factor or login challenge. No further association, recovery, disable/delete or AWS policy action is approved or performed here.

## Subsequent native MFA login passed

After using supported sign-out and native email/password login, the owner first confirmed Cognito requested the authenticator code, then explicitly confirmed that code submission returned to the Analyst profile. This completes the required live enrollment → sign-out → MFA challenge → successful sign-in sequence. The owner entered all secrets; the agent captured none.

Read-only post-login inspection confirmed the same native subject still has activated TOTP, remains enabled and has no Admin membership. Full snapshot equality initially failed; a focused comparison found **only EstimatedNumberOfUsers** changed, consistent with the owner-created native and Google identities. This is a population estimate, not a configuration setting. MFA configuration, both client fingerprints, Google provider, group definitions and AWS account fingerprint all match. No corrective AWS action was taken and no original snapshot was overwritten.

A temporary development-only read-only access checker used the existing authenticated API client to display only `/auth/me` role and seven Admin-route HTTP statuses. It created no endpoint, account mutation, user-selected role or token output. The owner confirmed the requested Analyst/403/sign-out checks, as detailed below. The component/import has been removed; it is not a permanent product feature.

## Post-MFA access and sign-out confirmation

Owner replied “It worked” to the explicit combined request to confirm server role Analyst, seven HTTP 403 results and supported sign-out returning to Sign in. Recorded as **owner-confirmed**, not independently observed browser evidence (the dedicated Chrome profile is not connected to the agent). Paths checked through the existing authorized API client:

- /admin/forecast/provenance
- /admin/monitoring/forecast-vintages
- /admin/monitoring/exogenous-readiness
- /admin/models/linear-feature-influence
- /admin/operations
- /monitoring/forecast-vintages
- /monitoring/exogenous-readiness

The temporary MfaLiveAccessCheck component and its development-only ProfilePage import/render were removed. Local enrollment is already disabled; source defaults remain false. No factor removal, recovery, account disable/delete, group change or AWS policy/client/IdP change was performed. The enrolled native account is left unchanged pending an explicit cleanup decision. Recommend retaining it as a clearly identified MFA regression account; the owner-created Google identity sharing its email is separate and was not enrolled or linked by this work.

Live invalid/expired-code rejection was not tested; automated wrong-code/attempt-limit tests passed. Lost-device recovery was not exercised. Fresh Google Admin/Nganga login was verified in Phase 4E but not repeated in Phase 4E.1; no new existing-account attribute writes were authorized. Production Streamlit MFA remains untested. These limitations do not negate the successful dedicated-account MFA login sequence and must not be represented as passed live checks.

## Final acceptance and cleanup decision

Core sequence and post-login read-only access/sign-out checks passed with the evidence distinctions above. The disposable native identity remains enrolled and enabled. Keeping it is useful for future MFA regression tests; recommend retention with its authenticator secured by the owner. No retention action changes AWS state. Disabling or deleting it requires a separate exact-target approval; no cleanup mutation will occur automatically. The extra Google identity sharing the email is untouched and needs its own cleanup decision if desired.

The local runtime release gate and source default are false. Temporary diagnostic UI is removed. The restored API remains loopback-only and uses no runtime IAM credentials. No pool/client/Google/group configuration changed during Phase 4E.1; only the expected estimated-population observation differed after account creation. Nothing was staged, committed, pushed, merged or deployed.

Final post-diagnostic-removal rerun: **616 backend tests passed in 30.79s**, one existing Starlette/httpx deprecation warning; **56 frontend tests passed**, lint and production build passed; diff check passed, index empty, temporary access component absent. Logs: /tmp/powerflow-phase4e1-final-backend.txt, /tmp/powerflow-phase4e1-final-frontend.txt, /tmp/powerflow-phase4e1-final-lint.txt, /tmp/powerflow-phase4e1-final-build.txt. No new test or AWS failures remain unexplained. Live invalid-code/recovery, fresh original-account rechecks and production Streamlit MFA remain untested as explicitly listed; automated negative cases are not substituted for live evidence.
