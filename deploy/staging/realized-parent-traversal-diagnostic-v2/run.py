"""One immutable read-only attempt; strict framed output and safe validation details."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import types

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-realized-parent-traversal-diagnostic-20261108-v2'
PARENT_SHA='41ebe0af3a0f9533af40e618c77be0238caa4d194366178ac1c7fd613a8ed4d6'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):
    path=Path(path)
    if any(p.is_symlink()for p in(path,*path.parents)):raise ValueError('LOCAL_BINDING')
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb')as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode)or s.st_size>4*1024**2:raise ValueError('LOCAL_BINDING')
        raw=f.read(4*1024**2+1)
        if len(raw)!=s.st_size:raise ValueError('LOCAL_BINDING')
        return raw

def module(raw,name,path):
    m=types.ModuleType(name);m.__file__=str(path);exec(compile(raw,'<verified-'+name+'>','exec'),m.__dict__);return m

def verify(expected):
    raw=read(HERE/'MANIFEST.json');assert sha(raw)==expected;m=json.loads(raw)
    assert set(m)=={'version','release','execution_authorized','parent_manifest','frame_id','artifacts','payload'}
    assert m['version']==1 and m['release']==RELEASE and m['execution_authorized']is False and m['parent_manifest']==PARENT_SHA
    source=read(HERE/'build.py');assert sha(source)==m['artifacts'][str((HERE/'build.py').relative_to(ROOT))]
    b=module(source,'traversal_v2_builder',HERE/'build.py');assert set(m['artifacts'])==b.artifact_paths()
    for path,digest in m['artifacts'].items():assert sha(read(ROOT/path))==digest
    transport,wrapper,supervisor,payload,schema,frame_id=b.assemble()
    assert m['frame_id']==frame_id and m['payload']=={'bytes':len(payload),'sha256':sha(payload)}and payload==read(HERE/'inspect.payload.py')
    protocol=module(read(HERE/'protocol.py'),'traversal_v2_protocol',HERE/'protocol.py')
    return transport,wrapper,supervisor,payload,schema,protocol,frame_id

def command(transport,wrapper):
    profile=wrapper['profile']();original=wrapper['ssh_argv'](profile)
    return original[:-2]+[part for option in transport.EXTRA_OPTIONS for part in ['-o',option]]+[profile['target'],'sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 20s /usr/bin/python3 -I -S -B -']

def assess(result,schema,protocol,frame_id,wrapper):
    failure=result['failure'];accepted=None;validation=None;candidate=None
    if failure is None and result['returncode']==255:failure=wrapper['failure_category'](255,result['stderr'])
    if failure is None:
        try:accepted=protocol.decode(result['stdout'],result['returncode'],schema,frame_id)
        except protocol.Rejected as error:
            failure='DIAGNOSTIC_OUTPUT_UNVERIFIED';validation=error.safe();candidate=getattr(error,'candidate',None)
        except Exception:
            failure='DIAGNOSTIC_OUTPUT_UNVERIFIED';validation={'stage':'REPORT','code':'REPORT_FIELDS','field':'REPORT'}
    summary={'exit_status':result['returncode'],'failure':failure,'report':accepted,'validation':validation,'stdout_bytes':len(result['stdout']),'stderr_bytes':len(result['stderr']),'ssh_attempts':1}
    return summary,candidate

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args();attempts=0
    try:
        transport,wrapper,supervisor,payload,schema,protocol,frame_id=verify(a.manifest_sha256)
        argv=command(transport,wrapper)
        if a.local_check:print('{"local_integrity":"PASS","ssh_attempts":0}');return 0
        os.umask(0o077);folder=Path(tempfile.mkdtemp(prefix='realized-parent-traversal-v2-',dir=wrapper['PRIVATE']/'preflight'))
        attempts=1;result=supervisor(argv,input=payload,timeout=40,limit=8192,grace=5)
        summary,candidate=assess(result,schema,protocol,frame_id,wrapper)
        private={**summary,'unaccepted_sanitized_candidate':candidate}
        with os.fdopen(os.open(folder/'assessment.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w')as f:json.dump(private,f,sort_keys=True)
        print(json.dumps(summary,sort_keys=True));return result['returncode']or(1 if summary['failure']else 0)
    except Exception:
        print(json.dumps({'status':'BLOCKED','reason':'LOCAL_IMMUTABLE_OR_PINNED_IDENTITY'if attempts==0 else'DIAGNOSTIC_TRANSPORT_OR_CAPTURE_UNVERIFIED','ssh_attempts':attempts}));return 1
if __name__=='__main__':raise SystemExit(main())
