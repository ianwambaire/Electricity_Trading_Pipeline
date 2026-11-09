"""Manifest-bound action; every remote invocation requires separate authorization."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import types

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-live-forecast-reliability-acceptance-20261107-v3'
TRANSACTION='565437b5103a45d3b6192ecd70498f78'
def read(p):
    with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode) and s.st_size<=4*1024*1024
        return f.read(4*1024*1024+1)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def verify(expected):
    raw=read(HERE/'MANIFEST.json');assert sha(raw)==expected;m=json.loads(raw)
    source=read(HERE/'build.py');assert sha(source)==m['artifacts'][str((HERE/'build.py').relative_to(ROOT))]
    b=types.ModuleType('verified_acceptance_builder');b.__file__=str(HERE/'build.py');exec(compile(source,'<verified-builder>','exec'),b.__dict__)
    assert m['version']==1 and m['execution_authorized']is False and m['release']==b.RELEASE and m['transaction']==TRANSACTION and m['parent_manifest']==b.PARENT_SHA
    assert set(m['artifacts'])==b.artifact_paths()
    for rel,digest in m['artifacts'].items():
        assert not Path(rel).is_absolute() and '..'not in Path(rel).parts and sha(read(ROOT/rel))==digest
    payload,wrapper,base=b.assemble()
    assert payload==read(HERE/'accept.payload.py') and sha(payload)==m['payload_sha256']
    return payload,wrapper,base
def validate_report(r):
    allowed={'status','phase','changed','reason','operation','line','release','transaction','linux_imports','forecast_enabled','operational_enabled','rollback_ready','deployment_authorized','browser','natural_run','retained_release_evidence','analyst_authorization','forecast_http','forecast_status','prediction_count','run_id','run_state','operational_status','evidence_sha256','pipeline_run_id','inference','delivery'}
    assert type(r)is dict and set(r)<=allowed and r.get('status')in {'PREFLIGHT_PASS','APPLIED','ROLLED_BACK','PASS','PARTIAL','BLOCKED','FAILED'} and type(r.get('changed'))is bool
    assert all(type(v)in {str,int,bool,type(None)} and (type(v)is not str or len(v)<=160) for v in r.values())
    return r
def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args();attempts=0
    try:
        payload,wrapper,base=verify(a.manifest_sha256)
        profile=wrapper.profile() # Local identity/known-host binding checks only.
        if a.local_check:print('{"status":"LOCAL_PASS","ssh_attempts":0}');return 0
        argv=wrapper.ssh_argv(profile);seconds=90
        argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s '+str(seconds)+'s /usr/bin/python3 -I -S -B -'
        os.umask(0o077);folder=Path(tempfile.mkdtemp(prefix='forecast-reliability-accept-v3-',dir=wrapper.PRIVATE/'preflight'))
        attempts=1;r=base.bounded_run(argv,input=payload,timeout=seconds+60,limit=32768,grace=5)
        for key in ['stdout','stderr']:
            with (folder/(key+'.private')).open('xb') as f:f.write(r[key])
        report=None;failure=r['failure']
        if not failure:
            try:
                report=validate_report(json.loads(r['stdout']));assert (r['returncode']==0)==(report['status']in {'PREFLIGHT_PASS','APPLIED','ROLLED_BACK','PASS','PARTIAL'})
            except Exception:failure='UNVERIFIED_OUTPUT'
        summary={'exit_status':r['returncode'],'failure':failure,'report':report,'ssh_attempts':1}
        with (folder/'assessment.json').open('x') as f:json.dump(summary,f,sort_keys=True)
        print(json.dumps(summary,sort_keys=True));print(json.dumps({'private_evidence':str(folder)}));return r['returncode']or(1 if failure else 0)
    except Exception:
        print(json.dumps({'status':'BLOCKED'if attempts==0 else'FAILED','reason':'LOCAL_INTEGRITY_OR_PINNED_IDENTITY'if attempts==0 else'TRANSPORT_OR_CAPTURE_UNVERIFIED','ssh_attempts':attempts}));return 1
if __name__=='__main__':raise SystemExit(main())
