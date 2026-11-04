# urllib3 metadata inspection — separate local preparation

No remote execution is authorized by this document. V2, V3, their manifests,
SDK lock and failed-attempt evidence remain unchanged. No dependency repair,
installation, acceptance of observed hashes or lock regeneration is implemented.

## Evidence and lock provenance

V3 observed FILE_MISSING at FILE_PARENT for
`urllib3-2.7.0.dist-info/METADATA`, after 178 verified files. This establishes a
missing required path, not the installed urllib3 version or historical cause.

V2's preserved `lock_sdk.py` generated SDK-LOCK.json from a local installation,
using importlib.metadata.distribution('urllib3'), requiring version 2.7.0 and
selecting that distribution's METADATA entry. The frozen entry is 6852 bytes,
SHA-256 `66147856d30bbb6bed01c6ce3326d0f48d84ed5f286ac177633a1486b82eace5`.
That generator is NOT run by this package. The lock assumes both version and
standard dist-info layout. It targets the previously reviewed production venv's
`.venv-prod/lib/python3.14/site-packages` under the fixed application root.
Neither metadata version matching nor this inspection proves executable integrity.

## Exact observation scope

Passively verify the unchanged root-owned OS Python 3.14 binary with V2's bound
runtime check. Never execute Python 3.14, its venv or any SDK/application modules.
Run only trusted system Python with -I -S -B, without site startup hooks.

Anchor the exact site-packages root with V3's retained no-follow descriptor
primitives. Check its metadata, enumerate at most 8192 immediate entry names and
inspect at most eight matching urllib3 distribution directories. No recursion.
The only accepted pattern is `urllib3-<version>.dist-info`, where version has two
to four numeric components (1..4 digits each), optionally a/b/rc prerelease or
.post/.dev numeric suffix. This intentionally bounded subset fails closed on
unrecognized urllib3-prefixed layouts. It does not dynamically approve paths.

Other immediate names are ignored, never opened or output. urllib3- or urllib3.
prefixed unexpected names fail UNEXPECTED_LAYOUT using the fixed
URLLIB3_METADATA sentinel. Matching directories
must be real directories; only their literal METADATA file may be opened.
No RECORD, WHEEL, INSTALLER, Python files, arbitrary contents or child inventory
are read. Missing metadata is reported explicitly. No unrelated tree is scanned.

Use owner 0/1000, no group/world writes and pipeline UID/GID-1000 readability /
traversal requirements unchanged from V3. Do not infer effective runtime access
from those permission checks. O_NOFOLLOW/O_DIRECTORY and Linux O_NOATIME remain;
there is no atime-changing fallback. No recursive chown/chmod or mutation exists.
Recheck pre-open/open/post-read/named identities, directory and site stability.
Reject symlinks and substitutions. No raw exceptions are emitted.

Read at most 65536 bytes per METADATA file, at most eight files. Parse only the
header block, requiring exactly one Name: urllib3 and one Version matching the
syntactically constrained directory version. Never emit descriptions, secret
identifiers, arbitrary fields, file contents, raw paths or observed hashes.
Only approved relative metadata identifiers, constrained versions, fixed layout
and security classifications, expected-directory/file booleans (null when blocked) and runtime
verification are retained. Output is schema-validated locally before storage.
For METADATA_MISSING, the version is only the directory label, not a verified
installed distribution version. A valid header must agree before it is confirmed.

Diagnostic PASS means observation completed, including a MISSING, INCOMPLETE,
DIFFERENT_VERSION, MULTIPLE or HASH_MISMATCH result; it never means an alternative
SDK was approved. EXPECTED requires exact original metadata size/hash, but still
is not full SDK integrity verification. Security/read bounds/parse failures BLOCK.
A missing distribution directory cannot prove all urllib3 code is absent: code
and package imports are outside scope. Multiple metadata directories are ambiguous.

## Immutable closure and transport

The new manifest binds the full unchanged V3 artifact closure and V3 manifest
`0e4b9f45318804cb3d94ac193c09bbcc3a1e042d37400b7ba4a1246b9c8172b5`, including
V2 and unchanged SDK lock, plus the new runner/inspector/builder/review/test.
Only selected V3 filesystem primitives, V2 runtime primitives, unchanged lock
and new inspector are assembled remotely from retained verified source bytes.
No V2/V3 SDK dispatcher or provider is assembled. No AWS, IMDSv2, ENTSO-E, HTTP,
credential/configuration, database, inference, publication or service path exists.
The local runner reuses the pinned SSH/profile verification and bounded supervisor.

One attempt only, no polling/retries: remote 60 seconds, local 90 seconds,
five-second escalation and 16 KiB stream caps. Fixed remote command:

```
sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -
```

Strict host-key checking, pinned identity, public-key/noninteractive restrictions,
no agent/forwarding/ambient config/multiplexing remain unchanged. No arbitrary
remote command, version, path or URL arguments. Sanitized evidence is stored only
locally under the ignored private preflight root, urllib3-metadata-* directory
0700 and assessment.json 0600. Raw stdout/stderr are never retained. Ordinary SSH
access logging may occur remotely.

## Offline verification and limits

Tests use real temporary files with simulated Linux owner IDs. Cover matching and
different versions, missing directory/file, multiple layouts, malformed metadata,
links/substitutions, ownership/permissions, bounds, unknown-entry redaction, no
mutating calls/imports/network and immutable closure. Actual Linux NOATIME,
filesystem race conditions and host metadata remain unverified without a separately
authorized execution. No remote call or SDK lock generator is run locally.

Local validation: 35 focused cases and 201 total selected tests passed. Local
integrity/profile checks passed with Python 3.9.6 and 3.14.7. Assembly uses retained
source segments for stable hashes across Python versions. The assembled definitions
also load under Python 3.9 with only the remote main entrypoint suppressed.

Future command requires NEW separate authorization:

```
venv/bin/python -I -B deploy/staging/forecast-publication/urllib3-metadata-inspection/run.py --manifest-sha256 <NEW_MANIFEST_SHA256>
```

`--local-check` verifies bindings/profile without SSH. No publication/deployment
transaction is created or reused. No setup or repair is authorized by this review.
