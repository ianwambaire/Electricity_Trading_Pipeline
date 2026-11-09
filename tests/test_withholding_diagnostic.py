"""Synthetic exact-run records; no network, real production data or DB writes."""
import ast,copy,datetime as dt,hashlib,importlib.util,json
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1];FOLDER=ROOT/'deploy/staging/forecast-publication/withholding-diagnostic'
def load(name):
    s=importlib.util.spec_from_file_location('withholding_'+name,FOLDER/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
@pytest.fixture
def context():
    r=load('run');m=load('inspect');reader=r.namespace(r.reader_source((ROOT/r.PREFECT_SOURCE).read_bytes()),'reader');m.R=reader
    start='2026-11-03T16:47:00+00:00';end='2026-11-03T16:47:02+00:00';when='2026-11-03T16:47:03+00:00'
    f={'id':m.FLOW,'deployment_id':'47e5ef51-26d0-44b6-b119-2c40d0e77397','auto_scheduled':True,'expected_start_time':m.SCHEDULED,'start_time':'2026-11-03T16:44:59+00:00','end_time':'2026-11-03T16:47:17+00:00','state':{'type':'COMPLETED'}}
    t={'id':'22222222-2222-4222-8222-222222222222','flow_run_id':m.FLOW,'name':'Generate next24h production forecast','start_time':start,'end_time':end,'state':{'type':'COMPLETED'}}
    hours={'price':'2026-11-03T15:00:00+00:00','load':'2026-11-03T13:00:00+00:00','generation':'2026-11-03T13:00:00+00:00'}
    value={'next24h_publication_status':'SKIPPED_WITHHELD','next24h_forecast_status':'WITHHELD','next24h_forecast_generated':False,'next24h_forecast_withheld_at_utc':when,'next24h_latest_complete_market_hours':hours}
    incident={'run_id':'a'*32,'reason':'Required load history unavailable for a fresh issue hour.','timestamp':when,'forecast_freshness_status':'WITHHELD','latest_complete_hours':hours}
    class Cursor:
        def fetchall(self):return [{'timestamp_utc':when,'details':json.dumps(incident)}]
    class DB:
        def execute(self,sql,args):
            assert sql.startswith('SELECT ') and 'operational_incidents' in sql and args[0:2]==('next24h forecast','forecast_withheld')
            return Cursor()
    return m,reader,f,t,value,incident,DB()

def test_precise_persisted_gate_and_expected_missing_receipt(context):
    m,r,f,t,v,i,c=context;out=m.detail(c,f,t,v,'a'*32,{'status':'WITHHELD'})
    assert out['failed_prerequisite']['gate']=='LOAD_HISTORY' and out['receipt_expected']is False
    assert out['failed_prerequisite']['reason']==i['reason'] and not out['gaps']

@pytest.mark.parametrize('kind',['missing','wrong_internal','bad_json','ambiguous','wrong_time','hours_disagree','generated','wrong_stage'])
def test_missing_or_malformed_evidence(context,kind):
    m,r,f,t,v,i,c=context
    if kind in ['missing','ambiguous','bad_json']:
        class Cursor:
            def fetchall(self):return [] if kind=='missing' else [{'timestamp_utc':i['timestamp'],'details':'bad' if kind=='bad_json' else json.dumps(i)}]*2
        c=type('DB',(),{'execute':lambda *args:Cursor()})()
    if kind=='wrong_internal':i['run_id']='b'*32
    if kind=='wrong_time':i['timestamp']='2026-11-03T16:00:00+00:00'
    if kind=='hours_disagree':i['latest_complete_hours']=dict(i['latest_complete_hours'],load=None)
    if kind=='generated':v['next24h_forecast_generated']=True
    if kind in ['missing','wrong_internal']:
        assert m.detail(c,f,t,v,'a'*32,{'status':'WITHHELD'})['gaps']==['MISSING_WITHHOLDING_INCIDENT']
    else:
        with pytest.raises(Exception):m.detail(c,f,t,v,'a'*32,{'status':'SUCCESS' if kind=='wrong_stage' else 'WITHHELD'})

@pytest.mark.parametrize('reason,gate',[
 ('Required price history unavailable for a fresh issue hour.','PRICE_HISTORY'),
 ('Latest complete market hour for load 2026-11-03T12:00:00+00:00 exceeds the 3-hour freshness threshold.','LOAD_FRESHNESS'),
 ('Operational weather unavailable: PRIVATE_TOKEN','WEATHER_SOURCE'),
 ('PRIVATE_TOKEN unrecognized problem','UNVERIFIED'),
 ('No fresh issue hour has 31 finite market and weather features.','FINITE_31_FEATURES')])
def test_reason_classification_no_secret_leak(context,reason,gate):
    m,*_=context;out=m.classify(reason);assert out['gate']==gate and 'PRIVATE_TOKEN' not in json.dumps(out)
    assert out['reason_sha256']==hashlib.sha256(reason.encode()).hexdigest()

def test_exact_run_and_internal_association_flow(context):
    m,r,f,t,v,i,c=context;p=dict(t,id='33333333-3333-4333-8333-333333333333',name='Publish validated staging next24h forecast',start_time='2026-11-03T16:47:04+00:00',end_time='2026-11-03T16:47:05+00:00')
    calls=[]
    def query(method,path,body=None):
        calls.append((method,path,body));return f if method=='GET' else [t,p]
    r.update(prefect_request=query,database_outcome=lambda flow,task:m.detail(c,flow,task,v,'a'*32,{'status':'WITHHELD'}))
    out=m.validate_report(m.inspect());assert out['status']=='PASS' and out['internal_run_uuid']!=m.FLOW
    assert calls[0][1]=='/flow_runs/'+m.FLOW and calls[1][2]['task_runs']['flow_run_id']['any_']==[m.FLOW]
    f['auto_scheduled']=False;assert m.inspect()['gaps']==['TARGET_RUN_BINDING']

def test_unknown_error_sanitized(context):
    m,r,*_=context;r['prefect_request']=lambda *a:(_ for _ in ()).throw(OSError('PRIVATE_TOKEN /secret'))
    out=m.validate_report(m.inspect());assert out['gaps']==['EVIDENCE_UNVERIFIED'] and 'PRIVATE_TOKEN' not in json.dumps(out)

def test_extraction_is_only_two_readonly_changes():
    r=load('run');raw=(ROOT/r.PREFECT_SOURCE).read_bytes();tree=ast.parse(r.reader_source(raw))
    assert {n.name for n in tree.body if isinstance(n,ast.FunctionDef)}=={'need','stamp','uid','state','task','prefect_request','directory','database_outcome'}
    source=ast.unparse(tree)
    assert 'mode=ro&immutable=1' in source and 'PRAGMA query_only=ON' in source and 'operational_incidents' in source
    assert 'return detail(c, flow, t, value, internal, rows[0])' in source
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {'write','mkdir','unlink','chmod','chown','publish','rollback'} for n in ast.walk(tree))
    assert 'os.replace(' not in source
    assert 'Popen' not in source and 'build(' not in source

def test_manifest_and_payload_closure(monkeypatch):
    r=load('run');raw=(FOLDER/'MANIFEST.json').read_bytes();m=json.loads(raw)
    real=r.namespace;monkeypatch.setattr(r,'namespace',lambda raw,name,file=None:{'profile':lambda:{}} if name=='wrapper' else real(raw,name,file))
    payload,_,_,_=r.verify(hashlib.sha256(raw).hexdigest());assert hashlib.sha256(payload).hexdigest()==m['payload_sha256']
    assert b'publish_automatic' not in payload and b'next24h_inference' not in payload
    read=r.read;monkeypatch.setattr(r,'read',lambda p:b'drift' if p==ROOT/r.PREFECT_SOURCE else read(p))
    with pytest.raises(ValueError,match='dependency_hash'):r.verify(hashlib.sha256(raw).hexdigest())

from test_automatic_acceptance import captured
import test_automatic_acceptance as prior
@pytest.mark.parametrize('kind',['valid','missing_status','journal','symlink','ambiguous','bad_internal','wrong_issue_source'])
def test_reused_real_sqlite_guard(captured,tmp_path,monkeypatch,kind):
    sample=prior.sample.__wrapped__(captured,monkeypatch);module=sample[0];runner=load('run')
    exec(compile(runner.reader_source((ROOT/runner.PREFECT_SOURCE).read_bytes()),'<extracted-readonly-reader>','exec'),module.__dict__)
    # Isolate unchanged snapshot/association machinery from incident projection;
    # projection itself is tested above with bounded synthetic incident rows.
    module.detail=lambda c,flow,t,value,internal,stage:{'internal_run_id':internal,'status':value.get('next24h_publication_status')}
    prior.test_readonly_database_association_in_isolated_fixture(sample,tmp_path,monkeypatch,kind)
