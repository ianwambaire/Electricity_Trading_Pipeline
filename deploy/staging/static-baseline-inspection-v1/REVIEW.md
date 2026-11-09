# Static baseline observation v1 — PREPARATION ONLY

No SSH or other remote action is authorized by this package's preparation.
Use only after separate authorization for exactly one observation. No apply,
rollback, repair, manifest refresh or host-baseline adoption is implemented.

The unchanged operational manifest 873619a9cd73d5fc676058facc1ed5daf1dc1030efbc4572b42c34653a4bf7d9
expects 62 files: all 37 static entries from release phase-api-body-bound-20261102-v2,
plus 25 distinct hashed assets from phase-forecast-consistency-20261101-v1.
The original deployment instead retained assets from its actual prior active static
tree. Its pinned predecessor path hash is NOT the forecast-consistency-v1 path
hash. Using that archive as the retained-host inventory is unsupported. This is a
confirmed expected-inventory construction defect; the exact host differences are
not persisted in the blocked preflight output and remain unobserved.

The diagnostic opens ONLY /var/www/powerflow-staging/releases/phase-api-body-bound-20261102-v2,
its fixed current pointer, and the approved original transaction's state.json at
/var/lib/powerflow-staging/forecast-consistency-transactions/f2f195174eda43daa8e5593087fbe1d3/state.json.
Only ancestry metadata is inspected outside those paths. The transaction record
is local persisted historical evidence, not an independently signed release manifest.
It is checked for exact transaction, completed phase, destination, pinned predecessor
hash and internally consistent retained assets; no paths from it are traversed.
Only derived counts/hashes/differences are reported, never the raw record or paths.
Missing/unverified transaction metadata is explicit rather than inferred.

Output compares host inventory against BOTH the unchanged operational expectation
and the original 37-file approved release, then separately compares it against
original approved files plus the transaction-recorded retained assets. Reports
missing/unexpected/hash mismatches with release-relative identifiers and hashes.
PASS means observation completed, NOT that integrity passed or host state is approved.

Root Linux + O_NOATIME are required. All ancestry is opened with directory FDs,
O_NOFOLLOW and O_NOATIME; directory scans and file reads use those descriptors.
Root ownership, non-writable-by-group/other modes, regular files, no symlinks,
160 files, 32 directories, depth 4, 2 MB/file, total <8 MiB and output <=128 KiB
are enforced. File/directory consistency and fixed pointer stability are checked.
No SDK/application imports, subprocesses, network, filesystem writes or runtime
execution occur in the remote payload. No services, databases or credentials read.

The runner reuses the original hash-verified pinned SSH profile and bounded
supervisor. The exact fixed remote command is:
sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -
One connection, no retry, 60 seconds remote/90 seconds local, five-second escalation.
Sudo only supplies the already-reviewed read-only metadata privileges. Private
local captures are root-user-private via umask077 under the existing Git-ignored
preflight capture directory. No secret or unrestricted raw remote output is requested.

run.py --local-check verifies bindings/reassembles payload/validates pinned local
profile and NEVER invokes SSH. No browser, AWS, source or remote test is performed
by offline tests. Native fixture tests simulate Linux ownership only; actual Linux
root/O_NOATIME and read permissions remain runtime gates. Original releases,
manifests, expected SDK/static hashes and failed-attempt evidence are unchanged.

Future separately authorized command:
venv/bin/python -I -B deploy/staging/static-baseline-inspection-v1/run.py --manifest-sha256 <manifest SHA-256>
