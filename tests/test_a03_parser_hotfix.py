"""Synthetic parser-only deployment tests; no SSH, imports of production code or service actions."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest
ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'deploy/staging/a03-parser-hotfix'
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
D=load('parser_hotfix_job',HERE/'deploy.py');R=load('parser_hotfix_runner',HERE/'run.py')
@pytest.fixture
def host(tmp_path,monkeypatch):
    target=tmp_path/'checkout/src/ingestion/fetch_entsoe_data.py';target.parent.mkdir(parents=True)
    target.write_bytes(b'answer = 1\n');target.chmod(0o644)
    parent=tmp_path/'private/hotfix';parent.parent.mkdir()
    for key,value in {'ROOT':tmp_path/'checkout','TARGET':target,'PARENT':parent,'OLD':D.sha(b'answer = 1\n'),'NEW':D.sha(b'answer = 2\n'),'CONFIG':{'transaction_id':'a'*32,'source':b'answer = 2\n'},'CHANGED':False,'MUTATION':False,'PHASE':'PREFLIGHT'}.items():monkeypatch.setattr(D,key,value,raising=False)
    monkeypatch.setattr(D,'safe',lambda *a,**k:None);monkeypatch.setattr(D.os,'geteuid',lambda:0)
    monkeypatch.setattr(D.os,'fchown',lambda *a:None);monkeypatch.setattr(D.os,'chown',lambda *a:None)
    def info(path):return {'uid':1000 if path==target else 0,'gid':1000 if path==target else 0,'mode':path.stat().st_mode&0o777,'regular':path.is_file()}
    monkeypatch.setattr(D,'info',info);monkeypatch.setattr(D,'read',lambda p,limit=64000000:Path(p).read_bytes())
    monkeypatch.setattr(D,'idle',lambda:None);monkeypatch.setattr(D,'preserve',lambda:'a'*64)
    monkeypatch.setattr(D,'resources',lambda:{'available_bytes':900*1024**2,'swap_used_bytes':0,'disk_available_bytes':5*1024**3})
    return target

def test_one_file_apply_and_independent_rollback(host):
    assert D.apply()['status']=='APPLIED';assert host.read_bytes()==b'answer = 2\n'
    control=D.PARENT/('a'*32);assert (control/'original.py').read_bytes()==b'answer = 1\n'
    assert (control/'original.py').stat().st_mode&0o777==0o600
    assert D.rollback()['status']=='ROLLED_BACK' and host.read_bytes()==b'answer = 1\n'
    assert json.loads((control/'state.json').read_bytes())['phase']=='ROLLED_BACK'
    with pytest.raises(D.Stop):D.rollback()

@pytest.mark.parametrize('gate',['source','mode','active','ram','preservation','collision','input'])
def test_preflight_failure_does_not_change_source(host,monkeypatch,gate):
    if gate=='source':host.write_bytes(b'changed')
    if gate=='mode':host.chmod(0o666)
    if gate=='active':monkeypatch.setattr(D,'idle',lambda:(_ for _ in ()).throw(D.Stop('PIPELINE_OR_WINDOW_GATE')))
    if gate=='ram':monkeypatch.setattr(D,'resources',lambda:(_ for _ in ()).throw(D.Stop('RAM_GATE')))
    if gate=='preservation':monkeypatch.setattr(D,'preserve',lambda:(_ for _ in ()).throw(D.Stop('SERVICE_STATE')))
    if gate=='collision':D.PARENT.mkdir();(D.PARENT/('a'*32)).mkdir()
    if gate=='input':D.CONFIG['source']=b'mismatch'
    before=host.read_bytes()
    with pytest.raises(D.Stop):D.apply()
    assert host.read_bytes()==before and not D.MUTATION and not D.CHANGED

@pytest.mark.parametrize('late',['backup','source','window','preservation'])
def test_late_failure_keeps_verified_original_active(host,monkeypatch,late):
    if late=='backup':
        original=D.create
        def create(path,*a,**k):
            original(path,*a,**k)
            if path.name=='original.py':path.write_bytes(b'bad')
        monkeypatch.setattr(D,'create',create)
    if late=='source':
        original=D.record_write
        def save(*a):original(*a);host.write_bytes(b'changed-by-someone-else')
        monkeypatch.setattr(D,'record_write',save)
    if late in ('window','preservation'):
        name='idle' if late=='window' else 'preserve';calls=[]
        def fail():
            calls.append(1)
            if len(calls)>1:raise D.Stop('PIPELINE_OR_WINDOW_GATE' if late=='window' else 'PRODUCTION_DRIFT')
            return 'a'*64
        monkeypatch.setattr(D,name,fail)
    with pytest.raises(D.Stop):D.apply()
    assert not D.MUTATION
    if late!='source':assert host.read_bytes()==b'answer = 1\n'

def test_post_install_failure_retains_usable_record_no_automatic_rollback(host,monkeypatch):
    original=D.replace_source
    def replace(*args):
        original(*args);raise D.Stop('INSTALLED_VERIFY')
    monkeypatch.setattr(D,'replace_source',replace)
    with pytest.raises(D.Stop):D.apply()
    assert D.MUTATION and host.read_bytes()==b'answer = 2\n'
    record=json.loads((D.PARENT/('a'*32)/'state.json').read_bytes());assert record['phase']=='INSTALLING'
    monkeypatch.setattr(D,'replace_source',original)
    assert D.rollback()['status']=='ROLLED_BACK'

@pytest.mark.parametrize('drift',['backup','source','record','production','pipeline'])
def test_rollback_stops_on_drift_without_overwriting(host,monkeypatch,drift):
    D.apply();control=D.PARENT/('a'*32)
    if drift=='backup':(control/'original.py').write_bytes(b'bad')
    if drift=='source':host.write_bytes(b'other')
    if drift=='record':
        record=json.loads((control/'state.json').read_bytes());record['transaction_id']='b'*32;(control/'state.json').write_text(json.dumps(record))
    if drift=='production':monkeypatch.setattr(D,'preserve',lambda:'b'*64)
    if drift=='pipeline':monkeypatch.setattr(D,'idle',lambda:(_ for _ in ()).throw(D.Stop('PIPELINE_OR_WINDOW_GATE')))
    before=host.read_bytes()
    with pytest.raises(D.Stop):D.rollback()
    assert host.read_bytes()==before

def test_manifest_executable_closure_and_source_identity():
    m=json.loads((HERE/'MANIFEST.json').read_bytes());assert set(m['artifacts'])==R.ARTIFACTS
    for name,item in m['artifacts'].items():
        raw=(ROOT/name).read_bytes();assert len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256']
    assert m['new_sha256']==R.NEW and m['baseline_sha256']==R.OLD
    blobs={name:(ROOT/name).read_bytes() for name in R.ARTIFACTS}
    for action in ('apply','rollback'):assert hashlib.sha256(R.assemble(blobs,m['transaction_id'],action)).hexdigest()==m['assembled_sha256'][action]

def test_changed_artifact_rejected_before_connection(monkeypatch):
    monkeypatch.setattr(R,'namespace',lambda *a,**kw:pytest.fail('Unverified helpers must not execute'))
    with pytest.raises(ValueError):R.verify('0'*64,'apply')

def test_runner_retains_source_bytes_after_verification():
    blobs={R.BASE:b'pass',R.SOURCE:b'approved source',R.JOB:b'pass'}
    original=R.assemble(blobs,'a'*32,'apply');blobs[R.SOURCE]=b'changed'
    assert b'approved source' in original and b'changed' not in original
    with pytest.raises(ValueError):R.assemble(blobs,'a'*32,'arbitrary-command')

def test_source_projection_unchanged_outside_two_parser_functions_and_math_import():
    comparison=json.loads((HERE/'BASELINE-COMPARISON.json').read_bytes())
    tree=ast.parse((ROOT/R.SOURCE).read_bytes())
    tree.body=[n for n in tree.body if not(isinstance(n,ast.FunctionDef) and n.name in ('parse_price_observations','query_price_observations')) and not(isinstance(n,ast.Import) and ast.unparse(n)=='import math')]
    assert hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest()==comparison['unchanged_ast_sha256']

def test_no_producer_service_action_or_forecast_reachable():
    source=(HERE/'deploy.py').read_text();tree=ast.parse(source,feature_version=(3,9))
    assert all(not(isinstance(n,ast.Import) and any(a.name in ('requests','pandas','joblib') for a in n.names)) for n in ast.walk(tree))
    assert 'subprocess' not in source and 'restart' not in source.replace('no_services_restarted','')
    assert 'run_next24h_forecast' not in source and 'parse_price_observations(' not in source

def test_failure_report_rejects_raw_messages():
    report={'status':'PARTIAL','phase':'INSTALL','reason':'INSTALLED_VERIFY','source_may_have_changed':True,'automatic_rollback':False}
    assert R.validate(report,'apply',1)==report
    for change in ({'reason':'PRIVATE_SENTINEL'},{'automatic_rollback':True},{'source_may_have_changed':'yes'}):
        with pytest.raises(ValueError):R.validate(dict(report,**change),'apply',1)
