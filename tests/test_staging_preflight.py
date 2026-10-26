"""Local preflight guardrails. No AWS, production requests or account mutations."""
import hashlib
import importlib.util
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest
from preflight_server import build, fixture_data

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('prepare_preflight_data',ROOT/'scripts/prepare_preflight_data.py')
snapshot=importlib.util.module_from_spec(spec);spec.loader.exec_module(snapshot)


def test_snapshot_allowlists_files_and_uses_consistent_local_database(tmp_path):
    source=tmp_path/'source';source.mkdir();fixture_data(source/'inputs',tmp_path/'absent')
    source=source/'inputs';(source/'.env').write_text('not copied');(source/'private.txt').write_text('not copied')
    before=hashlib.sha256((source/'database/electricity_trading.db').read_bytes()).hexdigest()
    destination=tmp_path/'snapshot';result=snapshot.prepare(source,destination)
    assert result['database_snapshot']
    assert not (destination/'.env').exists() and not (destination/'private.txt').exists()
    assert before==hashlib.sha256((source/'database/electricity_trading.db').read_bytes()).hexdigest()
    with sqlite3.connect(destination/'database/electricity_trading.db') as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT COUNT(*) FROM pipeline_runs').fetchone()[0]==1
    with pytest.raises(FileExistsError):snapshot.prepare(source,destination)
    with pytest.raises(ValueError):snapshot.prepare(source,source/'nested')


def test_preflight_main_auth_remains_closed_and_synthetic_surface_is_read_only(tmp_path):
    source=tmp_path/'source';fixture_data(source,tmp_path/'absent')
    actual=tmp_path/'snapshot';snapshot.prepare(source,actual)
    app=build(actual,tmp_path/'fixture')
    with TestClient(app) as client:
        assert client.get('/health').status_code==200
        assert client.get('/ready').json()['data_freshness']=='not_assessed'
        assert client.get('/docs').status_code==404
        for path in ['/admin/operations','/admin/forecast/provenance','/admin/models/linear-feature-influence','/admin/monitoring/forecast-vintages','/admin/monitoring/exogenous-readiness','/monitoring/forecast-vintages','/monitoring/exogenous-readiness','/account/profile']:
            assert client.get(path).status_code==401
        report=client.get('/__fixtures/forecast/next24')
        assert report.status_code==200 and report.json()['row_count']==24
        assert {r['model_release'] for r in report.json()['forecasts']}=={'fixture-not-a-trained-release'}
        assert client.get('/__fixtures/admin/operations').json()['timing_summary']['latest_total_seconds']==2.5
        evaluation=client.get('/__fixtures/forecast/realized-evaluation')
        assert evaluation.status_code==200
        assert evaluation.json()['releases'][0]['overall']['pair_count']==24
        assert evaluation.json()['releases'][0]['overall']['mae']==1
        for method in ['post','patch','delete','put']:
            assert getattr(client,method)('/__fixtures/account/profile').status_code==405
        assert app.state.account_totp_enabled is False
        assert client.get('/health',headers={'Host':'untrusted.example'}).status_code==400


def test_deployment_proposals_preserve_isolation_and_explicit_client_permissions():
    """Static guardrails only: NOT an Nginx/systemd/Linux deployment test."""
    import json
    proposal=ROOT/'deploy/preflight'
    client=json.loads((proposal/'cognito-production-client.json').read_text())
    assert client['GenerateSecret'] is False
    assert client['AllowedOAuthFlows']==['code']
    assert set(client['SupportedIdentityProviders'])=={'COGNITO','Google'}
    assert set(client['WriteAttributes'])=={'email','name','preferred_username'}
    assert set(client['ReadAttributes'])=={'email','email_verified','identities','name','preferred_username','sub'}
    assert client['CallbackURLs']==['https://powerflowenergy.dev/auth/callback']
    assert client['LogoutURLs']==['https://powerflowenergy.dev/']
    nginx=(proposal/'powerflowenergy.dev.conf').read_text()
    assert 'proxy_pass http://127.0.0.1:8010/;' in nginx
    assert '$proxy_add_x_forwarded_for' not in nginx
    assert 'proxy_set_header X-Forwarded-For $remote_addr;' in nginx
    assert 'try_files $uri =404;' in nginx
    assert 'ready|docs|redoc|openapi' in nginx
    assert 'proxy_intercept_errors off;' in nginx
    log=(proposal/'nginx-http.conf').read_text()
    assert all(value not in log for value in ('$request_uri','$args','$http_authorization','$request_body'))
    service=(proposal/'powerflow-react-api.service').read_text()
    assert 'User=powerflow-api' in service and '--port 8010 --workers 1' in service
    assert 'ProtectSystem=strict' in service and 'MemoryMax=512M' in service
    assert 'POWERFLOW_ACCOUNT_TOTP_ENABLED=false' in (proposal/'api.env.example').read_text()
