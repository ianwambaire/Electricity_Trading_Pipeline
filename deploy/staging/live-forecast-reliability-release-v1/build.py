"""Local immutable API/static assembly; no remote execution or authorization."""
import ast
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import types

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-live-forecast-reliability-20261107-v1'
TRANSACTION='de174d324c9b4b67be5198e44d988322'
HELPER_SHA='c677691a8e75e2ae09fb9eea8f60aefe1b71fcdc5e289109ed649b4b1f3b4262'
V5_SHA='cdd828defc52ea258852b88aa852d1d470ca915d098021d6ff8fd2be9b05223b'
FRONT=ROOT/'data/backups/private-staging-releases/live-forecast-reliability-20261107-v1/frontend'
FILES={'build.py','run.py','guards.py','transaction.py','acceptance.py','REVIEW.md'}
CHANGED={'src/api/app.py','src/api/forecast_source.py','src/api/operations_summary.py','src/shared/forecast_availability.py'}
TESTS={'tests/test_live_forecast_reliability_release.py','tests/test_live_forecast_reliability.py','tests/test_forecast_source_consistency.py','tests/test_inference_evidence.py','frontend/tests/liveForecastReliability.test.tsx'}
SOURCE={'frontend/src/api/contracts.ts','frontend/src/api/forecastState.ts','frontend/src/api/publicationState.ts','frontend/src/api/forecastPresentation.ts','frontend/src/api/operationalForecastState.ts','frontend/src/api/restoration.ts','frontend/src/components/data/ForecastChart.tsx','frontend/src/components/data/ForecastSummary.tsx','frontend/src/components/data/OperationalSummary.tsx','frontend/src/hooks/useClock.ts','frontend/src/pages/PipelinePage.tsx','frontend/docs/live-forecast-reliability.md'}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encode(v):return json.dumps(v,sort_keys=True,indent=2).encode()+b'\n'
def read(p):
    with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode) and s.st_size<=4*1024*1024
        raw=f.read(4*1024*1024+1);assert len(raw)==s.st_size;return raw
def module(raw,name,file):
    m=types.ModuleType(name);m.__file__=str(file);exec(compile(raw,'<verified-'+name+'>','exec'),m.__dict__);return m
def baseline():
    folder=HERE.parent/'operational-capture-helper-release-v2';raw=read(folder/'MANIFEST.json');assert sha(raw)==HELPER_SHA
    meta=json.loads(raw);runner=read(folder/'run.py');assert sha(runner)==meta['artifacts'][str((folder/'run.py').relative_to(ROOT))]
    h=module(runner,'reliability_baseline',folder/'run.py');payload,wrapper,base=h.verify(HELPER_SHA,'preflight')
    marker=b'try:\n report=HELPER.preflight_report()';assert payload.count(marker)==1
    v5raw=read(HERE.parent/'operational-evidence-release-v5/MANIFEST.json');assert sha(v5raw)==V5_SHA
    return payload.split(marker)[0],wrapper,base,json.loads(v5raw),meta
def artifact_paths():
    result={str((HERE/n).relative_to(ROOT)) for n in FILES}|CHANGED|TESTS|SOURCE
    for folder in ['frontend/src','frontend/build','frontend/public']:
        for p in (ROOT/folder).rglob('*'):
            assert not p.is_symlink()
            if p.is_file():result.add(p.relative_to(ROOT).as_posix())
    result.update({'frontend/package.json','frontend/package-lock.json','frontend/vite.config.ts','frontend/tsconfig.json','frontend/tsconfig.app.json','frontend/tsconfig.node.json','frontend/index.html','frontend/scripts/release-build.mjs','frontend/scripts/check-build.mjs'})
    return result
def safe_rel(name):return type(name)is str and bool(name) and not name.startswith('/') and all(p not in ('','.','..') for p in name.split('/')) and '\\'not in name
def config(v5):
    old=v5['config'];files={};api_raw={}
    for key,item in old['files'].items():
        if not key.startswith('api/'):continue
        raw=read(ROOT/item['source']);assert len(raw)==item['bytes'] and sha(raw)==item['sha256']
        rel=key[4:];api_raw[rel]=raw
    for rel in CHANGED:api_raw[rel]=read(ROOT/rel)
    for rel,raw in sorted(api_raw.items()):
        assert safe_rel(rel)
        files['api/'+rel]={'sha256':sha(raw),'bytes':len(raw),'base64':base64.b64encode(raw).decode()}
    assert FRONT.is_dir() and FRONT.resolve()==FRONT and not FRONT.is_symlink(),'FRONTEND_SOURCE_PATH'
    for p in sorted(FRONT.rglob('*')):
        assert not p.is_symlink()
        if p.is_file():
            rel=p.relative_to(FRONT).as_posix();assert safe_rel(rel)
            assert rel in {'index.html','build-config.json','favicon.svg','icons.svg','fonts/SourceSans3VF-Upright.woff2','fonts/SourceSans3-LICENSE.md'} or re.fullmatch(r'assets/[A-Za-z0-9._-]+\.(js|css|woff2|png|svg)',rel),'STATIC_FILE_SCOPE'
            raw=read(p);files['static/'+rel]={'sha256':sha(raw),'bytes':len(raw),'base64':base64.b64encode(raw).decode()}
    assert 'static/index.html'in files and sum(k.startswith('static/') for k in files)<=80
    for rel in ['favicon.svg','icons.svg','fonts/SourceSans3VF-Upright.woff2','fonts/SourceSans3-LICENSE.md']:
        assert files['static/'+rel]['sha256']==old['files']['static/'+rel]['sha256'],'PUBLIC_ASSET_DRIFT'
    actual=json.loads(base64.b64decode(files['static/build-config.json']['base64']))
    expected=json.loads(read(ROOT/old['files']['static/build-config.json']['source']))
    assert actual==expected and actual['releaseEligible']is True and actual['origin']=='https://staging.powerflowenergy.dev','AUTH_BUILD_DRIFT'
    # Keep every previously served hashed chunk; no guessed archives or host hashes.
    for key,item in old['files'].items():
        if key.startswith('static/assets/'):
            if key in files:assert files[key]['sha256']==item['sha256'],'HASHED_ASSET_COLLISION'
            else:files[key]={'sha256':item['sha256'],'bytes':item['bytes'],'max_bytes':item.get('max_bytes',2000000),'copy_from':item['destination']}
    c={'release':RELEASE,'transaction':TRANSACTION,'api':'/opt/powerflow/releases/'+RELEASE,'static':'/var/www/powerflow-staging/releases/'+RELEASE,'control':'/var/lib/powerflow-staging/forecast-reliability-'+TRANSACTION,'files':dict(sorted(files.items())),'changed_api':sorted(CHANGED),'helper_manifest':HELPER_SHA,'v5_manifest':V5_SHA}
    c['binding']=sha(encode(c));return c
def readonly_helper(raw):
    tree=ast.parse(raw);names={'validate_record','load_record','verified_backups','new_tree'}
    tree.body=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom)) or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PHASES' for t in n.targets) or isinstance(n,ast.FunctionDef) and n.name in names]
    assert {n.name for n in tree.body if isinstance(n,ast.FunctionDef)}==names
    return ast.unparse(tree).encode()
def assemble(action,prefix,c,blobs,helper_meta):
    assert action in {'preflight','apply','rollback','accept'}
    hp=HERE.parent/'operational-capture-helper-release-v2/transaction.py';raw=read(hp)
    assert sha(raw)==helper_meta['artifacts'][str(hp.relative_to(ROOT))]
    text=prefix+b"\nHVIEW=types.ModuleType('verified_helper_record');HVIEW.__dict__.update(HELPER.__dict__)\n"
    text+=b'exec(compile('+repr(readonly_helper(raw)).encode()+b",'<verified-helper-record>','exec'),HVIEW.__dict__)\n"
    text+=b"JOB=types.ModuleType('verified_forecast_reliability');JOB.__dict__.update(H=HELPER,P=PREFLIGHT,G=GUARD.__dict__,B=BASE.__dict__,HVIEW=HVIEW,OLD=CONFIG)\nJOB.C="+repr(c).encode()+b'\n'
    text+=b'exec(compile('+repr(blobs['guards.py']).encode()+b",'<verified-reliability-guards>','exec'),JOB.__dict__)\n"
    if action in {'apply','rollback'}:text+=b'exec(compile('+repr(blobs['transaction.py']).encode()+b",'<verified-reliability-transaction>','exec'),JOB.__dict__)\n"
    if action=='accept':
        tree=ast.parse(blobs['transaction.py']);names={'record_valid','load_record','verified_backups','tree_state','old_trees'}
        tree.body=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom)) or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PHASES' for t in n.targets) or isinstance(n,ast.FunctionDef) and n.name in names]
        assert {n.name for n in tree.body if isinstance(n,ast.FunctionDef)}==names
        text+=b'exec(compile('+repr(ast.unparse(tree).encode()).encode()+b",'<verified-reliability-record>','exec'),JOB.__dict__)\n"
    if action in {'apply','rollback','accept'}:text+=b'exec(compile('+repr(blobs['acceptance.py']).encode()+b",'<verified-reliability-acceptance>','exec'),JOB.__dict__)\n"
    call={'preflight':'preflight_report','apply':'apply','rollback':'rollback','accept':'accept_report'}[action]
    text+=b"try:\n report=JOB."+call.encode()+b"()\nexcept Exception as error:\n reason=str(error) if isinstance(error,(PLAN.Stop,GUARD.Stop,HELPER.OP.InvalidEvidence)) else 'UNVERIFIED_HOST_OPERATION'\n if not __import__('re').fullmatch('[A-Z0-9_]{1,80}',reason):reason='UNVERIFIED_HOST_OPERATION'\n report={'status':'FAILED' if JOB.CHANGED else 'BLOCKED','phase':JOB.PHASE,'changed':JOB.CHANGED,'reason':reason}\n trace=error.__traceback__\n while trace:\n  if trace.tb_frame.f_code.co_filename.startswith('<verified-reliability-'):report.update(operation=trace.tb_frame.f_code.co_name,line=trace.tb_lineno)\n  trace=trace.tb_next\nprint(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']in {'PREFLIGHT_PASS','APPLIED','ROLLED_BACK','PASS','PARTIAL'} else 1)\n"
    ast.parse(text,feature_version=(3,9));assert len(text)<4*1024*1024;return text
def emit(outputs):
    for p,raw in outputs.items():
        if os.path.lexists(p):assert read(p)==raw,'IMMUTABLE_RELEASE_DRIFT'
    for p,raw in outputs.items():
        if not os.path.lexists(p):
            with p.open('xb') as f:f.write(raw)
def main():
    prefix,_,_,v5,helper=baseline();c=config(v5);blobs={n:read(HERE/n) for n in FILES}
    m={'version':1,'execution_authorized':False,'release':RELEASE,'transaction':TRANSACTION,'config':c,'artifacts':{p:sha(read(ROOT/p)) for p in sorted(artifact_paths())},'payloads':{}}
    outputs={}
    for action in ['preflight','apply','rollback','accept']:
        raw=assemble(action,prefix,c,blobs,helper);outputs[HERE/(action+'.payload.py')]=raw;m['payloads'][action]={'sha256':sha(raw),'bytes':len(raw)}
    raw=encode(m);outputs[HERE/'MANIFEST.json']=raw;emit(outputs)
    print(json.dumps({'manifest_sha256':sha(raw),'release':RELEASE,'transaction':TRANSACTION,'files':len(c['files'])},sort_keys=True))
if __name__=='__main__':main()
