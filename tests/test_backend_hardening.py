"""Production boundaries with synthetic data only. No network, AWS or accounts."""
import json
import logging
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import APISettings, create_app
from api.database import read_snapshot
from api.readiness import Readiness
from api.runtime import RuntimeSettings
from api.security import SecuritySettings
from test_api_security import SETTINGS


def database(root):
    path = root / 'database/electricity_trading.db'
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as c:
        c.executescript((Path(__file__).parents[1] / 'database/schema.sql').read_text())
    return path


def deployed(root, origins=()):
    return create_app(APISettings.from_root(root), security_settings=SETTINGS,
                      runtime_settings=RuntimeSettings('staging', ('api.example.test',), origins))


@pytest.mark.parametrize('env', [
    {'POWERFLOW_API_ENV': 'typo'},
    {'POWERFLOW_API_ENV': 'production'},
    {'POWERFLOW_API_ENV': 'production', 'POWERFLOW_API_ALLOWED_HOSTS': '*'},
    {'POWERFLOW_API_ENV': 'staging', 'POWERFLOW_API_ALLOWED_HOSTS': 'https://api.example.test'},
    {'POWERFLOW_API_ENV': 'staging', 'POWERFLOW_API_ALLOWED_HOSTS': 'api.example.test', 'POWERFLOW_API_CORS_ORIGINS': '*'},
])
def test_invalid_runtime_configuration_stops_startup(tmp_path, monkeypatch, env):
    for key in ['POWERFLOW_API_ENV','POWERFLOW_API_ALLOWED_HOSTS','POWERFLOW_API_CORS_ORIGINS']:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        create_app(APISettings.from_root(tmp_path), security_settings=SETTINGS)


def test_production_identity_configuration_is_mandatory(tmp_path, monkeypatch):
    monkeypatch.delenv('POWERFLOW_API_COGNITO_ISSUER', raising=False)
    monkeypatch.delenv('POWERFLOW_API_COGNITO_CLIENT_IDS', raising=False)
    with pytest.raises(ValueError, match='identity configuration'):
        create_app(APISettings.from_root(tmp_path), runtime_settings=RuntimeSettings('production', ('api.example.test',)))
    # Explicit development remains backwards compatible: public health, closed auth.
    app=create_app(APISettings.from_root(tmp_path), runtime_settings=RuntimeSettings())
    c=TestClient(app)
    assert c.get('/health').status_code==200
    assert c.get('/auth/me',headers={'Authorization':'Bearer fixture'}).status_code==503


def test_cross_region_issuer_and_unapproved_deployed_enrollment_rejected(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        SecuritySettings('https://cognito-idp.us-east-1.amazonaws.com/us-west-2_TestPool', frozenset({'fixture'}))
    monkeypatch.setenv('POWERFLOW_ACCOUNT_TOTP_ENABLED','true')
    with pytest.raises(ValueError,match='not released'):
        deployed(tmp_path)


def test_host_and_cors_exact_allowlist_and_no_public_documentation(tmp_path):
    c=TestClient(deployed(tmp_path, ('https://app.example.test',)),base_url='https://api.example.test')
    for path in ['/docs','/redoc','/openapi.json']:
        assert c.get(path).status_code==404
    assert c.get('/health',headers={'Host':'evil.example.test'}).status_code==400
    assert c.get('/health',headers={'Host':'api.example.test.evil.test'}).status_code==400
    assert c.get('/health',headers={'X-Forwarded-Host':'evil.example.test'}).status_code==200
    ok=c.options('/account/profile', headers={'Origin':'https://app.example.test','Access-Control-Request-Method':'PATCH','Access-Control-Request-Headers':'Authorization,Content-Type'})
    assert ok.status_code==200 and ok.headers['access-control-allow-origin']=='https://app.example.test'
    assert 'access-control-allow-credentials' not in ok.headers
    denied=c.options('/account/profile',headers={'Origin':'https://evil.example.test','Access-Control-Request-Method':'PATCH'})
    assert denied.status_code==400 and 'access-control-allow-origin' not in denied.headers
    assert 'access-control-allow-origin' not in c.get('/health',headers={'Origin':'https://evil.example.test'}).headers


@pytest.mark.parametrize('origin', ['http://app.example.test','https://app.example.test/','https://a:b@app.example.test','https://app.example.test?key=private','null'])
def test_invalid_deployed_cors_origins_rejected(origin):
    with pytest.raises(ValueError):RuntimeSettings('production', ('api.example.test',), (origin,))


def test_readiness_not_liveness_or_forecast_freshness(tmp_path):
    app=deployed(tmp_path)
    c=TestClient(app,base_url='https://api.example.test')
    assert c.get('/health').status_code==200
    missing=c.get('/ready')
    assert missing.status_code==503
    assert missing.json()['checks']['operational_database']=='unavailable'
    assert str(tmp_path) not in missing.text
    assert not (tmp_path/'database').exists()
    database(tmp_path)
    app.state.readiness=Readiness(APISettings.from_root(tmp_path))
    ready=c.get('/ready')
    assert ready.status_code==200
    assert ready.json()['data_freshness']=='not_assessed'
    assert ready.json()['provider_connectivity']=='not_assessed'
    assert c.get('/forecast/next24').status_code==404
    assert ready.headers['cache-control']=='no-store'
    # An identity outage cannot be hidden by the DB readiness cache.
    app.state.cognito_verifier=None
    assert c.get('/ready').status_code==503


def test_readiness_schema_corruption_cache_and_recovery(tmp_path):
    path=database(tmp_path); now=[1.0]
    checker=Readiness(APISettings.from_root(tmp_path),clock=lambda:now[0])
    assert checker.check(True)['status']=='ready'
    with sqlite3.connect(path) as db:db.execute('DROP TABLE pipeline_runs')
    assert checker.check(True)['status']=='ready' # Bounded five-second cache.
    now[0]+=6
    assert checker.check(True)['status']=='not_ready'
    path.write_bytes(b'invalid database, private path')
    now[0]+=6
    assert checker.check(True)['status']=='not_ready'


def test_error_and_validation_sanitization_correlation_and_logs(tmp_path, caplog):
    app=deployed(tmp_path)
    @app.get('/fixture-failure')
    def failure():raise ValueError('password=private-fixture code=123456 /private/path')
    c=TestClient(app,base_url='https://api.example.test')
    with caplog.at_level(logging.INFO,logger='powerflow.api'):
        bad=c.get('/fixture-failure?token=private-query',headers={'Authorization':'Bearer private-token','X-Request-ID':'private-id'})
        invalid=c.get('/market/history?start=private-input')
        unknown=c.get('/unmatched-private-path')
        unauth=c.get('/admin/operations')
    assert bad.status_code==500
    assert len(bad.headers['x-request-id'])==32 and bad.json()['request_id']==bad.headers['x-request-id']
    assert invalid.status_code==422 and invalid.json()=={'detail':'Invalid request parameters.'}
    assert unauth.status_code==401
    text=caplog.text+bad.text+invalid.text+unknown.text
    for private in ['private-fixture','123456','/private/path','private-query','private-token','private-id','private-input','unmatched-private-path']:
        assert private not in text
    records=[json.loads(r.message) for r in caplog.records if r.name=='powerflow.api']
    assert any(r.get('access')=='rejected' for r in records)
    assert len({r['request_id'] for r in records if r['event']=='http_request'})==4
    assert all(r['route']!='private-input' for r in records if r['event']=='http_request')


def test_snapshot_is_read_only_consistent_and_releases_locks(tmp_path):
    path=database(tmp_path)
    before=path.read_bytes()
    with read_snapshot(path) as db:
        assert db.execute('PRAGMA query_only').fetchone()[0]==1
        with pytest.raises(sqlite3.OperationalError):db.execute('DROP TABLE pipeline_runs')
    assert path.read_bytes()==before
    with sqlite3.connect(path) as writer:writer.execute('INSERT INTO pipeline_runs(run_time,status) VALUES (?,?)',('2026-10-22T00:00:00+00:00','SUCCESS'))
    def read(_):
        with read_snapshot(path) as db:return db.execute('SELECT COUNT(*) FROM pipeline_runs').fetchone()[0]
    with ThreadPoolExecutor(max_workers=8) as pool:assert list(pool.map(read,range(20)))==[1]*20


def test_lock_failure_is_bounded_and_recovers_without_creating_database(tmp_path):
    path=database(tmp_path);app=deployed(tmp_path)
    c=TestClient(app,base_url='https://api.example.test')
    writer=sqlite3.connect(path)
    try:
        writer.execute('BEGIN EXCLUSIVE')
        start=time.monotonic()
        response=c.get('/pipeline/status')
        assert response.status_code==503 and time.monotonic()-start<2
        assert str(path) not in response.text
    finally:writer.rollback();writer.close()
    # Empty persisted history remains a real missing-data state, not a DB error.
    assert c.get('/pipeline/status').status_code==404


def test_lifespan_closes_snapshot_and_logs_only_fixed_events(tmp_path,caplog):
    app=deployed(tmp_path)
    with caplog.at_level(logging.INFO,logger='powerflow.api'):
        with TestClient(app,base_url='https://api.example.test') as c:
            assert c.get('/health').status_code==200
    events=[json.loads(r.message)['event'] for r in caplog.records if r.name=='powerflow.api']
    assert 'application_started' in events and 'application_stopped' in events


def test_deployed_environment_requires_absolute_published_root(monkeypatch):
    monkeypatch.setenv('POWERFLOW_API_ENV','staging')
    monkeypatch.setenv('POWERFLOW_API_ALLOWED_HOSTS','api.example.test')
    monkeypatch.delenv('POWERFLOW_API_DATA_ROOT',raising=False)
    with pytest.raises(ValueError,match='absolute published data root'):create_app(security_settings=SETTINGS)
    monkeypatch.setenv('POWERFLOW_API_DATA_ROOT','relative/private')
    with pytest.raises(ValueError,match='absolute published data root'):create_app(security_settings=SETTINGS)


def test_staging_template_has_isolated_runtime_and_no_general_enrollment():
    root=Path(__file__).parents[1]
    unit=(root/'deploy/staging/powerflow-api.service').read_text()
    env=(root/'deploy/staging/api.env.example').read_text()
    assert 'User=powerflow-api' in unit and 'User=root' not in unit
    assert '--workers 1' in unit and '--host 127.0.0.1' in unit and '--no-access-log' in unit
    assert '/.venv-api/' in unit and '/.venv-prod/' not in unit
    assert 'EnvironmentFile=/etc/powerflow/api.env' in unit
    assert 'ProtectSystem=strict' in unit and 'ReadOnlyPaths=/srv/powerflow/published' in unit
    assert 'POWERFLOW_ACCOUNT_TOTP_ENABLED=false' in env
    assert 'POWERFLOW_API_ENV=staging' in env


def test_sanitized_failure_retains_only_explicit_cors_policy(tmp_path):
    app=deployed(tmp_path,('https://app.example.test',))
    @app.get('/failure')
    def failed():raise RuntimeError('private-fixture')
    c=TestClient(app,base_url='https://api.example.test')
    response=c.get('/failure',headers={'Origin':'https://app.example.test'})
    assert response.status_code==500 and 'private-fixture' not in response.text
    assert response.headers['access-control-allow-origin']=='https://app.example.test'
    assert 'x-request-id' in response.headers
