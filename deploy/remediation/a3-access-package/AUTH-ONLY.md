# A3 IAM bootstrap + authentication only — requested approval

Proposed identities only: IAM user `PowerFlowA3Operator`, roles `PowerFlowA3Uploader` and `PowerFlowA3Reader`, all in870755688674. Existing EC2 role and bucket remain unchanged in THIS package. No bucket-policy activation, object access, transfer or recovery. Review `operator-policy.json`, `mfa-operator-trust.json`, `uploader-policy.json`, `reader-policy.json` and SHA256SUMS.json together; role S3 grants remain dormant until separately approved execution.

Run once sequentially with `AWS_PROFILE=default AWS_MAX_ATTEMPTS=1`, each `aws` invocation prefixed by `venv/bin/python -B deploy/remediation/a3-bounded-local.py --`. Capture privately mode0600 outside repository. Require exact870755688674 account and explicitly approved administrator identity; root may bootstrap only if explicitly approved, never routine upload. Stop on unexpected error/mismatch, no automatic retries. No other calls:

```sh
aws sts get-caller-identity --region us-east-1 --no-cli-pager
aws iam get-user --user-name PowerFlowA3Operator --region us-east-1 --no-cli-pager
aws iam get-role --role-name PowerFlowA3Uploader --region us-east-1 --no-cli-pager
aws iam get-role --role-name PowerFlowA3Reader --region us-east-1 --no-cli-pager
```

Last three MUST each return NoSuchEntity. Existing identity is STOP, not permission to reuse. Then:

```sh
aws iam create-user --user-name PowerFlowA3Operator --region us-east-1 --no-cli-pager
aws iam put-user-policy --user-name PowerFlowA3Operator --policy-name PowerFlowA3AssumeOnly --policy-document file://deploy/remediation/a3-access-package/operator-policy.json --region us-east-1 --no-cli-pager
aws iam create-role --role-name PowerFlowA3Uploader --assume-role-policy-document file://deploy/remediation/a3-access-package/mfa-operator-trust.json --max-session-duration 3600 --region us-east-1 --no-cli-pager
aws iam put-role-policy --role-name PowerFlowA3Uploader --policy-name PowerFlowA3Upload --policy-document file://deploy/remediation/a3-access-package/uploader-policy.json --region us-east-1 --no-cli-pager
aws iam create-role --role-name PowerFlowA3Reader --assume-role-policy-document file://deploy/remediation/a3-access-package/mfa-operator-trust.json --max-session-duration 3600 --region us-east-1 --no-cli-pager
aws iam put-role-policy --role-name PowerFlowA3Reader --policy-name PowerFlowA3Read --policy-document file://deploy/remediation/a3-access-package/reader-policy.json --region us-east-1 --no-cli-pager
aws iam get-user-policy --user-name PowerFlowA3Operator --policy-name PowerFlowA3AssumeOnly --region us-east-1 --no-cli-pager
aws iam get-role --role-name PowerFlowA3Uploader --region us-east-1 --no-cli-pager
aws iam get-role-policy --role-name PowerFlowA3Uploader --policy-name PowerFlowA3Upload --region us-east-1 --no-cli-pager
aws iam get-role --role-name PowerFlowA3Reader --region us-east-1 --no-cli-pager
aws iam get-role-policy --role-name PowerFlowA3Reader --policy-name PowerFlowA3Read --region us-east-1 --no-cli-pager
aws iam list-access-keys --user-name PowerFlowA3Operator --query 'length(AccessKeyMetadata)' --region us-east-1 --no-cli-pager
```

Require exact created ARNs under `arn:aws:iam::870755688674:user/PowerFlowA3Operator` and `arn:aws:iam::870755688674:role/PowerFlowA3Uploader` / `PowerFlowA3Reader`, structurally equal policy/trust JSON and zero keys. Any partial failure: preserve resources and stop, no rollback mutations automatically.

Owner performs console-password and IAM MFA enrollment for this NEW AWS operator only, as an explicit part of requested approval. Never Cognito identities. No passwords/MFA seeds in commands/chat. Minimum CLI2.32 and SDK login-provider support required. Owner runs same-device browser login, then exactly the two authentication-only commands in REVIEW.md. No `--remote` or access-key fallback. Stop if AssumeRole MFA context/age fails: TOTP does not prove renewed credential MFA age. Local mocks do not validate this AWS interaction.

Rollback, requiring explicit approval: first update BOTH role trust policies to a reviewed deny-all AssumeRole policy (rather than merely removing the operator Allow). For issued sessions, add explicit deny-all identity policies to BOTH new roles, wait at least3600seconds and verify before removal. Do not delete deny policies while active credentials remain. Console login/MFA/user/role cleanup is separate; never remove existing role/bucket protections or backup versions. High-privilege administrators can alter these controls; no account-compromise protection is claimed.
