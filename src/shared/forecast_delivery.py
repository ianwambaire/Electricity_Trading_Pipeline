"""Worker-side opt-in delivery. No root work, tokens or model execution here."""
import json
import os
import selectors
import signal
import subprocess
import time
import uuid

HELPER='/usr/local/sbin/powerflow-publish-next24'
STATUSES={'PUBLISHED','SKIPPED_WITHHELD','SKIPPED_EXPIRED','SKIPPED_DUPLICATE','REJECTED_OLDER_ISSUE','DISABLED','REJECTED_INFERENCE','FAILED'}

def valid_uuid(value):
    try:return isinstance(value,str) and str(uuid.UUID(value))==value
    except (ValueError,TypeError,AttributeError):return False

def invoke(receipt,flow):
    argv=['/usr/bin/sudo','-n',HELPER,'--receipt',receipt,'--flow-run',flow]
    p=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        env={'PATH':'/usr/bin:/bin'},start_new_session=True)
    selector=selectors.DefaultSelector();out=bytearray();total=0;deadline=time.monotonic()+40
    try:
        for stream in (p.stdout,p.stderr):os.set_blocking(stream.fileno(),False);selector.register(stream,selectors.EVENT_READ)
        while selector.get_map():
            if time.monotonic()>=deadline:raise TimeoutError()
            for key,_ in selector.select(min(.2,max(0,deadline-time.monotonic()))):
                raw=os.read(key.fileobj.fileno(),4096)
                if not raw:selector.unregister(key.fileobj);continue
                total+=len(raw)
                if total>16384:raise ValueError('output_bound')
                if key.fileobj is p.stdout:out.extend(raw)
        p.wait(timeout=max(.01,deadline-time.monotonic()))
        if p.returncode:raise ValueError('helper_failed')
        value=json.loads(out)
        if type(value)is not dict or set(value)!={'status'} or value['status'] not in STATUSES:raise ValueError('helper_contract')
        return value
    finally:
        if p.poll() is None:
            try:os.killpg(p.pid,signal.SIGTERM)
            except (ProcessLookupError,PermissionError):pass
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:os.killpg(p.pid,signal.SIGKILL)
                except (ProcessLookupError,PermissionError):pass
                # The root-owned launcher also has its own 30s+5s bound. Never
                # turn a failed signal permission into an unbounded worker wait.
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:pass
        selector.close();p.stdout.close();p.stderr.close()

def deliver(result,flow_id,*,enabled=False,runner=invoke):
    if not enabled:return {'status':'DISABLED'}
    if result.get('status')=='WITHHELD' and result.get('generated') is False:return {'status':'SKIPPED_WITHHELD'}
    if result.get('status') not in {'GENERATED','UNCHANGED'} or result.get('generated') is not True or not valid_uuid(result.get('inference_receipt_id')) or not valid_uuid(flow_id):
        return {'status':'REJECTED_INFERENCE'}
    try:
        report=runner(result['inference_receipt_id'],flow_id)
        if type(report)is not dict or set(report)!={'status'} or report['status'] not in STATUSES:raise ValueError()
        return report
    except Exception:return {'status':'FAILED'} # no tokens, stderr, paths or feature values
