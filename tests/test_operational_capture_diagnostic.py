"""Offline capture-stage replay, no SSH or publisher calls."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
from shared import operational_capture as capture
from shared import operational_evidence as op
from test_operational_terminal import stable,fixture_source,source_api
from test_current_operations import association,NOW
PATH=Path(__file__).resolve().parents[1]/'deploy/staging/operational-capture-diagnostic-v1/inspect.py'
@pytest.fixture
def m():
 spec=importlib.util.spec_from_file_location('capture_diag',PATH);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 m.OP=op;m.PLAN=SimpleNamespace(need=op.require);return m

def prepare(m,stable,tmp_path,monkeypatch):
 source,db=fixture_source(stable,tmp_path,monkeypatch)
 api,_=source_api(stable)
 m.FLOW=stable['flow']['id'];m.PIPELINE='a'*32
 m.CAPTURE=SimpleNamespace(capture_terminal=lambda *args,**kwargs:capture.capture_terminal(*args,source=source,**kwargs),query=api,NAMES=capture.NAMES)
 monkeypatch.delitem(sys.modules,'shared.operational_evidence_store',raising=False)
 return source,db

def test_replay_success_never_publishes(m,stable,tmp_path,monkeypatch):
 source,db=prepare(m,stable,tmp_path,monkeypatch);before=db.read_bytes()
 result=m.replay(stable['flow'],lambda:NOW)
 assert result['capture']=='PASS' and result['pipeline_association_verified'] and result['request_count']==3
 assert db.read_bytes()==before and sys.gettrace()is None

@pytest.mark.parametrize('kind',['permission','pipeline','missing_receipt','journal','retry'])
def test_replay_exact_gate(m,stable,tmp_path,monkeypatch,kind):
 source,db=prepare(m,stable,tmp_path,monkeypatch)
 expected={'permission':'SOURCE_METADATA','pipeline':'TARGET_PIPELINE_IDENTITY','missing_receipt':'RECEIPT_INVENTORY','journal':'ACTIVE_JOURNAL','retry':'FLOW_RETRY_UNVERIFIED'}[kind]
 if kind=='permission':next((source.root/'data/reports/next24h_inference').glob('*/forecast.csv')).chmod(0o644)
 elif kind=='pipeline':m.PIPELINE='b'*32
 elif kind=='missing_receipt':next((source.root/'data/reports/next24h_inference').glob('*/forecast.csv')).unlink()
 elif kind=='journal':Path(str(db)+'-wal').write_bytes(b'active')
 else:stable['flow']['run_count']=2
 before=db.read_bytes();result=m.replay(stable['flow'],lambda:NOW)
 assert result['capture']=='FAILED' and result['failure'].get('gate')==expected and (result['propagation'] or kind=='pipeline')
 assert db.read_bytes()==before and sys.gettrace()is None
 if kind=='permission':assert any(r.get('artifact')=='forecast.csv' and r.get('metadata',{}).get('mode')==0o644 for r in result['propagation'])

@pytest.mark.parametrize('error',[ValueError('SECRET'),KeyError('SECRET'),op.InvalidEvidence('SECRET')])
def test_no_message_disclosure(m,error):assert 'SECRET'not in str(m.classify(error))
def test_known_gate(m):assert m.classify(op.InvalidEvidence('ACTIVE_JOURNAL'))['gate']=='ACTIVE_JOURNAL'
def test_forbidden_call_blocked_before_body(m,monkeypatch):
 namespace={'__name__':'shared.operational_capture','CALLED':False}
 exec('def publish():\n global CALLED\n CALLED=True',namespace)
 observer=m.Observation()
 try:
  sys.settrace(observer.trace)
  with pytest.raises(op.InvalidEvidence,match='READ_ONLY_BOUNDARY'):namespace['publish']()
 finally:sys.settrace(None)
 assert namespace['CALLED']is False

def test_readonly_grammar_and_no_mutating_call():
 tree=ast.parse(PATH.read_text(),feature_version=(3,9));bad={'publish','publish_terminal','deliver_terminal','main','notify','invoke','write','mkdir','chmod','chown','replace','unlink','Popen','run','system'}
 assert not [n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in bad]
