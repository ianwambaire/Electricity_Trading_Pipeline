"""Synthetic fixtures only: no production artifact or database is read."""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from api.app import APISettings, create_app
import shared.forecast_publication as contract

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('forecast_publisher',ROOT/'deploy/staging/forecast-publication/publish.py')
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
ISSUE=dt.datetime(2026,1,5,8,tzinfo=dt.timezone.utc)
NOW=ISSUE+dt.timedelta(hours=2)

def fixture(issue=ISSUE):
    features=dict.fromkeys(contract.FEATURES,1.0)
    features.update(hour=issue.hour,day_of_week=issue.weekday(),month=issue.month,is_weekend=int(issue.weekday()>=5),price_eur_mwh=100,price_lag_1h=100,price_lag_24h=100,price_lag_168h=100,price_rolling_mean_24h=100,price_rolling_std_24h=0,load_mw=40000,load_lag_1h=40000,load_lag_24h=40000,load_rolling_mean_24h=40000,nuclear_mw=0,wind_offshore_mw=1,wind_onshore_mw=1,wind_total_mw=2,renewable_generation_mw=5,renewable_share=5/8)
    fields=['biomass_mw','lignite_mw','gas_mw','hard_coal_mw','hydro_mw','solar_mw','wind_offshore_mw','wind_onshore_mw']
    bundle = {'version':1,'forecasts':[{'issue_time':issue.isoformat(),'target_time':(issue+dt.timedelta(hours=i)).isoformat(),'horizon_hours':i,'predicted_price_eur_mwh':100+i,'model_release':contract.RELEASE} for i in range(1,25)],'model':{'release':contract.RELEASE,'model_sha256':contract.MODEL_HASH,'feature_contract_sha256':contract.CONTRACT_HASH},'execution':{'run_id':'11111111-1111-4111-8111-111111111111','started_at':(issue+dt.timedelta(hours=1)).isoformat(),'issued_at':(issue+dt.timedelta(hours=1,minutes=20)).isoformat(),'completed_at':(issue+dt.timedelta(hours=1,minutes=21)).isoformat(),'status':'GENERATED'},'provenance':{'issue_time':issue.isoformat(),'weather_hour':issue.isoformat(),'weather_acquired_at':(issue+dt.timedelta(hours=1,minutes=10)).isoformat(),'weather_source':'open_meteo_forecast_api_operational_model'},'inputs':{'features':features,'price_history':{(issue-dt.timedelta(hours=i)).isoformat():100 for i in {*range(24),24,168}},'load_history':{(issue-dt.timedelta(hours=i)).isoformat():40000 for i in range(25)},'generation_quarters':[{'timestamp':(issue+dt.timedelta(minutes=i*15)).isoformat(),**{k:1 for k in fields}} for i in range(4)]}}

    for source, field in [('price','price_eur_mwh'),('load','load_mw')]:
        bundle['inputs'][source+'_samples']={hour:{**({'resolution':'PT15M'} if source=='price' else {}),'points':[{'timestamp':(dt.datetime.fromisoformat(hour)+dt.timedelta(minutes=i*15)).isoformat(),field:value} for i in range(4)]} for hour,value in bundle['inputs'][source+'_history'].items()}
    return bundle


def encoded(bundle):
    raw=json.dumps(bundle,sort_keys=True).encode();return raw,hashlib.sha256(raw).hexdigest()

def storage(tmp_path):
    root=tmp_path/'overlay';root.mkdir(mode=0o750);(root/'releases').mkdir(mode=0o750);return root

def source(tmp_path,bundle):
    raw,digest=encoded(bundle);p=tmp_path/(digest+'.json');p.write_bytes(raw);p.chmod(0o640);return p,digest

def test_valid_contract_exact_freshness_boundary():
    raw,digest=encoded(fixture());assert contract.validate(raw,digest,NOW)['version']==1
    contract.validate(raw,digest,ISSUE+dt.timedelta(hours=3))
    with pytest.raises(contract.Withheld):contract.validate(raw,digest,ISSUE+dt.timedelta(hours=3,microseconds=1))
    with pytest.raises(contract.Withheld):contract.validate(raw,digest,ISSUE-dt.timedelta(seconds=1))

@pytest.mark.parametrize('kind',['missing','nan','bool','alignment','duplicate','model','contract','provenance','feature','lag','window','generation','calendar','extra','execution','price_quarter','load_quarter'])
def test_invalid_bundle_is_withheld(kind):
    b=fixture()
    if kind=='missing':b['forecasts'].pop()
    elif kind=='nan':b['forecasts'][0]['predicted_price_eur_mwh']=float('nan')
    elif kind=='bool':b['forecasts'][0]['predicted_price_eur_mwh']=True
    elif kind=='alignment':b['forecasts'][0]['target_time']=b['forecasts'][1]['target_time']
    elif kind=='duplicate':b['forecasts'][1]=copy.deepcopy(b['forecasts'][0])
    elif kind=='model':b['model']['release']='unapproved'
    elif kind=='contract':b['model']['feature_contract_sha256']='0'*64
    elif kind=='provenance':b['provenance']['weather_hour']=(ISSUE-dt.timedelta(hours=1)).isoformat()
    elif kind=='feature':b['inputs']['features'].pop('biomass_mw')
    elif kind=='lag':b['inputs']['price_history'].pop((ISSUE-dt.timedelta(hours=168)).isoformat())
    elif kind=='window':b['inputs']['load_history'].pop((ISSUE-dt.timedelta(hours=7)).isoformat())
    elif kind=='generation':b['inputs']['generation_quarters'].pop()
    elif kind=='price_quarter':b['inputs']['price_samples'][(ISSUE-dt.timedelta(hours=168)).isoformat()]['points'].pop()
    elif kind=='load_quarter':b['inputs']['load_samples'][ISSUE.isoformat()]['points'].pop()
    elif kind=='calendar':b['inputs']['features']['hour']+=1
    elif kind=='extra':b['secret']='must never be accepted'
    elif kind=='execution':b['execution']['status']='WITHHELD'
    raw,digest=encoded(b)
    with pytest.raises(contract.Withheld):contract.validate(raw,digest,NOW)

def test_hash_and_duplicate_json_keys_rejected():
    raw,digest=encoded(fixture())
    with pytest.raises(contract.Withheld):contract.validate(raw,'0'*64,NOW)
    malformed=b'{"version":1,"version":1}'
    with pytest.raises(contract.Withheld):contract.validate(malformed,hashlib.sha256(malformed).hexdigest(),NOW)


def test_atomic_publish_rollback_and_historical_preservation(tmp_path):
    root=storage(tmp_path);historical=tmp_path/'historical';historical.write_bytes(b'unchanged historical snapshot')
    first,one=source(tmp_path,fixture());result=publisher.publish(root,first,one,None,lambda:NOW)
    assert result['previous_sha256'] is None
    assert contract.read_active(root,NOW)['forecasts'][0]['issue_time']==ISSUE.isoformat()
    second,two=source(tmp_path,fixture(ISSUE+dt.timedelta(hours=1)))
    publisher.publish(root,second,two,one,lambda:NOW+dt.timedelta(hours=1))
    # Restoring an expired release is prohibited; withdrawal remains available.
    with pytest.raises(contract.Withheld):publisher.rollback(root,two,one,lambda:ISSUE+dt.timedelta(hours=4))
    publisher.rollback(root,two,one,lambda:NOW)
    assert publisher.pointer(root)==one
    publisher.rollback(root,one,None,lambda:NOW)
    with pytest.raises(contract.Withheld):contract.read_active(root,NOW)
    assert historical.read_bytes()==b'unchanged historical snapshot'
    assert (root/'releases'/one/'bundle.json').is_file() and (root/'releases'/two/'bundle.json').is_file()

@pytest.mark.parametrize('kind',['hash','source_expired','expires_before_switch','wrong_current'])
def test_failed_publication_never_activates(tmp_path,kind):
    root=storage(tmp_path);p,digest=source(tmp_path,fixture());clock=lambda:NOW
    if kind=='hash':digest='0'*64
    if kind=='source_expired':clock=lambda:ISSUE+dt.timedelta(hours=4)
    if kind=='expires_before_switch':
        times=iter([NOW,NOW,NOW,ISSUE+dt.timedelta(hours=4)]);clock=lambda:next(times)
    with pytest.raises(contract.Withheld):publisher.publish(root,p,digest,'1'*64 if kind=='wrong_current' else None,clock)
    assert not os.path.lexists(root/'current')

@pytest.mark.parametrize('kind',['partial','tampered','symlink','writable'])
def test_partial_or_unsafe_artifacts_withheld(tmp_path,kind):
    root=storage(tmp_path);p,digest=source(tmp_path,fixture())
    if kind=='partial':
        (root/'releases'/('.partial-'+digest)).mkdir();(root/'current').symlink_to('releases/'+digest)
    else:
        publisher.publish(root,p,digest,None,lambda:NOW);target=root/'releases'/digest/'bundle.json'
        if kind=='tampered':target.write_text('{}')
        elif kind=='symlink':target.unlink();target.symlink_to(p)
        elif kind=='writable':target.chmod(0o666)
    with pytest.raises(contract.Withheld):contract.read_active(root,NOW)


def test_api_overlay_expiry_and_no_historical_fallback(tmp_path,monkeypatch):
    root=storage(tmp_path);p,digest=source(tmp_path,fixture());publisher.publish(root,p,digest,None,lambda:NOW)
    historical=tmp_path/'snapshot';settings=APISettings.from_root(historical)
    settings.next24_forecast.parent.mkdir(parents=True);settings.next24_forecast.write_text('historical sentinel')
    before=settings.next24_forecast.read_bytes();real_read=contract.read_active;clock=[NOW]
    monkeypatch.setattr(contract,'read_active',lambda directory:real_read(directory,clock[0]))
    with TestClient(create_app(replace(settings,next24_publication_root=root))) as client:
        good=client.get('/forecast/next24');assert good.status_code==200
        assert good.headers['cache-control']=='no-store'
        data=good.json();assert data['publication']['status']=='VALID' and len(data['forecasts'])==24
        assert set(data['publication'])=={'status','issue_time','expires_at','completed_at'}
        assert 'inputs' not in data and 'execution' not in data
        clock[0]=ISSUE+dt.timedelta(hours=3,seconds=1)
        expired=client.get('/forecast/next24');assert expired.status_code==503
        assert expired.json()=={'detail':{'code':'FORECAST_WITHHELD'}}
        assert expired.headers['cache-control']=='no-store'
        assert client.get('/health').status_code==200
        assert client.get('/forecast/one-hour').status_code==404
    assert settings.next24_forecast.read_bytes()==before


def test_offline_builder_projects_only_allowlisted_data(tmp_path):
    import csv
    spec=importlib.util.spec_from_file_location('prepare_bundle',ROOT/'deploy/staging/forecast-publication/prepare.py')
    prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)
    b=fixture();forecast=tmp_path/'forecast.csv';provenance=tmp_path/'provenance.json';model=tmp_path/'model.json';evidence=tmp_path/'evidence.json'
    with forecast.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['forecast_issue_time','target_timestamp','horizon_hours','predicted_price_eur_mwh','model_release'])
        for r in b['forecasts']:w.writerow([r['issue_time'],r['target_time'],r['horizon_hours'],r['predicted_price_eur_mwh'],r['model_release']])
    provenance.write_text(json.dumps({'forecast_issue_time':ISSUE.isoformat(),'weather_hour':ISSUE.isoformat(),'weather_acquired_at_utc':b['provenance']['weather_acquired_at'],'weather_source':b['provenance']['weather_source'],'weather_endpoint':'unused-public-field'}))
    model.write_text(json.dumps({'feature_count':31,'features':list(contract.FEATURES),'horizons_hours':list(range(1,25)),'release_id':contract.RELEASE,'model_sha256':contract.MODEL_HASH,'feature_contract_sha256':contract.CONTRACT_HASH,'source_candidate_path':'excluded-internal-path'}))
    evidence.write_text(json.dumps({'execution':b['execution'],'inputs':b['inputs']}))
    files=[forecast,provenance,model,evidence];hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
    raw,digest=prepare.build(*files,hashes,NOW)
    assert contract.validate(raw,digest,NOW)==b
    assert b'excluded-internal-path' not in raw and b'weather_endpoint' not in raw
    with pytest.raises(contract.Withheld):prepare.build(*files,['0'*64,*hashes[1:]],NOW)
    with pytest.raises(contract.Withheld):prepare.build(*files,hashes,ISSUE+dt.timedelta(hours=4))


def test_hash_failure_preserves_existing_pointer_and_concurrent_writer_is_rejected(tmp_path):
    root=storage(tmp_path);p,digest=source(tmp_path,fixture());publisher.publish(root,p,digest,None,lambda:NOW)
    with pytest.raises(contract.Withheld):publisher.publish(root,p,'0'*64,digest,lambda:NOW)
    assert publisher.pointer(root)==digest
    with publisher.locked(root):
        with pytest.raises(BlockingIOError):publisher.rollback(root,digest,None,lambda:NOW)
    assert publisher.pointer(root)==digest


def test_path_traversal_pointer_and_oversized_bundle_rejected(tmp_path):
    root=storage(tmp_path);(root/'current').symlink_to('../outside')
    with pytest.raises(contract.Withheld):contract.read_active(root,NOW)
    raw=b' '*100001
    with pytest.raises(contract.Withheld):contract.validate(raw,hashlib.sha256(raw).hexdigest(),NOW)
