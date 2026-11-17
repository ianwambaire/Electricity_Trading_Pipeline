# Phase 4D.1 — Cognito scope diagnosis and native test-account handoff

> Follow-up: [Phase 4D.2 identity security review](phase4d2-identity-security-review.md) contains the current attribute-permission audit, application error-handling fixes and unapplied AWS allowlist proposal.

## Result

The four-scope Google authorization flow now succeeds against real Cognito without another AWS change. Profile retrieval and a reversible permitted profile update succeeded. Ordinary three-scope sign-in remains unchanged. Native email/password sign-in, four-scope self-service access, server-verified Analyst authorization, profile editing, password change, sign-out/reauthentication, and owner-completed managed recovery are now verified. See the final acceptance result below; earlier pending entries are chronological evidence.

Two different failures must be distinguished:

1. **Old session, account API 403:** confirmed missing self-service scope. Existing refresh tokens do not upgrade permissions merely because the client configuration changed. The supported fix is an explicit fresh authorization-code interaction requesting the additional scope.
2. **Earlier Cognito `invalid_request`:** the callback contained “Client is not allowed to request these scopes”, with no authorization code. This was an authorization-stage failure, before token exchange or GetUser. That exact historical cause cannot be established from retained evidence: DescribeUserPoolClient already showed the scope allowed, and the same four-scope flow now succeeds without a configuration change. Delayed provider configuration propagation or a previously initiated authentication transaction are possibilities, not proven root causes. Do not report the historical mismatch as definitively diagnosed.

The approved scope update's saved LastModifiedDate was 2026-10-21 06:22:55 UTC. During this audit (approximately 07:26–07:34 UTC) the saved scope list still matched and fresh Google authentication succeeded. No scope addition, client rewrite or pool change was performed in Phase 4D.1.

## Verified saved configuration (read-only AWS CLI)

Pool `us-east-1_NLoYFRvex`; SPA client `4t8s6a673a18qhbauqac8rhdcf`:

- AllowedOAuthScopes: `aws.cognito.signin.user.admin`, `email`, `openid`, `profile`.
- Code grant enabled; COGNITO and Google enabled; public client, no client secret.
- Callback `http://localhost:5175/auth/callback`; logout `http://localhost:5175/`.
- Domain `us-east-1nloyfrvex` maps to that same pool, ACTIVE, managed login version 2.
- Local frontend public environment settings match these identifiers and URLs.
- Pool uses case-insensitive email usernames; no username aliases.
- ReadAttributes and WriteAttributes omitted: provider defaults, **not** empty permissions.
- No custom schema attributes; no Lambda triggers configured. Authorization uses the signature-verified `cognito:groups`, never editable profile fields.

Reproducible read-only commands (use the default authenticated AWS CLI profile):

```sh
aws cognito-idp describe-user-pool-client --region us-east-1 --user-pool-id us-east-1_NLoYFRvex --client-id 4t8s6a673a18qhbauqac8rhdcf --query 'UserPoolClient.{ClientId:ClientId,UserPoolId:UserPoolId,Scopes:AllowedOAuthScopes,Flows:AllowedOAuthFlows,OAuthEnabled:AllowedOAuthFlowsUserPoolClient,Providers:SupportedIdentityProviders,ReadAttributes:ReadAttributes,WriteAttributes:WriteAttributes,Callbacks:CallbackURLs,LogoutURLs:LogoutURLs,Modified:LastModifiedDate}' --output json --no-cli-pager
aws cognito-idp describe-user-pool-domain --region us-east-1 --domain us-east-1nloyfrvex --query 'DomainDescription.{Domain:Domain,UserPoolId:UserPoolId,Status:Status,ManagedLoginVersion:ManagedLoginVersion}' --output json --no-cli-pager
aws cognito-idp describe-user-pool --region us-east-1 --user-pool-id us-east-1_NLoYFRvex --query 'UserPool.{UsernameAttributes:UsernameAttributes,Aliases:AliasAttributes,RegistrationRestricted:AdminCreateUserConfig.AllowAdminCreateUserOnly,PasswordPolicy:Policies.PasswordPolicy,FirstFactors:Policies.SignInPolicy.AllowedFirstAuthFactors,Recovery:AccountRecoverySetting,Schema:SchemaAttributes[*].{Name:Name,Mutable:Mutable},Triggers:LambdaConfig}' --output json --no-cli-pager
```

## Actual React request and scope confirmation

The browser-generated managed-login URL and its Google continuation both contained exactly the intended SPA client and localhost callback, `response_type=code`, all four space-delimited scopes, `code_challenge_method=S256`, a nonempty challenge, fresh state/nonce and `prompt=login`. Google receives its own normal `openid email profile` scopes; Cognito's self-service scope belongs to the downstream Cognito access token, not a Google API permission.

Fresh Google account selection returned to `/profile`; the account controls appeared and GetUserAuthFactors correctly reported no native password for this account. The scope was confirmed **server-side**, without reading browser token storage or printing/persisting raw JWTs: GET `/account/profile` returns 200 only after JWT signature/issuer/client/token-use/expiry verification, exact self-service scope membership, live token-authorized Cognito GetUser, and subject matching. The successful own-attribute PATCH enforces the same boundary. This is stronger evidence than an unverified browser JWT decode. No token or authorization code was copied to reports or fixtures.

## Minimal implementation

- Keep ordinary login at `openid email profile`.
- Centralize explicit account reconnect in `accountSigninRequest()`: four scopes, prompt=login, fresh nonce, fixed profile return destination. The established OIDC library creates independent state and S256 verifier/challenge and consumes each callback once.
- Never attempt permission acquisition by silent refresh, reuse an old callback, weaken backend scope checks, or clear unrelated browser storage.
- Give the known Cognito scope rejection a fixed safe error message. Arbitrary error descriptions remain hidden.
- Regression tests exercise the actual installed OIDC library for the reconnect request and retain old-session, replay, nonce, expiry and permission tests.
- No new dependencies, privileged runtime credentials, alternate password authentication, or AWS changes.

## Attribute permission findings — important remaining limitation

FastAPI permits only own `name` and `preferred_username` updates. It rejects email, verification flags, role/groups, other-user identifiers, arbitrary extra fields and query targets. Google-mapped name stays read-only. A native password change uses Cognito's own current-password verification. App roles are derived exclusively from signed Cognito group membership; the self-service scope does not make an Analyst an Admin.

**The Cognito client itself still has broad default attribute permissions.** A holder of a self-service token can bypass the PowerFlow UI and invoke Cognito's permitted own-account operations directly. UI/FastAPI allowlists cannot prohibit those provider operations. In particular, required `email` is writable; the pool does not require verification before an update takes effect. Therefore this audit cannot certify that all security-sensitive attributes are read-only at the identity provider. Email editing remains absent from PowerFlow, but that alone is not a provider-level restriction.

Cognito does not permit ordinary app-client writes to `email_verified` or `phone_number_verified`; these require verification or privileged administration. No mutable application-role/custom authorization attribute exists in the audited schema. Existing signed-group authorization remains the privilege boundary.

**Proposed separate hardening review, not applied:** replace default SPA attribute permissions with explicit minimal ReadAttributes (`sub`, `email`, `email_verified`, `name`, `preferred_username`, `identities`) and WriteAttributes (`email`, `name`, `preferred_username`). Preserve required email and Google-mapped name/email; verification flags cannot be writable. Re-test Google mapping with the explicit list before deployment. This narrows unrelated standard attributes but cannot prohibit required-email updates. Any policy requiring verification before email changes, restrictions across other pool clients, or stricter separation of native/federated management needs a separately approved identity-policy design. This phase makes no such change.

Sources: [AWS app-client permissions](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html), [attribute permissions](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-attributes.html), [reserved self-service scope](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html), [authorization endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html).

## Acceptance evidence

| Check | Real Cognito result |
| --- | --- |
| Fresh Google + requested four scopes | Passed, exact request inspected |
| Access-token self-service scope | Passed via server-verified scope gate and live GetUser |
| Own permitted profile retrieval | Passed |
| Allowed attribute update | Passed on user-designated Google test account; preferred username changed to a test value, persisted through reload, then restored to its original value |
| Google native password assumption | Correctly reports no configured native PASSWORD factor; no change-password control |
| Read-only fields | Google name not editable; email read-only; no MFA controls |
| Own-account targeting / role escalation | Backend signed-token regression tests; no deliberate real-account escalation attempted |
| Current-session sign-out | Passed; reload remains at sign-in gate |
| Native four-scope login | Passed after owner credential entry; server-verified self-service profile and PASSWORD factor |
| Native password change and subsequent login | Passed: owner submitted change, UI confirmed success, logout/reload stayed gated, owner used changed password and authenticated Analyst profile was verified |
| Native managed recovery | Passed with owner participation: owner completed email/code/reset-password steps and reported login using the reset password; authenticated native Analyst profile and account controls were then verified in the browser |
| Analyst restrictions | Passed with real native session: server Analyst and all seven Admin-only URLs returned 403 |

No Google password, group membership, email, name or identity link was changed. The preferred label was restored. The separate native account must be verified before recording native success.

## Safe native test-account creation

Read-only pool inspection confirms `AllowAdminCreateUserOnly=false`, PASSWORD allowed, email automatic verification, and recovery through verified email (then verified phone). The native email and Google accounts should use **different email addresses controlled by the owner**. Avoid the same email, alias-linking, federation-linking or force-alias operations.

1. From local PowerFlow choose Continue to sign in, then **Create an account** on Cognito. This navigation does not create a user.
2. The account owner enters a separate test email, a unique password (prefer a password manager), and submits registration personally. Current policy: at least 8 characters, uppercase, lowercase, number and symbol. Longer unique passwords are preferable. Do not send passwords or codes to the agent.
3. The owner completes the email verification code and sign-in. No Admin group is assigned by PowerFlow. With no configured group-assignment triggers, this account is expected to be Analyst; verify the authenticated server role rather than assuming.
4. Open My Profile → Enable account settings → Sign in again. Use the same native account to obtain the explicit four-scope session. Verify profile and native PASSWORD capability.
5. Test allowed native name/preferred label changes and restore them. Confirm the server denies Admin-only panels/endpoints. Do not add this user to `powerflow-admins`.
6. Test password recovery via Cognito's managed sign-in **Forgot password** flow. The owner enters email, code and new password and submits personally. Confirm the new password works; never enter credentials into chat.
7. Test local sign-out/reload and fresh native sign-in. Optional password-change testing likewise requires owner entry/submission. No automatic account deletion or user linking is part of this phase.

Creation, password entry and verification are an account-owner handoff. No account was created by the agent and no pool policies were changed. Native tests remain pending until the owner replies that registration is complete.

## Validation and files

Backend: 558 tests passed (one existing Starlette/httpx deprecation warning). Frontend: 43 tests passed. Lint, production build and diff whitespace checks passed. Phase-specific changed files: `frontend/src/auth/oidcSettings.ts`, `frontend/src/pages/ProfilePage.tsx`, `frontend/src/auth/authErrorMessage.ts`, `frontend/tests/auth.test.ts`, `frontend/tests/profile.test.ts`, `tests/test_account_management.py`, this report and the Phase 4D report supersession note. Existing Phase 4D dirty files were preserved. No deployment, commit, push or merge.

Local startup remains as documented in [Phase 4D](phase4d-account-security.md#local-acceptance).


## Native acceptance follow-up — 21 October 2026

The owner created and email-verified a separate native test account, then signed in. The existing `/auth/me` endpoint reported **Analyst**. A temporary development-only UI used the existing authenticated API client to call the actual protected URLs; it displayed only verified role and HTTP status, never tokens or response bodies. All seven returned **403**:

- `/admin/forecast/provenance`
- `/admin/monitoring/forecast-vintages`
- `/admin/monitoring/exogenous-readiness`
- `/admin/models/linear-feature-influence`
- `/admin/operations`
- `/monitoring/forecast-vintages`
- `/monitoring/exogenous-readiness`

The temporary check was removed immediately after collecting results. No backend authorization or AWS setting changed. The initial native session had only ordinary login scopes: the profile correctly requested explicit account reconnection. Four-scope native reauthentication, saving the owner-selected display name **Nganga**, and password flows remain in progress and require owner password/code entry. The Google Admin identity was not used or modified during these native checks.


The native follow-up re-ran frontend validation after removing the temporary harness: 43 tests passed; lint/build/diff checks passed. No backend code changed during this follow-up; the full 558-test backend result above remains the applicable regression baseline. The agent opened Cognito's explicit four-scope native login and handed credential entry to the owner before proceeding. No passwords or codes were read or entered by the agent.


### Native self-service permission and profile update

After the owner completed the explicit native reauthentication, `/account/profile` succeeded and reported Analyst plus a confirmed native PASSWORD factor. The account displayed no Google-connected-account section. This confirms the required scope through the signature-verified backend scope gate and live Cognito GetUser, without token extraction. The owner-selected display name **Nganga** was saved through the own-account PATCH and appeared after reload. The existing preferred label was preserved. Password-change and recovery submission remain owner handoffs; no success is claimed until their result and subsequent authentication are verified.


### Native password change and logout

The owner personally entered and submitted the native account's password change. The application displayed **“Your password has been changed.”**, confirming the real Cognito ChangePassword call completed successfully through the authenticated backend. No password was read, entered or stored by the agent. Current-session sign-out returned to the sign-in gate, and a full reload remained signed out. Fresh sign-in with the changed password and subsequent managed recovery are separate pending owner-input steps; password-change success alone is not recorded as proof of either.


### Changed-password reauthentication

The owner reported successful native login using the changed password. Browser verification then confirmed the authenticated native profile, persisted display name **Nganga**, server-derived Analyst role, and working self-service account controls. The agent opened the existing managed-login recovery entry and selected the native account email; recovery code/new-password input and submission remain an owner handoff.


### Managed recovery handoff

Changed-password login was followed by browser confirmation of the native Analyst profile with saved name **Nganga** and working account controls. Through My Profile → Open sign-in options, the agent navigated to the existing Cognito native password step and **Forgot your password?**. The managed recovery page displayed email entry and **Reset my password**. Email submission/code retrieval/new-password entry/final submission were handed to the owner. Recovery delivery, reset completion and login with the reset password remain pending; no completion is inferred from the page merely being available.


## Final native acceptance result — 21 October 2026

The owner completed Cognito recovery, entered the emailed code/new password personally, and reported successful login with the reset password. Browser verification then showed the authenticated native account, server-derived **Analyst**, verified email, saved display name/preferred label **Nganga**, and functional self-service controls including confirmed native PASSWORD capability. This supersedes earlier pending native-test entries above. Credential and code contents were never inspected, recorded or entered by the agent.

Completed real-account checks:

- Native registration/email verification and ordinary native sign-in (owner performed registration/credentials).
- Explicit native four-scope reauthentication, server-verified scope enforcement and live Cognito GetUser/GetUserAuthFactors.
- Server `/auth/me` role Analyst; all seven Admin-only routes returned HTTP 403 with the native session, including legacy monitoring aliases.
- Native permitted display-name edit and persistence after reload; owner explicitly requested retaining **Nganga**.
- Real password change (owner submitted), success confirmation, local sign-out/reload gate, and changed-password login.
- Managed recovery (owner completed) and reset-password login, followed by authenticated profile confirmation.

No native user group was changed. The Google Admin identity and all Cognito settings were preserved during acceptance testing. No deployment, commit, push or merge occurred. The temporary local authorization check was removed.

Regression baseline remains **558 backend tests passed** (one pre-existing Starlette/httpx warning), **43 frontend tests passed**, lint/build/diff checks passed. Subsequent acceptance turns changed documentation only; no unnecessary code or test reruns were introduced.

Remaining limitations are unchanged: the exact historical Cognito authorization-stage rejection is unproven and currently not reproducible; broad default provider attribute permissions (including required email) need separate hardening review; email editing and MFA remain unavailable in PowerFlow pending policy approval. Live cross-device GlobalSignOut/revocation and long-duration expiry were covered with mocked-provider/signed-JWT regression tests, not separate real multi-session acceptance. Production migration/security review is still required before deployment.
