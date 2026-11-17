# A3 access bootstrap — one proposed change authorization

**Preparation only; no command below has run.** Account870755688674, us-east-1. Existing verified identity: runtime role `PowerFlowEC2Role`, with broad object write/delete/version-delete on the existing bucket. Existing bucket has SSE-S3, versioning, Block Public Access and BucketOwnerEnforced; no bucket policy was present at the last check.

## Proposed identities, not existing discoveries

| New identity | Proposed exact ARN | Purpose |
|---|---|---|
| IAM user PowerFlowA3Operator | `arn:aws:iam::870755688674:user/PowerFlowA3Operator` | Human AWS browser login + MFA; same-device CLI Sign-In and AssumeRole only; no direct S3 |
| IAM role PowerFlowA3Uploader | `arn:aws:iam::870755688674:role/PowerFlowA3Uploader` | Two-key conditional encrypted PUT + version verification and bucket guards |
| IAM role PowerFlowA3Reader | `arn:aws:iam::870755688674:role/PowerFlowA3Reader` | Independent recovery identity; initially denied reads, later exact two VersionIds only |

Both roles trust **only the proposed operator user**, require MFA and MFA age<=300seconds. They do not trust root, EC2, Cognito users, an entire account or a guessed existing operator. The runner requests900second upload/restore sessions. Roles have3600second MaxSessionDuration (the IAM minimum), so other approved role sessions can last up to that limit; do not describe900seconds as a global role cap. Administrative bootstrap requires the owner's explicitly approved IAM administrator; the existing default was last verified root. If root is approved for this one bootstrap, that is separate from routine operation: the runner will still reject root for uploads/restoration. If root bootstrap is not acceptable, the owner must supply an existing approved IAM administrator. No privileged identity is invented or created automatically as a workaround.

The new IAM operator is **not** a PowerFlow/Cognito account. No existing Google Admin/native Analyst account, Cognito MFA, identity-provider mapping or Streamlit client is touched. Proposed IAM identities cost no standing monthly IAM fee; S3's small existing estimate remains below$0.001storage for two months plus negligible requests/transfer. No access keys, KMS, new bucket or EC2 are proposed.

## Exact files and protections

Review the five JSON documents beside this file and `SHA256SUMS.json`. Bucket policy denies apply to **only** these keys under bucket `powerflow-data-ian-2026-870755688674-us-east-1-an`:

- `recovery/phase5d2-a3/20261026T022230.137446Z/electricity_trading.db`
- `recovery/phase5d2-a3/20261026T022230.137446Z/manifest.json`

EC2 cannot write/read these keys because it is not an allowed role; all principals are denied DeleteObject/DeleteObjectVersion there. Uploader must use TLS, explicit AES256 and If-None-Match`*`; an existing current key cannot be overwritten. Deletion denies prevent routine creation of delete markers that would otherwise let conditional PUT recreate a current key. All unrelated runtime paths/grants remain untouched. Reader policy explicitly denies latest/current reads and all version reads until approved versions exist; later generated policy allows only those exact versions and denies other versions. Existing bucket encryption/public/versioning/ownership settings remain untouched.

This is not immutable retention: root/bucket-policy/IAM administrators can alter/remove these controls, change trust or impersonate the operator. Same-account protection is not protection from complete account compromise. There is no Object Lock, cross-account copy or claim of all-effective-permissions proof.

## Preconditions and bounded command sequence

Run from repository root **only after explicit approval of this complete batch and file hashes**. Use existing default profile only for administrator bootstrap, `AWS_MAX_ATTEMPTS=1`, no debug, no retries. Each command uses the existing local180second/five-second supervisor; prefix each `aws ...` invocation below with `venv/bin/python -B deploy/remediation/a3-bounded-local.py --`. No uploads/restoration/SSH is included.

1. `aws sts get-caller-identity --region us-east-1 --no-cli-pager`: require account870755688674; confirm the owner-approved administrator identity (last default was root; no silent alternate profile).
2. `aws iam get-user --user-name PowerFlowA3Operator --region us-east-1 --no-cli-pager`: require **NoSuchEntity**. Existing identity or other error is a STOP, not permission to reuse it.
3. `aws iam get-role --role-name PowerFlowA3Uploader --region us-east-1 --no-cli-pager`: require **NoSuchEntity**.
4. `aws iam get-role --role-name PowerFlowA3Reader --region us-east-1 --no-cli-pager`: require **NoSuchEntity**.
5. `aws s3api get-bucket-policy --bucket powerflow-data-ian-2026-870755688674-us-east-1-an --expected-bucket-owner 870755688674 --region us-east-1 --no-cli-pager`: require **NoSuchBucketPolicy**. If a policy now exists, STOP and preserve it privately for a new additive diff; never replace it blindly.

Only these expected absence errors permit continuation. Freeze local hashes first, require unchanged JSON and resource bindings. Preserve private0600 command results under a new operator-approved directory outside the repository. Policies have no credentials; full future results should still remain private. Execute each following line only after previous success:

```sh
aws iam create-user --user-name PowerFlowA3Operator --region us-east-1 --no-cli-pager
aws iam put-user-policy --user-name PowerFlowA3Operator --policy-name PowerFlowA3AssumeOnly --policy-document file://deploy/remediation/a3-access-package/operator-policy.json --region us-east-1 --no-cli-pager
aws iam create-role --role-name PowerFlowA3Uploader --assume-role-policy-document file://deploy/remediation/a3-access-package/mfa-operator-trust.json --max-session-duration 3600 --region us-east-1 --no-cli-pager
aws iam put-role-policy --role-name PowerFlowA3Uploader --policy-name PowerFlowA3Upload --policy-document file://deploy/remediation/a3-access-package/uploader-policy.json --region us-east-1 --no-cli-pager
aws iam create-role --role-name PowerFlowA3Reader --assume-role-policy-document file://deploy/remediation/a3-access-package/mfa-operator-trust.json --max-session-duration 3600 --region us-east-1 --no-cli-pager
aws iam put-role-policy --role-name PowerFlowA3Reader --policy-name PowerFlowA3Read --policy-document file://deploy/remediation/a3-access-package/reader-policy.json --region us-east-1 --no-cli-pager
aws s3api put-bucket-policy --bucket powerflow-data-ian-2026-870755688674-us-east-1-an --expected-bucket-owner 870755688674 --policy file://deploy/remediation/a3-access-package/bucket-policy.json --region us-east-1 --no-cli-pager
```

Use CLI timeout supervision and no retries as stated above. These administrative commands are proposed, not executed or automatically accepted. Command/API success is insufficient: read back exact state and compare JSON structurally, not formatting:

```sh
aws iam get-user --user-name PowerFlowA3Operator --region us-east-1 --no-cli-pager
aws iam get-user-policy --user-name PowerFlowA3Operator --policy-name PowerFlowA3AssumeOnly --region us-east-1 --no-cli-pager
aws iam get-role --role-name PowerFlowA3Uploader --region us-east-1 --no-cli-pager
aws iam get-role-policy --role-name PowerFlowA3Uploader --policy-name PowerFlowA3Upload --region us-east-1 --no-cli-pager
aws iam get-role --role-name PowerFlowA3Reader --region us-east-1 --no-cli-pager
aws iam get-role-policy --role-name PowerFlowA3Reader --policy-name PowerFlowA3Read --region us-east-1 --no-cli-pager
aws s3api get-bucket-policy --bucket powerflow-data-ian-2026-870755688674-us-east-1-an --expected-bucket-owner 870755688674 --region us-east-1 --no-cli-pager
aws iam list-access-keys --user-name PowerFlowA3Operator --query 'length(AccessKeyMetadata)' --region us-east-1 --no-cli-pager
```

Require exact new user/role ARNs in the table above, exact trust/policies and **zero access keys**. No attached/group permissions are requested for this newly created user. If any step fails or ownership/account/name/JSON/hash differs, STOP. IAM eventual consistency is not permission for unapproved retries; record partial resources, request a specifically bounded follow-up. No auto-cleanup, privilege expansion, policy replacement or data transfer.

## Human setup and secure credentials

After verified bootstrap, the owner uses AWS's own IAM console to enable console sign-in for **this new operator only**, choose its password, and enroll an AWS virtual MFA device (suggested device namePowerFlowA3Operator). Do not use create-login-profile password arguments, create access keys or place passwords/seeds/codes in chat/repository. Setup is a manual part of the proposed authorization, not something executed here. Existing accounts/MFA remain unchanged.

Then use the supported AWS CLI browser-login flow for a separate source profile, e.g. `aws login --profile powerflow-a3-operator`. The actual installed CLI/SDK provider's compatibility with that new IAM login is **not live-tested**. If it cannot yield the designated IAM user, STOP—no root fallback or access-key workaround. AWS-managed login caches reside outside the repository. Owner enters the password/MFA directly in AWS.

`run-a3-session.py` must be launched by the owner in an interactive Terminal; it rejects non-TTY input before AWS calls and suppresses SDK debug logging. It prompts locally for a current AWS operator MFA code, verifies source GetCallerIdentity exactly matches the new operator user, calls AssumeRole with that MFA serial/code and900second duration, and supplies the returned credentials to boto3 in memory. It never prints them, passes them in subprocess environment/argv, or writes them to any file. The existing A3 client then independently verifies the assumed role and storage guards. The runner pins the A3 payload hash and fails if it changes.

Future **separate A3.2 approval**, after the original two-file SCP and encrypted-Mac prerequisites:

```sh
venv/bin/python -B deploy/remediation/a3-bounded-local.py -- venv/bin/python -B deploy/remediation/run-a3-session.py upload --source-profile powerflow-a3-operator --mfa-device-arn arn:aws:iam::870755688674:mfa/PowerFlowA3Operator --source /Users/iannganga/powerflow-a3-transfer-20261026T022230.137446Z --bucket powerflow-data-ian-2026-870755688674-us-east-1-an --receipt /Users/iannganga/powerflow-a3-transfer-20261026T022230.137446Z/upload-receipt.json
```

After actual receipt/VersionIds exist, generate an exact-version reader policy using the existing compiler into a **new** private directory; approve/read back the one reader-policy delta. Future **separate A3.3 approval** uses the equivalent runner `restore` with the existing receipt, actual independently approved receiptSHA and new isolated workspace. No VersionId/digest is invented before upload. This bootstrap authorizes none of these transfers/recovery operations.

## Rollback and failure

This is not atomic. A failure can leave the new user/roles/policies; preserve them and report exactly which steps completed. No existing runtime grant/service was modified. Do not delete the bucket policy automatically: that would reopen broad EC2 access to any recovery objects already uploaded. Removing the identity-policy Allow alone does NOT prevent new sessions: this same-account trust directly grants the user access. Remove the operator from BOTH role trust policies or add an explicit deny to stop new sessions; already issued sessions can remain valid until expiry (900seconds requested by this runner, up to3600seconds for other role sessions). Any revocation, login/MFA removal, role/user deletion or bucket-policy rollback requires separate approval after inventory of only these newly created resources and any recovery objects. Never delete backup versions as rollback. If no objects exist and rollback is approved, remove only the new policies/roles/operator; no unrelated IAM or S3 resource is touched.

## Authentication-only gate (before bucket-policy activation or transfers)

Revised operator policy includes only `signin:AuthorizeOAuth2Access` and `signin:CreateOAuth2Token` on `arn:aws:signin:us-east-1:870755688674:oauth2/public-client/localhost`. No remote-login grant. References: https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html and https://docs.aws.amazon.com/aws-managed-policy/latest/reference/SignInLocalDevelopmentAccess.html (reviewed 2026-10-26). AWS CLI >=2.32; SDK must support login credentials. No long-lived keys.

Approve bootstrap steps 1–4 and IAM-only creation/readback above as one bounded batch; EXCLUDE bucket-policy read/write and all S3 calls. Authenticate the new operator in its own profile using `aws login --profile powerflow-a3-operator --region us-east-1`, then run the authentication-only helper below once per role. Owner enters IAM credentials/TOTP only in AWS or the local terminal. Newly proposed identities do not yet exist. Admin bootstrap is separate from routine operator identity.

```sh
venv/bin/python -B deploy/remediation/a3-bounded-local.py -- venv/bin/python -B deploy/remediation/run-a3-session.py upload --source-profile powerflow-a3-operator --mfa-device-arn arn:aws:iam::870755688674:mfa/PowerFlowA3Operator --authentication-only
venv/bin/python -B deploy/remediation/a3-bounded-local.py -- venv/bin/python -B deploy/remediation/run-a3-session.py restore --source-profile powerflow-a3-operator --mfa-device-arn arn:aws:iam::870755688674:mfa/PowerFlowA3Operator --authentication-only
```

The MFA Bool/age trust conditions remain mandatory. CLI login's temporary credential context and explicit AssumeRole TOTP are NOT assumed interchangeable: a new code does not prove the source MFA age refreshed. Both role assumptions must succeed server-side with the unchanged conditions; otherwise STOP without removing conditions, adding access keys or expanding permissions. Fresh browser MFA may be necessary; no automatic retry is authorized. Authentication-only prints only success/role, never credentials; no S3 operation occurs. Deny/expired-token paths are locally mocked, not live evidence.

Already-issued sessions require separate approved revocation: put an explicit deny-all role permissions policy on BOTH new roles and retain it through their maximum 3600-second lifetime before cleanup. Removing trust blocks new sessions but does not revoke existing ones. Do not delete S3 protection as an authentication rollback.
