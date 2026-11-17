"""One action/one pinned SSH attempt. Each remote action needs explicit approval."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import types

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-realized-next24h-performance-20261108-v3'
TRANSACTION='d57c5d23f387428bb606bce437ce4e82'

def read(path):
    path=Path(path)
    if any(p.is_symlink()for p in(path,*path.parents)):raise ValueError('LOCAL_SYMLINK')
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb')as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode)and s.st_size<=4*1024**2
        raw=f.read(4*1024**2+1);assert len(raw)==s.st_size;return raw

def sha(raw):return hashlib.sha256(raw).hexdigest()
def module(raw,name,path):
    m=types.ModuleType(name);m.__file__=str(path);exec(compile(raw,'<verified-'+name+'>','exec'),m.__dict__);return m

def verify(expected,action):
    assert action in {'preflight','apply','rollback','accept'}and re.fullmatch('[0-9a-f]{64}',expected)
    raw=read(HERE/'MANIFEST.json');assert sha(raw)==expected;m=json.loads(raw)
    assert m['version']==1 and m['execution_authorized']is False and(m['release'],m['transaction'])==(RELEASE,TRANSACTION)
    source=read(HERE/'build.py');assert sha(source)==m['artifacts'][str((HERE/'build.py').relative_to(ROOT))]
    b=module(source,'realized_builder',HERE/'build.py')
    assert set(m['artifacts'])==b.artifact_paths()and set(m['payloads'])=={'preflight','apply','rollback','accept'}
    for rel,digest in m['artifacts'].items():assert b.safe_rel(rel)and sha(read(ROOT/rel))==digest
    prefix,parent,_=b.parent();c=b.config(parent);assert c==m['config']
    payload=b.assemble(action,prefix,c);assert payload==read(HERE/(action+'.payload.py'))and sha(payload)==m['payloads'][action]['sha256']and len(payload)==m['payloads'][action]['bytes']
    # Existing reviewed transport modules, independently pinned in this manifest.
    wrapper=module(read(ROOT/b.WRAPPER),'pinned_wrapper',ROOT/b.WRAPPER)
    supervisor=module(read(ROOT/b.SUPERVISOR),'bounded_supervisor',ROOT/b.SUPERVISOR)
    return payload,wrapper,supervisor

def validate_report(r):
    allowed={'status','phase','changed','reason','exception_class','approved_module','cause_class','operation','line','release','transaction','linux_imports','forecast_enabled','operational_enabled','report_delivery_enabled','rollback_ready','deployment_authorized','natural_run','browser','retained_report_store','analyst_authorization','run_id','pipeline_run_id','report_http','report_sha256','report_status','data_status','pair_count','generated_at','fresh_until','backend_status'}
    assert type(r)is dict and set(r)<=allowed and r.get('status')in {'PREFLIGHT_PASS','APPLIED','ROLLED_BACK','PASS','PARTIAL','WAITING','BLOCKED','FAILED'}and type(r.get('changed'))is bool
    assert all(type(v)in {str,int,bool,type(None)}and(type(v)is not str or len(v)<=160)for v in r.values());return r

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['preflight','apply','rollback','accept']);p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args();attempts=0
    try:
        payload,w,b=verify(a.manifest_sha256,a.action);profile=w.profile()
        if a.local_check:print('{"status":"LOCAL_PASS","ssh_attempts":0}');return 0
        # Preflight/accept:90 remote,150 local; apply/rollback:120/180. Five-second
        # process-group escalation. No second command or automatic recovery.
        seconds=90 if a.action in {'preflight','accept'}else 120
        argv=w.ssh_argv(profile);argv=argv[:-2]+['-o','PreferredAuthentications=publickey','-o','PasswordAuthentication=no','-o','KbdInteractiveAuthentication=no']+argv[-2:];argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s '+str(seconds)+'s /usr/bin/python3 -I -S -B -'
        os.umask(0o077);folder=Path(tempfile.mkdtemp(prefix='realized-'+a.action+'-',dir=w.PRIVATE/'preflight'))
        attempts=1;result=b.bounded_run(argv,input=payload,timeout=seconds+60,limit=32768,grace=5)
        report=None;failure=result['failure']
        if result['returncode']==255 and failure is None:failure=w.failure_category(255,result['stderr'])
        if not failure:
            try:
                report=validate_report(json.loads(result['stdout']));assert(result['returncode']==0)==(report['status']in {'PREFLIGHT_PASS','APPLIED','ROLLED_BACK','PASS','PARTIAL','WAITING'})
            except Exception:failure='UNVERIFIED_OUTPUT'
        summary={'exit_status':result['returncode'],'failure':failure,'report':report,'ssh_attempts':1}
        # Never retain raw SSH stdout/stderr (or exception messages).
        with os.fdopen(os.open(folder/'assessment.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w')as f:json.dump(summary,f,sort_keys=True)
        print(json.dumps(summary,sort_keys=True));return result['returncode']or(1 if failure else 0)
    except Exception:
        print(json.dumps({'status':'BLOCKED'if attempts==0 else'FAILED','reason':'LOCAL_INTEGRITY_OR_PINNED_IDENTITY'if attempts==0 else'TRANSPORT_OR_CAPTURE_UNVERIFIED','ssh_attempts':attempts}));return 1
if __name__=='__main__':raise SystemExit(main())
