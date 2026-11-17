# Phase 5D.2 A3 — encrypted off-host recovery execution review

26 October 2026. **PREPARATION ONLY. No AWS CLI/SDK call, SSH/SFTP connection, upload, resource/configuration change, snapshot or restoration against real artifacts was performed.** Public AWS documentation was consulted for pricing and API semantics. A0/A1/A2 approval does not authorize A3.

## 1. Recommendation and evidence

Use **S3 Standard in us-east-1, SSE-S3 (AES256), private, versioned**, with an append-only upload principal and a separate version-scoped recovery reader. Prefer the existing PowerFlow bucket **only if** a prefix-specific access review can protect recovery objects without disrupting pipeline access. Earlier evidence reports all four Block Public Access flags true, versioning Enabled and default AES256; no bucket policy/lifecycle/Object Lock. This is historical evidence, not a current check. The existing pipeline role reportedly can delete backup versions: do not treat it as an isolated backup writer. If protecting this prefix requires unsafe policy changes, propose a small dedicated recovery bucket for separate approval instead. No dedicated bucket is presumed to exist.

S3 protects against loss of the EC2 root volume, not loss/compromise of the entire AWS account. Same-account privileged administrators can still change ordinary policies. This is not immutable storage, cross-account disaster recovery or a complete application backup.

### Costs and credits

Indicative us-east-1 USD estimates, excluding tax, subject to regional rates at execution. Budget without assuming free-tier allowances:

| Option | Incremental cost and tradeoff |
|---|---|
| S3 Standard + SSE-S3 (recommended) | Planning rate $0.023/GB-month: 12,115,968 bytes = 0.012116 decimal GB, about **$0.00028/month** for DB alone; allow $0.00031 with <=1MiB manifest. Two months under $0.001 storage for this single pair. Two PUTs at $0.005/1,000 = $0.000010; two GETs at $0.0004/1,000 = $0.0000008; HEAD/control calls add negligible request charges. No extra EC2. |
| SSE-KMS | Same S3 storage plus KMS requests; a new customer-managed symmetric key typically **$1/month** plus requests (commonly $0.03/10,000). AWS-managed keys have different ownership/cost controls. KMS adds key policy/deletion/decrypt dependencies and potentially CloudTrail costs. Not justified for this small initial set absent a compliance/separate-key requirement. This payload intentionally refuses a KMS-default bucket; do not expand encryption mode without new review/tests. |
| Existing EBS/snapshots or AWS Backup | No independently verified suitable existing recovery resource in approved evidence. The root volume is unencrypted; same-volume directories are not off-host protection. New snapshots/vaults, agent/configuration, broad volume coverage and restore EC2 costs exceed this narrowly scoped pair. Not proposed. |

S3 Standard has no archival retrieval delay or minimum-duration penalty. EC2-to-local staging and local-to-S3 transfer each involve ~13MB maximum. AWS ingress is generally free; conservatively reserve **$0.01 total transfer/request overhead** for this one exercise rather than depending on free outbound allowances. One 13MB internet egress at $0.09/GB would be ~$0.0012; actual transfer tier/account rules apply. Same-region direct EC2/S3 would reduce hops, but would require approved constrained host IAM/runtime support; this proposal deliberately keeps AWS credentials on the user's Mac. A3 is negligible relative to $95 credits and the $47.50/month two-month average cap; it does not revalidate total hosting spend. Retaining 60 such daily pairs is a different scope (~0.79GB including maximum manifests, ~$0.018/month), not an approved schedule.

Credit eligibility, balance and expiration **not newly checked**. Eligible S3 charges ordinarily apply against eligible promotional credits, but grant-specific applicability/expiration must be verified in Billing; do not promise credits cover every charge. No new paid monitoring/log sink, KMS key, NAT gateway, EC2 or staging host is proposed. Sources: [S3 pricing](https://aws.amazon.com/s3/pricing/), [KMS pricing](https://aws.amazon.com/kms/pricing/), [AWS credit terms](https://aws.amazon.com/awscredits/), [credit application](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/useconsolidatedbilling-credits.html).

## 2. Fixed scope, scripts and hashes

Only accepted A1 pair:

- `/home/ec2-user/powerflow-recovery-phase5d2-operational/20261026T022230.137446Z/electricity_trading.db`
- Same directory's `manifest.json`.
- DB SHA-256 `21fcb0e920ffaf13f214e39720e1176e012086d6ffa7b8a7ed736b6e4ab79690`, exactly **12,115,968 bytes**.
- Counts: pipeline_runs 891; data_quality_results 16,525; operational_incidents 1,485; pipeline_stage_timings 11,561; total **30,462**. No production DB opened.

PostgreSQL, Prefect SQLite, MLflow, models, dataset directories, environments and secrets are **excluded**. Operational records may contain confidential messages; treat DB and manifest as confidential even though no contents are printed. The A1 heuristic scan is not guaranteed de-identification.

| Local code | SHA-256 |
|---|---|
| `deploy/remediation/a3-offhost-recovery.py` | `c3f428bc0f4f55c69253239285786366d6f9f6cbe14d1807ae10b5c4c3857ea4` |
| `deploy/remediation/restore-operational-sqlite.py` (unchanged pinned validator) | `e0144438075b5219a2b03a7dad982bab14bde81d92d6c79cf11253c91284262c` |
| `deploy/remediation/a3-bounded-local.py` (local180s/5s process-group supervisor) | `9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40` |
| `tests/test_a3_offhost_recovery.py` (local fixtures only) | `f52ca748cb30ef5f081086056a779b02bea71dba9bced35e71879ee1188d6390` |

The exact executable source is in those files, not an abbreviated inline rewrite. A3 verifies the A2 file hash before loading it. It uses existing boto3, already declared by the project; no new dependency or installation performed. Local interpreter must have boto3 and support conditional PutObject `IfNoneMatch`; otherwise STOP, do not install on production. Transport uses standard OpenSSH/SFTP; private key contents never read/displayed/copied by the agent.

## 3. Separate approval A3.1 — storage and access configuration

### First proposed action: read-only identification, not configuration permission

Bucket identity and constrained principal ARNs were omitted from prior sanitized reports. Do not invent them or execute placeholder commands. Request approval for **only** these workstation AWS commands, existing default profile, no SSH:

```sh
aws sts get-caller-identity --region us-east-1 --no-cli-pager
aws s3api list-buckets --query 'Buckets[].Name' --region us-east-1 --no-cli-pager
```

Confirm account **870755688674**. If identity is root, it may be identified read-only, but **STOP before mutations or data transfer** and arrange a user-approved non-root role/session; do not create access keys or change identities automatically. Do not print credential provider files or full environment.

After the owner identifies the existing PowerFlow bucket, request a bounded follow-up read-only review, with the actual bucket name substituted and approved:

```sh
aws s3api get-bucket-location --bucket APPROVED_BUCKET --expected-bucket-owner 870755688674 --region us-east-1 --no-cli-pager
aws s3api get-public-access-block --bucket APPROVED_BUCKET --expected-bucket-owner 870755688674 --region us-east-1 --no-cli-pager
aws s3api get-bucket-versioning --bucket APPROVED_BUCKET --expected-bucket-owner 870755688674 --region us-east-1 --no-cli-pager
aws s3api get-bucket-encryption --bucket APPROVED_BUCKET --expected-bucket-owner 870755688674 --region us-east-1 --no-cli-pager
aws s3api get-bucket-ownership-controls --bucket APPROVED_BUCKET --expected-bucket-owner 870755688674 --region us-east-1 --no-cli-pager
aws s3api get-bucket-policy --bucket APPROVED_BUCKET --expected-bucket-owner 870755688674 --region us-east-1 --no-cli-pager
aws s3api get-bucket-lifecycle-configuration --bucket APPROVED_BUCKET --expected-bucket-owner 870755688674 --region us-east-1 --no-cli-pager
```

Capture policy response privately, report only relevant access conclusions; no public policy dump. A missing policy/lifecycle is distinct from denied inspection. Object ownership was not previously verified; A3 requires BucketOwnerEnforced, never silently updates it. No object listing/data read in this batch. Narrow IAM policy inspection must be separately specified once the actual operator/reader/pipeline roles are identified; no broad IAM enumeration is authorized.

### Target configuration requiring its own exact diff approval

- Private bucket, us-east-1, all four Block Public Access flags true, versioning Enabled, default AES256, BucketOwnerEnforced. Retain all unrelated objects/configuration.
- Recovery prefix: `recovery/phase5d2-a3/20261026T022230.137446Z/` with exactly two fixed keys.
- Non-root upload principal: `s3:PutObject` on these **two exact object ARNs**, conditioned on `s3:x-amz-server-side-encryption = AES256` and conditional `s3:if-none-match = *`. No DeleteObject/DeleteObjectVersion/PutObjectAcl/configuration authority. HEAD exact-version verification requires `s3:GetObjectVersion` on these objects (S3 has no HEAD-only IAM permission); disclose this limited read permission rather than claiming a write-only identity.
- Preflight metadata permissions on bucket ARN: `s3:GetBucketLocation`, `s3:GetBucketPublicAccessBlock`, `s3:GetBucketVersioning`, `s3:GetEncryptionConfiguration`, `s3:GetBucketOwnershipControls`. No ListBucket required by upload script.
- Recovery reader: `s3:GetObjectVersion` only for the approved two object versions, using `s3:VersionId` conditions after upload. STS GetCallerIdentity for account/root checks; no writer/admin privileges.
- Bucket policy: deny insecure transport; deny recovery-prefix writes by principals other than approved uploader/retention operator; enforce AES256 and conditional writes; deny deletion/version-deletion for uploader, pipeline and ordinary runtime principals. A separately named retention custodian is the only planned deletion exception. Review *all* existing identity policies so a broad pipeline role cannot escape prefix protections. Preserve its non-recovery access.
- No Object Lock/retention lock, lifecycle deletion, cross-region replication, new KMS key or IAM credential creation in this first exercise. Versioning permits recovery from ordinary deletion but does not prevent privileged version deletion. Conditional writes inspect the current key only: a delete marker can allow a new version, which is why deletion restrictions and pinned versions both matter. [AWS conditional-write semantics](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).

**No executable bucket/IAM mutation command is approved or finalized here.** The unknown bucket/principal bindings and existing policy documents prevent a safe exact current-versus-proposed diff now. A3.1 must return the exact named policy JSON, resource ARNs, hashes, existing-setting backup and rollback commands for explicit approval before applying any change. Never attach broad managed S3FullAccess to make the transfer work. If the existing bucket cannot safely satisfy these requirements, separately review creation of one small dedicated bucket; not implicit approval.

## 4. Separate approval A3.2 — stage the fixed pair and upload

Preconditions: completed/verified A3.1; exact bucket and non-root principal approved; SDK capability confirmed locally; encrypted workstation disk/FileVault enabled and secure private parent directory; no cloud-synced staging folder; workstation disk has >=350MiB free. Stop if workstation encryption cannot be established by the user. Backup confidentiality extends to workstation staging.

Proposed workstation directory: `/Users/iannganga/powerflow-a3-transfer-20261026T022230.137446Z/` (must not exist). The owner must approve this path before execution; current workspace write permission does not imply authorization to create it. Exact source reads use SFTP through SCP with strict existing host-key trust, no agent, no remote script, no live DB, no remote modifications:

```sh
umask 077
mkdir -m 700 /Users/iannganga/powerflow-a3-transfer-20261026T022230.137446Z
venv/bin/python -B deploy/remediation/a3-bounded-local.py -- scp -F /dev/null -i /Users/iannganga/.ssh/powerflow-key.pem -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts -o ForwardAgent=no -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=3 ec2-user@3.228.243.164:/home/ec2-user/powerflow-recovery-phase5d2-operational/20261026T022230.137446Z/electricity_trading.db ec2-user@3.228.243.164:/home/ec2-user/powerflow-recovery-phase5d2-operational/20261026T022230.137446Z/manifest.json /Users/iannganga/powerflow-a3-transfer-20261026T022230.137446Z/
```

Execute sequentially, STOP on any nonzero command (do not paste as an unconditional multi-command batch). No `-p`, recursive copy, `-O`, host-key bypass or source wildcard. SCP reads only the two named files; normal SSH audit records/access times can change. It does not validate source file mode or remote sidecars: the accepted standalone A1 image is the trusted immutable artifact, and local cryptographic/schema validation gates uploading it. A1/A2 did not publish an independent manifest hash: initial manifest authenticity is bounded by trusted SSH plus matching DB/hash/schema/count checks; A3 creates a cryptographic manifest digest pinned in the recovery receipt for future tests. This is not a signed manifest.

From repository root, recheck the four code hashes above, then the exact upload invocation (replace bucket only after separately approving that binding):

```sh
venv/bin/python -B deploy/remediation/a3-bounded-local.py -- venv/bin/python -B deploy/remediation/a3-offhost-recovery.py upload --source /Users/iannganga/powerflow-a3-transfer-20261026T022230.137446Z --bucket powerflow-data-ian-2026-870755688674-us-east-1-an --receipt /Users/iannganga/powerflow-a3-transfer-20261026T022230.137446Z/upload-receipt.json --expected-role-arn APPROVED_UPLOADER_ROLE_ARN
```

Use a local process supervisor with a **180-second wall timeout per SCP or upload invocation**, terminate at timeout, wait five seconds, then kill that local process if necessary. Do not restart/retry automatically. The exact supervisor source/hash is included above and invoked in each command. It starts a separate local process group, returns124 on timeout, never retries or deletes artifacts. Final bucket/identity bindings must be reviewed before A3.2. Preserve stdout/stderr in new exclusive private0600 local capture files under the approved staging directory; do not log SDK debug output, SCP verbosity or credentials. Use a live monitored terminal if a private capture has not been approved. SDK calls have connect=5s/read=20s and total_max_attempts=1. A timeout after PUT has an **unknown remote outcome**; preserve output and request a separately approved exact-key/version reconciliation, never blindly rerun.

Validation before upload: fixed DB size/SHA, bounded <=1MiB manifest, matching manifest DB name/hash/size/table/schema, private regular files/canonical paths, no local sidecars, full SQLite integrity, FK check, six indexes/column contract, four counts. File bytes uploaded are exactly those validated in memory; no data rows or schema details printed. The original remote files are never written. Only two single-part PutObject requests, TLS verification enabled, expected owner pinned, AES256 explicit, full SHA256 checksum and `IfNoneMatch='*'`. No ACL, public URL, presigned URL, multipart upload or credentials in source.

Each successful PUT prints its non-secret key/version/size/hash immediately, then HEADs that exact version and checks size/SHA256/encryption/version. ETag is **not** treated as SHA256. A private exclusive 0600 receipt records both object versions, DB and manifest SHA256, sizes, bucket/account/region/ID. Record the receipt SHA256 separately in the verification report and keep an independently accessible private copy on the encrypted Mac; do not rely on an EC2-only receipt. No third S3 receipt object is uploaded. Receipts contain storage metadata, not row contents or credentials; keep them private anyway.

## 5. Separate approval A3.3 — independent restoration on the Mac

No new EC2 charge. Use only S3 and the private receipt; disconnecting or losing the original EC2 volume must not affect this test. The A3 code, pinned validator and Python dependencies must be retained off-host too, with hashes recorded here (source code only, no production secrets). Use a non-root version-scoped reader session. No SSH call or original staging DB is used by this subcommand.

After A3.2 yields actual VersionIds and receipt digest, review those exact bindings before approval. Proposed new private workspace (must not exist): `/Users/iannganga/powerflow-a3-independent-20261026T022230.137446Z/`.

```sh
venv/bin/python -B deploy/remediation/a3-bounded-local.py -- venv/bin/python -B deploy/remediation/a3-offhost-recovery.py restore --receipt /Users/iannganga/powerflow-a3-transfer-20261026T022230.137446Z/upload-receipt.json --receipt-sha256 ACTUAL_APPROVED_RECEIPT_SHA256 --workspace /Users/iannganga/powerflow-a3-independent-20261026T022230.137446Z --expected-role-arn APPROVED_READER_ROLE_ARN
```

The same reviewed local 180s supervisor/5s escalation is required. Validate receipt digest before using its storage identity. Download exactly two pinned versions, expected owner, SSE-S3 and service SHA256; cap reads, validate downloaded lengths/hashes against receipt (DB also against independently approved SHA/size). Files are exclusive0600 under0700 directories. No replacement, deletion, source fallback, URL fetching or remote code execution. Disk guard before download: >=3*12,115,968 +256MiB = **304,783,360 bytes** available; reused A2 applies an additional25%-filesystem-reserve guard before restoration. Stop rather than weaken either guard.

Restore from `workspace/download/` into new `workspace/restored/`, yielding `restored-electricity_trading.db` and `verification.json`. Full A2 integrity, separate FK check/count, expected schema/six indexes, all noninternal schema objects, four table counts, readonly connection/query flag, exact size/SHA and source preservation are required. A2 has its90s deadline; outer supervisor covers network/startup/reporting. A3 prints whole-operation duration and the A2 copy/validation timings. A3's top-level off-host success is true only after downloads and full restored validation pass; nested A2's original `off_host_backup_verified:false` is its conservative standalone contract, not a failed S3 test. Do not claim full-application recovery.

## 6. Failure, retention and cleanup

- Any denied/missing metadata, wrong owner/region/root identity, missing version/checksum, unexpected encryption, existing output, schema/hash/count failure or partial transfer: STOP. No permission broadening, alternate bucket, automatic retries, repair, overwrite, deletion or production fallback.
- PUT pair is not atomic. First object can exist when the second fails; stdout records successful versions where responses arrive. A failed or timed-out request may have committed without a response. Preserve all known metadata and artifacts. Do not claim a complete recovery set unless both exact versions and receipt verification passed.
- No automatic cleanup anywhere. Failed/local partial files, successful download/restore files and S3 versions remain. Do not rerun against the same directories or keys without a reviewed reconciliation plan.
- Retain the validated pair and independently held receipt for **at least the two-month migration window**, and until a newer independently tested backup is accepted. This is an operational retention plan, not an enabled lifecycle/Object Lock guarantee. No deletion date is an authorization to delete.
- After acceptance, propose separately approved deletion of exact local paths and exact S3 VersionIds (including noncurrent versions/delete markers if applicable); verify a replacement recovery point first. Do not recursively empty buckets, delete original A1/A2, change lifecycle, disable encryption/versioning or schedule key deletion. No cleanup commands included for accidental execution.
- Configuration rollback: preserve original IAM/bucket JSON before any later A3.1 mutation; restore only the reviewed delta if safe, never disable public protection/encryption as a convenience. Upload/restore rollback is simply stop and preserve artifacts: production state has not changed. A3 receipt-write failure may leave two valid uploaded objects but no receipt: reconcile separately.

## 7. Other stores: known evidence and minimum future inspection proposals

These inspections are **not executed or authorized by A3**.

| Store | Previously approved evidence / unresolved question | Minimum future read-only proposal for separate review |
|---|---|---|
| PostgreSQL | Service/processes observed; directory usage inaccessible/unknown. No verified database names/ownership or active Prefect binding. | Selected service metadata already approved previously does not expose backend config. Propose a custodian-run in-memory parser of **named** Prefect configuration, emitting backend type and sanitized DB identifier only, never URI/password/host; separately authorize catalog-only query for database names/size and connected application names, no rows, SQL text, users or credentials in report. Exact path/privilege method must be reviewed first; no sudo under existing approval. |
| Prefect | Server/worker active; candidate `~/.prefect/prefect.db` 1,302,528 bytes plus WAL4,132,392/SHM32,768 from A0. Candidate presence is not proof of active SQLite backend. | After approved sanitized binding check, fixed-path metadata of the identified store; if PostgreSQL, plan native consistent pg_dump separately; if SQLite, online SQLite backup including WAL semantics separately. No copying an active DB without WAL consistency. |
| MLflow | Checkout-root mlflow.db absent at fixed A0 path; mlruns usage unknown; no clearly named MLflow process proves neither absence nor inactivity. | Review repository tracking/artifact URI setup locally first; then propose exact-path metadata and sanitized scheme-only configuration parsing on host. If active tracking DB/artifact root identified, review linkage/completeness and consistent backup separately. No broad filesystem search or artifact-row dump. |
| Models/datasets | Shared pipeline/forecast/anomaly models, Silver/Gold datasets and reports must survive React migration. Prior directory sizes are partial; publication lineage not fully backed up. | Local code/manifest reference inventory first; propose fixed allowlisted manifest metadata/hash checks and directory size metadata only for identified required production artifacts. No model execution, training, pipeline trigger or wholesale home/secret/config reads. |

Do not declare production cutover recovery-ready until required stores and protected configuration are independently inventoried/backed up/restored under their own approvals. A3 covers operational history only; its recovery point is the old immutable A1 timestamp, not current production state, and does not establish an ongoing RPO.

## 8. Local test results and approval boundaries

67 tests passed in3.00s: A3, A2, recovery preparation and recovery tooling tests, including local supervisor exit/timeout behavior. Disposable synthetic SQLite fixture round-trip through fake S3 verifies download/full validation/restoration, not live S3/IAM behavior. Tests cover wrong-account/root refusal, bucket-control failure, conditional overwrite refusal, uploaded checksum/size mismatch, corrupted downloads, receipt-key injection, private exclusive files and pinned A2 hash. First test attempt used system Python without pytest; rerun used existing `venv/bin/python`, no package installation. No real data, AWS or SSH involved. Live IAM policy enforcement, SSE-S3 headers, SFTP, current account/credits and independent recovery remain **unverified**.

Separate authorizations:

1. **A3.1:** first approve only the two read-only identity/bucket-name commands in section3. Follow-up named metadata/access review and exact configuration diff require explicit approval; no implicit mutation.
2. **A3.2:** after A3.1, approve frozen hashes, concrete bucket/operator, exact two-file SFTP transfer, encrypted workstation destination, bounded supervisor and two-object upload. No restoration/cleanup bundled.
3. **A3.3:** after receipt/version IDs exist, approve concrete receipt hash/versions, reader and new workstation restore directory. No SSH, live production access or cleanup bundled.

STOP after preparation. No resource creation, policy change, upload, recovery operation, deployment, Streamlit retirement or Git staging/history write was performed.

## A3.1 approved inventory attempt — 26 October 2026

The owner approved one execution of STS followed by bucket-name inventory only if STS confirmed account `870755688674`, using the existing default profile on the Mac. The exact first command ran once:

```sh
aws sts get-caller-identity --region us-east-1 --no-cli-pager
```

**Exit status: 255.** AWS CLI reported: `Your session has expired. Please reauthenticate using 'aws login'.`

No identity response was returned. Current account ID and identity type therefore remain **unverified**; `870755688674` is the expected account, not a verified result from this attempt. The conditional bucket-name inventory command **was not executed** (exit status: not applicable), in accordance with the stop-on-failure condition. No bucket names were obtained and no likely PowerFlow bucket can be identified from this attempt.

Stopped without retry, additional AWS commands, SSH, configuration inspection/change, upload, restoration or Git staging/history modification. The user must refresh their default-profile login themselves. A new explicit approval is required before rerunning the two-command inventory; subsequent named-bucket configuration inspection remains separately approval-gated. No storage/access configuration or transfer is authorized by this failed attempt.

## A3.1 newly authorized inventory — 26 October 2026

After refreshing the default-profile session, the owner explicitly authorized one new sequential attempt. The exact two approved AWS CLI commands ran once each on the Mac, using the existing default profile:

1. `aws sts get-caller-identity --region us-east-1 --no-cli-pager` — **exit 0**. Account **870755688674**, matching the required account. Identity type **AWS account root** (`arn:aws:iam::870755688674:root`). No authentication error.
2. Only after that account match, `aws s3api list-buckets --query 'Buckets[].Name' --region us-east-1 --no-cli-pager` — **exit 0**. Returned one bucket name: **`powerflow-data-ian-2026-870755688674-us-east-1-an`**. No reported error.

This is the likely existing PowerFlow bucket based on its name and the earlier single-PowerFlow-bucket evidence. Name alone does not verify region, ownership controls, encryption, versioning, access policies, contents or suitability for A3. No named-bucket inspection, IAM inspection, object access, SDK call, SSH, upload, restoration, modification or deployment was performed. Root use was limited to the two expressly authorized read-only inventory calls; it is not approved as a transfer/runtime identity.

Stopped after inventory. Request separate approval for exactly the seven named-bucket metadata commands listed in section 3, substituting only `powerflow-data-ian-2026-870755688674-us-east-1-an` for `APPROVED_BUCKET`. The proposed follow-up covers location, public-access block, versioning, encryption, ownership controls, policy and lifecycle, with expected owner `870755688674`; it does not include object listing/data reads, IAM inspection or modifications. Any policy response must be handled privately as specified there. No subsequent operation is authorized by the successful inventory.

## A3.1 separately approved named-bucket configuration check — 26 October 2026

Executed the seven exact approved S3 CLI operations once each, sequentially in the approved order, using the existing default profile and expected owner `870755688674`, region argument `us-east-1`, bucket `powerflow-data-ian-2026-870755688674-us-east-1-an`. No STS, IAM, object, SSH or additional AWS calls were added. No command was rerun. No bucket policy contents were returned because no bucket policy exists.

| Order / operation | Verified result | Exit status |
|---|---|---|
| 1. get-bucket-location | `LocationConstraint: null`, representing **us-east-1** | 0 |
| 2. get-public-access-block | **BlockPublicAcls=true; IgnorePublicAcls=true; BlockPublicPolicy=true; RestrictPublicBuckets=true** | 0 |
| 3. get-bucket-versioning | **Enabled** | 0 |
| 4. get-bucket-encryption | **AES256 / SSE-S3** default; BucketKeyEnabled=false; configuration additionally reports **SSE-C blocked** | 0 |
| 5. get-bucket-ownership-controls | **BucketOwnerEnforced**, ACLs disabled | 0 |
| 6. get-bucket-policy | **Absent**, `NoSuchBucketPolicy`; expected absence, not permission denial | 254 |
| 7. get-bucket-lifecycle-configuration | **Absent**, `NoSuchLifecycleConfiguration`; expected absence | 254 |

No unexpected errors or ownership/permission failures occurred. Expected absence responses were recorded and execution continued as authorized. The SSE-C blocking setting is an additional observed protection, not a setting changed by this review. SSE-S3 operation does not require a new KMS key; BucketKeyEnabled=false is not a defect for AES256. All unrelated settings must be preserved.

**Suitability assessment:** existing region/encryption/versioning/public-access/ownership settings satisfy the proposed storage checks, so this is a suitable *candidate* without creating another bucket. It is **not yet approved for A3.2**: identity-based access was not inspected; the previously reported pipeline deletion capability is not resolved. With no bucket policy, no bucket-level TLS-only, append-only conditional-write or recovery-prefix deletion protection can be asserted. Block Public Access does not establish least-privilege authenticated access. Versioning is not immutable retention, and absent lifecycle means no automated expiration; retain/manual-cleanup approval boundaries still apply. No object existence or recoverability has been checked.

Private aggregate evidence on the Mac: `/tmp/powerflow-a3-bucket-config-results.json` (0600). No credentials, policy document, object contents or backup data were collected. No AWS setting, production service or Git staging/history was modified.

**STOP / next approval boundary:** propose a narrowly scoped read-only IAM/access review for the existing pipeline role and the intended non-root upload/restore identity, to determine exact effective grants and construct an additive recovery-prefix policy without affecting existing pipeline access. No IAM command is authorized here. The owner must identify/confirm intended non-root identities; then the exact bounded IAM commands/resources must be presented for explicit approval before execution. If preferred, prepare a dedicated-bucket alternative without inspecting IAM, but creation/policies still require separate approval. Do not upload under root or broaden permissions automatically.

## Parallel local readiness preparation — 26 October 2026

See the [consolidated A3 and React readiness report](phase5d2-a3-and-react-readiness.md) for the exact four-command proposed runtime IAM batch, identity/access blockers, bucket-bound transfer/restore commands and shortest safe deployment sequence including the next24 forecast-availability backlog. No new AWS/SSH calls ran. The A3 script now pins the verified bucket and checks the receipt parent before upload; current code/test hashes above supersede the earlier unexecuted proposal. Recovery regression:68passed in2.83s. Existing boto3 service-model support was checked entirely locally. Storage/identity/policy approval, encrypted workstation confirmation, transfer approval and actual receipt/version binding remain gates.

## Final local package and IAM reference completion — 26 October 2026

The two separately authorized policy-list calls each ran once and exited0: inline policies `PowerFlowEC2S3Access` and `PowerFlowReadProductionParameters`; no attached managed policies. Earlier get-role established no permissions boundary and was not repeated. No policy bodies, extra AWS/SSH operations, objects or credentials were inspected in this preparation. The exact next two get-role-policy commands and final execution boundaries are in the [consolidated report](phase5d2-a3-and-react-readiness.md#consolidated-completion--approved-policy-lists-and-final-local-packages).

Current A3 code now **requires** an approved `--expected-role-arn` and validates the caller's STS assumed-role identity/account; no IAM user/root/other role is accepted. This replaces the earlier account/non-root-only gate. Names/ARNs of future uploader/reader roles must still be nominated and approved; placeholders are not executable authorization. The timeout supervisor now sends group KILL after the full five-second grace even if the leader exited, and the receipt-key test actually reaches key validation with a valid bucket. Current code/test hashes in section2 supersede earlier unexecuted proposals. Frozen A2 code is unchanged.

Local validation: **701 Python tests passed in34.67s; 81 frontend tests passed; lint, production build and asset guard passed; pip check found no broken requirements** (a local pip-cache permission warning only). Asset guard:30JS chunks,376,359-byte entry,114,072-byte gzip entry,886,058totalJS bytes; zero source maps/test sources. No live S3 transfer/restore/IAM policy behavior is verified by mocks. No generated build was deployed.

## Inline-policy findings and consolidated execution sequence — 26 October 2026

The separately approved two inline-policy reads each exited0 and matched the requested role/policy names. Full bodies stay private off-repository. `PowerFlowEC2S3Access` grants bucket-level ListBucket/GetBucketLocation without prefix condition and GetObject/GetObjectVersion/PutObject/DeleteObject/DeleteObjectVersion on the entire known bucket object range. Thus the inspected identity grants cover write/delete/version-delete for A3 keys. `PowerFlowReadProductionParameters` grants only one scoped ssm:GetParameter; no parameter values were retrieved. Neither policy has conditions or explicit denies. No attached managed policies or boundary were found previously. These two bodies do not prove all effective account/resource/session permissions.

The [latest consolidated plan](phase5d2-a3-and-react-readiness.md#latest-authorized-inline-policy-inspection--26-october-2026) includes exact upload/restore/SCP commands, new offline policy JSON generator, key-scoped protection changes, non-root identity blockers, costs, rollback and stop rules. The generator neither accesses AWS nor creates roles; actual non-root role/trusted-operator binding must precede mutation approval. Upload/restore remain unauthorized. No repeat inventory is needed solely to re-establish these completed policy reads.

New local code hashes:

| File | SHA-256 |
|---|---|
| deploy/remediation/prepare-a3-access.py | cccf83a6626af732410061d7cfa65146cfab9b5c59a16f038b166879dca060f8 |
| tests/test_a3_access_proposal.py | 7c33a3dfa92ed68bf39aadc7489676bbac6d152921d4e47e1724527b7043fdc3 |
| src/models/next24h_exogenous_evaluation.py | 459fe38016e43878fb34e060b6087c840e95ab3ded05ce215efc1433647fc862 |
| tests/test_next24h_exogenous_evaluation.py | 76de9b48f86c0fc8d97bfb20b52816e2430badbefc462ab81db46f488b3bc8b8 |

The forecasting module is local-only actual-issuance validation and purged horizon evaluation; no real input availability, accuracy or operational promotion is claimed. No existing pipeline/ML/production service path changed.

Final local regression for this update: **724 Python tests passed in33.19s**. No new frontend code changed; earlier81-test/lint/build results are historical, not newly rerun claims. No real forecast/accuracy, IAM mutation, S3 transfer or independent live restoration was tested in this update.

## Autonomous local implementation checkpoint — 26 October 2026

See [local implementation checkpoint](local-implementation-checkpoint.md) for actual code, exact changed-file list,783Python/85frontend regression results, candidate build/package/rehearsal evidence and remaining gates. No AWS/SSH/external network, transfer, live restore or deployment ran in that work. New A3bytes supersede earlier unexecuted proposals: upload now preserves a private exclusive `upload-receipt.json.progress.jsonl` journal in addition to the final receipt; policy preparation produces `approval-metadata.json` in addition to three policy files. Both object entries are validated before any GET, receipts are bounded/private, and reader explicit denies cover current/latest and non-approved versions. Current hashes in the tables above must be reviewed before future execution; no earlier approval authorizes changed payloads. Non-root identity/trust and exact access-application approval remain blockers. Frozen A2hash is unchanged.
