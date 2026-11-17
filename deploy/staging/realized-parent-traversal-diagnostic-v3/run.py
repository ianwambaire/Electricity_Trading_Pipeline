"""One stdin-enabled, pinned read-only attempt. No remote authorization implied."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import types

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-realized-parent-traversal-diagnostic-20261108-v3'
PARENT_SHA='303af3ff285c1628081bec69bd28dd3502e0bc0994765c753a3800b3a3e6ab05'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):
    path=Path(path);assert not any(p.is_symlink()for p in(path,*path.parents))
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb')as f:
        st=os.fstat(f.fileno());assert stat.S_ISREG(st.st_mode)and st.st_size<=4*1024**2
        raw=f.read(4*1024**2+1);assert len(raw)==st.st_size;return raw

def module(raw,name,path):
    m=types.ModuleType(name);m.__file__=str(path);exec(compile(raw,'<verified-'+name+'>','exec'),m.__dict__);return m

def verify(expected):
    raw=read(HERE/'MANIFEST.json');assert sha(raw)==expected;m=json.loads(raw)
    assert set(m)=={'version','release','execution_authorized','parent_manifest','stdin_policy','frame_id','artifacts','payload'}
    assert m['version']==1 and m['release']==RELEASE and m['execution_authorized']is False and m['parent_manifest']==PARENT_SHA and m['stdin_policy']=='PAYLOAD_REQUIRED_STDINNULL_NO'
    source=read(HERE/'build.py');assert sha(source)==m['artifacts'][str((HERE/'build.py').relative_to(ROOT))]
    b=module(source,'traversal_v3_builder',HERE/'build.py');assert set(m['artifacts'])==b.artifact_paths()
    for path,digest in m['artifacts'].items():assert sha(read(ROOT/path))==digest
    parent,values=b.parent();_,_,_,payload,_,_,frame_id=values
    assert m['frame_id']==frame_id and m['payload']=={'sha256':sha(payload),'bytes':len(payload)}and payload==read(HERE/'inspect.payload.py')
    return parent,values

def command(parent,transport,wrapper):
    original=parent.command(transport,wrapper)
    # Correct the single inherited connectivity-only setting IN PLACE. OpenSSH
    # uses the first obtained option; appending StdinNull=no would not fix it.
    slots=[i for i,arg in enumerate(original)if arg.lower().startswith('stdinnull=')]
    assert len(slots)==1 and original[slots[0]]=='StdinNull=yes'and slots[0]>0 and original[slots[0]-1]=='-o','STDIN_POLICY_DRIFT'
    assert '-n'not in original and '-f'not in original,'STDIN_POLICY_DRIFT'
    assert original[0:4]==['/usr/bin/ssh','-F','/dev/null','-T']and original[-1]=='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 20s /usr/bin/python3 -I -S -B -','SSH_COMMAND_DRIFT'
    result=list(original);result[slots[0]]='StdinNull=no'
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');args=p.parse_args();attempts=0
    try:
        parent,values=verify(args.manifest_sha256);transport,wrapper,supervisor,payload,schema,protocol,frame_id=values
        argv=command(parent,transport,wrapper)
        if args.local_check:print('{"local_integrity":"PASS","stdin_policy":"PAYLOAD_ENABLED","ssh_attempts":0}');return 0
        os.umask(0o077);folder=Path(tempfile.mkdtemp(prefix='realized-parent-traversal-v3-',dir=wrapper['PRIVATE']/'preflight'))
        attempts=1;result=supervisor(argv,input=payload,timeout=40,limit=8192,grace=5)
        # Same held, verified strict V2 frame/schema/identity/exit validator.
        summary,candidate=parent.assess(result,schema,protocol,frame_id,wrapper)
        with os.fdopen(os.open(folder/'assessment.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w')as f:json.dump({**summary,'unaccepted_sanitized_candidate':candidate},f,sort_keys=True)
        print(json.dumps(summary,sort_keys=True));return result['returncode']or(1 if summary['failure']else 0)
    except Exception:
        print(json.dumps({'status':'BLOCKED','reason':'LOCAL_IMMUTABLE_IDENTITY_OR_STDIN_POLICY'if attempts==0 else'DIAGNOSTIC_TRANSPORT_OR_CAPTURE_UNVERIFIED','ssh_attempts':attempts}));return 1
if __name__=='__main__':raise SystemExit(main())
