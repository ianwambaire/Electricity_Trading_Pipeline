# Isolated Linux dependency gate — local review updated

Run on a disposable LOCAL Linux x86_64 container/VM, not the production Python environment. No EC2 changes or services. Disposable local verification is authorized by the current request, but no usable local Linux environment is available. EC2 installation remains separately approved work. Required before running: reviewed Linux CPython3.14 image pinned by digest, approved x86_64 wheelhouse with exact file SHA256 manifest matching candidate `api/requirements/api.lock` and `shared.txt`. Neither is currently supplied/verified. No assumed Docker tag or network download is an execution-ready substitute.

After those inputs and local Docker availability are verified, proposed container command (variables require exact approved values):

```sh
docker run --pull=never --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" --platform linux/amd64 \
  --memory 1536m --cpus 1 --pids-limit 128 \
  --tmpfs /tmp:rw,nosuid,nodev,size=768m,mode=1777 \
  --mount type=bind,src=/private/tmp/powerflow-react-stage-review-dudwnuhr/candidate,dst=/candidate,readonly \
  --mount type=bind,src="$APPROVED_WHEELHOUSE",dst=/wheels,readonly \
  --mount type=bind,src="$REVIEWED_RUNTIME_PROBE",dst=/probe.py,readonly \
  "$APPROVED_LINUX_IMAGE_DIGEST" /bin/sh -eu -c '
    export PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
    python -I -S -B -c "import sys; assert sys.version_info[:3] == (3,14,7)"
    cd /wheels
    sha256sum -c SHA256SUMS
    python -I -S -B -m venv /tmp/api-check
    /tmp/api-check/bin/python -m pip install --no-index --only-binary=:all: --no-cache-dir --find-links=/wheels -r /candidate/api/requirements/api.lock
    /tmp/api-check/bin/python -m pip check
    mkdir -p /tmp/probe-root/scripts
    ln -s /candidate/api/src /tmp/probe-root/src
    cp /probe.py /tmp/probe-root/scripts/check_api_runtime.py
    PYTHONPATH=/candidate/api/src /tmp/api-check/bin/python -B /tmp/probe-root/scripts/check_api_runtime.py
    du -sk /tmp/api-check
  '
```

`REVIEWED_RUNTIME_PROBE` is the local `scripts/check_api_runtime.py`, whose hash must be bound in approval. It constructs only synthetic disposable fixtures, blocks imports of Streamlit/Prefect/MLflow/sklearn/joblib/boto3 and checks healthy/not-ready/auth states. It must not be installed in production as a fixture endpoint. The cp/ln and venv writes above are confined to disposable container tmpfs. The command destroys only this newly created container/tmpfs on exit (`--rm`), not host artifacts. Docker may not pull images automatically: pre-provision the pinned image separately and add `--pull=never` in the final bound command.

Use a 300-second external process-group timeout with five-second kill grace in the final verification wrapper; no retries. Capture output privately, return exit/summary only. Stop on missing/incompatible wheels, mismatch/extra files in wheel inventory, import failures or memory exhaustion. No dependency resolver access to the internet, source builds, relaxed pins or shared venv updates. `sha256sum -c` alone does not reject extra wheel files: exact wheel inventory and lock matching must be verified before this command. Linux success is not proof of production systemd/cgroup/BPF enforcement.

## Actual local results

- Immutable release manifest and all68 file digests verified unchanged; see `LINUX-DEPENDENCY-RESULTS.json` for exact26 versions, Requires-Python and installed wheel tags.
- Existing isolated macOS environment: CPython3.14.7; platform `macosx-10.15-universal2`, host Darwin arm64. All26 pins match; pip check passed. Actual immutable candidate imports, numpy/pandas operations, cffi/pydantic-core imports, cryptography hashing and Uvicorn config load passed. No listener or provider calls. Offline lifecycle passed: health200, missing dependency ready503, protected401, absent reports404, deployed docs404; research imports excluded.
- These results are NOT Linux installation evidence. Docker CLI exists and selected context is local Unix socket; that socket is absent and daemon query returned1. No remote Docker endpoint, image pull, container launch, package download or installation was performed.
- All installed package Requires-Python metadata accepts3.14.7. Eleven pins reject system3.9.25; do NOT create the candidate with `/usr/bin/python3`.
- Existing macOS API TEST venv occupies186,620KiB (182.25MiB), including test tools. Linux API-only size is unmeasured. Budget conservatively300MiB venv and1GiB total installation workspace IN ADDITION TO2GiB free reserve; replace estimates with measurements. Do not compile dependencies on the shared EC2.

## Reproducible environment and wheel acquisition gates

Proposed local environment: non-free-threaded CPython3.14.7, Linux x86_64, glibc-based image pinned by OCI digest and verified interpreter/architecture (not just a mutable tag). `python:3.14.7-slim-bookworm` is a proposed discovery reference ONLY; availability and digest have not been verified. Acquire the image/wheels through separately reviewed network access if needed; no fabricated digest. Local Docker Desktop must first be available.

Prefer wheels with glibc baseline <=2.28 and cp314 or compatible abi3 tags (plus pure-Python wheels). Do not use macOS/arm64, musllinux or cp314t wheels. Confirm EC2 libc, base interpreter location and shared-library requirements before claiming compatibility. A Debian test alone does not prove Amazon Linux compatibility.

Proposed download command ONLY after network acquisition is permitted (not executed):

```sh
python -m pip download --only-binary=:all: --no-cache-dir \
  --implementation cp --python-version 3.14 --abi cp314 --abi abi3 --abi none \
  --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 \
  --platform manylinux2014_x86_64 \
  --dest "$NEW_REVIEWED_WHEELHOUSE" \
  -r /private/tmp/powerflow-react-stage-review-dudwnuhr/candidate/api/requirements/api.lock
```

Verify exact distribution/version inventory against all26 pins (including `shared.txt`), reject extras/symlinks/source archives, record every wheel size/SHA256 and total size, then bind that inventory in approval. Stop if any compatible wheel is unavailable; do not silently loosen pins or add source builds. An offline pip resolution and imports must then pass in the pinned Linux container. No Linux wheel availability is currently claimed.

## Separately approvable EC2 environment installation

After successful local Linux verification and publication approval:

1. Inspect exact CPython3.14.7 real executable, base_prefix, stdlib/shared libraries and libc. They must remain accessible under `ProtectHome=true`; a new venv referring into `/home/ec2-user` is NOT acceptable. Do not alter production Python or weaken ProtectHome. If no safe existing base is available, propose a separately reviewed root-owned runtime artifact and hashes first.
2. Transfer only approved wheelhouse/runtime/release into exclusive private incoming paths. Verify exact inventory/SHA256 before writes to the new release. Recheck free disk >= all incoming/unpacked/venv/publication requirements +2GiB. No shared caches/global pip installs.
3. Using the verified existing base (no guessed interpreter path), create ONLY `/opt/powerflow/releases/phase-staging-https-ready-20261026/.venv-api`; use offline binary-only pinned install with `--no-index --find-links=APPROVED_WHEELHOUSE`, no cache. Bounded install window, no automatic retry. Never reuse `.venv-prod`.
4. Run pip check, all26 version assertions, compiled-library imports/primitives and offline candidate import/lifecycle tests. Do not start Uvicorn, unit or account operations. Measure actual venv size and peak filesystem consumption. Preserve private failure artifacts; no automatic cleanup or repair.
5. Make only new release root-owned/nonwritable to service user, recheck interpreter traversability under sandbox, and review effective unit/cgroup/BPF controls in the later separately approved activation window. No systemd/user/Nginx changes are included in this environment-install step.

Host cgroup-v2/root/system.slice interface availability is CONFIRMED by the authorized diagnostic (exit0). Effective candidate384M/512M/zero-swap limits and BPF protection remain UNVERIFIED. No policy or service changes are required to fix the former root-file preflight assumption.
