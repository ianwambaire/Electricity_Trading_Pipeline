"""Offline fixed-run diagnostic tests; no SSH, network or real database."""
import ast
import datetime as dt
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from shared import operational_evidence as op
from shared import operational_evidence_producer as producer
ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'deploy/staging/operational-delivery-diagnostic-v1/inspect.py'
FLOW={'id':'11111111-1111-4111-8111-111111111111','start_time':'2026-11-07T08:45:01+00:00','end_time':'2026-11-07T08:47:30+00:00'}
@pytest.fixture
def module():
 spec=importlib.util.spec_from_file_location('diagnostic',PATH);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 m.OP=op;m.PRODUCER=producer;m.PLAN=SimpleNamespace(need=op.require);return m

def row(message,**kwargs):return dict(flow_run_id=FLOW['id'],timestamp='2026-11-07T08:47:31Z',message=message,**kwargs)
@pytest.mark.parametrize('status,reason',[('FAILED','CAPTURE_UNVERIFIED'),('FAILED','TERMINAL_CAPTURE_UNVERIFIED'),('FAILED','IMMUTABLE_RUNTIME_UNVERIFIED'),('FAILED','HOOK_UNAVAILABLE'),('PUBLISHED',None),('DISABLED',None),('SKIPPED_NOT_NATURAL',None)])
def test_known_result(module,status,reason):
 value={'status':status};value.update({'reason':reason}if reason else {})
 result=module.sanitize_logs([row(module.PREFIX+json.dumps(value))],FLOW)[0]
 assert result['kind']=='TERMINAL_RESULT' and result['status']==status
 assert result.get('reason')==reason
@pytest.mark.parametrize('message',["Running hook '_operational_evidence_terminal_hook'", "Hook '_operational_evidence_terminal_hook' finished running successfully"])
def test_hook_invocation(module,message):assert module.sanitize_logs([row(message)],FLOW)[0]['kind']in {'HOOK_STARTED','HOOK_FINISHED'}
@pytest.mark.parametrize('message',["Operational evidence terminal delivery: SECRET",'Operational evidence terminal delivery: {"status":"FAILED","reason":"SECRET"}'])
def test_malformed_result_redacted(module,message):
 value=module.sanitize_logs([row(message)],FLOW);assert value[0]['kind']=='MALFORMED_TERMINAL_RESULT';assert 'SECRET'not in json.dumps(value)
def test_exception_projection(module):
 value=module.sanitize_logs([row("_operational_evidence_terminal_hook NameError: name 'json' is not defined /private/SECRET?token=SECRET")],FLOW)
 assert value[0]['exceptions']==['NameError'] and value[0]['missing_symbol']=='json';assert 'SECRET'not in json.dumps(value)
@pytest.mark.parametrize('field,value',[('flow_run_id','22222222-2222-4222-8222-222222222222'),('timestamp','2026-11-07T08:40:00Z'),('message','x'*65537)])
def test_scope_rejection(module,field,value):
 r=row('message');r[field]=value
 with pytest.raises(op.InvalidEvidence):module.sanitize_logs([r],FLOW)
def test_request_fixed(module):
 body=module.log_body(FLOW);assert body['logs']['flow_run_id']=={'any_':[FLOW['id']]};assert body['limit']==64
 assert body['logs']['text']=={'query':'operational'};assert op.timestamp(body['logs']['timestamp']['before_'])==op.timestamp(FLOW['end_time'])+dt.timedelta(seconds=120)
@pytest.mark.parametrize('status,encoding,data',[(500,None,b'{}'),(200,'gzip',b'[]'),(200,None,b'x'*262145),(200,None,b'[')])
def test_response_bounds(module,monkeypatch,status,encoding,data):
 closed=[]
 class Connection:
  def request(self,*args,**kwargs):assert args[:2]==('POST','/api/logs/filter')
  def getresponse(self):return SimpleNamespace(status=status,getheader=lambda n:'application/json'if n=='Content-Type'else encoding,read=lambda limit:data)
  def close(self):closed.append(True)
 monkeypatch.setattr(module.http_client,'HTTPConnection',lambda host,port,timeout:Connection() if(host,port,timeout)==('127.0.0.1',4200,3)else None)
 with pytest.raises(Exception):module.logs(FLOW)
 assert closed==[True]
def test_summary_exact_identity_and_redaction(module):
 secret={'prefect_flow_run_id':FLOW['id'],'run_id':'a'*32,'next24h_forecast_status':'GENERATED','next24h_publication_status':'PUBLISHED','token':'SECRET'}
 class Connection:
  def set_progress_handler(self,*a):pass
  def execute(self,sql,args):assert sql.startswith('SELECT substr(message,1,262145)') and args==(FLOW['start_time'],FLOW['end_time']);return self
  def fetchmany(self,n):assert n==13;return [(json.dumps(secret),)]
 result=module.summary(Connection(),FLOW);assert result['pipeline_run_id']=='a'*32;assert 'SECRET'not in json.dumps(result)
def test_grammar_and_no_mutators():
 raw=PATH.read_text();tree=ast.parse(raw,feature_version=(3,9))
 forbidden={'Popen','run','system','mkdir','chmod','chown','replace','unlink','publish','publish_terminal','deliver_terminal','capture_terminal','invoke','notify'}
 assert not [n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in forbidden]
