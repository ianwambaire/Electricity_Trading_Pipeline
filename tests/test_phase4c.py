"""Feature parity acceptance: source equality, safe projections and genuine JWT guards."""
import csv
import hashlib
import json
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from api.app import APISettings, create_app
from api.market_data import VALUE_FIELDS, WEATHER_FIELDS
from api.feature_parity import forecast_context
from api.market_data import MarketStore
from test_api_security import client, token, auth, signing  # ephemeral key fixture, mocked JWKS

ROOT = Path(__file__).resolve().parents[1]


def market(root, count=168):
    path=APISettings.from_root(root).market_silver
    path.parent.mkdir(parents=True, exist_ok=True)
    first=datetime(2026,9,1,tzinfo=timezone.utc)
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['timestamp',*VALUE_FIELDS,*WEATHER_FIELDS]);writer.writeheader()
        for i in range(count):
            row=dict.fromkeys([*VALUE_FIELDS,*WEATHER_FIELDS],1)
            row.update(timestamp=(first+timedelta(hours=i)).isoformat(),price_eur_mwh=i-50,temperature_2m=i/10,wind_speed_10m=4+i/10)
            writer.writerow(row)
    return path,first


def test_exploration_and_exact_context_equal_original_helper(tmp_path):
    path,first=market(tmp_path)
    before=path.read_bytes()
    from dashboard_data import build_model_input_context
    frame=pd.read_csv(path)
    expected=build_model_input_context(frame, first+timedelta(hours=167))
    with TestClient(create_app(APISettings.from_root(tmp_path))) as c:
        r=c.get('/market/exploration?max_points=12');assert r.status_code==200
        report=r.json();assert report['matched_rows']==168 and len(report['weather'])<=12
        assert len(report['generation'])==8 and all(r['average_mw']==1 for r in report['generation'])
        assert report['weather'][0]['temperature_2m']==0 and report['weather'][-1]['temperature_2m']==16.7
        result=c.get('/forecast/context',params={'issue_time':(first+timedelta(hours=167)).isoformat()})
        assert result.status_code==200
        for key,value in expected.items():
            if key=='issue_time':continue
            assert result.json()[key]==value
        equivalent=c.get('/forecast/context',params={'issue_time':(first+timedelta(hours=167)).astimezone(timezone(timedelta(hours=3))).isoformat()})
        assert equivalent.json()==result.json()
        assert result.json()['price_rolling_std_24h']==pytest.approx(statistics.stdev(range(94,118)))
        missing=c.get('/forecast/context?issue_time=2027-01-01T00:00:00Z').json()
        assert missing['available'] is False and missing['price_eur_mwh'] is None
        for query in ['issue_time=2026-09-01','issue_time=2026-09-01T01:01:00Z','issue_time=bad','issue_time=2026-09-01T01:00:00%2B00:30']:
            assert c.get('/forecast/context?'+query).status_code==422
        for query in ['max_points=3','max_points=2001','start=2026-09-01','end=bad']:
            assert c.get('/market/exploration?'+query).status_code==422
    assert before==path.read_bytes()


def test_missing_hour_never_fills_rolling_context(tmp_path):
    path,first=market(tmp_path)
    rows=path.read_text().splitlines();path.write_text('\n'.join([r for i,r in enumerate(rows) if i!=160])+'\n')
    store=MarketStore(path)
    result=forecast_context(store,first+timedelta(hours=167))
    assert result.available and result.price_rolling_mean_24h is None and result.price_average_7d is None
    store.close()


def test_missing_optional_weather_does_not_invalidate_market(tmp_path):
    path,_=market(tmp_path,1)
    frame=pd.read_csv(path).drop(columns=list(WEATHER_FIELDS));frame.to_csv(path,index=False)
    with TestClient(create_app(APISettings.from_root(tmp_path))) as c:
        assert c.get('/market/coverage').status_code==200
        assert c.get('/market/exploration').json()['weather'][0]['temperature_2m'] is None


def test_admin_operations_missing_corrupt_and_safe_recorded_data(tmp_path,signing):
    c=client(tmp_path,signing);headers=auth(token(signing,**{'cognito:groups':['powerflow-admins']}))
    path='/admin/operations'
    assert c.get(path).status_code==401
    assert c.get(path,headers=auth(token(signing))).status_code==403
    result=c.get(path,headers=headers);assert result.status_code==200
    assert result.json()['incident_evidence']=='missing' and result.json()['timing_summary'] is None
    db=APISettings.from_root(tmp_path).operational_database;db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as con:
        con.executescript((ROOT/'database/schema.sql').read_text())
        con.execute('INSERT INTO pipeline_runs(run_time,status,records_processed,message) VALUES(?,?,?,?)',('2026-09-01T00:00:00Z','SUCCESS',100,json.dumps({'next24h_forecast_status':'WITHHELD','new_rows_ingested':0,'message':'/private/path secret','token':'sensitive'})))
        con.execute('INSERT INTO operational_incidents(timestamp_utc,severity,component,event_type,status,message,details_json) VALUES(?,?,?,?,?,?,?)',('2026-09-01T00:00:00Z','WARNING','private-component','private-event','ACTIVE','credential=secret','/private/path'))
        for stage,seconds in [('Total pipeline',12.5),('Next24h forecast generation',2.5),('private-stage',3)]:
            con.execute('INSERT INTO pipeline_stage_timings(run_id,stage_name,start_timestamp_utc,end_timestamp_utc,duration_seconds,status) VALUES(?,?,?,?,?,?)',('private-run',stage,'2026-09-01T00:00:00Z','2026-09-01T00:00:12.500Z',seconds,'SUCCESS'))
    before=db.read_bytes()
    result=c.get(path,headers=headers);assert result.status_code==200
    s=result.json();assert s['runs'][0]['status']=='SUCCESS' and s['runs'][0]['forecast_status']=='WITHHELD'
    assert s['runs'][0]['new_rows_ingested']==0
    assert s['timing_summary']['latest_total_seconds']==12.5 and s['timing_summary']['latest_forecast_seconds']==2.5
    assert all(x not in result.text for x in ['private-','credential=secret','sensitive','/private/path'])
    assert before==db.read_bytes()
    assert c.post(path,headers=headers).status_code==405
    db.write_bytes(b'corrupt operational database')
    assert c.get(path,headers=headers).status_code==503


def write_realized(root,count=20):
    from models.next24h_monitoring import REALIZED_COLUMNS
    path=root/'data/reports/next24h_realized_errors.csv';path.parent.mkdir(parents=True)
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=REALIZED_COLUMNS);w.writeheader()
        for i in range(count):
            issue=datetime(2026,9,1,tzinfo=timezone.utc)+timedelta(hours=i)
            w.writerow(dict(forecast_issue_time=issue.isoformat(),target_timestamp=(issue+timedelta(hours=1)).isoformat(),issued_at_utc=issue.isoformat(),horizon_hours=1,model_release='fixture-release',predicted_price_eur_mwh=-3,actual_price_eur_mwh=-5,absolute_error=2,squared_error=4,signed_error=2))
    return path


@pytest.mark.parametrize('pairs',[0,4,5,19,20])
def test_realized_thresholds_and_exact_original_summary(tmp_path,pairs):
    path=write_realized(tmp_path,pairs)
    from models.next24h_monitoring import summarize_realized_performance
    expected=summarize_realized_performance(pd.read_csv(path))
    with TestClient(create_app(APISettings.from_root(tmp_path))) as c:
        result=c.get('/forecast/realized-evaluation');assert result.status_code==200
        s=result.json();assert s['report_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
        if pairs:
            release=s['releases'][0]
            assert release['overall']==expected['overall']
            assert release['overall']['mae']==(2 if pairs>=20 else None)
            assert release['horizons'][0]['mae']==(2 if pairs>=5 else None)
            assert release['windows']['24h']['mae'] is None  # historical, never live
        else:assert s['releases']==[]


def test_realized_missing_invalid_duplicate_and_post_target_issuance(tmp_path):
    with TestClient(create_app(APISettings.from_root(tmp_path))) as c:
        assert c.get('/forecast/realized-evaluation').status_code==404
        path=write_realized(tmp_path)
        frame=pd.read_csv(path)
        frame['issued_at_utc']=frame['target_timestamp'];frame.to_csv(path,index=False)
        r=c.get('/forecast/realized-evaluation');assert r.status_code==200
        assert r.json()['releases'][0]['overall']['pair_count']==0
        frame=pd.concat([frame,frame.iloc[:1]]);frame.to_csv(path,index=False)
        assert c.get('/forecast/realized-evaluation').status_code==503
        path.write_text('private malformed report')
        r=c.get('/forecast/realized-evaluation');assert r.status_code==503 and 'private' not in r.text


def test_real_local_market_weather_means_and_streamlit_still_reads_files():
    root=ROOT;source=APISettings.from_root(root).market_silver
    if not source.is_file():pytest.skip('Local Silver not supplied')
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    frame=pd.read_csv(source)
    with TestClient(create_app(APISettings.from_root(root))) as c:
        s=c.get('/market/exploration').json()
        for r in s['generation']:
            assert r['average_mw']==pytest.approx(frame[r['source']].mean())
        indexed=frame.set_index(pd.to_datetime(frame.timestamp,utc=True))
        for row in s['weather']:
            original=indexed.loc[pd.Timestamp(row['timestamp'])]
            assert row['temperature_2m']==pytest.approx(original.temperature_2m)
            assert row['wind_speed_10m']==pytest.approx(original.wind_speed_10m)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    # Original Streamlit imports/readers remain independent of the migrated HTTP aliases.
    from dashboard_data import load_dashboard_csv
    with patch('httpx.get',side_effect=AssertionError('No API dependency')):
        assert len(load_dashboard_csv(source))==len(frame)

@pytest.mark.parametrize('changes',[{'token_use':'id'},{'client_id':'wrongclient'},{'iss':'https://wrong.invalid'},{'exp':1},{'scope':'email'}])
def test_all_admin_resources_reject_invalid_access_claims_before_reading(tmp_path,signing,changes):
    c=client(tmp_path,signing)
    headers=auth(token(signing,**{'cognito:groups':['powerflow-admins']},**changes))
    for path in ['/admin/operations','/admin/models/linear-feature-influence','/admin/forecast/provenance','/admin/monitoring/forecast-vintages','/admin/monitoring/exogenous-readiness','/monitoring/forecast-vintages','/monitoring/exogenous-readiness']:
        response=c.get(path,headers=headers)
        assert response.status_code==401
        assert response.headers['cache-control']=='no-store'


def test_raw_price_comparison_matches_streamlit_and_missing_windows(tmp_path):
    from dashboard_data import summarize_clean_price_history
    root=tmp_path;path=root/'data/raw/entsoe/prices.csv';path.parent.mkdir(parents=True)
    frame=pd.DataFrame({'timestamp':pd.date_range('2026-09-01', periods=168*4, freq='15min',tz='UTC'), 'price_eur_mwh':[v for v in range(-100,68) for _ in range(4)]})
    frame.to_csv(path,index=False)
    expected=summarize_clean_price_history(frame)
    with TestClient(create_app(APISettings.from_root(root))) as c:
        result=c.get('/market/price-comparison');assert result.status_code==200
        for key in ['latest_price','previous_24h_average','seven_day_average']:
            assert result.json()[key]==expected[key]
        assert result.json()['latest_price']==67
        frame.iloc[-12:].to_csv(path,index=False)
        s=c.get('/market/price-comparison').json()
        assert s['latest_price']==67 and s['previous_24h_average'] is None and s['seven_day_average'] is None
        explicit=pd.DataFrame({'timestamp':pd.date_range('2026-09-01',periods=3,freq='h',tz='UTC'),'price_eur_mwh':[1,2,3],'source_resolution':['PT60M']*3})
        explicit.to_csv(path,index=False)
        assert c.get('/market/price-comparison').json()['latest_price']==3
        path.write_text('timestamp,price_eur_mwh\nprivate,nan\n')
        r=c.get('/market/price-comparison');assert r.status_code==503 and 'private' not in r.text
        path.unlink()
        assert c.get('/market/price-comparison').status_code==404


def test_realized_releases_never_share_sample_counts(tmp_path):
    path=write_realized(tmp_path,20)
    rows=pd.read_csv(path)
    other=rows.iloc[:4].copy();other['model_release']='another-release'
    pd.concat([rows,other]).to_csv(path,index=False)
    with TestClient(create_app(APISettings.from_root(tmp_path))) as c:
        result=c.get('/forecast/realized-evaluation');assert result.status_code==200
        releases={r['model_release']:r for r in result.json()['releases']}
        assert releases['fixture-release']['overall']['pair_count']==20
        assert releases['fixture-release']['overall']['mae']==2
        assert releases['another-release']['overall']['pair_count']==4
        assert releases['another-release']['overall']['mae'] is None


def test_forecast_provenance_requires_admin_and_matches_complete_issued_cycle(tmp_path,signing):
    from test_api import _write_next24
    settings=APISettings.from_root(tmp_path);_write_next24(settings.next24_forecast)
    c=client(tmp_path,signing);headers=auth(token(signing,**{'cognito:groups':['powerflow-admins']}))
    route='/admin/forecast/provenance'
    assert c.get(route).status_code==401
    assert c.get(route,headers=auth(token(signing))).status_code==403
    result=c.get(route,headers=headers);assert result.status_code==200
    assert result.json()['issuance_evidence']=='missing' and result.json()['issued_at_utc'] is None
    frame=pd.read_csv(settings.next24_forecast)
    issue=pd.Timestamp(frame.forecast_issue_time.iloc[0])
    frame['issued_at_utc']=(issue+pd.Timedelta(minutes=5)).isoformat()
    history=tmp_path/'data/reports/next24h_forecast_history.csv';frame.to_csv(history,index=False)
    provenance=tmp_path/'data/reports/next24h_forecast_provenance.json'
    provenance.write_text(json.dumps({'forecast_issue_time':issue.isoformat(),'weather_source':'open_meteo_forecast_api_operational_model','market_latest_complete_hour':issue.isoformat(),'weather_acquired_at_utc':issue.isoformat(),'local_path':'private-path','credential':'never-display'}))
    result=c.get(route,headers=headers);assert result.status_code==200
    assert result.json()['issuance_evidence']=='available' and result.json()['provenance_evidence']=='available'
    assert 'private-path' not in result.text and 'never-display' not in result.text
    frame.iloc[:23].to_csv(history,index=False)
    assert c.get(route,headers=headers).json()['issuance_evidence']=='no_matching_complete_issue'
    frame.loc[0,'predicted_price_eur_mwh']+=1;frame.to_csv(history,index=False)
    assert c.get(route,headers=headers).status_code==503
