"""Offline route-policy and real FastAPI authorization tests; no Nginx execution."""
import importlib.util
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
from api.app import APISettings,create_app
from api.security import CurrentUser,get_current_user

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('operational_routing',ROOT/'deploy/staging/operational-evidence-routing/routing.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

def test_three_current_endpoints_are_exact_additions():
    old=r.approved();new=r.patch(old)
    for path in r.ROUTES:
        assert re.fullmatch(r.rule(old),path)is None
        assert re.fullmatch(r.rule(new),path)is not None
    before=old.decode().splitlines();after=new.decode().splitlines()
    assert len(before)==len(after) and sum(a!=b for a,b in zip(before,after))==1
    assert (ROOT/'deploy/staging/operational-evidence-routing/staging.powerflowenergy.dev.conf').read_bytes()==new


@pytest.mark.parametrize('path',['/api/health','/api/auth/me','/api/pipeline/status','/api/operations/summary','/api/forecast/next24','/api/forecast/one-hour','/api/forecast/context','/api/forecast/realized-evaluation','/api/market/history','/api/monitoring/forecast-vintages','/api/admin/operations','/api/admin/forecast/provenance','/api/account/profile'])
def test_existing_routes_remain_allowed(path):
    old=r.approved();assert re.fullmatch(r.rule(old),path) and re.fullmatch(r.rule(r.patch(old)),path)


@pytest.mark.parametrize('path',['/api/ready','/api/docs','/api/openapi.json','/api/admin/users','/api/operations/current/extra','/api/pipeline/current/','/api/admin/operations/current/extra','/api/Operations/current','/api/operations/currently','/api/pipeline/../current','/api/../operations/current'])
def test_unapproved_paths_are_not_added(path):
    assert re.fullmatch(r.rule(r.patch(r.approved())),path)is None


def test_auth_headers_tls_security_and_response_bounds_are_unchanged():
    old=r.approved();new=r.patch(old)
    assert old.replace(r.rule(old).encode(),b'ALLOWLIST')==new.replace(r.rule(new).encode(),b'ALLOWLIST')
    for directive in [b'proxy_set_header Authorization $http_authorization;',b'proxy_pass http://127.0.0.1:8010/;',b'proxy_redirect off;',b'proxy_cache off;',b'add_header Cache-Control no-store always;',b'ssl_protocols TLSv1.2 TLSv1.3;',b'client_max_body_size 16k;']:
        assert directive in new


@pytest.mark.parametrize('kind',['duplicate_rule','wrong_hostname','unanchored','unexpected_route','already_patched'])
def test_ambiguous_or_drifted_config_fails_closed(kind):
    source=r.approved()
    if kind=='duplicate_rule':source+=source
    elif kind=='wrong_hostname':source=source.replace(b'server_name staging.powerflowenergy.dev;',b'server_name other.invalid;')
    elif kind=='unanchored':source=source.replace(b'^/api/',b'/api/')
    elif kind=='unexpected_route':source=source.replace(b'pipeline/status',b'pipeline/status|unreviewed')
    else:source=r.patch(source)
    with pytest.raises(ValueError):r.patch(source)


def test_current_public_routes_and_admin_boundary_using_real_api(tmp_path):
    # This models only the reviewed proxy allowlist/prefix stripping, not Nginx.
    client=TestClient(create_app(APISettings.from_root(tmp_path)))
    pattern=r.rule(r.patch(r.approved()))
    for path in ['/api/operations/current','/api/pipeline/current']:
        assert re.fullmatch(pattern,path)
        response=client.get(path[4:]);assert response.status_code==200
        assert response.json()['status']=='MISSING' and response.json()['current_execution']is None
        assert response.headers['cache-control']=='no-store'
    assert re.fullmatch(pattern,'/api/admin/operations/current')
    assert client.get('/admin/operations/current').status_code==401
    client.app.dependency_overrides[get_current_user]=lambda:CurrentUser('11111111-1111-4111-8111-111111111111','Analyst',None,None,frozenset(),None)
    assert client.get('/admin/operations/current').status_code==403
    client.app.dependency_overrides[get_current_user]=lambda:CurrentUser('11111111-1111-4111-8111-111111111111','Admin',None,None,frozenset(),None)
    response=client.get('/admin/operations/current')
    assert response.status_code==200 and response.json()['status']=='MISSING'


def test_proposal_generation_does_not_modify_approved_source():
    path=r.BASE/r.SOURCE;before=path.read_bytes();r.patch(before);assert path.read_bytes()==before
