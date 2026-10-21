# Approved SPA attribute allowlists — application record

## Status

The approved two-list change was accepted and saved by Cognito on **21 October 2026 at 12:41:53 Africa/Nairobi** (09:41:53 UTC). Only ReadAttributes and WriteAttributes changed, apart from AWS's LastModifiedDate. Post-allowlist native Analyst acceptance is verified: profile retrieval, reversible permitted editing, all seven Admin-route denials and current-session sign-out passed. Fresh Google acceptance is now verified (see follow-up below); post-change password operations remain unverified; do not infer those results from a successful configuration save.

## Exact saved configuration

Target: pool `us-east-1_NLoYFRvex`, existing React SPA client `4t8s6a673a18qhbauqac8rhdcf`.

```json
{
  "ReadAttributes": ["email", "email_verified", "identities", "name", "preferred_username", "sub"],
  "WriteAttributes": ["email", "name", "preferred_username"]
}
```

AWS reordered the approved read list; membership is identical. Full before/after comparison verified every other described client field unchanged, ignoring only LastModifiedDate. Preserved settings include:

- OAuth scopes: email, openid, profile, aws.cognito.signin.user.admin.
- Authorization Code flow; COGNITO and Google federation.
- ALLOW_REFRESH_TOKEN_AUTH, ALLOW_USER_AUTH, ALLOW_USER_SRP_AUTH.
- Callback `http://localhost:5175/auth/callback`; logout `http://localhost:5175/`.
- Access/ID lifetimes 60 minutes; refresh lifetime 5 days; validity units unchanged.
- Token revocation enabled; refresh rotation unchanged/not configured.
- Every other returned SPA setting, not merely this selected list.

Before/after fingerprints also matched for the complete pool configuration, Google provider configuration, original Streamlit client configuration and group definitions. No user record, group membership, pool policy, MFA or IdP mapping write operation was performed. No deployment, merge, commit or push.

## Google mapping preflight

The live mapping exactly matched the prior review:

| Destination ← Google source | Compatibility with approved lists |
| --- | --- |
| email ← email | Required mutable field retained in reads/writes |
| name ← name | Mutable field retained in reads/writes |
| email_verified ← email_verified | Provider-controlled verification flag retained in reads; ordinary client writes to verification flags are not permitted |
| username ← sub | Cognito provider-derived identity identifier, not an ordinary writable user attribute; sub retained in reads, excluded from writes |

No mapping was added or changed. No unexpected mapped field was found. The application aborted on any preflight mapping drift rather than inventing permissions. AWS accepted the exact approved lists without adjustment. Fresh Google login/profile verification subsequently passed; see the follow-up below. A successful save alone was not treated as runtime proof.

References: [AWS mapping requirements and derived username](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-specifying-attribute-mapping.html), [provider-controlled verification flags and required attributes](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html).

## Protected backup and rollback

Prepared **before** the mutation in this Git-ignored directory:

`/Users/iannganga/Desktop/electricity-trading-pipeline/backups/cognito-spa-attributes-20261021T094109Z/`

Directory mode 0700; backup/request/procedure/evidence files mode 0600. Files include:

- `before-client.json`: complete described SPA configuration (public client, no client secret).
- `rollback-request.json`: all existing fields accepted by UpdateUserPoolClient, preserving original omitted/default attribute permissions.
- `approved-update-request.json`: the same preserved input configuration with only the approved lists changed.
- `ROLLBACK.txt`: procedure prepared before change, with exact command and drift guard.
- `after-client.json`, `verification.json`, and before/after fingerprints for unrelated configuration.

No provider secret, Streamlit client configuration or raw user token is persisted in this backup. Other configuration comparison uses hashes. Keep this protected backup outside Git; do not publish it with frontend assets.

Rollback is prepared but **not performed**:

1. Re-describe the SPA and compare it with `after-client.json`, ignoring modification time and attribute-list order. Stop if another administrator changed settings; do not overwrite concurrent work.
2. Review `rollback-request.json`. The original attribute fields were absent, so the complete rollback request omits them to restore provider defaults while preserving all other saved fields. This broadens permissions back to their prior state and needs an explicit rollback decision.
3. Exact command after that decision:

```sh
aws cognito-idp update-user-pool-client --region us-east-1 --cli-input-json file:///Users/iannganga/Desktop/electricity-trading-pipeline/backups/cognito-spa-attributes-20261021T094109Z/rollback-request.json --no-cli-pager
```

4. Re-describe and compare against the complete before snapshot, ignoring LastModifiedDate. Confirm default attribute permissions and all other settings; repeat fresh Google/native acceptance. Do not silently add alternate attributes if restoration or verification fails.

Rollback does not undo issued tokens, change user data back, or bypass configuration propagation. No automatic rollback was attempted.

## Post-change verification

| Check | Result |
| --- | --- |
| Complete before snapshot / rollback prepared first | Passed |
| AWS update accepted exact lists | Passed |
| Complete saved SPA field comparison | Passed; only the two lists plus modification timestamp changed |
| Other pool/IdP/Streamlit/group configuration fingerprints | Passed, unchanged |
| Independent read-only AWS CLI saved-setting check | Passed |
| Backend regression | 582 passed; one pre-existing Starlette/httpx deprecation warning |
| Frontend regression / lint / build | 45 passed; lint/build passed |
| Fresh Google sign-in | Passed in follow-up: Code+PKCE, four-scope reauthentication, live profile retrieval, Admin role and Google provider confirmed |
| Fresh native sign-in and all seven Analyst Admin denials | Passed: owner completed native sign-in; `/auth/me` verified Analyst and all seven routes returned HTTP 403 |
| Post-change permitted profile update | Passed: preferred label saved as `Nganga allowlist check`, retrieved, immediately restored to `Nganga` and retrieved again; display name unchanged |
| Post-change current-session sign-out | Passed: Cognito logout returned to sign-in; direct navigation to `/profile` remained gated |
| Post-change password management | Native password capability retrieved and Change password available. No password change/recovery repeated after allowlists; earlier real tests remain pre-change evidence |

The native verification used a temporary development-only component through the existing authenticated API client; it displayed only the verified role and HTTP statuses and was removed immediately. No raw tokens or response bodies were extracted. All seven returned 403: `/admin/forecast/provenance`, `/admin/monitoring/forecast-vintages`, `/admin/monitoring/exogenous-readiness`, `/admin/models/linear-feature-influence`, `/admin/operations`, `/monitoring/forecast-vintages`, `/monitoring/exogenous-readiness`. Profile retrieval returned the verified native email and password capability; no connected Google identity was shown. No Google account or AWS settings were modified in this verification.

Earlier Google interactive limitation: one automatic browser permission review timed out; its one permitted retry passed the review but the browser command timed out. Rebinding then failed to reach the tab. This is not evidence of an AWS mapping incompatibility. No additional AWS change, permission expansion or rollback was attempted. Earlier Phase 4D.1/4D.2 acceptance remains historical evidence, not a substitute for the remaining Google and password post-change tests.

## Remaining risks

- Required email remains writable at Cognito; verification-before-update policy is unchanged. PowerFlow still exposes no email-update control.
- The original Streamlit client retains its default attribute permissions. Attribute values are shared across clients; this is SPA-only hardening.
- The reserved self-service scope still permits other own-account Cognito operations directly, beyond PowerFlow's gateway allowlist.
- Real fresh-token and account-action checks are necessary after propagation; existing sessions alone do not certify the changed configuration.
- Google-mapped name stays provider-managed; preferred_username is unmapped and user managed. Roles continue to derive exclusively from verified Cognito group membership.

See the [security review](phase4d2-identity-security-review.md) for the complete threat-boundary analysis and [prior acceptance](phase4d1-scope-diagnosis.md) for the tests completed before this AWS change.

## Remaining acceptance follow-up — 21 October 2026

Read-only AWS CLI reinspection confirmed exact approved ReadAttributes and WriteAttributes. The complete saved client matches the protected after snapshot after normalizing attribute/list ordering and equivalent CreationDate timezone formatting, excluding LastModifiedDate. No AWS update was performed.

The regression rerun passed: 582 backend tests (one existing Starlette/httpx deprecation warning), 45 frontend tests, ESLint and production build. Logs: `/tmp/powerflow-postallowlist-backend.txt` and `/tmp/powerflow-postallowlist-frontend.txt`.

Fresh Google login succeeded through Code + S256 PKCE. Ordinary three-scope login correctly required account reconnection. Explicit reauthentication requested `openid email profile aws.cognito.signin.user.admin` with prompt=login, then `/account/profile` loaded the Google-connected Admin with verified email and no native password control. Preferred username was changed from `Ian Wambaire` to `Ian Wambaire allowlist check`, retrieved, then immediately restored to `Ian Wambaire` and retrieved again. Google-managed name/email, identity links and groups were unchanged. This confirms live token-authorized own-account retrieval/update under the backend scope/subject checks without extracting raw tokens.

Google Admin authorization was verified after the restored profile settled: feature-influence and operations returned 200; the other five report URLs returned the expected missing-local-report 404 after authorization (none returned 401/403). The temporary development-only diagnostic displayed role/status only and was removed. Native Analyst previously returned 403 on all seven after the same allowlist change. Google current-session sign-out passed; direct navigation to `/profile` remained gated. Native post-change password change/recovery awaits owner credential entry; no post-change password success is claimed.
