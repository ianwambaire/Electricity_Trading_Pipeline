# Read-only Admin MFA capability/configuration procedure — NOT EXECUTED

Owner target: native Cognito password+TOTP for Admin, Google retained for non-Admin,
60-minute Admin authentication age. Existing Admin access stays unchanged until a
parallel replacement and recovery path are verified. No current API policy change.

## Fixed scope and execution prerequisites

Region us-east-1, pool us-east-1_NLoYFRvex. Existing public React and separate legacy
client IDs are fixed in projection.py. Verify these against trusted prior records
and the immutable deployed frontend before execution; do not discover accounts or
search other pools. Use an explicitly approved existing temporary least-privilege
operator session, not a default/root credential or access-key fallback. Fresh STS
identity must match the approved historical pool ARN/account binding before any
Cognito call. If identity/permission/runtime trust cannot be established, stop.
No credentials, token/cookie export, user lookup, enrollment or changes are needed.

One separately authorized batch, no retries/pagination: connect timeout2s,
read timeout5s, total45s, maximum five operations. Trusted TLS/standard regional
endpoints; disable SDK endpoint/proxy overrides and request/body debug logging.
Verify local SDK/CLI executable dependencies before execution. No SSH involved.

1. sts:GetCallerIdentity — compare approved account/role in memory; print neither.
2. cognito-idp:GetUserPoolMfaConfig — exact pool; MFA mode and TOTP support.
3. cognito-idp:DescribeUserPool — exact pool; tier, ACR capability fields (if
   returned), native sign-in-factor and device policy compatibility. Missing new
   capability fields mean NOT_REPORTED, not proof of unsupported functionality.
4. cognito-idp:DescribeUserPoolClient — exact existing React client.
5. cognito-idp:DescribeUserPoolClient — exact existing legacy client.

Project only the allowlisted non-secret fields using projection.py; discard raw
responses. DescribeUserPoolClient may include a ClientSecret: never access, print
or retain its value (only check field presence). Do NOT call DescribeIdentityProvider,
which can return the Google provider secret. Client provider lists establish
configured Google/native support; previously accepted sign-in remains baseline.
Do not change providers, mappings, scopes, callbacks, groups, factors or clients.
No GetUser/AdminGetUser/ListUsers/secret-store or authentication requests.

Required IAM: cognito-idp:GetUserPoolMfaConfig, DescribeUserPool,
DescribeUserPoolClient scoped to the approved exact user-pool ARN. STS identity
read is normally allowed without a separate grant; SCP/session/network restrictions
still apply. No IAM modification is authorized. Preserve a private sanitized
assessment only, never raw provider or credential output.

## What this can and cannot prove

Configuration can establish TOTP support, compatibility and whether the plan can
request step-up. It cannot prove rollout availability or actual signed MFA claims,
nor whether a particular Google session completed MFA. ACR/AMR is a gradual
rollout; requested step-up requires Essentials/Plus, and managed login can ignore
acr_values on an insufficient plan. Therefore follow later, separately authorized
native sign-in with verification of issuer-signed access-token assurance and real
auth_time through a trusted attestation path. Never rely only on MFA enrollment,
a successful login, a new token iat, a UI claim or an observed challenge alone.

## Implementation gate after inspection (not implemented here)

Keep current Admin access until a parallel native Admin test identity, password+
TOTP path, server-side access-token assurance verification and recovery are proven.
Require approved native identity provenance, signed password+TOTP MFA assurance
(Cognito default level4/AMR pwd+otp+mfa if supported), existing group membership,
and auth_time age<=3600s. Refresh must not reset authentication age. Apply the guard
to all Admin routes/legacy aliases; reject missing/malformed/stale assurance. Google
non-Admin sign-in remains unchanged. Existing own-account fresh-sign-in controls
remain separate. Do not enable a guard based only on these configuration reads.

If claims/step-up are unavailable, stop for an explicit alternate provider-enforced
policy decision; do not broaden pool MFA to all native/legacy users silently.
Any tier/cost, AWS policy, provider, account/group, rollout or deployment change
needs separate approval. No further owner choice is needed for the stated target;
actual capability, test-account availability and recovery ownership remain gates.
