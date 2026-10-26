# Offline Linux dependency gate — proposed, NOT executed

Run on a disposable LOCAL Linux x86_64 container/VM, not the production Python environment. No EC2 changes or services. Do not install dependencies until approved. Required before running: reviewed Linux CPython3.14 image pinned by digest, approved x86_64 wheelhouse with exact file SHA256 manifest matching candidate `api/requirements/api.lock` and `shared.txt`. Neither is currently supplied/verified. No assumed Docker tag or network download is an execution-ready substitute.

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
    test "$(python -I -S -B -c "import sys;print(str(sys.version_info.major)+str(sys.version_info.minor))")" = 314
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
