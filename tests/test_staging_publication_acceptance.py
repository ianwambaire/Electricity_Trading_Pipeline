"""Synthetic HTTP responses via MockTransport; no listener, tokens or network."""
import copy
import importlib.util
from pathlib import Path
from datetime import timedelta
import httpx
import pytest
from test_forecast_publication import fixture, ISSUE, NOW

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('state_smoke',ROOT/'scripts/smoke_staging.py')
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)


def transport(state, fault=None, changed=False):
    calls=[];bundle=fixture()
    data={'row_count':24,'forecasts':bundle['forecasts'],'publication':{'status':'VALID','issue_time':ISSUE.isoformat(),'expires_at':(ISSUE+timedelta(hours=3)).isoformat(),'completed_at':bundle['execution']['completed_at']}}
    def handler(req):
        calls.append(req);assert req.method=='GET'
        path=req.url.path
        if path in (*smoke.PAGES,'/auth/callback'):
            return httpx.Response(200,text='<div id="root"></div>',headers={'content-type':'text/html'})
        if path=='/api/ready':return httpx.Response(404)
        if path.removeprefix('/api') in smoke.ADMIN:
            value=req.headers.get('authorization')
            if not value:return httpx.Response(401)
            if value=='Bearer analyst':return httpx.Response(200 if fault=='analyst_escalation' else 403)
            if path!='/api/admin/forecast/provenance':return httpx.Response(503 if fault=='other_admin_503' else 404)
            if state in ('EXPIRED','WITHHELD','MISSING_PUBLICATION'):
                return httpx.Response(503,json={'detail':{'code':'OTHER' if fault=='bad_provenance_503' else 'FORECAST_WITHHELD'}},headers={'cache-control':'no-store'})
            if changed or fault=='unexpected_409':
                return httpx.Response(409,json={'detail':smoke.CHANGED_DETAIL},headers={'cache-control':'no-store'})
            return httpx.Response(200,json={'issue_time':(ISSUE+timedelta(hours=1)).isoformat() if fault=='issue_mismatch' else ISSUE.isoformat(),
                'issuance_evidence':'available','provenance_evidence':'available','weather_acquired_at_utc':bundle['provenance']['weather_acquired_at'],'issued_at_utc':bundle['execution']['issued_at']},headers={'cache-control':'no-store'})
        if path=='/api/auth/me':return httpx.Response(200,json={'role':'Analyst' if req.headers['authorization']=='Bearer analyst' else 'Admin'})
        if path=='/api/operations/summary':return httpx.Response(200,json={
            'forecast_status':'VALID' if fault=='wrong_state' else state,'health':'Historical snapshot','completeness_note':'Historical operational snapshot',
            'forecast_reason_provenance':'Active controlled publication','forecast_reason':f'Valid published forecast; issue {ISSUE.isoformat()}, freshness cutoff {(ISSUE+timedelta(hours=3)).isoformat()}.'})
        if path=='/api/forecast/next24':
            if state in ('EXPIRED','WITHHELD','MISSING_PUBLICATION'):
                return httpx.Response(503,json={'detail':{'code':'OTHER' if fault=='bad_forecast_503' else 'FORECAST_WITHHELD'}},headers={'cache-control':'public' if fault=='cached_503' else 'no-store'})
            if fault=='valid_503':return httpx.Response(503,json={'detail':{'code':'FORECAST_WITHHELD'}},headers={'cache-control':'no-store'})
            value=copy.deepcopy(data)
            if fault=='missing_prediction':value['forecasts'].pop()
            if fault=='nan':value['forecasts'][0]['predicted_price_eur_mwh']=True
            if fault=='alignment':value['forecasts'][0]['target_time']=value['forecasts'][1]['target_time']
            if fault=='boolean_horizon':value['forecasts'][0]['horizon_hours']=True
            if fault=='boolean_release':
                for row in value['forecasts']:row['model_release']=True
            return httpx.Response(200,json=value,headers={'cache-control':'no-store'})
        return httpx.Response(200)
    return httpx.MockTransport(handler),calls


@pytest.mark.parametrize('state',['VALID','EXPIRED','WITHHELD','MISSING_PUBLICATION'])
def test_state_specific_success_has_seven_admin_denials_and_gets_only(state):
    mock,calls=transport(state)
    with httpx.Client(base_url='https://staging.powerflowenergy.dev',transport=mock) as client:
        result=smoke.verify(client,'analyst','admin',expected_publication=state,now=NOW)
    assert result['analyst_admin_denials']==7 and result['publication_state']==state
    assert len([req for req in calls if req.url.path in smoke.PAGES])==7


@pytest.mark.parametrize('state,fault',[
    ('VALID','valid_503'),('VALID','unexpected_409'),('VALID','issue_mismatch'),('VALID','missing_prediction'),
    ('VALID','nan'),('VALID','boolean_horizon'),('VALID','boolean_release'),('VALID','alignment'),('VALID','analyst_escalation'),('VALID','other_admin_503'),
    ('EXPIRED','bad_forecast_503'),('WITHHELD','bad_provenance_503'),('MISSING_PUBLICATION','cached_503'),('EXPIRED','wrong_state')])
def test_errors_never_receive_blanket_status_acceptance(state,fault):
    mock,_=transport(state,fault)
    with httpx.Client(base_url='https://staging.powerflowenergy.dev',transport=mock) as client:
        with pytest.raises(AssertionError):smoke.verify(client,'analyst','admin',expected_publication=state,now=NOW)


def test_409_requires_explicit_stale_pin_and_valid_changed_publication():
    mock,calls=transport('VALID',changed=True)
    with httpx.Client(base_url='https://staging.powerflowenergy.dev',transport=mock) as client:
        result=smoke.verify(client,'analyst','admin',expected_publication='VALID',now=NOW,
            previous_issue=(ISSUE-timedelta(hours=1)).isoformat(),previous_completed=(ISSUE+timedelta(minutes=20)).isoformat())
    assert result['provenance_status']==409
    request=next(req for req in calls if req.url.path=='/api/admin/forecast/provenance' and req.headers.get('authorization')=='Bearer admin')
    assert request.url.params['issue_time']==(ISSUE-timedelta(hours=1)).isoformat()


def test_stale_http200_cannot_pass_as_valid():
    mock,_=transport('VALID')
    with httpx.Client(base_url='https://staging.powerflowenergy.dev',transport=mock) as client:
        with pytest.raises(AssertionError):smoke.verify(client,'analyst','admin',expected_publication='VALID',now=ISSUE+timedelta(hours=4))
