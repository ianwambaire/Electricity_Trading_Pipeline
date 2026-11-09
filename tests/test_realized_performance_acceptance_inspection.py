"""Offline real-transport simulation; never SSH, browser or staging traffic."""
import ast
import copy
import datetime as dt
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import ssl
import types
import zipfile
from unittest.mock import Mock,patch
import pytest

ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'deploy/preflight/realized-performance-acceptance'
WHEEL=ROOT/'data/backups/private-staging-releases/phase-forecast-consistency-20261101-v1/preflight/prefect-implementation-wdw123f9/reference-prefect-3.7.5.whl'
WHEEL_SHA='214837b7cb1e10f8fec59018253cd8ef65c8b394b7df29c511b645b0ff5e4478'
def load(name):
    spec=importlib.util.spec_from_file_location('acceptance_'+name,HERE/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
I=load('inspect');RUN=load('run');CTX=load('context')
TASK='11111111-2222-4333-8444-555555555555';STATE='22222222-3333-4444-8555-666666666666'
SYMBOLS={'src/shared/realized_report_store.py':['opened','publish'],'src/models/next24h_monitoring.py':['update_next24h_monitoring']}
MESSAGE='Traceback (most recent call last):\n File "/private/worker/src/shared/realized_report_store.py", line 24, in opened\nPermissionError: [Errno 13] Permission denied: \'powerflow\' token=SECRET'

def flow():return dict(id=I.FLOW,flow_id=STATE,deployment_id=I.DEPLOYMENT,auto_scheduled=True,expected_start_time=I.SCHEDULED,start_time='2026-11-08T18:45:02Z',end_time='2026-11-08T18:48:00Z',state_type='COMPLETED',state=dict(id=STATE,type='COMPLETED',timestamp='2026-11-08T18:48:00Z',name='Completed'))
def task(state='FAILED',message=MESSAGE):return dict(id=TASK,flow_run_id=I.FLOW,task_key='monitor',dynamic_key='0',name=I.MONITOR+'-abc',start_time='2026-11-08T18:47:00Z',end_time='2026-11-08T18:47:01Z',state_type=state,state=dict(id=STATE,type=state,timestamp='2026-11-08T18:47:01Z',name=state.capitalize(),message=message))
def log():return dict(id=STATE,name='prefect.task_runs',level=40,flow_run_id=I.FLOW,task_run_id=TASK,timestamp='2026-11-08T18:47:01Z',message=MESSAGE)
def forecast():return {'row_count':24,'forecasts':[dict(horizon_hours=h,issue_time='2026-11-08T16:00:00Z',target_time=(dt.datetime(2026,11,8,16,tzinfo=dt.timezone.utc)+dt.timedelta(hours=h)).isoformat(),predicted_price_eur_mwh=12.5,model_release='frozen')for h in range(1,25)],'publication':{'status':'VALID'}}

def fixtures(state='FAILED'):
    return {'FLOW':(200,flow()),'TASKS':(200,[task(state)]),'LOGS':(200,[log()]),'FORECAST_API':(200,forecast()),'OPERATIONS_API':(200,{'status':'VALID'}),'OPERATIONS_SUMMARY':(200,{'forecast_status':'VALID'}),'REALIZED_API':(404,{'detail':{'code':'REALIZED_REPORT_MISSING'}})}

class Response:
    def __init__(self,status,body,headers=None):self.status=status;self.raw=body if type(body)is bytes else json.dumps(body).encode();self.headers={'Content-Type':'application/json','Cache-Control':'no-store',**(headers or{})}
    def getheader(self,key):return self.headers.get(key)
    def read(self,n):return self.raw[:n]
class Connection:
    def __init__(self,server,port):self.server=server;self.port=port;self.closed=False
    def request(self,method,path,body=None,headers=None):self.server.requests.append((self.port,method,path,json.loads(body)if body is not None else None));self.requested=(method,path,body)
    def getresponse(self):
        item=self.server.responses.pop(0)
        if isinstance(item,Exception):raise item
        return Response(*item)
    def close(self):self.closed=True
class Server:
    def __init__(self,responses):self.responses=list(responses);self.requests=[];self.connections=[]
    def connect(self,port):c=Connection(self,port);self.connections.append(c);return c
class Context:
    def guard(self):return {'read_only':True}
    def operational(self):return {'target_association':'MATCH','delivery_outcome':'PUBLISHED'}
    def publication(self):return {'summary':{'present':False,'state':None}}
    def consistency(self,*a):raise I.Rejected('MISSING')
    def reconstruct(self,*a):return {'receipt_source_and_metrics':'RECONSTRUCTED_MATCH'}
    def apis(self,bodies):return {'forecast_api_consistency':True}
    def protected(self):return {'protected_state':'VERIFIED'}
def execute(data=None,context=None):
    data=data or fixtures();s=Server([data[k]for k in ['FLOW','TASKS','LOGS','FORECAST_API','OPERATIONS_API','OPERATIONS_SUMMARY','REALIZED_API']]);h=I.HTTP(s.connect);result=I.Inspection(context or Context(),h,SYMBOLS).execute();return result,s


def nodes(raw):return {n.name:n for n in ast.parse(raw).body if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef))}
@pytest.fixture(scope='module')
def wheel():
    raw=WHEEL.read_bytes();assert hashlib.sha256(raw).hexdigest()==WHEEL_SHA
    return zipfile.ZipFile(io.BytesIO(raw))

@pytest.mark.parametrize('module,name,route,verb',[('task_runs','read_task_runs','/filter','post'),('flow_runs','read_flow_run','/{id:uuid}','get'),('logs','read_logs','/filter','post')])
def test_actual_375_routes_methods_signatures(wheel,module,name,route,verb):
    source=wheel.read('prefect/server/api/'+module+'.py');n=nodes(source)[name]
    assert any(isinstance(d,ast.Call)and isinstance(d.func,ast.Attribute)and d.func.attr==verb and d.args[0].value==route for d in n.decorator_list)
    local=ROOT/'venv/lib/python3.14/site-packages/prefect/server/api'/ (module+'.py')
    # Complete actual endpoint signature parity, not an invented mock schema.
    assert ast.dump(n.args)==ast.dump(nodes(local.read_bytes())[name].args)
    if module=='task_runs':assert 'START_TIME_ASC'not in ast.unparse(n.args)and 'TaskRunSort.ID_DESC'in ast.unparse(n.args)

@pytest.mark.parametrize('module,names',[
 ('sorting',['TaskRunSort','LogSort']),
 ('filters',['FlowRunFilter','FlowRunFilterId','LogFilter','LogFilterFlowRunId','LogFilterTaskRunId','LogFilterTimestamp']),
 ('core',['FlowRun','TaskRun','Log']),('states',['State','StateType','StateBaseModel'])])
def test_375_request_and_response_schema_parity(wheel,module,names):
    remote=nodes(wheel.read('prefect/server/schemas/'+module+'.py'));local=nodes((ROOT/'venv/lib/python3.14/site-packages/prefect/server/schemas'/ (module+'.py')).read_bytes())
    for name in names:
        # Field declarations/defaults/validators/methods are identical for every
        # schema used by our realistic simulated HTTP server.
        assert ast.dump(remote[name])==ast.dump(local[name]),name


def test_realistic_prefect_response_models():
    from prefect.server.schemas import core
    core.FlowRun.model_validate(flow());core.TaskRun.model_validate(task());core.Log.model_validate(log())


def test_full_http_path_with_actual_api_validation_models():
    from prefect.server.schemas.filters import FlowRunFilter,LogFilter
    from prefect.server.schemas.sorting import TaskRunSort,LogSort
    from pydantic import create_model,Field
    Tasks=create_model('Tasks',flow_runs=(FlowRunFilter,...),limit=(int,Field(ge=0,le=200)),offset=(int,Field(ge=0)),sort=(TaskRunSort,TaskRunSort.ID_DESC))
    Logs=create_model('Logs',logs=(LogFilter,...),limit=(int,Field(ge=0,le=200)),offset=(int,Field(ge=0)),sort=(LogSort,LogSort.TIMESTAMP_ASC))
    result,server=execute()
    assert len(server.requests)==7 and all(c.closed for c in server.connections)
    for port,method,path,body in server.requests:
        if path=='/api/task_runs/filter':assert Tasks.model_validate(body).sort==TaskRunSort.ID_DESC and 'sort'not in body and body['offset']==0
        elif path=='/api/logs/filter':assert Logs.model_validate(body).sort==LogSort.TIMESTAMP_DESC and body['offset']==0
        else:assert method=='GET'and body is None and '?'not in path
    assert result['sections']['MONITORING']['evidence']['state']=='FAILED'
    assert result['sections']['LOGS']['evidence']['entries'][0]['diagnosis']['denied_component']=='REPORT_PARENT'
    assert result['sections']['FORECAST_API']['status']=='VERIFIED'
    assert result['sections']['PROTECTED_STATE']['status']=='VERIFIED'
    assert result['status']=='BLOCKED'
    text=json.dumps(result);assert 'SECRET'not in text and '/private'not in text and '12.5'not in text

@pytest.mark.parametrize('status,body,headers,reason',[
 (422,{'detail':[{'loc':['body','sort'],'type':'enum','msg':'SECRET','input':'SECRET'}]},None,'HTTP_STATUS'),
 (404,{'detail':'SECRET'},None,'HTTP_STATUS'),(301,{},None,'REDIRECT_BLOCKED'),
 (200,b'bad',None,'JSON_INVALID'),(200,b'{"x":1,"x":2}',None,'JSON_INVALID'),
 (200,b'{"x":NaN}',None,'JSON_INVALID'),(200,{}, {'Content-Type':'text/html'},'CONTENT_TYPE'),
 (200,b'x'*524289,None,'RESPONSE_TOO_LARGE')])
def test_http_failures_keep_safe_status(status,body,headers,reason):
    server=Server([(status,body,headers)]);h=I.HTTP(server.connect)
    with pytest.raises(I.Rejected,match=reason):h.get('FLOW')
    assert h.probes[0]['http_status']==status and h.probes[0]['error']==reason
    assert 'SECRET'not in json.dumps(h.probes)
    if status==422:assert h.probes[0]['validation']==[{'location':['body','sort'],'category':'enum'}]
@pytest.mark.parametrize('error,code',[(socket.timeout(),'NETWORK_TIMEOUT'),(ssl.SSLError(),'TLS_FAILURE'),(ConnectionRefusedError(),'NETWORK_FAILURE')])
def test_transport_errors(error,code):
    h=I.HTTP(Server([error]).connect)
    with pytest.raises(I.Rejected,match=code):h.get('FLOW')
    assert h.probes[0]['error']==code

def test_no_retries_or_arbitrary_endpoints():
    s=Server([(200,flow())]);h=I.HTTP(s.connect);h.get('FLOW')
    with pytest.raises(I.Rejected,match='REQUEST_SCOPE'):h.get('FLOW')
    with pytest.raises(I.Rejected,match='REQUEST_SCOPE'):h.get('/api/flow_runs/create')
    assert len(s.requests)==1

@pytest.mark.parametrize('field,value,code',[('id',STATE,'IDENTITY'),('deployment_id',STATE,'IDENTITY'),('auto_scheduled',False,'IDENTITY'),('expected_start_time','2026-11-08T19:45:00Z','IDENTITY'),('end_time',None,'TIMESTAMP'),('state_type','FAILED','STATE_CONTRADICTION')])
def test_flow_identity_and_terminal_guards(field,value,code):
    f=flow();f[field]=value
    with pytest.raises(I.Rejected,match=code):I.verified_flow(f)
@pytest.mark.parametrize('rows,code',[(lambda:[],'MISSING'),(lambda:[task(),task()],'IDENTITY'),(lambda:[task()]*100,'TRUNCATED'),(lambda:[{**task(),'flow_run_id':STATE}],'IDENTITY')])
def test_task_scope_and_bounds(rows,code):
    with pytest.raises(I.Rejected,match=code):I.verified_task(rows(),flow(),SYMBOLS)

def test_expected_conditional_skip_retains_real_notready():
    t=task('PENDING',"Upstream task run abc did not reach a 'COMPLETED' state");t['state']['name']='NotReady';t['start_time']=None;t['end_time']=None
    row,summary,window,basis=I.verified_task([t],flow(),SYMBOLS)
    assert summary['state_name']=='NotReady'and summary['started_at']is None and summary['completed_at']is None
    assert summary['diagnosis']['upstream_not_completed']is True and basis=='FLOW_TIMES_NOT_TASK_TIMES'


def test_independent_failure_does_not_stop_other_collection():
    c=Context();c.operational=Mock(side_effect=PermissionError('SECRET'));result,s=execute(context=c)
    assert result['sections']['OPERATIONAL_PUBLICATION']['reason']=='OS_ERROR'
    assert result['sections']['MONITORING']['evidence']['state']=='FAILED'
    assert result['sections']['REPORT_PUBLICATION']['status']=='VERIFIED'and len(s.requests)==7

def test_guard_failure_stops_before_requests():
    c=Context();c.guard=Mock(side_effect=I.Rejected('GUARD_FAILED'));result,s=execute(context=c)
    assert not s.requests and result['status']=='BLOCKED'

def test_wrong_log_identity_rejected_but_api_collected():
    data=fixtures();data['LOGS']=(200,[{**log(),'flow_run_id':STATE}]);result,s=execute(data)
    assert result['sections']['LOGS']['reason']=='IDENTITY'and result['sections']['REALIZED_API']['status']=='VERIFIED'

def test_exact_log_bound_reports_incompleteness():
    data=fixtures();data['LOGS']=(200,[log()for _ in range(50)]);result,_=execute(data)
    assert result['sections']['LOGS']['evidence']['limit_reached']is True

def test_missing_publication_never_passes():
    result,_=execute(fixtures('COMPLETED'));assert result['status']=='BLOCKED'and result['sections']['REPORT_CONSISTENCY']['reason']=='MISSING'

@pytest.mark.parametrize('code',['REALIZED_INPUTS_MISSING','REALIZED_REPORT_FAILED','REALIZED_REPORT_INVALID'])
def test_explicit_unavailable_api_states_retained(code):
    data=fixtures();data['REALIZED_API']=(503,{'detail':{'code':code}});result,_=execute(data)
    assert result['sections']['REALIZED_API']['evidence']['error_code']==code

def test_unknown_exceptions_are_never_retained():
    c=Context();c.publication=Mock(side_effect=RuntimeError('token SECRET /private/secret'));result,_=execute(context=c)
    assert result['sections']['REPORT_PUBLICATION']['reason']=='UNVERIFIED_CHECK'and 'SECRET'not in json.dumps(result)

@pytest.fixture(scope='module')
def frozen():
    prefix,_,_,_=RUN.components();ns={};exec(prefix,ns);return ns['R']

def test_frozen_contract_checks_without_sdk_or_application_imports(frozen):
    c=CTX.Context(frozen,I);contract=c.contract();now=dt.datetime(2026,11,8,19,tzinfo=dt.timezone.utc)
    doc=contract.failure('MISSING_HISTORY',now);assert contract.validate(contract.encode(doc),now)==doc
    doc['generated_at']='2026-11-08T19:00:00'
    with pytest.raises(ValueError):contract.validate(contract.encode(doc),now)

def test_actual_absent_report_and_partial_marker(frozen,monkeypatch):
    r=types.SimpleNamespace(report_metadata=lambda record:None);c=CTX.Context(r,I)
    assert c.publication()=={'summary':{'present':False,'state':None}}
    with pytest.raises(I.Rejected,match='MISSING'):c.consistency(c.publication(),(404,{}),task())

@pytest.mark.parametrize('state,code',[('MISSING_INPUTS','REALIZED_INPUTS_MISSING'),('FAILED','REALIZED_REPORT_FAILED')])
def test_nonready_document_api_association(state,code):
    c=CTX.Context(None,I);doc={'state':state,'generated_at':'2026-11-08T18:47:00.5Z'};pub={'summary':{'present':True},'document':doc}
    assert c.consistency(pub,(503,{'detail':{'code':code}}),task())['publication_matches_api']
    with pytest.raises(I.Rejected,match='API_MISMATCH'):c.consistency(pub,(404,{}),task())

def test_newer_publication_not_substituted():
    c=CTX.Context(None,I);pub={'summary':{'present':True},'document':{'state':'READY','generated_at':'2026-11-08T19:47:00Z'}}
    with pytest.raises(I.Rejected,match='PUBLICATION_NOT_TARGET'):c.consistency(pub,(200,{}),task())


def test_source_advancement_blocks_reconstruction():
    r=types.SimpleNamespace(WORKER=Path('/approved'),P=types.SimpleNamespace(safe=lambda *a:None,read=lambda *a:b'advanced'))
    c=CTX.Context(r,I);pub={'document':{'generated_at':'2026-11-08T18:47:00.5Z','sources':{'history_sha256':'0'*64}}}
    with pytest.raises(I.Rejected,match='SOURCE_ADVANCED'):c.reconstruct(pub,task())


def test_readonly_assembly_and_python39(frozen):
    payload,source,_,_=RUN.assemble();ast.parse(payload,feature_version=(3,9));assert len(payload)<4*1024**2
    pending=[payload];functions=set()
    while pending:
        tree=ast.parse(pending.pop())
        for n in ast.walk(tree):
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):functions.add(n.name)
            if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='compile'and n.args and isinstance(n.args[0],ast.Constant)and type(n.args[0].value)in{str,bytes}:pending.append(n.args[0].value)
    assert not functions&{'apply','rollback','write','mkdir','restart','patch','publish','deliver_terminal'} # retained accept_report is read-only and is never invoked


def test_source_bound_sanitized_output():
    result,_=execute();result['inspection_source_sha256']='a'*64
    assert RUN.safe_output(json.dumps(result).encode(),'a'*64,I,SYMBOLS)==result
    for mutate in [lambda x:x.update(inspection_source_sha256='b'*64),lambda x:x.update(secret='SECRET'),lambda x:x['sections']['FLOW']['evidence'].update(raw='SECRET')]:
        bad=copy.deepcopy(result);mutate(bad)
        with pytest.raises(I.Rejected):RUN.safe_output(json.dumps(bad).encode(),'a'*64,I,SYMBOLS)


def test_complete_mocked_pass_has_all_evidence():
    c=Context();c.publication=lambda:{'summary':{'present':True,'state':'READY'}};c.consistency=lambda *a:{'publication_matches_api':True}
    result,_=execute(fixtures('COMPLETED'),c);assert result['status']=='PASS'
    result['inspection_source_sha256']='a'*64;assert RUN.safe_output(json.dumps(result).encode(),'a'*64,I,SYMBOLS)['status']=='PASS'


def test_local_check_and_immutable_bindings_when_frozen():
    if not(HERE/'BINDINGS.json').exists():pytest.skip('bindings frozen after validation')
    expected=RUN.sha((HERE/'BINDINGS.json').read_bytes());payload,*_=RUN.verify(expected);assert payload==RUN.assemble()[0]

@pytest.mark.parametrize('error,operation,reason',[(PermissionError('secret'),'REPORT_DOCUMENT','OS_ERROR'),(ValueError('PIPELINE_OR_WINDOW_GATE'),'WINDOW','GUARD_FAILED')])
def test_context_failure_preserves_exact_approved_gate(error,operation,reason):
    old=I.APPROVED_GATES;I.APPROVED_GATES={'PIPELINE_OR_WINDOW_GATE'}
    try:
        c=CTX.Context(None,I);c.operation=operation
        with pytest.raises(I.Rejected)as caught:c.check(lambda:(_ for _ in()).throw(error))
        assert caught.value.code==reason and caught.value.detail['operation']==operation
        assert caught.value.detail['exception_class']==type(error).__name__
        if isinstance(error,ValueError):assert caught.value.detail['gate']=='PIPELINE_OR_WINDOW_GATE'
        assert 'secret'not in json.dumps(caught.value.detail)
    finally:I.APPROVED_GATES=old

@pytest.mark.parametrize('value',['2026-11-08T18:47:00','2026-11-08T18:47:00+03:00','bad',None])
def test_strict_utc_timestamps(value):
    with pytest.raises(I.Rejected,match='TIMESTAMP'):I.stamp(value)

@pytest.mark.parametrize('name',['FORECAST_API','OPERATIONS_API','OPERATIONS_SUMMARY','REALIZED_API'])
def test_api_failure_independence(name):
    data=fixtures();data[name]=(503,{'detail':{'code':'FORECAST_WITHHELD'if name=='FORECAST_API'else'UNRECOGNIZED'}})
    result,s=execute(data);assert len(s.requests)==7 and result['sections']['PROTECTED_STATE']['status']=='VERIFIED'
    assert result['sections'][name]['status']==('VERIFIED'if name=='FORECAST_API'else'UNVERIFIED')

@pytest.mark.parametrize('count',[0,23,25])
def test_invalid_forecast_inventory_never_accepted(count):
    data=fixtures();body=forecast();body['forecasts']=body['forecasts'][:count]if count<=24 else body['forecasts']+[body['forecasts'][0]];body['row_count']=count;data['FORECAST_API']=(200,body)
    result,_=execute(data);assert result['sections']['FORECAST_API']['status']=='UNVERIFIED'

@pytest.mark.parametrize('state',['VALID','STALE','MISSING','INVALID'])
def test_all_operational_evidence_statuses_observable(state):
    data=fixtures();data['OPERATIONS_API']=(200,{'status':state});result,_=execute(data)
    assert result['sections']['OPERATIONS_API']['evidence']['operational_status']==state


def test_task_collection_rejects_malformed_before_selection():
    with pytest.raises(I.Rejected):I.verified_tasks({'secret':'value'})
    with pytest.raises(I.Rejected,match='AMBIGUOUS'):I.verified_task([task(),{**task(),'id':STATE}],flow(),SYMBOLS)


def test_guard_pass_and_complete_context_transport_path(frozen,monkeypatch):
    # Full collector+real Context+HTTP serialization; filesystem/commands are
    # fixtures, not live calls. Uses the exact frozen report contract source.
    source=b'bound SDK';digest=I.sha(source);pointer=b'a'*64+b'\n'
    op={'execution':{'flow_run_id':I.FLOW,'pipeline_run_id':I.PIPELINE,'outcome':'COMPLETED'},'observed_at':'2026-11-08T18:48:00Z','inference':{'outcome':'GENERATED'},'delivery':{'outcome':'PUBLISHED'}}
    commands=[]
    p=types.SimpleNamespace(idle=lambda n:None,safe=lambda *a:None,read=lambda *a:source,snap=lambda *a:({'sha256':'environment'},pointer),deployment=lambda:{'job_variables':{'env':{'REPORT':'true'}}},STORE=Path('/bound/store'))
    r=types.SimpleNamespace(load_record=lambda:{'phase':'APPLIED','activated_at':'2026-11-08T18:00:00Z','before':{'env_after':'environment','new_variables':{'env':{'REPORT':'true'}},'projection':'bound'}},ENV=Path('/bound/env'),FLAG='REPORT',P=p,verify_backups=lambda *a:None,new_trees=lambda *a:None,worker_state=lambda *a:None,WORKER=Path('/bound/worker'),H=types.SimpleNamespace(OLD_PLAN=types.SimpleNamespace(stable_projection=lambda d:'bound'),OLD_CONFIG={'prefect_version':'3.7.5','worker_sdk':{'flow_engine.py':digest,'workers/base.py':digest},'prefect_metadata_sha256':digest},OP=types.SimpleNamespace(validate=lambda *a:op,view=lambda *a,**k:{'status':'VALID'})),report_metadata=lambda *a:None,protected=lambda *a:None)
    monkeypatch.setattr(CTX.sys,'platform','linux');monkeypatch.setattr(CTX.os,'getuid',lambda:0);monkeypatch.setattr(CTX.os,'geteuid',lambda:0)
    result,_=execute(context=CTX.Context(r,I))
    assert result['sections']['HOST_GUARD']['status']=='VERIFIED'
    assert result['sections']['OPERATIONAL_PUBLICATION']['evidence']['target_association']=='MATCH'
    assert result['sections']['REPORT_PUBLICATION']['evidence']['present']is False
    assert result['sections']['REPORT_CONSISTENCY']['reason']=='MISSING'
    assert result['sections']['PROTECTED_STATE']['status']=='VERIFIED'
    assert not commands


def test_exact_report_hash_and_pointer_security(frozen):
    contract=CTX.Context(frozen,I).contract();now=dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=1)
    document=contract.failure('MISSING_HISTORY',now);raw=contract.encode(document);digest=I.sha(raw)
    p=types.SimpleNamespace(safe=lambda *a:None,read=lambda *a:raw)
    r=types.SimpleNamespace(P=p,REPORT=Path('/bound/report'),report_metadata=Mock(side_effect=[digest,digest]),raw_file=frozen.raw_file)
    c=CTX.Context(r,I);pub=c.publication();assert pub['summary']['state']=='MISSING_INPUTS'
    r.report_metadata=Mock(side_effect=[digest,'b'*64])
    with pytest.raises(I.Rejected,match='POINTER_CHANGED'):c.publication()
    r.report_metadata=Mock(return_value='b'*64)
    with pytest.raises(I.Rejected,match='CONTRACT_INVALID'):c.publication()


def test_nonready_publication_not_equated_to_available_metrics():
    c=Context();c.publication=lambda:{'summary':{'present':True,'state':'MISSING_INPUTS'}};c.consistency=lambda *a:{'publication_matches_api':True,'data_state':'MISSING_INPUTS'}
    data=fixtures('COMPLETED');data['REALIZED_API']=(503,{'detail':{'code':'REALIZED_INPUTS_MISSING'}})
    result,_=execute(data,c);assert result['status']=='PASS'and result['sections']['RECEIPT_RECONSTRUCTION']['status']=='NOT_CHECKED'
    # A successful diagnostic/valid unavailable marker is not proof of metrics.
    assert result['sections']['REALIZED_API']['evidence']['http_status']==503


def test_one_shot_transport_command_keeps_pins_and_stdin():
    transport=RUN.module(ROOT/'deploy/staging/realized-parent-traversal-diagnostic-v3/run.py','test_transport');parent,values=transport.verify(RUN.TRANSPORT)
    argv=RUN.command(transport,parent,values)
    assert argv[:4]==['/usr/bin/ssh','-F','/dev/null','-T']and argv.count('StdinNull=no')==1
    assert 'StrictHostKeyChecking=yes'in argv and 'BatchMode=yes'in argv
    assert '90s'in argv[-1]and '--kill-after=5s'in argv[-1]


def test_actual_app_endpoints_and_response_models_are_frozen(frozen):
    source=ast.parse(frozen.raw_file('api/src/api/app.py'));paths={}
    for node in ast.walk(source):
        if isinstance(node,ast.FunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec,ast.Call)and isinstance(dec.func,ast.Attribute)and dec.func.attr=='get'and dec.args and isinstance(dec.args[0],ast.Constant):paths[dec.args[0].value]=node
    for operation in ['FORECAST_API','OPERATIONS_API','OPERATIONS_SUMMARY','REALIZED_API']:
        path=I.request_spec(operation)[2].removeprefix('/api');assert path in paths
    from pydantic import BaseModel,ConfigDict,Field
    from typing import Literal
    ns=dict(StrictResponseModel=type('StrictResponseModel',(BaseModel,),{'model_config':ConfigDict(extra='forbid')}),datetime=dt.datetime,Literal=Literal,Field=Field)
    selected=[n for n in source.body if isinstance(n,ast.ClassDef)and n.name in {'ForecastPublication','Next24ForecastRow','Next24ForecastResponse'}]
    exec(compile(ast.Module(body=selected,type_ignores=[]),'<frozen-api-response>','exec'),ns)
    body=forecast();pub=body['publication'];pub.update(issue_time='2026-11-08T16:00:00Z',expires_at='2026-11-09T16:00:00Z',completed_at='2026-11-08T18:47:00Z',availability_policy='ISSUE_HORIZON_V1',refresh_due_at='2026-11-08T19:00:00Z')
    ns['Next24ForecastResponse'].model_validate(body)


def test_375_limit_constraint_and_log_filter_nested_fields(wheel):
    from prefect.server.schemas.filters import LogFilter,FlowRunFilter
    from pydantic import ValidationError
    body=I.request_spec('LOGS',TASK,('2026-11-08T18:46:30Z','2026-11-08T18:47:30Z'))[3]
    parsed=LogFilter.model_validate(body['logs']);assert str(parsed.flow_run_id.any_[0])==I.FLOW and str(parsed.task_run_id.any_[0])==TASK
    # All nested filter classes used, not merely top-level filter signatures.
    names=['FlowRunFilterId','LogFilterFlowRunId','LogFilterTaskRunId','LogFilterTimestamp','PrefectFilterBaseModel','PrefectOperatorFilterBaseModel']
    official=nodes(wheel.read('prefect/server/schemas/filters.py'));local=nodes((ROOT/'venv/lib/python3.14/site-packages/prefect/server/schemas/filters.py').read_bytes())
    for name in names:assert ast.dump(official[name])==ast.dump(local[name])
    official=nodes(wheel.read('prefect/server/api/dependencies.py'));local=nodes((ROOT/'venv/lib/python3.14/site-packages/prefect/server/api/dependencies.py').read_bytes())
    assert ast.dump(official['LimitBody'])==ast.dump(local['LimitBody'])


def test_related_forecast_delivery_tasks_preserved_independently():
    data=fixtures();data['TASKS']=(200,[task(),{**task('COMPLETED'),'id':STATE,'name':'Generate next24h production forecast-123'}])
    result,_=execute(data);rows=result['sections']['TASKS']['evidence']['related_tasks']
    assert {r['role']for r in rows}=={'MONITORING','INFERENCE'}and rows[1]['state']=='COMPLETED'


def test_failed_report_marker_cannot_pass_acceptance():
    c=Context();c.publication=lambda:{'summary':{'present':True,'state':'FAILED'}};c.consistency=lambda *a:{'publication_matches_api':True}
    data=fixtures('COMPLETED');data['REALIZED_API']=(503,{'detail':{'code':'REALIZED_REPORT_FAILED'}})
    result,_=execute(data,c);assert result['status']=='BLOCKED'


def test_insufficient_data_pass_is_validated_without_claim_of_metrics():
    c=Context();c.publication=lambda:{'summary':{'present':True,'state':'MISSING_INPUTS'}};c.consistency=lambda *a:{'publication_matches_api':True}
    data=fixtures('COMPLETED');data['REALIZED_API']=(503,{'detail':{'code':'REALIZED_INPUTS_MISSING'}})
    result,_=execute(data,c);result['inspection_source_sha256']='a'*64
    assert RUN.safe_output(json.dumps(result).encode(),'a'*64,I,SYMBOLS)['status']=='PASS'


def test_cross_api_scope_and_forecast_status_consistency():
    c=CTX.Context(None,I);c.op_public={'status':'VALID'}
    bodies={'OPERATIONS_API':(200,c.op_public),'FORECAST_API':(503,{'detail':{'code':'FORECAST_WITHHELD'}}),'OPERATIONS_SUMMARY':(200,{'forecast_status':'EXPIRED'})}
    assert c.apis(bodies)['admin_fields_disclosed']is False
    bodies['OPERATIONS_API']=(200,{'status':'VALID','admin':{'SECRET':True}})
    with pytest.raises(I.Rejected,match='API_MISMATCH'):c.apis(bodies)
    bodies['OPERATIONS_API']=(200,c.op_public);bodies['OPERATIONS_SUMMARY']=(200,{'forecast_status':'VALID'})
    with pytest.raises(I.Rejected,match='API_MISMATCH'):c.apis(bodies)


def test_cross_api_exact_forecast_expiry_and_refresh_timestamps():
    c=CTX.Context(None,I);c.op_public={'status':'VALID'}
    publication={'expires_at':'2026-11-09T16:00:00Z','refresh_due_at':'2026-11-08T19:00:00Z'}
    bodies={'OPERATIONS_API':(200,c.op_public),'FORECAST_API':(200,{'publication':publication}),'OPERATIONS_SUMMARY':(200,{'forecast_status':'VALID','forecast_expires_at':publication['expires_at'],'forecast_refresh_due_at':publication['refresh_due_at']})}
    assert c.apis(bodies)['forecast_api_consistency']
    bodies['OPERATIONS_SUMMARY'][1]['forecast_expires_at']='2026-11-10T16:00:00Z'
    with pytest.raises(I.Rejected,match='API_MISMATCH'):c.apis(bodies)


def test_complete_request_response_path_through_fastapi_schema_validation():
    from fastapi import FastAPI,Body
    from fastapi.testclient import TestClient
    from prefect.server.schemas import core
    from prefect.server.schemas.filters import FlowRunFilter,LogFilter
    from prefect.server.schemas.sorting import TaskRunSort,LogSort
    app=FastAPI();seen=[];data=fixtures()
    @app.get('/api/flow_runs/{run_id}',response_model=core.FlowRun)
    def read_flow(run_id:str):
        assert run_id==I.FLOW;seen.append('FLOW');return flow()
    @app.post('/api/task_runs/filter',response_model=list[core.TaskRun])
    def read_tasks(flow_runs:FlowRunFilter=Body(...),sort:TaskRunSort=Body(TaskRunSort.ID_DESC),limit:int=Body(200,ge=0,le=200),offset:int=Body(0,ge=0)):
        assert list(map(str,flow_runs.id.any_))==[I.FLOW]and sort==TaskRunSort.ID_DESC and limit==100 and offset==0
        seen.append('TASKS');return [task()]
    @app.post('/api/logs/filter',response_model=list[core.Log])
    def read_logs(logs:LogFilter=Body(...),sort:LogSort=Body(LogSort.TIMESTAMP_ASC),limit:int=Body(200,ge=0,le=200),offset:int=Body(0,ge=0)):
        assert list(map(str,logs.flow_run_id.any_))==[I.FLOW]and list(map(str,logs.task_run_id.any_))==[TASK]and sort==LogSort.TIMESTAMP_DESC and limit==50 and offset==0
        assert logs.timestamp.after_<logs.timestamp.before_;seen.append('LOGS');return [log()]
    for op in ['FORECAST_API','OPERATIONS_API','OPERATIONS_SUMMARY','REALIZED_API']:
        def get(operation=op):
            from fastapi.responses import JSONResponse
            status,body=data[operation];seen.append(operation);return JSONResponse(body,status_code=status,headers={'Cache-Control':'no-store'})
        app.add_api_route(I.request_spec(op)[2],get,methods=['GET'])
    class C:
        def request(self,method,path,body=None,headers=None):self.response=client.request(method,path,content=body,headers=headers)
        def getresponse(self):return Response(self.response.status_code,self.response.content,dict(self.response.headers)|{'Content-Type':self.response.headers['content-type'],'Cache-Control':self.response.headers.get('cache-control')})
        def close(self):pass
    with TestClient(app)as client:
        h=I.HTTP(lambda port:C());result=I.Inspection(Context(),h,SYMBOLS).execute()
        assert seen==['FLOW','TASKS','LOGS','FORECAST_API','OPERATIONS_API','OPERATIONS_SUMMARY','REALIZED_API']
        assert result['sections']['MONITORING']['evidence']['state']=='FAILED'and result['sections']['PROTECTED_STATE']['status']=='VERIFIED'
        # Reproduce the unsupported-sort failure with actual FastAPI validation.
        invalid=I.request_spec('TASKS')[3]|{'sort':'START_TIME_ASC'}
        response=client.post('/api/task_runs/filter',json=invalid);assert response.status_code==422
        safe=I.validation_fields(response.json());assert {'location':['body','sort'],'category':'enum'}in safe


def test_old_output_cannot_be_replayed_as_current_inspection():
    result,_=execute();result['inspection_source_sha256']='a'*64
    result['inspected_at']='2020-01-01T00:00:00Z'
    with pytest.raises(I.Rejected,match='TIMESTAMP'):RUN.safe_output(json.dumps(result).encode(),'a'*64,I,SYMBOLS,dt.datetime.now(dt.timezone.utc))


def test_unknown_guard_payload_values_are_not_echoed():
    c=CTX.Context(None,I)
    with pytest.raises(I.Rejected)as caught:c.check(lambda:(_ for _ in()).throw(ValueError('token=SECRET /private/path')),'BACKUPS')
    assert caught.value.detail=={'operation':'BACKUPS','exception_class':'ValueError'}


def test_reporting_policy_drift_is_independent_and_specific():
    before={'env_after':'env-hash','new_variables':{'env':{'REPORT':'true'}},'projection':'bound'}
    p=types.SimpleNamespace(snap=lambda *a:({'sha256':'env-hash'},b''),deployment=lambda:{'job_variables':{'env':{'REPORT':'false'}}})
    r=types.SimpleNamespace(protected=lambda *a:None,P=p,ENV=Path('/approved-env'),FLAG='REPORT',H=types.SimpleNamespace(OLD_PLAN=types.SimpleNamespace(stable_projection=lambda d:'bound')))
    c=CTX.Context(r,I);c.record={'before':before}
    with pytest.raises(I.Rejected)as caught:c.protected()
    assert caught.value.detail['operation']=='REPORT_POLICY'
