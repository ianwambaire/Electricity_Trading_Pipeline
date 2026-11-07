"""Local immutable candidate assembly only. No install/remote execution."""
import ast
import base64
import hashlib
import json
from pathlib import Path
import shutil
import types

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
RELEASE='phase-operational-evidence-20261107-v4'
PRIVATE=ROOT/'data/backups/private-staging-releases'/RELEASE/'release'
PREFIX='deploy/staging/operational-evidence-release-v4/'
BASE='deploy/staging/forecast-consistency-release/preflight_readonly.py'
GUARD='deploy/staging/forecast-consistency-deployment/deploy.py'
WRAPPER='deploy/staging/forecast-consistency-release/run_preflight.py'
PRIOR='deploy/staging/forecast-publication/automation-continuation-v2/MANIFEST.json'
OLD='data/backups/private-staging-releases/phase-api-body-bound-20261102-v2/release'
# The predecessor mapping comes only from the verified completed transaction.
TRANSACTION='321a9d8a1d7a483d923b84bc1917b0a9'
GUARD_FUNCTIONS={'need','sha','read','digest','safe','target','inventory','production','idle_capacity','runtime'}
FILES=['run.py','build.py','baseline.py','BASELINE.json','prefect_reference.py','PREFECT-REFERENCE.json','plan.py','preflight.py','transaction.py','acceptance.py','REVIEW.md']
ARTIFACTS={PREFIX+n for n in FILES}|{BASE,GUARD,WRAPPER,PRIOR,'tests/test_operational_release_v4.py',
    'deploy/staging/operational-evidence/TOOLS.json','deploy/staging/operational-evidence/bootstrap.py',
    'deploy/staging/operational-evidence/powerflow-publish-operations','deploy/staging/operational-evidence/sudoers.rule',
    'src/shared/operational_evidence.py','src/shared/forecast_publication.py','src/shared/operational_evidence_producer.py','src/shared/operational_capture.py'}


def sha(raw):return hashlib.sha256(raw).hexdigest()
def encode(v):return json.dumps(v,sort_keys=True,indent=2).encode()+b'\n'

def subset(raw,functions,classes=(),skip_import=None):
    tree=ast.parse(raw)
    tree.body=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.Assign)) or
               isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in functions or isinstance(n,ast.ClassDef) and n.name in classes]
    if skip_import:tree.body=[n for n in tree.body if not isinstance(n,ast.ImportFrom) or n.module!=skip_import]
    return ast.unparse(ast.fix_missing_locations(tree)).encode()


def assemble(action,config,blobs,data):
    assert action in {'preflight','apply','rollback','accept'}
    cfg=json.loads(json.dumps(config))
    if action=='apply':
        for key,value in data.items():
            if 'copy_from' not in cfg['files'][key]:cfg['files'][key]['base64']=base64.b64encode(value).decode()
    text='import types,sys,json\n'
    for name,raw in [('BASE',blobs[BASE]),('GUARD',subset(blobs[GUARD],GUARD_FUNCTIONS,('Stop',))),('PLAN',blobs[PREFIX+'plan.py'])]:
        text+=name+"=types.ModuleType('verified_"+name+"')\n"
        if name=='GUARD':text+="GUARD.__dict__.update(BASE=BASE.__dict__,CONFIG={})\n"
        # Strip assignments depending on original transaction CONFIG/ID. Only
        # UNIT is used by this read-only guard subset.
        if name=='GUARD':
            t=ast.parse(raw);t.body=[n for n in t.body if (not isinstance(n,ast.Assign) or any(isinstance(x,ast.Name) and x.id=='UNIT' for x in n.targets)) and (not isinstance(n,ast.Import) or all(x.name in {'hashlib','json','os','re','stat'} for x in n.names))];raw=ast.unparse(t).encode()
        text+='exec(compile('+repr(raw)+",'<verified-"+name+">','exec'),"+name+".__dict__)\n"
    text+='CONFIG='+repr(cfg)+'\n'
    text+="PREFLIGHT=types.ModuleType('verified_preflight');PREFLIGHT.__dict__.update(BASE=BASE.__dict__,GUARD=GUARD.__dict__,PLAN=PLAN,CONFIG=CONFIG)\n"
    text+='exec(compile('+repr(blobs[PREFIX+'preflight.py'])+",'<verified-preflight>','exec'),PREFLIGHT.__dict__)\n"
    if action in {'apply','rollback'}:
        text+="JOB=types.ModuleType('verified_transaction');JOB.__dict__.update(BASE=BASE.__dict__,GUARD=GUARD.__dict__,PLAN=PLAN,CONFIG=CONFIG,PREFLIGHT=PREFLIGHT)\n"
        text+='exec(compile('+repr(blobs[PREFIX+'transaction.py'])+",'<verified-transaction>','exec'),JOB.__dict__)\n"
    if action=='accept':
        text+="package=types.ModuleType('shared');package.__path__=[];sys.modules['shared']=package\n"
        for name in ['forecast_publication','operational_evidence','operational_evidence_producer','operational_capture']:
            raw=blobs['src/shared/'+name+'.py']
            if name=='operational_capture':raw=subset(raw,{'query','directory','signature','capture_terminal'},('Source',),skip_import='operational_evidence_store')
            text+="module=types.ModuleType('shared."+name+"');module.__package__='shared';sys.modules[module.__name__]=module;setattr(package,'"+name+"',module)\n"
            text+='exec(compile('+repr(raw)+",'<verified-readonly-"+name+">','exec'),module.__dict__)\n"
        text+="ACCEPT=types.ModuleType('verified_accept');ACCEPT.__dict__.update(PREFLIGHT=PREFLIGHT,PLAN=PLAN,CONFIG=CONFIG,OP=sys.modules['shared.operational_evidence'],CAPTURE=sys.modules['shared.operational_capture'],PRODUCER=sys.modules['shared.operational_evidence_producer'],FORECAST=sys.modules['shared.forecast_publication'])\n"
        text+='exec(compile('+repr(blobs[PREFIX+'acceptance.py'])+",'<verified-acceptance>','exec'),ACCEPT.__dict__)\n"
    text+="try:\n"
    if action=='preflight':text+=" facts=PREFLIGHT.initial();report={'status':'PREFLIGHT_PASS','changed':False,'forecast_enabled':True,'operational_enabled':False,'root_access':'DEFERRED_UNTIL_PROVISION','baseline_sha256':PLAN.sha(json.dumps(facts,sort_keys=True).encode())}\n"
    elif action=='accept':text+=" report=ACCEPT.inspect()\n"
    else:text+=" report=JOB."+action+"()\n"
    text+="except Exception as error:\n category=str(error) if isinstance(error,(PLAN.Stop,GUARD.Stop)) else 'UNVERIFIED_HOST_OPERATION'\n if not isinstance(category,str) or not __import__('re').fullmatch('[A-Z0-9_]{1,80}',category):category='UNVERIFIED_HOST_OPERATION'\n report={'status':'BLOCKED','phase':getattr(globals().get('JOB'),'PHASE','READ_ONLY'),'changed':getattr(globals().get('JOB'),'CHANGED',False),'reason':category}\n if isinstance(error,OSError):report.update(reason='FILE_MISSING' if error.errno==2 else 'HOST_IO_ERROR',errno=error.errno,path_id=PREFLIGHT.path_id(error.filename))\n"
    text+="print(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status'] in {'PREFLIGHT_PASS','APPLIED','ROLLED_BACK','PASS'} else 1)\n"
    return text.encode()


def baseline_module():
    module=types.ModuleType('verified_historical_baseline');module.__file__=str(HERE/'baseline.py')
    exec(compile((HERE/'baseline.py').read_bytes(),'<verified-historical-baseline>','exec'),module.__dict__)
    return module


def prefect_reference():
    module=types.ModuleType('verified_prefect_reference');module.__file__=str(HERE/'prefect_reference.py')
    exec(compile((HERE/'prefect_reference.py').read_bytes(),'<verified-prefect-reference>','exec'),module.__dict__)
    return module.load()


def sources():
    raw=(ROOT/PRIOR).read_bytes();assert sha(raw)=='53fcc9323a5bacf81ffb5bf067048df3403be4eeca3b7a2dd6e4e6f770f9907a'
    prior=json.loads(raw)['config'];binding=baseline_module();baseline=binding.load()
    assert encode(baseline)==(HERE/'BASELINE.json').read_bytes()
    raw=(ROOT/OLD/'release-manifest.json').read_bytes();assert sha(raw)==binding.APPROVED_SHA
    old=binding.parse(raw)
    for rel,item in old['files'].items():
        assert binding.path_ok(rel)
        content=(ROOT/OLD/rel).read_bytes();assert len(content)==item['bytes'] and sha(content)==item['sha256']
    return prior,old,baseline


def release_snapshot():
    prior,old,baseline=sources()
    assert (PRIVATE/'static/index.html').is_file()
    target=PRIVATE/'api';assert not target.exists()
    for name,item in old['files'].items():
        if name.startswith('api/'):
            path=PRIVATE/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/OLD/name).read_bytes())
    for rel in ['src/api/app.py','src/api/market_data.py','src/api/current_operations.py','src/shared/operational_evidence.py','src/shared/operational_evidence_store.py']:
        path=target/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/rel).read_bytes())
    return prior,old,baseline


def build_config(initial=False):
    prior,old,baseline=release_snapshot() if initial else sources()
    old_static=baseline['static_inventory'];reference=prefect_reference()
    data={};paths={}
    for sub in ['api','static']:
        for path in sorted((PRIVATE/sub).rglob('*')):
            assert not path.is_symlink()
            if path.is_file():key=path.relative_to(PRIVATE).as_posix();data[key]=path.read_bytes();paths[key]=str(path.relative_to(ROOT))
    helper=json.loads((ROOT/'deploy/staging/operational-evidence/TOOLS.json').read_bytes())
    for name,digest in helper.items():
        path=ROOT/('deploy/staging/operational-evidence/bootstrap.py' if name=='bootstrap.py' else 'src/'+name)
        assert sha(path.read_bytes())==digest;data['helper/'+name]=path.read_bytes();paths['helper/'+name]=str(path.relative_to(ROOT))
    for name in ['TOOLS.json']:
        path=ROOT/'deploy/staging/operational-evidence'/name;data['helper/'+name]=path.read_bytes();paths['helper/'+name]=str(path.relative_to(ROOT))
    worker={'src/scheduled_pipeline.py':{'before':prior['files']['pipeline']['sha256']},'src/shared/operational_terminal.py':{'before':None},'src/shared/operational_evidence.py':{'before':None}}
    for rel in worker:data['worker/'+rel]=(ROOT/rel).read_bytes();paths['worker/'+rel]=rel
    for key,name in [('launcher','powerflow-publish-operations'),('sudoers','sudoers.rule')]:
        path=ROOT/'deploy/staging/operational-evidence'/name;data[key]=path.read_bytes();paths[key]=str(path.relative_to(ROOT))
    env=(ROOT/OLD/'proposals/api.env.example').read_bytes();env+=b'' if env.endswith(b'\n') else b'\n';env+=b'POWERFLOW_FORECAST_PUBLICATION_ROOT=/srv/powerflow/forecast-publications\n'
    api_old={n[4:]:v['sha256'] for n,v in old['files'].items() if n.startswith('api/')}
    config={'transaction':'321a9d8a1d7a483d923b84bc1917b0a9','release':RELEASE,'old_backend':'/opt/powerflow/releases/phase-api-body-bound-20261102-v2','old_static':'/var/www/powerflow-staging/releases/phase-api-body-bound-20261102-v2',
            'old_api':api_old,'old_static_inventory':old_static,'worker':worker,'env_before':sha(env),'env_after':sha(env+b'POWERFLOW_OPERATIONAL_PUBLICATION_ROOT=/srv/powerflow/operational-publications\n'),
            'first_tools':prior['original_tools'],'first_packet':prior['original_packet'],'existing_forecast_tools':prior['installed_tools'],'existing_forecast_entrypoints':{'/usr/local/sbin/powerflow-publish-next24':prior['files']['launcher']['sha256'],'/etc/sudoers.d/powerflow-publish-next24':prior['files']['sudoers']['sha256']},
            'historical_record_sha256':baseline['historical_record_sha256'],'retained_assets':baseline['retained_assets'],
            'worker_sdk':{'workers/base.py':reference['files']['prefect/workers/base.py'],'flow_engine.py':reference['files']['prefect/flow_engine.py']},
            'prefect_version':reference['version'],'prefect_metadata_sha256':reference['files']['prefect-3.7.5.dist-info/METADATA'],'prefect_reference_wheel_sha256':reference['wheel_sha256'],
            'frozen':{'next24h_model.joblib':'69a3fa10f45c18c4733b3f8e12792e36ec9b209b7afd5e94a9932315e4dde0ed','next24h_feature_contract.joblib':'1d6554e469a869613dd91d820b0537b4562321ea69e8827ecb83137950078a88'},
            'sudoers_hex':data['sudoers'].hex(),'files':{},'total_bytes':sum(map(len,data.values()))}
    # old_static path and inventory are separate fields, avoiding a scope collision.
    for key,raw in data.items():
        destination=('/opt/powerflow/releases/'+RELEASE+'/'+key[4:] if key.startswith('api/') else '/var/www/powerflow-staging/releases/'+RELEASE+'/'+key[7:] if key.startswith('static/') else '/opt/powerflow/operational-evidence-v1/'+key[7:] if key.startswith('helper/') else '/home/ec2-user/Electricity_Trading_Pipeline/'+key[7:] if key.startswith('worker/') else '/usr/local/sbin/powerflow-publish-operations' if key=='launcher' else '/etc/sudoers.d/powerflow-publish-operations')
        config['files'][key]={'source':paths[key],'destination':destination,'bytes':len(raw),'sha256':sha(raw),'uid':1000 if key.startswith('worker/') else 0,'gid':1000 if key.startswith('worker/') else 0,'mode':0o755 if key=='launcher' else 0o440 if key=='sudoers' else 0o600 if key.startswith('helper/') else 0o644}
    # Retain every previously served immutable hashed chunk. Missing local bytes
    # are NOT fabricated: copy only exact historical hashes from the existing tree.
    import re
    for rel,digest in sorted(old_static.items()):
        if not re.fullmatch(r'assets/[A-Za-z0-9._-]+\.(js|css|woff2)',rel):continue
        key='static/'+rel;copy_from=config['old_static']+'/'+rel
        if key in config['files']:
            assert config['files'][key]['sha256']==digest,'HASHED_ASSET_COLLISION'
            config['files'][key]['copy_from']=copy_from
        else:
            known=old['files'].get(key)
            config['files'][key]={'source':'historical-retained-asset:'+rel,'destination':'/var/www/powerflow-staging/releases/'+RELEASE+'/'+rel,'copy_from':copy_from,
                                  'sha256':digest,'bytes':known['bytes'] if known else None,'max_bytes':2000000,'uid':0,'gid':0,'mode':0o644}
    config['files']=dict(sorted(config['files'].items()))
    config['total_bytes']=sum(v['bytes'] if v['bytes'] is not None else v['max_bytes'] for v in config['files'].values())
    baseline_module().validate_copies(config)
    return config,data


def main():
    import sys
    config,data=build_config('--initial' in sys.argv)
    blobs={name:(ROOT/name).read_bytes() for name in ARTIFACTS}
    manifest={'version':1,'execution_authorized':False,'release':RELEASE,'transaction':config['transaction'],'config':config,
              'artifacts':{name:{'sha256':sha(raw),'bytes':len(raw)} for name,raw in blobs.items()},'payloads':{}}
    for action in ['preflight','apply','rollback','accept']:
        payload=assemble(action,config,blobs,data);assert len(payload)<4*1024*1024;compile(payload,'<offline-payload>','exec')
        (HERE/(action+'.payload.py')).write_bytes(payload);manifest['payloads'][action]={'sha256':sha(payload),'bytes':len(payload)}
    (HERE/'MANIFEST.json').write_bytes(encode(manifest))
    print(json.dumps({'manifest_sha256':sha((HERE/'MANIFEST.json').read_bytes()),'files':len(config['files']),'payloads':manifest['payloads']},sort_keys=True))

if __name__=='__main__':main()
