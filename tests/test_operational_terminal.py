"""Offline terminal lifecycle: no Prefect engine, SSH, sudo, network or live data."""
import ast
import contextlib
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from shared import operational_capture as capture
from shared import operational_evidence as c
from shared import operational_evidence_store as store
from shared import operational_terminal as terminal
from shared.operational_evidence_producer import associate
from test_current_operations import association, summary, make_withheld, NOW, FLOW
from test_operational_evidence import root_at, encoded, fixture as op_fixture

STATE='66666666-6666-4666-8666-666666666666'
ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def stable(association):
    a=association
    a['flow'].update(deployment_id=capture.DEPLOYMENT,run_count=1)
    a['flow']['state']['id']=STATE
    a['expected_deployment']=capture.DEPLOYMENT
    proof=json.loads(a['receipts'][0]['evidence.json'])
    summary(a,prefect_flow_run_id=FLOW,prefect_deployment_id=capture.DEPLOYMENT,
            next24h_prefect_task_run_id=a['tasks'][0]['id'],next24h_inference_receipt_id=proof['execution']['run_id'])
    a['stable_identity']=True
    return a


@pytest.fixture(autouse=True)
def no_network_or_subprocess(monkeypatch):
    import socket
    monkeypatch.setattr(socket,'create_connection',lambda *a,**k:pytest.fail('Unexpected network'))
    monkeypatch.setattr(terminal.subprocess,'Popen',lambda *a,**k:pytest.fail('Unexpected subprocess'))


def test_stable_identity_does_not_depend_on_two_second_proximity(stable):
    # Real wrapper encloses task queueing/engine/retries, not the other way round.
    stage=stable['stages'][0]
    stage['start_timestamp_utc']=stable['flow']['start_time']
    stage['end_timestamp_utc']=stable['flow']['end_time']
    stable['tasks'][0]['run_count']=3
    b=c.validate(*associate(**stable),NOW)
    assert b['execution']['pipeline_run_id']=='a'*32 and b['inference']['outcome']=='GENERATED'


@pytest.mark.parametrize('kind',['missing_flow','wrong_flow','wrong_deployment','wrong_task','duplicate_internal','wrong_receipt','stage_excludes_task','flow_retry_records'])
def test_stable_association_conflicts_fail_closed(stable,kind):
    if kind=='missing_flow':summary(stable,prefect_flow_run_id=None)
    elif kind=='wrong_flow':summary(stable,prefect_flow_run_id=STATE)
    elif kind=='wrong_deployment':summary(stable,prefect_deployment_id=STATE)
    elif kind=='wrong_task':summary(stable,next24h_prefect_task_run_id=STATE)
    elif kind=='duplicate_internal':stable['stages']*=2
    elif kind=='wrong_receipt':summary(stable,next24h_inference_receipt_id=STATE)
    elif kind=='stage_excludes_task':stable['stages'][0]['start_timestamp_utc']=stable['flow']['end_time']
    else:stable['records'].append(copy.deepcopy(stable['records'][0]))
    with pytest.raises(c.InvalidEvidence):associate(**stable)


def fixture_source(a,tmp_path,monkeypatch):
    root=tmp_path.resolve()/'producer';(root/'database').mkdir(parents=True)
    database=root/'database/electricity_trading.db'
    connection=sqlite3.connect(database)
    connection.executescript('CREATE TABLE pipeline_runs(id INTEGER PRIMARY KEY,run_time TEXT,status TEXT,message TEXT); CREATE TABLE pipeline_stage_timings(run_id TEXT,stage_name TEXT,start_timestamp_utc TEXT,end_timestamp_utc TEXT,status TEXT); CREATE TABLE operational_incidents(timestamp_utc TEXT,component TEXT,event_type TEXT,details_json TEXT);')
    for n,r in enumerate(a['records']):connection.execute('INSERT INTO pipeline_runs VALUES (?,?,?,?)',(n,r['run_time'],r['status'],r['message']))
    for s in a['stages']:connection.execute('INSERT INTO pipeline_stage_timings VALUES (?,?,?,?,?)',tuple(s[k] for k in ['run_id','stage_name','start_timestamp_utc','end_timestamp_utc','status']))
    for r in a['incidents']:connection.execute('INSERT INTO operational_incidents VALUES (?,?,?,?)',tuple(r[k] for k in ['timestamp_utc','component','event_type','details_json']))
    connection.commit();connection.close()
    if a['receipts']:
        receipt=json.loads(a['receipts'][0]['integrity.json'])['run_id']
        folder=root/'data/reports/next24h_inference'/receipt;folder.mkdir(parents=True,mode=0o700)
        for name,raw in a['receipts'][0].items():(folder/name).write_bytes(raw);(folder/name).chmod(0o600)
    actual=sqlite3.connect
    def connect(database_uri,**kwargs):
        assert database_uri.startswith('file:/proc/self/fd/') and database_uri.endswith('?mode=ro&immutable=1')
        return actual(database.as_uri()+'?mode=ro&immutable=1',**kwargs)
    monkeypatch.setattr(capture.sqlite3,'connect',connect)
    return capture.Source(root,owner=os.geteuid()),database


def source_api(a,changed=False):
    calls=[]
    def api(identity,tasks=False):
        assert identity==a['flow']['id'];calls.append(tasks)
        value=copy.deepcopy(a['tasks'] if tasks else a['flow'])
        if changed and len(calls)==3:value['state']['id']=FLOW
        return value
    return api,calls


def test_terminal_capture_reads_durable_facts_and_rechecks_state(stable,tmp_path,monkeypatch):
    source,db=fixture_source(stable,tmp_path,monkeypatch);before=db.read_bytes();api,calls=source_api(stable)
    raw,digest=capture.capture_terminal(FLOW,STATE,source=source,api=api,clock=lambda:NOW)
    b=c.validate(raw,digest,NOW)
    assert b['delivery']['outcome']=='PUBLISHED' and b['delivery']['published_at'] is None
    assert calls==[False,True,False] and db.read_bytes()==before


@pytest.mark.parametrize('kind',['not_terminal','missing_end','state_changed','manual','missing_receipt','missing_summary','active_journal','receipt_symlink','source_changed','flow_retry'])
def test_capture_failures_do_not_repair_or_publish(stable,tmp_path,monkeypatch,kind):
    if kind=='missing_summary':stable['records']=[]
    source,db=fixture_source(stable,tmp_path,monkeypatch)
    if kind=='not_terminal':stable['flow']['state']['type']='RUNNING'
    elif kind=='missing_end':stable['flow']['end_time']=None
    elif kind=='manual':stable['flow']['auto_scheduled']=False
    elif kind=='missing_receipt':
        receipt=json.loads(stable['receipts'][0]['integrity.json'])['run_id'];(source.root/'data/reports/next24h_inference'/receipt/'model.json').unlink()
    elif kind=='active_journal':Path(str(db)+'-wal').write_bytes(b'active')
    elif kind=='receipt_symlink':
        receipt=json.loads(stable['receipts'][0]['integrity.json'])['run_id'];p=source.root/'data/reports/next24h_inference'/receipt/'model.json';p.unlink();p.symlink_to(db)
    elif kind=='source_changed':
        original=source.capture
        def mutate(*args):
            result=original(*args);os.utime(db,ns=(db.stat().st_atime_ns,db.stat().st_mtime_ns+1000));return result
        monkeypatch.setattr(source,'capture',mutate)
    elif kind=='flow_retry':stable['flow']['run_count']=2
    api,calls=source_api(stable,changed=kind=='state_changed')
    with pytest.raises((c.InvalidEvidence,OSError,TypeError)):
        capture.capture_terminal(FLOW,STATE,source=source,api=api,clock=lambda:NOW)
    assert len(calls)<=3


@pytest.mark.parametrize('status',['SKIPPED_WITHHELD','DISABLED'])
def test_withheld_terminal_capture_has_no_receipt_and_preserves_skip(stable,tmp_path,monkeypatch,status):
    make_withheld(stable);summary(stable,next24h_inference_receipt_id=None,next24h_publication_status=status)
    if status=='DISABLED':stable['tasks'].pop()
    source,_=fixture_source(stable,tmp_path,monkeypatch);api,_=source_api(stable)
    b=c.validate(*capture.capture_terminal(FLOW,STATE,source=source,api=api,clock=lambda:NOW),NOW)
    assert b['inference']['outcome']=='WITHHELD' and b['delivery']['outcome']==status


def test_failed_before_inference_preserves_failed_flow(stable,tmp_path,monkeypatch):
    stable['flow']['state']['type']='FAILED';stable['records'][0]['status']='FAILED';stable['tasks']=[];stable['receipts']=[]
    summary(stable,status='FAILED',next24h_prefect_task_run_id=None,next24h_inference_receipt_id=None,next24h_forecast_status='UNKNOWN',next24h_forecast_generated=None,next24h_publication_status='UNKNOWN')
    stable['stages'][0].update(stage_name='Total pipeline',start_timestamp_utc=stable['flow']['start_time'],end_timestamp_utc=stable['flow']['end_time'],status='FAILED')
    source,_=fixture_source(stable,tmp_path,monkeypatch);api,_=source_api(stable)
    b=c.validate(*capture.capture_terminal(FLOW,STATE,source=source,api=api,clock=lambda:NOW),NOW)
    assert b['execution']['outcome']=='FAILED' and b['inference']['outcome']=='UNKNOWN' and b['inference']['receipt_id'] is None


def test_terminal_store_duplicate_older_conflict_and_forecast_preservation(tmp_path):
    root=root_at(tmp_path);now=dt.datetime(2026,11,5,6,49,tzinfo=dt.timezone.utc)
    b=op_fixture();raw,digest=encoded(b)
    assert store.publish_terminal(root,raw,digest,clock=lambda:now)['status']=='PUBLISHED'
    b['observed_at']=now.isoformat();duplicate,newhash=encoded(b)
    assert store.publish_terminal(root,duplicate,newhash,clock=lambda:now)['status']=='SKIPPED_DUPLICATE'
    assert store.read_current(root,now=now)['evidence_id']==digest and not(root/'releases'/newhash).exists()
    older=copy.deepcopy(b);older['execution']['scheduled_at']='2026-11-05T05:45:00Z'
    assert store.publish_terminal(root,*encoded(older),clock=lambda:now)['status']=='SKIPPED_OLDER_RUN'
    b['execution']['outcome']='FAILED'
    with pytest.raises(c.InvalidEvidence,match='TERMINAL_DRIFT'):store.publish_terminal(root,*encoded(b),clock=lambda:now)
    assert store.read_current(root,now=now)['evidence_id']==digest


def test_terminal_atomic_failure_and_unavailable_store(tmp_path,monkeypatch):
    root=root_at(tmp_path);b=op_fixture();now=dt.datetime(2026,11,5,6,49,tzinfo=dt.timezone.utc)
    raw,old=encoded(b);store.publish_terminal(root,raw,old,clock=lambda:now)
    b['execution']['scheduled_at']='2026-11-05T06:46:00Z';b['execution']['started_at']='2026-11-05T06:46:01Z';b['execution']['flow_run_id']=STATE;b['provenance'].update(flow_run_id=STATE,task_flow_run_id=STATE)
    monkeypatch.setattr(store.os,'replace',lambda *a,**k:(_ for _ in ()).throw(OSError('private write error')))
    with pytest.raises(OSError):store.publish_terminal(root,*encoded(b),clock=lambda:now)
    assert store.read_current(root,now=now)['evidence_id']==old
    with pytest.raises(OSError):store.publish_terminal(tmp_path.resolve()/'absent',raw,old,clock=lambda:now)


@pytest.mark.parametrize('kind',['disabled','manual','failed_runner','published','duplicate','older','bad_result'])
def test_notification_isolated_and_never_changes_flow_state(kind):
    flow=SimpleNamespace(id=FLOW,deployment_id=capture.DEPLOYMENT,auto_scheduled=True,end_time=None)
    state=SimpleNamespace(id=STATE,type='FAILED');calls=[]
    def runner(*args):
        calls.append(args)
        if kind=='failed_runner':raise RuntimeError('TOKEN_PRIVATE')
        return {'status':dict(published='PUBLISHED',duplicate='SKIPPED_DUPLICATE',older='SKIPPED_OLDER_RUN').get(kind,'BOGUS')}
    if kind=='manual':flow.auto_scheduled=False
    result=terminal.notify(flow,state,enabled=kind!='disabled',runner=runner)
    assert state.type=='FAILED' and flow.end_time is None and 'TOKEN_PRIVATE' not in json.dumps(result)
    assert len(calls)==(0 if kind in {'disabled','manual'} else 1)
    assert result['status']==dict(disabled='DISABLED',manual='SKIPPED_NOT_NATURAL',published='PUBLISHED',duplicate='SKIPPED_DUPLICATE',older='SKIPPED_OLDER_RUN').get(kind,'FAILED')


def test_actual_hook_registration_and_missing_module_are_nonfatal(monkeypatch):
    # Extract only wrappers: no flow/task execution or application imports.
    tree=ast.parse((ROOT/'src/scheduled_pipeline.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='powerflow_entsoe_pipeline')
    decorator=next(n for n in function.decorator_list if isinstance(n,ast.Call) and getattr(n.func,'id',None)=='flow')
    assert {k.arg for k in decorator.keywords}>={'on_completion','on_failure'}
    hook=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_operational_evidence_terminal_hook')
    messages=[];namespace={'os':os,'json':json,'logger':SimpleNamespace(warning=lambda *a:messages.append(a))}
    exec(compile(ast.Module(body=[hook],type_ignores=[]),'<offline-hook>','exec'),namespace)
    monkeypatch.delenv('POWERFLOW_OPERATIONAL_EVIDENCE_ENABLED',raising=False)
    assert namespace[hook.name](None,None,None)=={'status':'DISABLED'}
    monkeypatch.setenv('POWERFLOW_OPERATIONAL_EVIDENCE_ENABLED','true')
    import builtins
    original=builtins.__import__
    def missing(name,*a,**kw):
        if name=='shared.operational_terminal':raise ImportError('private detail')
        return original(name,*a,**kw)
    monkeypatch.setattr(builtins,'__import__',missing)
    assert namespace[hook.name](None,None,None)=={'status':'FAILED','reason':'HOOK_UNAVAILABLE'}
    assert 'private detail' not in str(messages)


@pytest.mark.parametrize('status',[200,302,503])
def test_fixed_prefect_protocol_no_arbitrary_request_or_redirect(monkeypatch,status):
    calls=[]
    class Connection:
        def __init__(self,*a,**kw):calls.append((a,kw))
        def request(self,*a,**kw):calls.append((a,kw))
        def getresponse(self):return SimpleNamespace(status=status,getheader=lambda _: 'application/json',read=lambda _:b'[]')
        def close(self):calls.append('closed')
    monkeypatch.setattr(capture.http.client,'HTTPConnection',Connection)
    if status==200:assert capture.query(FLOW,tasks=True)==[]
    else:
        with pytest.raises(c.InvalidEvidence,match='PREFECT_HTTP'):capture.query(FLOW,tasks=True)
    assert calls[0]==(('127.0.0.1',4200),{'timeout':3})
    assert calls[1][0]==('POST','/api/task_runs/filter') and json.loads(calls[1][1]['body'])=={'task_runs':{'flow_run_id':{'any_':[FLOW]}},'limit':100}
    with pytest.raises(c.InvalidEvidence):capture.query('../../secrets')


def test_runtime_lifecycle_and_bootstrap_bindings():
    import importlib.util
    spec=importlib.util.find_spec('prefect');engine=Path(spec.origin).parent/'flow_engine.py'
    tree=ast.parse(engine.read_text())
    for cls in [n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in {'FlowRunEngine','AsyncFlowRunEngine'}]:
        method=next(n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='set_state')
        code=ast.unparse(method)
        assert code.index('propose_state')<code.index('call_hooks')
        assert 'self.flow_run.end_time =' not in code
    for path in ['src/shared/operational_capture.py','src/shared/operational_terminal.py','deploy/staging/operational-evidence/bootstrap.py']:
        ast.parse((ROOT/path).read_text(),feature_version=(3,9))
    spec=importlib.util.spec_from_file_location('operational_build',ROOT/'deploy/staging/operational-evidence/build.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    artifacts=module.artifacts();manifest=json.loads(artifacts['TOOLS.json'])
    assert set(manifest)==set(module.SOURCES)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==manifest[n] for n,p in module.SOURCES.items())
    assert b'sha256:'+hashlib.sha256(artifacts['powerflow-publish-operations']).hexdigest().encode() in artifacts['sudoers.rule']
    assert b'--flow-run ' in artifacts['sudoers.rule'] and b' --state ' in artifacts['sudoers.rule'] and b'NOSETENV' in artifacts['sudoers.rule']
    assert b' -I -S -B ' in artifacts['powerflow-publish-operations']


def test_context_identities_are_persisted_without_forecast_execution(monkeypatch):
    from prefect.context import FlowRunContext,TaskRunContext
    monkeypatch.setattr(FlowRunContext,'get',classmethod(lambda cls:SimpleNamespace(flow_run=SimpleNamespace(id=FLOW,deployment_id=capture.DEPLOYMENT))))
    monkeypatch.setattr(TaskRunContext,'get',classmethod(lambda cls:SimpleNamespace(task_run=SimpleNamespace(id=STATE))))
    assert terminal.flow_identity()=={'prefect_flow_run_id':FLOW,'prefect_deployment_id':capture.DEPLOYMENT}
    assert terminal.task_result({'status':'WITHHELD'})=={'status':'WITHHELD','prefect_task_run_id':STATE}
    source=(ROOT/'src/scheduled_pipeline.py').read_text()
    assert "storage_state['next24h_prefect_task_run_id'] = forecast_result['prefect_task_run_id']" in source
    assert "storage_state['next24h_inference_receipt_id'] = forecast_result['inference_receipt_id']" in source
    assert '**_operational_flow_identity()' in source


def test_precision_and_delayed_stage_durability(stable):
    ft=stable['tasks'][0];stage=stable['stages'][0]
    stage['start_timestamp_utc']=(c.timestamp(ft['start_time'])-dt.timedelta(microseconds=1)).isoformat()
    stage['end_timestamp_utc']=(c.timestamp(ft['end_time'])+dt.timedelta(microseconds=1)).isoformat()
    ft['start_time']=ft['start_time'].replace('+00:00','Z')
    assert c.validate(*associate(**stable),NOW)['inference']['outcome']=='GENERATED'
    stable['stages']=[]
    with pytest.raises(c.InvalidEvidence,match='INTERNAL_ASSOCIATION'):associate(**stable)


@pytest.mark.parametrize('kind',['capture','delivery'])
def test_capture_and_delivery_errors_are_sanitized_separately(kind):
    calls=[]
    def source(*a):
        calls.append('capture')
        if kind=='capture':raise RuntimeError('SECRET source path')
        return b'fixture','a'*64
    def publisher(*a,**k):calls.append('store');raise OSError('SECRET root path')
    result=capture.deliver_terminal(FLOW,STATE,capture=source,publisher=publisher)
    assert result=={'status':'FAILED','reason':'CAPTURE_UNVERIFIED' if kind=='capture' else 'OPERATIONAL_STORE_UNCERTAIN'}
    assert calls==(['capture'] if kind=='capture' else ['capture','store'])


@pytest.mark.parametrize('payload,exit_code',[(b'{"status":"PUBLISHED"}',0),(b'{"status":"FAILED","reason":"CAPTURE_UNVERIFIED"}',1),(b'{"status":"FAILED","reason":"SECRET_RAW_ERROR"}',1)])
def test_actual_invocation_argv_environment_no_retry_and_sanitization(monkeypatch,payload,exit_code):
    calls=[]
    class Process:
        pid=99999999
        returncode=exit_code
        def __init__(self):
            r,w=os.pipe();os.write(w,payload);os.close(w);self.stdout=os.fdopen(r,'rb')
            r,w=os.pipe();os.close(w);self.stderr=os.fdopen(r,'rb')
        def wait(self,**kwargs):return self.returncode
        def poll(self):return self.returncode
    def popen(argv,**kwargs):calls.append((argv,kwargs));return Process()
    monkeypatch.setattr(terminal.subprocess,'Popen',popen)
    if b'SECRET' in payload:
        with pytest.raises(ValueError,match='HELPER_CONTRACT'):terminal.invoke(FLOW,STATE)
    else:assert terminal.invoke(FLOW,STATE)['status']==('PUBLISHED' if exit_code==0 else 'FAILED')
    assert len(calls)==1
    argv,options=calls[0]
    assert argv==['/usr/bin/sudo','-n','/usr/local/sbin/powerflow-publish-operations','--flow-run',FLOW,'--state',STATE]
    assert options['env']=={'PATH':'/usr/bin:/bin'} and options['start_new_session'] is True
    with pytest.raises(c.InvalidEvidence):terminal.invoke('bad argument',STATE)
    assert len(calls)==1


def test_read_only_authorizer_and_no_forecast_store_writes(stable,tmp_path,monkeypatch):
    source,db=fixture_source(stable,tmp_path,monkeypatch);before=db.read_bytes()
    with source.snapshot() as connection:
        for sql in ['DELETE FROM pipeline_runs','CREATE TABLE private(x)','SELECT load_extension(\'anything\')','PRAGMA journal_mode=WAL']:
            with pytest.raises(sqlite3.DatabaseError):connection.execute(sql)
    assert db.read_bytes()==before
    forecast_root=tmp_path.resolve()/'forecast-publications';forecast_root.mkdir();(forecast_root/'sentinel').write_bytes(b'unchanged')
    operational=root_at(tmp_path)
    b=op_fixture();now=dt.datetime(2026,11,5,6,49,tzinfo=dt.timezone.utc)
    result=capture.deliver_terminal(FLOW,STATE,capture=lambda *a:encoded(b),root=operational,clock=lambda:now)
    assert result=={'status':'PUBLISHED'} and (forecast_root/'sentinel').read_bytes()==b'unchanged'
    assert sorted(p.name for p in forecast_root.iterdir())==['sentinel']


def test_privileged_bootstrap_refuses_checkout_and_unverified_bytes(monkeypatch):
    spec=importlib.util.spec_from_file_location('ops_bootstrap',ROOT/'deploy/staging/operational-evidence/bootstrap.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with pytest.raises(ValueError,match='INSTALLED_ENTRYPOINT_REQUIRED'):module.load()
    monkeypatch.setattr(module,'__file__',str(module.BASE/'bootstrap.py'))
    monkeypatch.setattr(module.os,'getuid',lambda:0);monkeypatch.setattr(module.os,'geteuid',lambda:0)
    manifest={name:'0'*64 for name in module.FILES}
    monkeypatch.setattr(module,'read',lambda p:json.dumps(manifest).encode() if p.name=='TOOLS.json' else b'not executable')
    before=set(module.sys.modules)
    with pytest.raises(ValueError,match='CODE_HASH'):module.load()
    assert set(module.sys.modules)==before


def test_old_deployment_binding_rejects_changed_pipeline_without_refreshing_manifest():
    folder=ROOT/'deploy/staging/forecast-publication/automation-continuation-v2'
    manifest=(folder/'MANIFEST.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest()=='53fcc9323a5bacf81ffb5bf067048df3403be4eeca3b7a2dd6e4e6f770f9907a'
    spec=importlib.util.spec_from_file_location('old_operational_gate',folder/'run.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with pytest.raises(ValueError,match='artifact_hash'):
        module.verify(hashlib.sha256(manifest).hexdigest(),'apply')


def test_verified_closure_loads_in_memory_without_source_access_or_execution(monkeypatch):
    import sys
    spec=importlib.util.spec_from_file_location('local_ops_build',ROOT/'deploy/staging/operational-evidence/build.py');build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)
    spec=importlib.util.spec_from_file_location('local_ops_bootstrap',ROOT/'deploy/staging/operational-evidence/bootstrap.py');boot=importlib.util.module_from_spec(spec);spec.loader.exec_module(boot)
    blobs={name:path.read_bytes() for name,path in build.SOURCES.items()};manifest={n:hashlib.sha256(b).hexdigest() for n,b in blobs.items()}
    monkeypatch.setattr(boot,'__file__',str(boot.BASE/'bootstrap.py'))
    monkeypatch.setattr(boot.os,'getuid',lambda:0);monkeypatch.setattr(boot.os,'geteuid',lambda:0)
    monkeypatch.setattr(boot,'read',lambda p:json.dumps(manifest).encode() if p.name=='TOOLS.json' else blobs[p.relative_to(boot.BASE).as_posix()])
    saved={n:m for n,m in sys.modules.items() if n=='shared' or n.startswith('shared.')}
    try:
        verified=boot.load()
        assert str(verified.PUBLICATION)=='/srv/powerflow/operational-publications'
        assert verified.capture_terminal.__module__=='shared.operational_capture'
    finally:
        for name in list(sys.modules):
            if name=='shared' or name.startswith('shared.'):sys.modules.pop(name,None)
        sys.modules.update(saved)
