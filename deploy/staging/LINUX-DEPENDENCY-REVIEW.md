# Isolated Linux dependency gate — local review updated

Run on a disposable LOCAL Linux x86_64 container/VM, not the production Python environment. No EC2 changes or services. Disposable local verification is authorized by the current request, but the local Linux engine is now available but image acquisition is blocked by registry DNS resolution. EC2 installation remains separately approved work. Required before running: reviewed Linux CPython3.14 image pinned by digest, approved x86_64 wheelhouse with exact file SHA256 manifest matching candidate `api/requirements/api.lock` and `shared.txt`. Neither is currently supplied/verified. No assumed Docker tag or network download is an execution-ready substitute.

After those inputs and local Docker availability are verified, proposed container command (variables require exact approved values):

```sh
docker run --pull=never --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" --platform linux/amd64 \
  --memory 1536m --cpus 1 --pids-limit 128 \
  --tmpfs /tmp:rw,nosuid,nodev,size=768m,mode=1777 \
  --mount type=bind,src=/private/tmp/powerflow-react-stage-review-dudwnuhr/candidate/api,dst=/candidate,readonly \
  --mount type=bind,src="$APPROVED_WHEELHOUSE",dst=/wheels,readonly \
  --mount type=bind,src="$REVIEWED_RUNTIME_PROBE",dst=/probe.py,readonly \
  "$APPROVED_LINUX_IMAGE_DIGEST" /bin/sh -eu -c '
    export PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
    python -I -S -B -c "import sys; assert sys.version_info[:3] == (3,14,7)"
    cd /wheels
    sha256sum -c SHA256SUMS
    python -I -S -B -m venv /tmp/api-check
    /tmp/api-check/bin/python -m pip install --no-index --only-binary=:all: --no-cache-dir --find-links=/wheels -r /candidate/requirements/api.lock
    /tmp/api-check/bin/python -m pip check
    mkdir -p /tmp/probe-root/scripts
    ln -s /candidate/src /tmp/probe-root/src
    cp /probe.py /tmp/probe-root/scripts/check_api_runtime.py
    PYTHONPATH=/candidate/src /tmp/api-check/bin/python -B /tmp/probe-root/scripts/check_api_runtime.py
    du -sk /tmp/api-check
  '
```

`REVIEWED_RUNTIME_PROBE` is the local `scripts/check_api_runtime.py`, whose hash must be bound in approval. It constructs only synthetic disposable fixtures, blocks imports of Streamlit/Prefect/MLflow/sklearn/joblib/boto3 and checks healthy/not-ready/auth states. It must not be installed in production as a fixture endpoint. The cp/ln and venv writes above are confined to disposable container tmpfs. The command destroys only this newly created container/tmpfs on exit (`--rm`), not host artifacts. Docker may not pull images automatically: pre-provision the pinned image separately and add `--pull=never` in the final bound command.

Use a 300-second external process-group timeout with five-second kill grace in the final verification wrapper; no retries. Capture output privately, return exit/summary only. Stop on missing/incompatible wheels, mismatch/extra files in wheel inventory, import failures or memory exhaustion. No dependency resolver access to the internet, source builds, relaxed pins or shared venv updates. `sha256sum -c` alone does not reject extra wheel files: exact wheel inventory and lock matching must be verified before this command. Linux success is not proof of production systemd/cgroup/BPF enforcement.

## Actual local results

- Immutable release manifest and all68 file digests verified unchanged; see `LINUX-DEPENDENCY-RESULTS.json` for exact26 versions, Requires-Python and installed wheel tags.
- Existing isolated macOS environment: CPython3.14.7; platform `macosx-10.15-universal2`, host Darwin arm64. All26 pins match; pip check passed. Actual immutable candidate imports, numpy/pandas operations, cffi/pydantic-core imports, cryptography hashing and Uvicorn config load passed. No listener or provider calls. Offline lifecycle passed: health200, missing dependency ready503, protected401, absent reports404, deployed docs404; research imports excluded.
- These results are NOT Linux installation evidence. Docker Desktop29.5.2 is accessible through the selected local Unix socket; engine Linux arm64. One `docker pull --platform linux/amd64 python:3.14.7-slim-bookworm` failed resolving registry-1.docker.io. No image digest/patch/ABI could be established, no container was created and no package installation occurred. Cached PowerFlow images inspected are arm64 and were not run. No retries, resolver changes or alternate registries were used.
- All installed package Requires-Python metadata accepts3.14.7. Eleven pins reject system3.9.25; do NOT create the candidate with `/usr/bin/python3`.
- Existing macOS API TEST venv occupies186,620KiB (182.25MiB), including test tools. Linux API-only size is unmeasured. Budget conservatively300MiB venv and1GiB total installation workspace IN ADDITION TO2GiB free reserve; replace estimates with measurements. Do not compile dependencies on the shared EC2.

## Reproducible environment and wheel acquisition gates

Proposed local environment: non-free-threaded CPython3.14.7, Linux x86_64, glibc-based image pinned by OCI digest and verified interpreter/architecture (not just a mutable tag). `python:3.14.7-slim-bookworm` is a proposed discovery reference ONLY; availability and digest have not been verified. Acquire the image/wheels through separately reviewed network access if needed; no fabricated digest. Local Docker Desktop is now available; registry DNS resolution or a separately verified offline amd64 image is required first.

Prefer wheels with glibc baseline <=2.28 and cp314 or compatible abi3 tags (plus pure-Python wheels). Do not use macOS/arm64, musllinux or cp314t wheels. Confirm EC2 libc, base interpreter location and shared-library requirements before claiming compatibility. A Debian test alone does not prove Amazon Linux compatibility.

Proposed download command ONLY after network acquisition is permitted (not executed):

```sh
python -m pip download --only-binary=:all: --no-cache-dir \
  --implementation cp --python-version 3.14 --abi cp314 --abi abi3 --abi none \
  --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 \
  --platform manylinux2014_x86_64 \
  --dest "$NEW_REVIEWED_WHEELHOUSE" \
  -r /private/tmp/powerflow-react-stage-review-dudwnuhr/candidate/requirements/api.lock
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

## Latest execution result — local Docker available, Linux run blocked

Authoritative lock SHA256: `b1d8bbbec84a08b651b7bdc0b96e5bb94bf6c527297e037357702de00bcc84e3`. Correct dateutil pin: **python-dateutil==3.0.0**. The previous chat summary was incorrect; no lock change is needed.

Image pull failed before manifest resolution: Docker reported DNS lookup failure for `registry-1.docker.io`. Consequently immutable image digest, actual Python patch/ABI, compatible Linux wheels, Linux installation/import results and Linux venv size are all UNVERIFIED. A mutable reference is not a selected immutable image. No3.14.7-to-EC2 patch comparison can be claimed yet.

Next: restore Docker Desktop registry DNS outside this procedure, or supply an independently verified offline Linux amd64 image. Do not change Docker/system DNS automatically. Then resolve and pin the amd64 image digest, verify actual interpreter version, acquire/hash exact26 wheels, and run the disposable clean-install procedure. Keep only candidate `api/` and the reviewed probe mounted read-only; no production environment/credentials, Docker socket mount, host networking, privileges or other host directories. Run under Linux amd64 explicitly, with bounded time/resource limits. Prefer a separate network-enabled wheel acquisition container and then `--network none` for installation/import testing, using an explicitly approved temporary wheel volume. No EC2 action is required to resolve this local blocker.

## Latest resumed verification — image/runtime PASS, locked install TIMEOUT

The image is now locally available and digest-verified:
`python@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56`.
A disposable `--platform linux/amd64 --network none` runtime probe confirmed CPython3.14.7, Linux x86_64, ABI `cpython-314-x86_64-linux-gnu`, glibc2.36. Python patch matches the existing EC2 interpreter; EC2 libc/base-prefix accessibility is still unverified. Earlier image/DNS blocker is historical, not current.

A separate disposable non-root container used read-only root, dropped capabilities, no-new-privileges,1.5GiB memory cap, one CPU,128-task cap and768MiB tmpfs. Only candidate `api/` and the reviewed runtime probe were mounted read-only. No Docker socket, host network, production environment, credentials, SSH keys or production data were supplied. Image pulling was disabled and exact digest used. Package access was explicit isolated pip against public `https://pypi.org/simple`, binary-only, no cache, retries0. No private package index or alternate version was used.

Fresh venv creation passed. Exact full-lock install hit its150-second bound (status124); overall container verification exited1. The independent exact-pin check succeeded and downloaded `python_dateutil-3.0.0-py2.py3-none-any.whl` from PyPI. Thus dateutil3.0.0 availability is CONFIRMED, not a missing-pin blocker. No pin changed. Wheel SHA256 was not recorded before disposable container removal, so this is not an approved transfer wheelhouse.

Because the full install did not finish, Linux pip check, compiled imports, lifecycle and regressions were NOT RUN. The incomplete venv occupied13,200KiB (12.89MiB); it is NOT a valid installed-size estimate. Other locked wheel availability and Amazon Linux compatibility remain unresolved. The150-second install timeout retained no partial pip output in this probe; no package-specific stall can be attributed from this evidence. Full stdout/stderr/result captures remain private locally. The container/tmpfs was removed automatically; no host data was deleted.

No automatic install retry was performed. Next local verification should retain incremental pip logs throughout execution and separate binary-wheel resolution/download from a network-disabled install/import phase, with an explicitly reviewed longer overall bound. Reuse this exact image digest and lock; do not loosen pins or perform source builds. Measure full venv and workspace usage only after completion. No EC2 installation is ready for authorization until that gate passes.28 local macOS regression tests passed; these are not Linux tests.
