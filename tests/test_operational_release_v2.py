"""Local release preparation only. Synthetic policy + isolated transaction fixtures."""
import ast
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'deploy/staging/operational-evidence-release-v2'


def load(name,extra=None):
    import types
    m=types.ModuleType('offline_operational_'+name);m.__file__=str(FOLDER/(name+'.py'))
    if extra:m.__dict__.update(extra)
    exec(compile((FOLDER/(name+'.py')).read_bytes(),'<offline-'+name+'>','exec'),m.__dict__)
    return m


@pytest.fixture(autouse=True)
def no_remote(monkeypatch):
    import socket
    monkeypatch.setattr(socket,'create_connection',lambda *a,**k:pytest.fail('Unexpected network'))
    # Runner tests deliberately tighten umask. Keep their process-global change
    # from altering ownership/permission fixture setup in subsequent tests.
    previous=os.umask(0o022)
    try:yield
    finally:os.umask(previous)


def test_policy_preserves_forecast_flag_and_rejects_other_overrides():
    p=load('plan');old={'env':{p.FORECAST_FLAG:'true'}};new=p.variables(old)
    assert new=={'env':{p.FORECAST_FLAG:'true',p.FLAG:'true'}} and p.FLAG not in old['env']
    for bad in [{'env':{}},{'env':{p.FORECAST_FLAG:'false'}},{'env':{p.FORECAST_FLAG:'true',p.FLAG:'false'}}, {'command':'arbitrary'}, {'env':{p.FORECAST_FLAG:'true','AWS_SECRET_ACCESS_KEY':'private'}}, {'unsupported':True}]:
        with pytest.raises(p.Stop):p.variables(bad)
    raw=b'PUBLIC_SETTING=fixture\n';expected=p.sha(raw)
    assert p.environment(raw,expected)==raw+b'POWERFLOW_OPERATIONAL_PUBLICATION_ROOT=/srv/powerflow/operational-publications\n'
    with pytest.raises(p.Stop):p.environment(raw,'0'*64)
    configured=raw+b'POWERFLOW_OPERATIONAL_PUBLICATION_ROOT=/wrong\n'
    with pytest.raises(p.Stop):p.environment(configured,p.sha(configured))


def test_readonly_preflight_and_payload_boundaries():
    b=load('build');tree=ast.parse((FOLDER/'preflight.py').read_bytes())
    inspected=ast.Module(body=[n for n in tree.body if not isinstance(n,ast.FunctionDef) or n.name!='path_id'],type_ignores=[])
    calls={getattr(n.func,'attr',getattr(n.func,'id','')) for n in ast.walk(inspected) if isinstance(n,ast.Call)}
    assert not calls&{'mkdir','chmod','chown','unlink','replace','patch','restart','write','publish','publish_terminal'}
    guard=b.subset((ROOT/b.GUARD).read_bytes(),b.GUARD_FUNCTIONS,('Stop',))
    names={n.name for n in ast.parse(guard).body if isinstance(n,ast.FunctionDef)}
    assert names==b.GUARD_FUNCTIONS and not names&{'apply','rollback','run','create','atomic_file'}
    for name in ['plan','preflight','transaction','acceptance','run','build']:
        ast.parse((FOLDER/(name+'.py')).read_bytes(),feature_version=(3,9))
    cfg={};blobs={n:(ROOT/n).read_bytes() for n in b.ARTIFACTS}
    payload=b.assemble('preflight',cfg,blobs,{})
    assert b'<verified-transaction>' not in payload and b'base64' not in payload.split(b'CONFIG=',1)[-1].split(b'PREFLIGHT=',1)[0]
    assert b'JOB.apply' not in payload and b'JOB.rollback' not in payload


def test_sudo_and_readonly_process_restrictions():
    plan=load('plan');calls=[]
    base={'bounded_run':lambda *a,**k:(calls.append(a[0]) or {'returncode':0,'failure':None,'stdout':b''})}
    p=load('preflight',dict(BASE=base,GUARD={},PLAN=plan,CONFIG={}))
    p.process(['/usr/sbin/visudo','-cf','-'],b'fixture')
    with pytest.raises(plan.Stop):p.process(['/usr/bin/systemctl','restart','anything'])
    assert calls==[['/usr/sbin/visudo','-cf','-']]
    helper=ROOT/'deploy/staging/operational-evidence'
    rule=(helper/'sudoers.rule').read_text();launcher=(helper/'powerflow-publish-operations').read_bytes()
    assert 'sha256:'+plan.sha(launcher) in rule and 'NOSETENV' in rule and '^--flow-run ' in rule and ' --state ' in rule and rule.rstrip().endswith('$')
    assert 'ALL=(root) NOPASSWD: ALL' not in rule


@pytest.fixture
def transaction(tmp_path,monkeypatch):
    plan=load('plan');top=tmp_path.resolve();prod=top/'prod';prod.mkdir();(prod/'src/shared').mkdir(parents=True)
    old_api=top/'old-api';old_api.mkdir();(old_api/'file.py').write_bytes(b'old api')
    venv=top/'venv';venv.mkdir();(old_api/'.venv-api').symlink_to(venv)
    old_static=top/'old-static';old_static.mkdir();(old_static/'index.html').write_bytes(b'old static')
    backend=top/'backend';backend.symlink_to(old_api);web=top/'web';web.symlink_to(old_static)
    pipeline=prod/'src/scheduled_pipeline.py';pipeline.write_bytes(b'old pipeline')
    env=top/'api.env';env.write_bytes(b'PUBLIC=fixture\n');env.chmod(0o600)
    forecast=top/'forecast';forecast.write_bytes(b'unchanged forecast sentinel')
    old_vars={'env':{plan.FORECAST_FLAG:'true'}};state={'vars':copy.deepcopy(old_vars),'restarts':0}
    data={'worker/src/scheduled_pipeline.py':b'new pipeline','worker/src/shared/operational_terminal.py':b'new terminal', 'api/file.py':b'new api','static/index.html':b'new static','helper/bootstrap.py':b'fixture helper','launcher':b'fixture launcher','sudoers':b'fixture sudoers'}
    config={'transaction':plan.TRANSACTION,'release':plan.RELEASE,'old_backend':str(old_api),'old_static':str(old_static),'old_api':{'file.py':plan.sha(b'old api')},'old_static_inventory':{'index.html':plan.sha(b'old static')},'worker':{'src/scheduled_pipeline.py':{'before':plan.sha(b'old pipeline')},'src/shared/operational_terminal.py':{'before':None}},'env_before':plan.sha(env.read_bytes()),'env_after':plan.sha(plan.environment(env.read_bytes(),plan.sha(env.read_bytes()))),'files':{k:{'base64':base64.b64encode(v).decode(),'sha256':plan.sha(v),'bytes':len(v)} for k,v in data.items()}}
    base={'request':lambda port,path,**k:(200,(web.resolve()/'index.html').read_bytes() if path=='/' else b'{}'), 'canonical':lambda p,parent:p.resolve()}
    p=load('preflight',dict(BASE=base,GUARD={},PLAN=plan,CONFIG=config))
    for name,path in {'PRODUCTION':prod,'OLD_API':old_api,'OLD_STATIC':old_static,'API':top/'new-api','STATIC':top/'new-static','TOOLS':top/'new-tools','STORE':top/'store','CONTROL':top/'transaction','LAUNCHER':top/'launcher','RULE':top/'sudoers','ENV':env,'BACKEND_LINK':backend,'STATIC_LINK':web}.items():setattr(p,name,path)
    writes=[]
    def safe(path,owners=(0,)):
        path=Path(path);assert str(path).startswith(str(top))
        assert not path.is_symlink()
    def snap(path,uid=0,gid=0,mode=0o644):
        path=Path(path);assert str(path).startswith(str(top));assert not path.is_symlink() and path.is_file()
        assert path.stat().st_mode&0o777==mode
        raw=path.read_bytes();return dict(sha256=plan.sha(raw),uid=uid,gid=gid,mode=mode,bytes=len(raw)),raw
    p.safe=safe;p.snap=snap;p.read=lambda path,limit=2000000:Path(path).read_bytes()
    p.deployment=lambda:{'id':plan.DEPLOYMENT,'job_variables':copy.deepcopy(state['vars'])}
    p.pool=lambda:'pool-sha';p.baseline_installation=lambda:{'fixture':'runtime'};p.idle=lambda extra:None;p.process=lambda *a,**k:None;p.candidate_environment=lambda *a,**k:None
    p.forecast_fingerprint=lambda:{'fixture':plan.sha(forecast.read_bytes())}
    p.forecast_configuration=lambda:None
    def inventory(root):return {x.relative_to(root).as_posix():plan.sha(x.read_bytes()) for x in root.rglob('*') if x.is_file() and not x.is_symlink()}
    guard={'production':lambda:'production-sha','runtime':lambda expected:None,'inventory':inventory}
    p.GUARD=guard
    projection=plan.stable_projection(p.deployment())
    before={'backups':{'api_env':snap(env,0,0,0o600)[0],'src/scheduled_pipeline.py':snap(pipeline,1000,1000)[0],'src/shared/operational_terminal.py':None},'projection':projection,'old_variables':old_vars,'new_variables':plan.variables(old_vars),'venv':str(venv),'production':'production-sha','forecast':p.forecast_fingerprint(),'runtime':p.baseline_installation(),'pool_sha256':p.pool()}
    p.initial=lambda:copy.deepcopy(before)
    def http(path):
        if path=='/api/forecast/next24':return 503,{'cache-control':'no-store'},{'detail':{'code':'FORECAST_WITHHELD'}}
        if path=='/api/admin/operations/current':return 401,{},{}
        return 200,{'cache-control':'no-store'},{'status':'MISSING','current_execution':None}
    p.http=http
    tx=load('transaction',dict(BASE=base,GUARD=guard,PLAN=plan,CONFIG=config,PREFLIGHT=p))
    monkeypatch.setattr(tx.os,'chown',lambda *a:None);monkeypatch.setattr(tx.os,'fchown',lambda *a:None)
    original_write=tx.write
    def tracked(path,*a,**k):writes.append(Path(path));return original_write(path,*a,**k)
    tx.write=tracked
    tx.patch=lambda values:state.update(vars=copy.deepcopy(values))
    tx.restart=lambda:state.update(restarts=state['restarts']+1)
    tx.effective_access=lambda:None
    def installed(record):
        assert plan.FLAG not in state['vars']['env']
        for root,prefix in [(p.API,'api/'),(p.STATIC,'static/')]:p.assert_files(root,{k[len(prefix):]:v['sha256'] for k,v in config['files'].items() if k.startswith(prefix)})
        assert (p.STORE/'contract').read_bytes()==b'powerflow-operational-evidence-v1\n'
    tx.installed=installed
    return tx,p,config,state,before,writes,forecast


def test_apply_then_independent_rollback_restores_exact_state(transaction):
    tx,p,cfg,state,before,writes,forecast=transaction
    assert tx.apply()['status']=='APPLIED'
    assert state['vars']['env'][tx.PLAN.FLAG]=='true' and state['vars']['env'][tx.PLAN.FORECAST_FLAG]=='true'
    assert p.BACKEND_LINK.resolve()==p.API and p.STATIC_LINK.resolve()==p.STATIC
    assert tx.rollback()['status']=='ROLLED_BACK'
    assert state['vars']==before['old_variables']
    assert (p.PRODUCTION/'src/scheduled_pipeline.py').read_bytes()==b'old pipeline'
    assert not(p.PRODUCTION/'src/shared/operational_terminal.py').exists()
    assert p.ENV.read_bytes()==b'PUBLIC=fixture\n' and p.BACKEND_LINK.resolve()==p.OLD_API and p.STATIC_LINK.resolve()==p.OLD_STATIC
    assert not p.LAUNCHER.exists() and not p.RULE.exists() and p.STORE.is_dir() and p.TOOLS.is_dir()
    assert forecast.read_bytes()==b'unchanged forecast sentinel' and forecast not in writes


@pytest.mark.parametrize('failure',['install','pointers','activated'])
def test_partial_apply_never_auto_rolls_back_and_explicit_rollback_is_bounded(transaction,monkeypatch,failure):
    tx,p,cfg,state,before,writes,forecast=transaction
    if failure=='install':monkeypatch.setattr(tx,'installed',lambda _:tx.need(False,'INSTALL_FAILURE'))
    else:
        acceptance=tx.acceptance;calls=[]
        def fail(record):
            calls.append(1)
            if len(calls)==(1 if failure=='pointers' else 2):tx.need(False,'ACCEPTANCE_FAILURE')
            return acceptance(record)
        monkeypatch.setattr(tx,'acceptance',fail)
    with pytest.raises(tx.PLAN.Stop):tx.apply()
    assert tx.CHANGED and (p.CONTROL/'record.json').is_file()
    assert (tx.PLAN.FLAG in state['vars']['env'])==(failure=='activated')
    assert tx.rollback()['status']=='ROLLED_BACK'
    assert forecast.read_bytes()==b'unchanged forecast sentinel'


def test_drift_and_corrupt_backup_block_rollback_before_any_write(transaction):
    tx,p,cfg,state,before,writes,forecast=transaction;tx.apply()
    (p.PRODUCTION/'src/scheduled_pipeline.py').write_bytes(b'external drift')
    count=len(writes)
    with pytest.raises(tx.PLAN.Stop,match='ROLLBACK_FILE_DRIFT'):tx.rollback()
    assert len(writes)==count and state['vars']['env'][tx.PLAN.FLAG]=='true'


def test_preflight_failure_has_no_mutation(transaction,monkeypatch):
    tx,p,cfg,state,before,writes,forecast=transaction
    monkeypatch.setattr(p,'initial',lambda:tx.need(False,'HOST_DRIFT'))
    with pytest.raises(tx.PLAN.Stop):tx.apply()
    assert not tx.CHANGED and not writes and not p.CONTROL.exists()


def test_backup_interruption_does_not_change_application(transaction,monkeypatch):
    tx,p,cfg,state,before,writes,forecast=transaction
    original=tx.write
    def fail(path,*a,**k):
        if str(path).endswith('.independent'):raise OSError('fixture interrupted backup')
        return original(path,*a,**k)
    monkeypatch.setattr(tx,'write',fail)
    with pytest.raises(OSError):tx.apply()
    assert tx.PHASE=='BACKUP' and state['vars']==before['old_variables']
    assert (p.PRODUCTION/'src/scheduled_pipeline.py').read_bytes()==b'old pipeline' and p.BACKEND_LINK.resolve()==p.OLD_API
    assert not p.API.exists()


def test_manifest_integrity_and_payload_assembly():
    b=load('build');r=load('run');manifest=(FOLDER/'MANIFEST.json').read_bytes();m=json.loads(manifest)
    assert m['execution_authorized']is False
    for action in ['preflight','apply','rollback','accept']:
        payload,_,_=r.verify(r.sha(manifest),action)
        assert r.sha(payload)==m['payloads'][action]['sha256']
    with pytest.raises(ValueError,match='manifest_hash'):r.verify('0'*64,'apply')
    assert m['config']['env_before']=='688ec4fe56a59252f629a671c9adf17011762001b33f19a703b63eb346aaa926'
    assert m['config']['existing_forecast_tools']['shared/forecast_publication.py']==r.sha((ROOT/'src/shared/forecast_publication.py').read_bytes())


def test_staged_api_import_and_current_routes_are_compatible(tmp_path):
    staged=ROOT/'data/backups/private-staging-releases/phase-operational-evidence-20261107-v2/release/api/src'
    code='''import sys,tempfile,pathlib
sys.path.insert(0,sys.argv[1])
from api.app import APISettings,create_app
from fastapi.testclient import TestClient
assert str(pathlib.Path(__import__('api.app',fromlist=['app']).__file__)).startswith(sys.argv[1])
with tempfile.TemporaryDirectory() as folder:
 client=TestClient(create_app(APISettings.from_root(pathlib.Path(folder))))
 for path in ('/operations/current','/pipeline/current'):
  response=client.get(path);assert response.status_code==200 and response.json()['status']=='MISSING' and response.json()['current_execution'] is None
 assert client.get('/admin/operations/current').status_code==401
'''
    result=subprocess.run([str(ROOT/'venv/bin/python'),'-I','-B','-c',code,str(staged)],capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr.decode()[-1000:]


def test_rollback_preserves_legitimate_new_natural_forecast(transaction):
    tx,p,cfg,state,before,writes,forecast=transaction;tx.apply()
    forecast.write_bytes(b'new authentic natural publication fixture')
    assert tx.rollback()['status']=='ROLLED_BACK'
    assert forecast.read_bytes()==b'new authentic natural publication fixture'
    assert state['vars']['env'][tx.PLAN.FORECAST_FLAG]=='true'


@pytest.mark.parametrize('kind',['missing','modified'])
def test_local_dependency_drift_stops_before_remote(kind,monkeypatch):
    r=load('run');manifest=(FOLDER/'MANIFEST.json').read_bytes();original=r.read
    def changed(path,*a,**kw):
        if Path(path)==FOLDER/'preflight.py':
            if kind=='missing':raise FileNotFoundError('fixture missing')
            return original(path,*a,**kw)+b'\n# fixture drift'
        return original(path,*a,**kw)
    monkeypatch.setattr(r,'read',changed)
    with pytest.raises((ValueError,FileNotFoundError)):r.verify(r.sha(manifest),'preflight')


def test_write_and_pointer_scope_are_closed(transaction):
    tx,p,cfg,state,before,writes,forecast=transaction
    with pytest.raises(tx.PLAN.Stop,match='WRITE_SCOPE'):tx.write(forecast,b'forbidden')
    with pytest.raises(tx.PLAN.Stop,match='POINTER_SCOPE'):tx.pointer(p.BACKEND_LINK,p.STORE)
    assert forecast.read_bytes()==b'unchanged forecast sentinel'


def test_permission_violation_is_rejected_with_fixed_category(tmp_path,monkeypatch):
    plan=load('plan');p=load('preflight',dict(PLAN=plan,BASE={},GUARD={},CONFIG={}))
    file=tmp_path.resolve()/'bad';file.write_bytes(b'fixture');file.chmod(0o666)
    monkeypatch.setattr(p,'safe',lambda *a,**k:None)
    with pytest.raises(plan.Stop,match='FILE_METADATA'):p.snap(file,os.getuid(),os.getgid(),0o644)


def test_candidate_environment_is_confirmed_in_process_without_exposing_other_values(monkeypatch):
    plan=load('plan');raw=b'POWERFLOW_API_DATA_ROOT=/srv/powerflow/published\0POWERFLOW_FORECAST_PUBLICATION_ROOT=/srv/powerflow/forecast-publications\0PRIVATE_TOKEN=not-retained\0'
    service={'EnvironmentFiles':'/etc/powerflow/react-api.env (ignore_errors=no)','MainPID':'123'}
    p=load('preflight',dict(PLAN=plan,BASE={'services':lambda:{plan.UNIT:service}},GUARD={},CONFIG={}))
    monkeypatch.setattr(p,'read',lambda *a:raw)
    p.candidate_environment(False)
    with pytest.raises(plan.Stop,match='CANDIDATE_PROCESS_ENV'):p.candidate_environment(True)
    raw+=b'POWERFLOW_OPERATIONAL_PUBLICATION_ROOT=/srv/powerflow/operational-publications\0'
    p.candidate_environment(True)
    with pytest.raises(plan.Stop,match='EXISTING_OPERATIONAL_CONFIG'):p.candidate_environment(False)


def test_api_and_helper_import_closure_and_static_origin():
    import sys
    b=load('build');config,data=b.build_config(False)
    allowed=set(sys.stdlib_module_names)|{'fastapi','uvicorn','httpx','joserfc','cryptography','pydantic','numpy','pandas','starlette'}
    api_modules={key[8:-3].replace('/','.') for key in data if key.startswith('api/src/') and key.endswith('.py')}
    for key,raw in data.items():
        if not key.startswith('api/src/') or not key.endswith('.py'):continue
        for node in ast.walk(ast.parse(raw)):
            if isinstance(node,ast.Import):
                for name in node.names:assert name.name.split('.')[0] in allowed|{'api','shared'}
            elif isinstance(node,ast.ImportFrom):
                if node.level:
                    parent=key[8:-3].replace('/','.').split('.')[:-node.level]
                    target='.'.join(parent+([node.module] if node.module else []))
                    assert target in api_modules or any(m.startswith(target+'.') for m in api_modules),target
                elif node.module:assert node.module.split('.')[0] in allowed|{'api','shared'}
    assert data['api/requirements/api.lock']==(ROOT/'requirements/api.lock').read_bytes()
    assert data['api/src/shared/forecast_publication.py']==(ROOT/'src/shared/forecast_publication.py').read_bytes()
    meta=json.loads(data['static/build-config.json'])
    assert meta['releaseEligible']is True and meta['origin']=='https://staging.powerflowenergy.dev' and meta['apiBase']=='/api'
    assert not any(key.endswith('.map') for key in data)


def test_corrupt_independent_backup_blocks_rollback(transaction):
    tx,p,cfg,state,before,writes,forecast=transaction;tx.apply()
    (p.CONTROL/'api_env.independent').write_bytes(b'corrupt backup')
    count=len(writes)
    with pytest.raises(tx.PLAN.Stop,match='ROLLBACK_BACKUP'):tx.rollback()
    assert len(writes)==count and state['vars']['env'][tx.PLAN.FLAG]=='true'


def test_failure_path_identifiers_are_allowlisted():
    plan=load('plan');p=load('preflight',dict(PLAN=plan,BASE={},GUARD={},CONFIG={'worker':{'src/scheduled_pipeline.py':{}},'old_api':{},'worker_sdk':{}}))
    assert p.path_id('/home/ec2-user/Electricity_Trading_Pipeline/src/scheduled_pipeline.py')=='WORKER_SCHEDULED_PIPELINE_PY'
    assert p.path_id('/proc/123/environ')=='PROCESS_ENVIRON'
    assert p.path_id('/private/secret-token-value')=='UNIDENTIFIED'


def test_preflight_cli_local_check_has_no_transport(monkeypatch,capsys):
    import sys
    r=load('run');digest=r.sha((FOLDER/'MANIFEST.json').read_bytes())
    monkeypatch.setattr(sys,'argv',['run.py','preflight','--manifest-sha256',digest,'--local-check'])
    assert r.main()==0
    assert json.loads(capsys.readouterr().out)=={'status':'LOCAL_PASS','ssh_attempts':0}


def test_single_restart_with_bounded_readiness_observations(monkeypatch):
    plan=load('plan');commands=[];reads=[]
    def request(port,path):
        reads.append(path);return (503 if len(reads)<3 else 200),b'{}'
    base={'bounded_run':lambda argv,**kw:(commands.append(argv)or{'returncode':0,'failure':None}), 'request':request}
    tx=load('transaction',dict(BASE=base,GUARD={},PLAN=plan,CONFIG={},PREFLIGHT=SimpleNamespace()))
    monkeypatch.setattr(tx.time,'sleep',lambda _:None)
    tx.restart()
    assert commands==[['/usr/bin/systemctl','restart',plan.UNIT]] and len(reads)<=20
    base['request']=lambda *a:(503,b'{}')
    with pytest.raises(plan.Stop,match='STARTUP_READINESS'):tx.restart()
    assert len(commands)==2  # two independent offline test calls; no retry inside either


def test_report_schema_rejects_unbounded_or_unapproved_output():
    r=load('run')
    assert r.validate_report({'status':'BLOCKED','reason':'FILE_MISSING','changed':False})['status']=='BLOCKED'
    for report in [{'status':'APPLIED','raw_stdout':'private'}, {'status':'PREFLIGHT_PASS','reason':'x'*201}, {'status':'PARTIAL','changed':{'secret':'private'}}]:
        with pytest.raises(ValueError):r.validate_report(report)


def test_transport_exception_does_not_claim_zero_attempts(monkeypatch,tmp_path,capsys):
    import sys
    r=load('run');private=tmp_path.resolve();(private/'preflight').mkdir()
    wrapper=SimpleNamespace(PRIVATE=private,profile=lambda:{},ssh_argv=lambda _:['ssh','fixed'])
    base=SimpleNamespace(bounded_run=lambda *a,**k:(_ for _ in ()).throw(OSError('fixture interrupted transport')))
    monkeypatch.setattr(r,'verify',lambda *a:(b'fixed payload',wrapper,base))
    monkeypatch.setattr(sys,'argv',['run.py','preflight','--manifest-sha256','a'*64])
    assert r.main()==1
    report=json.loads(capsys.readouterr().out)
    assert report=={'status':'FAILED','reason':'TRANSPORT_OR_CAPTURE_UNVERIFIED','ssh_attempts':1}


def test_exact_historical_baseline_and_six_overlaps():
    b=load('baseline');baseline=b.load();approved=b.parse(b.APPROVED.read_bytes())
    release={k[7:]:v['sha256'] for k,v in approved['files'].items() if k.startswith('static/')}
    retained=baseline['retained_assets'];combined=baseline['static_inventory']
    assert len(release)==37 and len(retained)==31 and len(release.keys()&retained.keys())==6 and len(combined)==62
    assert all(combined[k]==v for k,v in release.items()) and combined==dict(sorted(combined.items()))
    assert b.sha(b.RECORD.read_bytes())=='b37d5e173ab58a1690f9fee22c3a40d4dbb346427326772934617771fbac3e11'
    assert b.load()==json.loads((FOLDER/'BASELINE.json').read_bytes())


@pytest.mark.parametrize('kind',['modified','missing_asset','conflicting_overlap','wrong_transaction','wrong_predecessor','incomplete_phase'])
def test_historical_record_rejects_inconsistency(kind,monkeypatch):
    b=load('baseline');raw=b.RECORD.read_bytes();record=b.parse(raw);approved=b.APPROVED.read_bytes()
    if kind=='modified':
        with pytest.raises(ValueError,match='HISTORICAL_RECORD_HASH'):b.reconstruct(raw+b' ',approved)
        return
    if kind=='missing_asset':record['retained_assets'].pop(next(iter(record['retained_assets'])))
    if kind=='conflicting_overlap':
        release={k[7:]:v['sha256'] for k,v in b.parse(approved)['files'].items() if k.startswith('static/')}
        key=next(iter(release.keys()&record['retained_assets'].keys()))
        record['retained_assets'][key]='0'*64;record['old_static_files'][key]='0'*64
    if kind=='wrong_transaction':record['transaction_id']='0'*32
    if kind=='wrong_predecessor':record['previous_static']='/var/www/powerflow-staging/releases/phase-forecast-consistency-20261101-v1'
    if kind=='incomplete_phase':record['phase']='BACKUPS'
    bad=json.dumps(record).encode();monkeypatch.setattr(b,'RECORD_SHA',b.sha(bad))
    with pytest.raises(ValueError):b.reconstruct(bad,approved)


@pytest.mark.parametrize('name',['../outside','assets/../outside','/absolute','assets//x.js','assets/./x.js','assets/x?secret.js'])
def test_baseline_rejects_path_escape_and_noncanonical_names(name):
    b=load('baseline')
    with pytest.raises(ValueError):b.inventory({name:'a'*64})


def test_duplicate_json_entries_and_conflicting_merge_rejected():
    b=load('baseline')
    for raw in [b'{"x":1,"x":2}',b'{"retained_assets":{"a":"x","a":"y"}}']:
        with pytest.raises(ValueError,match='DUPLICATE_KEY'):b.parse(raw)
    with pytest.raises(ValueError,match='RETAINED_HASH_CONFLICT'):b.merge({'assets/a.js':'a'*64},{'assets/a.js':'b'*64})


def test_wrong_archive_cannot_substitute_historical_record():
    b=load('baseline');old=ROOT/'data/backups/private-staging-releases/phase-forecast-consistency-20261101-v1/release/release-manifest.json'
    with pytest.raises(ValueError,match='HISTORICAL_RECORD_HASH'):b.reconstruct(old.read_bytes(),b.APPROVED.read_bytes())


def test_missing_private_record_fails_closed(monkeypatch,tmp_path):
    b=load('baseline');monkeypatch.setattr(b,'RECORD',tmp_path/'absent.json')
    with pytest.raises(FileNotFoundError):b.load()


@pytest.mark.parametrize('kind',['escape','wrong_hash','wrong_root','duplicate_destination','nonstatic_copy'])
def test_invalid_copy_bindings_rejected(kind):
    builder=load('build');b=load('baseline');cfg,_=builder.build_config(False);cfg=copy.deepcopy(cfg)
    key=next(k for k,v in cfg['files'].items() if 'copy_from'in v);item=cfg['files'][key]
    if kind=='escape':item['copy_from']=b.STATIC+'/assets/../../outside'
    if kind=='wrong_hash':item['sha256']='0'*64
    if kind=='wrong_root':item['copy_from']=item['copy_from'].replace('phase-api-body-bound-20261102-v2','phase-forecast-consistency-20261101-v1')
    if kind=='duplicate_destination':item['destination']=next(v['destination'] for k,v in cfg['files'].items() if k!=key)
    if kind=='nonstatic_copy':cfg['files']['worker/src/scheduled_pipeline.py']['copy_from']=item['copy_from']
    with pytest.raises(ValueError):b.validate_copies(cfg)


def test_retained_remote_copy_requires_exact_content_and_rejects_drift(transaction,monkeypatch):
    tx,p,cfg,*_=transaction;key='static/assets/historical.js';raw=b'authentic historical bytes fixture'
    cfg['files'][key]={'copy_from':str(p.OLD_STATIC/'assets/historical.js'),'bytes':None,'max_bytes':2000000,'sha256':tx.PLAN.sha(raw)}
    cfg['old_static_inventory']['assets/historical.js']=tx.PLAN.sha(raw)
    monkeypatch.setattr(p,'snap',lambda path,*a,**kw:({},raw))
    assert tx.raw_file(key)==raw
    monkeypatch.setattr(p,'snap',lambda path,*a,**kw:({},b'changed'))
    with pytest.raises(tx.PLAN.Stop,match='PAYLOAD_HASH'):tx.raw_file(key)


def test_new_payload_assembly_is_deterministic_and_has_no_unverified_copies():
    b=load('build');cfg,data=b.build_config(False);cfg2,data2=b.build_config(False)
    assert cfg==cfg2 and data==data2
    assert len(cfg['old_static_inventory'])==62 and cfg['historical_record_sha256']==load('baseline').RECORD_SHA
    blobs={n:(ROOT/n).read_bytes() for n in b.ARTIFACTS}
    for action in ['preflight','apply','rollback','accept']:
        assert b.assemble(action,cfg,blobs,data)==b.assemble(action,cfg2,blobs,data2)
    assert all(key.startswith('static/') and cfg['old_static_inventory'][key[7:]]==v['sha256'] for key,v in cfg['files'].items() if 'copy_from'in v)


def test_v1_manifest_and_payloads_remain_unchanged():
    import hashlib
    old=ROOT/'deploy/staging/operational-evidence-release-v1';raw=(old/'MANIFEST.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='873619a9cd73d5fc676058facc1ed5daf1dc1030efbc4572b42c34653a4bf7d9'
    for action,item in json.loads(raw)['payloads'].items():assert hashlib.sha256((old/(action+'.payload.py')).read_bytes()).hexdigest()==item['sha256']
