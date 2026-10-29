# Staging Cognito URL configuration — 2026-10-29

One authorized UpdateUserPoolClient completed successfully for existing SPA client `4t8s6a673a18qhbauqac8rhdcf`, pool `us-east-1_NLoYFRvex`, account870755688674/us-east-1. Subsequent DescribeUserPoolClient exactly matched the intended configuration. Only CallbackURLs and LogoutURLs changed; timestamps excluded from comparison. Original CreationDate preserved.

CallbackURLs:

- `http://localhost:5175/auth/callback` (preserved)
- `https://staging.powerflowenergy.dev/auth/callback` (added)

LogoutURLs:

- `http://localhost:5175/` (preserved)
- `https://staging.powerflowenergy.dev/` (added)

All18 other returned writable settings preserved, including Authorization Code flow, OAuth scopes, native/Google identity providers, attribute permissions and token settings. No client secret introduced. PKCE remains configured by the unchanged deployed OIDC frontend. No other app client/pool, IAM, EC2, Nginx, API, production service or Git setting changed. There were no existing production-domain URLs on this SPA client to remove; the separate Streamlit client was not accessed or modified.

The deployed URLs were checked against the immutable release and previously verified deployed JS asset SHA. Current direct staging HTTPS checks from this Mac could not pass trust validation; they were not bypassed. Public TLS inspection returned a certificate for staging.powerflowenergy.dev issued by Fortinet, rather than the previously verified Let's Encrypt chain. DNS still resolves3.228.243.164. No explicit HTTPS proxy configured in the local HTTP environment. OpenSSL public-CA validation returned code20, unable to get local issuer certificate. Transparent TLS inspection on the current connection is the likely cause; no server-side TLS change was made.

Stateless tests with normal TLS verification, no cookies, credentials or token exchange:

- Cognito authorize request: response_type=code, scopes openid/email/profile, S256 PKCE challenge, correct staging callback; HTTP302 to the same Cognito /login with expected callback and no OAuth error.
- Cognito logout request: HTTP302 to https://staging.powerflowenergy.dev/.

These confirm accepted redirect configuration, not a real-account login or successful token exchange. Final browser Google Admin/native Analyst/MFA sign-in, role/API authorization, callback completion and logout acceptance remain pending on a trusted network with valid end-to-end TLS.

Private before/update/after configurations, exact-setting verification and sanitized redirect results retained at `/private/tmp/powerflow-cognito-staging-update-ubu0t7s7/`. TLS public-certificate capture retained privately at `/private/tmp/powerflow-staging-TLS-review-adfw9bwe/`. No raw tokens/passwords or private keys collected.
