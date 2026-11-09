"""Immutable tooling-only continuation; unchanged metadata and UID probe."""
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import types

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-realized-parent-traversal-diagnostic-20261108-v2'
PARENT='deploy/staging/realized-parent-traversal-diagnostic-v1'
PARENT_SHA='41ebe0af3a0f9533af40e618c77be0238caa4d194366178ac1c7fd613a8ed4d6'
FILES={'build.py','run.py','protocol.py','REVIEW.md'}
TEST='tests/test_realized_parent_traversal_diagnostic_v2.py'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):
    path=Path(path);assert not any(p.is_symlink()for p in(path,*path.parents))
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb')as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode)and s.st_size<=4*1024**2
        raw=f.read(4*1024**2+1);assert len(raw)==s.st_size;return raw

def module(raw,name,path):
    m=types.ModuleType(name);m.__file__=str(path);exec(compile(raw,'<verified-'+name+'>','exec'),m.__dict__);return m

def artifact_paths():return {str((HERE/f).relative_to(ROOT))for f in FILES}|{TEST,PARENT+'/MANIFEST.json',PARENT+'/run.py'}

def parent():
    raw=read(ROOT/PARENT/'MANIFEST.json');assert sha(raw)==PARENT_SHA;m=json.loads(raw)
    source=read(ROOT/PARENT/'run.py');assert sha(source)==m['artifacts'][PARENT+'/run.py']['sha256']
    p=module(source,'verified_v1_traversal',ROOT/PARENT/'run.py')
    return p.verify(PARENT_SHA)

def assemble():
    transport,wrapper,supervisor,payload,schema=parent();protocol=read(HERE/'protocol.py')
    frame_id=sha(b'powerflow-traversal-output-v2\n'+hashlib.sha256(payload).digest()+hashlib.sha256(protocol).digest())
    marker=b"print(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']=='PASS'else 1)\n"
    assert payload.count(marker)==1
    replacement=b"print(json.dumps({'protocol_version':2,'diagnostic_id':"+repr(frame_id).encode()+b",'report':report},sort_keys=True));raise SystemExit(0 if report['status']=='PASS'else 1)\n"
    framed=payload.replace(marker,replacement);ast.parse(framed,feature_version=(3,9))
    # No changes to any privileged coordinator or unprivileged probe operation.
    old={n.name:ast.dump(n,include_attributes=False)for n in ast.walk(ast.parse(payload))if isinstance(n,ast.FunctionDef)}
    new={n.name:ast.dump(n,include_attributes=False)for n in ast.walk(ast.parse(framed))if isinstance(n,ast.FunctionDef)}
    assert old==new and framed.replace(replacement,marker)==payload
    return transport,wrapper,supervisor,framed,schema,frame_id

def main():
    *_,payload,schema,frame_id=assemble()
    m={'version':1,'release':RELEASE,'execution_authorized':False,'parent_manifest':PARENT_SHA,'frame_id':frame_id,'artifacts':{p:sha(read(ROOT/p))for p in sorted(artifact_paths())},'payload':{'sha256':sha(payload),'bytes':len(payload)}}
    raw=json.dumps(m,sort_keys=True,indent=2).encode()+b'\n';outputs={HERE/'MANIFEST.json':raw,HERE/'inspect.payload.py':payload}
    for path,value in outputs.items():
        if os.path.lexists(path):assert read(path)==value,'IMMUTABLE_DIAGNOSTIC_DRIFT'
    for path,value in outputs.items():
        if not os.path.lexists(path):
            with path.open('xb')as f:f.write(value)
    print(json.dumps({'manifest_sha256':sha(raw),'payload_sha256':sha(payload),'frame_id':frame_id,'ssh_attempts':0},sort_keys=True))
if __name__=='__main__':main()
