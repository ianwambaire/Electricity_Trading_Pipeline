"""Local-only immutable reporting overlay on the approved read-only preflight."""
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
import types

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
PARENT_SHA='e184215a3959c61dbd41e66e47a78af7951c90bb903d30f4ebb6a2d28ee6aa19'
PREFLIGHT_SHA='e9f16758a03f4690e845e1ac31f6f1cb6607767ede46588210069ef76ef3b564'
RELEASE='phase-live-forecast-import-diagnostic-20261107-v1'
FILES={'build.py','child.py','inspect.py','run.py','REVIEW.md'}
TEST='tests/test_live_forecast_import_diagnostic.py'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(p):
    import stat
    with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode) and s.st_size<=4*1024*1024
        return f.read(4*1024*1024+1)
def module(raw,name,file):
    m=types.ModuleType(name);m.__file__=str(file);exec(compile(raw,'<verified-'+name+'>','exec'),m.__dict__);return m
def parent():
    folder=HERE.parent/'live-forecast-reliability-release-v1';raw=read(folder/'MANIFEST.json');assert sha(raw)==PARENT_SHA
    m=json.loads(raw);runner=read(folder/'run.py');assert sha(runner)==m['artifacts'][str((folder/'run.py').relative_to(ROOT))]
    r=module(runner,'diagnostic_parent_runner',folder/'run.py');payload,wrapper,base=r.verify(PARENT_SHA,'preflight');assert sha(payload)==PREFLIGHT_SHA
    marker=b'try:\n report=JOB.preflight_report()';assert payload.count(marker)==1
    guards=read(folder/'guards.py');assert sha(guards)==m['artifacts'][str((folder/'guards.py').relative_to(ROOT))]
    def need(v,code):
        if not v:raise AssertionError(code)
    scope=types.ModuleType('parent_probe_source');scope.__dict__.update(C=m['config'],H=types.SimpleNamespace(need=need,sha=sha))
    exec(compile(guards,'<verified-parent-guards>','exec'),scope.__dict__)
    original=scope.candidate_probe_script()
    return payload.split(marker)[0],wrapper,base,original
def assemble(prefix,original,blobs):
    child=module(blobs['child.py'],'diagnostic_child',HERE/'child.py');script=child.instrument(original)
    tree=ast.parse(original);sources=ast.literal_eval(tree.body[4].value)
    text=prefix+b"\nDIAG=types.ModuleType('verified_import_diagnostic');DIAG.__dict__.update(JOB=JOB,PLAN=PLAN,GUARD=GUARD,HELPER=HELPER,need=PLAN.need)\n"
    config={'CHILD':script,'MODULES':tuple(sorted(sources)),'STDLIB':tuple(sorted(sys.stdlib_module_names)),'DEPENDENCIES':tuple(sorted(child.DEPENDENCIES)),'RELEASE':RELEASE,'PARENT_SHA':PARENT_SHA}
    text+=b'DIAG.__dict__.update('+repr(config).encode()+b')\n'
    text+=b'exec(compile('+repr(blobs['inspect.py']).encode()+b",'<verified-import-diagnostic>','exec'),DIAG.__dict__)\n"
    text+=b"report=DIAG.inspect();print(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']=='PASS' else 1)\n"
    ast.parse(text,feature_version=(3,9));assert len(text)<4*1024*1024
    return text,script
def emit(outputs):
    for p,raw in outputs.items():
        if os.path.lexists(p):assert read(p)==raw,'IMMUTABLE_DIAGNOSTIC_DRIFT'
    for p,raw in outputs.items():
        if not os.path.lexists(p):
            with p.open('xb') as f:f.write(raw)
def main():
    prefix,_,_,original=parent();blobs={n:read(HERE/n) for n in FILES};payload,child=assemble(prefix,original,blobs)
    artifacts={str((HERE/n).relative_to(ROOT)):sha(v) for n,v in blobs.items()};artifacts[TEST]=sha(read(ROOT/TEST))
    m={'version':1,'execution_authorized':False,'release':RELEASE,'parent_manifest':PARENT_SHA,'parent_preflight':PREFLIGHT_SHA,'original_child_sha256':sha(original),'child_sha256':sha(child),'payload_sha256':sha(payload),'artifacts':dict(sorted(artifacts.items()))}
    raw=json.dumps(m,sort_keys=True,indent=2).encode()+b'\n'
    emit({HERE/'inspect.payload.py':payload,HERE/'child.payload.py':child,HERE/'MANIFEST.json':raw})
    print(json.dumps({'manifest_sha256':sha(raw),'payload_sha256':sha(payload),'child_sha256':sha(child)},sort_keys=True))
if __name__=='__main__':main()
