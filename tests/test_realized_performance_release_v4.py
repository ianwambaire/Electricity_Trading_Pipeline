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
HERE=ROOT/'deploy/staging/realized-performance-release-v4'
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
    m.optional_package_state=lambda:{'shared':{'initializer':{'verified':True}}}if kind=='worker'else{}
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


def original_manifest():
    raw=(HERE.with_name('realized-performance-release-v1')/'MANIFEST.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='a3dceba7641ceaa9030709b1b7d4ce59460b54f5123b7e89f15d95bba39b0a83'
    return json.loads(raw)


def test_owner_approved_independent_predecessor_and_frozen_candidate(package):
    b,p,parent,c=package;old=original_manifest();baseline=json.loads((HERE/'BASELINE.json').read_bytes())
    assert baseline['historical_deployment_authorization_established']is False
    assert baseline['git_commit']=='436d7364fa07dae8d01d60bddfc78ef9d12022cd'
    assert c['worker_before']['src/models/next24h_monitoring.py']=='fb9fc1004c79e7888a9b762bfae73cdeec7038c025718dffb5cd21dfa8397bfd'
    assert {k:v for k,v in c['files'].items()if k not in {'worker/'+rel for rel in b.NEW_DEPENDENCIES}}==old['config']['files']
    for key in ['worker_closure','worker_versions','api_change','python']:
        assert c[key]==old['config'][key]
    for rel,expected in old['artifacts'].items():assert b.sha(b.read(ROOT/rel))==expected
    for action,item in old['payloads'].items():assert b.sha(b.read(HERE.with_name('realized-performance-release-v1')/(action+'.payload.py')))==item['sha256']
    assert b.RELEASE=='phase-realized-next24h-performance-20261108-v4'
    assert b.TRANSACTION!=old['transaction']and c['binding']!=old['config']['binding']
    assert c['worker_before']=={**old['config']['worker_before'],'src/models/next24h_monitoring.py':baseline['monitoring_sha256'],**{rel:None for rel in b.NEW_DEPENDENCIES}}


@pytest.mark.parametrize('state',['approved','unexpected','old_v1','candidate_before_apply','candidate_installed'])
def test_real_predecessor_candidate_hash_transition(package,tmp_path,state):
    b,_,_,config=package;rel='src/models/next24h_monitoring.py';c=copy.deepcopy(config)
    c['worker_before']={rel:config['worker_before'][rel]};c['worker_dependencies']={};c['worker_optional_packages']={}
    p=tmp_path/'worker'/rel;p.parent.mkdir(parents=True);p.write_bytes(b'synthetic-file: verified hash supplied by fixture')
    digest={'approved':config['worker_before'][rel],'unexpected':'0'*64,'old_v1':'077e2ccfb388be623b01a655071d75f6de87aa093a71a27e52a4ceafd42ffe0a','candidate_before_apply':c['files']['worker/'+rel]['sha256'],'candidate_installed':c['files']['worker/'+rel]['sha256']}[state]
    def need(ok,code):
        if not ok:raise ValueError(code)
    m=types.ModuleType('strict_worker_transition');m.__dict__.update(C=c,need=need,P=types.SimpleNamespace(PRODUCTION=tmp_path/'worker',ENV=tmp_path/'env',safe=lambda *args:None,snap=lambda *args:({'sha256':digest,'bytes':p.stat().st_size},b'')))
    exec((HERE/'policy.py').read_bytes(),m.__dict__)
    exec((HERE/'guards.py').read_bytes(),m.__dict__)
    if state in {'approved','candidate_installed'}:assert m.worker_state(state=='candidate_installed')[rel]['sha256']==digest
    else:
        with pytest.raises(ValueError,match='WORKER_BASELINE_DRIFT_NEXT24H_MONITORING'):m.worker_state()


@pytest.mark.parametrize('case',['valid','changed','missing','wrong_size'])
def test_worker_closure_dependencies_remain_mandatory_before_and_after_install(package,tmp_path,case):
    b,_,_,config=package;c=copy.deepcopy(config);c['worker_before']={};c['worker_optional_packages']={}
    rel='src/shared/operational_evidence.py';c['worker_dependencies']={rel:config['worker_dependencies'][rel]}
    meta=dict(c['worker_dependencies'][rel])
    if case=='changed':meta['sha256']='f'*64
    if case=='wrong_size':meta['bytes']+=1
    def snap(*args):
        assert args[1:]==(1000,1000,0o644)
        if case=='missing':raise FileNotFoundError('offline fixture')
        return dict(meta),b''
    def need(ok,code):
        if not ok:raise ValueError(code)
    m=types.ModuleType('strict_dependency_transition');m.__dict__.update(C=c,need=need,P=types.SimpleNamespace(PRODUCTION=tmp_path/'worker',ENV=tmp_path/'env',snap=snap))
    exec((HERE/'policy.py').read_bytes(),m.__dict__)
    exec((HERE/'guards.py').read_bytes(),m.__dict__)
    for installed in [False,True]:
        if case=='valid':assert m.worker_state(installed)=={}
        elif case=='missing':
            with pytest.raises(m.DependencyInventoryFailure):m.worker_state(installed)
        else:
            with pytest.raises(ValueError,match='WORKER_DEPENDENCY_DRIFT_OPERATIONAL_EVIDENCE'):m.worker_state(installed)


def test_guarded_apply_rollback_restores_exact_approved_predecessor(job):
    m,state,calls,before=job;rel='src/models/next24h_monitoring.py'
    raw=subprocess.run(['git','show','436d7364fa07dae8d01d60bddfc78ef9d12022cd:'+rel],cwd=ROOT,capture_output=True,check=True,timeout=5).stdout
    digest=hashlib.sha256(raw).hexdigest();assert digest=='fb9fc1004c79e7888a9b762bfae73cdeec7038c025718dffb5cd21dfa8397bfd'
    path=m.WORKER/rel;path.write_bytes(raw);m.C['worker_before'][rel]=digest
    before['worker'][rel]=m.P.snap(path,1000,1000,0o644)[0]
    assert m.apply()['status']=='APPLIED'
    assert path.read_bytes()==b'new-monitor'
    journal=m.load_record();m.verify_backups(journal)
    first=m.backup_name(rel,'backup');second=m.backup_name(rel,'independent')
    assert first.read_bytes()==second.read_bytes()==raw and first.stat().st_ino!=second.stat().st_ino
    assert m.rollback()['status']=='ROLLED_BACK'and path.read_bytes()==raw
    assert m.load_record()['phase']=='ROLLED_BACK'


def test_unchanged_guard_and_transaction_security_code():
    old=HERE.with_name('realized-performance-release-v1')
    for name in ['transaction.py']:
        assert (HERE/name).read_bytes()==(old/name).read_bytes()


def test_immutable_verifier_when_frozen():
    if not(HERE/'MANIFEST.json').exists():pytest.skip('freeze follows offline fixture tests')
    r=load('run');digest=r.sha(r.read(HERE/'MANIFEST.json'))
    for action in ['preflight','apply','rollback','accept']:r.verify(digest,action)


def test_only_initializer_requirement_removed_and_old_packages_preserved(package):
    b,_,_,c=package;old=original_manifest()['config']
    assert c['worker_dependencies']=={k:v for k,v in old['worker_dependencies'].items()if k!='src/shared/__init__.py'and k not in b.NEW_DEPENDENCIES}
    assert c['worker_closure']==old['worker_closure']and {k:v for k,v in c['files'].items()if k not in {'worker/'+rel for rel in b.NEW_DEPENDENCIES}}==old['files']
    assert c['worker_optional_packages']['shared']==dict(old['worker_closure']['shared'],path='src/shared',initializer='src/shared/__init__.py')
    assert not any(k=='worker/src/shared/__init__.py'for k in c['files'])
    for name,digest in [('realized-performance-release-v1','a3dceba7641ceaa9030709b1b7d4ce59460b54f5123b7e89f15d95bba39b0a83'),('realized-performance-release-v2','a8c2cab1dd96767d4ec3e3469d86e2b527689d9d8eb5c5b77df0aae15a494d75')]:
        folder=HERE.with_name(name);raw=(folder/'MANIFEST.json').read_bytes();assert b.sha(raw)==digest
        original=json.loads(raw)
        for path,sha in original['artifacts'].items():assert b.sha(b.read(ROOT/path))==sha


@pytest.fixture
def package_fixture(package,tmp_path,monkeypatch):
    b,_,_,config=package;c=copy.deepcopy(config);worker=tmp_path/'worker';worker.mkdir()
    for name,item in c['worker_closure'].items():
        if name=='shared':continue
        path=worker/item['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/item['path']).read_bytes());path.chmod(0o644)
    shared=worker/'src/shared';shared.chmod(0o755)
    native=Path.lstat
    def linux_metadata(path):
        s=native(path)
        if path==worker or worker in path.parents:
            return types.SimpleNamespace(st_mode=s.st_mode,st_uid=1000,st_gid=1000,st_dev=s.st_dev,st_ino=s.st_ino,st_nlink=s.st_nlink,st_size=s.st_size)
        return s
    monkeypatch.setattr(Path,'lstat',linux_metadata)
    def need(ok,code):
        if not ok:raise ValueError(code)
    def safe(path,owners=(0,)):
        path=Path(path)
        for p in [path,*path.parents]:
            if p!=worker and worker not in p.parents:break
            s=p.lstat();need(not stat.S_ISLNK(s.st_mode)and s.st_uid in owners and not s.st_mode&0o022,'PATH_METADATA')
    def snap(path,uid=0,gid=0,mode=0o644):
        safe(path,(0,1000));s=path.lstat();need(stat.S_ISREG(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(uid,gid,mode),'FILE_METADATA')
        raw=path.read_bytes();return dict(sha256=b.sha(raw),uid=uid,gid=gid,mode=mode,bytes=len(raw)),raw
    p=types.SimpleNamespace(PRODUCTION=worker,ENV=tmp_path/'env',safe=safe,snap=snap)
    m=types.ModuleType('namespace_release_fixture');m.__dict__.update(C=c,P=p,need=need,sha=b.sha)
    exec((HERE/'policy.py').read_bytes(),m.__dict__)
    exec((HERE/'guards.py').read_bytes(),m.__dict__)
    return m,shared


@pytest.mark.parametrize('initializer',['absent','approved'])
def test_shared_namespace_or_verified_regular_package_is_supported(package_fixture,initializer):
    m,shared=package_fixture
    if initializer=='approved':
        (shared/'__init__.py').write_bytes((ROOT/'src/shared/__init__.py').read_bytes());(shared/'__init__.py').chmod(0o644)
    state=m.optional_package_state();assert(state['shared']['initializer']is None)==(initializer=='absent')
    code,locations=m.sources('worker')
    assert code['shared'][1]is True
    assert locations['shared']==str(shared if initializer=='absent'else shared/'__init__.py')
    assert code['shared'][0]==(''if initializer=='absent'else(ROOT/'src/shared/__init__.py').read_text())
    assert not(shared/'__init__.py').exists()if initializer=='absent'else True


@pytest.mark.parametrize('kind',['modified_initializer','bad_initializer_mode','initializer_link','directory_link','directory_file','directory_mode','shadow_module'])
def test_invalid_package_structure_fails_closed(package_fixture,tmp_path,kind):
    m,shared=package_fixture;initializer=shared/'__init__.py'
    if kind=='modified_initializer':initializer.write_text('raise RuntimeError("never execute")')
    elif kind=='bad_initializer_mode':initializer.write_bytes((ROOT/'src/shared/__init__.py').read_bytes());initializer.chmod(0o600)
    elif kind=='initializer_link':initializer.symlink_to(ROOT/'src/shared/__init__.py')
    elif kind in {'directory_link','directory_file'}:
        previous=shared.with_name('shared-original');shared.rename(previous)
        if kind=='directory_link':shared.symlink_to(previous,target_is_directory=True)
        else:shared.write_text('not a package')
    elif kind=='directory_mode':shared.chmod(0o777)
    else:(shared.parent/'shared.py').write_text('raise RuntimeError("shadowing forbidden")')
    with pytest.raises(ValueError):m.optional_package_state()


@pytest.mark.parametrize('rel',['src/shared/forecast_evaluation.py','src/shared/forecast_publication.py','src/shared/operational_evidence.py'])
def test_remaining_three_required_dependencies_not_optional(package_fixture,rel):
    m,_=package_fixture;m.C['worker_before']={};path=m.WORKER/rel;path.unlink()
    if rel in {'src/shared/forecast_evaluation.py','src/shared/forecast_publication.py'}:
        # These two required modules now come from immutable deployment payloads,
        # never from a missing installed-file fallback.
        sources,_=m.sources('worker')
        assert sources['shared.'+Path(rel).stem][0]==m.raw_file('worker/'+rel).decode()
        m.C['worker_before']={rel:None}
        assert m.worker_state(False)[rel]is None
        with pytest.raises(m.DependencyInventoryFailure):m.worker_state(True)
    else:
        with pytest.raises(m.DependencyInventoryFailure):m.worker_state()
        with pytest.raises(m.DependencyInventoryFailure):m.sources('worker')


@pytest.mark.parametrize('kind',['missing','modified','wrong_mode'])
def test_namespace_does_not_weaken_other_required_module_validation(package_fixture,kind):
    m,_=package_fixture;m.C['worker_before']={};path=m.WORKER/'src/ingestion/fetch_weather_data.py'
    if kind=='missing':path.unlink()
    elif kind=='modified':path.write_text('changed')
    else:path.chmod(0o600)
    with pytest.raises((ValueError,FileNotFoundError)):m.worker_state()


@pytest.mark.parametrize('mechanism',['native','release_probe'])
def test_python314_real_namespace_imports_from_root_without_initializer(package_fixture,mechanism):
    m,shared=package_fixture;assert not(shared/'__init__.py').exists()
    if mechanism=='native':
        script="import sys,importlib.machinery\nsys.path.insert(0,"+repr(str(m.WORKER/'src'))+")\nimport shared\nassert shared.__spec__.origin is None and getattr(shared,'__file__',None)is None\nassert list(shared.__path__)==["+repr(str(shared))+"]\nimport models.realized_reporting,models.next24h_monitoring\nprint('NAMESPACE_IMPORT_PASS')\n"
    else:
        script=m.probe_script('worker').decode()
        script=script.replace('os.getuid()==os.geteuid()==1000','os.getuid()==os.geteuid()=='+str(os.getuid())).replace('os.getgid()==os.getegid()==1000','os.getgid()==os.getegid()=='+str(os.getgid()))
        script+="import shared\nassert shared.__spec__.origin is None and getattr(shared,'__file__',None)is None\nassert list(shared.__path__)==["+repr(str(shared))+"]\n"
    result=subprocess.run([sys.executable,'-I','-B','-'],input=script.encode(),cwd='/',env={'PATH':'/usr/bin:/bin','LANG':'C','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MPLBACKEND':'Agg'},capture_output=True,timeout=40)
    assert result.returncode==0,result.stderr.decode()
    assert result.stdout==(b'NAMESPACE_IMPORT_PASS\n'if mechanism=='native'else b'REPORT_IMPORT_PASS\n')
    assert not(shared/'__init__.py').exists()and not list(m.WORKER.rglob('__pycache__'))


def test_namespace_state_cannot_change_across_protected_acceptance(job):
    m,_,_,before=job;m.C['worker_optional_packages']={'shared':{'scope':'fixture'}}
    before['snapshot']['worker_packages']={'shared':{'initializer':None}}
    baseline=copy.deepcopy(before['snapshot']);current=copy.deepcopy(baseline);current['worker_packages']['shared']['initializer']={'unexpected':True}
    m.snapshot=lambda:copy.deepcopy(current)
    r={'before':before,'activated_at':None,'created_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    with pytest.raises(ValueError,match='PRESERVATION_WORKER_PACKAGES'):m.protected(r)
    assert not m.CHANGED


def test_no_initializer_install_backup_or_rollback_deletion(package):
    _,_,_,c=package;initializer='src/shared/__init__.py'
    assert initializer not in c['worker_before']and 'worker/'+initializer not in c['files']
    assert set(c['worker_change'])==set(original_manifest()['config']['worker_change'])|{'src/shared/forecast_evaluation.py','src/shared/forecast_publication.py'}
    assert (HERE/'transaction.py').read_bytes()==(HERE.with_name('realized-performance-release-v2')/'transaction.py').read_bytes()


def test_namespace_predecessor_to_candidate_transition_checks_every_required_module(package_fixture):
    m,shared=package_fixture;rel='src/models/next24h_monitoring.py'
    originals={key:m.raw_file('worker/'+key)for key in m.C['worker_before']}
    for key,expected in m.C['worker_before'].items():
        path=m.WORKER/key
        if key==rel:path.write_bytes((HERE/'baseline/next24h_monitoring.py').read_bytes())
        elif expected is None:path.unlink()
    state=m.worker_state(False)
    assert state[rel]['sha256']=='fb9fc1004c79e7888a9b762bfae73cdeec7038c025718dffb5cd21dfa8397bfd'
    for key,raw in originals.items():
        (m.WORKER/key).write_bytes(raw);(m.WORKER/key).chmod(0o644)
    result=m.worker_state(True)
    assert result[rel]['sha256']==m.C['files']['worker/'+rel]['sha256']
    assert not(shared/'__init__.py').exists()


def test_optional_initializer_policy_is_fixed_and_source_bound(package_fixture):
    m,_=package_fixture;m.C['worker_optional_packages']['shared']['initializer']='src/shared/other.py'
    with pytest.raises(ValueError,match='WORKER_OPTIONAL_PACKAGE_SCOPE'):m.optional_package_state()


@pytest.mark.parametrize('field',['st_uid','st_gid'])
def test_namespace_directory_identity_enforced(package_fixture,monkeypatch,field):
    m,shared=package_fixture;previous=Path.lstat
    def changed(path):
        s=previous(path)
        if path==shared:
            values=dict(vars(s));values[field]=777;return types.SimpleNamespace(**values)
        return s
    monkeypatch.setattr(Path,'lstat',changed)
    with pytest.raises(ValueError):m.optional_package_state()


def test_namespace_drift_blocks_rollback_before_mutation(job):
    m,_,_,before=job;m.apply();record=m.load_record()
    m.C['worker_optional_packages']={'shared':{'scope':'fixture'}}
    # A journal from a real V3 fresh gate must contain package-state evidence.
    # An absent baseline is rejected; do not infer it from current state.
    with pytest.raises(ValueError,match='PRESERVATION_WORKER_PACKAGES'):m.rollback()
    assert m.load_record()['phase']=='APPLIED'


def host_layout(m):
    for rel,expected in m.C['worker_before'].items():
        path=m.WORKER/rel
        if rel=='src/models/next24h_monitoring.py':path.write_bytes((HERE/'baseline/next24h_monitoring.py').read_bytes())
        elif expected is None:
            if path.exists():path.unlink()
    return m.worker_state(False)


def test_complete_audit_and_exact_two_new_payloads(package):
    b,_,_,c=package;audit=json.loads((HERE/'DEPENDENCY-AUDIT.json').read_bytes());rows=audit['rows']
    assert len(rows)==15 and len({r['identifier']for r in rows})==15
    assert sum(r['classification']=='MANDATORY_EXISTING'for r in rows)==12
    assert sum(r['classification']=='OPTIONAL_NAMESPACE_INITIALIZER'for r in rows)==1
    assert {r['identifier']for r in rows if r['classification']=='REQUIRED_NEW_PAYLOAD'}==b.NEW_DEPENDENCIES
    assert sum(r['category']=='FILE_MISSING'for r in rows)==3 and audit['file_contents_read']is False
    assert len(c['worker_dependencies'])==12 and len(c['worker_change'])==7
    original=original_manifest()['config']
    assert {k:v for k,v in c['files'].items()if k not in {'worker/'+r for r in b.NEW_DEPENDENCIES}}==original['files']
    for rel in b.NEW_DEPENDENCIES:
        assert c['worker_before'][rel]is None
        assert c['files']['worker/'+rel]==original['files']['api/'+rel]
        assert rel not in c['worker_dependencies']


def test_full_host_layout_preflight_overlay_and_post_install(package_fixture):
    m,shared=package_fixture;before=host_layout(m)
    new={'src/shared/forecast_evaluation.py','src/shared/forecast_publication.py'}
    assert all(before[r]is None and not(m.WORKER/r).exists()for r in new)
    code,locations=m.sources('worker')
    for rel in new:assert code['shared.'+Path(rel).stem][0]==m.raw_file('worker/'+rel).decode()
    assert m.optional_package_state()['shared']['initializer']is None
    with pytest.raises(m.DependencyInventoryFailure)as e:m.worker_state(True)
    missing={r['identifier']for r in e.value.dependency_issues}
    assert new<=missing
    for rel in m.C['worker_change']:
        (m.WORKER/rel).write_bytes(m.raw_file('worker/'+rel));(m.WORKER/rel).chmod(0o644)
    m.worker_state(True)
    assert not(shared/'__init__.py').exists()


def test_all_dependency_failures_reported_once_and_source_scoped(package_fixture,package):
    m,_=package_fixture;host_layout(m)
    missing='src/ingestion/fetch_weather_data.py';changed='src/models/backtesting.py';bad_mode='src/shared/operational_evidence.py'
    (m.WORKER/missing).unlink();(m.WORKER/changed).write_text('unexpected content');(m.WORKER/bad_mode).chmod(0o600)
    with pytest.raises(m.DependencyInventoryFailure)as caught:m.worker_state(False)
    issues=caught.value.dependency_issues
    assert {r['identifier']for r in issues}=={missing,changed,bad_mode}
    assert len(issues)==3
    assert {r['category']for r in issues}=={'MISSING','HASH_OR_SIZE_MISMATCH','METADATA_MISMATCH'}
    m.OLD=types.SimpleNamespace(H=types.SimpleNamespace(OP=types.SimpleNamespace(InvalidEvidence=ValueError),OLD_PLAN=types.SimpleNamespace(Stop=ValueError)))
    m.PREFLIGHT_STAGE='WORKER_INVENTORY';report=m.failure_report(caught.value)
    assert report['reason']=='WORKER_DEPENDENCY_INVENTORY'and report['dependency_issues']==issues
    b,p,_,c=package;payload=b.assemble('preflight',p,c)
    accepted=load('run').validate_report(report,payload)
    assert accepted['preflight_stage']=='WORKER_INVENTORY'
    assert str(m.WORKER)not in json.dumps(accepted)


@pytest.mark.parametrize('field,value',[('identifier','src/secrets.py'),('identifier','/private/secret'),('gate','SECRET_VALUE'),('stage','UNKNOWN'),('category','UNKNOWN')])
def test_dependency_failure_response_rejects_unapproved_fields(package,field,value):
    b,p,_,c=package;payload=b.assemble('preflight',p,c);r=load('run')
    item={'identifier':next(iter(c['worker_dependencies'])),'stage':'DEPENDENCY','category':'MISSING','gate':'WORKER_DEPENDENCY_INVENTORY'}
    report={'status':'BLOCKED','changed':False,'reason':'WORKER_DEPENDENCY_INVENTORY','preflight_stage':'WORKER_INVENTORY','dependency_issues':[item]}
    assert r.validate_report(report,payload)==report
    changed=copy.deepcopy(report);changed['dependency_issues'][0][field]=value
    with pytest.raises(AssertionError):r.validate_report(changed,payload)


def test_private_exception_values_never_escape_inventory(package_fixture):
    m,_=package_fixture;host_layout(m);previous=m.P.snap
    def failed(path,*args):
        if str(path).endswith('src/ingestion/fetch_weather_data.py'):raise PermissionError(13,'SECRET_TOKEN private value','/private/do-not-disclose')
        return previous(path,*args)
    m.P.snap=failed
    with pytest.raises(m.DependencyInventoryFailure)as caught:m.worker_state(False)
    raw=json.dumps(caught.value.dependency_issues)
    assert all(s not in raw for s in ['SECRET_TOKEN','private value','/private/do-not-disclose'])
    assert caught.value.dependency_issues[0]['category']=='PERMISSION_DENIED'


@pytest.mark.parametrize('rel',['src/shared/forecast_evaluation.py','src/shared/forecast_publication.py'])
def test_new_dependency_present_before_apply_or_missing_after_install_blocks(package_fixture,rel):
    m,_=package_fixture;host_layout(m)
    (m.WORKER/rel).write_bytes(m.raw_file('worker/'+rel));(m.WORKER/rel).chmod(0o644)
    with pytest.raises(m.DependencyInventoryFailure)as caught:m.worker_state(False)
    assert any(i['identifier']==rel and i['category']=='UNEXPECTED_PRESENT'for i in caught.value.dependency_issues)
    (m.WORKER/rel).unlink()
    with pytest.raises(m.DependencyInventoryFailure)as caught:m.worker_state(True)
    assert any(i['identifier']==rel and i['category']=='MISSING'for i in caught.value.dependency_issues)


def extend_transaction(m,before,package):
    c=package[3];rel='src/models/next24h_monitoring.py';raw=(HERE/'baseline/next24h_monitoring.py').read_bytes()
    (m.WORKER/rel).write_bytes(raw);m.C['worker_before'][rel]=c['worker_before'][rel];before['worker'][rel]=m.P.snap(m.WORKER/rel,1000,1000,0o644)[0]
    for rel in c['worker_before']:
        m.C['files']['worker/'+rel]=copy.deepcopy(c['files']['worker/'+rel])
        if rel not in m.C['worker_before']:
            m.C['worker_before'][rel]=copy.deepcopy(c['worker_before'][rel]);before['worker'][rel]=None
    return raw


def test_seven_worker_files_and_new_dependency_absence_rollback(job,package):
    m,state,calls,before=job;original=extend_transaction(m,before,package)
    assert m.apply()['status']=='APPLIED'
    record=m.load_record();assert len(record['before']['worker'])==7;m.verify_backups(record)
    for rel in package[0].NEW_DEPENDENCIES:
        assert record['before']['worker'][rel]is None
        assert(m.WORKER/rel).read_bytes()==m.raw_file('worker/'+rel)
        assert not m.backup_name(rel,'backup').exists()and not m.backup_name(rel,'independent').exists()
    assert m.rollback()['status']=='ROLLED_BACK'
    assert all(not(m.WORKER/rel).exists()for rel in package[0].NEW_DEPENDENCIES)
    assert(m.WORKER/'src/models/next24h_monitoring.py').read_bytes()==original
    assert m.backup_name('src/models/next24h_monitoring.py','backup').read_bytes()==original


@pytest.mark.parametrize('rel',['src/shared/forecast_evaluation.py','src/shared/forecast_publication.py'])
def test_corrupted_new_dependency_blocks_rollback_without_deletion(job,package,rel):
    m,_,_,before=job;extend_transaction(m,before,package);m.apply();path=m.WORKER/rel;path.write_bytes(b'unexpected change')
    with pytest.raises(ValueError,match='ROLLBACK_WORKER_DRIFT'):m.rollback()
    assert path.read_bytes()==b'unexpected change'and m.load_record()['phase']=='APPLIED'


def test_input_missing_report_retains_only_fixed_relative_id(package_fixture):
    m,_=package_fixture
    with pytest.raises(m.DependencyInventoryFailure)as caught:m.input_bounds()
    assert caught.value.dependency_issues[0]['identifier']=='data/reports/next24h_forecast_history.csv'
    assert caught.value.dependency_issues[0]['stage']=='INPUT'


def test_every_project_import_has_exactly_one_deployment_classification(package):
    b,_,_,c=package;installed=set(c['worker_before']);existing=set(c['worker_dependencies']);optional={v['initializer']for v in c['worker_optional_packages'].values()}
    assert not installed&existing and not installed&optional and not existing&optional
    assert installed|existing|optional=={v['path']for v in c['worker_closure'].values()}
    assert len(installed)==7 and len(existing)==12 and optional=={'src/shared/__init__.py'}
    assert {k[7:]for k in c['files']if k.startswith('worker/')}==installed


def test_all_issue_response_retained_in_one_bounded_runner_invocation(package,tmp_path,monkeypatch):
    b,p,_,c=package;r=load('run');payload=b.assemble('preflight',p,c);private=tmp_path/'private';(private/'preflight').mkdir(parents=True)
    issues=[{'identifier':rel,'stage':'DEPENDENCY','category':'MISSING','gate':'WORKER_DEPENDENCY_INVENTORY'}for rel in list(c['worker_dependencies'])[:3]]
    report={'status':'BLOCKED','phase':'READ_ONLY','changed':False,'reason':'WORKER_DEPENDENCY_INVENTORY','preflight_stage':'WORKER_INVENTORY','dependency_issues':issues}
    calls=[]
    wrapper=types.SimpleNamespace(PRIVATE=private,profile=lambda:{'verified':True},ssh_argv=lambda _:['/usr/bin/ssh','pinned.invalid','old-command'])
    def run(argv,**kw):
        calls.append(argv);return{'returncode':1,'failure':None,'stdout':json.dumps(report).encode(),'stderr':b'PRIVATE RAW NOT RETAINED'}
    monkeypatch.setattr(r,'verify',lambda *_:(payload,wrapper,types.SimpleNamespace(bounded_run=run)))
    monkeypatch.setattr(sys,'argv',['run.py','preflight','--manifest-sha256','a'*64])
    assert r.main()==1 and len(calls)==1
    evidence=next((private/'preflight').glob('*/assessment.json'));value=json.loads(evidence.read_bytes())
    assert value['report']['dependency_issues']==issues and value['failure']is None
    assert b'PRIVATE RAW'in b'PRIVATE RAW NOT RETAINED'and 'PRIVATE RAW'not in evidence.read_text()
