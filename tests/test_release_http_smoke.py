"""No AWS, listener, real accounts or production forecast data."""
import importlib.util
import json
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

spec=importlib.util.spec_from_file_location('smoke_web_release',Path(__file__).parents[1]/'scripts/smoke_web_release.py')
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)


def test_candidate_routing_api_auth_and_readiness(tmp_path):
    (tmp_path/'index.html').write_text('<html><div id="root"></div></html>')
    (tmp_path/'build-config.json').write_text(json.dumps(dict(apiBase='/api',releaseEligible=True,origin='https://candidate.example.test')))
    result=smoke.run(tmp_path)
    assert result['pages']==7 and result['analyst_denials']==7 and not result['production_deployed']


def test_local_build_not_silently_treated_as_release(tmp_path):
    (tmp_path/'build-config.json').write_text(json.dumps(dict(apiBase='/api',releaseEligible=False)))
    with pytest.raises(ValueError):smoke.run(tmp_path)


def test_existing_pages_and_other_apis_work_when_next24_is_unavailable(tmp_path):
    (tmp_path/'index.html').write_text('<html><div id="root"></div></html>')
    (tmp_path/'build-config.json').write_text(json.dumps(dict(apiBase='/api',releaseEligible=True,origin='https://candidate.example.test')))
    result=smoke.run(tmp_path,next24_available=False)
    assert result['pages']==7 and result['next24_available'] is False


from test_api_security import signing, token, auth


def test_proxy_rehearsal_preserves_query_pins_and_authorization(tmp_path,monkeypatch,signing):
    from test_forecast_source_consistency import make_client, write_bundle
    from test_forecast_publication import fixture, ISSUE
    from datetime import timedelta
    api,settings,publication,clock,_=make_client(tmp_path,monkeypatch,signing)
    write_bundle(publication,fixture())
    dist=tmp_path/'static';dist.mkdir();(dist/'index.html').write_text('<div id="root"></div>')
    with api,TestClient(smoke.frontend_rehearsal(dist,api)) as web:
        route='/api/admin/forecast/provenance'
        assert web.get(route).status_code==401
        assert web.get(route,headers=auth(token(signing))).status_code==403
        admin=auth(token(signing,**{'cognito:groups':['powerflow-admins']}))
        expected=web.get('/api/forecast/next24').json()['publication']
        good=web.get(route,headers=admin,params={'issue_time':expected['issue_time'],'completed_at':expected['completed_at']})
        assert good.status_code==200
        changed=web.get(route,headers=admin,params={'issue_time':(ISSUE-timedelta(hours=1)).isoformat()})
        assert changed.status_code==409
        assert 'no-store' in changed.headers['cache-control']
