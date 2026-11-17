# Independent urllib3 2.8.0 compatibility reference

LOCAL PREPARATION ONLY. This is not an executable remote inspection, deployment,
installation or publication package. It authorizes no remote action and replaces
no original SDK lock, inspector, adapter, production dependency or evidence.

## Versions and declared compatibility

The original immutable V2 baseline binds boto3 1.43.98, botocore 1.43.98,
s3transfer 0.19.2, jmespath 1.1.0, python-dateutil 2.9.0.post0, six 1.17.0 and
urllib3 2.7.0. Existing 178 successful host file checks do not establish complete
remote SDK integrity. Remote urllib3 2.8.0 metadata is not trusted reference code.

Exact original metadata, checked against V2 hashes locally, declares:

- boto3: botocore >=1.43.98,<1.44.0; jmespath >=0.7.1,<2.0.0;
  s3transfer >=0.19.0,<0.20.0. Python >=3.10.
- botocore: urllib3 >=1.25.4,<3,!=2.2.0; jmespath >=0.7.1,<2.0.0;
  python-dateutil >=2.1,<3.0.0. Python >=3.10.
- urllib3 2.8.0: Python >=3.10; explicitly classifies Python 3.14. All declared
  external dependencies are optional extras. No extras are enabled here.

urllib3 2.8.0 satisfies these declared constraints. That is a necessary condition,
not a substitute for testing. Python 3.9 is bootstrap-only: it must not import this
SDK. Actual SDK protocol tests use local Python 3.14.7 with -I -S -B, held verified
source bytes and no site hooks. Linux remote runtime identity is still unverified
against this candidate baseline; previously approved runtime restrictions remain.

## Independent reference and provenance

Reference wheel downloaded from the official PyPI release's files.pythonhosted.org
URL, separately from EC2, using macOS system TLS with certificate verification,
no redirects and bounded transfers. The local Python TLS store could not validate
the issuer; no trust settings were changed or verification disabled.

- https://pypi.org/project/urllib3/2.8.0/
- https://pypi.org/pypi/urllib3/2.8.0/json
- Wheel: urllib3-2.8.0-py3-none-any.whl; exactly 135717 bytes.
- SHA-256: 0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3
- Provenance: https://pypi.org/integrity/urllib3/2.8.0/urllib3-2.8.0-py3-none-any.whl/provenance
- PyPI identifies GitHub publisher urllib3/urllib3, environment publish,
  workflow publish.yml. Its published release page names commit
  b1d30ab61fe0db8f11092805e8c5ac43e091064a.

The wheel hash is compared to both the PyPI release API and release page.
The checked-in PyPI provenance assertion's subject also matches that hash.
This is trust in PyPI's TLS-delivered, PyPI-verified publisher assertion; this
work does NOT independently verify Sigstore signatures or transparency proofs.
The full assertion is retained for an independent reviewer. No live AWS call is
needed to reproduce any reference or compatibility check.

The small public wheel (including its MIT license) is kept as a reproducible
reference artifact, not installed into PowerFlow or vendored as a remote SDK tree.
reference.py verifies its pinned whole-archive hash BEFORE parsing ZIP, rejects
unsafe/duplicate archive paths, links and excessive sizes, validates every RECORD
hash/size and verifies Name/Version/Python metadata. Extraction is into a fresh
in-memory byte mapping only; no site-packages, production directory or interpreter
configuration is changed. Reference identity is not learned from remote metadata.

## New candidate baseline and unchanged closure

The new SDK-LOCK.json is separate. Only 36 urllib3 Python file records and its
one distribution METADATA record are replaced from the verified wheel. The Python
file-name inventory is unchanged. Versions.urllib3 becomes 2.8.0. The remaining
178 records are carried forward byte-for-byte from V2's immutable lock:
`da19f5a81c7741d19333e7bfcc25004c50fe2c83e31642c9f39c828518de35c4`.

No EC2 bytes or hashes are used. Local non-urllib3 source/model/metadata bytes must
match that prior approved baseline before they can participate in tests. The new
candidate still has 215 approved files: 194 Python files, seven METADATA files and
14 bounded botocore JSON assets. The exact transitive default dependencies are
checked with their declared markers and Python 3.14 version constraints. Optional
native/CRT/extra dependencies remain denied by the unchanged MemorySDK loader.

This candidate does not authorize accepting writable code, extra files, native
extensions, links, ownership/mode drift or arbitrary imports. Existing owner 0/1000,
non-group/world-write, pipeline UID/GID-1000 read/traverse, no-follow capture,
file/aggregate bounds and permanent privilege-drop rules remain unchanged in V2.
They are not rewritten or bypassed by this local baseline. Effective Linux access,
NOATIME and actual host file hashes still require guarded remote verification.

## Adapter compatibility checks

No adapter or production secret-provider source changes. Tests reuse the established
V2 SMOKE protocol harness, substituting only independently verified urllib3 bytes.
The loader executes all SDK imports from held bytes and forbids unbound third-party
modules. Socket connect and DNS resolution are replaced with unconditional failures.
IMDSv2 and AWS responses are fixtures at the HTTP transport boundary.

The exercised APIs include urllib3.connectionpool.HTTPConnectionPool.urlopen,
urllib3.response.HTTPResponse construction/streaming and botocore's URLLib3Session
and AWSResponse integration. The source baseline is newer; compatibility is shown
for these exact bounded adapter operations, not asserted for every urllib3 API.

Both SSM GetParameter (WithDecryption=True) and Secrets Manager GetSecretValue
serialization/signing run through the real unchanged SDK. Tests cover binary
secrets, access failures, empty responses, IMDSv1 rejection, redirect rejection,
TLS verify/CA configuration, header/body bounds, arbitrary hosts/methods/mutation
operations/identifiers, duplicate identifiers, secret redaction, one-call limits
and zero real network calls. Existing tests protect no credential fallback,
unwrapped/no-cache production secret reads and UID/GID/capability boundaries.
The short-lived subprocess exits with fixture credentials only in memory.

The TLS checks test that verification remains configured, not a real server's TLS
handshake. No actual IMDS/AWS/ENTSO-E permission or connectivity is proven. No
network request is made during tests. The only external requests in preparation
are public PyPI metadata, wheel and provenance retrieval.

## Reproduce offline and next boundary

```
venv/bin/python -I -B deploy/staging/forecast-publication/sdk-baseline-urllib3-2.8.0/build.py
venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_urllib3_280_compatibility.py tests/test_load_source_aws_adapter.py
```

build.py only writes this new directory's baseline and manifest. It neither runs
V2's lock generator nor installs anything. The manifest binds the wheel/provenance,
reference/builder/review/tests, original SDK lock, adapter and production provider.
The original V2 manifest hash also gates adapter, provider and protocol-harness
bytes before tests or reference assembly. They cannot be silently substituted.

Local validation: 21 focused compatibility cases and 222 selected total tests
passed on Python 3.14.7. The added subprocess audit rejects file writes and
network/process side effects and asserts no attempts, including rejected attempts.
Python 3.9 grammar/bootstrap and deterministic baseline assembly are checked
separately; Python 3.9 does not execute third-party SDK code.

No additional metadata-only host investigation is indicated by the known version
mismatch. Before credentials or source access, a separately versioned executable
source-check package must explicitly bind this candidate and reverify the ENTIRE
installed SDK closure, unchanged privilege boundary/runtime and pinned SSH identity.
A future guarded source check can include that gate; do not run the old V2 with a
changed lock or treat this local compatibility result as remote executable integrity.
No remote command or authorization is provided by this reference package.
