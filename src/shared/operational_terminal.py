"""Disabled-by-default Prefect terminal notification; no capture/publisher in worker.

The restricted immutable helper independently verifies the exact terminal state.
All failures are isolated from inference, forecast delivery and flow state.
"""
import json
import os
import selectors
import signal
import subprocess
import time

from .operational_evidence import identifier

HELPER = '/usr/local/sbin/powerflow-publish-operations'
DEPLOYMENT = '47e5ef51-26d0-44b6-b119-2c40d0e77397'
STATUSES = {'PUBLISHED', 'SKIPPED_DUPLICATE', 'SKIPPED_OLDER_RUN', 'FAILED'}
REASONS = {'CAPTURE_UNVERIFIED', 'OPERATIONAL_STORE_UNCERTAIN', 'IMMUTABLE_RUNTIME_UNVERIFIED',
           'EVIDENCE_REJECTED', 'CAPTURE_OR_STORE_UNVERIFIED'}


def valid_result(value):
    return (type(value) is dict and set(value) in ({'status'}, {'status', 'reason'})
            and isinstance(value.get('status'), str) and value['status'] in STATUSES
            and ('reason' not in value or value['status'] == 'FAILED' and value['reason'] in REASONS))


def flow_identity():
    from prefect.context import FlowRunContext
    context = FlowRunContext.get()
    if context is None:return {}
    run = context.flow_run
    return {'prefect_flow_run_id': str(run.id), 'prefect_deployment_id': str(run.deployment_id) if run.deployment_id else None}


def task_result(result):
    from prefect.context import TaskRunContext
    context = TaskRunContext.get()
    return dict(result, prefect_task_run_id=str(context.task_run.id)) if context is not None else result


def invoke(flow_id, state_id):
    identifier(flow_id); identifier(state_id)
    process = subprocess.Popen(['/usr/bin/sudo', '-n', HELPER, '--flow-run', flow_id, '--state', state_id],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={'PATH': '/usr/bin:/bin'}, start_new_session=True)
    selector = selectors.DefaultSelector(); output = bytearray(); size = 0; deadline = time.monotonic()+40
    try:
        for stream in (process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False); selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            if time.monotonic() >= deadline:raise TimeoutError()
            for key, _ in selector.select(min(.2, max(0, deadline-time.monotonic()))):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:selector.unregister(key.fileobj); continue
                size += len(chunk)
                if size > 16384:raise ValueError('OUTPUT_BOUND')
                if key.fileobj is process.stdout:output.extend(chunk)
        process.wait(timeout=max(.01, deadline-time.monotonic()))
        value = json.loads(output)
        if not valid_result(value) or process.returncode and value['status'] != 'FAILED':raise ValueError('HELPER_CONTRACT')
        return value
    finally:
        if process.poll() is None:
            try:os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):pass
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):pass
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:pass
        selector.close(); process.stdout.close(); process.stderr.close()


def notify(flow_run, state, *, enabled=False, runner=invoke):
    if not enabled:return {'status': 'DISABLED'}
    try:
        if flow_run.auto_scheduled is not True or str(flow_run.deployment_id) != DEPLOYMENT:
            return {'status': 'SKIPPED_NOT_NATURAL'}
        kind = getattr(state.type, 'value', state.type)
        if kind not in {'COMPLETED', 'FAILED'}:return {'status': 'FAILED', 'reason': 'UNSUPPORTED_TERMINAL_STATE'}
        flow_id, state_id = str(flow_run.id), str(state.id)
        identifier(flow_id); identifier(state_id)
        result = runner(flow_id, state_id)
        if not valid_result(result):raise ValueError()
        return result
    except Exception:
        return {'status': 'FAILED', 'reason': 'TERMINAL_CAPTURE_UNVERIFIED'}
