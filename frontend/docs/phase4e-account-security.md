# Phase 4E — MFA and account security audit / approval proposal

> This is the Stage 1 historical audit. Proposal A was subsequently approved and applied; account-security code is now implemented behind a disabled-by-default release gate. See the [application and implementation record](phase4e-implementation.md) for current state, tests and pending live acceptance. Proposal B remains unapproved. The pre-approval statements below describe the state at audit time.

Reviewed 21 October 2026 (Africa/Nairobi) on `feature/react-frontend`, baseline `9093d5c`. The checkout was clean at the start of this audit.

## Decision and approval boundary

**Stage 1 is complete. Implementation is paused for approval.** The live pool has MFA OFF and no configured software-token factor. It also does not require verification before an email update takes effect. Enabling optional TOTP or implementing the intended verified email-change workflow requires a pool-wide AWS policy change. The task explicitly requires stopping at this boundary.

No application behavior, AWS configuration, user record, identity-provider mapping, group, Streamlit client, deployment or Git history was changed. This report is the only Phase 4E file added. No enrollment, verification-code delivery, password reset, identity linking or account mutation was attempted. No credentials, raw tokens, MFA secrets, codes, account IDs or provider secrets were recorded.

## Read-only evidence and capability matrix

Live operations: `DescribeUserPool`, `GetUserPoolMfaConfig`, `DescribeUserPoolClient`, `DescribeIdentityProvider` (Google) and `GetCallerIdentity`. Full responses were filtered in memory before displaying non-secret configuration. The identity check recorded only its type, not an ARN or account number. Source review covered account routes/gateway, JWT/group authorization, OIDC settings, profile/credential forms, logout and regression tests.

Target pool: `us-east-1_NLoYFRvex`; React SPA client: `4t8s6a673a18qhbauqac8rhdcf`.

| Capability | Live setting / current application behavior | Decision |
| --- | --- | --- |
| Pool MFA | `MfaConfiguration: OFF` in both pool and MFA configuration | No current MFA enrollment or challenge support |
| TOTP | `SoftwareTokenMfaConfiguration` absent; no SMS/email MFA configuration returned | Requires proposal A; do not treat absence as enabled |
| Optional TOTP enrollment | Not currently available; Cognito rejects software-token setup when the pool factor is not enabled | Do not call setup merely to prove rejection: it is a user mutation if configuration changes concurrently |
| Native account | Email/password; `AllowedFirstAuthFactors: [PASSWORD]`; email username attribute; case-insensitive sign-in established in Phase 4D | Eligible for future optional TOTP once approved and enabled |
| Google account | Federation mapping remains `email←email`, `email_verified←email_verified`, `name←name`, `username←sub` | Google controls authentication/MFA; no Cognito TOTP enrollment for federated sign-in |
| Self-service APIs | SPA already allows `aws.cognito.signin.user.admin` plus `openid email profile` | Sufficient OAuth scope for token-authorized TOTP operations after pool enablement; no new IAM runtime grant, SPA scope or attribute expansion needed |
| Application gateway | Allows only GetUser, GetUserAuthFactors, UpdateUserAttributes, ChangePassword, GlobalSignOut | TOTP APIs deliberately not exposed; implementation remains pending |
| Profile writes | Gateway allows only `name`, `preferred_username`; mapped names read-only | Existing own-account editing retained |
| SPA reads | Exactly `email`, `email_verified`, `identities`, `name`, `preferred_username`, `sub` | Existing approved allowlist retained |
| SPA writes | Exactly `email`, `name`, `preferred_username` | Existing approved allowlist retained; required/mapped email remains writable directly at Cognito |
| Safe email update | Mutable required email; auto-verified email; `AttributesRequireVerificationBeforeUpdate: []` | Keep PowerFlow email read-only; proposal B required before offering verification-before-effect |
| Password policy | Minimum 8, uppercase/lowercase/number/symbol, temporary password validity 7 days | Existing native password form matches current audited requirements; Cognito remains authoritative |
| Password recovery | Verified email priority 1; verified phone priority 2 | Existing managed-login recovery; actual recovery availability depends on verified attributes on that user |
| MFA recovery | No configured factor; no implemented recovery/reset mechanism | Do not present password reset as authenticator removal, invent backup codes, or promise self-service lost-device recovery |
| Tokens | Access/ID 60 minutes; refresh 5 days; revocation enabled; refresh rotation absent | Existing configuration retained; rotation would be a separate client compatibility change |
| Auth session | `AuthSessionValidity: 3` minutes; no device configuration returned | Not a three-minute access-token lifetime; no device inventory/trusted-device UI promised |
| Role | Exact verified `powerflow-admins` signed group grants Admin, otherwise Analyst | Scope/profile fields/recovery never grant Admin; no role/group change proposed |
| CLI operator identity | `GetCallerIdentity` reports root | Operational concern requiring separate operator remediation; not used by runtime account APIs |

Cognito delegates federated authentication to the external provider. Optional MFA needs an application enrollment interface; managed login challenges users who have enrolled, but does not automatically enroll optional-MFA users. Google security cannot be inferred from Cognito group membership or email verification. [AWS MFA behavior](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-mfa.html).

## Existing security and limitations

The API verifies JWT signature, issuer, expiration, access-token type, client binding and scopes, then performs a live provider check and immutable-subject match. Self-service routes accept no target username/subject. Bounded, strict request schemas reject extra targets and sensitive attributes; validation/provider errors are sanitized. API responses use no-store headers. Existing group authorization remains the only Admin boundary.

`GlobalSignOut` invalidates Cognito user tokens, but does not clear the managed-login cookie; PowerFlow follows it with the existing browser logout. Current-browser logout clears local OIDC state and the Cognito browser session; it is not a guarantee that copied tokens were revoked. Google sessions remain separate. PowerFlow additionally checks token activity through Cognito, rather than relying solely on local JWT signature validation. Other consumers that validate only JWT signatures can accept revoked JWTs until expiration. Group removal is not reflected in an already issued signed group claim until token renewal/expiry; it is not a live group-directory lookup. [AWS GlobalSignOut](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_GlobalSignOut.html), [AWS logout](https://docs.aws.amazon.com/cognito/latest/developerguide/logout-endpoint.html), [revocation behavior](https://docs.aws.amazon.com/cognito/latest/developerguide/token-revocation.html).

The current profile's `mfa_management: not_enabled` is consistent with today's pool. It is a static application capability, not a live per-request MFA-policy or Google-security attestation. After any approved policy change, the backend/UI must be updated together before claiming accurate enrollment status. No fake switch or unsupported operation is being introduced meanwhile.

The self-service scope is broader than the PowerFlow gateway: a token holder can call supported own-account Cognito APIs directly. Gateway restrictions cannot prohibit every direct Cognito operation. No privileged backend credentials should be added to compensate. Streamlit shares the pool and attributes; SPA permissions alone are not a pool-wide attribute policy.

### Recovery boundaries

Email verification confirms address possession, not a role or an identity link. Under the current update policy an address change can take effect before verification, which is why PowerFlow does not offer an email editor. A native email change also affects the email sign-in/recovery address; Google-mapped email remains provider-managed. Never auto-link accounts based on equal email strings. [AWS verification-before-update settings](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_UserAttributeUpdateSettingsType.html).

Password recovery uses configured verified channels. Email/SMS MFA can conflict with using the same channel for recovery; TOTP avoids that particular channel conflict but does not provide a lost-authenticator recovery process. Resetting a password must not be described as disabling TOTP or changing group access. Before enrollment is released, define a separately controlled support recovery process that verifies identity and never removes MFA solely because someone knows an email address. Do not expose that administrative process as an unauthenticated endpoint. [AWS password and recovery restrictions](https://docs.aws.amazon.com/cognito/latest/developerguide/managing-users-passwords.html).

### Root CLI identity

The audit confirms root identity use, not whether credentials are long-lived, how they were obtained, or whether root MFA is enabled. Those were not inspected. Root is unnecessarily privileged for this read-only audit and routine Cognito maintenance. Use a dedicated short-lived assumed role/Identity Center permission set with only necessary read permissions for audits and separately approved change permissions. Keep root for tasks that require it, protect it with MFA, and avoid root access keys. No IAM user/role/key or root MFA change was made. Runtime AccountGateway uses user access tokens and HTTP calls, not boto3/IAM/root credentials. [AWS root-user guidance](https://docs.aws.amazon.com/IAM/latest/UserGuide/root-user-best-practices.html).

## Exact proposals — not applied

### A — optional authenticator TOTP (recommended next approval)

Only pool `us-east-1_NLoYFRvex`:

| Field | Current | Proposed |
| --- | --- | --- |
| `MfaConfiguration` | `OFF` | `OPTIONAL` |
| `SoftwareTokenMfaConfiguration` | Absent / not enabled | `{"Enabled": true}` |
| SMS/email MFA, WebAuthn, devices, recovery, password policy, email policy | Existing state | Preserve unchanged |
| SPA/Streamlit clients, scopes/permissions/callbacks/tokens, Google mapping, accounts/groups | Existing state | Preserve unchanged |

Review-only request shape for `SetUserPoolMfaConfig` (not executed):

```json
{
  "UserPoolId": "us-east-1_NLoYFRvex",
  "MfaConfiguration": "OPTIONAL",
  "SoftwareTokenMfaConfiguration": {"Enabled": true}
}
```

This is **pool-wide**, not isolated to React. It does not auto-enroll existing users, but an enrolled native user will receive MFA challenges when signing in through other clients including Streamlit. Streamlit's hosted login compatibility must be tested before an existing account enrolls. No existing account will be enrolled under this proposal without separate explicit authorization. Google authentication remains delegated to Google; this does not add MFA to the Google Admin account. TOTP is not phishing-resistant, and optional MFA is not a guarantee all users have MFA. Lost-device support and secure disabling are release prerequisites. [AWS configuration API](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_SetUserPoolMfaConfig.html).

### B — verified email changes (separate approval; recommend deferring)

Only pool `UserAttributeUpdateSettings.AttributesRequireVerificationBeforeUpdate`: `[]` → `["email"]`. Preserve all other pool/client/IdP settings exactly. This keeps the old email active until the new email is verified; an eventual UI would be native-only, require fresh authentication, validate the new address, send/verify a code and reread current provider state. Never set `email_verified` directly, update Google-mapped email, or transfer an alias/link identity. [AWS update verification](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-email-phone-verification.html).

Because this requires `UpdateUserPool`, prepare a complete supported-field preservation request rather than submitting a minimal object that can reset omitted settings. Review Google mapping/verification and Streamlit email behavior first. This changes shared sign-in/recovery behavior and needs its own compatibility and delivery tests; no such request has been constructed or executed. Do not bundle B with approval A.

## Change safeguards and rollback plan (approval required)

Before any approved mutation, re-read pool/MFA/client/Google configuration, validate no drift, and create a protected 0700 directory / 0600 non-secret snapshots outside Git. Keep provider secrets and user data out. Capture full supported request fields needed to preserve configuration; compare before/after, allowing only approved fields plus provider modification timestamps. Abort on drift or AWS rejection; never broaden permissions or change another setting to make the call work.

For A, current effective rollback is `MfaConfiguration: OFF`, `SoftwareTokenMfaConfiguration: {Enabled: false}` via the same dedicated MFA API, preserving every other factor/configuration from the pre-change snapshot. AWS might return explicit disabled state instead of the original absent object; compare effective disabled behavior and all unrelated fields. Rollback needs explicit approval because turning MFA off weakens protection. Do not automatically roll back after users enroll: it affects all clients and does not prove stored authenticators were erased. Coordinate affected users and verify hosted login first. No user MFA preference or secret will be reset automatically.

For B, restore the complete preserved supported pool configuration with `AttributesRequireVerificationBeforeUpdate: []` only after approval and a drift check. This removes verification-before-effect protection; it does not undo verified email changes or safely resolve pending updates. Reconcile pending requests individually before rollback; never overwrite account attributes as part of policy rollback.

No rollback is currently needed: no AWS mutation occurred in Phase 4E.

## Proposed implementation after approval — not implemented

Keep the existing compact white/blue, Source Sans 3 profile styling. Group security into Password, Two-step verification, Recovery and Sessions. For native users show actual enrollment status with a clear action; for Google show provider-managed security and the existing Google security link. Do not show nonfunctional toggles or imply an email/MFA setting is editable before it is supported.

Native TOTP would use token-authorized `AssociateSoftwareToken`, `VerifySoftwareToken`, and `SetUserMFAPreference` with the existing self-service scope, after fresh authentication and subject matching. Accept no caller-selected account or arbitrary Cognito operation. Read live preferred/enabled factors through GetUser; enable only after verified SUCCESS and confirm preference readback. Wrong codes, rate limits, timeouts and uncertain completion must reread provider state instead of optimistically claiming enrollment. Disabling a preference is not deletion of its secret, and replacing a verified authenticator can disassociate the previous one; those need explicit UI confirmation and recovery safeguards. [AssociateSoftwareToken](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AssociateSoftwareToken.html), [VerifySoftwareToken](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_VerifySoftwareToken.html), [SetUserMFAPreference](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_SetUserMFAPreference.html).

Return setup material only to its authenticated owner with no-store. Render QR locally (no third-party QR service), accessible manual key and code entry; keep secret only in short-lived component memory, clear on completion/cancel/navigation/expiry, never localStorage, URLs, telemetry or logs. Review proxy/error tracing redaction before adding secret-bearing endpoints. Prefer no database persistence. Do not fabricate recovery codes. Keep existing OIDC/PKCE, API client bindings and group guards. Any QR dependency would require a specific explanation before installation; none added now.

Reauthentication is needed for enrollment, disabling/replacing a factor, email changes and global session revocation. A recent Cognito `auth_time` is not proof Google performed its own MFA. Cognito prompt=login and provider behavior must be tested; never bypass an unmet freshness requirement. Existing password/current-password checks and provider-hosted recovery remain intact.

## Tests and evidence

Existing automated regressions were rerun during this audit. They exercise JWT failures, signed groups, all seven Analyst denials, own-subject binding, forbidden attribute/target writes, native versus Google password capability, current-password errors, revoked/expired sessions, malformed inputs, rate limits and safe frontend errors.

| Command | Result |
| --- | --- |
| `venv/bin/python -m pytest -q` (repository root) | 582 passed in 30.79 s; one existing Starlette/httpx TestClient deprecation warning |
| `npm test` (`frontend/`) | 45 passed, 0 failed |
| `npm run lint` (`frontend/`) | Passed |
| `npm run build` (`frontend/`) | Passed |
| `git diff --check` | Passed |

Local logs: `/tmp/powerflow-phase4e-backend.txt`, `/tmp/powerflow-phase4e-frontend.txt`. No tests were added for unimplemented APIs. No new dependency was installed. Final status contains only this untracked report; nothing staged or committed.

No new operation or UI was implemented before approval, so no new MFA success tests or responsive enrollment screenshots exist. Mocked success would not establish live pool support. No live MFA enrollment, challenge, removal, lost-device recovery or email change was performed. Prior Phase 4D.2 real-account evidence remains historical: Google Admin login/profile/edit/sign-out, native Analyst profile/edit/sign-out and all seven 403 denials passed. Password change/recovery passed earlier; the owner declined repeating them after allowlist hardening. Those tests were not repeated as Phase 4E tests. No production or Streamlit behavior was tested or changed in this audit.

After approval, add tests for eligibility (native/federated/unknown), fresh auth, wrong scope, cross-subject attempts, strict payload/code bounds, setup/verification/preference transitions, partial failure reconciliation, no-secret logs/cache/storage, expired/revoked sessions, 403/429/503 handling, cancellation and duplicate submissions, recovery without privilege escalation and all seven Admin guards. Frontend tests must cover actual forms, focus management, keyboard errors and status announcements; existing parser-only tests are not sufficient to certify an enrollment UX.

## Manual acceptance plan after approved configuration and implementation

1. Recheck exact saved MFA/client/email policy and unrelated-setting preservation. Use a designated disposable native test account authorized for enrollment; do not enroll the existing Google Admin or native Analyst merely under a configuration approval.
2. Owner completes native Code+PKCE login and self-service reauthentication. Confirm server Analyst, verified recovery channel and all seven Admin-route 403 responses. No password/code/token is sent to chat.
3. Test fresh-auth gate, start enrollment, scan locally rendered QR or enter key in owner's authenticator, submit correct/wrong/expired codes personally. Confirm verified/enabled status from Cognito and wipe setup display. Never screenshot the key/QR/code.
4. Sign out, sign in through Cognito and observe the actual TOTP challenge. Owner submits code; verify profile and Analyst restrictions. Test cancellation, offline/retry, rate limiting and uncertain provider responses safely.
5. With separate owner authorization, test factor disable/re-enable/replacement and lost-device support using disposable accounts. Verify password recovery does not remove MFA, grant a group, or transfer identity. Do not weaken policies to complete the test.
6. Google Admin fresh sign-in/profile/provider guidance/sign-out and authorized Admin paths must still work; there must be no Cognito enrollment control for Google federation. Test native hosted login through the Streamlit client in an approved environment before production rollout; leave production untouched.
7. Verify profile editing/current-browser and global sign-out, token rejection, and native password/recovery flows with owner entry if authorized. Distinguish current-browser logout from global revocation and Google logout.
8. Check desktop/tablet/mobile at 1440/768/390 px, keyboard navigation, focus containment/restoration, labels, error announcements, contrast and overflow. Preserve all seven routes and analytics.
9. If B is separately approved/implemented, use a disposable native account and controlled second mailbox to prove the old email remains valid until verification, invalid/expired codes fail safely, alias conflicts do not link identities and recovery/role remain correct. Do not test email changes on Google Admin.

Approval requested: **A only (optional TOTP)**, or defer. B and root-operator remediation are separate decisions. Neither proposal has been applied, and no account enrollment is authorized by this report itself.
