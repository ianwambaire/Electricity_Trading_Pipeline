#!/usr/bin/env python3
"""Authorized local Docker verification only; 600+300 seconds, no retry."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import tempfile
import threading
import time

ROOT=Path('/Users/iannganga/Desktop/electricity-trading-pipeline')
CANDIDATE=Path('/private/tmp/powerflow-react-stage-review-dudwnuhr/candidate')
IMAGE='python@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56'
DOCKER=['docker','--host','unix:///Users/iannganga/.docker/run/docker.sock']

def main():
    os.umask(0o077)
    capture=Path(tempfile.mkdtemp(prefix='powerflow-linux-15min-'))
    manifest=json.loads((CANDIDATE/'release-manifest.json').read_bytes())
    assert hashlib.sha256((CANDIDATE/'release-manifest.json').read_bytes()).hexdigest()=='50be8e7a20c462eb8850d9bf61b77bb655f687f85c725cbd3d903b7ff14aad27'
    for name,item in manifest['files'].items():
        p=CANDIDATE/name;assert not p.is_symlink()
        data=p.read_bytes();assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256']
    phase=ROOT/'deploy/staging/linux-dependency-phase.py'
    regression=ROOT/'deploy/staging/linux-regression-unittest.py'
    unit=ROOT/'deploy/staging/powerflow-candidate-api.service'
    assert hashlib.sha256((CANDIDATE/'api/requirements/api.lock').read_bytes()).hexdigest()=='b1d8bbbec84a08b651b7bdc0b96e5bb94bf6c527297e037357702de00bcc84e3'
    assert unit.read_bytes()==(CANDIDATE/'proposals/powerflow-candidate-api.service').read_bytes()
    runid=capture.name.removeprefix('powerflow-linux-15min-')
    volume='powerflow-verification-wheels-'+runid
    summary={'image':IMAGE,'platform':'linux/amd64','private_capture_directory':str(capture),
        'wheelhouse_volume':volume,'retry_performed':False,'phases':{},'status':'failed',
        'payload_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (phase,regression,unit)}}
    started=time.monotonic();overall=started+895 # reserve5s for bounded cleanup, total<=900 target
    created=subprocess.run(DOCKER+['volume','create','--label','powerflow.scope=local-dependency-verification',volume],capture_output=True,timeout=5)
    if created.returncode:
        summary['failure']='volume_creation_failed';print(json.dumps(summary));return 1
    for name,seconds in [('acquire',600),('offline',300)]:
        remaining=overall-time.monotonic()
        if remaining<=0:summary['failure']='overall_deadline';break
        deadline=min(overall,time.monotonic()+seconds)
        container='powerflow-local-'+name+'-'+runid
        command=DOCKER+['run','--pull=never','--rm','--name',container,'--platform','linux/amd64',
            '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','1536m',
            '--cpus','2','--pids-limit','128','--tmpfs','/tmp:rw,nosuid,nodev,size=768m,mode=1777',
            '--mount','type=bind,src='+str(CANDIDATE/'api')+',dst=/candidate,readonly',
            '--mount','type=volume,src='+volume+',dst=/wheelhouse'+(',readonly' if name=='offline' else '')]
        if name=='offline':
            command+=['--tmpfs','/venv:rw,exec,nosuid,nodev,size=512m,mode=1777',
                '--network','none','--user',str(os.getuid())+':'+str(os.getgid()),
                '--mount','type=bind,src='+str(regression)+',dst=/regression.py,readonly',
                '--mount','type=bind,src='+str(unit)+',dst=/candidate-unit.service,readonly']
        command+=['--entrypoint','python','-i',IMAGE,'-I','-S','-B','-',name]
        logpath=capture/(name+'.log');messages=queue.Queue();phase_start=time.monotonic()
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        def reader():
            for line in iter(process.stdout.readline,b''):messages.put(line)
            messages.put(None)
        thread=threading.Thread(target=reader,daemon=True);thread.start()
        process.stdin.write(phase.read_bytes());process.stdin.close()
        result={'log':str(logpath),'last_completed_operation':None};done=False
        with logpath.open('xb') as log:
            while not done:
                if time.monotonic()>=deadline:
                    result['timeout']=True
                    # Only kill this newly created verification container, never a host service.
                    try:subprocess.run(DOCKER+['kill',container],capture_output=True,timeout=3)
                    except subprocess.TimeoutExpired:pass
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    break
                try:line=messages.get(timeout=0.25)
                except queue.Empty:continue
                if line is None:done=True;continue
                stamp=datetime.datetime.now(datetime.timezone.utc).isoformat().encode()
                log.write(stamp+b' '+line);log.flush()
                text=line.decode(errors='replace').strip()
                if text.startswith('OPERATION_EXIT=') and text.endswith(':0'):
                    result['last_completed_operation']=text[len('OPERATION_EXIT='):-2]
                if text.startswith('RESULT_JSON='):result['report']=json.loads(text[len('RESULT_JSON='):])
        try:result['exit_status']=process.wait(timeout=1)
        except subprocess.TimeoutExpired:result['exit_status']=124
        result['elapsed_seconds']=round(time.monotonic()-phase_start,3)
        summary['phases'][name]=result
        (capture/'progress.json').write_text(json.dumps(summary,indent=2)+'\n')
        if result.get('timeout') or result['exit_status'] or result.get('report',{}).get('status')!='passed':break
    if summary['phases'].get('offline',{}).get('report',{}).get('status')=='passed':summary['status']='passed'
    summary['elapsed_seconds']=round(time.monotonic()-started,3)
    summary['wheelhouse_retention']='Dedicated local Docker volume retained; no automatic deletion'
    (capture/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    brief={k:v for k,v in summary.items() if k!='phases'}
    brief['phases']={}
    for name,result in summary['phases'].items():
        report=result.get('report',{})
        brief['phases'][name]={k:v for k,v in result.items() if k!='report'}
        brief['phases'][name]['report']={k:v for k,v in report.items() if k!='wheels'}
    print(json.dumps(brief,indent=2))
    return 0 if summary['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
