"""Offline association/API integration: synthetic bytes and temporary SQLite only."""
import copy
import csv
import datetime as dt
import hashlib
import io
import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from api.app import APISettings, create_app
from api.security import CurrentUser, get_current_user
from shared import forecast_publication as forecast
from shared import operational_evidence as contract
from shared import operational_evidence_store as store
from shared.operational_evidence_producer import associate, from_snapshot, latest_natural
from test_forecast_publication import fixture as forecast_fixture, ISSUE, NOW
from test_operational_evidence import fixture as op_fixture, encoded, root_at

FLOW='11111111-1111-4111-8111-111111111111'
DEP='33333333-3333-4333-8333-333333333333'
INTERNAL='a'*32


def receipt_files():
    b=forecast_fixture(); out=io.StringIO(); writer=csv.writer(out,lineterminator='\n')
    writer.writerow(['forecast_issue_time','target_timestamp','horizon_hours','predicted_price_eur_mwh','model_release'])
    for r in b['forecasts']:writer.writerow([r[k] for k in ['issue_time','target_time','horizon_hours','predicted_price_eur_mwh','model_release']])
    model=dict(release_id=forecast.RELEASE,model_sha256=forecast.MODEL_HASH,feature_contract_sha256=forecast.CONTRACT_HASH,feature_count=31,features=list(forecast.FEATURES),horizons_hours=list(range(1,25)))
    proof=dict(version=1,execution=b['execution'],inputs=b['inputs'],inference=dict(feature_names=list(forecast.FEATURES),feature_values=[b['inputs']['features'][k] for k in forecast.FEATURES],issue_time=b['forecasts'][0]['issue_time'],target_times=[r['target_time'] for r in b['forecasts']],model={k:model[k] for k in ['release_id','model_sha256','feature_contract_sha256']},source_sha256=dict.fromkeys(['price','load','generation'],'c'*64),release_manifest_sha256='d'*64))
    provenance=dict(forecast_issue_time=b['provenance']['issue_time'],weather_hour=b['provenance']['weather_hour'],weather_acquired_at_utc=b['provenance']['weather_acquired_at'],weather_source=b['provenance']['weather_source'],inference_evidence=dict(schema_version=1,run_id=b['execution']['run_id'],payload_sha256='pending'))
    # The feature receipt exceeds the operational document's 16KiB budget; its
    # existing independent 100KiB contract is used, never the operational encoder.
    encode=lambda v:json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    provenance['inference_evidence']['payload_sha256']=hashlib.sha256(encode(proof)).hexdigest()
    files={'forecast.csv':out.getvalue().encode(),'provenance.json':encode(provenance),'model.json':encode(model)}
    proof['artifacts']=dict(zip(['forecast_sha256','provenance_sha256','model_manifest_sha256'],[hashlib.sha256(files[n]).hexdigest() for n in ['forecast.csv','provenance.json','model.json']]))
    files['evidence.json']=encode(proof)
    files['integrity.json']=encode(dict(version=1,run_id=b['execution']['run_id'],sha256={n:hashlib.sha256(v).hexdigest() for n,v in files.items()}))
    return files


@pytest.fixture
def association():
    time=lambda m:(ISSUE+dt.timedelta(minutes=m)).isoformat()
    flow=dict(id=FLOW,deployment_id=DEP,auto_scheduled=True,expected_start_time=time(45),start_time=time(46),end_time=time(89),state={'type':'COMPLETED'})
    ft=dict(id='44444444-4444-4444-8444-444444444444',flow_run_id=FLOW,name='Generate next24h production forecast-test',start_time=time(59),end_time=time(82),state={'type':'COMPLETED'})
    pt=dict(id='55555555-5555-4555-8555-555555555555',flow_run_id=FLOW,name='Publish validated staging next24h forecast-test',start_time=time(83),end_time=time(84),state={'type':'COMPLETED'})
    meta=dict(run_id=INTERNAL,status='SUCCESS',next24h_forecast_status='GENERATED',next24h_forecast_generated=True,next24h_forecast_issue_time=ISSUE.isoformat(),next24h_publication_status='PUBLISHED',private='NEVER_EXPOSE')
    records=[dict(run_time=time(88),status='SUCCESS',message=json.dumps(meta))]
    stages=[dict(run_id=INTERNAL,stage_name='Next24h forecast generation',start_timestamp_utc=ft['start_time'],end_timestamp_utc=ft['end_time'],status='SUCCESS')]
    return dict(flow=flow,tasks=[ft,pt],records=records,stages=stages,incidents=[],receipts=[receipt_files()],expected_deployment=DEP,observed_at=NOW)


def produce(a):return associate(**a)
def summary(a, **changes):
    value=json.loads(a['records'][0]['message']);value.update(changes);a['records'][0]['message']=json.dumps(value)


def test_generated_association_and_no_live_eligibility_claim(association):
    raw,digest=produce(association); b=contract.validate(raw,digest,NOW)
    assert b['execution']['flow_run_id']==FLOW and b['execution']['pipeline_run_id']==INTERNAL
    assert b['inference']['outcome']=='GENERATED' and b['delivery']['outcome']=='PUBLISHED'
    assert b['delivery']['published_at'] is None
    assert b['execution']['completed_at']==association['flow']['end_time']
    assert contract.view(raw,digest,now=NOW)['forecast_eligibility']=='NOT_ASSESSED'
    assert b'NEVER_EXPOSE' not in raw and b'feature_values' not in raw


@pytest.mark.parametrize('kind',['manual','wrong_deployment','no_end','duplicate_task','wrong_task_flow','missing_stage','duplicate_stage','wrong_internal','duplicate_summary','bad_issue','bad_receipt_hash','wrong_receipt_task','missing_receipt','missing_delivery_task','task_failed','unknown_status'])
def test_reject_ambiguous_incomplete_or_conflicting_evidence(association,kind):
    a=association
    if kind=='manual':a['flow']['auto_scheduled']=False
    elif kind=='wrong_deployment':a['flow']['deployment_id']=FLOW
    elif kind=='no_end':a['flow']['end_time']=None
    elif kind=='duplicate_task':a['tasks'].append(copy.deepcopy(a['tasks'][0]))
    elif kind=='wrong_task_flow':a['tasks'][0]['flow_run_id']=DEP
    elif kind=='missing_stage':a['stages']=[]
    elif kind=='duplicate_stage':a['stages']*=2
    elif kind=='wrong_internal':a['stages'][0]['run_id']='b'*32
    elif kind=='duplicate_summary':a['records']*=2
    elif kind=='bad_issue':summary(a,next24h_forecast_issue_time=(ISSUE-dt.timedelta(hours=1)).isoformat())
    elif kind=='bad_receipt_hash':a['receipts'][0]['forecast.csv']+=b'changed'
    elif kind=='wrong_receipt_task':a['tasks'][0]['start_time']=(ISSUE+dt.timedelta(minutes=61)).isoformat();a['stages'][0]['start_timestamp_utc']=a['tasks'][0]['start_time']
    elif kind=='missing_receipt':a['receipts']=[]
    elif kind=='missing_delivery_task':a['tasks'].pop()
    elif kind=='task_failed':a['tasks'][0]['state']['type']='FAILED'
    else:summary(a,next24h_publication_status='SECRET_VALUE')
    with pytest.raises(contract.InvalidEvidence) as error:produce(a)
    assert 'SECRET_VALUE' not in str(error.value) and 'NEVER_EXPOSE' not in str(error.value)


def make_withheld(a, with_incident=True):
    a['receipts']=[];a['stages'][0]['status']='WITHHELD';when=(ISSUE+dt.timedelta(minutes=80)).isoformat()
    hours=dict(price=ISSUE.isoformat(),load=None,generation=None)
    summary(a,next24h_forecast_status='WITHHELD',next24h_forecast_generated=False,next24h_forecast_issue_time=None,next24h_publication_status='SKIPPED_WITHHELD',next24h_forecast_withheld_at_utc=when,next24h_latest_complete_market_hours=hours)
    if with_incident:
        a['incidents']=[dict(component='next24h forecast',event_type='forecast_withheld',timestamp_utc=when,details_json=json.dumps(dict(run_id=INTERNAL,timestamp=when,forecast_freshness_status='WITHHELD',latest_complete_hours=hours,reason='Required load history unavailable at fresh price issue hours.')))]


@pytest.mark.parametrize('with_incident',[True,False])
def test_withheld_is_successful_flow_without_receipt(association,with_incident):
    make_withheld(association,with_incident)
    b=contract.validate(*produce(association),NOW)
    assert b['execution']['outcome']=='COMPLETED' and b['inference']['receipt_id'] is None
    assert b['delivery']['outcome']=='SKIPPED_WITHHELD'
    assert b['inference']['withholding']==(dict(reason='INPUTS_UNAVAILABLE',gate='JOINT_PRICE_LOAD_HOUR') if with_incident else None)


@pytest.mark.parametrize('outcome',['FAILED','DISABLED','SKIPPED_EXPIRED','SKIPPED_DUPLICATE','REJECTED_OLDER_ISSUE'])
def test_generated_delivery_outcomes_are_independent(association,outcome):
    summary(association,next24h_publication_status=outcome)
    b=contract.validate(*produce(association),NOW)
    assert b['inference']['outcome']=='GENERATED' and b['delivery']['outcome']==outcome


@pytest.mark.parametrize('outcome',['UNCHANGED','FAILED','UNAVAILABLE','UNKNOWN'])
def test_other_inference_outcomes(association,outcome):
    if outcome=='UNCHANGED':summary(association,next24h_forecast_status=outcome)
    else:
        association['receipts']=[]
        summary(association,next24h_forecast_status=outcome,next24h_forecast_generated=None,next24h_forecast_issue_time=None,next24h_publication_status='FAILED' if outcome=='FAILED' else 'UNKNOWN')
    assert contract.validate(*produce(association),NOW)['inference']['outcome']==outcome


def test_latest_natural_does_not_fall_back_to_older_completed_run(association):
    flow=association['flow'];manual=copy.deepcopy(flow);manual['auto_scheduled']=False;manual['id']=DEP
    assert latest_natural([manual,flow],DEP,NOW)==flow
    newer=copy.deepcopy(flow);newer['expected_start_time']=(ISSUE+dt.timedelta(hours=1,minutes=45)).isoformat();newer['state']['type']='RUNNING';newer['end_time']=None
    with pytest.raises(contract.InvalidEvidence,match='NOT_TERMINAL'):
        latest_natural([flow,newer],DEP,NOW)
    with pytest.raises(contract.InvalidEvidence,match='AMBIGUOUS_RUN'):
        latest_natural([flow,copy.deepcopy(flow)],DEP,NOW)


def test_snapshot_selects_only_bounded_read_records(association,tmp_path):
    p=tmp_path/'synthetic.db';c=sqlite3.connect(p)
    c.executescript('CREATE TABLE pipeline_runs(id INTEGER PRIMARY KEY,run_time TEXT,status TEXT,message TEXT); CREATE TABLE pipeline_stage_timings(run_id TEXT,stage_name TEXT,start_timestamp_utc TEXT,end_timestamp_utc TEXT,status TEXT); CREATE TABLE operational_incidents(timestamp_utc TEXT,component TEXT,event_type TEXT,details_json TEXT);')
    r=association['records'][0];s=association['stages'][0]
    c.execute('INSERT INTO pipeline_runs VALUES (1,?,?,?)',tuple(r[k] for k in ['run_time','status','message']))
    c.execute('INSERT INTO pipeline_stage_timings VALUES (?,?,?,?,?)',tuple(s[k] for k in ['run_id','stage_name','start_timestamp_utc','end_timestamp_utc','status']))
    c.commit();c.close();before=p.read_bytes()
    ro=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True);ro.execute('PRAGMA query_only=ON');ro.execute('BEGIN');statements=[];ro.set_trace_callback(statements.append)
    try:
        args={k:association[k] for k in ['flow','tasks','receipts','expected_deployment','observed_at']}
        assert from_snapshot(ro,**args)==produce(association)
    finally:ro.close()
    assert all(s.startswith(('PRAGMA query_only','SELECT ')) for s in statements)
    assert p.read_bytes()==before


@pytest.fixture
def api_client(tmp_path,monkeypatch):
    from api import current_operations
    instant=dt.datetime(2026,11,5,6,49,tzinfo=dt.timezone.utc)
    monkeypatch.setattr(current_operations,'datetime',SimpleNamespace(now=lambda _:instant))
    root=root_at(tmp_path)
    b=op_fixture();raw,digest=encoded(b);store.publish(root,raw,digest,None,clock=lambda:instant)
    settings=replace(APISettings.from_root(tmp_path),operational_publication_root=root)
    app=create_app(settings)
    return TestClient(app),app,root,digest,instant


def test_public_endpoints_share_evidence_and_admin_guard(api_client):
    c,app,root,digest,now=api_client
    public=c.get('/operations/current');pipeline=c.get('/pipeline/current')
    assert public.status_code==pipeline.status_code==200 and public.json()==pipeline.json()
    assert public.json()['evidence_id']==digest and 'admin' not in public.json()
    assert c.get('/operations/current?admin=true').json()==public.json()
    assert c.get('/admin/operations/current').status_code==401
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(FLOW,'Analyst',None,None,frozenset(),None)
    assert c.get('/admin/operations/current').status_code==403
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(FLOW,'Admin',None,None,frozenset(),None)
    admin=c.get('/admin/operations/current')
    assert admin.status_code==200 and admin.json()['evidence_id']==digest
    assert {k:v for k,v in admin.json().items() if k!='admin'}==public.json()
    assert 'admin' in admin.json() and public.headers['cache-control']=='no-store'


@pytest.mark.parametrize('kind',['missing','stale','invalid','unconfigured'])
def test_no_current_endpoint_falls_back_to_historical_database(api_client,monkeypatch,kind):
    c,app,root,digest,now=api_client
    from api import current_operations
    if kind=='missing':(root/'current').unlink()
    elif kind=='stale':monkeypatch.setattr(current_operations,'datetime',SimpleNamespace(now=lambda _:now+dt.timedelta(hours=2)))
    elif kind=='invalid':(root/'releases'/digest/'evidence.json').write_text('{}')
    else:c=TestClient(create_app(APISettings.from_root(root.parent)))
    import api.database
    monkeypatch.setattr(api.database.sqlite3,'connect',lambda *a,**kw:pytest.fail('Current API must not read any execution DB'))
    c.app.dependency_overrides[get_current_user]=lambda:CurrentUser(FLOW,'Admin',None,None,frozenset(),None)
    for path in ['/operations/current','/pipeline/current','/admin/operations/current']:
        r=c.get(path);assert r.status_code==200
        assert r.json()['status']==dict(missing='MISSING',stale='STALE',invalid='INVALID',unconfigured='MISSING')[kind]
        assert r.json()['current_execution'] is None and 'admin' not in r.json()


def test_pointer_change_does_not_mix_response_versions(api_client,monkeypatch):
    c,app,root,old,now=api_client
    from api import current_operations
    read=current_operations.read_current
    b=op_fixture();b['observed_at']=now.isoformat();raw,new=encoded(b)
    calls=[]
    def during_read(*args,**kwargs):
        result=read(*args,**kwargs);calls.append(1)
        if len(calls)==1:store.publish(root,raw,new,old,clock=lambda:now)
        return result
    monkeypatch.setattr(current_operations,'read_current',during_read)
    first=c.get('/operations/current').json();second=c.get('/pipeline/current').json()
    assert first['evidence_id']==old and second['evidence_id']==new
    assert first['observed_at']=='2026-11-05T06:48:00Z' and second['observed_at']==now.isoformat()
    assert len(calls)==2


def test_producer_to_atomic_store_to_all_current_endpoints(association,tmp_path,monkeypatch):
    from api import current_operations
    raw,digest=produce(association)
    root=root_at(tmp_path)
    store.publish(root,raw,digest,None,clock=lambda:NOW)
    monkeypatch.setattr(current_operations,'datetime',SimpleNamespace(now=lambda _:NOW))
    app=create_app(replace(APISettings.from_root(tmp_path),operational_publication_root=root))
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(FLOW,'Admin',None,None,frozenset(),None)
    c=TestClient(app)
    pub=c.get('/operations/current').json();pipeline=c.get('/pipeline/current').json();admin=c.get('/admin/operations/current').json()
    assert pub==pipeline=={k:v for k,v in admin.items() if k!='admin'}
    assert pub['status']=='VALID' and pub['evidence_id']==digest
    assert pub['current_execution']['completed_at']==association['flow']['end_time']
    assert admin['admin']['execution_identity']['pipeline_run_id']==INTERNAL
    assert admin['admin']['delivery']['outcome']=='PUBLISHED'
    assert pub['forecast_eligibility']=='NOT_ASSESSED'


@pytest.mark.parametrize('kind',['unknown_reason','ambiguous_incident','wrong_time','wrong_hours'])
def test_incident_binding_and_redaction(association,kind):
    make_withheld(association)
    row=association['incidents'][0];detail=json.loads(row['details_json'])
    if kind=='unknown_reason':detail['reason']='TOKEN_PRIVATE_DETAIL'
    elif kind=='ambiguous_incident':association['incidents'].append(copy.deepcopy(row))
    elif kind=='wrong_time':detail['timestamp']=(ISSUE+dt.timedelta(minutes=79)).isoformat()
    else:detail['latest_complete_hours']={}
    row['details_json']=json.dumps(detail)
    if kind=='unknown_reason':
        raw,digest=produce(association)
        b=contract.validate(raw,digest,NOW)
        assert b['inference']['withholding']==dict(reason='UNKNOWN',gate='UNKNOWN') and b'TOKEN_PRIVATE_DETAIL' not in raw
    else:
        with pytest.raises(contract.InvalidEvidence):produce(association)


def test_failed_flow_can_have_successful_inference_and_delivery(association):
    association['flow']['state']['type']='FAILED';association['records'][0]['status']='FAILED';summary(association,status='FAILED')
    b=contract.validate(*produce(association),NOW)
    assert b['execution']['outcome']=='FAILED' and b['inference']['outcome']=='GENERATED' and b['delivery']['outcome']=='PUBLISHED'


def test_early_failure_never_invents_forecast_task_or_receipt(association):
    a=association;a['flow']['state']['type']='FAILED';a['records'][0]['status']='FAILED'
    summary(a,status='FAILED',next24h_forecast_status='UNKNOWN',next24h_forecast_generated=None,next24h_publication_status='UNKNOWN')
    a['tasks']=[];a['receipts']=[];a['stages'][0].update(stage_name='Total pipeline',start_timestamp_utc=a['flow']['start_time'],end_timestamp_utc=a['flow']['end_time'],status='FAILED')
    b=contract.validate(*produce(a),NOW)
    assert b['inference']['outcome']=='UNKNOWN' and b['inference']['task_run_id'] is None and b['delivery']['published_at'] is None


def test_expired_receipt_keeps_historical_inference_outcome(association):
    association['observed_at']=NOW+dt.timedelta(hours=4)
    raw,digest=produce(association)
    assert contract.validate(raw,digest,association['observed_at'])['delivery']['outcome']=='PUBLISHED'
    assert contract.view(raw,digest,now=association['observed_at'])['status']=='STALE'


def test_read_only_transaction_is_required(association):
    connection=sqlite3.connect(':memory:')
    try:
        with pytest.raises(contract.InvalidEvidence,match='READ_ONLY_SNAPSHOT_REQUIRED'):
            from_snapshot(connection,association['flow'],association['tasks'],association['receipts'],expected_deployment=DEP,observed_at=NOW)
    finally:connection.close()


def test_request_local_selector_resolves_once(api_client,monkeypatch):
    from api import current_operations
    c,app,root,digest,now=api_client
    request=SimpleNamespace(state=SimpleNamespace());calls=[]
    read=current_operations.read_current
    def counted(*a,**kw):calls.append(1);return read(*a,**kw)
    monkeypatch.setattr(current_operations,'read_current',counted)
    pub=current_operations.current_selection(request,root)
    admin=current_operations.current_selection(request,root,admin=True)
    assert calls==[1] and pub=={k:v for k,v in admin.items() if k!='admin'}


def test_explicit_not_run_is_preserved_without_inventing_it(association):
    a=association;a['flow']['state']['type']='FAILED';a['records'][0]['status']='FAILED';a['tasks']=[];a['receipts']=[]
    a['stages'][0].update(stage_name='Total pipeline',start_timestamp_utc=a['flow']['start_time'],end_timestamp_utc=a['flow']['end_time'],status='FAILED')
    summary(a,status='FAILED',next24h_forecast_status='NOT_RUN',next24h_forecast_generated=False,next24h_publication_status='NOT_RUN')
    assert contract.validate(*produce(a),NOW)['inference']['outcome']=='NOT_RUN'


def test_latest_selection_failure_is_sanitized_and_manual_only_rejected(association):
    with pytest.raises(contract.InvalidEvidence,match='NATURAL_RUN_UNVERIFIED'):
        latest_natural([{'deployment_id':DEP,'auto_scheduled':True}],DEP,NOW)
    association['flow']['auto_scheduled']=False
    with pytest.raises(contract.InvalidEvidence,match='NO_NATURAL_RUN'):
        latest_natural([association['flow']],DEP,NOW)


def test_adapter_never_reads_active_forecast_or_invokes_publisher(association,monkeypatch):
    monkeypatch.setattr(forecast,'read_active',lambda *a,**k:pytest.fail('Must not inspect live forecast eligibility'))
    monkeypatch.setattr(store,'publish',lambda *a,**k:pytest.fail('Producer association must not activate a publication'))
    assert contract.validate(*produce(association),NOW)['delivery']['outcome']=='PUBLISHED'


def test_future_persisted_summary_is_not_accepted_as_observed(association):
    association['observed_at']=timestamp=dt.datetime.fromisoformat(association['flow']['end_time'])
    association['records'][0]['run_time']=(timestamp+dt.timedelta(seconds=1)).isoformat()
    with pytest.raises(contract.InvalidEvidence,match='SUMMARY_TIME'):produce(association)


def test_snapshot_budget_aborts_and_clears_handler(association,monkeypatch):
    import shared.operational_evidence_producer as producer
    clock=iter([0,3]);monkeypatch.setattr(producer.time,'monotonic',lambda:next(clock))
    class SlowSnapshot:
        in_transaction=True
        def __init__(self):self.handler=None;self.cleared=False
        def set_progress_handler(self,handler,steps):
            self.handler=handler
            if handler is None:self.cleared=True
        def execute(self,sql,*params):
            if sql=='PRAGMA query_only':return SimpleNamespace(fetchone=lambda:(1,))
            assert self.handler()==1
            raise sqlite3.OperationalError('interrupted; private database detail')
    snapshot=SlowSnapshot()
    with pytest.raises(contract.InvalidEvidence,match='SNAPSHOT_UNVERIFIED') as error:
        from_snapshot(snapshot,association['flow'],association['tasks'],association['receipts'],expected_deployment=DEP,observed_at=NOW)
    assert snapshot.cleared and 'private' not in str(error.value)
