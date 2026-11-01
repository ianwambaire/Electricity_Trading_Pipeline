"""Explicit-origin, read-only staging acceptance. No browser/credentials are automated.

Tokens are prompted in the owner's TTY only; never argv/files/logs. Does not follow
redirects or retry. Run only after approval for the named deployment origin.
"""
import argparse
import getpass
import math
from datetime import datetime, timedelta, timezone
import json
import sys
import time
from urllib.parse import urlparse
import httpx

PAGES = ('/', '/analytics', '/forecasting', '/anomalies', '/models', '/pipeline', '/profile')
ADMIN = ('/admin/operations', '/admin/forecast/provenance', '/admin/models/linear-feature-influence',
         '/admin/monitoring/forecast-vintages', '/admin/monitoring/exogenous-readiness',
         '/monitoring/forecast-vintages', '/monitoring/exogenous-readiness')


PROVENANCE = '/admin/forecast/provenance'
PUBLICATION_STATES = ('VALID', 'EXPIRED', 'WITHHELD', 'MISSING_PUBLICATION', 'HISTORICAL')
CHANGED_DETAIL = 'The forecast changed. Refresh the forecast before requesting its evidence.'


def stamp(value):
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    assert parsed.tzinfo is not None
    return parsed.astimezone(timezone.utc)


def withheld(response):
    assert response.status_code == 503
    assert response.json() == {'detail': {'code': 'FORECAST_WITHHELD'}}
    assert 'no-store' in response.headers.get('cache-control', '')


def valid_forecast(response, now=None):
    assert response.status_code == 200 and 'no-store' in response.headers.get('cache-control', '')
    data = response.json()
    publication = data['publication']
    assert publication['status'] == 'VALID' and data['row_count'] == len(data['forecasts']) == 24
    issue, completed = stamp(publication['issue_time']), stamp(publication['completed_at'])
    assert stamp(publication['expires_at']) == issue + timedelta(hours=3)
    assert issue < completed <= stamp(publication['expires_at'])
    now = now or datetime.now(timezone.utc)
    assert issue <= now <= stamp(publication['expires_at']) and completed <= now
    for horizon, row in enumerate(data['forecasts'], 1):
        assert stamp(row['issue_time']) == issue and type(row['horizon_hours']) is int and row['horizon_hours'] == horizon
        assert stamp(row['target_time']) == issue + timedelta(hours=horizon)
        assert type(row['predicted_price_eur_mwh']) in (int, float) and math.isfinite(row['predicted_price_eur_mwh'])
        assert isinstance(row['model_release'], str) and row['model_release'] == data['forecasts'][0]['model_release'] and row['model_release']
    return data


def verify(client, analyst, admin, *, expected_publication, previous_issue=None, previous_completed=None, now=None):
    assert expected_publication in PUBLICATION_STATES
    changed = previous_issue is not None or previous_completed is not None
    assert not changed or (expected_publication == 'VALID' and previous_issue is not None and previous_completed is not None)
    for path in (*PAGES, '/auth/callback'):
        response = client.get(path)
        assert response.status_code == 200 and 'text/html' in response.headers.get('content-type', '')
        assert '<div id="root"' in response.text
    assert client.get('/api/health').status_code == 200
    assert client.get('/api/ready').status_code == 404
    for path in ADMIN:
        # Never let report absence, expiry or source changes excuse authorization.
        assert client.get('/api'+path).status_code == 401
        assert client.get('/api'+path, headers={'Authorization':'Bearer '+analyst}).status_code == 403
        if path != PROVENANCE:
            assert client.get('/api'+path, headers={'Authorization':'Bearer '+admin}).status_code in (200,404)
    for value, role in ((analyst,'Analyst'), (admin,'Admin')):
        response = client.get('/api/auth/me', headers={'Authorization':'Bearer '+value})
        assert response.status_code == 200 and response.json()['role'] == role
    for path in ('/market/coverage','/models/summary','/pipeline/status'):
        assert client.get('/api'+path).status_code == 200
    forecast = client.get('/api/forecast/next24')
    summary_response = client.get('/api/operations/summary')
    assert summary_response.status_code == 200
    summary = summary_response.json()
    if expected_publication != 'HISTORICAL':
        assert summary['forecast_status'] == expected_publication
        assert summary['health'] in ('Historical snapshot', 'Unavailable')
        assert 'Historical' in summary['completeness_note']
        assert 'publication' in summary['forecast_reason_provenance'].lower()
    if expected_publication == 'VALID':
        data = valid_forecast(forecast, now)
        publication = data['publication']
        pin = {'issue_time': previous_issue or publication['issue_time'], 'completed_at': previous_completed or publication['completed_at']}
        if changed:
            assert (stamp(previous_issue), stamp(previous_completed)) != (stamp(publication['issue_time']), stamp(publication['completed_at']))
        evidence = client.get('/api'+PROVENANCE, params=pin, headers={'Authorization':'Bearer '+admin})
        if changed:
            assert evidence.status_code == 409 and evidence.json() == {'detail': CHANGED_DETAIL}
            assert 'no-store' in evidence.headers.get('cache-control', '')
        else:
            assert evidence.status_code == 200 and 'no-store' in evidence.headers.get('cache-control', '')
            body = evidence.json()
            assert stamp(body['issue_time']) == stamp(publication['issue_time'])
            assert body['issuance_evidence'] == body['provenance_evidence'] == 'available'
            assert stamp(publication['issue_time']) <= stamp(body['weather_acquired_at_utc']) <= stamp(body['issued_at_utc']) <= stamp(publication['completed_at'])
        assert stamp(publication['issue_time']).isoformat() in summary['forecast_reason']
        assert stamp(publication['expires_at']).isoformat() in summary['forecast_reason']
    elif expected_publication == 'HISTORICAL':
        assert forecast.status_code in (200,404)
        if forecast.status_code == 200: assert 'publication' not in forecast.json()
        evidence = client.get('/api'+PROVENANCE, headers={'Authorization':'Bearer '+admin})
        assert evidence.status_code in (200,404)
        assert 'Historical' in summary['completeness_note']
    else:
        withheld(forecast)
        evidence = client.get('/api'+PROVENANCE, headers={'Authorization':'Bearer '+admin})
        withheld(evidence)
    return {'status':'passed', 'pages':len(PAGES), 'analyst_admin_denials':len(ADMIN),
            'publication_state':expected_publication, 'forecast_status':forecast.status_code,
            'provenance_status':evidence.status_code, 'manual_browser_acceptance':'required',
            'scope':'Read-only acceptance, not proof of inference or live operational health'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',required=True)
    parser.add_argument('--expected-publication', choices=PUBLICATION_STATES, required=True)
    parser.add_argument('--previous-issue', help='Explicit stale public issue timestamp for a separately approved 409 check')
    parser.add_argument('--previous-completed', help='Matching stale public completion timestamp; no token or credential')
    args=parser.parse_args()
    url=urlparse(args.origin)
    if url.scheme!='https' or url.netloc!='staging.powerflowenergy.dev' or url.path or url.query or url.fragment:
        parser.error('Only https://staging.powerflowenergy.dev is approved by this template')
    if not sys.stdin.isatty():parser.error('Owner interactive terminal required')
    analyst=getpass.getpass('Native Analyst access token (local terminal only): ')
    admin=getpass.getpass('Google Admin access token (local terminal only): ')
    try:
        with httpx.Client(base_url=args.origin,timeout=10,follow_redirects=False,trust_env=False, event_hooks={'request':[lambda _: time.sleep(0.25)]}) as client:
            result=verify(client,analyst,admin,expected_publication=args.expected_publication,previous_issue=args.previous_issue,previous_completed=args.previous_completed)
        print(json.dumps(result));return 0
    except Exception:
        print('{"status":"failed","detail":"Acceptance failed; no response bodies or credentials logged"}');return 1
    finally:analyst=admin=None


if __name__=='__main__':raise SystemExit(main())
