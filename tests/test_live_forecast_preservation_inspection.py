"""Offline component/replay/sanitization tests. No SSH or application execution."""
import ast
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import pytest
from shared import operational_evidence as OP
ROOT=Path(__file__).parents[1];HERE=ROOT/'deploy/staging/live-forecast-preservation-inspection-v1'
def load(name):
    s=importlib.util.spec_from_file_location('preservation_'+name,HERE/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
class Stop(ValueError):pass
def need(v,code):
    if not v:raise Stop(code)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(v):return sha(json.dumps(v,sort_keys=True).encode())
def scope():
    m=load('inspect');m.need=need;m.JOB=types.SimpleNamespace(sha=sha,H=types.SimpleNamespace(OP=OP));return m

@pytest.mark.parametrize('key',load('inspect').KEYS)
def test_component_report_no_values(key):
    m=scope();a={k:'fixed'for k in m.KEYS};b=dict(a);b[key]='secret/path/token'
    out=m.compare(a,b);assert out[key]=='DIFFERENT' and list(out.values()).count('DIFFERENT')==1
    assert 'secret'not in json.dumps(out)

def test_production_replay_resolves_only_two_fixed_output_paths():
    m=scope();prefix=Path('/home/ec2-user/Electricity_Trading_Pipeline');keys=['data/reports/next24h_forecast.csv','data/reports/next24h_forecast_provenance.json'];paths=[prefix/k for k in keys]+[Path('/fixed-config')]
    current={paths[0]:'c'*64,paths[1]:'d'*64,paths[2]:'fixed'};old={keys[0]:'a'*64,keys[1]:'b'*64};calls=[]
    def original(p):calls.append(p);return current[p]
    m.JOB.B={'digest':original};m.JOB.P=types.SimpleNamespace(production=lambda:digest({str(p):m.JOB.B['digest'](p)for p in paths}))
    expected=digest({str(paths[0]):'a'*64,str(paths[1]):'b'*64,str(paths[2]):'fixed'})
    assert m.replay_production(expected,old)=='MATCH_EXCEPT_PIPELINE_OUTPUTS'
    assert calls==paths and m.JOB.B['digest']is original
    current[paths[2]]='unexpected config'
    assert m.replay_production(expected,old)=='UNRESOLVED_PRODUCTION_DIFFERENCE'

def test_replay_restores_original_on_failure_and_rejects_arbitrary_paths():
    m=scope();original=lambda _: 'hash';m.JOB.B={'digest':original}
    m.JOB.P=types.SimpleNamespace(production=lambda:(_ for _ in ()).throw(Stop('SECURITY_GATE')))
    with pytest.raises(Stop,match='REPLAY_SCOPE'):m.replay_production('hash',{'/secret':'a'*64})
    outputs={p:'a'*64 for p in ['data/reports/next24h_forecast.csv','data/reports/next24h_forecast_provenance.json']}
    with pytest.raises(Stop,match='SECURITY_GATE'):m.replay_production('hash',outputs)
    assert m.JOB.B['digest']is original

def test_legacy_serialization_preserves_actual_production_order(monkeypatch):
    m=scope();tree=ast.parse((ROOT/'src/models/next24h_production.py').read_bytes())
    assignment=next(n for n in ast.walk(tree)if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='provenance'for t in n.targets)and isinstance(n.value,ast.Dict))
    keys=[k.value for k in assignment.value.keys];provenance={k:'test-'+k for k in keys}
    expected=sha((json.dumps(provenance,indent=2)+'\n').encode());receipt=json.dumps(dict(provenance,inference_evidence={'run_id':'test'}),sort_keys=True).encode()
    bundle={'identity':'bundle'};files={'forecast.csv':b'csv\n','provenance.json':receipt}
    producer=types.SimpleNamespace(receipt_bundle=lambda f,now:(bundle,'a'*64));monkeypatch.setitem(sys.modules,'shared.operational_evidence_producer',producer)
    out=m.legacy_hashes(files,bundle,'a'*64)
    assert out['data/reports/next24h_forecast_provenance.json']==expected
    assert out['data/reports/next24h_forecast.csv']==sha(b'csv\n')
    with pytest.raises(Stop,match='BASELINE_RECEIPT_ASSOCIATION'):m.legacy_hashes(files,bundle,'b'*64)
    producer.receipt_bundle=lambda *a:(_ for _ in ()).throw(Stop('RECEIPT_HASH'))
    with pytest.raises(Stop,match='RECEIPT_HASH'):m.legacy_hashes(files,bundle,'a'*64)

def store_fixture():
    old={'contract':'contract-hash','current':'a'*64,'releases':{'a'*64:'a'*64}}
    new={'contract':'contract-hash','current':'b'*64,'releases':dict(old['releases'],**{'b'*64:'b'*64})}
    records={'a'*64:{'observed_at':'2026-11-07T18:47:00Z'},'b'*64:{'observed_at':'2026-11-07T19:47:00Z'}}
    return old,new,records

def test_store_advancement_reconstructs_unchanged_historical_inventory():
    m=scope();old,new,records=store_fixture()
    assert m.reconstruct_store(digest(old),'2026-11-07T19:03:00Z',new,records)=='BASELINE_RECONSTRUCTED_SUBSET'
@pytest.mark.parametrize('change',['deletion','modified-old','namespace','extra-historical','wrong-cutoff'])
def test_store_protected_changes_never_silently_accepted(change):
    m=scope();old,new,records=store_fixture();cutoff='2026-11-07T19:03:00Z'
    if change=='deletion':new['releases'].pop('a'*64);records.pop('a'*64)
    elif change=='modified-old':new['releases']['a'*64]='c'*64
    elif change=='namespace':new['contract']='wrong'
    elif change=='extra-historical':new['releases']['c'*64]='c'*64;records['c'*64]={'observed_at':'2026-11-07T17:00:00Z'}
    else:cutoff='2026-11-07T17:00:00Z'
    assert m.reconstruct_store(digest(old),cutoff,new,records)=='UNRESOLVED_STORE_DIFFERENCE'

def test_idle_gate_failure_prevents_all_inspection():
    m=scope();m.JOB.P=types.SimpleNamespace(idle=lambda _:(_ for _ in ()).throw(Stop('PIPELINE_OR_WINDOW_GATE')))
    with pytest.raises(Stop,match='PIPELINE_OR_WINDOW_GATE'):m.inspect()
    assert m.STAGE=='IDLE_WINDOW'

def test_end_to_end_mock_all_components_match():
    m=scope();before={k:'fixed'for k in m.KEYS};r={'phase':'APPLIED','activated_at':'2026-11-07T19:03:00Z','baseline':dict(before,venv='/venv',runtime='closure')};calls=[]
    link=lambda target:types.SimpleNamespace(resolve=lambda **_:target)
    m.JOB.P=types.SimpleNamespace(idle=lambda _:calls.append('idle'),candidate_environment=lambda _:None,BACKEND_LINK=link('api'),STATIC_LINK=link('static'),runtime_closure=lambda _:'closure')
    m.JOB.load_record=lambda:r;m.JOB.verified_backups=lambda _:None;m.JOB.old_trees=lambda:None;m.JOB.tree_state=lambda *a,**kw:None;m.JOB.G={'runtime':lambda _:None};m.JOB.API='api';m.JOB.STATIC='static';m.JOB.baseline_preservation=lambda:dict(before)
    report=m.inspect();assert report['status']=='PASS' and report['stage']=='COMPLETE' and report['production_resolution']=='MATCH' and calls==['idle','idle']
    load('run').validate_report(report)
    calls.clear();counter=iter([dict(before),dict(before,policy='changed')]);m.JOB.baseline_preservation=lambda:next(counter)
    with pytest.raises(Stop,match='SNAPSHOT_CHANGED'):m.inspect()

def test_no_mutation_entrypoints_assembly_python39():
    b=load('build');payload,_,_=b.assemble();ast.parse(payload,feature_version=(3,9))
    for n in ['run.py','build.py','inspect.py']:ast.parse((HERE/n).read_bytes(),feature_version=(3,9))
    functions=set()
    for n in ast.walk(ast.parse(payload)):
        if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='compile'and isinstance(n.args[0],ast.Constant)and isinstance(n.args[0].value,(str,bytes)):
            functions.update(t.name for t in ast.walk(ast.parse(n.args[0].value))if isinstance(t,ast.FunctionDef))
    assert not {'apply','rollback','write','mkdir','restart','publish','deliver_terminal'}&functions
    assert b'report=JOB.accept_report()'not in payload
    if (HERE/'MANIFEST.json').exists():
        raw=(HERE/'MANIFEST.json').read_bytes();assert load('run').verify(sha(raw))[0]==payload

def test_report_rejects_sensitive_values_unknown_fields_and_raw_errors():
    runner=load('run')
    good={'status':'BLOCKED','changed':False,'stage':'IDLE_WINDOW','reason':'PIPELINE_OR_WINDOW_GATE'};runner.validate_report(good)
    for bad in [dict(good,reason='/private/path SECRET'),dict(good,token='secret')]:
        with pytest.raises(AssertionError):runner.validate_report(bad)
