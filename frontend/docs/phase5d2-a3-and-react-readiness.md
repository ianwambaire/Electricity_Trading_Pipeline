# A3 and React deployment — remaining execution review

26 October 2026. Local preparation and parallel local code/report review only. **No AWS/SDK/SSH call, transfer, restoration, credential creation, deployment or Git staging/history operation was performed.** This report consolidates the next decisions; the [full A3 review](phase5d2-a3-offhost-recovery-review.md) retains exact source paths, hashes, costs, failure handling and prior live evidence.

## 1. Exact next IAM inspection — approval required

The known instance profile is `PowerFlowEC2Role`, account870755688674. The matching role name is a hypothesis to confirm, not permission to enumerate IAM. Proposed batch: each command once, in this order, existing default profile, no automatic retries. Root is allowed **for this read-only review only**.

```sh
aws iam get-instance-profile --instance-profile-name PowerFlowEC2Role --region us-east-1 --no-cli-pager
aws iam get-role --role-name PowerFlowEC2Role --region us-east-1 --no-cli-pager
aws iam list-role-policies --role-name PowerFlowEC2Role --region us-east-1 --no-cli-pager
aws iam list-attached-role-policies --role-name PowerFlowEC2Role --region us-east-1 --no-cli-pager
```

After command1, confirm profile ARN is `arn:aws:iam::870755688674:instance-profile/PowerFlowEC2Role` and exactly one role is returned with ARN `arn:aws:iam::870755688674:role/PowerFlowEC2Role`. If names/account differ, STOP before command2, report the binding; do not guess another role. Stop on any error/permission denial; no retries or automatic repair. For command2, verify same role/account; privately retain the trust document, report only relevant trust/permissions-boundary conclusions. No user names, trust-policy bodies or unrelated identity details in public report.

These four commands identify **only the known runtime role**, its boundary reference and policy references. They do not fetch policy bodies or establish all effective permissions. Historical evidence already found scoped `s3:DeleteObject` and `s3:DeleteObjectVersion` allows; the new `recovery/phase5d2-a3/...` key range must be compared against actual Resource/Condition patterns rather than assuming the older backup-prefix allow matches it.

**Next, separately approved policy-body batch:** substitute only exact names/ARNs returned by that role review, with each concrete command submitted before execution:

```sh
aws iam get-role-policy --role-name PowerFlowEC2Role --policy-name EXACT_RETURNED_INLINE_NAME --region us-east-1 --no-cli-pager
aws iam get-policy --policy-arn EXACT_RETURNED_ATTACHED_OR_BOUNDARY_ARN --region us-east-1 --no-cli-pager
aws iam get-policy-version --policy-arn EXACT_RETURNED_ATTACHED_OR_BOUNDARY_ARN --version-id EXACT_RETURNED_DEFAULT_VERSION --region us-east-1 --no-cli-pager
```

No `list-roles`, `list-users`, `get-account-authorization-details`, credential reports, access-key enumeration or account-wide scans. Policy text stays private. Compare allows/denies for PutObject, DeleteObject, DeleteObjectVersion, PutBucketPolicy, DeleteBucketPolicy, PutBucketVersioning, PutLifecycleConfiguration and privilege-changing IAM actions against this bucket/two keys. Boundaries limit identity policies; trust alone does not establish access. Without separately scoped SCP/session-policy evidence, do not claim a complete account-wide effective-permission proof; explicit bucket denies and isolated live acceptance remain relevant.

**Uploader/reader identities:** none is verified in existing evidence. The default CLI was root; the instance role is not automatically an approved Mac assume-role identity. The owner must nominate existing non-root role ARNs (one or two roles with distinct least-privilege sessions) before preparing their exact `get-role`/policy-reference commands. For a specifically nominated IAM user, inspect only that user's policies/group membership and only the returned groups after separate approval. Do not discover candidates by enumerating unrelated users/roles, reuse production runtime credentials, alter trust or create long-lived keys. If no suitable identity exists, request approval for a concrete short-lived-role design, not a broad managed policy attachment.

## 2. Minimal proposed S3 access changes — not applied

Already verified: us-east-1, all four public-access blocks true, versioningEnabled, SSE-S3/AES256, BucketOwnerEnforced, SSE-C blocked. **Preserve these exactly.** No KMS key/new bucket required if narrow policies are safe. Bucket policy/lifecycle absent.

Scope object permissions to these two ARNs:

```text
arn:aws:s3:::powerflow-data-ian-2026-870755688674-us-east-1-an/recovery/phase5d2-a3/20261026T022230.137446Z/electricity_trading.db
arn:aws:s3:::powerflow-data-ian-2026-870755688674-us-east-1-an/recovery/phase5d2-a3/20261026T022230.137446Z/manifest.json
```

Proposed additive controls, after named-principal review:

- On these two keys, deny insecure transport; deny PutObject except the approved uploader role; deny writes missing/wrong `s3:x-amz-server-side-encryption=AES256` or `s3:if-none-match=*`. Separate deny conditions are needed so either incorrect header is rejected. Do not apply a broad bucket-wide change that can break pipeline consumers.
- Deny DeleteObject/DeleteObjectVersion on these keys for all principals during this exercise. No routine runtime/reader/uploader deletion exception; future cleanup needs its own exact policy-delta approval. This is protection against ordinary credentials, **not** irreversible Object Lock: privileged policy administrators can remove the deny.
- Uploader identity policy: PutObject plus GetObjectVersion for exact-version HEAD on those two keys, and only the bucket configuration reads performed by the preflight. No delete/configuration/ACL grants. Reader: GetObjectVersion limited to actual two VersionIds once known. No listing needed.
- Restrict reading these keys to approved uploader/reader roles if existing policies otherwise grant other runtime identities access. Any privileged custodian exception must be named/reviewed. Backup messages may be sensitive; public blocking alone is insufficient.
- Do not remove existing pipeline permissions outside this recovery scope. Do not add lifecycle deletion, Object Lock, KMS, credentials or snapshots.

Final policy JSON/hash, exact principal ARNs, current-versus-proposed diff, private policy backup and rollback commands follow the read-only IAM results and require separate approval. No policy document with guessed identities will be applied. If prefix isolation cannot be introduced safely, present the dedicated-bucket alternative separately; no automatic expansion.

## 3. A3.2/A3.3 ready procedures and blockers

The [full A3 review](phase5d2-a3-offhost-recovery-review.md#4-separate-approval-a32--stage-the-fixed-pair-and-upload) contains the exact fixed two-file SCP command with strict host-key verification, new private Mac transfer path, encrypted-workstation prerequisites and180s/5s supervisor. It now binds the verified bucket in both script and command. A1 original is read only; no SSH inspection or production DB read is added. Transfers require new explicit approval.

From repository root, **after** separately approved staging of the fixed pair:

```sh
venv/bin/python -B deploy/remediation/a3-bounded-local.py -- venv/bin/python -B deploy/remediation/a3-offhost-recovery.py upload --source /Users/iannganga/powerflow-a3-transfer-20261026T022230.137446Z --bucket powerflow-data-ian-2026-870755688674-us-east-1-an --receipt /Users/iannganga/powerflow-a3-transfer-20261026T022230.137446Z/upload-receipt.json
```

Only two checksum-bearing conditional AES256 PUTs, exact-version HEAD verification, private exclusive receipt; no overwrite/delete/retry. Source DB hash/size, manifest/schema/index/integrity/count checks precede upload. Private canonical receipt parent is now checked before PUTs. Local SDK boto3**1.43.98** service models support PutObject IfNoneMatch/ChecksumSHA256/ExpectedBucketOwner and GetObject/HeadObject VersionId/ChecksumMode; verified locally without obtaining credentials or making a client/network call.

For A3.3, after actual upload receipt/VersionIds exist:

```sh
venv/bin/python -B deploy/remediation/a3-bounded-local.py -- venv/bin/python -B deploy/remediation/a3-offhost-recovery.py restore --receipt /Users/iannganga/powerflow-a3-transfer-20261026T022230.137446Z/upload-receipt.json --receipt-sha256 ACTUAL_APPROVED_RECEIPT_SHA256 --workspace /Users/iannganga/powerflow-a3-independent-20261026T022230.137446Z
```

The receipt SHA placeholder cannot be filled before upload; it is an explicit approval gate. Retrieval uses exact versions, never EC2 or staged DB as fallback. Full A2 isolated restore checks and durations run on the encrypted Mac with no extra EC2. Preserve partial artifacts and stop on failure; no automatic retry or deletion.

**Execution blockers:** non-root identities and exact access protections; separately approved policy application/readback; owner confirmation of encrypted local disk, directory permissions/free space and destination authorization; source transfer approval; exact SDK credential/role session to use. Script currently enforces account and non-root, but not a chosen role because no role has yet been approved: bind/verify that role before live execution, do not claim any non-root identity is acceptable. A3.3 additionally requires actual receipt digest/versions and version-scoped reader grants. A1 is an October26 point-in-time recovery set, not an ongoing backup schedule or current application recovery guarantee.

## 4. Shortest safe staging/cutover sequence

Run local work while execution approvals/data evidence are obtained:

1. **Local, no production approval needed:** regression/import/dependency checks, frontend test/lint/build and artifact guard; static release/unit/proxy review; approved local snapshot/browser parity and rollback manifest preparation. Linux packaging can be reproduced locally only with a suitable existing approved Linux runtime—do not install a container engine silently.
2. **A3:** approved bounded runtime IAM review → approve named non-root roles/policy bodies → exact access-policy diff/readback → separately approved A3.2 transfer/upload → separately approved A3.3 independent restore. No new permanently running EC2.
3. **Recovery/infrastructure gates:** inventory actual required PostgreSQL/Prefect/MLflow/model/dataset/configuration recovery scope; arrange independent consistent recovery coverage. A1/A2 are satisfied but full-store/off-host/root-encryption gates are not. Separately resolve TLS renewal (historical timer disabled/inactive), dedicated service identity/IMDS isolation/coherent read-only publication, and passive normal-scheduled peak RAM/swap/I/O evidence. Do not conflate an idle2GiB host snapshot with safe Streamlit+React/API overlap.
4. **Approve bounded staging:** exact hostname/origin/Cognito callbacks/logout, Nginx/ACME paths, Linux API environment and unit, release/data paths, cost/lifetime. Use existing host only if measured overlap/isolation is acceptable; otherwise separately approve a short-lived bounded alternative. Preserve production Streamlit and run no duplicate scheduler. Validate Linux imports/locks, `nginx -t`, systemd unit and effective sandbox before activation.
5. **Staging acceptance:** Google/native/TOTP user-controlled sign-in, server-side roles and seven Analyst403s, logout, seven-page real-data parity, denied writes/metadata, resource limits, private readiness, proxy/errors and rollback rehearsal. Missing data must be explicit; mocks do not close production-data gates.
6. **Separate production cutover approval:** exact apex `powerflowenergy.dev` Nginx/API/static/Cognito diff, maintenance/rollback window and abort criteria. Keep pipeline/data and original Streamlit client/release recoverable. After proposed>=7days stable operation and acceptance, separately approve Streamlit stop/disable; later separately approve code/dependency/client cleanup. No database restore merely for a frontend rollback; preserve newer pipeline writes.

### Explicit application backlog: next-24-hour electricity prices

**Restore legitimate next-24-hour forecast availability/publication**, rather than inventing a new forecast or replacing a model. API `/forecast/next24` and React Forecast Intelligence/Executive Overview rendering already exist. Current local evidence lacks the legitimate next24/realized-error/monitoring report generation. Diagnose expected `data/reports/next24h_forecast.csv`, issue/target UTC/h+1…h+24, production model/release, source completeness and coherent publication using local evidence first. Obtain approved real report data or separately approved production diagnosis where needed. Do not weaken completeness/withholding, substitute one-hour predictions, fabricate values or relabel historical records live. Treat genuine success-path parity as a release gate, or obtain explicit owner acceptance of documented unavailability before demonstration/cutover.

## 5. Changes and local validation

This preparation changed:

- `deploy/remediation/a3-offhost-recovery.py`: verified bucket binding, receipt-parent preflight.
- `tests/test_a3_offhost_recovery.py`: pinned-bucket regression and matching fixture updates.
- `frontend/docs/phase5d2-a3-offhost-recovery-review.md`: bound procedures/current hashes and preparation status.
- This consolidated readiness report.
- `frontend/docs/phase5d1-staging-preflight-and-approval.md`: corrected historical recovery gate to acknowledge A1/A2.

68 focused recovery tests passed in2.83s, including synthetic S3 round-trip and A2 validation. Existing frozen A2 payload unchanged. Local SDK capability check passed. No frontend/backend application behavior changed, so frontend test/lint/build and full application regression results are not newly claimed; these remain local release checks in step1. No production or real-account checks were performed. Current hashes are in the full A3 review; changed A3 code requires review of the new hash before execution. No superseded hash approval authorizes new bytes.

**Next exact approval requested:** only the four IAM commands in section1, with stated role/account stop conditions. This does not authorize policy-body follow-ups, IAM/S3 changes, non-root credential creation, source transfer, upload, restore, SSH inspection or deployment.

## Approved IAM attempt — stopped on mandatory ARN mismatch

26 October 2026: executed command1 (`get-instance-profile --instance-profile-name PowerFlowEC2Role --region us-east-1 --no-cli-pager`) once using the existing default profile. **Exit0**. Returned profile ARN `arn:aws:iam::870755688674:instance-profile/PowerFlowEC2Role`, with exactly one associated role, ARN `arn:aws:iam::870755688674:role/PowerFlowEC2Role`.

The execution authorization instead required both ARNs to equal `arn:aws:iam::870755688674/PowerFlowEC2Role`, omitting the IAM ARN resource-type separator and resource type. Neither returned ARN equals that literal value. Stopped immediately per mandatory mismatch condition; no corrected value was substituted automatically. AWS returned a successful response, not a service error. Returned identities match this report's original proposal but do not satisfy the subsequent authorization's literal checks.

Commands2–4 were **not executed** (no exit statuses). Inline policy names, attached managed-policy names/ARNs and permissions-boundary status remain **unverified by this attempt**; no trust-document conclusions are asserted. Trust-policy bodies were not displayed or retained. Private aggregate response evidence only: `/tmp/powerflow-a3-iam-command1-result.json` (0600). No additional AWS call, retry, policy-body inspection, IAM/S3 change, SSH, transfer, deployment or Git staging/history operation followed.

Next approval needed: corrected profile check `arn:aws:iam::870755688674:instance-profile/PowerFlowEC2Role` and role check `arn:aws:iam::870755688674:role/PowerFlowEC2Role`, then one execution of remaining commands2–4 (or a newly approved whole sequence if fresh binding evidence is desired). The successful command1 is not automatically retried.

Minimum later policy-body review remains separately approval-gated: one `get-role-policy` per exact returned inline name; for each exact returned attached/boundary policy ARN, one `get-policy` to identify its default version, then one `get-policy-version` for that exact version. Names/ARNs/versions cannot be concretized until the remaining reference-only commands succeed. No broad IAM enumeration or policy-body call is currently authorized.

## Newly approved get-role attempt — stopped on exact comparison

26 October 2026: the user explicitly authorized a new three-command sequence, requiring `Role.Arn` to equal literal `arn:aws:iam::870755688674/PowerFlowEC2Role`. Executed only `aws iam get-role --role-name PowerFlowEC2Role --region us-east-1 --no-cli-pager`, once under the existing default profile. **Exit0**. Actual `Role.Arn`: **`arn:aws:iam::870755688674:role/PowerFlowEC2Role`**. No permissions boundary was present in the returned role metadata. Trust-policy contents were neither emitted nor retained; no trust conclusions are asserted.

The actual role ARN did not equal the mandated literal, which omits `:role/`. Stopped immediately; `list-role-policies` and `list-attached-role-policies` were **not executed**, and their exit statuses/policy names remain unavailable. No retry, extra AWS command, policy-body read, modification, SSH, transfer, deployment or Git staging/history operation occurred. The local documentation update is the only persisted change in this attempt.

A future approval can avoid the formatting ambiguity by explicitly authorizing the two remaining reference-only list commands for the **actual ARN returned by get-role**, without requiring another get-role or the malformed literal. Policy-body inspection still requires separate approval after names/ARNs are known.
