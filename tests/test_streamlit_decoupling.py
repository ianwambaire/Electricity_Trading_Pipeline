"""Cold-process dependency boundary and sampled-gap parity; local fixtures only."""
import csv
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys

import pytest

from api.market_data import MarketStore, VALUE_FIELDS, WEATHER_FIELDS, market_chart
from api.feature_parity import market_exploration


def observations(path, hours):
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['timestamp', *VALUE_FIELDS, *WEATHER_FIELDS])
        writer.writeheader()
        for i in hours:
            row = dict.fromkeys([*VALUE_FIELDS, *WEATHER_FIELDS], 1)
            row.update(timestamp=(start + timedelta(hours=i)).isoformat(), price_eur_mwh=(i % 7) - 3)
            if i % 11 == 0:
                row['price_eur_mwh'] = row['temperature_2m'] = None
            writer.writerow(row)
    return start


@pytest.mark.parametrize('kind', ['price', 'weather'])
@pytest.mark.parametrize('bounded', [False, True])
def test_sampled_gap_flags_match_full_source_without_per_point_queries(tmp_path, kind, bounded):
    hours = [i for i in range(160) if i not in {9, 10, 29, 30, 31, 69, 100}]
    source = tmp_path / 'silver.csv'
    start = observations(source, hours)
    store = MarketStore(source)
    try:
        store.coverage()  # exclude one-time index construction from request query count
        queries = []
        store._connection.set_trace_callback(queries.append)
        a, b = (start + timedelta(hours=15), start + timedelta(hours=120)) if bounded else (None, None)
        if kind == 'price':
            points = market_chart(store, a, b, 12).points
        else:
            points = market_exploration(store, a, b, 12).weather
        assert len(queries) == 2  # range count + bounded sampling, independent of point count
        assert len(points) <= 12
        for i, point in enumerate(points):
            if i == 0:
                expected = False
            else:
                previous = int((points[i-1].timestamp - start).total_seconds() // 3600)
                current = int((point.timestamp - start).total_seconds() // 3600)
                expected = any(h not in hours for h in range(previous+1, current))
            assert point.gap_before is expected
    finally:
        store.close()


def test_data_backed_api_routes_do_not_import_ui_or_inference_packages(tmp_path):
    # A fresh process prevents pre-imported Streamlit/model packages hiding coupling.
    root = Path(__file__).parents[1]
    script = r'''
import csv, importlib.abc, json, sqlite3, sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'streamlit','sklearn','joblib','mlflow','prefect','boto3','processing'}:
            raise AssertionError('Unexpected runtime dependency: '+fullname)
sys.meta_path.insert(0, Block())
from api.app import APISettings, create_app
from api.market_data import VALUE_FIELDS, WEATHER_FIELDS
from shared.forecast_evaluation import summarize_realized_performance
from shared.operational_health import source_freshness_state
from fastapi.testclient import TestClient
root=Path(sys.argv[1]); settings=APISettings.from_root(root)
start=datetime(2026,1,1,tzinfo=timezone.utc)
settings.market_silver.parent.mkdir(parents=True)
with settings.market_silver.open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['timestamp',*VALUE_FIELDS,*WEATHER_FIELDS]); w.writeheader()
    for i in range(168):
        row=dict.fromkeys([*VALUE_FIELDS,*WEATHER_FIELDS],1)
        row.update(timestamp=(start+timedelta(hours=i)).isoformat(),price_eur_mwh=i)
        w.writerow(row)
raw=root/'data/raw/entsoe/prices.csv';raw.parent.mkdir(parents=True)
with raw.open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['timestamp','price_eur_mwh'])
    for i in range(168):w.writerow([(start+timedelta(hours=i)).isoformat(),i])
report=root/'data/reports/next24h_realized_errors.csv';report.parent.mkdir(parents=True)
fields=['forecast_issue_time','target_timestamp','issued_at_utc','horizon_hours','model_release','predicted_price_eur_mwh','actual_price_eur_mwh','absolute_error','squared_error','signed_error']
with report.open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    for i in range(20):
        issue=start+timedelta(hours=i)
        w.writerow(dict(zip(fields,[issue.isoformat(),(issue+timedelta(hours=1)).isoformat(),issue.isoformat(),1,'test-release',2,1,1,1,1])))
with TestClient(create_app(settings)) as c:
    for path in ['/market/summary','/market/chart','/market/exploration','/market/price-comparison','/operations/summary','/forecast/realized-evaluation','/forecast/context?issue_time=2026-01-07T23:00:00Z']:
        r=c.get(path); assert r.status_code==200,(path,r.status_code,r.text)
    context=c.get('/forecast/context?issue_time=2026-01-07T23:00:00Z').json()
    assert context['price_rolling_mean_24h']==155.5 and context['price_average_7d']==83.5
    assert c.get('/forecast/realized-evaluation').json()['releases'][0]['overall']['mae']==1
    assert c.get('/forecast/next24').status_code==404
    assert c.get('/admin/operations').status_code==401
assert source_freshness_state(start,source_kind='silver')=='Historical dataset'
assert not any(k.split('.')[0] in {'streamlit','sklearn','joblib','prefect','mlflow','boto3','processing'} for k in sys.modules)
'''
    env = {k:v for k,v in os.environ.items() if not k.startswith('POWERFLOW_')}
    env['PYTHONPATH'] = str(root/'src')
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], env=env, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr
