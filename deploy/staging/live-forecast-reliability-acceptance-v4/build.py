"""Acceptance-only immutable overlay; preserves deployed V2 and prior packages."""
import ast
import json
from pathlib import Path
import types
import hashlib
import os
import stat
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-live-forecast-reliability-acceptance-20261108-v4'
TRANSACTION='565437b5103a45d3b6192ecd70498f78'
PARENT_SHA='80da2c6f98b41c0237919f860a270268e5e5870f0530f95d5dc2261e1acf1730'
INSPECTION_SHA='8cba57746328cd4dcc5434dc29a19f9468d884560aa793d3f7caf9cae03b0339'
FILES={'build.py','run.py','acceptance.py','REVIEW.md'}
TEST='tests/test_live_forecast_reliability_acceptance_v4.py'
def read(p):
    with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb')as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode)and s.st_size<=4*1024*1024
        raw=f.read(4*1024*1024+1);assert len(raw)==s.st_size;return raw
def sha(raw):return hashlib.sha256(raw).hexdigest()
def artifact_paths():return {str((HERE/n).relative_to(ROOT))for n in FILES}|{TEST}
def verified(folder,expected):
    raw=read(folder/'MANIFEST.json');assert sha(raw)==expected;m=json.loads(raw)
    source=read(folder/'run.py');assert sha(source)==m['artifacts'][str((folder/'run.py').relative_to(ROOT))]
    runner=types.ModuleType('verified_parent');runner.__file__=str(folder/'run.py');exec(compile(source,'<verified-parent>','exec'),runner.__dict__)
    return runner.verify(expected),m

def assemble():
    folder=HERE.parent/'live-forecast-reliability-acceptance-v3';(payload,wrapper,base),m=verified(folder,PARENT_SHA)
    inspection=HERE.parent/'live-forecast-preservation-inspection-v1';_,im=verified(inspection,INSPECTION_SHA)
    raw=read(inspection/'inspect.py');assert sha(raw)==im['artifacts'][str((inspection/'inspect.py').relative_to(ROOT))]
    names={'legacy_hashes','historical_output_hashes','replay_production','reconstruct_store','store_history'}
    tree=ast.parse(raw);tree.body=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))or isinstance(n,ast.FunctionDef)and n.name in names]
    assert {n.name for n in tree.body if isinstance(n,ast.FunctionDef)}==names
    helper=ast.unparse(tree).encode()
    original=read(folder/'acceptance.py');assert sha(original)==m['artifacts'][str((folder/'acceptance.py').relative_to(ROOT))]
    corrected=read(HERE/'acceptance.py')
    originalfunc={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(original).body if isinstance(n,ast.FunctionDef)}
    newfunc={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(corrected).body if isinstance(n,ast.FunctionDef)}
    assert all(newfunc[n]==originalfunc[n] for n in {'available_module','forecast_checks','public_operations','started_natural'})
    marker=b'exec(compile('+repr(original).encode()+b",'<verified-reliability-acceptance>','exec'),JOB.__dict__)"
    assert payload.count(marker)==1
    replacement=b"PRES=types.ModuleType('verified_preservation');PRES.__dict__.update(JOB=JOB,need=JOB.need)\n"
    replacement+=b'exec(compile('+repr(helper).encode()+b",'<verified-preservation>','exec'),PRES.__dict__)\nJOB.PRES=PRES\n"
    replacement+=b'exec(compile('+repr(corrected).encode()+b",'<verified-reliability-acceptance>','exec'),JOB.__dict__)"
    payload=payload.replace(marker,replacement);ast.parse(payload,feature_version=(3,9));assert len(payload)<4*1024*1024
    return payload,wrapper,base

def main():
    payload,_,_=assemble();m={'version':1,'execution_authorized':False,'release':RELEASE,'transaction':TRANSACTION,'parent_manifest':PARENT_SHA,'inspection_manifest':INSPECTION_SHA,'artifacts':{p:sha(read(ROOT/p)) for p in sorted(artifact_paths())},'payload_sha256':sha(payload)}
    raw=json.dumps(m,sort_keys=True,indent=2).encode()+b'\n';outputs={HERE/'MANIFEST.json':raw,HERE/'accept.payload.py':payload}
    for p,v in outputs.items():
        if os.path.lexists(p):assert read(p)==v,'IMMUTABLE_ACCEPTANCE_DRIFT'
    for p,v in outputs.items():
        if not os.path.lexists(p):
            with p.open('xb')as f:f.write(v)
    print(json.dumps({'manifest_sha256':sha(raw),'payload_sha256':sha(payload),'runner_sha256':sha(read(HERE/'run.py')),'acceptance_sha256':sha(read(HERE/'acceptance.py'))}))
if __name__=='__main__':main()
