"""Offline immutable assembly, Linux guard mocks and guarded transaction tests."""
import ast
import base64
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import types
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'deploy/staging/realized-performance-release-v1'
def load(name):
    spec=importlib.util.spec_from_file_location('realized_release_'+name,HERE/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
@pytest.fixture(scope='module')
def package():
    b=load('build');prefix,m,a=b.parent();return b,prefix,m,b.config(m)

def test_precise_inventory_and_frozen_implementation(package):
    b,_,m,c=package
    assert {k[4:]for k,v in c['files'].items()if k.startswith('api/')and(k not in m['config']['files']or v['sha256']!=m['config']['files'][k]['sha256'])}==b.API_CHANGE
    assert {k[7:]for k in c['files']if k.startswith('worker/')}==b.WORKER
    for k,v in m['config']['files'].items():
        if k.startswith('static/assets/'):assert c['files'][k]['sha256']==v['sha256']
    for rel in ['src/api/security.py','src/api/mfa_service.py','src/api/current_operations.py','src/api/forecast_source.py','src/shared/forecast_availability.py','src/shared/forecast_publication.py']:
        assert c['files']['api/'+rel]['sha256']==m['config']['files']['api/'+rel]['sha256']
    assert not any('scheduled_pipeline' in key or key in {'nginx','launcher','sudoers'}for key in c['files'])
    assert c['files']['static/build-config.json']['sha256']==m['config']['files']['static/build-config.json']['sha256']
    assert len(c['worker_closure'])>=15
    assert c['worker_before']['src/models/next24h_monitoring.py']==b.sha(b.read(HERE/'baseline/next24h_monitoring.py'))

@pytest.mark.parametrize('action',['preflight','apply','rollback','accept'])
def test_determinism_closure_and_python39(package,action):
    b,p,_,c=package;raw=b.assemble(action,p,c);assert raw==b.assemble(action,p,c);ast.parse(raw,feature_version=(3,9));assert len(raw)<=4*1024**2
    if(HERE/'MANIFEST.json').exists():
        m=json.loads((HERE/'MANIFEST.json').read_bytes());assert raw==(HERE/(action+'.payload.py')).read_bytes();assert m['payloads'][action]==dict(sha256=b.sha(raw),bytes=len(raw))

def compiled_functions(raw):
    functions=set();pending=[raw]
    while pending:
        tree=ast.parse(pending.pop())
        for n in ast.walk(tree):
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):functions.add(n.name)
            if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='compile'and n.args and isinstance(n.args[0],ast.Constant)and isinstance(n.args[0].value,(str,bytes)):pending.append(n.args[0].value)
    return functions
@pytest.mark.parametrize('action',['preflight','accept'])
def test_readonly_payload_cannot_call_mutation_entrypoints(package,action):
    b,p,_,c=package;names=compiled_functions(b.assemble(action,p,c))
    assert not names&{'apply','rollback','write','mkdir','restart','pointer','patch','publish','deliver_terminal'}

def test_immutable_emit_never_overwrites(tmp_path):
    b=load('build');old=tmp_path/'old';old.write_bytes(b'old');new=tmp_path/'new'
    with pytest.raises(AssertionError,match='IMMUTABLE_RELEASE_DRIFT'):b.emit({new:b'new',old:b'changed'})
    assert old.read_bytes()==b'old'and not new.exists()
@pytest.mark.parametrize('path',['','/x','../x','a/../b','a//b','a/./b','a\\b'])
def test_paths_reject_unsafe(path):assert not load('build').safe_rel(path)

@pytest.fixture
def policy():
    m=types.ModuleType('policy');m.C={'root':'/srv/powerflow/realized-performance','failure_gates':['PIPELINE_OR_WINDOW_GATE','WORKER_BASELINE_DRIFT_NEXT24H_MONITORING','PREFECT_IMPLEMENTATION_DRIFT']}
    m.OLD=types.SimpleNamespace(H=types.SimpleNamespace(OP=types.SimpleNamespace(InvalidEvidence=ValueError),OLD_PLAN=types.SimpleNamespace(Stop=ValueError)))
    exec(compile((HERE/'policy.py').read_bytes(),'<verified-realized-policy>','exec'),m.__dict__);return m

def test_environment_and_variables_only_declared_keys(policy):
    old={'env':{'POWERFLOW_AUTO_PUBLICATION_ENABLED':'true','POWERFLOW_OPERATIONAL_EVIDENCE_ENABLED':'true'},'labels':{'unchanged':'yes'}};copyold=copy.deepcopy(old)
    new=policy.variables(old);assert old==copyold
    assert new['env']=={**old['env'],'POWERFLOW_REALIZED_REPORT_ENABLED':'true','POWERFLOW_REALIZED_REPORT_ROOT':policy.C['root']}
    assert new['labels']==old['labels']
    raw=b'EXISTING_PUBLIC_CONFIG=preserved\n';assert policy.environment(raw)==raw+b'POWERFLOW_REALIZED_REPORT_ROOT=/srv/powerflow/realized-performance\n'
    with pytest.raises(ValueError):policy.variables(new)
    with pytest.raises(ValueError):policy.environment(policy.environment(raw))

def test_failure_reporting_sanitized_and_original_gates(policy):
    for reason in ['PIPELINE_OR_WINDOW_GATE','WORKER_BASELINE_DRIFT_NEXT24H_MONITORING','PREFECT_IMPLEMENTATION_DRIFT']:
        assert policy.failure_report(ValueError(reason))['reason']==reason
    r=policy.failure_report(RuntimeError('SECRET /private/raw/path token=value'))
    assert 'SECRET'not in json.dumps(r)and r['reason']=='UNVERIFIED_HOST_OPERATION'


def test_runner_sanitization_rejects_unknown_fields():
    r=load('run')
    with pytest.raises(AssertionError):r.validate_report({'status':'BLOCKED','changed':False,'token':'secret'})
    assert r.validate_report({'status':'WAITING','changed':False})['status']=='WAITING'

@pytest.fixture
def job(tmp_path,monkeypatch):
    b=load('build');oldapi=tmp_path/'old-api';oldstatic=tmp_path/'old-static';worker=tmp_path/'worker';venv=tmp_path/'venv'
    for p in [oldapi,oldstatic,worker/'src/models',worker/'src/shared',venv]:p.mkdir(parents=True,exist_ok=True)
    (oldapi/'old.py').write_bytes(b'old-api');(oldstatic/'index.html').write_bytes(b'old-static');(worker/'src/models/next24h_monitoring.py').write_bytes(b'old-monitor')
    backend=tmp_path/'api-current';static=tmp_path/'static-current';backend.symlink_to(oldapi);static.symlink_to(oldstatic)
    env=tmp_path/'api.env';env.write_bytes(b'PRESERVED_AUTH_SETTING=yes\n');env.chmod(0o600)
    c={'release':b.RELEASE,'transaction':b.TRANSACTION,'binding':'bound','api':str(tmp_path/'new-api'),'static':str(tmp_path/'new-static'),'root':str(tmp_path/'reports'),'control':str(tmp_path/'journal'),'files':{},'failure_gates':['PIPELINE_OR_WINDOW_GATE','PREFECT_IMPLEMENTATION_DRIFT','WORKER_BASELINE_DRIFT_NEXT24H_MONITORING'],'worker_closure':{},'worker_dependencies':{},'worker_versions':{},'worker_before':{'src/models/next24h_monitoring.py':b.sha(b'old-monitor'),'src/models/realized_reporting.py':None}}
    for key,raw in [('api/src/api/app.py',b'new-api'),('static/index.html',b'new-static'),('worker/src/models/next24h_monitoring.py',b'new-monitor'),('worker/src/models/realized_reporting.py',b'new-report')]:c['files'][key]=dict(sha256=b.sha(raw),bytes=len(raw),base64=base64.b64encode(raw).decode())
    oldvars={'env':{'POWERFLOW_OPERATIONAL_EVIDENCE_ENABLED':'true','POWERFLOW_AUTO_PUBLICATION_ENABLED':'true'}};state={'variables':copy.deepcopy(oldvars)};calls=[]
    runtime={'sha256':'runtime','files':1,'bytes':1,'imports':'PASS'}
    snapshot={'production':'production','forecast':{'pointer':'releases/'+('a'*64),'bundle':'a'*64,'root':[0,992,488]},'store':'store','helper':'helper','nginx':'nginx','pool':'pool'}
    class Stop(ValueError):pass
    h=types.SimpleNamespace(OLD_PLAN=types.SimpleNamespace(Stop=Stop,UNIT='powerflow-candidate-api.service',DEPLOYMENT='11111111-1111-4111-8111-111111111111',stable_projection=lambda _:{'hourly':True,'concurrency':1}),OP=types.SimpleNamespace(InvalidEvidence=ValueError,timestamp=lambda s:dt.datetime.fromisoformat(s.replace('Z','+00:00'))))
    h.entries=lambda path,limit:list(Path(path).iterdir())
    old=types.SimpleNamespace(H=h,API=oldapi,STATIC=oldstatic,tree_state=lambda *_,**kw:calls.append('old-trees'),load_record=lambda:{'phase':'APPLIED','activated_at':'2026-11-07T00:00:00Z','baseline':{'venv':str(venv),'runtime':runtime}},verified_backups=lambda _:calls.append('old-backups'),deployment_checks=lambda _:calls.append('old-deployment-checks'),public_operations=lambda:calls.append('public-operations'),forecast_checks=lambda:calls.append('forecast-checks'))
    def snap(path,uid=0,gid=0,mode=0o644):
        raw=Path(path).read_bytes();return dict(sha256=b.sha(raw),uid=uid,gid=gid,mode=mode,bytes=len(raw)),raw
    p=types.SimpleNamespace(PRODUCTION=worker,ENV=env,BACKEND_LINK=backend,STATIC_LINK=static,safe=lambda *args:None,snap=snap,read=lambda p,limit=2000000:Path(p).read_bytes(),idle=lambda _:calls.append('idle'),deployment=lambda:{'job_variables':copy.deepcopy(state['variables'])},runtime_closure=lambda _:runtime,candidate_environment=lambda _:calls.append('candidate-env'))
    m=types.ModuleType('transaction_fixture');m.__dict__.update(C=c,OLD=old,H=h,P=p,B={'read':lambda p,limit:Path(p).read_bytes()},G={'runtime':lambda p:calls.append(('runtime',str(p)))})
    for name in ['policy','guards','transaction','acceptance']:exec(compile((HERE/(name+'.py')).read_bytes(),'<verified-realized-'+name+'>','exec'),m.__dict__)
    m.P.forecast_configuration=lambda:calls.append('forecast-config')
    m.snapshot=lambda:copy.deepcopy(snapshot)
    before={'snapshot':copy.deepcopy(snapshot),'worker':{'src/models/next24h_monitoring.py':snap(worker/'src/models/next24h_monitoring.py',1000,1000,0o644)[0],'src/models/realized_reporting.py':None},'env':snap(env,0,0,0o600)[0],'env_after':b.sha(m.environment(env.read_bytes())),'old_variables':oldvars,'new_variables':m.variables(oldvars),'projection':{'hourly':True,'concurrency':1},'venv':str(venv),'runtime':runtime}
    m.fresh_guard=m.fresh
    m.fresh=lambda:copy.deepcopy(before)
    def activate(expected,value):
        assert state['variables']==expected;state['variables']=copy.deepcopy(value);calls.append('enable'if m.FLAG in value['env']else'disable')
    m.patch=activate;m.queued_gate=lambda:calls.append('queued-check');m.restart=lambda target:calls.append(('restart',str(target)));m.report_environment=lambda active:calls.append(('report-env',active))
    def checks(r,enabled):
        m.new_trees(r,True);m.worker_state(True);m.report_metadata(r,empty=True)
        assert state['variables']==r['before']['new_variables'if enabled else'old_variables'];assert p.BACKEND_LINK.resolve()==m.API
        assert b.sha(env.read_bytes())==before['env_after'];calls.append('checks-enabled'if enabled else'checks-disabled')
    m.deployment_checks=checks
    monkeypatch.setattr(os,'chown',lambda *_:None);monkeypatch.setattr(os,'fchown',lambda *_:None)
    original=Path.lstat;chmod=os.chmod;desired_modes={}
    def linux_chmod(path,mode,*args,**kwargs):
        desired_modes[Path(path)]=mode;return chmod(path,mode,*args,**kwargs)
    monkeypatch.setattr(os,'chmod',linux_chmod)
    def metadata(path):
        s=list(original(path));owner=(1000,992)if path==m.REPORT or path.is_relative_to(m.REPORT)else(1000,1000)if path==worker or path.is_relative_to(worker)else(0,0)
        s[4],s[5]=owner
        # Darwin strips setgid for this unprivileged test process. Simulate only
        # the exact bits requested by the privileged Linux installer.
        if desired_modes.get(path,0)&stat.S_ISGID:s[0]|=stat.S_ISGID
        if stat.S_ISLNK(s[0]):s[0]=stat.S_IFLNK|0o777
        return os.stat_result(s)
    monkeypatch.setattr(Path,'lstat',metadata)
    return m,state,calls,before


def test_apply_and_rollback_complete_offline(job):
    m,state,calls,before=job
    assert m.apply()['status']=='APPLIED'
    assert calls.index('enable')>calls.index('checks-disabled')
    r=m.load_record();m.verify_backups(r)
    assert r['roots'].keys()=={'api','static','report','report_releases'}
    assert m.report_metadata(r,empty=True)is None
    assert m.rollback()['status']=='ROLLED_BACK'
    assert m.P.BACKEND_LINK.resolve()==m.OLD.API and m.P.STATIC_LINK.resolve()==m.OLD.STATIC
    assert m.P.ENV.read_bytes()==b'PRESERVED_AUTH_SETTING=yes\n'
    assert(m.WORKER/'src/models/next24h_monitoring.py').read_bytes()==b'old-monitor'
    assert not(m.WORKER/'src/models/realized_reporting.py').exists()
    assert m.REPORT.exists()and m.API.exists()and m.CONTROL.exists()
    assert state['variables']==before['old_variables']
    assert calls.count('enable')==calls.count('disable')==1

@pytest.mark.parametrize('gate',['PIPELINE_OR_WINDOW_GATE','PREFECT_IMPLEMENTATION_DRIFT','WORKER_BASELINE_DRIFT_NEXT24H_MONITORING'])
def test_complete_mock_preflight_original_gate_no_writes(job,gate):
    m,_,_,_=job
    def blocked():raise ValueError(gate)
    m.fresh=blocked
    with pytest.raises(ValueError,match='^'+gate+'$'):m.preflight_report()
    assert m.failure_report(ValueError(gate))['reason']==gate
    assert not m.CONTROL.exists()and not m.REPORT.exists()and not m.CHANGED


def test_apply_fresh_gate_drift_aborts_before_mutation(job):
    m,_,_,before=job;different=copy.deepcopy(before);different['snapshot']['helper']='drift'
    values=iter([before,different]);m.fresh=lambda:next(values)
    with pytest.raises(ValueError,match='FRESH_GATE_CHANGED'):m.apply()
    assert not m.CHANGED and not m.CONTROL.exists()


def test_acceptance_failure_never_activates_or_auto_rolls_back(job):
    m,state,calls,before=job
    def fail(r,enabled):raise ValueError('ROUTED_HTTP_FAILURE')
    m.deployment_checks=fail
    with pytest.raises(ValueError,match='ROUTED_HTTP_FAILURE'):m.apply()
    assert state['variables']==before['old_variables']and 'enable'not in calls
    assert m.P.BACKEND_LINK.resolve()==m.API and m.load_record()['phase']=='POINTERS'
    assert m.failure_report(ValueError('ROUTED_HTTP_FAILURE'))['status']=='FAILED'
    m.verify_backups(m.load_record())
    assert m.rollback()['status']=='ROLLED_BACK'


def test_missing_backup_and_foreign_worker_block_rollback(job):
    m,_,_,_=job;m.apply();r=m.load_record()
    backup=m.backup_name('env','independent');raw=backup.read_bytes();backup.unlink()
    with pytest.raises(FileNotFoundError):m.rollback()
    backup.write_bytes(raw);backup.chmod(0o600)
    (m.WORKER/'src/models/next24h_monitoring.py').write_bytes(b'unknown change')
    with pytest.raises(ValueError,match='ROLLBACK_WORKER_DRIFT'):m.rollback()
    assert m.P.BACKEND_LINK.resolve()==m.API


def test_write_scope_and_immutable_release_guards(job):
    m,_,_,_=job
    with pytest.raises(ValueError,match='WRITE_SCOPE'):m.write(m.WORKER/'unrelated',b'bad')
    m.apply();(m.API/'src/api/app.py').write_bytes(b'changed')
    with pytest.raises(ValueError,match='RELEASE_CONTENT_DRIFT'):m.rollback()

@pytest.mark.parametrize('kind',['api','worker'])
def test_candidate_imports_from_root_no_network_writes_or_inference(package,kind):
    b,_,_,c=package;m=types.ModuleType('import_fixture')
    p=types.SimpleNamespace(PRODUCTION=Path('/home/ec2-user/Electricity_Trading_Pipeline'),ENV=Path('/etc/powerflow/react-api.env'),snap=lambda path,*args:(None,(ROOT/'src'/Path(path).relative_to('/home/ec2-user/Electricity_Trading_Pipeline/src')).read_bytes()))
    m.__dict__.update(C=c,P=p,OLD=types.SimpleNamespace(H=types.SimpleNamespace(OP=types.SimpleNamespace(InvalidEvidence=ValueError),OLD_PLAN=types.SimpleNamespace(Stop=ValueError))))
    for name in ['policy','guards']:exec(compile((HERE/(name+'.py')).read_bytes(),'<verified-realized-'+name+'>','exec'),m.__dict__)
    script=m.probe_script(kind).decode();uid=992 if kind=='api'else 1000
    # Only the Linux identity assertion is mocked on macOS; filesystem layout,
    # actual imports, side-effect audit and runtime-version assertion are real.
    script=script.replace('os.getuid()==os.geteuid()=='+str(uid),'os.getuid()==os.geteuid()=='+str(os.getuid())).replace('os.getgid()==os.getegid()=='+str(uid),'os.getgid()==os.getegid()=='+str(os.getgid()))
    result=subprocess.run([sys.executable,'-I','-B','-'],input=script.encode(),cwd='/',env={'PATH':'/usr/bin:/bin','LANG':'C','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'},capture_output=True,timeout=40)
    assert result.returncode==0,result.stderr.decode();assert result.stdout==b'REPORT_IMPORT_PASS\n'


def linux_fresh_setup(job,monkeypatch):
    m,state,calls,before=job
    m.sys=types.SimpleNamespace(platform='linux',version_info=(3,14,7))
    for name in ['getuid','geteuid','getgid','getegid']:monkeypatch.setattr(os,name,lambda:0)
    monkeypatch.setattr(os,'uname',lambda:types.SimpleNamespace(machine='x86_64'))
    monkeypatch.setattr(os,'O_NOATIME',getattr(os,'O_NOATIME',0x40000),raising=False)
    original=Path.is_dir
    monkeypatch.setattr(Path,'is_dir',lambda p:True if str(p)=='/proc/self/fd'else original(p))
    monkeypatch.setattr(m.pwd,'getpwnam',lambda name:types.SimpleNamespace(pw_uid=1000 if name=='ec2-user'else 992,pw_gid=1000 if name=='ec2-user'else 992))
    (m.WORKER/'.env').write_bytes(b'EXISTING=unchanged\n')
    meta=m.WORKER/'.venv-prod/lib/python3.14/site-packages/prefect-3.7.5.dist-info/METADATA';meta.parent.mkdir(parents=True);meta.write_bytes(b'reference')
    executable=m.WORKER/'.venv-prod/bin/python';executable.parent.mkdir();executable.symlink_to(sys.executable)
    m.H.OLD_CONFIG={'worker':{},'worker_sdk':{},'prefect_metadata_sha256':hashlib.sha256(b'reference').hexdigest()}
    m.B['services']=lambda:{'powerflow-prefect-worker.service':{'User':'ec2-user','Group':'ec2-user','WorkingDirectory':str(m.WORKER),'MainPID':'123','NoNewPrivileges':'no'}}
    m.P.read=lambda path,limit=2000000:b''if str(path).startswith('/proc/')else Path(path).read_bytes()
    m.P.process=lambda argv:calls.append(('readonly-command',tuple(argv)))
    m.parent_access=lambda:calls.append('parent-access');m.input_bounds=lambda:calls.append('input-bounds')
    m.import_probe=lambda kind,venv:calls.append(('import-probe',kind))
    m.report_http=lambda:(404,{'detail':{'code':'REALIZED_REPORT_MISSING'}})
    m.fresh=m.fresh_guard
    return m,calls


def test_full_mocked_linux_preflight_success_read_only(job,monkeypatch):
    m,calls=linux_fresh_setup(job,monkeypatch)
    result=m.preflight_report();assert result['status']=='PREFLIGHT_PASS'and result['changed']is False
    assert result['report_delivery_enabled']is False
    assert 'old-deployment-checks'in calls and 'parent-access'in calls and('import-probe','api')in calls and('import-probe','worker')in calls
    assert not m.REPORT.exists()and not m.CONTROL.exists()and not m.API.exists()


def test_full_mocked_linux_idle_failure_retains_gate(job,monkeypatch):
    m,calls=linux_fresh_setup(job,monkeypatch)
    def busy(_):raise ValueError('PIPELINE_OR_WINDOW_GATE')
    m.P.idle=busy
    with pytest.raises(ValueError,match='PIPELINE_OR_WINDOW_GATE'):m.preflight_report()
    assert not m.CHANGED and not m.CONTROL.exists()and'old-deployment-checks'not in calls


def test_report_namespace_permissions_and_symlinks_fail_closed(job):
    m,_,_,_=job;m.apply()
    m.REPORT.chmod(0o777)
    with pytest.raises(ValueError,match='REPORT_DIRECTORY_METADATA'):m.report_metadata(m.load_record())


def test_forecast_handler_unchanged_from_accepted_deployment(package):
    b,_,m,c=package
    old=ast.parse(base64.b64decode(m['config']['files']['api/src/api/app.py']['base64']))
    new=ast.parse(base64.b64decode(c['files']['api/src/api/app.py']['base64']))
    functions=lambda tree:{n.name:ast.dump(n,include_attributes=False)for n in ast.walk(tree)if isinstance(n,ast.FunctionDef)}
    a,z=functions(old),functions(new)
    for name in a:
        if name not in {'create_app','realized_evaluation_route'}:assert a[name]==z[name],name

@pytest.mark.parametrize('raw',[b' POWERFLOW_REALIZED_REPORT_ROOT = /wrong\n',b'export POWERFLOW_REALIZED_REPORT_ROOT=/wrong\n'])
def test_environment_cannot_hide_override(policy,raw):
    with pytest.raises(ValueError,match='REPORT_ENV_ALREADY_CONFIGURED'):policy.environment(raw)


def test_copy_reference_cannot_escape_predecessor(job):
    m,_,_,_=job;m.C['files']['static/assets/test.js']={'sha256':'a'*64,'bytes':None,'copy_from':'/etc/unapproved'}
    with pytest.raises(ValueError,match='COPY_SOURCE_SCOPE'):m.raw_file('static/assets/test.js')


def test_reconstruction_is_read_only_build_not_publication():
    raw=(HERE/'acceptance.py').read_text();tree=ast.parse(raw)
    names={n.func.attr for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)}
    assert not names&{'publish','deliver_terminal','apply','rollback'}
    assert 'currentAdminOperations'not in raw
    assert 'capture.query(flow[\'id\'],tasks=True)'in raw
    assert "Monitor next24h realized forecast errors"in raw
    assert "@task(name=\"Monitor next24h realized forecast errors\")"in (ROOT/'src/scheduled_pipeline.py').read_text()


def test_import_failure_classification_cannot_disclose_module_or_message(policy):
    error=policy.ImportProbeFailure('PIPELINE_OR_WINDOW_GATE','SECRET_MODULE','SECRET_CLASS')
    report=policy.failure_report(error)
    assert report['reason']=='PIPELINE_OR_WINDOW_GATE'and report['approved_module']=='UNVERIFIED'and report['cause_class']=='OTHER'
    assert 'SECRET'not in json.dumps(report)
    assert policy.failure_report(ValueError('SECRET_TOKEN'))['reason']=='UNVERIFIED_HOST_OPERATION'

@pytest.mark.parametrize('action,seconds',[('preflight',90),('accept',90),('apply',120),('rollback',120)])
def test_runner_one_attempt_exact_timeouts_no_raw_diagnostics(tmp_path,monkeypatch,action,seconds):
    r=load('run');private=tmp_path/'private';(private/'preflight').mkdir(parents=True);calls=[]
    wrapper=types.SimpleNamespace(PRIVATE=private,profile=lambda:{'verified':True},ssh_argv=lambda _:['/usr/bin/ssh','pinned-test-destination','old-command'])
    def bounded(argv,**kw):
        calls.append((argv,kw));return {'returncode':1,'failure':None,'stdout':json.dumps({'status':'BLOCKED','changed':False,'reason':'PIPELINE_OR_WINDOW_GATE'}).encode(),'stderr':b'SECRET_TRANSPORT_TEXT'}
    base=types.SimpleNamespace(bounded_run=bounded)
    monkeypatch.setattr(r,'verify',lambda *_:(b'reviewed-payload',wrapper,base));monkeypatch.setattr(sys,'argv',['run.py',action,'--manifest-sha256','a'*64])
    assert r.main()==1 and len(calls)==1
    argv,kw=calls[0];assert argv[-1]=='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s '+str(seconds)+'s /usr/bin/python3 -I -S -B -'
    assert all(option in argv for option in ['PreferredAuthentications=publickey','PasswordAuthentication=no','KbdInteractiveAuthentication=no'])
    assert kw==dict(input=b'reviewed-payload',timeout=seconds+60,limit=32768,grace=5)
    files=list((private/'preflight').rglob('*'));assert len([p for p in files if p.is_file()])==1
    evidence=next(p for p in files if p.is_file());assert 'SECRET'not in evidence.read_text()and stat.S_IMODE(evidence.stat().st_mode)==0o600


def test_runner_local_check_cannot_connect(tmp_path,monkeypatch):
    r=load('run');wrapper=types.SimpleNamespace(profile=lambda:{'verified':True},ssh_argv=lambda _:pytest.fail('SSH invoked'))
    monkeypatch.setattr(r,'verify',lambda *_:(b'reviewed',wrapper,None));monkeypatch.setattr(sys,'argv',['run.py','preflight','--manifest-sha256','a'*64,'--local-check'])
    assert r.main()==0

@pytest.mark.parametrize('action',['preflight','apply','rollback','accept'])
def test_final_manifest_and_executable_integrity(action):
    r=load('run');raw=(HERE/'MANIFEST.json').read_bytes();expected=r.sha(raw)
    payload,wrapper,supervisor=r.verify(expected,action)
    m=json.loads(raw);assert r.sha(payload)==m['payloads'][action]['sha256']
    assert wrapper.TARGET_SHA=='f5ab84b2a2be98b70e4f528642368b20e170d93595e6f6e9c98f7037974c1623'
    assert wrapper.KNOWN_HOSTS_SHA=='df8fab3b5c8c08a6d2f85c4208e280b1ca61b75dad6168c0bdc29c4567cc73b2'


def test_manifest_or_source_tampering_rejected_before_transport(monkeypatch):
    r=load('run');expected=r.sha((HERE/'MANIFEST.json').read_bytes())
    with pytest.raises(AssertionError):r.verify('0'*64,'preflight')
    original=r.read
    monkeypatch.setattr(r,'read',lambda p:b'changed'if Path(p)==ROOT/'src/shared/realized_report.py'else original(p))
    with pytest.raises(AssertionError):r.verify(expected,'preflight')
