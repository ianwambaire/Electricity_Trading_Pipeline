"""Immutable transport-only continuation. Remote payload/protocol are unchanged."""
import hashlib
import json
import os
from pathlib import Path
import stat
import types

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-realized-parent-traversal-diagnostic-20261108-v3'
PARENT='deploy/staging/realized-parent-traversal-diagnostic-v2'
PARENT_SHA='303af3ff285c1628081bec69bd28dd3502e0bc0994765c753a3800b3a3e6ab05'
FILES={'build.py','run.py','REVIEW.md'}
TEST='tests/test_realized_parent_traversal_diagnostic_v3.py'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):
    path=Path(path);assert not any(p.is_symlink()for p in(path,*path.parents))
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb')as f:
        st=os.fstat(f.fileno());assert stat.S_ISREG(st.st_mode)and st.st_size<=4*1024**2
        raw=f.read(4*1024**2+1);assert len(raw)==st.st_size;return raw

def module(raw,name,path):
    m=types.ModuleType(name);m.__file__=str(path);exec(compile(raw,'<verified-'+name+'>','exec'),m.__dict__);return m

def artifact_paths():return {str((HERE/name).relative_to(ROOT))for name in FILES}|{TEST,PARENT+'/MANIFEST.json',PARENT+'/run.py'}

def parent():
    raw=read(ROOT/PARENT/'MANIFEST.json');assert sha(raw)==PARENT_SHA;manifest=json.loads(raw)
    source=read(ROOT/PARENT/'run.py');assert sha(source)==manifest['artifacts'][PARENT+'/run.py']
    runner=module(source,'verified_traversal_v2',ROOT/PARENT/'run.py')
    return runner,runner.verify(PARENT_SHA)

def main():
    _,(_,_,_,payload,_,_,frame_id)=parent()
    m={'version':1,'release':RELEASE,'execution_authorized':False,'parent_manifest':PARENT_SHA,'stdin_policy':'PAYLOAD_REQUIRED_STDINNULL_NO','frame_id':frame_id,'artifacts':{path:sha(read(ROOT/path))for path in sorted(artifact_paths())},'payload':{'sha256':sha(payload),'bytes':len(payload)}}
    raw=json.dumps(m,sort_keys=True,indent=2).encode()+b'\n';outputs={HERE/'MANIFEST.json':raw,HERE/'inspect.payload.py':payload}
    for path,value in outputs.items():
        if os.path.lexists(path):assert read(path)==value,'IMMUTABLE_DIAGNOSTIC_DRIFT'
    for path,value in outputs.items():
        if not os.path.lexists(path):
            with path.open('xb')as f:f.write(value)
    print(json.dumps({'release':RELEASE,'manifest_sha256':sha(raw),'payload_sha256':sha(payload),'frame_id':frame_id,'ssh_attempts':0},sort_keys=True))
if __name__=='__main__':main()
