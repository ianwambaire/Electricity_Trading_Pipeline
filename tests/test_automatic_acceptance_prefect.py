"""V2 adapter tests: real HTTPConnection/parser, in-memory sockets; no network."""
import ast
import copy
import hashlib
import importlib.util
import io
import json
import socket
from pathlib import Path
import pytest
import test_automatic_acceptance as original

ROOT=Path(__file__).parents[1]
FOLDER=ROOT/'deploy/staging/forecast-publication/automatic-acceptance-v2'
FLOW=original.FLOW
FT=original.FT

def load(name):
    spec=importlib.util.spec_from_file_location('acceptance_v2_'+name,FOLDER/(name+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(socket,'create_connection',lambda *a,**kw:pytest.fail('Unexpected network access'))
    # Execute ALL existing acceptance regressions against v2, without copying or
    # editing the approved v1 tests/package. Reverted automatically after each case.
    monkeypatch.setattr(original,'load',load);monkeypatch.setattr(original,'FOLDER',FOLDER)

captured=original.captured
@pytest.fixture
def sample(captured,monkeypatch):return original.sample.__wrapped__(captured,monkeypatch)

for name,function in list(vars(original).items()):
    if name.startswith('test_') and callable(function):globals()['test_v2_existing_'+name[5:]]=function

@pytest.fixture
def wire(monkeypatch):
    pending=[];connections=[]
    class MemorySocket:
        def __init__(self,response):self.response=response;self.sent=[];self.closed=False
        def setsockopt(self,*args):pass
        def sendall(self,data):self.sent.append(bytes(data))
        def makefile(self,*args,**kwargs):return io.BytesIO(self.response)
        def close(self):self.closed=True
    def connect(address,timeout,source_address=None,**kwargs):
        assert address==('127.0.0.1',4200) and timeout==3 and source_address is None
        assert pending,'Unexpected additional connection/retry'
        sock=MemorySocket(pending.pop(0));connections.append(sock);return sock
    monkeypatch.setattr(socket,'create_connection',connect)
    def respond(value=None,status=200,raw=None,kind='application/json',headers=None):
        body=json.dumps(value).encode() if raw is None else raw
        lines=[f'HTTP/1.1 {status} Test',f'Content-Type: {kind}',f'Content-Length: {len(body)}','Connection: close']
        lines.extend((headers or []));pending.append(('\r\n'.join(lines)+'\r\n\r\n').encode()+body)
    return respond,pending,connections

def flow(m):return {'id':FLOW,'deployment_id':m.DEP,'state':{'type':'COMPLETED'}}
def task():return {'id':FT,'flow_run_id':FLOW,'state':{'type':'COMPLETED'},'name':'Generate next24h production forecast-test'}
def body():return {'task_runs':{'flow_run_id':{'any_':[FLOW]}},'limit':100}

def test_reproduce_original_rejection_then_valid_v2_reads(wire):
    respond,pending,connections=wire;run=load('run');base=run.namespace((ROOT/run.CORE).read_bytes(),'original_readonly_base')
    for path,data in [('/flow_runs/'+FLOW,None),('/task_runs/filter',body())]:
        with pytest.raises(ValueError,match='unapproved_probe'):base['api'](path,data)
    assert not connections
    m=load('inspect');remote=m.Remote();respond(flow(m));assert remote.flow(FLOW)==flow(m)
    respond([task()]);assert remote.tasks(FLOW)==[task()]
    assert len(connections)==2 and not pending
    requests=[b''.join(c.sent) for c in connections]
    assert requests[0].startswith(('GET /api/flow_runs/'+FLOW+' HTTP/1.1\r\n').encode())
    assert requests[1].startswith(b'POST /api/task_runs/filter HTTP/1.1\r\n')
    assert json.loads(requests[1].split(b'\r\n\r\n')[1])==body()
    assert all(b'Host: 127.0.0.1:4200\r\n'in r and b'Authorization:' not in r for r in requests)
    assert all(c.closed for c in connections)


def test_run_filter_preserves_exact_post_semantics(wire):
    respond,pending,connections=wire;m=load('inspect');respond([]);assert m.Remote().runs()==[]
    request=b''.join(connections[0].sent);method,entity=request.split(b'\r\n\r\n')
    assert method.startswith(b'POST /api/flow_runs/filter HTTP/1.1\r\n')
    assert json.loads(entity)=={'deployments':{'id':{'any_':[m.DEP]}},'flow_runs':{'state':{'type':{'any_':['COMPLETED']}}},'sort':'EXPECTED_START_TIME_DESC','limit':20}

@pytest.mark.parametrize('method,path,data',[
 ('GET','/task_runs/filter',None),('POST','/flow_runs/'+FLOW,{}),
 ('DELETE','/flow_runs/'+FLOW,None),('PATCH','/flow_runs/'+FLOW,{'state':{}}),('PUT','/task_runs/filter',body()),
 ('GET','/task_runs/'+FT,None),('GET','/deployments/'+FLOW,None),
 ('GET','/flow_runs/'+FLOW+'?x=1',None),('GET','/flow_runs/'+FLOW+'/',None),
 ('GET','http://evil/flow_runs/'+FLOW,None),('GET','//evil/flow_runs/'+FLOW,None),
 ('GET','https://127.0.0.1:4200/api/flow_runs/'+FLOW,None),
 ('GET','/flow_runs/'+'-'*36,None),('GET','/flow_runs/'+FLOW.replace('2','A',1),None),
 ('GET','/flow_runs/../secret',None),('get','/flow_runs/'+FLOW,None),
 ('GET','/flow_runs/'+FLOW,{}),('GET',None,None),
])
def test_request_scope_rejected_before_connection(wire,method,path,data):
    _,_,connections=wire;m=load('inspect')
    with pytest.raises(m.Stop):m.prefect_request(method,path,data)
    assert not connections

@pytest.mark.parametrize('change',['none','extra','wrong_key','two_ids','bad_id','null_id','wrong_limit','float_limit','wrong_deployment'])
def test_malformed_filters_rejected_before_connection(wire,change):
    _,_,connections=wire;m=load('inspect');data=copy.deepcopy(body());path='/task_runs/filter'
    if change=='none':data=None
    elif change=='extra':data['state']={'type':'RUNNING'}
    elif change=='wrong_key':data={'task_runs':{'id':{'any_':[FLOW]}},'limit':100}
    elif change=='two_ids':data['task_runs']['flow_run_id']['any_']=[FLOW,FLOW]
    elif change=='bad_id':data['task_runs']['flow_run_id']['any_']=['PRIVATE_SECRET']
    elif change=='null_id':data['task_runs']['flow_run_id']['any_']=[None]
    elif change=='wrong_limit':data['limit']=1000
    elif change=='float_limit':data['limit']=100.0
    else:path='/flow_runs/filter';data={'deployments':{'id':{'any_':[FLOW]}},'limit':20}
    with pytest.raises(m.Stop) as error:m.prefect_request('POST',path,data)
    assert 'PRIVATE_SECRET' not in str(error.value) and not connections

@pytest.mark.parametrize('kind',['missing','array','bad_id','wrong_flow','bad_deployment','missing_state','missing_name','wrong_task_flow','bad_task_id','duplicate'])
def test_response_schema_and_identifiers(wire,kind):
    respond,pending,connections=wire;m=load('inspect');value=flow(m);path='/flow_runs/'+FLOW;data=None;method='GET'
    if kind=='missing':value={}
    elif kind=='array':value=[]
    elif kind=='bad_id':value['id']='PRIVATE_TOKEN'
    elif kind=='wrong_flow':value['id']='55555555-5555-4555-8555-555555555555'
    elif kind=='bad_deployment':value['deployment_id']=FLOW
    elif kind=='missing_state':value.pop('state')
    else:
        path='/task_runs/filter';method='POST';data=body();value=task()
        if kind=='missing_name':value.pop('name')
        elif kind=='wrong_task_flow':value['flow_run_id']='55555555-5555-4555-8555-555555555555'
        elif kind=='bad_task_id':value['id']='PRIVATE_TOKEN'
        value=[value,value] if kind=='duplicate' else [value]
    respond(value)
    with pytest.raises(m.Stop) as error:m.prefect_request(method,path,data)
    assert 'PRIVATE_TOKEN' not in str(error.value) and len(connections)==1

@pytest.mark.parametrize('kind',['redirect','http_error','content_type','json','duplicate_json','nan','oversize','task_bound','flow_bound','protocol','timeout'])
def test_bounded_failures_and_sanitization(wire,monkeypatch,kind):
    respond,pending,connections=wire;m=load('inspect');path='/flow_runs/'+FLOW;method='GET';data=None
    if kind=='redirect':respond(None,status=302,headers=['Location: http://PRIVATE_TOKEN/secret'])
    elif kind=='http_error':respond({'secret':'PRIVATE_TOKEN'},status=500)
    elif kind=='content_type':respond({},kind='text/plain')
    elif kind=='json':respond(raw=b'PRIVATE_TOKEN')
    elif kind=='duplicate_json':respond(raw=b'{"id":1,"id":2}')
    elif kind=='nan':respond(raw=b'{"id":NaN}')
    elif kind=='oversize':respond(raw=b'x'*1_000_001)
    elif kind=='task_bound':path='/task_runs/filter';method='POST';data=body();respond([task()]*100)
    elif kind=='flow_bound':path='/flow_runs/filter';method='POST';data={'deployments':{'id':{'any_':[m.DEP]}},'flow_runs':{'state':{'type':{'any_':['COMPLETED']}}},'sort':'EXPECTED_START_TIME_DESC','limit':20};respond([flow(m)]*21)
    elif kind=='protocol':pending.append(b'PRIVATE_TOKEN\r\n')
    else:monkeypatch.setattr(socket,'create_connection',lambda *a,**kw:(_ for _ in ()).throw(socket.timeout('PRIVATE_TOKEN')))
    with pytest.raises(m.Stop) as error:m.prefect_request(method,path,data)
    assert str(error.value).startswith('PREFECT_') and 'PRIVATE_TOKEN' not in str(error.value)
    assert len(connections)<=1


def test_full_acceptance_uses_real_adapter_and_http_parser(sample,wire):
    m,backend,b,run,tasks,files=sample;respond,pending,connections=wire
    respond([run]);respond(run);respond(tasks)
    backend.runs=m.Remote().runs;backend.flow=m.Remote().flow;backend.tasks=m.Remote().tasks
    result=m.validate_report(m.inspect(backend,backend.now))
    assert result['status']=='PASS' and result['delivery_status']=='PUBLISHED' and result['api_predictions']==24
    assert len(connections)==3 and not pending


def test_adapter_failure_is_visible_and_sanitized_in_report(sample,wire):
    m,backend,*_=sample;respond,_,connections=wire
    respond(raw=b'PRIVATE_TOKEN');backend.runs=m.Remote().runs
    report=m.validate_report(m.inspect(backend,backend.now))
    assert report['gaps']==['PREFECT_FLOW_FILTER_RESPONSE_JSON'] and report['phase']=='RUN'
    assert 'PRIVATE_TOKEN' not in json.dumps(report) and len(connections)==1


def test_only_adapter_and_remote_delegation_changed():
    old=ast.parse((ROOT/'deploy/staging/forecast-publication/automatic-acceptance/inspect.py').read_bytes())
    new=ast.parse((FOLDER/'inspect.py').read_bytes())
    def normalize(tree):
        tree=copy.deepcopy(tree)
        tree.body=[n for n in tree.body if not(isinstance(n,ast.FunctionDef)and n.name=='prefect_request') and not(isinstance(n,ast.Import)and any(a.name=='socket' for a in n.names))]
        for n in tree.body:
            if isinstance(n,ast.ClassDef)and n.name=='Remote':n.body=[f for f in n.body if not(isinstance(f,ast.FunctionDef)and f.name in {'runs','flow','tasks'})]
        return ast.dump(tree,include_attributes=False)
    assert normalize(old)==normalize(new)
    assert hashlib.sha256((ROOT/'deploy/staging/forecast-publication/automatic-acceptance/MANIFEST.json').read_bytes()).hexdigest()=='0da25e6276f0a2589fb61ed08820dabf7163323e5e2e3801f18cd1a7277ebf11'
