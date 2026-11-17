"""Offline real strict UTC contract and mocked Prefect selection; no network."""
import ast
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import types
import pytest
from shared import operational_evidence as OP
ROOT=Path(__file__).parents[1]
HERE=ROOT/'deploy/staging/live-forecast-reliability-acceptance-v3'
OLD=ROOT/'deploy/staging/live-forecast-reliability-release-v2'
def load(name,folder=HERE):
    s=importlib.util.spec_from_file_location('accept_v3_'+name,folder/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
class Stop(ValueError):pass
def need(value,reason):
    if not value:raise Stop(reason)
def flow(**updates):
    return dict({'id':'11111111-1111-4111-8111-111111111111','deployment_id':'deployment','auto_scheduled':True,'start_time':None,'state_type':'SCHEDULED'},**updates)
def setup(folder=HERE):
    m=load('acceptance',folder);m.need=need;m.H=types.SimpleNamespace(OP=OP,OLD_PLAN=types.SimpleNamespace(DEPLOYMENT='deployment'));return m

def test_original_null_start_reproduces_exact_lambda_failure():
    with pytest.raises(OP.InvalidEvidence,match='^TIMESTAMP$'):
        max([flow()],key=lambda f:OP.timestamp(f['start_time']))

def test_prefect_filter_semantics_locally_installed_source():
    # Inspect implementation without importing Prefect or starting services.
    candidates=list((ROOT/'venv/lib').glob('python*/site-packages/prefect/server/schemas/filters.py'))
    assert candidates
    tree=ast.parse(candidates[0].read_bytes());node=next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=='FlowRunFilterStartTime')
    source=ast.unparse(node)
    assert 'coalesce(db.FlowRun.start_time, db.FlowRun.expected_start_time)'in source and 'db.FlowRun.start_time.is_not(None)'in source

def test_unstarted_scheduled_is_not_a_timestamp_or_completed_execution():
    m=setup();assert m.started_natural([flow()])==[]
@pytest.mark.parametrize('state',['COMPLETED','FAILED','CRASHED','CANCELLED','RUNNING','PENDING',None])
def test_null_started_or_terminal_fails_closed(state):
    with pytest.raises(Stop,match='NATURAL_START_MISSING'):setup().started_natural([flow(state_type=state)])
@pytest.mark.parametrize('value',['','2026-11-07 19:45:00+00:00','2026-11-07T19:45:00','2026-11-07T19:45:00+03:00','2026-11-32T19:45:00Z',0,{}])
def test_malformed_actual_start_remains_strict(value):
    with pytest.raises(OP.InvalidEvidence,match='TIMESTAMP'):setup().started_natural([flow(start_time=value)])
@pytest.mark.parametrize('value',['2026-11-07T19:45:00Z','2026-11-07T19:45:00.123456+00:00'])
def test_real_utc_started_record_preserved(value):
    f=flow(start_time=value,state_type='COMPLETED');assert setup().started_natural([f])==[f]
def test_manual_and_other_deployment_never_selected():
    assert setup().started_natural([flow(auto_scheduled=False),flow(deployment_id='other')])==[]

@pytest.fixture
def job(monkeypatch):
    m=setup();m.dt=dt;calls=[]
    m.load_record=lambda:{'phase':'APPLIED','activated_at':'2026-11-07T19:03:00Z'}
    m.verified_backups=lambda _:calls.append('backups')
    m.deployment_checks=lambda _:{'forecast_http':200,'forecast_status':'VALID','prediction_count':24}
    rows=[]
    def api(path,body):
        assert path=='/flow_runs/filter'
        assert body['flow_runs']=={'start_time':{'after_':'2026-11-07T19:03:00Z','is_null_':False}}
        assert body['limit']==20 and body['sort']=='START_TIME_DESC'
        calls.append('api');return rows
    m.B={'api':api};return m,rows,calls

def test_complete_mock_no_run_path(job):
    m,rows,calls=job;rows.append(flow())
    assert m.accept_report()['reason']=='NO_POST_ACTIVATION_NATURAL_RUN'
    assert calls==['backups','api']
def test_complete_mock_incomplete_run(job):
    m,rows,_=job;rows.append(flow(start_time='2026-11-07T19:45:01Z',state_type='RUNNING'))
    r=m.accept_report();assert r['reason']=='NATURAL_RUN_NOT_TERMINAL' and r['run_state']=='RUNNING'
def test_pre_activation_rejected_despite_server_filter(job):
    m,rows,_=job;rows.append(flow(start_time='2026-11-07T18:45:00Z',state_type='COMPLETED'))
    with pytest.raises(Stop,match='RUN_BEFORE_ACTIVATION'):m.accept_report()
def test_terminal_provenance_path_is_reached_without_publication(job,monkeypatch):
    m,rows,_=job;f=flow(start_time='2026-11-07T19:45:01Z',state_type='COMPLETED',state={'id':'state'});rows.append(f)
    m.H.artifact=lambda _:b'from_snapshot = object()'
    capture=types.ModuleType('shared.operational_capture')
    def terminal(fid,sid):
        assert (fid,sid)==(f['id'],'state');raise Stop('PROVENANCE_SENTINEL')
    capture.capture_terminal=terminal;monkeypatch.setitem(sys.modules,'shared.operational_capture',capture)
    with pytest.raises(Stop,match='PROVENANCE_SENTINEL'):m.accept_report()
def test_all_existing_provenance_and_freshness_functions_unchanged():
    def functions(path):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef)}
    old=functions(OLD/'acceptance.py');new=functions(HERE/'acceptance.py')
    assert set(new)==set(old)|{'started_natural'}
    assert all(new[k]==v for k,v in old.items()if k!='accept_report')
    a=ast.parse((OLD/'acceptance.py').read_bytes());b=ast.parse((HERE/'acceptance.py').read_bytes())
    orig=next(n for n in a.body if isinstance(n,ast.FunctionDef)and n.name=='accept_report')
    corrected=next(n for n in b.body if isinstance(n,ast.FunctionDef)and n.name=='accept_report')
    # Only the request and natural-list expressions differ; receipt/store checks identical.
    def retained(nodes):
        return [ast.dump(n,include_attributes=False)for n in nodes if not (isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id in {'flows','natural'}for t in n.targets))]
    assert retained(orig.body)==retained(corrected.body)

def test_payload_readonly_and_python39_and_integrity():
    b=load('build');payload,_,_=b.assemble();ast.parse(payload,feature_version=(3,9))
    for n in ['run.py','build.py','acceptance.py']:ast.parse((HERE/n).read_bytes(),feature_version=(3,9))
    assert b'<verified-reliability-transaction>'not in payload
    functions=set()
    for n in ast.walk(ast.parse(payload)):
        if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='compile'and isinstance(n.args[0],ast.Constant)and isinstance(n.args[0].value,(str,bytes)):
            functions.update(t.name for t in ast.walk(ast.parse(n.args[0].value))if isinstance(t,ast.FunctionDef))
    assert not {'apply','rollback','publish','deliver_terminal','write','mkdir','restart','pointer'}&functions
    if (HERE/'MANIFEST.json').exists():
        raw=(HERE/'MANIFEST.json').read_bytes();runner=load('run');assert runner.verify(b.sha(raw))[0]==payload
        with pytest.raises(AssertionError):runner.verify('0'*64)
