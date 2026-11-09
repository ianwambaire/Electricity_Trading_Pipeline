"""Offline V4 preservation policy, authentic fixture receipts, no remote access."""
import ast
import copy
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import pytest
from shared import forecast_publication as FC, forecast_availability as FA, operational_evidence as OP
from shared import operational_evidence_producer as producer
from test_current_operations import association, produce
from test_forecast_publication import ISSUE
ROOT=Path(__file__).parents[1];HERE=ROOT/'deploy/staging/live-forecast-reliability-acceptance-v4'
OLD=ROOT/'deploy/staging/live-forecast-reliability-acceptance-v3'
class Stop(ValueError):pass
def need(v,reason):
    if not v:raise Stop(reason)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def load(name):
    spec=importlib.util.spec_from_file_location('v4_'+name,HERE/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def protected_fixture():
    b={'production':'original','forecast':{'forecast-publications':[0,0,493],'releases':[0,0,493],'pointer':'releases/'+'a'*64,'bundle':'a'*64},'store':'old','helper':'fixed','policy':'fixed','environment':'fixed','nginx':'fixed','runtime':'closure','venv':'/venv'}
    a={k:copy.deepcopy(v)for k,v in b.items()if k not in {'runtime','venv'}}
    a.update(production='changed-exports',store='advanced');a['forecast'].update(pointer='releases/'+'b'*64,bundle='b'*64)
    m=load('acceptance');m.need=need;m.baseline_preservation=lambda:a
    calls=[];m.PRES=types.SimpleNamespace(historical_output_hashes=lambda _:calls.append('receipt')or{'verified':'hash'},replay_production=lambda *a:'MATCH_EXCEPT_PIPELINE_OUTPUTS',store_history=lambda *a:'BASELINE_RECONSTRUCTED_SUBSET')
    return m,b,a,calls

def test_legitimate_publication_advancement_keeps_protected_state_exact():
    m,b,a,calls=protected_fixture();assert m.preservation_checks({'baseline':b,'activated_at':'time'})==a and calls==['receipt']
@pytest.mark.parametrize('key',['helper','policy','environment','nginx'])
def test_genuine_fixed_component_drift_rejected_with_safe_identifier(key):
    m,b,a,_=protected_fixture();a[key]='SECRET /private/path'
    with pytest.raises(Stop,match='^PRESERVATION_DRIFT_'+key.upper()+'$'):m.preservation_checks({'baseline':b,'activated_at':'time'})
def test_protected_production_drift_not_masked_by_changed_exports():
    m,b,_,_=protected_fixture();m.PRES.replay_production=lambda *a:'UNRESOLVED_PRODUCTION_DIFFERENCE'
    with pytest.raises(Stop,match='PRESERVATION_DRIFT_PRODUCTION'):m.preservation_checks({'baseline':b,'activated_at':'time'})
@pytest.mark.parametrize('change',['permissions','unexpected-field'])
def test_forecast_namespace_permissions_and_schema_remain_exact(change):
    m,b,a,_=protected_fixture()
    if change=='permissions':a['forecast']['releases']=[1000,1000,511]
    else:a['forecast']['extra']='unsafe'
    with pytest.raises(Stop,match='PRESERVATION_DRIFT_FORECAST_METADATA'):m.preservation_checks({'baseline':b,'activated_at':'time'})
def test_deleted_or_modified_original_store_inventory_rejected():
    m,b,_,_=protected_fixture();m.PRES.store_history=lambda *a:'UNRESOLVED_STORE_DIFFERENCE'
    with pytest.raises(Stop,match='PRESERVATION_DRIFT_STORE_RETENTION'):m.preservation_checks({'baseline':b,'activated_at':'time'})
@pytest.mark.parametrize('key',['production','forecast','store','helper','policy','environment','nginx'])
def test_mid_read_publication_or_protected_state_change_fails_closed(key):
    m,_,a,_=protected_fixture();b=copy.deepcopy(a);b[key]='changed'
    with pytest.raises(Stop,match='^READBACK_CHANGED_'+key.upper()+'$'):m.stable_components(a,b)

@pytest.fixture
def active(association,monkeypatch):
    m=load('acceptance');m.need=need;m.sha=sha;m.Path=Path
    files=association['receipts'][0];bundle,digest=producer.receipt_bundle(files,association['observed_at']);raw=json.dumps(bundle,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    op_raw,_=produce(association);evidence=OP.decode(op_raw)
    clock=ISSUE+dt.timedelta(hours=4);fp={'pointer':'releases/'+digest,'bundle':digest};baseline=copy.deepcopy(fp)
    m.available_module=lambda:types.SimpleNamespace(read_active=lambda root,now:FA.validate(raw,digest,now),SERVING_HORIZON=FA.SERVING_HORIZON)
    m.P=types.SimpleNamespace(forecast_fingerprint=lambda:dict(fp),STORE=Path('/store'))
    m.B={'read':lambda *a:raw};m.H=types.SimpleNamespace(OP=OP,artifact=lambda _:(ROOT/'deploy/staging/operational-capture-correction-v1/operational_evidence_producer.py').read_bytes())
    capture=types.ModuleType('shared.operational_capture');capture.Source=lambda:types.SimpleNamespace(root=Path('/production'),file=lambda folder,name:files[name])
    monkeypatch.setitem(sys.modules,'shared.operational_capture',capture)
    return m,evidence,bundle,digest,clock,fp,baseline,capture,files

def test_valid_real_receipt_after_three_hours_has_only_future_actionable_targets(active):
    m,e,b,d,now,fp,base,_,_=active;r=m.active_association(e,now,base)
    assert r['backend_status']=='PASS' and r['receipt_id']==b['execution']['run_id'] and r['bundle_sha256']==d
    assert r['remaining_predictions']==20 and r['elapsed_predictions']==4 and r['refresh_delayed']is True
    assert FC.time(r['next_target_time'])==ISSUE+dt.timedelta(hours=5) and FC.time(r['expires_at'])==ISSUE+dt.timedelta(hours=24)
@pytest.mark.parametrize('change',['receipt','issue','bundle'])
def test_published_operational_receipt_and_active_bundle_must_match(active,change):
    m,e,b,d,now,fp,base,_,_=active;e=copy.deepcopy(e)
    if change=='receipt':e['inference']['receipt_id']='99999999-9999-4999-8999-999999999999'
    elif change=='issue':e['inference']['issue_time']=(ISSUE+dt.timedelta(hours=1)).isoformat()
    else:e['delivery']['bundle_sha256']='b'*64
    with pytest.raises(Stop):m.active_association(e,now,base)

def test_corrupt_receipt_is_never_accepted_even_when_pointer_hash_matches(active):
    m,e,b,d,now,fp,base,_,files=active;files['forecast.csv']+=b'corrupted'
    with pytest.raises(OP.InvalidEvidence,match='RECEIPT_INTEGRITY'):m.active_association(e,now,base)
def test_changed_pointer_during_receipt_read_rejected(active):
    m,e,b,d,now,fp,base,capture,files=active
    def read(folder,name):
        if name=='integrity.json':fp['pointer']='releases/'+'a'*64
        return files[name]
    capture.Source=lambda:types.SimpleNamespace(root=Path('/production'),file=read)
    with pytest.raises(Stop,match='FORECAST_POINTER_CHANGED'):m.active_association(e,now,base)
@pytest.mark.parametrize('kind',['expired','missing','invalid'])
def test_unavailable_active_forecast_never_substitutes_history(active,kind):
    m,e,_,_,now,_,base,_,_=active;calls=[]
    exc={'expired':FC.ExpiredPublication,'missing':FC.MissingPublication,'invalid':FC.Withheld}[kind]
    m.available_module=lambda:types.SimpleNamespace(read_active=lambda *a:(_ for _ in ()).throw(exc('safe')))
    m.H.entries=lambda *a:calls.append('history')
    if kind=='invalid':
        with pytest.raises(Stop,match='ACTIVE_FORECAST_INVALID'):m.active_association(e,now,base)
    else:assert m.active_association(e,now,base)=={'backend_status':'PARTIAL','active_publication':'UNAVAILABLE'}
    assert not calls

def test_newer_withheld_run_can_retain_only_independently_verified_current_publication(active):
    m,e,b,d,now,fp,base,capture,files=active;old=copy.deepcopy(e);latest=copy.deepcopy(e)
    latest['delivery'].update(outcome='SKIPPED_WITHHELD',bundle_sha256=None,receipt_id=None)
    latest['inference'].update(outcome='WITHHELD',receipt_id=None,issue_time=None)
    latest['execution'].update(scheduled_at=(ISSUE+dt.timedelta(hours=3,minutes=45)).isoformat(),flow_run_id='99999999-9999-4999-8999-999999999999')
    old_raw=OP.canonical(old);old_digest=sha(old_raw)
    m.H.entries=lambda *a:[Path('/store/releases')/old_digest]
    m.P.snap=lambda *a:({},old_raw)
    capture.query=lambda fid:{'id':fid,'state':{'id':'state'}};capture.capture_terminal=lambda *a:(old_raw,old_digest)
    r=m.active_association(latest,now,base)
    assert r['backend_status']=='PARTIAL' and r['active_publication']=='VERIFIED' and r['active_flow_run_id']==old['execution']['flow_run_id']
    capture.capture_terminal=lambda *a:(OP.canonical(dict(old,provenance={'source':'wrong'})),old_digest)
    with pytest.raises(Stop,match='ACTIVE_NATURAL_ASSOCIATION'):m.active_association(latest,now,base)

def test_runtime_drift_rejected_before_dynamic_preservation_checks():
    m=load('acceptance');m.need=need;m.Path=Path;m.API='api';m.STATIC='static';m.sha=sha;m.old_trees=lambda:None;m.tree_state=lambda *a,**k:None;m.G={'runtime':lambda _:None}
    link=lambda t:types.SimpleNamespace(resolve=lambda **_:t)
    m.P=types.SimpleNamespace(idle=lambda _:None,candidate_environment=lambda _:None,BACKEND_LINK=link('api'),STATIC_LINK=link('static'),runtime_closure=lambda _:'modified')
    m.B={'request':lambda *a,**k:(200,b'index')};m.C={'files':{'static/index.html':{'sha256':sha(b'index')}}}
    with pytest.raises(Stop,match='PRESERVATION_DRIFT_RUNTIME'):m.deployment_checks({'baseline':{'venv':'/venv','runtime':'expected'}})

def test_immutable_api_validation_and_natural_discrimination_are_unchanged():
    funcs=lambda p:{n.name:ast.dump(n,include_attributes=False)for n in ast.parse(p.read_bytes()).body if isinstance(n,ast.FunctionDef)}
    a=funcs(OLD/'acceptance.py');b=funcs(HERE/'acceptance.py')
    assert all(a[n]==b[n]for n in ['available_module','forecast_checks','public_operations','started_natural'])

def test_package_python39_readonly_and_deterministic():
    b=load('build');payload,_,_=b.assemble();assert payload==b.assemble()[0];ast.parse(payload,feature_version=(3,9))
    for f in ['run.py','build.py','acceptance.py']:ast.parse((HERE/f).read_bytes(),feature_version=(3,9))
    functions=set()
    for n in ast.walk(ast.parse(payload)):
        if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='compile'and isinstance(n.args[0],ast.Constant)and isinstance(n.args[0].value,(str,bytes)):
            functions.update(t.name for t in ast.walk(ast.parse(n.args[0].value))if isinstance(t,ast.FunctionDef))
    assert not {'apply','rollback','publish','deliver_terminal','write','mkdir','restart','pointer'}&functions
    if (HERE/'MANIFEST.json').exists():
        assert load('run').verify(sha((HERE/'MANIFEST.json').read_bytes()))[0]==payload


def test_full_mock_acceptance_path_keeps_terminal_capture_and_current_identity(active,association):
    m,e,b,d,_,fp,base,capture,files=active
    raw=OP.canonical(e);evidence_sha=sha(raw);clock=ISSUE+dt.timedelta(hours=2)
    class Clock:
        @staticmethod
        def now(tz):return clock
    m.dt=types.SimpleNamespace(datetime=Clock,timezone=dt.timezone)
    snapshot={k:'fixed'for k in ['production','forecast','store','helper','policy','environment','nginx']}
    m.load_record=lambda:{'phase':'APPLIED','activated_at':(ISSUE+dt.timedelta(minutes=30)).isoformat(),'baseline':{'forecast':base}}
    m.verified_backups=lambda _:None;m.deployment_checks=lambda _:({'forecast_http':200,'forecast_status':'VALID','prediction_count':24},snapshot)
    m.baseline_preservation=lambda:dict(snapshot);m.P.idle=lambda _:None
    f=dict(association['flow'],state_type='COMPLETED');f['state']=dict(f['state'],id='state')
    def api(path,body):
        assert path=='/flow_runs/filter' and body['flow_runs']['start_time']['is_null_']is False and body['limit']==20
        return [f]
    m.B['api']=api;m.H.OLD_PLAN=types.SimpleNamespace(DEPLOYMENT=f['deployment_id']);m.H.artifact=lambda _:(ROOT/'deploy/staging/operational-capture-correction-v1/operational_evidence_producer.py').read_bytes()
    capture.capture_terminal=lambda fid,sid:(raw,evidence_sha)
    m.P.snap=lambda path,*a:({},(evidence_sha+'\n').encode()if path.name=='current'else raw)
    m.public_operations=lambda:OP.view(raw,evidence_sha,now=clock)
    report=m.accept_report();assert report['backend_status']=='PASS' and report['status']=='PARTIAL'
    assert report['run_id']==f['id'] and report['receipt_id']==b['execution']['run_id']
    assert report['pipeline_run_id']==e['execution']['pipeline_run_id'] and report['evidence_sha256']==evidence_sha
    load('run').validate_report(report)
    # Current record must not be replaced by a different execution despite matching APIs.
    other=copy.deepcopy(e);other['execution']['pipeline_run_id']='f'*32;other['provenance']['pipeline_run_id']='f'*32;bad=OP.canonical(other);bad_sha=sha(bad)
    m.P.snap=lambda path,*a:({},(bad_sha+'\n').encode()if path.name=='current'else bad)
    with pytest.raises(Stop,match='NATURAL_RUN_ASSOCIATION'):m.accept_report()


@pytest.mark.parametrize('value',['2026-01-05 08:00:00+00:00','2026-01-05T08:00:00Z'])
def test_actual_persisted_issue_spelling_reuses_verified_utc_parser(active,value):
    m,e,b,d,*_=active;b=copy.deepcopy(b);b['forecasts'][0]['issue_time']=value
    m.associated_publication(e,b,d)
@pytest.mark.parametrize('value',['2026-01-05 08:00:00','2026-01-05 11:00:00+03:00','2026-01-05  08:00:00Z'])
def test_persisted_issue_still_rejects_missing_timezone_and_non_utc(active,value):
    m,e,b,d,*_=active;b=copy.deepcopy(b);b['forecasts'][0]['issue_time']=value
    with pytest.raises(OP.InvalidEvidence,match='TIMESTAMP'):m.associated_publication(e,b,d)
