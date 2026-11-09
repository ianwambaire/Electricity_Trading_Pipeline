"""Offline reporting-only diagnostics. No SSH, real credentials or source requests."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import pytest
ROOT=Path(__file__).parents[1];HERE=ROOT/'deploy/staging/live-forecast-import-diagnostic-v1'
def load(name):
    s=importlib.util.spec_from_file_location('diag_'+name,HERE/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
@pytest.fixture(scope='module')
def parent():
    b=load('build');prefix,_,_,original=b.parent();return b,prefix,original
def fixture_script(original,app=None,policy=None):
    app=app if app is not None else "from types import SimpleNamespace as N\nForecastPublication=N(model_fields={'availability_policy','refresh_due_at'})\napp=N(routes=[N(path=p)for p in ['/forecast/next24','/operations/current','/pipeline/current','/admin/operations/current']])"
    sources={'api':('',True),'api.app':(app,False),'shared':('',True),'shared.forecast_availability':(policy or "import datetime\nAVAILABILITY_POLICY='ISSUE_HORIZON_V1'\nSERVING_HORIZON=datetime.timedelta(hours=24)",False),'shared.forecast_publication':("import datetime\nMAX_AGE=datetime.timedelta(hours=3)",False)}
    tree=ast.parse(original);tree.body[4].value=ast.parse(repr(sources),mode='eval').body;return ast.unparse(ast.fix_missing_locations(tree)).encode()
def run_child(script,simulate=True):
    if simulate:script=script.replace(b'import sys,os,json,re\n',b'import sys,os,json,re\nos.getuid=os.geteuid=os.getgid=os.getegid=lambda:992\n',1)
    return subprocess.run([sys.executable,'-I','-B','-'],input=script,capture_output=True,timeout=15,env={'PATH':'/usr/bin:/bin','LANG':'C','MPLBACKEND':'Agg'})
def report(child):
    assert child.stderr==b''
    out=json.loads(child.stdout);assert len(child.stdout)<4096
    assert (child.returncode==0)==(out['status']=='PASS')
    return out
def test_original_and_instrumented_success_have_same_import_guards(parent):
    _,_,original=parent;source=fixture_script(original);diag=load('child').instrument(source)
    native=source.replace(b'import sys, os, json, importlib.abc, importlib.util',b'import sys, os, json, importlib.abc, importlib.util\nos.getuid=os.geteuid=os.getgid=os.getegid=lambda:992',1)
    old=subprocess.run([sys.executable,'-I','-B','-'],input=native,capture_output=True,timeout=15,env={'PATH':'/usr/bin:/bin'})
    assert old.returncode==0 and old.stdout==b'CANDIDATE_IMPORT_PASS\n'
    r=report(run_child(diag));assert r['status']=='PASS' and r['stage']=='COMPLETE'
def test_all_original_ast_nodes_ordered_unmodified_and_no_source_changes(parent):
    _,_,original=parent;diag=load('child').instrument(original)
    tree=ast.parse(diag);wrapped=next(n for n in tree.body if isinstance(n,ast.Try))
    actual=[n for n in wrapped.body if not(isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id.startswith('__diag_')for t in n.targets))]
    assert [ast.dump(n,include_attributes=False)for n in actual]==[ast.dump(n,include_attributes=False)for n in ast.parse(original).body]
    assert diag==load('child').instrument(original)
    assert b"module.__file__ = '<verified-candidate>'"in diag
@pytest.mark.parametrize('code,category,exc',[
 ("raise ModuleNotFoundError('PRIVATE_MESSAGE',name='fastapi.fixture_missing')",'MODULE_MISSING','ModuleNotFoundError'),
 ("raise ImportError('PRIVATE_MESSAGE',name='pydantic')",'IMPORT_ERROR','ImportError'),
 ("raise PermissionError(13,'PRIVATE_MESSAGE','/PRIVATE_HOST/PASSWORD')",'PERMISSION_DENIED','PermissionError'),
 ("raise FileNotFoundError(2,'PRIVATE_MESSAGE','/PRIVATE_HOST/PASSWORD')",'FILE_MISSING','FileNotFoundError'),
 ("raise AttributeError('PRIVATE_MESSAGE')",'ATTRIBUTE_ERROR','AttributeError'),
 ("raise TypeError('PRIVATE_MESSAGE')",'TYPE_ERROR','TypeError'),
 ("raise ValueError('PRIVATE_MESSAGE')",'VALUE_ERROR','ValueError'),
 ("raise NameError('PRIVATE_MESSAGE')",'UNCLASSIFIED_FAILURE','NameError'),
 ("raise RuntimeError('PRIVATE_MESSAGE')",'UNCLASSIFIED_FAILURE','RuntimeError')])
def test_sanitized_import_failure(parent,code,category,exc):
    _,_,original=parent;r=report(run_child(load('child').instrument(fixture_script(original,app=code))))
    assert r['stage']=='API_IMPORT' and r['category']==category and r['exception']==exc
    assert r['candidate_module']=='api.app' and r['line']==1
    assert all(s not in json.dumps(r)for s in ['PRIVATE_MESSAGE','PRIVATE_HOST','PASSWORD'])
def test_unknown_import_name_redacted(parent):
    _,_,s=parent;code="raise ModuleNotFoundError('PRIVATE',name='api.password_secret_token')"
    r=report(run_child(load('child').instrument(fixture_script(s,app=code))))
    assert r['import_name']=='REDACTED_MODULE' and 'password'not in json.dumps(r)
@pytest.mark.parametrize('policy,app,stage',[
 ("import datetime\nAVAILABILITY_POLICY='WRONG'\nSERVING_HORIZON=datetime.timedelta(hours=24)",None,'POLICY_CHECK'),
 (None,"from types import SimpleNamespace as N\nForecastPublication=N(model_fields={})\napp=N(routes=[])",'SCHEMA_CHECK'),
 (None,"from types import SimpleNamespace as N\nForecastPublication=N(model_fields={'availability_policy','refresh_due_at'})\napp=N(routes=[])",'ROUTES_CHECK')])
def test_policy_schema_route_assertions_not_weakened(parent,policy,app,stage):
    _,_,s=parent;r=report(run_child(load('child').instrument(fixture_script(s,app=app,policy=policy))))
    assert r['status']=='BLOCKED' and r['stage']==stage and r['exception']=='AssertionError'
def test_native_wrong_identity_fails_closed(parent):
    _,_,s=parent;r=report(run_child(load('child').instrument(fixture_script(s)),simulate=False))
    if os.getuid()!=992:assert r['category']=='IDENTITY_MISMATCH' and r['stage']=='RUNTIME_IDENTITY'
@pytest.mark.parametrize('code,event,category',[
 ("open('/PRIVATE_HOST/CREDENTIALS','w')",'open','FILESYSTEM_WRITE_BLOCKED'),
 ("import os\nos.mkdir('/PRIVATE_HOST/CREDENTIALS')",'os.mkdir','SIDE_EFFECT_BLOCKED'),
 ("import socket\nsocket.create_connection(('127.0.0.1',1))",'socket.connect','SIDE_EFFECT_BLOCKED'),
 ("import subprocess\nsubprocess.run(['/usr/bin/true'])",'subprocess.Popen','SIDE_EFFECT_BLOCKED')])
def test_mutation_and_network_audit_guards_block_before_side_effect(parent,code,event,category):
    _,_,s=parent;r=report(run_child(load('child').instrument(fixture_script(s,app=code))))
    assert r['category']==category and r['audit_event']==event and r['exception']=='RuntimeError'
    assert 'PRIVATE_HOST'not in json.dumps(r)
def test_extra_stdout_not_accepted_or_disclosed(parent):
    _,_,s=parent;source=fixture_script(s,app="print('PRIVATE_SECRET_TEXT')\n"+ast.literal_eval(ast.parse(fixture_script(s)).body[4].value)['api.app'][0])
    r=report(run_child(load('child').instrument(source)))
    assert r['category']=='UNEXPECTED_STDOUT' and r['status']=='BLOCKED' and 'PRIVATE_SECRET_TEXT'not in json.dumps(r)
def test_stderr_output_bound_not_weakened(parent):
    _,_,s=parent;good=ast.literal_eval(ast.parse(fixture_script(s)).body[4].value)['api.app'][0]
    r=report(run_child(load('child').instrument(fixture_script(s,app="import sys\nsys.stderr.write('PRIVATE'*2000)\n"+good))))
    assert r['category']=='CHILD_OUTPUT_LIMIT' and 'PRIVATE'not in json.dumps(r)
def test_original_parent_binding_and_actual_candidate_imports_locally(parent):
    b,p,s=parent;assert b.sha((HERE.parent/'live-forecast-reliability-release-v1/MANIFEST.json').read_bytes())==b.PARENT_SHA
    r=report(run_child(load('child').instrument(s)));assert r['status']=='PASS'
def inspector(parent):
    _,_,original=parent;m=load('inspect');c=load('child')
    m.need=lambda ok,code:None if ok else (_ for _ in ()).throw(ValueError(code))
    m.MODULES=tuple(ast.literal_eval(ast.parse(original).body[4].value));m.STDLIB=tuple(sys.stdlib_module_names);m.DEPENDENCIES=c.DEPENDENCIES
    return m
@pytest.mark.parametrize('failure,category',[('TIMEOUT','CHILD_TIMEOUT'),('OUTPUT_LIMIT','CHILD_OUTPUT_LIMIT')])
def test_supervisor_bounds(parent,failure,category):
    m=inspector(parent);r=m.classify({'failure':failure,'returncode':-15,'stdout':b'PRIVATE','stderr':b'PRIVATE'})
    assert r['category']==category and 'PRIVATE'not in json.dumps(r)
@pytest.mark.parametrize('stderr,category',[
 (b'nsenter: /PRIVATE_HOST: Operation not permitted','NAMESPACE_ENTRY_DENIED'),
 (b'setpriv: /PRIVATE_HOST failure','IDENTITY_LAUNCH_FAILED'),
 (b'/PRIVATE_HOST: No such file or directory','EXECUTABLE_OR_NAMESPACE_MISSING'),
 (b'PRIVATE_HOST','CHILD_OUTPUT_UNVERIFIED')])
def test_startup_failures_never_expose_raw_stderr(parent,stderr,category):
    r=inspector(parent).classify({'failure':None,'returncode':1,'stdout':b'','stderr':stderr})
    assert r['category']==category and 'PRIVATE_HOST'not in json.dumps(r)
def test_untrusted_module_or_malformed_child_report_rejected(parent):
    m=inspector(parent);valid=report(run_child(load('child').instrument(fixture_script(parent[2]))))
    for mutate in [lambda r:r.update(module='/PRIVATE_HOST/password'),lambda r:r.update(candidate_module='api.secret_token'),lambda r:r.update(extra='PRIVATE'),lambda r:r.update(line=-1),lambda r:r.update(exception='PASSWORD_SECRET')]:
        r=dict(valid);mutate(r);out=m.classify({'failure':None,'returncode':0,'stdout':json.dumps(r,sort_keys=True).encode()+b'\n','stderr':b''})
        assert out['category']=='CHILD_OUTPUT_UNVERIFIED' and 'PRIVATE'not in json.dumps(out)
@pytest.mark.parametrize('mode',['success','child_failure','early_guard','late_guard'])
def test_full_parent_reporting_overlay_one_child_no_retries_restore(parent,mode):
    m=inspector(parent);calls=[];good=report(run_child(load('child').instrument(fixture_script(parent[2]))))
    if mode=='child_failure':good.update(status='BLOCKED',stage='API_IMPORT',category='ATTRIBUTE_ERROR',exception='AttributeError')
    class Stop(ValueError):pass
    m.need=lambda ok,code:None if ok else (_ for _ in ()).throw(Stop(code));m.PLAN=types.SimpleNamespace(Stop=Stop);m.GUARD=types.SimpleNamespace(Stop=Stop);m.HELPER=types.SimpleNamespace(OP=types.SimpleNamespace(InvalidEvidence=Stop))
    original=lambda _:None
    job=types.SimpleNamespace(import_probe=original,H=types.SimpleNamespace(OLD_PLAN=types.SimpleNamespace(UNIT='powerflow-candidate-api.service')))
    def bounded(argv,**kw):
        calls.append((argv,kw));return {'failure':None,'returncode':0 if mode!='child_failure'else 1,'stdout':json.dumps(good,sort_keys=True).encode()+b'\n','stderr':b'PRIVATE_NOT_RETAINED'}
    job.B={'services':lambda:{'powerflow-candidate-api.service':{'MainPID':'123'}},'bounded_run':bounded}
    def fresh():
        if mode=='early_guard':raise Stop('PIPELINE_OR_WINDOW_GATE')
        job.import_probe(Path('/APPROVED/runtime'))
        if mode=='late_guard':raise Stop('POST_IMPORT_GUARD')
    job.fresh=fresh;m.JOB=job;m.CHILD=b'fixed-script';m.RELEASE='diagnostic';m.PARENT_SHA=parent[0].PARENT_SHA
    r=m.inspect();assert job.import_probe is original and len(calls)==(0 if mode=='early_guard'else 1)
    assert r['changed']is False and 'PRIVATE_NOT_RETAINED'not in json.dumps(r)
    if mode=='success':assert r['status']=='PASS'
    else:assert r['status']=='BLOCKED'
    if mode=='late_guard':assert r['category']=='POST_IMPORT_GUARD' and r['child_status']=='PASS'
    if mode=='early_guard':assert r['category']=='PIPELINE_OR_WINDOW_GATE' and r['child_status']=='NOT_REACHED'
    if calls:
        argv,kw=calls[0];assert argv[:3]==['/usr/bin/nsenter','--mount=/proc/123/ns/mnt','--']
        assert '--no-new-privs'in argv and '--clear-groups'in argv and '-I'in argv and '-B'in argv
        assert kw=={'input':b'fixed-script','timeout':20,'limit':8192,'grace':5}
def test_payload_no_mutation_entrypoints_and_integrity_reproducible(parent):
    b,p,s=parent;blobs={n:b.read(HERE/n)for n in b.FILES};a,child=b.assemble(p,s,blobs)
    assert (a,child)==b.assemble(p,s,blobs);ast.parse(a,feature_version=(3,9));ast.parse(child,feature_version=(3,9))
    assert b'<verified-reliability-transaction>'not in a
    if (HERE/'MANIFEST.json').exists():
        m=json.loads((HERE/'MANIFEST.json').read_bytes());assert b.sha(a)==m['payload_sha256'] and a==(HERE/'inspect.payload.py').read_bytes()
def test_immutable_emission_never_refreshes_existing_outputs(tmp_path):
    b=load('build');p=tmp_path/'old';q=tmp_path/'new';p.write_bytes(b'old')
    with pytest.raises(AssertionError):b.emit({q:b'new',p:b'new'})
    assert not q.exists() and p.read_bytes()==b'old'

def test_environment_canary_and_custom_exception_names_are_not_exposed(parent):
    _,_,s=parent
    source=fixture_script(s,app="import os\nraise ValueError(os.environ['DIAGNOSTIC_CANARY'])")
    script=load('child').instrument(source).replace(b'import sys,os,json,re\n',b'import sys,os,json,re\nos.getuid=os.geteuid=os.getgid=os.getegid=lambda:992\n',1)
    r=subprocess.run([sys.executable,'-I','-B','-'],input=script,capture_output=True,timeout=15,env={'PATH':'/usr/bin:/bin','DIAGNOSTIC_CANARY':'PRIVATE_ENVIRONMENT_VALUE'})
    data=report(r);assert data['category']=='VALUE_ERROR' and b'PRIVATE_ENVIRONMENT_VALUE'not in r.stdout
    r=report(run_child(load('child').instrument(fixture_script(s,app="class PRIVATE_SECRET_EXCEPTION(Exception):pass\nraise PRIVATE_SECRET_EXCEPTION('PRIVATE_MESSAGE')"))))
    assert r['exception']=='UNCLASSIFIED_EXCEPTION' and 'PRIVATE'not in json.dumps(r)

def test_local_only_mode_never_builds_ssh_arguments(monkeypatch,capsys):
    m=load('run');calls=[]
    wrapper=types.SimpleNamespace(profile=lambda:(calls.append('identity')or{}),ssh_argv=lambda _:pytest.fail('SSH forbidden'))
    monkeypatch.setattr(m,'verify',lambda *_:(b'payload',wrapper,None));monkeypatch.setattr(sys,'argv',['run.py','--manifest-sha256','0'*64,'--local-check'])
    assert m.main()==0 and calls==['identity'] and json.loads(capsys.readouterr().out)['ssh_attempts']==0

def test_native_stdout_whitespace_cannot_bypass_original_exact_output_guard(parent):
    _,_,s=parent;good=ast.literal_eval(ast.parse(fixture_script(s)).body[4].value)['api.app'][0]
    raw=run_child(load('child').instrument(fixture_script(s,app="import os\nos.write(1,b'\\n')\n"+good)))
    out=inspector(parent).classify({'failure':None,'returncode':raw.returncode,'stdout':raw.stdout,'stderr':raw.stderr})
    assert out['status']=='BLOCKED' and out['category']=='CHILD_OUTPUT_UNVERIFIED'
