"""Read-only, loopback-only Vite/FastAPI preflight. Never a live authentication test."""
import csv,json,hashlib
from pathlib import Path
import httpx
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--snapshot',type=Path,required=True)
args=parser.parse_args()
root=args.snapshot.resolve()
admin=['/admin/operations','/admin/forecast/provenance','/admin/models/linear-feature-influence','/admin/monitoring/forecast-vintages','/admin/monitoring/exogenous-readiness','/monitoring/forecast-vintages','/monitoring/exogenous-readiness']
with httpx.Client(base_url='http://127.0.0.1:4174/api',timeout=20) as c:
    statuses={}
    for p in ['/health','/market/coverage','/market/history','/market/summary','/market/chart','/market/exploration','/anomalies/summary','/anomalies/events','/models/summary','/pipeline/status','/operations/summary','/forecast/one-hour','/forecast/next24','/forecast/realized-evaluation','/docs','/market/history?limit=2001','/market/history?start=bad',*admin]:
        r=c.get(p);statuses[p]=r.status_code
        assert r.headers.get('cache-control')=='no-store'
    assert all(statuses[p]==401 for p in admin)
    assert c.get('/account/profile').status_code==401
    assert c.get('/admin/operations',headers={'Authorization':'Bearer intentionally-invalid-test-value'}).status_code==401
    coverage=c.get('/market/coverage').json();summary=c.get('/market/summary').json();historical=c.get('/forecast/one-hour').json()
    with (root/'data/processed/silver_electricity_market_data.csv').open() as f:rows=list(csv.DictReader(f))
    assert coverage['row_count']==len(rows)
    assert summary['latest_observation']['price_eur_mwh']==float(rows[-1]['price_eur_mwh'])
    with (root/'data/reports/actual_vs_predicted.csv').open() as f:prediction_rows=list(csv.DictReader(f))
    assert historical['row_count']==len(prediction_rows)
    expected={'/forecast/next24':404,'/forecast/realized-evaluation':404,'/docs':404,'/market/history?limit=2001':422,'/market/history?start=bad':422}
    assert all(statuses[p]==s for p,s in expected.items())
    assert c.get('/__fixtures/forecast/realized-evaluation').json()['releases'][0]['overall']['mae']==1
manifest=json.loads((root/'preflight-manifest.json').read_text())
assert all(hashlib.sha256((root/p).read_bytes()).hexdigest()==v['sha256'] for p,v in manifest['files'].items())
print(json.dumps({'scope':'local Vite-to-FastAPI TCP proxy; no real OIDC; snapshot matches copied persisted values','statuses':statuses,'market_rows':len(rows),'latest_price':summary['latest_observation']['price_eur_mwh'],'historical_predictions':historical['row_count'],'snapshot_digests_unchanged':True},indent=2))
