"""Immutable acceptance-only overlay; original release remains unchanged."""
import ast
import json
from pathlib import Path
import types
import hashlib
import os
import stat
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-live-forecast-reliability-acceptance-20261107-v3'
TRANSACTION='565437b5103a45d3b6192ecd70498f78'
PARENT_SHA='01b98fc094595b5ec626be8a0a254d57193ba63a8b25e1cc2a729f4c2752dba7'
FILES={'build.py','run.py','acceptance.py','REVIEW.md'}
TEST='tests/test_live_forecast_reliability_acceptance_v3.py'
def read(p):
    with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode) and s.st_size<=4*1024*1024
        raw=f.read(4*1024*1024+1);assert len(raw)==s.st_size;return raw
def sha(raw):return hashlib.sha256(raw).hexdigest()
def artifact_paths():return {str((HERE/n).relative_to(ROOT)) for n in FILES}|{TEST}
def parent():
    folder=HERE.parent/'live-forecast-reliability-release-v2'
    raw=read(folder/'MANIFEST.json');assert sha(raw)==PARENT_SHA;m=json.loads(raw)
    source=read(folder/'run.py');assert sha(source)==m['artifacts'][str((folder/'run.py').relative_to(ROOT))]
    r=types.ModuleType('verified_v2_acceptance');r.__file__=str(folder/'run.py');exec(compile(source,'<verified-parent-runner>','exec'),r.__dict__)
    payload,wrapper,base=r.verify(PARENT_SHA,'accept')
    original=read(folder/'acceptance.py');assert sha(original)==m['artifacts'][str((folder/'acceptance.py').relative_to(ROOT))]
    return payload,wrapper,base,original

def assemble():
    payload,wrapper,base,original=parent();corrected=read(HERE/'acceptance.py')
    # Only the acceptance module changes. No mutation entrypoint can be added.
    old=repr(original).encode();new=repr(corrected).encode();assert payload.count(old)==1
    oldtree=ast.parse(original);newtree=ast.parse(corrected)
    oldfunc={n.name:ast.dump(n,include_attributes=False) for n in oldtree.body if isinstance(n,ast.FunctionDef)}
    newfunc={n.name:ast.dump(n,include_attributes=False) for n in newtree.body if isinstance(n,ast.FunctionDef)}
    assert set(newfunc)==set(oldfunc)|{'started_natural'}
    assert all(newfunc[k]==v for k,v in oldfunc.items() if k!='accept_report')
    payload=payload.replace(old,new);ast.parse(payload,feature_version=(3,9));assert len(payload)<4*1024*1024
    return payload,wrapper,base

def main():
    payload,_,_=assemble()
    m={'version':1,'execution_authorized':False,'release':RELEASE,'transaction':TRANSACTION,'parent_manifest':PARENT_SHA,'artifacts':{p:sha(read(ROOT/p)) for p in sorted(artifact_paths())},'payload_sha256':sha(payload)}
    raw=json.dumps(m,sort_keys=True,indent=2).encode()+b'\n'
    outputs={HERE/'MANIFEST.json':raw,HERE/'accept.payload.py':payload}
    for p,v in outputs.items():
        if os.path.lexists(p):assert read(p)==v,'IMMUTABLE_ACCEPTANCE_DRIFT'
    for p,v in outputs.items():
        if not os.path.lexists(p):
            with p.open('xb') as f:f.write(v)
    print(json.dumps({'manifest_sha256':sha(raw),'payload_sha256':sha(payload),'runner_sha256':sha(read(HERE/'run.py')),'acceptance_sha256':sha(read(HERE/'acceptance.py'))}))
if __name__=='__main__':main()
