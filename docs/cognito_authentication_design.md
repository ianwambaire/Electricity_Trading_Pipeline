# PowerFlow Cognito authentication design

Status: native Cognito OIDC support is implemented but opt-in. The active and
default provider remains the existing hashed username/password registry until
`POWERFLOW_AUTH_PROVIDER=cognito` is explicitly configured. No AWS setting is
created or changed by this repository.

## Intended architecture

PowerFlow uses one Amazon Cognito user pool as its OIDC identity provider.
Cognito managed login currently presents email/password and Google. Sign in
with Apple remains a future provider and must not be shown until configured and
tested in Cognito. Streamlit connects only to Cognito through its native OIDC
support, avoiding custom callback, token, and provider-button code in PowerFlow.

Streamlit 1.57.0 already provides `st.login()`, `st.user`, and `st.logout()`.
Its OIDC support authenticates an identity but does not define application
authorization. PowerFlow must continue to enforce page and section access on
the server after every login.

Reference documentation:

- [Streamlit authentication and OIDC](https://docs.streamlit.io/develop/concepts/connections/authentication)
- [Amazon Cognito managed login](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-managed-login.html)
- [Cognito managed-login branding](https://docs.aws.amazon.com/cognito/latest/developerguide/managed-login-branding.html)
- [Cognito token claims and groups](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-with-identity-providers.html)
- [Cognito logout endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/logout-endpoint.html)

## Registration, verification, and recovery

The user pool may allow public self-registration by email but must require email
verification before PowerFlow grants a session. Cognito managed login
should own sign-up, verification-code delivery, resend, forgot-password, and
password-reset screens. Google accounts are federated into the same user pool
with their verified email and stable Cognito `sub` mapped into a consistent
identity. Any future Apple provider must follow the same policy. Account linking
must be tested before launch to avoid duplicate accounts for one email address.

Email delivery must be production-ready before public registration is enabled:
use an approved SES identity and production sending configuration, configure
bounce/complaint handling, and test verification and recovery messages. Do not
enable self-registration while Cognito is using an unsuitable sandbox or an
unverified sender.

PowerFlow should identify a user by the immutable Cognito `sub`, not by an
email address that can change. Display name and email are presentation claims,
not authorization inputs.

## Server-side role mapping

The authorization policy is intentionally asymmetric:

1. Reject any identity that is not authenticated or whose `email_verified`
   claim is not exactly `true`.
2. Assign every newly verified identity the restricted `analyst` role.
3. Assign `admin` only when the validated Cognito ID token contains the exact
   trusted group `powerflow-admins` in `cognito:groups`.
4. Manage that group only through a trusted administrator workflow. Public
   registration, profile attributes, email domains, query parameters, and
   client-submitted role values must never grant Admin.
5. Unknown or malformed claims fail closed. Existing `ROLE_PAGE_ACCESS`,
   `ADMIN_ONLY_SECTIONS`, and direct-render checks remain the final application
   authorization boundary.

`src/auth.py` reads these claims only from Streamlit's read-only `st.user`
mapping after native OIDC login. It validates the expected issuer, app-client
audience, ID-token use, expiry, subject, email, and verified-email flag. Missing
or malformed group claims remain Analyst. The legacy session-state role is
never consulted in Cognito mode.

## OIDC client and URL configuration

Create a Cognito user-pool app client for the Streamlit server and enable the
authorization-code grant with `openid`, `email`, and `profile` scopes. Configure
only exact URLs, including:

- production callback: `https://<powerflow-domain>/oauth2callback`
- production sign-out: `https://<powerflow-domain>/`
- local callback: `http://localhost:8501/oauth2callback`
- local sign-out: `http://localhost:8501/`

Production callbacks must use HTTPS. Nginx must forward `/oauth2callback` to
Streamlit with the original host and scheme headers. Keep the API route and
Streamlit route behavior otherwise unchanged.

The protected Streamlit configuration has this shape; values are placeholders,
not credentials:

```toml
[auth]
redirect_uri = "https://<powerflow-domain>/oauth2callback"
cookie_secret = "<secret-managed-outside-git>"

[auth.cognito]
client_id = "<cognito-app-client-id>"
client_secret = "<cognito-app-client-secret>"
server_metadata_url = "https://cognito-idp.<region>.amazonaws.com/<user-pool-id>/.well-known/openid-configuration"
client_kwargs = { scope = "openid email profile" }
```

The cookie secret and client secret must be supplied through the production
secret-delivery mechanism and never committed. Before production cutover,
confirm how the deployed Streamlit process receives `secrets.toml` values from
the approved SSM/Secrets Manager setup; do not put them into the repository.

`st.logout()` removes Streamlit's identity cookie. Cognito managed login also
has a `/logout` endpoint with an allow-listed sign-out URL. Cutover testing must
verify
whether the required user experience is local-app logout or Cognito-session
logout and implement the latter explicitly if switching accounts must terminate
the Cognito managed-login session too. Logging out of Cognito does not
necessarily sign a user out of the upstream Google or Apple session.

## Google and Apple federation

Google is configured as a social identity provider in Cognito and enabled for
the PowerFlow app client. Provider secrets remain in Cognito/AWS, not in
PowerFlow or Git. Its provider return URL is Cognito's
`/oauth2/idpresponse`; the application callback remains Streamlit's
`/oauth2callback`. Map only the minimum claims required for stable identity,
display, and verified email. Google appears inside managed login, not as a fake
local button. Apply the same rule to Apple if it is added later.

## Managed-login branding constraints

Cognito managed login is a provider-hosted page. Branding is configured per app
client with Cognito's branding editor, subject to the selected user-pool feature
plan. A user-pool domain uses either managed login or the classic hosted UI.
Managed login supports logos, colors, backgrounds, and component styling, but
its displayed text is not generally editable beyond supported localization.
The PowerFlow Streamlit sign-in design therefore cannot be copied pixel-for-
pixel into the Cognito page. Production cutover should align logo, navy/blue
palette,
contrast, and terminology within those constraints and verify desktop/mobile,
verification, recovery, and error screens.

## Local setup and verification

The exact local callback
`http://localhost:8501/oauth2callback` must be added to the Cognito app
client's allowed callback URLs before local login will work. Do not change AWS
from this repository.

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edit only the ignored `.streamlit/secrets.toml` locally. Replace the cookie and
client-secret placeholders yourself; never paste them into chat, Git, command
arguments, logs, or screenshots. Generate the cookie secret with an approved
local password generator. Then set these non-secret values in `.env`:

```dotenv
POWERFLOW_AUTH_ENABLED=true
POWERFLOW_AUTH_PROVIDER=cognito
```

Install dependencies and start Streamlit normally:

```bash
pip install -r requirements-prod.txt
streamlit run src/dashboard.py
```

The browser is redirected to Cognito managed login. Cognito—not PowerFlow—owns
email/password, Google, registration, verification, and recovery. Test a normal
verified user, a member of `powerflow-admins`, logout, expiry, and direct access
to an admin-only page. The application must never display tokens or claims.

Run deterministic local verification without live Cognito calls:

```bash
PYTHONPATH=src python -m pytest -q tests/test_auth.py
PYTHONPATH=src python scripts/check_production_imports.py
```

## Controlled migration and rollback

The explicit `POWERFLOW_AUTH_PROVIDER=legacy|cognito` switch defaults to
`legacy`. Do not infer provider readiness from partial secrets. A selected but
incomplete Cognito configuration fails closed rather than silently falling back
to the legacy registry.

Migration order:

1. Provision and secure the user pool, domain, app client, SES delivery, and
   Google outside this repository. Treat Apple as a separate future addition.
2. Configure exact callback/sign-out URLs and managed-login branding.
3. Deliver OIDC secrets securely and validate Nginx callback routing.
4. Deploy the reviewed Cognito branch using native Streamlit OIDC and the
   existing server-side RBAC checks.
5. Test verified/unverified identities, public Analyst registration, trusted
   Admin group assignment/removal, account recovery, provider linking, logout,
   session expiry, and direct page access in a non-production environment.
6. Run a production smoke test with registration still disabled, then enable
   public registration only after review.
7. Retain the legacy credential secret for a short, controlled rollback window;
   rollback by selecting `legacy` and restarting only after approval.

Removing a user from the Admin group must take effect after token/session
renewal; Phase 2 must define acceptable revocation latency and an emergency
session-revocation procedure before launch.

Rollback does not require deleting Cognito configuration. Set
`POWERFLOW_AUTH_PROVIDER=legacy`, confirm the existing
`POWERFLOW_AUTH_USERS_JSON` secret is available, and restart Streamlit only in
an approved deployment window. The legacy registry, timeout, lockout, and
password-hash flow remain intact.

## Future production cutover checklist

- approved Cognito region, user-pool feature plan, domain, and production URL;
- app client with authorization-code flow and exact callback/sign-out URLs;
- approved SES verification/recovery delivery;
- working Google OAuth configuration in Cognito;
- protected delivery for client secret and Streamlit cookie secret;
- `powerflow-admins` ownership, assignment, removal, and audit procedure;
- account-linking and duplicate-email policy;
- Nginx validation for `/oauth2callback` and forwarded HTTPS headers;
- staging tests for registration, verification, recovery, both configured
  sign-in methods, logout, expiry, revocation, mobile layout, and RBAC bypass
  attempts;
- approved migration window and tested legacy rollback.

## Separate FastAPI authorization gap

Streamlit's OIDC session protects only the Streamlit application. The separate
FastAPI service currently has no authentication or role enforcement on its
read-only endpoints. Nginx routing does not transfer the Streamlit identity
cookie into an authorization decision. Do not represent `/api/` as Cognito-
protected and do not expose sensitive or Admin-only data through it. A future
API-authentication task must validate Cognito bearer tokens independently
(issuer, signature, audience/client, token use, expiry, and authorization)
before any protected API surface is added.

