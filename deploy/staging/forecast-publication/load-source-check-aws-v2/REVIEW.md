# AWS-backed fixed load-source check v2 — authorization review

LOCAL PREPARATION ONLY. No SSH, AWS, IMDS or ENTSO-E request is run by build or
local-check. This is a NEW immutable package. The approved v1 remote manifest
`d4fec87a1eab63c1671b1d6820db10aca0ee7618633b079dad6fc91eaf089065`, its source,
all failed-attempt evidence and every deployment/publication package are preserved.

## Provider selection and identity

The production `src/powerflow_secrets.py` source is unchanged. Its explicit
POWERFLOW_SECRETS_BACKEND selects env/ssm/secretsmanager, defaulting to env only
when configuration is absent. The last remote evidence establishes an AWS backend
but does not distinguish SSM from Secrets Manager. Local source cannot establish
the current EC2 choice. V2 accepts only the configured ssm or secretsmanager choice;
env/unknown/ambiguous or unsupported routing fails closed without a fallback token.

Region precedence is AWS_REGION, AWS_DEFAULT_REGION, then the provider's existing
us-east-1 default. This package permits only us-east-1. Resource selection preserves
the provider's exact POWERFLOW_SECRET_ID_ENTSOE_API_KEY override or prefix/name
construction. Neither identifier nor its hash enters evidence. Names/ARNs must be
bounded and syntactically valid; ARN region must match the approved region. Existing
SSM label/version selectors are passed unchanged. Resource identifiers are opaque
AWS JSON values, never local filesystem paths.

Effective configuration still comes from the verified running worker environment,
the fixed Prefect deployment's job_variables.env and shared .env with the original
dotenv interpolation/override=False semantics. Only the old adapter's explicit
env-only guard is removed by a checked AST/source extraction. The capture helper
also permits the fixed SDK-only owner pair (0,1000), avoiding a separate pathname
stat before its anchored no-follow read. SDK files must also be readable by UID/GID
1000 without supplementary groups, and SDK directories readable/traversable.
All scalar owner checks remain exact;
all other selected helpers, source hashes, no-follow captures, permissions and drift
checks are retained. No production application code is imported or executed. Raw process
environment and .env remain private in process memory; no raw captures are saved.

Root performs passive source/runtime/SDK-file verification only. Before any SDK
import, AWS credential resolution or source request, the existing helper permanently
sets real/effective/saved UID/GID to 1000 and clears supplementary groups. SDK child
entry verifies that identity, empty groups and zero effective/permitted/ambient
capabilities before importing third-party code. Parent and child disable core dumps.
No sudo rule, service identity, API sandbox, cgroup/BPF control or IAM policy changes.

## Installed dependencies, not vendored SDK code

requirements-prod.txt pins Boto3 1.43.98. SDK-LOCK.json records the exact locally
installed Boto3 1.43.98, Botocore 1.43.98, S3Transfer 0.19.2, JMESPath 1.1.0,
python-dateutil 2.9.0.post0, urllib3 2.7.0 and six 1.17.0 file baseline. It contains
only paths, sizes, versions and hashes, not SDK sources or models. The index binds
215 files / 4,362,847 bytes: all 194 Python files in these namespaces, seven package
METADATA files and fourteen Botocore data files limited to global endpoint/retry
configuration and SSM/Secrets Manager models. No arbitrary service model is loaded.
Version matching alone is never accepted as executable integrity.

The remote adapter must find exact matching files under the existing production
`.venv-prod/lib/python3.14/site-packages`. Availability and matching bytes have NOT
been observed remotely in this task. Wrong/missing files, added code, symlinks,
native extensions inside these namespaces, unsafe ownership/modes or excessive
inventory/bytes fail closed before credentials or ENTSO-E access. Owners may be
root or pipeline UID 1000; no group/world write is allowed. Ancestors and inventory
walks use no-follow descriptors. Python caches are ignored because they never run.

All SDK bytes and selected model data are captured and hashed while root, then
held in memory. The unprivileged child rechecks the entire held envelope's exact
inventory, sizes and hashes before import. MemorySDK compiles only those held
Python bytes and serves model JSON from held data with bounded decompression.
Unknown non-stdlib imports are rejected rather than searched on disk.
There is no sys.path insertion or import from the writable production checkout,
site hooks, .pth, pyc, disk model search or credential_process. Verified six's
synthetic six.moves aliases are allowed; optional CRT, Certifi, PyOpenSSL, Brotli
and Zstandard extensions are disabled. The real SDK's pure-Python signing path is
tested offline. SDK code/data is never reopened after verification.

SDK versions require Python >=3.10. The bootstrap and supervisor support Python
3.9; actual SDK execution uses the already reviewed root-controlled OS
`/usr/bin/python3.14 -I -S -B -c <verified code>`, not the production venv interpreter.
Its expected SHA-256 is
`ac1b8b9815ac3935d6708cbe8223458a19d9dee438ebe18e88378d61712da8d6`, recorded
in retained passive preflight evidence. Fresh hash, root ownership, non-symlink
ancestry, non-writable metadata and absence of set-ID bits must pass; inode/metadata
is rechecked after dropping root. Child requires Python 3.14. The OS interpreter,
stdlib and root-controlled OS CA trust store are trusted host dependencies, not
falsely represented as vendored SDK closure. Root administrator changes are outside
the UID-1000 TOCTOU threat boundary. Any observed mismatch blocks execution.

## Narrow SDK authentication and operations

The unchanged provider function body is executed in an isolated namespace using
a restricted Boto3 facade backed by the verified real SDK. Only its eager boto3
import is removed; that name is supplied by the facade. Its optional lru_cache is
bypassed with __wrapped__ for this one-shot diagnostic, with no production change.
Retrieved ENTSO-E secrets are neither cached nor written. Transient request/pipe
buffers necessarily hold values until process exit; secure memory zeroization is
not claimed.

The SDK uses only InstanceMetadataProvider and checks credentials.method=iam-role,
the same credential source production accepts. Environment/static credentials,
profiles, shared credential/config files, web identity, container credentials,
credential_process and assume-role providers cannot run. Configured alternate
routes, custom metadata/API endpoints and CA overrides are rejected. The child
receives no environment token. Its SDK config files are /dev/null, proxies are
empty, CRT is disabled and no production environment is inherited implicitly.

Allowed metadata protocol is only IMDSv2 on 169.254.169.254:

- PUT /latest/api/token, once, to obtain the SDK's normal IMDSv2 session token.
- GET /latest/meta-data/iam/security-credentials/, once.
- GET the returned bounded role-name path under that same prefix, once.

No IMDSv1 fallback, retry, instance identity document or other metadata path is
permitted. The token PUT is the standard instance authentication protocol, not an
AWS resource modification. Role metadata and credentials never enter evidence.

Exactly one configured AWS secret read is permitted:

- SSM: `get_parameter(Name=<configured identifier>, WithDecryption=True)`.
- Secrets Manager: `get_secret_value(SecretId=<configured identifier>)`, preserving
  both SecretString and SecretBinary decoding in the original provider.

Both are AWS read operations serialized as HTTPS POST; method POST alone does
not imply a resource write. The transport independently checks exact endpoint,
HTTP method, X-Amz-Target, JSON keys/values and one-request budget. No PutParameter,
ListSecrets, STS, IAM, resource mutation or unapproved AWS call can pass it.

Only `https://ssm.us-east-1.amazonaws.com/` or
`https://secretsmanager.us-east-1.amazonaws.com/` is permitted, selected by backend.
Signature v4, verified OS CA, no proxies, no FIPS/dualstack/custom endpoint and no
redirects. Redirect following is explicitly disabled in the pool before send.
Connect/read timeouts are 3/5 seconds and total_max_attempts=1. IMDS has a 2-second
timeout and one attempt per step. AWS/metadata bodies are capped at 128 KiB before
SDK JSON parsing, including chunked responses. SDK logging is disabled; exceptions
are converted to fixed codes, never server messages, ARNs or protected URLs.

Required existing permissions: ssm:GetParameter on the configured parameter OR
secretsmanager:GetSecretValue on the configured secret, plus kms:Decrypt where its
customer-managed key requires it. No policy query, IAM change or broader permission
is attempted. AccessDenied/not found/decryption errors block source access; no
fallback is attempted.

## Process, request and output bounds

The unprivileged SDK child receives only bound SDK bytes and selected provider
configuration via an anonymous stdin pipe. Its returned secret uses an internal
bounded stdout pipe, never SSH stdout or saved evidence. Identifiers/values are
not argv fields. Parent rejects malformed or unexpected child output and discards
stderr; the child never emits a traceback. A fixed verified-code -c argument is
under 100 KiB; the bounded input envelope is under 8 MB; each child output stream
is limited to 64 KiB. This child is supervised for 20 seconds with five-second
termination escalation. It shares the outer remote timeout's process group and
cannot escape that timeout through a new session. No child command is configurable.

After a successful secret lookup only, the UNCHANGED reviewed comparison core
makes at most one authenticated TLS GET for A65/A16, DE_LU, periodStart=202611031500,
periodEnd=202611031600, at the configured approved ENTSO-E origin. All original
2 MB response, timeout, resolution, timestamp, A01/A03, no-redirect and sanitized
comparison rules remain intact. No ingestion, CSV/database write or publication.
The captured load snapshot is rechecked after the source request. Source availability
now cannot establish availability at the original withholding time or ingestion blame.

Manifest/runner/payload/closure verification occurs before SSH. All supervisor,
SSH helper, payload and output-validation code executes from retained verified
bytes. Original pinned SSH identity/known-host checks and one-attempt restrictions
remain unchanged. Exact outer command:

```
sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -
```

Remote deadline 60 seconds, local deadline 90 seconds, five-second escalation,
one attempt, no retries/polling, each SSH stream capped at 16 KiB. The original
private ignored evidence convention is reused as `preflight/load-source-aws-v2-*/`
with directory 0700/file 0600. Only strict-schema sanitized results are persisted.
New fields identify backend, whether iam-role was positively verified and whether
the source request was NOT_ATTEMPTED/ATTEMPTED/COMPLETED. Unknown errors never echo
protected values. A PASS means comparison completed, not that the quarters exist
or that a current forecast is eligible.

## Validation and authorization

Offline tests mock AWS/IMDS HTTP responses, forbid real sockets, exercise the real
verified SDK/model loader and signing stack, test both backends, original provider
semantics, no cache/fallback, errors, role identity, TLS/redirect/method/target guards,
body limits, SDK/runtime incompatibility, privilege ordering, payload closure and
report redaction. Linux procfs, UID changes, effective IAM permissions, installed
SDK byte matches and live source availability remain runtime prerequisites.

Validation: 140 selected tests passed (AWS adapter, existing source adapter/core and
production secret-provider tests). Both Python 3.9.6 and 3.14 verify identical
payload bytes. The held bootstrap imports and both backend selectors execute
offline on 3.9.6 without importing SDK packages. Python 3.9 syntax and whitespace
checks pass. The SDK itself is not claimed to support Python 3.9; the sixteen
actual SDK protocol scenarios execute on Python 3.14 with mocked IMDS/AWS HTTP and
real sockets forbidden. No real credentials, AWS calls, SSH or ENTSO-E calls occur.
Installed-host SDK/runtime/CA/permission checks and live IAM access remain unverified.

Future command, requiring NEW explicit one-attempt authorization:

```
venv/bin/python -I -B deploy/staging/forecast-publication/load-source-check-aws-v2/run.py --manifest-sha256 <NEW_MANIFEST_SHA256>
```

`--local-check` verifies locally and cannot connect. Authorization must explicitly
include approved installed SDK/runtime reads, IMDSv2 role resolution, one selected
AWS secret read and at most one fixed ENTSO-E request. Previous authorizations are
consumed and do not cover this changed package. No deployment, privilege/policy
change, manual forecasting/publication, service action or Git operation is included.
