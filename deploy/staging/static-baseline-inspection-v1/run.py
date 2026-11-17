"""One separately authorized SSH observation; --local-check never connects."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ORIGINAL='deploy/staging/operational-evidence-release-v1/'
MANIFEST_SHA='873619a9cd73d5fc676058facc1ed5daf1dc1030efbc4572b42c34653a4bf7d9'
APPROVED='data/backups/private-staging-releases/phase-api-body-bound-20261102-v2/release/release-manifest.json'
APPROVED_SHA='dc2fd9aa9cb0e961fd3859aa63b946a307c43f8a31ed6d8ac0ef4529c32f2045'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(p):
    with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_size>4*1024**2:raise ValueError('LOCAL_BOUND')
        return f.read(4*1024**2+1)
def verify(expected):
    raw=read(HERE/'MANIFEST.json')
    if sha(raw)!=expected:raise ValueError('MANIFEST')
    m=json.loads(raw)
    for name,digest in m['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or sha(read(ROOT/name))!=digest:raise ValueError('DEPENDENCY')
    original=read(ROOT/ORIGINAL/'MANIFEST.json');approved=read(ROOT/APPROVED)
    if sha(original)!=MANIFEST_SHA or sha(approved)!=APPROVED_SHA:raise ValueError('BASELINE')
    expected_inventory=json.loads(original)['config']['old_static_inventory']
    approved_inventory={k[7:]:v['sha256'] for k,v in json.loads(approved)['files'].items() if k.startswith('static/')}
    source=read(HERE/'inspect.py')
    payload=('EXPECTED='+repr(expected_inventory)+'\nAPPROVED='+repr(approved_inventory)+'\n').encode()+source
    if payload!=read(HERE/'inspect.payload.py') or sha(payload)!=m['payload_sha256']:raise ValueError('PAYLOAD')
    spec=importlib.util.spec_from_file_location('verified_operational_runner',ROOT/ORIGINAL/'run.py')
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    _,wrapper,base=old.verify(MANIFEST_SHA,'preflight')
    return payload,wrapper,base
def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');args=p.parse_args();attempts=0
    try:
        payload,wrapper,base=verify(args.manifest_sha256)
        if args.local_check:print('{"status":"LOCAL_PASS","ssh_attempts":0}');return 0
        argv=wrapper.ssh_argv(wrapper.profile());argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -'
        os.umask(0o077);folder=Path(tempfile.mkdtemp(prefix='static-baseline-',dir=wrapper.PRIVATE/'preflight'))
        attempts=1;result=base.bounded_run(argv,input=payload,timeout=90,limit=150000,grace=5)
        for name in ['stdout','stderr']:
            with (folder/(name+'.private')).open('xb') as f:f.write(result[name])
        report=None
        if not result['failure'] and len(result['stdout'])<=131072:
            try:
                value=json.loads(result['stdout'])
                if type(value)is not dict or value.get('status')not in {'PASS','BLOCKED'} or value.get('changed')is not False:raise ValueError('REPORT')
                report=value
            except (ValueError,TypeError):pass
        summary={'exit_status':result['returncode'],'ssh_attempts':1,'report':report,'failure':result['failure'] or (None if report else 'UNVERIFIED_OUTPUT')}
        with (folder/'assessment.json').open('x') as f:json.dump(summary,f,sort_keys=True)
        print(json.dumps(summary,sort_keys=True));return result['returncode'] or (1 if summary['failure'] else 0)
    except Exception:
        print(json.dumps({'status':'BLOCKED','ssh_attempts':attempts,'reason':'LOCAL_BINDING_FAILED' if not attempts else 'TRANSPORT_OR_CAPTURE_UNVERIFIED'}));return 1
if __name__=='__main__':raise SystemExit(main())
