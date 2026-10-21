# Phase 4A — React Cognito authentication

Implemented on `feature/react-frontend`. This phase adds real Cognito OIDC integration to React using the existing public SPA client. It does not change Streamlit, its confidential client, any backend route, Cognito/AWS settings, models, data or deployment. Nothing was committed, pushed, merged or deployed.

## Packages

- `oidc-client-ts` **3.5.0**: authorization code + S256 PKCE, protocol state/nonce handling, token exchange, session storage and renewal.
- `react-oidc-context` **3.3.1**: React authentication lifecycle and hooks. Its declared peers support the installed OIDC and React versions.
- npm added the transitive `jwt-decode` dependency. Install reported **0 vulnerabilities**. No test/UI framework was added.

## Public environment configuration

Copy `frontend/.env.example` to `frontend/.env.local` if local settings are absent. This session created the ignored `.env.local` using those public settings; it did not overwrite an existing file. Restart Vite after changing environment values.

| Variable | Local value |
| --- | --- |
| `VITE_COGNITO_AUTHORITY` | `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_NLoYFRvex` |
| `VITE_COGNITO_DOMAIN` | `https://us-east-1nloyfrvex.auth.us-east-1.amazoncognito.com` |
| `VITE_COGNITO_CLIENT_ID` | `4t8s6a673a18qhbauqac8rhdcf` |
| `VITE_COGNITO_REDIRECT_URI` | `http://localhost:5175/auth/callback` |
| `VITE_COGNITO_POST_LOGOUT_REDIRECT_URI` | `http://localhost:5175/` |

Scopes are fixed to `openid email profile`. No client secret is accepted or needed. Every `VITE_*` setting is public browser configuration; never put credentials or tokens there. The Streamlit client is not reused. These callback/logout URLs were supplied as already approved; no AWS configuration change was made or is requested for local Phase 4A.

Open the application on **localhost**, not `127.0.0.1`. They are separate origins with separate session storage. On the wrong origin, the sign-in screen supplies a link to the configured origin rather than starting an unusable callback flow. Invalid/missing configuration or unavailable session storage fails closed with a setup screen.

## Implemented behavior

- All seven dashboard routes require a usable OIDC session; `/auth/callback` is public so the protocol can complete. Unknown dashboard paths remain behind the same gate.
- Professional sign-in entry delegates Google/email selection, passwords, registration and recovery to Cognito managed login. No custom credential handling, fake identity or login fallback exists.
- One module-level `UserManager` and `AuthProvider` process callbacks. No page calls `signinCallback`. The installed provider guards initialization with a ref, preserving single processing during StrictMode effect replay. Successful and failed callback parameters are removed from the address bar.
- State restores only an allowlisted dashboard pathname. External destinations, callback URLs, queries and fragments are discarded. No automatic sign-in loop is used; sign-in is an explicit user action.
- Authentication transactions, PKCE verifiers and the OIDC session use app-prefixed **sessionStorage**, not localStorage. Reload restores the tab's session. Session storage requires the usual protection against XSS; it is not an HttpOnly/BFF session. No tokens are displayed or intentionally logged, and library logging is disabled.
- Automatic renewal uses the OIDC library and the issued refresh token when supplied. Expiration, renewal failure or API HTTP 401 ends local access and requires sign-in. HTTP 403 shows an insufficient-permission error without silently signing out. Network/API response errors remain sanitized. Actual long-running Cognito refresh behavior still needs account testing.
- Additional presentation checks require expected issuer/client, ID-token use, nonempty subject, ID-token expiry and access-session expiry. The code uses profile claims from the OIDC session, never an independently decoded user-supplied token. The library handles PKCE/state/nonce and obtains tokens through Cognito's HTTPS token endpoint. This **does not implement FastAPI JWT signature verification or server authorization**.
- API calls attach only the access token as `Authorization: Bearer …`, only to the existing same-origin `/api` client. ID tokens are never used as API credentials. Existing endpoints remain public/backward compatible in Phase 4A.
- Navigation uses actual name/email when provided. `Admin` requires the exact `powerflow-admins` string in a well-formed ID-token `cognito:groups` array; every other authenticated user presents as `Analyst`. These labels grant no server permission.
- My Profile displays supplied name/email and email-verification flag, Cognito as identity provider, an abbreviated subject reference, role, sign-out and managed-sign-in recovery entry. A Google link is identified only from an explicit `identities` claim and labeled as a **linked identity**, not proof of which provider was used in this particular session. Missing fields remain “Not supplied”. No direct profile editing/password-change functionality is claimed.
- Sign-out stops renewal, removes the local OIDC user, clears this app's pending transactions, then redirects to Cognito `/logout` using only `client_id` and `logout_uri`. No token is included in that URL. Cognito sign-out does not sign out the upstream Google account or globally revoke every previously issued token. See [AWS logout documentation](https://docs.aws.amazon.com/cognito/latest/developerguide/logout-endpoint.html).
- Profile recovery opens a fresh managed sign-in with `prompt=login`. The user can choose recovery when offered for a password account. Google recovery belongs to Google. Existing pool registration/recovery policies are unchanged. See [AWS authorization endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html) and [managed-login flows](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-managed-login.html).

## Validation results and limits

- `npm test`: **22 passed**, including the existing data/forecast tests.
- `npm run lint`: passed with no warnings.
- `npm run build`: passed.
- Auth tests exercise public config validation, every return destination, restoration/loading/error/expiry gates, issuer/client/token-use checks, exact Admin group mapping, optional identity/provider claims, logout ordering/failure, access-token-only API headers and HTTP 401/403.
- Tests use the **actual installed OIDC library** with isolated in-memory storage and synthetic test-only HTTP/token evidence: S256 verifier/challenge matching, nonce binding, successful code exchange with no client secret, unknown/replayed callback rejection, session restore and removal. These are not real Cognito logins; fixtures are not imported by the application.
- Real browser: all seven dashboard URLs displayed the sign-in gate while signed out; clicking Sign In reached the actual configured Cognito managed login with the expected public client, callback, code grant, S256 PKCE, nonce and scopes. Google, email and account-creation entries were visible. An invalid callback showed only a generic error and cleaned its parameters. Desktop sign-in styling was inspected.
- **Not yet verified with a real signed-in account:** Google/email completion, successful callback return, displayed real profile/role, authenticated chart/API behavior, authenticated Cognito logout, password recovery, long-running renewal, or expiry after a real session. Those require the account owner's interaction; no account was invented or bypassed. No JWTs were copied into reports or test fixtures.
- Relevant unchanged Python authentication/API regression tests: **68 passed**, with one pre-existing Starlette/httpx TestClient deprecation warning. No Python source changed.

Reference: [react-oidc-context lifecycle and callbacks](https://github.com/authts/react-oidc-context), [AWS PKCE](https://docs.aws.amazon.com/cognito/latest/developerguide/using-pkce-in-authorization-code.html), [Cognito token/group claims](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-with-identity-providers.html).

## Exact local startup

Terminal 1:

```sh
cd /Users/iannganga/Desktop/electricity-trading-pipeline
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./venv/bin/python -B -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```sh
cd /Users/iannganga/Desktop/electricity-trading-pipeline/frontend
# Only if .env.local has not already been created:
cp .env.example .env.local
# Only if dependencies are absent:
npm ci
npm run dev -- --host localhost --port 5175 --strictPort
```

If a development server from this session is already running on either port, use it rather than starting a duplicate. Open `http://localhost:5175/`. Use Vite dev for its existing `/api` proxy; a static `npm run preview` does not provide that proxy. Do not use another Vite port without separately approving matching Cognito callback/logout settings.

Checks from the repository root:

```sh
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_auth.py tests/test_api.py tests/test_api_deployment.py
```

## Manual account verification

1. **Protected routes:** in a fresh signed-out browser session visit `http://localhost:5175/anomalies` (and each of the other six routes). Expect the sign-in screen, with no market data rendered.
2. **Google:** click **Sign In**, choose **Sign in with Google** on Cognito, and complete your real account flow. Expect `/auth/callback` to finish once, remove OAuth parameters and return to `/anomalies`. Do not paste tokens or authorization codes into chats/screenshots/logs. If Google skips account selection due to its existing cookie, that is separate from PowerFlow's session.
3. **Profile/navigation:** open **My Profile**. Compare name/email to the identity provider, check verification/optional-field handling and the abbreviated reference. Expect Admin only for an account already assigned to `powerflow-admins`; otherwise Analyst. No group changes are required or performed by this implementation. Confirm restricted coefficient/operations panels remain deferred even for an Admin display label.
4. **Authenticated pages:** navigate all seven routes, check existing charts/tables/filtering/retry and browser back/forward. Reload `/profile` to confirm restoration in the same tab. API requests should carry an access-token bearer header; do not copy or expose its value. Existing missing next24h/monitoring reports should retain their honest unavailable states.
5. **Logout:** click **Sign out** in the desktop navigation or profile. Expect Cognito logout to return to `http://localhost:5175/` and the sign-in screen. Reload and visit `/profile`; both must stay gated. Browser Back must not yield usable dashboard data. An upstream Google cookie can still exist; it is not evidence that PowerFlow stayed authenticated.
6. **Email:** after signing out, open `/forecasting`, click **Sign In**, enter the real Cognito email address, choose **Next**, and complete the offered password/MFA flow. Expect return to `/forecasting` and the matching profile. PowerFlow should never ask for the password itself.
7. **Recovery:** from My Profile choose **Open Cognito sign-in for recovery**; enter the password account's email and proceed to the recovery option if offered. Confirm the managed flow is available without changing a password unless you intentionally want to. Registration/recovery availability and delivery are controlled by existing Cognito policies. No new user creation or password reset was performed in this session.
8. **Callback/error:** signed out, open `http://localhost:5175/auth/callback` directly. Expect a safe restart screen, not dashboard access or a redirect loop. Test cancellation from managed login; raw provider error text must not appear. A successful callback URL refresh must not re-exchange a used code.
9. **Session expiry/renewal:** keep a real session open through an access-token lifetime. Verify renewal if a refresh token was issued. If renewal fails or the session is no longer valid, expect sign-in and no continued data access. Do not alter pool lifetimes or paste/edit real tokens just to perform this check.
10. **Responsive:** check the entry screen, protected-route loading, account link and profile sign-out on mobile/tablet; once authenticated, recheck the existing navigation drawer and charts.

## Every created/modified file

Modified:

- `frontend/package.json`, `frontend/package-lock.json` — requested OIDC packages and lockfile.
- `frontend/README.md` — current authentication/setup documentation links.
- `frontend/src/main.tsx` — router and authentication provider inside existing StrictMode.
- `frontend/src/App.tsx` — public callback plus protected workspace route group.
- `frontend/src/api/client.ts` — access-token bearer and safe 401/403 handling.
- `frontend/src/components/layout/AppLayout.tsx` — actual identity/role and sign-out.
- `frontend/src/index.css` — flat sign-in/account styles and responsive controls.
- `frontend/src/pages/WorkspacePages.tsx` — compatibility export to the functional profile page.

Created:

- `frontend/.env.example` — five non-secret public settings.
- `frontend/.env.local` — ignored local copy, not a tracked deliverable.
- `frontend/src/auth/config.ts` — public config validation, safe return destinations, logout URL.
- `frontend/src/auth/oidcSettings.ts` — shared public-client/PKCE/session settings.
- `frontend/src/auth/runtime.ts` — singleton manager, safe callback completion/cleanup.
- `frontend/src/auth/AuthenticationRoot.tsx` — provider, expiry lifecycle, API session binding.
- `frontend/src/auth/ProtectedRoutes.tsx` — session gate and callback route.
- `frontend/src/auth/SignInScreen.tsx` — sign-in, errors and origin guidance.
- `frontend/src/auth/SignOutButton.tsx` — local clearing and managed logout action.
- `frontend/src/auth/logout.ts` — tested logout sequencing.
- `frontend/src/auth/identity.ts` — session checks and limited presentation claims.
- `frontend/src/auth/sessionStatus.ts` — non-sensitive ended-session notice.
- `frontend/src/api/accessToken.ts` — in-memory access-token-aware API binding.
- `frontend/src/pages/ProfilePage.tsx` — read-only real account and supported management entry.
- `frontend/tests/auth.test.ts` — isolated protocol, state, role, logout and API tests.
- `frontend/docs/authentication.md` — this guide and handover.

## Phase 4B and remaining boundaries

**No FastAPI endpoint is newly protected in Phase 4A.** The React route gate and role display do not secure independently callable public API routes. Keeping those routes unchanged preserves Streamlit compatibility as requested.

Phase 4B must implement trusted Cognito JWKS signature verification, issuer/expiration checks, access-token `token_use`, correct public-client `client_id`/audience binding, and server-side Admin/Analyst/scope checks with 401/403 behavior. It must decide/document which market/health routes remain public and how existing Streamlit consumers retain their approved contract. User-specific or sensitive endpoints cannot be added until that boundary works.

Restricted one-hour feature influence, detailed operational reports/configuration/incidents/timings stay pending authentication/authorization on the server. Phase 4A does not unlock them. Production callback/hosting/proxy/Cognito changes and deployment require a separate approved phase. Existing missing local next24h/monitoring evidence remains unrelated to sign-in and was not fabricated.
