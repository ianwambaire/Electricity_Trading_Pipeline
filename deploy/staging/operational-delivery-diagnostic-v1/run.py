"""One pinned read-only connection; separate from preserved V5 release."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
V5='cdd828defc52ea258852b88aa852d1d470ca915d098021d6ff8fd2be9b05223b'
def sha(v):return hashlib.sha256(v).hexdigest()
def load():
    spec=importlib.util.spec_from_file_location('v5_bound_runner',HERE.parent/'operational-evidence-release-v5/run.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

def assemble():
    v5=load();payload,wrapper,base=v5.verify(V5,'accept')
    marker=b"ACCEPT=types.ModuleType('verified_accept');"
    if payload.count(marker)!=1:raise ValueError('prefix')
    code=v5.read(HERE/'inspect.py')
    prefix=payload.split(marker)[0]
    tail=b"OP=sys.modules['shared.operational_evidence'];CAPTURE=sys.modules['shared.operational_capture'];PRODUCER=sys.modules['shared.operational_evidence_producer']\n"
    tail+=code+b"\ntry:\n report=inspect()\nexcept Exception as error:\n reason=str(error) if isinstance(error,(PLAN.Stop,OP.InvalidEvidence)) else 'DIAGNOSTIC_UNVERIFIED'\n if not re.fullmatch('[A-Z0-9_]{1,80}',reason):reason='DIAGNOSTIC_UNVERIFIED'\n report={'status':'BLOCKED','changed':False,'reason':reason}\nprint(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']=='PASS' else 1)\n"
    return prefix+tail,wrapper,base

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args();attempt=0
    try:
        v5=load();raw=v5.read(HERE/'MANIFEST.json');m=json.loads(raw)
        if sha(raw)!=a.manifest_sha256 or m['v5_manifest']!=V5:raise ValueError('manifest')
        for n,digest in m['files'].items():
            if n not in {'run.py','inspect.py','REVIEW.md','payload.py'} or sha(v5.read(HERE/n))!=digest:raise ValueError('file')
        if set(m['files'])!={'run.py','inspect.py','REVIEW.md','payload.py'}:raise ValueError('closure')
        payload,wrapper,base=assemble()
        if payload!=v5.read(HERE/'payload.py'):raise ValueError('assembly')
        if a.local_check:print(json.dumps({'status':'LOCAL_PASS','ssh_attempts':0}));return 0
        profile=wrapper.profile();argv=wrapper.ssh_argv(profile)
        argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 90s /usr/bin/python3 -I -S -B -'
        os.umask(0o077);folder=Path(tempfile.mkdtemp(prefix='operational-delivery-diagnostic-',dir=wrapper.PRIVATE/'preflight'))
        attempt=1;r=base.bounded_run(argv,input=payload,timeout=150,limit=32768,grace=5)
        report=None
        if not r['failure']:
            report=json.loads(r['stdout']);assert report['status']in {'PASS','PARTIAL','BLOCKED'} and report['changed']is False
        summary={'exit_status':r['returncode'],'failure':r['failure'],'ssh_attempts':1,'report':report}
        for n in ['stdout','stderr']:
            with (folder/(n+'.private')).open('xb') as f:f.write(r[n])
        with (folder/'assessment.json').open('x') as f:json.dump(summary,f,sort_keys=True)
        print(json.dumps(summary,sort_keys=True));print(json.dumps({'private_evidence':str(folder)}));return r['returncode']
    except Exception:
        print(json.dumps({'status':'BLOCKED','reason':'LOCAL_BINDING_FAILED' if not attempt else 'TRANSPORT_OR_CAPTURE_UNVERIFIED','ssh_attempts':attempt}));return 1
if __name__=='__main__':raise SystemExit(main())
