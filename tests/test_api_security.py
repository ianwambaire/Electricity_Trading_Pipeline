"""Offline Cognito authorization tests: generated keys and mocked public JWKS only."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from joserfc import jwk, jwt
from api.app import APISettings, create_app
from api.security import CognitoVerifier, JwksCache, SecuritySettings, fetch_jwks

ISSUER = 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool'
SUB = '01234567-89ab-4def-8123-0123456789ab'
SETTINGS = SecuritySettings(ISSUER, frozenset({'allowedclient'}))


@pytest.fixture(scope='module')
def signing():
    return jwk.RSAKey.generate_key(2048, parameters={'kid':'key-one','alg':'RS256','use':'sig'})


def public(key):
    return key.as_dict(private=False)


def token(key, **changes):
    now = int(time.time())
    claims = dict(iss=ISSUER, sub=SUB, client_id='allowedclient', token_use='access', iat=now-1, exp=now+3600, scope='openid email profile')
    claims.update(changes)
    return jwt.encode({'alg':'RS256','kid':key.kid}, claims, key)


def client(root, key, settings=SETTINGS, fetch=None):
    app = create_app(APISettings.from_root(root), security_settings=settings)
    cache = JwksCache(settings.jwks_url, fetch=fetch or (lambda _url: {'keys':[public(key)]}))
    app.state.cognito_verifier = CognitoVerifier(settings, cache)
    return TestClient(app)


def auth(value):
    return {'Authorization':'Bearer '+value}


def test_valid_access_identity_minimal_and_no_tokens(tmp_path, signing):
    c=client(tmp_path,signing)
    value=token(signing)
    r=c.get('/auth/me',headers=auth(value))
    assert r.status_code==200 and r.json()==dict(subject=SUB,role='Analyst',email=None,display_name=None)
    assert r.headers['cache-control']=='no-store'
    assert value not in r.text and 'scope' not in r.json()
    r=c.get('/auth/me?role=Admin',headers=auth(value))
    assert r.json()['role']=='Analyst'


@pytest.mark.parametrize('header',[{}, {'Authorization':'Basic nonsense'}, {'Authorization':'Bearer'}, {'Authorization':'Bearer not-a-token'}, {'Authorization':'Bearer a.b.c'}, {'Authorization':'Bearer '+ 'a'*17000}])
def test_missing_and_malformed_tokens_are_401(tmp_path,signing,header):
    r=client(tmp_path,signing).get('/auth/me',headers=header)
    assert r.status_code==401 and r.headers['www-authenticate']=='Bearer'
    assert r.json()['detail']=='A valid Cognito access token is required.'


@pytest.mark.parametrize('changes',[
 {'exp':1}, {'iss':'https://wrong.invalid'}, {'client_id':'wrongclient'}, {'token_use':'id'}, {'scope':'email profile'},
 {'scope':['openid']}, {'exp':True}, {'iat':int(time.time())+86400}, {'nbf':int(time.time())+86400},
 {'aud':'https://unexpected-resource.invalid'}, {'sub':'not-a-subject'}, {'iss':[ISSUER]}, {'client_id':['allowedclient']},
])
def test_invalid_claims_are_401(tmp_path,signing,changes):
    r=client(tmp_path,signing).get('/auth/me',headers=auth(token(signing,**changes)))
    assert r.status_code==401


def test_signature_forgery_algorithms_embedded_keys_and_missing_claims(tmp_path,signing):
    c=client(tmp_path,signing)
    wrong=jwk.RSAKey.generate_key(2048,parameters={'kid':'key-one','alg':'RS256','use':'sig'})
    assert c.get('/auth/me',headers=auth(token(wrong))).status_code==401
    claims=dict(iss=ISSUER,sub=SUB,client_id='allowedclient',token_use='access',scope='openid',iat=int(time.time())-1,exp=int(time.time())+300)
    for field in ['iss','sub','exp','iat','client_id','scope','token_use']:
        value=jwt.encode({'alg':'RS256','kid':signing.kid},{k:v for k,v in claims.items() if k!=field},signing)
        assert c.get('/auth/me',headers=auth(value)).status_code==401
    hs=jwk.OctKey.generate_key(256)
    value=jwt.encode({'alg':'HS256','kid':signing.kid},claims,hs)
    assert c.get('/auth/me',headers=auth(value)).status_code==401
    value=jwt.encode({'alg':'RS256','kid':signing.kid,'jku':'https://untrusted.invalid'},claims,signing)
    assert c.get('/auth/me',headers=auth(value)).status_code==401


def test_optional_resource_binding_exact_and_required_scopes(tmp_path,signing):
    settings=SecuritySettings(ISSUER,frozenset({'allowedclient'}),audience='https://resource.invalid',required_scopes=frozenset({'openid','reports/read'}))
    c=client(tmp_path,signing,settings)
    assert c.get('/auth/me',headers=auth(token(signing,aud='https://resource.invalid',scope='openid reports/read'))).status_code==200
    for changes in [{},{'aud':'https://resource.invalid'},{'aud':['https://resource.invalid'],'scope':'openid reports/read'}]:
        assert c.get('/auth/me',headers=auth(token(signing,**changes))).status_code==401


@pytest.mark.parametrize('groups,role',[(None,'Analyst'),([], 'Analyst'),(['users'],'Analyst'),('powerflow-admins','Analyst'),(['powerflow-admins',42],'Analyst'),(['powerflow-admins-evil'],'Analyst'),(['powerflow-admins'],'Admin')])
def test_roles_and_admin_guards_before_report_access(tmp_path,signing,groups,role):
    c=client(tmp_path,signing)
    headers=auth(token(signing,**{'cognito:groups':groups}))
    assert c.get('/auth/me',headers=headers).json()['role']==role
    for route in ['/admin/monitoring/forecast-vintages','/admin/monitoring/exogenous-readiness','/admin/models/linear-feature-influence','/admin/forecast/provenance','/monitoring/forecast-vintages','/monitoring/exogenous-readiness']:
        assert c.get(route).status_code==401
        assert c.get(route,headers=headers).status_code==(404 if role=='Admin' else 403)


def test_rotation_refresh_throttle_and_cache_expiration(signing):
    second=jwk.RSAKey.generate_key(2048,parameters={'kid':'key-two','alg':'RS256','use':'sig'})
    now=[0.0]; calls=[]; bundle=[{'keys':[public(signing)]}]
    def fetch(url):
        calls.append(url);return bundle[0]
    cache=JwksCache(SETTINGS.jwks_url,fetch=fetch,clock=lambda:now[0])
    assert cache.key(signing.kid)
    bundle[0]={'keys':[public(signing),public(second)]}
    assert cache.key(second.kid) and len(calls)==2
    for kid in ['unknown-one','unknown-two']:
        with pytest.raises(HTTPException) as error:cache.key(kid)
        assert error.value.status_code==401
    assert len(calls)==2
    now[0]=31
    with pytest.raises(HTTPException):cache.key('unknown-three')
    assert len(calls)==3
    now[0]=332;bundle[0]={'keys':[public(second)]}
    with pytest.raises(HTTPException) as error:cache.key(signing.kid)
    assert error.value.status_code==401 and len(calls)==4
    assert cache.key(second.kid)


def test_jwks_outage_no_stale_fallback_and_backoff(tmp_path,signing):
    now=[0.0];calls=[];fail=[False]
    def fetch(_url):
        calls.append(1)
        if fail[0]:raise httpx.ConnectError('private network detail')
        return {'keys':[public(signing)]}
    cache=JwksCache(SETTINGS.jwks_url,fetch=fetch,clock=lambda:now[0])
    cache.key(signing.kid);fail[0]=True;now[0]=301
    for _ in range(2):
        with pytest.raises(HTTPException) as error:cache.key(signing.kid)
        assert error.value.status_code==503 and 'private' not in error.value.detail
    assert len(calls)==2
    now[0]=307;fail[0]=False
    assert cache.key(signing.kid)
    c=client(tmp_path,signing,fetch=lambda _: {'keys':[]})
    assert c.get('/auth/me',headers=auth(token(signing))).status_code==503


def test_concurrent_cache_reads_fetch_once(signing):
    calls=[]
    cache=JwksCache(SETTINGS.jwks_url,fetch=lambda _:calls.append(1) or {'keys':[public(signing)]})
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:cache.key(signing.kid),range(16)))
    assert len(calls)==1


def test_http_jwks_fetch_bounded_timeout_and_no_redirects(signing):
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'keys':[public(signing)]}))
    real=httpx.Client
    with patch('api.security.httpx.Client',side_effect=lambda **kw:real(transport=transport,**kw)) as factory:
        assert fetch_jwks(SETTINGS.jwks_url)['keys']
        assert factory.call_args.kwargs['follow_redirects'] is False
        assert factory.call_args.kwargs['trust_env'] is False
        assert factory.call_args.kwargs['timeout'].connect==2
    oversized=httpx.MockTransport(lambda request:httpx.Response(200,content=b' '*65537))
    with patch('api.security.httpx.Client',side_effect=lambda **kw:real(transport=oversized,**kw)):
        with pytest.raises(ValueError):fetch_jwks(SETTINGS.jwks_url)


def test_missing_config_fails_closed_without_affecting_public_routes(tmp_path,monkeypatch):
    monkeypatch.delenv('POWERFLOW_API_COGNITO_ISSUER',raising=False)
    monkeypatch.delenv('POWERFLOW_API_COGNITO_CLIENT_IDS',raising=False)
    c=TestClient(create_app(APISettings.from_root(tmp_path)))
    assert c.get('/health').status_code==200
    assert c.get('/auth/me').status_code==401
    assert c.get('/auth/me',headers=auth('a.b.c')).status_code==503
    assert not (tmp_path/'database').exists()


def test_safe_admin_reports_exclude_raw_operational_information(tmp_path,signing):
    settings=APISettings.from_root(tmp_path)
    settings.forecast_vintage_health.parent.mkdir(parents=True)
    report={'generated_at_utc':'2026-10-21T00:00:00Z','overall_status':'HEALTHY','sources':[{'source':'OPEN_METEO','status':'HEALTHY','local_path':'private-path','reasons':['secret internal message'],'missing_target_count':0}],'credential':'never-public'}
    settings.forecast_vintage_health.write_text(json.dumps(report))
    readiness={'generated_at_utc':'2026-10-21T00:00:00Z','dataset_status':'NOT_READY','output_rows':0,'distinct_issue_cycles':0,'distinct_calendar_days':0,'complete_issue_cycles':0,'horizon_coverage_count':0,'leakage_check':{'passed':True},'dataset':'private-path'}
    settings.exogenous_readiness.write_text(json.dumps(readiness))
    before=settings.forecast_vintage_health.read_bytes()
    c=client(tmp_path,signing);headers=auth(token(signing,**{'cognito:groups':['powerflow-admins']}))
    for route in ['/admin/monitoring/forecast-vintages','/admin/monitoring/exogenous-readiness']:
        r=c.get(route,headers=headers)
        assert r.status_code==200 and r.headers['cache-control']=='no-store'
        assert all(value not in r.text for value in ['private-path','secret','never-public'])
    # Approved migration: deprecated aliases share the exact Admin boundary and allowlist.
    for suffix in ['forecast-vintages','exogenous-readiness']:
        legacy='/monitoring/'+suffix
        assert c.get(legacy).status_code==401
        assert c.get(legacy,headers=auth(token(signing))).status_code==403
        r=c.get(legacy,headers=headers)
        assert r.status_code==200 and r.json()==c.get('/admin'+legacy,headers=headers).json()
        assert all(value not in r.text for value in ['private-path','secret','never-public'])
    assert before==settings.forecast_vintage_health.read_bytes()
    settings.forecast_vintage_health.write_text('bad private text')
    r=c.get('/admin/monitoring/forecast-vintages',headers=headers)
    assert r.status_code==503 and 'private' not in r.text


def test_linear_report_admin_only_values_and_safe_provenance(tmp_path,signing):
    import csv
    from api.restricted_reports import LINEAR_FEATURES
    root=Path(__file__).resolve().parents[1]
    manifest=tmp_path/'artifacts/models/final_model_release_manifest.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes((root/'artifacts/models/final_model_release_manifest.json').read_bytes())
    report=tmp_path/'data/reports/feature_importance.csv'
    report.parent.mkdir(parents=True)
    with report.open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['feature','importance','signed_coefficient'])
        writer.writeheader()
        for i,feature in enumerate(sorted(LINEAR_FEATURES)):
            writer.writerow(dict(feature=feature,importance=i+.5,signed_coefficient=-(i+.5)))
    before=report.read_bytes()
    c=client(tmp_path,signing)
    headers=auth(token(signing,**{'cognito:groups':['powerflow-admins']}))
    path='/admin/models/linear-feature-influence'
    assert c.get(path,headers=auth(token(signing))).status_code==403
    result=c.get(path,headers=headers)
    assert result.status_code==200 and result.json()['feature_count']==31
    assert result.json()['features'][0]['importance']==30.5
    assert result.json()['features'][0]['signed_coefficient']==-30.5
    assert result.json()['horizon_hours']==1
    assert 'no report-to-artifact cryptographic binding' in result.json()['provenance']
    assert str(tmp_path) not in result.text
    assert before==report.read_bytes()
    report.write_text('feature,importance,signed_coefficient\nprivate-path,nan,99\n')
    result=c.get(path,headers=headers)
    assert result.status_code==503 and 'private-path' not in result.text


@pytest.mark.parametrize('bundle',[
 {'keys':[]}, {'keys':[{'kid':'bad','kty':'oct','alg':'HS256'}]},
 {'keys':[{'kid':'bad','kty':'RSA','alg':'RS256','use':'sig','n':'bad','e':'bad'}]},
])
def test_malformed_jwks_fail_closed(tmp_path,signing,bundle):
    c=client(tmp_path,signing,fetch=lambda _:bundle)
    r=c.get('/auth/me',headers=auth(token(signing)))
    assert r.status_code==503
    assert 'bad' not in r.text


def test_config_rejects_wildcards_unknown_hosts_and_missing_identity():
    for env in [{},{'POWERFLOW_API_COGNITO_ISSUER':'https://evil.invalid','POWERFLOW_API_COGNITO_CLIENT_IDS':'allowedclient'},
                {'POWERFLOW_API_COGNITO_ISSUER':ISSUER,'POWERFLOW_API_COGNITO_CLIENT_IDS':'*'}]:
        with pytest.raises(ValueError):SecuritySettings.from_environment(env)
    config=SecuritySettings.from_environment({'POWERFLOW_API_COGNITO_ISSUER':ISSUER,'POWERFLOW_API_COGNITO_CLIENT_IDS':'one,two','POWERFLOW_API_REQUIRED_SCOPES':'reports/read'})
    assert config.client_ids==frozenset({'one','two'})
    assert config.required_scopes==frozenset({'openid','reports/read'})
    assert config.jwks_url==ISSUER+'/.well-known/jwks.json'


def test_actual_linear_report_parity_without_unpickling_or_source_writes(tmp_path,signing):
    import csv
    import hashlib
    from api.restricted_reports import LINEAR_FEATURES
    from models.final_evaluation import FINAL_FEATURES
    assert LINEAR_FEATURES==frozenset(FINAL_FEATURES)
    root=Path(__file__).resolve().parents[1]
    report=root/'data/reports/feature_importance.csv'
    if not report.is_file():pytest.skip('No local persisted coefficient report')
    before=(report.stat().st_mtime_ns,hashlib.sha256(report.read_bytes()).hexdigest())
    with report.open() as handle:rows=list(csv.DictReader(handle))
    c=client(root,signing)
    with patch('joblib.load',side_effect=AssertionError('No model deserialization allowed')):
        r=c.get('/admin/models/linear-feature-influence',headers=auth(token(signing,**{'cognito:groups':['powerflow-admins']})))
    assert r.status_code==200
    actual={row['feature']:(float(row['importance']),float(row['signed_coefficient'])) for row in rows}
    assert {row['feature']:(row['importance'],row['signed_coefficient']) for row in r.json()['features']}==actual
    assert before==(report.stat().st_mtime_ns,hashlib.sha256(report.read_bytes()).hexdigest())


def test_duplicate_authorization_headers_rejected(tmp_path,signing):
    value=token(signing)
    r=client(tmp_path,signing).get('/auth/me',headers=[('Authorization','Bearer '+value),('Authorization','Bearer '+value)])
    assert r.status_code==401


@pytest.mark.parametrize('suffix,setting,payload,permitted_fields', [
    ('forecast-vintages', 'forecast_vintage_health', {
        'generated_at_utc': '2026-10-21T00:00:00Z',
        'overall_status': 'STALE',
        'sources': [{'source': 'OPEN_METEO', 'status': 'STALE',
                     'missing_target_count': 3, 'local_path': '/private/source',
                     'raw_incidents': ['not permitted']}],
        'internal_infrastructure': 'not permitted',
    }, {'generated_at_utc', 'overall_status', 'sources'}),
    ('exogenous-readiness', 'exogenous_readiness', {
        'generated_at_utc': '2026-10-21T00:00:00Z',
        'dataset_status': 'NOT_READY', 'distinct_issue_cycles': 0,
        'distinct_calendar_days': 0, 'complete_issue_cycles': 0,
        'horizon_coverage_count': 0, 'output_rows': 0,
        'duplicate_key_count': 0, 'leakage_check': {'passed': False,
                                                  'internal_details': 'not permitted'},
        'dataset': '/private/dataset', 'raw_incidents': ['not permitted'],
    }, {'generated_at_utc', 'dataset_status', 'distinct_issue_cycles',
        'distinct_calendar_days', 'complete_issue_cycles',
        'horizon_coverage_count', 'output_rows', 'duplicate_key_count',
        'leakage_check_passed'}),
])
def test_legacy_monitoring_exact_admin_boundary_and_field_allowlists(
        tmp_path, signing, suffix, setting, payload, permitted_fields):
    """Deprecated URLs must never become an alternate public/raw report path."""
    from api.security import require_admin
    settings = APISettings.from_root(tmp_path)
    path = getattr(settings, setting)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    c = client(tmp_path, signing)
    legacy = '/monitoring/' + suffix
    protected = '/admin' + legacy
    routes = {route.path: route for route in c.app.routes if hasattr(route, 'dependencies')}
    assert routes[legacy].response_model is routes[protected].response_model
    assert routes[legacy].dependencies[0].dependency is require_admin
    assert routes[protected].dependencies[0].dependency is require_admin
    assert routes[legacy].deprecated is True

    assert c.get(legacy).status_code == 401
    assert c.get(legacy, headers=auth(token(signing))).status_code == 403
    admin = auth(token(signing, **{'cognito:groups': ['powerflow-admins']}))
    response = c.get(legacy, headers=admin)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    data = response.json()
    assert data == c.get(protected, headers=admin).json()
    assert set(data) == permitted_fields
    assert '/private/' not in response.text and 'not permitted' not in response.text
    if suffix == 'forecast-vintages':
        assert set(data['sources'][0]) == {
            'source', 'status', 'latest_acquired_at_utc',
            'expected_target_count', 'observed_target_count',
            'missing_target_count', 'duplicate_identity_count', 'revision_count',
            'consecutive_collection_failures', 's3_sync_status',
        }
        assert data['sources'][0]['missing_target_count'] == 3
    else:
        assert data['duplicate_key_count'] == 0
        assert data['leakage_check_passed'] is False
    assert path.read_bytes() == before
