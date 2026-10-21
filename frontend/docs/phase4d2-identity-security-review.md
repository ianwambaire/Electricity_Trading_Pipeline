# Phase 4D.2 — Cognito identity and attribute security review

> Subsequent approved change: [SPA allowlist application record](phase4d2-attribute-application.md). The exact two lists were applied and saved-setting comparisons passed; post-change real-account acceptance is tracked separately there. The audit and unapplied-proposal statements below record the pre-approval state.

Reviewed 21 October 2026, Africa/Nairobi. Branch: `feature/react-frontend`.

## Decision

Application authorization remains group-based and prevents client-selected roles or account targets. Two application permission/error-handling defects were fixed and a second defensive write allowlist added. **No AWS configuration, pool policy, identity link, user attribute or group was changed during this review.**

The provider configuration is broader than the PowerFlow forms. An SPA-only attribute allowlist is proposed below for approval. It reduces exposure but cannot establish a pool-wide guarantee that only name/preferred username can change: required email remains writable, the Streamlit client uses defaults, and the Cognito self-service scope authorizes additional own-account operations. Those boundaries must be accepted or separately redesigned before claiming full provider-level restriction.

## Read-only evidence

AWS CLI `describe-user-pool-client`, `describe-user-pool`, `describe-identity-provider`, `list-user-pool-clients` and `list-groups` were used with field projections. No user enumeration, user record export, raw JWT capture, client-secret output or provider-secret output was performed.

| Setting | Saved value |
| --- | --- |
| Pool | `us-east-1_NLoYFRvex` |
| SPA client | `4t8s6a673a18qhbauqac8rhdcf` |
| SPA ReadAttributes / WriteAttributes | Both omitted: broad Cognito defaults, not empty lists |
| SPA OAuth scopes | `openid`, `email`, `profile`, `aws.cognito.signin.user.admin` |
| SPA OAuth flow / providers | Code; COGNITO and Google |
| Callback / logout | `http://localhost:5175/auth/callback` / `http://localhost:5175/` |
| Token revocation / refresh rotation | Enabled / not configured |
| SPA token validity | Access/ID: 60 minutes; refresh: 5 days |
| SPA explicit auth flows | Refresh-token auth, USER_AUTH and SRP enabled; user-existence errors protected |
| Other pool client | Streamlit `5qa93km3lf2bbu3ffnrpea4r3g`; default read/write attributes; OAuth scopes email/openid/profile; COGNITO and Google |
| Username configuration | Email username attribute; case insensitive; no alias list |
| Email | Required; auto-verified; `AttributesRequireVerificationBeforeUpdate=[]` |
| Recovery | Verified email first, verified phone second |
| Registration / MFA | Native self-registration permitted; MFA OFF |
| Lambda triggers / custom schema | None configured / no custom attributes |
| Groups | `powerflow-admins`, and the pool's Google provider group; no precedence configured |

The pool contains exactly those two clients at audit time. This audit did not read group user membership; actual Admin/Analyst behavior was verified through authenticated application evidence in Phase 4D.1.

Native Cognito is not an external IdP mapping. Native attributes come from registration, supported own-account APIs and administrators. Google mapping is exactly:

```json
{"email":"email","email_verified":"email_verified","name":"name","username":"sub"}
```

Google authorization scopes remain `openid email profile`. No Google tokens are mapped to stored custom attributes.

## Attribute inventory and minimum need

| Attribute(s) | Schema | Intended ordinary-user handling | Identity/authorization consequence |
| --- | --- | --- | --- |
| `sub` | Immutable, required | Never editable; not displayed in profile | Canonical server account identity; checked against live provider subject |
| Cognito username / Google-derived username | Provider-generated identifier; username is not a general editable schema field | Never editable/accepted as an account target | Google username derives from provider `sub`, not editable email or preferred label |
| `name` | Mutable | Native editable; Google read-only in PowerFlow | Presentation only; Google refreshes mapped name on login |
| `preferred_username` | Mutable | Editable profile label | No login alias configured; never grants a role; not Google mapped |
| `email` | Mutable, required | Read-only in PowerFlow | Verification/recovery/login-associated identity data; direct provider changes remain possible |
| `email_verified`, `phone_number_verified` | Schema reports mutable; provider-controlled verification flags | Never writable through PowerFlow or ordinary client attribute writes | Schema mutability is not permission to self-assert verification; Cognito requires verification/admin or trusted IdP mapping |
| `identities` | Schema reports mutable; provider-managed linked-identity metadata | Read only for linkage presentation; no write/link API | Do not treat schema mutability as approval to edit identity links |
| `phone_number` | Mutable | No PowerFlow editor; exclude from proposed SPA writes | Could influence recovery if verified; broad defaults currently exceed product need |
| `profile`, `address`, `birthdate`, `gender`, `updated_at`, `website`, `picture`, `zoneinfo`, `locale`, `given_name`, `family_name`, `middle_name`, `nickname` | Mutable | No working product setting needs these; exclude from proposed SPA access | Must never become role or verified-identity evidence |
| `cognito:groups`, `cognito:roles`, `cognito:preferred_role` | Provider token claims, not user-editable profile schema fields | Reject as profile input | Only exact verified `powerflow-admins` group grants API Admin; IAM-role claims ignored |

No custom administrative/entitlement attribute exists. Future custom attributes must have explicit deny-by-default client write review; do not use mutable fields for authorization.

## Findings

### 1. Broad provider permissions and writable required email — unresolved provider boundary

Both clients omit attribute permission lists. Cognito's defaults permit substantially more attributes than PowerFlow needs. The FastAPI body schema and new gateway defense constrain requests *through PowerFlow*, but cannot constrain a user directly calling Cognito with their token.

Email is required and Google mapped, so simply removing email from the client write list is not a supported way to preserve the current registration/federation contract. The pool also does not hold the old email until the new address is verified. This review therefore does not certify email changes as verification-before-effect. No unsafe email-change test was performed.

The separate Streamlit client shares user attributes with the SPA. Restricting only the SPA does not make a field immutable across the pool. No production client or policy was changed. Read permission changes also affect ID-token/userInfo claims, not only profile API responses.

### 2. Self-service scope is broader than two profile fields

`aws.cognito.signin.user.admin` is a reserved **own-account** capability, not a PowerFlow Admin role. Attribute read/write access follows the client permissions. The scope can authorize other Cognito user operations, including password/device/security operations and even own-account deletion. The application gateway exposes only GetUser, GetUserAuthFactors, UpdateUserAttributes, ChangePassword and GlobalSignOut; it does not expose DeleteUser or identity linking. That gateway cannot prevent a direct Cognito call by a token holder, and IAM deny policies are not a per-operation filter for these token-authorized APIs.

This is a threat-model limitation, not a newly implemented delete function. No deletion, security enrollment or identity-link test was attempted. If a narrower provider capability is mandatory, a separately approved architecture/security design is needed; do not claim the current scope can be split into name-only permissions or add privileged runtime credentials as a shortcut.

### 3. Federation overwrite and identity conflicts

Cognito updates mapped Google fields during Google sign-in. PowerFlow blocks mapped-name editing to avoid promising persistence that federation would overwrite. The preferred label is unmapped and remains user managed. The mapped verified flag reflects Google's claim, not a user's submitted flag.

No automatic linking implementation or configured linking trigger was found. No AdminLinkProviderForUser, alias transfer, user migration or account modification was performed. Equal email strings must never be used to merge subjects or infer Admin; native/federated accounts can represent distinct subjects. The server uses verified token subject, pool, client and group, so changing a display/email field cannot impersonate another account or confer its group membership. Google-associated automatic group membership alone does not grant Admin.

### 4. Authorization and revocation boundary

FastAPI verifies RS256 signature using trusted issuer JWKS, issuer, expiration, access-token use, client/audience binding and required scopes. Account requests require the self-service scope plus live GetUser subject matching. All protected requests check live activity; older ordinary sessions use trusted userInfo. A missing scope gives an explicit reconnect error rather than silently widening permissions.

Every Admin endpoint and both legacy monitoring aliases use the same server `require_admin` dependency. Profile bodies reject role/group fields and other-account selectors. Name, preferred label, email, verification flag, Google provider group and frontend role display cannot grant API Admin. The SPA's accepted client binding excludes the Streamlit client. Existing public market/health routes expose no new account-write/admin capability.

Group membership is verified from the issued token. Removing a group does not rewrite an existing JWT: role revocation requires token expiration/refresh or appropriate session revocation. Live activity checks detect revoked sessions, not current group membership. Do not promise immediate group-removal enforcement without revocation. React stores the OIDC session in tab-scoped sessionStorage; protection against XSS remains necessary. No tokens were copied into tests/reports.

Streamlit's verified Cognito flow additionally requires verified email and independently derives the same Admin group. It was inspected read-only; its existing behavior and client were not modified.

## Safe application changes implemented

1. A known Cognito attribute-write permission refusal now becomes sanitized **403 ATTRIBUTE_NOT_WRITABLE**, rather than **401 session expired**. Actual expired/revoked token errors still return 401. Unknown authorization failures still fail closed.
2. The profile editor renders the central client's allowlisted error text, including permission refusal, rate limit, provider ownership and reconnect requirements. Raw provider diagnostics remain hidden.
3. The Cognito gateway independently rejects any UpdateUserAttributes payload outside `name`/`preferred_username`, duplicate field names, extra targets or malformed attribute rows. This is a second application boundary in addition to Pydantic; it does not claim to restrict direct provider calls.
4. The frontend rejects inconsistent capabilities that say a Google-mapped name is editable. No email, verification, MFA, identity-link, group or internal-ID control was added.

Current editor capabilities match the audited live configuration. They are not a dynamic DescribeUserPoolClient permission lookup: if an administrator later restricts a permitted field, the provider remains authoritative and the application reports a safe permission failure. No new IAM runtime permission was added.

## Approval proposal A — SPA-only attribute allowlist, NOT APPLIED

Target only SPA client `4t8s6a673a18qhbauqac8rhdcf` in pool `us-east-1_NLoYFRvex`.

| Field | Current | Proposed exact value |
| --- | --- | --- |
| ReadAttributes | Omitted/default | `["sub","email","email_verified","name","preferred_username","identities"]` |
| WriteAttributes | Omitted/default | `["email","name","preferred_username"]` |
| All other described client settings | Existing values | Preserve unchanged |
| Google mapping / Streamlit client / pool policies / user records / groups | Existing values | Preserve unchanged |

Rationale: retain only account presentation, identity linkage and the approved profile fields. Email must remain because it is required and federated. Do not add verification flags, username, identities, `oidc:profile` write shorthand, phone or role fields to writes. `sub` is always a provider identifier, never a writable target.

Risks and residuals:

- Missing a necessary readable claim could hide account fields or affect existing ID-token/userInfo consumers of this SPA client. The proposed identities read preserves federation ownership detection.
- Google-mapped name/email must retain necessary provider write handling; verification flags remain provider controlled. Recheck a complete Google login after the change. Validation failure must abort, not remove federation mappings.
- Cognito may propagate changes asynchronously. A saved describe response alone is insufficient acceptance; obtain fresh tokens and perform both native and Google tests.
- This narrows unrelated fields; **it does not make required email read-only, restrict all own-account operations, or harden the other client**. It is not a fix for verification-before-update.

Apply procedure after explicit approval:

1. Re-describe the SPA client and validate expected identity, all four scopes, existing providers/callbacks/logout, and that no unrelated settings drifted. Retain an access-controlled rollback snapshot of the non-secret SPA settings only. Never capture provider credentials or Streamlit secrets.
2. Construct UpdateUserPoolClient from **all existing accepted input fields**, changing only these two lists. Do not pass the small proposal JSON as a complete update: omitted client fields can reset to defaults. Do not update the pool, IdP or other client.
3. Re-describe and compare every saved field, ignoring LastModifiedDate. Require exactly ReadAttributes and WriteAttributes changes. If there is any additional difference, stop and review/rollback.
4. Verify fresh Google Admin and native Analyst login, both self-service profiles, permitted edits on designated test accounts, rejected non-allowed fields, recovery, logout and all Admin denials. Require owner credential entry; never copy tokens.

Rollback: re-describe the client, compare against the after-change snapshot to avoid overwriting concurrent administrator work, then submit the full preserved configuration with the two permission fields returned to their original omitted/default state. Re-describe to verify effective defaults and unchanged remaining settings; repeat fresh native/Google acceptance. Rollback restores the previously broader attribute rights, so it needs an explicit decision and does not repair any user data changed while rights were active. No user data changes are planned in this review.

The exact proposal is also saved in `phase4d2-spa-attribute-proposal.json` as a review artifact; it is deliberately **not a runnable update request**.

## Separate recommendations outside approval A

- Review all pool clients before treating any attribute as pool-wide protected; the Streamlit client needs its own production compatibility review and approval.
- Verification-before-email-update, MFA, self-service account deletion policy, any broker/BFF redesign or role revocation policy are separate decisions. No pool-wide settings are proposed for application in this task.
- Never introduce mutable `role`, `admin`, subscription or entitlement attributes without removing their write access from every client. Keep PowerFlow roles bound to verified groups.

## Validation

Automated: **582 backend tests passed**, including 24 new cases for sensitive-field rejection, gateway defense, correct 403 versus revoked-token 401, and profile labels not affecting group authorization. **45 frontend tests passed**, including safe editor permission errors and conflicting Google capabilities. Lint and production build passed. One existing Starlette/httpx TestClient deprecation warning remains.

Real-account baseline evidence: Phase 4D.1 recently verified Google Admin and native Analyst login, four-scope GetUser, permitted edits, all seven native Admin-only 403 responses, password change/recovery, logout and reauthentication. Phase 4D.2 safe read-only checks and limits are recorded below as completed. No destructive/forbidden provider mutation is performed to prove a refusal on existing users; signed-JWT/mocked-provider regression tests cover those negative cases. No new account or identity link is created.

## Changed files in Phase 4D.2

- `src/api/account_service.py` — permission-denial classification and defensive profile allowlist.
- `frontend/src/api/profile.ts` — safe editor errors and provider capability consistency.
- `frontend/src/components/account/ProfileEditor.tsx` — accurate sanitized errors.
- `tests/test_account_management.py`, `frontend/tests/profile.test.ts` — regression cases.
- This report, the review-only proposal JSON, and the Phase 4D.1 report cross-reference.

Pre-existing dirty files were preserved. No dependencies, deployment, commit, push or merge.

## Sources

[AWS client attribute permissions and required fields](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html), [shared attributes and least privilege](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-attributes.html), [federation mapping](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-specifying-attribute-mapping.html), [access-token scopes/groups](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html), [scope-authorized DeleteUser boundary](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_DeleteUser.html), [UpdateUserPoolClient defaults](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_UpdateUserPoolClient.html).


### Phase 4D.2 live read-only results

After the application fixes, the original native profile remained Analyst with verified email, unchanged **Nganga** fields and native password capability. A separate tab completed fresh Google authentication with all four scopes and returned the existing Google Admin identity; mapped name remained read-only and preferred label unchanged. A temporary local development UI used the existing central API client to display only server role and HTTP status (never tokens or response bodies):

| GET path | Native Analyst | Google Admin |
| --- | --- | --- |
| `/admin/forecast/provenance` | 403 | 404: local report absent |
| `/admin/monitoring/forecast-vintages` | 403 | 404: local report absent |
| `/admin/monitoring/exogenous-readiness` | 403 | 404: local report absent |
| `/admin/models/linear-feature-influence` | 403 | 200 |
| `/admin/operations` | 403 | 200 |
| `/monitoring/forecast-vintages` | 403 | 404: local report absent |
| `/monitoring/exogenous-readiness` | 403 | 404: local report absent |

These 404 responses occur after authorization and retain the documented missing-local-report behavior; no report was fabricated. The temporary development UI was removed after verification. There were no user-attribute writes, no group changes and no identity links. No new password reset was triggered; the recently completed owner-led recovery and credential acceptance in Phase 4D.1 remain the real-account evidence for those unchanged paths.


The Google edit form was opened and cancelled without submitting: only the preferred label was editable, with the Google name managed by its provider and no email input. Google sign-out returned to the local sign-in gate, and reload stayed gated. The original native tab retained its separate session and was reloaded for fresh provider-backed profile verification. The review tab was created only for testing and was not retained as a product artifact.
