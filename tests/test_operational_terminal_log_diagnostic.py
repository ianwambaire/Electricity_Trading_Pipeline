"""Offline synthetic log files; no real logs, browser, SSH or network."""
import ast
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'deploy/staging/operational-terminal-log-diagnostic-v1/inspect.py'
START='2026-11-07 08:47:30,000';END='2026-11-07 08:48:00,000'
@pytest.fixture
def m():
 spec=importlib.util.spec_from_file_location('log_diagnostic',PATH);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 def need(v,c):
  if not v:raise ValueError(c)
 m.PLAN=SimpleNamespace(need=need);return m

def line(at,message):return (at+' - WARNING - test - '+message+'\n').encode()
@pytest.mark.parametrize('status,reason',[('FAILED','CAPTURE_UNVERIFIED'),('FAILED','TERMINAL_CAPTURE_UNVERIFIED'),('FAILED','IMMUTABLE_RUNTIME_UNVERIFIED'),('FAILED','HOOK_UNAVAILABLE'),('FAILED','OPERATIONAL_STORE_UNCERTAIN'),('PUBLISHED',None),('DISABLED',None),('SKIPPED_NOT_NATURAL',None),('SKIPPED_DUPLICATE',None)])
def test_result(m,status,reason):
 value={'status':status};value.update({'reason':reason}if reason else {})
 result=m.project(line('2026-11-07 08:47:42,000',m.PREFIX+json.dumps(value)),START,END)
 assert result[0]['status']==status and result[0].get('reason')==reason
@pytest.mark.parametrize('at',['2026-11-07 08:47:29,999','2026-11-07 08:48:00,001','2026-11-06 08:47:42,000'])
def test_window(m,at):assert m.project(line(at,m.PREFIX+'{"status":"PUBLISHED"}'),START,END)==[]
def test_unrelated_and_secret_redaction(m):
 raw=line('2026-11-07 08:47:41,000','SECRET token=PRIVATE')+line('2026-11-07 08:47:42,000',m.PREFIX+'{"status":"FAILED","reason":"SECRET"}')
 result=m.project(raw,START,END);assert len(result)==1 and result[0]['kind']=='UNRECOGNIZED_TERMINAL_RESULT';assert 'SECRET'not in json.dumps(result) and 'PRIVATE'not in json.dumps(result)
def test_exception_projection(m):
 raw=line('2026-11-07 08:47:42,000','_operational_evidence_terminal_hook traceback SECRET')+b"NameError: name 'json' is not defined SECRET\n"
 result=m.project(raw,START,END);assert result[0]['exception_classes']==['NameError'] and result[0]['approved_symbols']==['json'];assert 'SECRET'not in json.dumps(result)
def test_no_context_bleed(m):
 raw=line('2026-11-07 08:47:42,000','_operational_evidence_terminal_hook')+line('2026-11-07 08:47:43,000','unrelated')+b'NameError: SECRET\n'
 assert m.project(raw,START,END)[0]['exception_classes']==[]
def test_result_bound(m):
 with pytest.raises(ValueError,match='RESULT_BOUND'):m.project(line('2026-11-07 08:47:42,000',m.PREFIX+'{"status":"PUBLISHED"}')*17,START,END)
@pytest.mark.parametrize('padding',[0,1000,100000])
def test_bounded_seek(m,tmp_path,padding):
 p=tmp_path/'fixture';data=line('2026-11-07 08:45:00,000','a'*100)*padding+line('2026-11-07 08:47:42,000',m.PREFIX+'{"status":"DISABLED"}')+line('2026-11-07 09:45:00,000','b'*100)*padding
 p.write_bytes(data);fd=os.open(p,os.O_RDONLY)
 try:
  if padding:
   raw,count=m.read_window(fd,len(data),START,END);assert m.project(raw,START,END)[0]['status']=='DISABLED' and count<=2*1024*1024
  else:
   with pytest.raises(ValueError,match='WINDOW_NOT_COVERED'):m.read_window(fd,len(data),START,END)
 finally:os.close(fd)
def test_grammar_readonly():
 tree=ast.parse(PATH.read_text(),feature_version=(3,9));blocked={'write','mkdir','chmod','chown','replace','unlink','Popen','system','notify','invoke','capture_terminal','publish','request','connect'}
 assert not [n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in blocked]
