# Phase 4D — Account management and security

> Updated verification: see [Phase 4D.1](phase4d1-scope-diagnosis.md). Fresh Google and native four-scope authentication, own-profile editing, native Analyst restrictions, password change, logout/reauthentication and owner-completed native recovery now pass. The historical rejection below is retained as earlier evidence; its exact provider-side cause was not established. Provider attribute-policy hardening and separate production review remain pending.

Implementation status: ordinary Google sign-in and authenticated dashboard access were verified. Account self-service remains blocked by a live Cognito scope rejection; real account mutations still require acceptance testing. Do not deploy on the basis of mocked tests alone.

## Audited capabilities

Read-only Cognito inspection used the refreshed default AWS CLI profile. No user records, credentials, tokens or raw claims are included here.

| Capability | Current configuration | Implemented behavior |
| --- | --- | --- |
| Native sign-in | Email is the username attribute; case insensitive | Existing managed email/password login retained |
| Username / both aliases | Username aliases are not configured | No username sign-in claim; changing aliases requires separate migration review |
| Google | Existing configured provider | Preserved; linked identity shown only when reported by Cognito |
| Name | Mutable; Google maps name | Native name editing; Google name managed by Google |
| Preferred username | Mutable standard attribute | Editable profile label, explicitly not a sign-in alias |
| Email | Mutable, auto-verified, but verification-before-update is not configured | Read-only; email editing deferred pending separate pool-policy approval |
| Password | PASSWORD is an allowed first factor | Change only when GetUserAuthFactors confirms this user's PASSWORD factor; Google linkage alone proves neither presence nor absence |
| Recovery | Verified email, then verified phone | Existing managed sign-in/recovery entry; Google recovery through Google |
| MFA | Pool OFF; TOTP not enabled | Honest unavailable state; no enrollment/removal controls or endpoints |
| Session revocation | Token revocation enabled | Own-account GlobalSignOut, requiring authentication within ten minutes |
| Preferences | No persisted preferences exist | No fake preference controls |

Attribute permissions omitted on the SPA client use Cognito defaults. Current mutable attribute policies are an audited configuration, not permission to change pool settings. Provider rejection remains authoritative; configuration drift requires reassessment. Unknown password capability hides password editing rather than guessing.

## Approved configuration change

The user explicitly approved adding **only** `aws.cognito.signin.user.admin` to the existing React SPA client's AllowedOAuthScopes. This was applied and re-described: only that scope list changed (apart from modification time). Existing `openid email profile`, Google, callbacks, logout URLs, grants and all other described client settings were preserved. No pool-wide or Streamlit client settings changed.

Ordinary sign-in requests the original `openid email profile`. The explicit account-settings reconnect requests `openid email profile aws.cognito.signin.user.admin`, keeping basic dashboard access independent of self-service enrollment. This reserved scope permits the signed-in user to manage their own Cognito account; it does **not** confer PowerFlow Admin privileges. Existing sessions require fresh sign-in to obtain it. Restart Vite and reload the browser after changing OIDC settings; hot reload alone can retain an already initialized manager.

## Server boundary

New routes, under the existing production `/api` proxy prefix:

| Route | Access and permitted output/action |
| --- | --- |
| GET `/account/profile` | Verified own access token + self-service scope; allowlisted identity, signed application role and audited capabilities |
| PATCH `/account/profile` | Same; name/preferred_username only, own account |
| POST `/account/password` | Same plus confirmed PASSWORD factor; Cognito verifies current password |
| POST `/account/sign-out-all` | Same plus recent signed auth_time; own-account GlobalSignOut |

No target account identifier is accepted. Query parameters, extra fields, email/role changes and oversized bodies are rejected. Passwords use secret input fields, never database persistence or response echoing. Errors are fixed safe messages. Responses use no-store. No new IAM credential access, administrative endpoints, email-update endpoints or MFA endpoints were introduced.

Existing JWT issuer/signature/expiry/token-use/client/group checks remain. All protected requests additionally validate activity with Cognito: GetUser for the new scope, trusted OIDC userInfo for older sessions. This closes offline-JWT revocation gaps. There is no active-session result cache. The trusted discovery URL is cached briefly; tokens are never cached by this gateway. Cognito unavailability fails closed with a sanitized 503. This adds outbound latency and availability dependence to protected routes and needs production capacity/reliability review. Public routes retain their existing access policy; no authorization was broadened.

Global sign-out revokes Cognito sessions, not the upstream Google session. Other services that validate only JWT signatures may accept tokens until expiry. This phase does not modify Streamlit's implementation or assert immediate revocation there.

## Verification evidence and limits

- Backend: 555 tests passed, including 27 account/security regression cases; one existing Starlette/httpx deprecation warning.
- Tests use actual signed test JWTs with mocked JWKS and Cognito HTTP responses. They cover native/Google/unknown password capability, own-attribute changes, validation, forbidden targeting, secret redaction, body limits, unauthorized/expired/wrong issuer/client, old scope, recent authentication, revocation and upstream failures.
- Frontend: 41 tests passed; tests cover safe profile parsing, field/password validation, native versus linked accounts, authenticated account calls and sanitized errors. Lint and production build also pass.
- Real Cognito: read-only configuration audit and trusted OIDC discovery succeeded. An existing Google session passed live userInfo and existing protected API authorization. The redesigned profile rendered with real identity and the reconnect requirement for its old scope. Managed login displayed the approved four scopes and existing Google/email options.
- **Live follow-up:** the user completed ordinary sign-in; the authenticated Executive Overview and real profile identity were verified. The account endpoint correctly requested reconnection. The explicit four-scope Google flow returned Cognito `invalid_request`: “Client is not allowed to request these scopes”. A subsequent read-only DescribeUserPoolClient confirmed all four scopes are currently allowed. The mismatch remains unresolved; no additional AWS changes were made. Basic sign-in retains its original three scopes; only explicit account reconnect requests the additional permission. No real profile mutation, password change, recovery completion, global sign-out or native password account was tested. Account management remains gated, Desktop, 820px tablet and 390px mobile profile layouts were inspected; mobile identity wrapping was corrected. Editable form layouts still need live acceptance once account permissions work. No account attributes/passwords were changed for testing.

## Local acceptance

From the repository root, with the existing local API identity environment configured:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./venv/bin/python -B -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```sh
cd /Users/iannganga/Desktop/electricity-trading-pipeline/frontend
npm run dev -- --host localhost --port 5175 --strictPort
```

Use `http://localhost:5175/` (not 127.0.0.1), matching approved callback `http://localhost:5175/auth/callback` and logout `http://localhost:5175/`. Reuse running servers rather than starting duplicates. Backend environment names are `POWERFLOW_API_COGNITO_ISSUER` and `POWERFLOW_API_COGNITO_CLIENT_IDS`; use the existing `.env.example` public values without adding secrets. Account operations need only the user's verified access token, not AWS CLI credentials.

1. Reload, start a fresh sign-in, complete Google/native login and verify callback returns once without URL parameters. If it fails, retain the safe error and investigate before deployment; do not weaken state/nonce validation.
2. Verify profile identity, Google name restriction, editable preferred label, and native name editing with a real consenting account. Save a deliberate reversible change and verify it persists after reload.
3. A native PASSWORD account should show password change. Account owner enters current/new/confirmation and submits; verify wrong-current-password handling. Never send passwords or verification codes to chat.
4. Recovery delegates to Cognito or Google; email and MFA settings remain read-only/unavailable.
5. Test all-device sign-out with awareness that it ends other Cognito sessions. After ten minutes it should request fresh authentication. Confirm another PowerFlow session is rejected on its next protected request.
6. Recheck all seven routes and mobile/tablet profile forms/navigation. Check cancelled edits, network failure/retry, expired session and logout.

Regression commands:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./venv/bin/python -B -m pytest -q -p no:cacheprovider
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
```

## Files in this phase

Backend: `src/api/account_service.py`, `src/api/account_routes.py`, `src/api/security.py`, `src/api/app.py`, `tests/test_account_management.py`, `tests/test_api_security.py`, `tests/test_api.py`.

Frontend: `src/api/profile.ts`, `src/api/client.ts`, `src/auth/profilePresentation.ts`, `src/auth/signOutCurrentSession.ts`, `src/auth/authErrorMessage.ts`, `src/auth/SignInScreen.tsx`, `src/auth/SignOutButton.tsx`, `src/auth/oidcSettings.ts`, `src/components/account/AccountSection.tsx`, `src/components/account/ProfileEditor.tsx`, `src/components/account/PasswordForm.tsx`, `src/components/layout/AppLayout.tsx`, `src/hooks/useApi.ts`, `src/pages/ProfilePage.tsx`, `src/index.css`, `tests/profile.test.ts`, `tests/auth.test.ts`, this document and the authentication guide supersession note. Paths in this paragraph are relative to `frontend/`.

Pre-existing `.env.example` and `requirements.txt` edits are outside this phase. No dependencies added in Phase 4D. No commit, push, merge or deployment performed.

## Primary references

[Cognito attributes and aliases](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-attributes.html), [UpdateUserAttributes](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_UpdateUserAttributes.html), [GetUserAuthFactors](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_GetUserAuthFactors.html), [access-token scope](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html), [userInfo](https://docs.aws.amazon.com/cognito/latest/developerguide/userinfo-endpoint.html), [token revocation](https://docs.aws.amazon.com/cognito/latest/developerguide/token-revocation.html), [GlobalSignOut](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_GlobalSignOut.html).
