"""Immutable diagnostic overlay; no acceptance or deployment policy changes."""
import ast
import json
from pathlib import Path
import types
import hashlib
import os
import stat
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-live-forecast-preservation-inspection-20261108-v1'
TRANSACTION='565437b5103a45d3b6192ecd70498f78'
PARENT_SHA='80da2c6f98b41c0237919f860a270268e5e5870f0530f95d5dc2261e1acf1730'
FILES={'build.py','run.py','inspect.py','REVIEW.md'}
TEST='tests/test_live_forecast_preservation_inspection.py'
SOURCE={'src/models/next24h_production.py','src/models/inference_evidence.py'}
def read(p):
    with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb')as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode)and s.st_size<=4*1024*1024
        raw=f.read(4*1024*1024+1);assert len(raw)==s.st_size;return raw
def sha(raw):return hashlib.sha256(raw).hexdigest()
def artifact_paths():return {str((HERE/n).relative_to(ROOT)) for n in FILES}|{TEST}|SOURCE

def parent():
    folder=HERE.parent/'live-forecast-reliability-acceptance-v3';raw=read(folder/'MANIFEST.json');assert sha(raw)==PARENT_SHA;m=json.loads(raw)
    source=read(folder/'run.py');assert sha(source)==m['artifacts'][str((folder/'run.py').relative_to(ROOT))]
    r=types.ModuleType('verified_v3_parent');r.__file__=str(folder/'run.py');exec(compile(source,'<verified-parent-runner>','exec'),r.__dict__)
    return r.verify(PARENT_SHA)

def assemble():
    payload,wrapper,base=parent();marker=b'try:\n report=JOB.accept_report()'
    assert payload.count(marker)==1
    text=payload.split(marker)[0]
    text+=b"\nDIAG=types.ModuleType('verified_preservation_inspection');DIAG.__dict__.update(JOB=JOB,need=JOB.need)\n"
    text+=b'exec(compile('+repr(read(HERE/'inspect.py')).encode()+b",'<verified-preservation-inspection>','exec'),DIAG.__dict__)\n"
    text+=b"try:\n report=DIAG.inspect()\nexcept Exception as error:\n reason=str(error) if isinstance(error,(PLAN.Stop,GUARD.Stop,HELPER.OP.InvalidEvidence)) else 'UNVERIFIED_INSPECTION'\n if not __import__('re').fullmatch('[A-Z0-9_]{1,80}',reason):reason='UNVERIFIED_INSPECTION'\n report={'status':'BLOCKED','changed':False,'stage':DIAG.STAGE,'reason':reason}\nprint(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']=='PASS' else 1)\n"
    ast.parse(text,feature_version=(3,9));assert len(text)<4*1024*1024
    return text,wrapper,base

def main():
    payload,_,_=assemble();m={'version':1,'execution_authorized':False,'release':RELEASE,'transaction':TRANSACTION,'parent_manifest':PARENT_SHA,'artifacts':{p:sha(read(ROOT/p)) for p in sorted(artifact_paths())},'payload_sha256':sha(payload)}
    raw=json.dumps(m,sort_keys=True,indent=2).encode()+b'\n';outputs={HERE/'MANIFEST.json':raw,HERE/'inspect.payload.py':payload}
    for p,v in outputs.items():
        if os.path.lexists(p):assert read(p)==v,'IMMUTABLE_DIAGNOSTIC_DRIFT'
    for p,v in outputs.items():
        if not os.path.lexists(p):
            with p.open('xb')as f:f.write(v)
    print(json.dumps({'manifest_sha256':sha(raw),'payload_sha256':sha(payload),'runner_sha256':sha(read(HERE/'run.py')),'inspector_sha256':sha(read(HERE/'inspect.py'))}))
if __name__=='__main__':main()
