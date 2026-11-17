# Shortest safe staging path — 26 October 2026

**Preparation only. No AWS/SSH/production command, deployment, backup transfer, credential creation or Git operation ran. Existing frontend assets were not rebuilt or modified.**

## A3 change authorization package

Review [A3 access package](../../deploy/remediation/a3-access-package/REVIEW.md) and its [hash manifest](../../deploy/remediation/a3-access-package/SHA256SUMS.json). It contains exact preflight, creation, policy-configuration and readback commands plus proposed trust/operator/uploader/reader JSON. These are **proposed new identities**, not discovered resources:

- `arn:aws:iam::870755688674:user/PowerFlowA3Operator`: human IAM login/MFA, no direct S3, only AssumeRole to the next two roles.
- `arn:aws:iam::870755688674:role/PowerFlowA3Uploader`: TLS/create-only AES256 upload and version verification on the two fixed A1keys.
- `arn:aws:iam::870755688674:role/PowerFlowA3Reader`: separate recovery role, exact-version reads only after approved VersionIds; no latest/current or other versions.

Trust is only the new operator user with recent MFA, never root or EC2. Administrative bootstrap is a separately approved owner IAM-admin operation; the last verified default was root. No unknown non-root administrator is claimed. Owner-controlled console password/MFA setup for **the new IAM user only** is included as a manual proposed step; no password, seed, token, access key or login profile is created by the prepared code. No existing Cognito accounts/groups/MFA/clients change.

New `run-a3-session.py` obtains900second role credentials in memory using the designated source profile and locally entered AWS MFA code, pins the A3payload hash, requires owner-controlled interactive Terminal input before any provider use, suppresses SDK debug logging, and rejects root/EC2/other source users. Existing A3client rechecks its assumed role. It writes/prints no temporary credentials. Installed CLI browser-login/provider compatibility for this newly proposed IAM user is **not live verified**; a failed source login/authorization must stop, not trigger access-key creation or new unapproved Sign-In permissions. This operational acceptance gate cannot be closed by mocks.

Bucket denies cover only the fixed database and manifest keys: EC2overwrite/read denied; DeleteObject/DeleteObjectVersion denied for all principals; conditional encrypted PUT limited to uploader. Unrelated pipeline access stays unchanged. IAM/bucket administrators can change/remove policies or trust: no account-compromise/immutable-retention guarantee. New identities must be absent before creation; unexpected existing user/role/policy stops the batch. Errors, account/hash/JSON/owner mismatch or changed current policy stop without retries/repair/cleanup. Exact rollback/session-expiration considerations are in the package. No upload/restore is bundled into bootstrap approval.

## One subsequent read-only inspection authorization

Review [infrastructure inspection batch](../../deploy/preflight/INSPECTION-BATCH.md) and [hashes](../../deploy/preflight/INSPECTION-SHA256.json). One bounded authorization covers: one account check; one strict SSH-stdin execution of `inspect-production-readonly.py`; projected callback/logout/OAuth reads for the two existing Cognito clients. It uses existing key/ec2-user/verified host, no sudo, no raw config/secrets/logs/env/argv output, no object/data reads or process change.

Payload emits allowlisted Nginx observations, selected service metadata,8000/8010/8501listener ownership, memory/disk counters, fixed public-cert metadata, named renewal timer/cron reference evidence and four loopback health/readiness statuses. It does not validate loaded Nginx syntax/includes, run renewal, read private keys or claim peak headroom. Failures/unknown evidence do not authorize searches, elevation or fixes. The batch's full command list and resource/time/path bounds are fixed in its review; do not execute it before separate approval.

## Existing candidate with next24 unavailable

The **same66-file,1,267,808-byte** candidate passed read-only package/hash verification and strict asset checks. Manifest SHA256:

`64070c74a36d26fa7f8e5d8e03786b1d093846663e46e3f8538f2893176d4add`

Local rehearsal used its unchanged static bytes, synthetic persisted backend data, next24HTTP404 and pipeline `forecast_status=WITHHELD`. All seven route/callback fallbacks, other relevant public APIs and seven Analyst403s passed. Frontend85tests include actual route rendering, unavailable/error/withheld/session behavior. This is local contract/DOM evidence, **not new real-browser/live JWT/Cognito/Nginx proof**. No synthetic predictions were made live and no real accuracy claim follows.

The candidate inventory/guards exclude env/credential/key files, databases/datasets/private recovery material, tests/node_modules and maps. No development callback origins or fixture markers were found. This is allowlist/pattern/provenance evidence, not an exhaustive proof that arbitrary source text can never contain a secret. The packaged existing SPA client ID is public configuration, not a credential; its suitability for staging remains unapproved/unverified.

**Forecast withholding is not a technical blocker for staging:** the UI can honestly show unavailable/withheld while the other pages remain functional. Owner acceptance must explicitly retain that limitation. **Live staging is still blocked**, because this artifact is bound to `https://powerflowenergy.dev`; it cannot be authenticated unchanged at a different staging origin. Approve the actual staging origin/client/callbacks first, then build exactly once with those bindings. Do not rebuild before that decision or repoint production merely to reuse these bytes.

Other genuine gates: completed A3upload/independent restore; required data/configuration recovery coverage; approved root-volume/security decision; TLS renewal and installed Linux/Nginx/systemd/runtime/isolation; measured overlap capacity on the2GiBhost. No second permanent EC2is assumed. Streamlit and port8000remain untouched; candidate API uses8010.

## Validation and changed files

- Focused recovery/access/identity/inspection/smoke/package tests: **92passed in0.76s**.
- Frontend: **85passed**, no rebuild.
- Existing candidate package verification and strict artifact guard: passed.
- Existing-candidate withheld rehearsal: passed; synthetic/in-process only.
- Full Python regression: **794passed in33.08s** (previous checkpoint783).

Created:

- `deploy/remediation/a3-access-package/REVIEW.md`
- `deploy/remediation/a3-access-package/SHA256SUMS.json`
- `deploy/remediation/a3-access-package/bucket-policy.json`
- `deploy/remediation/a3-access-package/uploader-policy.json`
- `deploy/remediation/a3-access-package/reader-policy.json`
- `deploy/remediation/a3-access-package/mfa-operator-trust.json`
- `deploy/remediation/a3-access-package/operator-policy.json`
- `deploy/remediation/run-a3-session.py`
- `deploy/preflight/inspect-production-readonly.py`
- `deploy/preflight/INSPECTION-BATCH.md`
- `deploy/preflight/INSPECTION-SHA256.json`
- `tests/test_a3_identity_package.py`
- `tests/test_readonly_inspection_package.py`
- This report.

Modified:

- `deploy/remediation/a3-offhost-recovery.py` — accepts an injected in-memory session; all role/storage guards retained.
- `scripts/smoke_web_release.py` — explicit unavailable/WITHHELD synthetic scenario using unchanged candidate bytes.
- `tests/test_release_http_smoke.py` — unavailable forecast regression.

**Next authorization:** owner review/approval of the hash-bound A3bootstrap package, including acceptance of new identity names, administrator binding and manual new-operator login/MFA setup. No existing-user discovery or repeated IAMinventory is necessary simply to propose these new identities. Source provider compatibility, successful protected upload and actual-version restore remain separately verified stages; stop before any cloud changes now.
