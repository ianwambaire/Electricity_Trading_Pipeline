"""Explicit-origin, read-only staging acceptance. No browser/credentials are automated.

Tokens are prompted in the owner's TTY only; never argv/files/logs. Does not follow
redirects or retry. Run only after approval for the named deployment origin.
"""
import argparse
import getpass
import json
import sys
import time
from urllib.parse import urlparse
import httpx

PAGES = ('/', '/analytics', '/forecasting', '/anomalies', '/models', '/pipeline', '/profile')
ADMIN = ('/admin/operations', '/admin/forecast/provenance', '/admin/models/linear-feature-influence',
         '/admin/monitoring/forecast-vintages', '/admin/monitoring/exogenous-readiness',
         '/monitoring/forecast-vintages', '/monitoring/exogenous-readiness')


def verify(client, analyst, admin):
    for path in (*PAGES, '/auth/callback'):
        response = client.get(path)
        assert response.status_code == 200 and 'text/html' in response.headers.get('content-type', '')
        assert '<div id="root"' in response.text
    assert client.get('/api/health').status_code == 200
    assert client.get('/api/ready').status_code == 404
    for path in ADMIN:
        assert client.get('/api'+path).status_code == 401
        assert client.get('/api'+path, headers={'Authorization':'Bearer '+analyst}).status_code == 403
        # A legitimate missing report may be 404; permission must not be denied.
        assert client.get('/api'+path, headers={'Authorization':'Bearer '+admin}).status_code in (200,404)
    for token, role in ((analyst,'Analyst'), (admin,'Admin')):
        response=client.get('/api/auth/me', headers={'Authorization':'Bearer '+token})
        assert response.status_code == 200
        assert response.json()['role'] == role
    for path in ('/market/coverage','/models/summary','/pipeline/status'):
        assert client.get('/api'+path).status_code == 200
    forecast=client.get('/api/forecast/next24')
    assert forecast.status_code in (200,404,503)
    return {'status':'passed','pages':len(PAGES),'analyst_admin_denials':len(ADMIN),
            'forecast_status':forecast.status_code,'manual_browser_acceptance':'required'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',required=True)
    args=parser.parse_args()
    url=urlparse(args.origin)
    if url.scheme!='https' or url.netloc!='staging.powerflowenergy.dev' or url.path or url.query or url.fragment:
        parser.error('Only https://staging.powerflowenergy.dev is approved by this template')
    if not sys.stdin.isatty():parser.error('Owner interactive terminal required')
    analyst=getpass.getpass('Native Analyst access token (local terminal only): ')
    admin=getpass.getpass('Google Admin access token (local terminal only): ')
    try:
        with httpx.Client(base_url=args.origin,timeout=10,follow_redirects=False,trust_env=False, event_hooks={'request':[lambda _: time.sleep(0.25)]}) as client:
            result=verify(client,analyst,admin)
        print(json.dumps(result));return 0
    except Exception:
        print('{"status":"failed","detail":"Acceptance failed; no response bodies or credentials logged"}');return 1
    finally:analyst=admin=None


if __name__=='__main__':raise SystemExit(main())
