# PowerFlow Cognito authentication design

Status: Phase 1 design only. The active production login remains the existing
hashed username/password registry. No Cognito user pool, client, provider, or
public registration is enabled by this change.

## Intended architecture

PowerFlow should use one Amazon Cognito user pool as its OIDC identity provider.
Cognito managed login presents email/password, Google, and Sign in with Apple;
Streamlit connects only to Cognito through its native OIDC support. This avoids
custom OAuth callback, token, and provider-button code in PowerFlow.

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

The Phase 2 user pool should allow public self-registration by email and require
email verification before PowerFlow grants a session. Cognito managed login
should own sign-up, verification-code delivery, resend, forgot-password, and
password-reset screens. Google and Apple accounts should be federated into the
same user pool with their verified email and stable Cognito `sub` mapped into a
consistent identity. Account-linking policy must be tested before launch to
avoid duplicate accounts for one email address.

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

`src/auth.py` now contains the inactive, unit-tested mapping function
`role_for_verified_identity()`. Phase 2 can call it only after Streamlit has
validated the Cognito OIDC identity. It is not wired into the current login.

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

The future protected Streamlit configuration has this shape; values are
placeholders, not credentials:

```toml
[auth]
redirect_uri = "https://<powerflow-domain>/oauth2callback"
cookie_secret = "<secret-managed-outside-git>"
client_id = "<cognito-app-client-id>"
client_secret = "<cognito-app-client-secret>"
server_metadata_url = "https://cognito-idp.<region>.amazonaws.com/<user-pool-id>/.well-known/openid-configuration"
```

The cookie secret and client secret must be supplied through the production
secret-delivery mechanism and never committed. Before implementation, confirm
how the deployed Streamlit process receives `secrets.toml` values from the
approved SSM/Secrets Manager setup; do not put them into the repository.

`st.logout()` removes Streamlit's identity cookie. Cognito managed login also
has a `/logout` endpoint with an allow-listed sign-out URL. Phase 2 must test
whether the required user experience is local-app logout or Cognito-session
logout and implement the latter explicitly if switching accounts must terminate
the Cognito managed-login session too. Logging out of Cognito does not
necessarily sign a user out of the upstream Google or Apple session.

## Google and Apple federation

Configure Google and Apple as social identity providers in Cognito, then enable
them for the PowerFlow app client. Provider secrets remain in Cognito/AWS, not
in PowerFlow or Git. Their provider return URL is Cognito's
`/oauth2/idpresponse`; the application callback remains Streamlit's
`/oauth2callback`. Map only the minimum claims required for stable identity,
display, and verified email. No Google or Apple button should appear in the
Streamlit UI before the corresponding provider has passed end-to-end testing.

## Managed-login branding constraints

Cognito managed login is a provider-hosted page. Branding is configured per app
client with Cognito's branding editor, subject to the selected user-pool feature
plan. A user-pool domain uses either managed login or the classic hosted UI.
Managed login supports logos, colors, backgrounds, and component styling, but
its displayed text is not generally editable beyond supported localization.
The PowerFlow Streamlit sign-in design therefore cannot be copied pixel-for-
pixel into the Cognito page. Phase 2 should align logo, navy/blue palette,
contrast, and terminology within those constraints and verify desktop/mobile,
verification, recovery, and error screens.

## Controlled migration and rollback

Phase 2 should add one explicit provider switch such as
`POWERFLOW_AUTH_PROVIDER=legacy|cognito`, defaulting to `legacy` until all tests
and production configuration are complete. Do not infer provider readiness from
partial secrets. A selected but incomplete Cognito configuration must fail
closed rather than silently fall back to the legacy registry.

Migration order:

1. Provision and secure the user pool, domain, app client, SES delivery, Google,
   and Apple outside this repository.
2. Configure exact callback/sign-out URLs and managed-login branding.
3. Deliver OIDC secrets securely and validate Nginx callback routing.
4. Implement the Cognito branch using native Streamlit OIDC and the existing
   server-side RBAC checks.
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

## Phase 2 acceptance prerequisites

- approved Cognito region, user-pool feature plan, domain, and production URL;
- app client with authorization-code flow and exact callback/sign-out URLs;
- approved SES verification/recovery delivery;
- working Google OAuth and Apple Services ID/team/key configuration in Cognito;
- protected delivery for client secret and Streamlit cookie secret;
- `powerflow-admins` ownership, assignment, removal, and audit procedure;
- account-linking and duplicate-email policy;
- Nginx validation for `/oauth2callback` and forwarded HTTPS headers;
- staging tests for registration, verification, recovery, all three sign-in
  methods, logout, expiry, revocation, mobile layout, and RBAC bypass attempts;
- approved migration window and tested legacy rollback.

