"""Offline source consistency: synthetic bundles, mocked operations and JWKS only."""
import copy
from dataclasses import replace
from datetime import timedelta
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from joserfc import jwk
import pytest

import api.app as app_module
from api.app import APISettings, create_app
from api.operations_summary import unavailable_operations
from api.security import CognitoVerifier, JwksCache
import shared.forecast_publication as contract
import shared.forecast_availability as availability
from test_forecast_publication import fixture, encoded, ISSUE, NOW
from test_api_security import SETTINGS, public, token, auth


@pytest.fixture
def signing():
    return jwk.RSAKey.generate_key(2048, parameters={'kid':'key-one','alg':'RS256','use':'sig'})


def write_bundle(root, bundle):
    """Synthetic fixture layout only; never execute the publication tool."""
    root.mkdir(mode=0o750, exist_ok=True)
    releases=root/'releases';releases.mkdir(mode=0o750, exist_ok=True)
    raw,digest=encoded(bundle)
    directory=releases/digest;directory.mkdir(mode=0o750,exist_ok=True)
    path=directory/'bundle.json';path.write_bytes(raw);path.chmod(0o640)
    pointer=root/'current'
    if pointer.is_symlink():pointer.unlink()
    pointer.symlink_to('releases/'+digest)
    return path


def make_client(tmp_path, monkeypatch, signing, *, configured=True):
    settings=APISettings.from_root(tmp_path/'historical')
    root=tmp_path/'publication'
    if configured:settings=replace(settings,next24_publication_root=root)
    # An unrelated retained report must never be used by publication mode.
    settings.next24_forecast.parent.mkdir(parents=True)
    settings.next24_forecast.write_text('unrelated historical report; never use this as fallback')
    app=create_app(settings,security_settings=SETTINGS)
    app.state.cognito_verifier=CognitoVerifier(SETTINGS,JwksCache(SETTINGS.jwks_url,fetch=lambda _: {'keys':[public(signing)]}))
    app.state.account_gateway=SimpleNamespace(assert_active=lambda _token,_scopes,subject:{'sub':subject})
    snapshot=unavailable_operations().model_copy(update={
        'health':'Degraded','latest_run_status':'SUCCESS','latest_run_time':ISSUE-timedelta(days=3),
        'latest_success_time':ISSUE-timedelta(days=3),'forecast_status':'WITHHELD',
        'forecast_reason':'Historical withholding, not current publication evidence.'})
    monkeypatch.setattr(app_module,'operations_summary',lambda *_args,**_kwargs:snapshot)
    real=availability.read_active;clock=[NOW];reads=[]
    def read(directory):
        reads.append(directory)
        return real(directory,clock[0])
    monkeypatch.setattr(availability,'read_active',read)
    return TestClient(app),settings,root,clock,reads


def admin(signing):return auth(token(signing,**{'cognito:groups':['powerflow-admins']}))


def test_forecast_provenance_and_status_use_same_bundle_not_frozen_paths(tmp_path,monkeypatch,signing):
    c,settings,root,clock,reads=make_client(tmp_path,monkeypatch,signing)
    bundle=fixture();write_bundle(root,bundle)
    before=settings.next24_forecast.read_bytes()
    def forbidden(*_):raise AssertionError('Legacy forecast source used in publication mode')
    monkeypatch.setattr(app_module,'_next24_report',forbidden)
    with c:
        forecast=c.get('/forecast/next24');assert forecast.status_code==200
        report=forecast.json()
        response=c.get('/admin/forecast/provenance',headers=admin(signing),params={
            'issue_time':report['publication']['issue_time'],'completed_at':report['publication']['completed_at']})
        assert response.status_code==200
        evidence=response.json()
        assert contract.time(evidence['issue_time'])==contract.time(report['publication']['issue_time'])
        assert contract.time(evidence['issued_at_utc'])==contract.time(bundle['execution']['issued_at'])
        assert contract.time(evidence['weather_acquired_at_utc'])==contract.time(bundle['provenance']['weather_acquired_at'])
        assert evidence['issuance_evidence']==evidence['provenance_evidence']=='available'
        assert evidence['market_latest_complete_hour'] is None
        assert 'hash-bound bundle' in evidence['note']
        summary=c.get('/operations/summary').json()
        assert summary['forecast_status']=='VALID'
        assert next(p for p in summary['products'] if p['product']=='24-hour predictions')['status']=='available'
        assert summary['latest_run_status']=='SUCCESS'
        assert summary['health']=='Historical snapshot'
        assert 'not live' in summary['explanation']
        assert 'Historical operational snapshot' in summary['completeness_note']
        assert ISSUE.isoformat() in summary['forecast_reason']
        assert 'Historical withholding' not in summary['forecast_reason']
        assert len(reads)==3  # exactly one selection per affected request
        for body in [report,evidence,summary]:
            text=json.dumps(body)
            assert 'feature_values' not in text and 'source_sha256' not in text and 'unrelated historical report' not in text
    assert settings.next24_forecast.read_bytes()==before


@pytest.mark.parametrize('kind,status',[('missing','MISSING_PUBLICATION'),('expired','EXPIRED'),('invalid','WITHHELD'),('invalid_expired','WITHHELD'),('missing_evidence','WITHHELD')])
def test_no_stale_or_missing_fallback_and_independent_status(tmp_path,monkeypatch,signing,kind,status):
    c,settings,root,clock,_=make_client(tmp_path,monkeypatch,signing)
    bundle=fixture()
    if kind.startswith('invalid'):bundle['inputs']['price_history'].pop(next(iter(bundle['inputs']['price_history'])))
    if kind=='missing_evidence':bundle.pop('provenance')
    if kind!='missing':write_bundle(root,bundle)
    if 'expired' in kind:clock[0]=ISSUE+timedelta(hours=24)
    with c:
        for path in ['/forecast/next24','/admin/forecast/provenance']:
            result=c.get(path,headers=admin(signing))
            assert result.status_code==503
            assert result.json()=={'detail':{'code':'FORECAST_WITHHELD'}}
            assert result.headers['cache-control']=='no-store'
        result=c.get('/operations/summary')
        assert result.status_code==200
        assert result.json()['forecast_status']==status
        assert next(p for p in result.json()['products'] if p['product']=='24-hour predictions')['status']=='missing'
        assert result.json()['latest_run_status']=='SUCCESS'  # not proof of generation
        assert 'forecasts' not in result.json() and 'predicted_price_eur_mwh' not in result.text


def test_unavailable_operations_does_not_mask_valid_forecast(tmp_path,monkeypatch,signing):
    from fastapi import HTTPException
    c,settings,root,clock,_=make_client(tmp_path,monkeypatch,signing)
    write_bundle(root,fixture())
    def unavailable(*_):raise HTTPException(503,'private database details must not escape')
    monkeypatch.setattr(app_module,'operations_summary',unavailable)
    with c:
        result=c.get('/operations/summary')
        assert result.status_code==200
        data=result.json()
        assert data['health']=='Unavailable' and data['latest_run_status'] is None
        assert data['forecast_status']=='VALID'
        assert 'private database details' not in result.text
        assert c.get('/forecast/next24').status_code==200
        assert c.get('/admin/forecast/provenance',headers=admin(signing)).status_code==200


def test_cross_request_publication_change_rejects_issue_and_same_issue_revision(tmp_path,monkeypatch,signing):
    c,settings,root,clock,_=make_client(tmp_path,monkeypatch,signing)
    first=fixture();write_bundle(root,first)
    with c:
        old=c.get('/forecast/next24').json()['publication']
        revised=copy.deepcopy(first)
        revised['execution']['issued_at']=(ISSUE+timedelta(hours=1,minutes=22)).isoformat()
        revised['execution']['completed_at']=(ISSUE+timedelta(hours=1,minutes=23)).isoformat()
        write_bundle(root,revised)
        response=c.get('/admin/forecast/provenance',headers=admin(signing),params={'issue_time':old['issue_time'],'completed_at':old['completed_at']})
        assert response.status_code==409
        clock[0]=NOW+timedelta(hours=1)
        write_bundle(root,fixture(ISSUE+timedelta(hours=1)))
        assert c.get('/admin/forecast/provenance',headers=admin(signing),params={'issue_time':old['issue_time']}).status_code==409


@pytest.mark.parametrize('state',['valid','missing','expired'])
def test_admin_authorization_is_checked_before_reading_publication(tmp_path,monkeypatch,signing,state):
    c,settings,root,clock,reads=make_client(tmp_path,monkeypatch,signing)
    if state!='missing':write_bundle(root,fixture())
    if state=='expired':clock[0]=ISSUE+timedelta(hours=24)
    with c:
        assert c.get('/admin/forecast/provenance').status_code==401
        assert c.get('/admin/forecast/provenance',headers=auth(token(signing))).status_code==403
        assert reads==[]
        assert c.get('/forecast/next24').status_code==(200 if state=='valid' else 503)
        assert c.get('/operations/summary').status_code==200


def test_legacy_snapshot_mode_remains_separate_and_explicit(tmp_path,monkeypatch,signing):
    import csv
    c,settings,root,clock,reads=make_client(tmp_path,monkeypatch,signing,configured=False)
    bundle=fixture()
    with settings.next24_forecast.open('w',newline='') as handle:
        writer=csv.writer(handle)
        writer.writerow(['forecast_issue_time','target_timestamp','horizon_hours','predicted_price_eur_mwh','model_release'])
        for row in bundle['forecasts']:writer.writerow([row['issue_time'],row['target_time'],row['horizon_hours'],row['predicted_price_eur_mwh'],row['model_release']])
    with c:
        report=c.get('/forecast/next24').json()
        assert 'publication' not in report
        evidence=c.get('/admin/forecast/provenance',headers=admin(signing)).json()
        assert evidence['issuance_evidence']==evidence['provenance_evidence']=='missing'
        result=c.get('/operations/summary').json()
        assert result['forecast_status']=='WITHHELD'
        assert 'Historical' in result['forecast_reason_provenance']
        assert 'not live' in result['explanation']
        assert reads==[]


def test_real_adapter_missing_and_corrupt_snapshot_keeps_publication_independent(tmp_path,monkeypatch,signing):
    from api.operations_summary import operations_summary
    c,settings,root,clock,_=make_client(tmp_path,monkeypatch,signing)
    write_bundle(root,fixture())
    monkeypatch.setattr(app_module,'operations_summary',operations_summary)
    with c:
        # No operational database exists. No SQLite connection creates one.
        first=c.get('/operations/summary')
        assert first.status_code==200 and first.json()['health']=='Unavailable'
        assert first.json()['forecast_status']=='VALID'
        assert not settings.operational_database.exists()
        settings.operational_database.parent.mkdir()
        settings.operational_database.write_bytes(b'synthetic corrupt snapshot; confidential sentinel')
        before=settings.operational_database.read_bytes()
        second=c.get('/operations/summary')
        assert second.status_code==200 and second.json()['health']=='Unavailable'
        assert second.json()['forecast_status']=='VALID'
        assert 'confidential sentinel' not in second.text
        assert settings.operational_database.read_bytes()==before
        assert c.get('/forecast/next24').status_code==200


def test_product_availability_never_uses_retained_csv_when_publication_expired(tmp_path,monkeypatch,signing):
    from api.operations_summary import operations_summary
    c,settings,root,clock,_=make_client(tmp_path,monkeypatch,signing)
    write_bundle(root,fixture());clock[0]=ISSUE+timedelta(hours=24)
    monkeypatch.setattr(app_module,'operations_summary',operations_summary)
    with c:
        summary=c.get('/operations/summary').json()
        assert settings.next24_forecast.is_file()
        assert summary['forecast_status']=='EXPIRED'
        assert next(p for p in summary['products'] if p['product']=='24-hour predictions')['status']=='missing'
