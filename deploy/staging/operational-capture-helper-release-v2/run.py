"""One manifest-bound action. Every remote action needs separate authorization."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import types
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-operational-capture-helper-20261107-v2'
TRANSACTION='13ee1fecc7214ba789feb78af43f28b4'
def read(path):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode) and s.st_size<=4*1024*1024
        return f.read(4*1024*1024+1)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def verify(expected,action):
    raw=read(HERE/'MANIFEST.json');assert sha(raw)==expected;m=json.loads(raw)
    assert m['version']==1 and m['execution_authorized']is False and m['release']==RELEASE and m['transaction']==TRANSACTION
    builder=read(HERE/'build.py');assert sha(builder)==m['artifacts'][str((HERE/'build.py').relative_to(ROOT))]
    b=types.ModuleType('verified_helper_builder');b.__file__=str(HERE/'build.py');exec(compile(builder,'<verified-helper-builder>','exec'),b.__dict__)
    expected_artifacts={str((HERE/n).relative_to(ROOT)) for n in b.FILES}|{'deploy/staging/operational-capture-correction-v1/MANIFEST.json','tests/test_operational_capture_helper_release_v2.py','tests/test_operational_capture_correction.py'}
    assert set(m['artifacts'])==expected_artifacts and set(m['payloads'])=={'preflight','apply','rollback'}
    for rel,digest in m['artifacts'].items():
        path=Path(rel);assert not path.is_absolute() and '..'not in path.parts and sha(read(ROOT/path))==digest
    old,prefix,wrapper,base=b.baseline();cfg=b.config(old);assert cfg==m['config']
    blobs={n:read(HERE/n) for n in b.FILES};payload=b.assemble(action,prefix,cfg,blobs)
    assert payload==read(HERE/(action+'.payload.py')) and sha(payload)==m['payloads'][action]['sha256'] and len(payload)==m['payloads'][action]['bytes']
    return payload,wrapper,base

def validate_report(value):
    allowed={'status','phase','changed','reason','error_class','function','line','release','transaction','operational_enabled','forecast_enabled','activation','rollback','helper_version','forecast_preserved','services_restarted','natural_run_acceptance','rollback_ready','retained_versioned_helper'}
    assert type(value)is dict and set(value)<=allowed and value.get('status')in {'PREFLIGHT_PASS','APPLIED','ROLLED_BACK','BLOCKED','FAILED'}
    assert type(value.get('changed'))is bool
    assert all(type(v)in {str,bool,int,type(None)} and (not isinstance(v,str)or len(v)<=160) for v in value.values())
    return value

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['preflight','apply','rollback']);p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args();attempts=0
    try:
        payload,wrapper,base=verify(a.manifest_sha256,a.action)
        if a.local_check:print('{"status":"LOCAL_PASS","ssh_attempts":0}');return 0
        argv=wrapper.ssh_argv(wrapper.profile());seconds=90 if a.action=='preflight' else 120
        argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s '+str(seconds)+'s /usr/bin/python3 -I -S -B -'
        os.umask(0o077);folder=Path(tempfile.mkdtemp(prefix='operational-helper-'+a.action+'-',dir=wrapper.PRIVATE/'preflight'))
        attempts=1;r=base.bounded_run(argv,input=payload,timeout=seconds+60,limit=32768,grace=5)
        for key in ['stdout','stderr']:
            with (folder/(key+'.private')).open('xb') as f:f.write(r[key])
        report=None;failure=r['failure']
        if not failure:
            try:
                report=validate_report(json.loads(r['stdout']));assert (r['returncode']==0)==(report['status']in {'PREFLIGHT_PASS','APPLIED','ROLLED_BACK'})
            except Exception:failure='UNVERIFIED_OUTPUT'
        summary={'exit_status':r['returncode'],'failure':failure,'report':report,'ssh_attempts':1}
        with (folder/'assessment.json').open('x') as f:json.dump(summary,f,sort_keys=True)
        print(json.dumps(summary,sort_keys=True));print(json.dumps({'private_evidence':str(folder)}));return r['returncode']or(1 if failure else 0)
    except Exception:
        print(json.dumps({'status':'BLOCKED'if attempts==0 else'FAILED','reason':'LOCAL_INTEGRITY_OR_PINNED_IDENTITY'if attempts==0 else'TRANSPORT_OR_CAPTURE_UNVERIFIED','ssh_attempts':attempts}));return 1
if __name__=='__main__':raise SystemExit(main())
