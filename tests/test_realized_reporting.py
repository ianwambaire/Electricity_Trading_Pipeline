"""Offline realized reporting: synthetic receipts/prices only, no model execution."""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import pytest
from fastapi import HTTPException
from models.realized_reporting import build
from models.next24h_monitoring import match_realized_forecasts
from shared import realized_report as contract, realized_report_store as store
from api.realized_reporting import evaluation
from test_current_operations import receipt_files
from test_forecast_publication import ISSUE, fixture

NOW=ISSUE+dt.timedelta(hours=27)

@pytest.fixture
def inputs(tmp_path):
    b=fixture();root=tmp_path/'receipts';root.mkdir();folder=root/b['execution']['run_id'];folder.mkdir()
    for name,raw in receipt_files().items():(folder/name).write_bytes(raw)
    rows=[dict(forecast_issue_time=r['issue_time'],target_timestamp=r['target_time'],horizon_hours=r['horizon_hours'],predicted_price_eur_mwh=r['predicted_price_eur_mwh'],model_release=r['model_release'],issued_at_utc=b['execution']['completed_at'])for r in b['forecasts']]
    history=tmp_path/'history.csv';pd.DataFrame(rows).to_csv(history,index=False)
    prices=tmp_path/'prices.csv';pd.DataFrame([dict(timestamp=(dt.datetime.fromisoformat(r['target_time'])+dt.timedelta(minutes=m)).isoformat(),price_eur_mwh=r['predicted_price_eur_mwh']-2)for r in b['forecasts']for m in (0,15,30,45)]).to_csv(prices,index=False)
    return history,prices,root

@pytest.fixture
def namespace(tmp_path):
    root=tmp_path/'store';root.mkdir(mode=0o750);(root/'releases').mkdir(mode=0o750);(root/'contract').write_bytes(store.MARKER);(root/'contract').chmod(0o640)
    return root

def test_receipt_verified_completed_hour_metrics(inputs):
    b=build(*inputs,now=NOW)
    assert b['coverage']==dict(history_rows=24,verified_rows=24,unverified_rows=0,eligible_rows=23,realized_pairs=23)
    assert all(r['absolute_error']==2 and r['signed_error']==2 and r['squared_error']==4 for r in b['rows'])
    assert len(b['sources']['receipts_sha256'])==64

@pytest.mark.parametrize('kind',['missing_history','missing_prices','missing_receipts','unverified','corrupt','duplicate','incomplete_hour'])
def test_sources_fail_closed(inputs,kind):
    history,prices,root=inputs
    if kind=='missing_history':history.unlink();assert build(*inputs,now=NOW)['reason']=='MISSING_HISTORY';return
    if kind=='missing_prices':prices.unlink();assert build(*inputs,now=NOW)['reason']=='MISSING_OBSERVATIONS';return
    if kind=='missing_receipts':
        import shutil
        shutil.rmtree(root);assert build(*inputs,now=NOW)['reason']=='MISSING_RECEIPTS';return
    if kind=='unverified':
        for p in root.iterdir():
            for f in p.iterdir():f.unlink()
            p.rmdir()
        b=build(*inputs,now=NOW);assert not b['rows'] and b['coverage']['unverified_rows']==24;return
    if kind=='corrupt':next(root.glob('*/forecast.csv')).write_bytes(b'corrupt')
    if kind=='duplicate':
        h=pd.read_csv(history);pd.concat([h,h.iloc[:1]]).to_csv(history,index=False)
    if kind=='incomplete_hour':
        p=pd.read_csv(prices);p.iloc[:-1].to_csv(prices,index=False);assert len(build(*inputs,now=NOW)['rows'])==22;return
    with pytest.raises(ValueError):build(*inputs,now=NOW)

@pytest.mark.parametrize('kind',['hash','timestamp','math','future','horizon','model','late','duplicate','nan'])
def test_document_rejects_corruption(inputs,kind):
    b=build(*inputs,now=NOW);r=b['rows'][0]
    if kind=='hash':b['sources']['prices_sha256']='x'
    elif kind=='timestamp':r['issued_at_utc']='2026-01-05 09:21:00'
    elif kind=='math':r['absolute_error']=99
    elif kind=='future':b['generated_at']=(NOW+dt.timedelta(seconds=1)).isoformat()
    elif kind=='horizon':r['horizon_hours']=0
    elif kind=='model':r['model_release']='historical'
    elif kind=='late':r['issued_at_utc']=r['target_timestamp']
    elif kind=='duplicate':b['rows'][1]=copy.deepcopy(r)
    elif kind=='nan':r['signed_error']=float('nan')
    with pytest.raises((ValueError,contract.InvalidReport)):contract.validate(contract.encode(b),NOW)


def test_atomic_store_api_and_freshness(inputs,namespace):
    b=build(*inputs,now=NOW);digest=store.publish(namespace,b,now=NOW)
    result=evaluation(namespace,NOW)
    assert result.report_sha256==digest and result.report_status=='VALID'
    assert result.data_status=='AVAILABLE'
    assert result.releases[0].overall.mae==2 and result.releases[0].overall.rmse==2 and result.releases[0].overall.bias==2
    assert result.releases[0].horizons[0].status=='Insufficient data'
    assert evaluation(namespace,NOW+contract.MAX_AGE).report_status=='STALE'
    for reason,code in [('MISSING_HISTORY','REALIZED_INPUTS_MISSING'),('INVALID_INPUT','REALIZED_REPORT_FAILED')]:
        later=NOW+dt.timedelta(hours=2 if reason=='MISSING_HISTORY'else 3)
        store.publish(namespace,contract.failure(reason,later),now=later)
        with pytest.raises(HTTPException)as e:evaluation(namespace,later)
        assert e.value.status_code==503 and e.value.detail['code']==code


def test_empty_valid_is_insufficient(inputs,namespace):
    b=build(*inputs,now=NOW);b['rows']=[];b['coverage']['realized_pairs']=0
    store.publish(namespace,b,now=NOW);r=evaluation(namespace,NOW)
    assert r.report_status=='VALID'and r.data_status=='INSUFFICIENT_DATA'and not r.releases


def test_missing_invalid_no_fallback(namespace,inputs):
    with pytest.raises(HTTPException)as e:evaluation(namespace,NOW)
    assert e.value.status_code==404
    digest=store.publish(namespace,build(*inputs,now=NOW),now=NOW)
    (namespace/'releases'/digest/'report.json').write_text('{}')
    with pytest.raises(HTTPException)as e:evaluation(namespace,NOW)
    assert e.value.detail['code']=='REALIZED_REPORT_INVALID'


def test_failed_activation_preserves_previous(namespace,inputs):
    b=build(*inputs,now=NOW);first=store.publish(namespace,b,now=NOW)
    b['generated_at']=(NOW+dt.timedelta(minutes=1)).isoformat()
    with patch.object(store.os,'replace',side_effect=OSError('synthetic failure')):
        with pytest.raises(OSError):store.publish(namespace,b,now=NOW+dt.timedelta(minutes=1))
    assert store.read_active(namespace,NOW+dt.timedelta(minutes=1))[1]==first
    assert not list(namespace.glob('.current-*'))

@pytest.mark.parametrize('kind',['symlink','permissions','older','marker'])
def test_namespace_guards(namespace,inputs,kind):
    b=build(*inputs,now=NOW);digest=store.publish(namespace,b,now=NOW)
    if kind=='symlink':
        p=namespace/'releases'/digest/'report.json';p.rename(p.with_name('original'));p.symlink_to('original')
    elif kind=='permissions':(namespace/'releases'/digest/'report.json').chmod(0o666)
    elif kind=='marker':(namespace/'contract').write_bytes(b'wrong')
    elif kind=='older':
        with pytest.raises(ValueError):store.publish(namespace,contract.failure('INVALID_INPUT',NOW-dt.timedelta(seconds=1)),now=NOW)
        return
    with pytest.raises((OSError,ValueError)):store.read_active(namespace,NOW)


def test_complete_targets_only(inputs):
    h,p,_=inputs;history=pd.read_csv(h);observed=pd.DataFrame(dict(target_timestamp=history.target_timestamp,price_eur_mwh=0))
    now=pd.Timestamp(ISSUE+dt.timedelta(hours=3,minutes=30))
    result=match_realized_forecasts(history,observed,now=now)
    assert list(result.horizon_hours)==[2]
    for value in [float('inf'),float('nan')]:
        bad=history.copy();bad.loc[0,'predicted_price_eur_mwh']=value
        with pytest.raises(ValueError):match_realized_forecasts(bad,observed,now=now)


def test_time_windows_thresholds_negative_and_zero_prices():
    from shared.forecast_evaluation import summarize_realized_performance
    issue=pd.Timestamp(ISSUE);now=pd.Timestamp(NOW)
    rows=[]
    for i in range(20):
        target=now-pd.Timedelta(hours=2 if i<10 else 30)
        error=(-2 if i%2 else 4)
        rows.append(dict(forecast_issue_time=target-pd.Timedelta(hours=2),target_timestamp=target,issued_at_utc=target-pd.Timedelta(hours=1),horizon_hours=2,predicted_price_eur_mwh=error-5,actual_price_eur_mwh=-5,signed_error=error,absolute_error=abs(error),squared_error=error**2))
    result=summarize_realized_performance(pd.DataFrame(rows),now=now)
    assert result['overall']==dict(status='Available',pair_count=20,mae=3,rmse=pytest.approx(10**.5),bias=1)
    assert result['windows']['24h']['status']=='Insufficient data'
    assert result['windows']['24h']['mae']is None
    assert result['windows']['7d']['pair_count']==20
    assert result['horizons'].iloc[1]['status']=='Available'
    assert summarize_realized_performance(pd.DataFrame(rows[:19]),now=now)['overall']['mae']is None


def test_concurrent_readers_consistent_or_fail_closed(inputs,namespace):
    from concurrent.futures import ThreadPoolExecutor
    b=build(*inputs,now=NOW);first=store.publish(namespace,b,now=NOW)
    def reader():
        try:
            doc,digest=store.read_active(namespace,NOW+dt.timedelta(minutes=5))
            assert hashlib.sha256(contract.encode(doc)).hexdigest()==digest
        except (OSError,contract.InvalidReport):pass # pointer changed: explicit retry by consumer, never mixed bytes
    with ThreadPoolExecutor(max_workers=4)as pool:
        tasks=[pool.submit(reader)for _ in range(20)]
        b['generated_at']=(NOW+dt.timedelta(minutes=1)).isoformat()
        store.publish(namespace,b,now=NOW+dt.timedelta(minutes=1))
        for task in tasks:task.result()
    assert (namespace/'releases'/first/'report.json').exists()


def test_api_shared_route_no_legacy_fallback(inputs,namespace,tmp_path):
    from api.app import APISettings,create_app
    from dataclasses import replace
    from fastapi.testclient import TestClient
    store.publish(namespace,build(*inputs,now=NOW),now=NOW)
    settings=replace(APISettings.from_root(tmp_path),realized_publication_root=namespace)
    client=TestClient(create_app(settings))
    response=client.get('/forecast/realized-evaluation')
    assert response.status_code==200 and response.json()['report_status']=='STALE'
    body=response.text
    assert 'feature_values'not in body and str(namespace)not in body
    (namespace/'current').unlink()
    assert client.get('/forecast/realized-evaluation').status_code==404


def test_opt_in_missing_inputs_publishes_explicit_state(tmp_path,monkeypatch):
    import models.next24h_monitoring as monitor
    calls=[]
    monkeypatch.setattr(store,'publish',lambda root,document,**kw:calls.append(document))
    monitor.update_next24h_monitoring(tmp_path/'missing',tmp_path/'prices')
    assert not calls
    monkeypatch.setenv('POWERFLOW_REALIZED_REPORT_ENABLED','true')
    assert monitor.update_next24h_monitoring(tmp_path/'missing',tmp_path/'prices')==(0,0)
    assert calls[0]['state']=='MISSING_INPUTS'


def test_actual_pandas_receipt_writer_format(inputs):
    import io
    from models.inference_evidence import receipt
    history,prices,root=inputs;folder=next(root.iterdir());files={p.name:p.read_bytes()for p in folder.iterdir()}
    proof=json.loads(files['evidence.json']);provenance=json.loads(files['provenance.json']);provenance.pop('inference_evidence')
    frame=pd.read_csv(io.BytesIO(files['forecast.csv']))
    for key in ['forecast_issue_time','target_timestamp']:frame[key]=pd.to_datetime(frame[key],utc=True)
    matrix=pd.DataFrame([proof['inference']['feature_values']],columns=proof['inference']['feature_names'])
    actual=receipt(frame,provenance,files['model.json'],matrix,proof['inputs'],proof['inference']['source_sha256'],proof['execution'])
    assert b'2026-01-05 08:00:00+00:00'in actual['forecast.csv']
    for name,raw in actual.items():(folder/name).write_bytes(raw)
    assert build(*inputs,now=NOW)['coverage']['realized_pairs']==23


def test_source_symlink_and_input_bounds(inputs,tmp_path):
    from models.realized_reporting import read
    history,_,_=inputs;link=tmp_path/'link';link.symlink_to(history)
    with pytest.raises(OSError):read(link,100000)
    with pytest.raises(ValueError):read(history,1)
    with pytest.raises(ValueError):read(history.parent/'..'/history.parent.name/history.name,100000)


def test_no_publisher_activation_side_effects(inputs,tmp_path):
    paths=[p for p in tmp_path.rglob('*')if p.is_file()]
    before={p:p.read_bytes()for p in paths}
    build(*inputs,now=NOW)
    assert before=={p:p.read_bytes()for p in paths}
    assert not (tmp_path/'current').exists()


def test_python39_syntax_compatibility():
    import ast
    for name in ['src/shared/realized_report.py','src/shared/realized_report_store.py','src/models/realized_reporting.py','src/api/realized_reporting.py']:
        ast.parse(Path(name).read_text(),feature_version=(3,9))
