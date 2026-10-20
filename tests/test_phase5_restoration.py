"""Read-only Phase 5 contracts; synthetic fixtures stay in temporary folders."""
import csv
import hashlib
import json
import sqlite3
import statistics
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from api.app import APISettings, create_app
from api.market_data import VALUE_FIELDS

ROOT = Path(__file__).resolve().parents[1]


def client(root):
    return TestClient(create_app(APISettings.from_root(root)))


def market(root, values=(-5, 20, 15)):
    path = APISettings.from_root(root).market_silver
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['timestamp', *VALUE_FIELDS])
        writer.writeheader()
        for i, value in enumerate(values):
            row = dict.fromkeys(VALUE_FIELDS, None)
            row.update(timestamp=f'2026-09-01T0{[0,1,3][i]}:00:00Z', price_eur_mwh=value, load_mw=100+i, wind_total_mw=20, solar_mw=3)
            writer.writerow(row)
    return path


def anomalies(root, rows=None):
    path = APISettings.from_root(root).anomaly_report
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['timestamp','price_eur_mwh','load_mw','anomaly'])
        writer.writeheader()
        writer.writerows(rows if rows is not None else [dict(timestamp=f'2026-09-01T0{i}:00:00Z',price_eur_mwh=p,load_mw=100+i,anomaly=-1) for i,p in enumerate([-10,20,5])])
    return path


def test_anomaly_source_parity_order_pagination_and_filters(tmp_path):
    path = anomalies(tmp_path)
    before = path.read_bytes()
    with client(tmp_path) as c:
        summary = c.get('/anomalies/summary').json()
        assert (summary['count'], summary['minimum_price'], summary['maximum_price'], summary['average_load_mw']) == (3,-10,20,101)
        assert 'score' not in summary
        first = c.get('/anomalies/events?order=price_desc&limit=2').json()
        assert [r['price_eur_mwh'] for r in first['events']] == [20,5]
        assert first['next_offset'] == 2
        last = c.get('/anomalies/events?order=price_desc&limit=2&offset=2').json()
        assert last['next_offset'] is None and last['events'][0]['price_eur_mwh'] == -10
        assert c.get('/anomalies/events?offset=100').json()['events'] == []
        assert c.get('/anomalies/summary?start=2026-09-01T01:00:00Z&end=2026-09-01T01:00:00Z').json()['count'] == 1
        assert c.get('/anomalies/summary?start=2027-01-01T00:00:00Z').json()['count'] == 0
    assert path.read_bytes() == before
    assert 'models.anomaly_detection' not in sys.modules


@pytest.mark.parametrize('query',['limit=0','limit=1001','offset=-1','order=severity','start=bad','start=2026-09-01','start=2027-01-01T00:00:00Z&end=2026-01-01T00:00:00Z'])
def test_anomaly_invalid_inputs(tmp_path, query):
    anomalies(tmp_path)
    with client(tmp_path) as c:
        assert c.get('/anomalies/events?'+query).status_code == 422


def test_missing_empty_malformed_and_cache_invalidation(tmp_path):
    with client(tmp_path) as c:
        assert c.get('/anomalies/summary').status_code == 404
        path = anomalies(tmp_path, [])
        assert c.get('/anomalies/summary').json()['report_status'] == 'empty'
        anomalies(tmp_path)
        assert c.get('/anomalies/summary').json()['count'] == 3
        for text in ['secret_path,token\nprivate,secret\n', 'timestamp,price_eur_mwh,load_mw,anomaly\n2026-09-01T00:00:00Z,nan,100,-1\n', 'timestamp,price_eur_mwh,load_mw,anomaly\n2026-09-01T00:00:00Z,10,100,1\n']:
            path.write_text(text)
            response = c.get('/anomalies/summary')
            assert response.status_code == 503
            assert str(tmp_path) not in response.text and 'secret' not in response.text


def test_whole_range_metrics_exact_recent_rows_sampling_and_gaps(tmp_path):
    market(tmp_path)
    with client(tmp_path) as c:
        s = c.get('/market/summary').json()
        assert s['mean_load_mw'] == 101
        assert s['sample_price_std'] == pytest.approx(statistics.stdev([-5,20,15]))
        assert s['average_price'] == 10
        assert s['recent'][0]['timestamp'] == '2026-09-01T03:00:00Z'
        assert s['recent'][0]['wind_solar_mw'] == 23
        chart = c.get('/market/chart?max_points=4').json()
        assert chart['row_count'] <= 4 and chart['points'][-1]['gap_before']
        assert {p['price_eur_mwh'] for p in chart['points']} == {-5,20,15}
        assert c.get('/market/summary?start=2026-09-01T01:00:00Z').json()['matched_rows'] == 2
        assert c.get('/market/summary?start=2027-01-01T00:00:00Z').json()['mean_load_mw'] is None
        for query in ['max_points=3','max_points=2001','start=bad','start=2026-09-01']:
            assert c.get('/market/chart?'+query).status_code == 422


def test_operations_safe_fields_missing_evidence_and_read_only(tmp_path):
    settings = APISettings.from_root(tmp_path)
    with client(tmp_path) as c:
        s = c.get('/operations/summary').json()
        assert s['health'] == 'Degraded'
        assert s['recent_checks_failed'] is None and s['continuity_warning_sources'] is None
        assert 'Missing local evidence' in s['incident_evidence']
        assert not settings.operational_database.exists()
    settings.operational_database.parent.mkdir(parents=True)
    with sqlite3.connect(settings.operational_database) as db:
        db.execute('CREATE TABLE pipeline_runs(id INTEGER, run_time TEXT, status TEXT, message TEXT)')
        db.execute('CREATE TABLE data_quality_results(id INTEGER, check_time TEXT, check_name TEXT, status TEXT)')
        metadata = dict(next24h_forecast_status='WITHHELD',next24h_forecast_reason='Biomass secret-location token',unresolved_source_gaps={'private-source':{}},s3_sync_status='SUCCESS',secret='never-display')
        db.execute('INSERT INTO pipeline_runs VALUES(1,?,?,?)', ('2026-09-01T00:00:00Z','SUCCESS',json.dumps(metadata)))
        db.execute('INSERT INTO data_quality_results VALUES(1,?,?,?)', ('2026-09-01T00:00:00Z','secret-check','FAILED'))
    before = settings.operational_database.read_bytes()
    with client(tmp_path) as c:
        response = c.get('/operations/summary')
        assert response.status_code == 200
        s = response.json()
        assert s['forecast_status'] == 'WITHHELD' and 'Biomass' in s['forecast_reason']
        assert s['recent_checks_failed'] == 1 and s['continuity_warning_sources'] == 1
        assert not any(v in response.text for v in ['secret','private-source','never-display',str(tmp_path)])
        assert s['quality_history'][0]['check'] == 'Validation check'
        assert c.get('/models/feature-influence').status_code == 404
        assert c.post('/operations/summary').status_code == 405
    assert before == settings.operational_database.read_bytes()


def test_actual_persisted_data_parity_without_writes():
    settings = APISettings.from_root(ROOT)
    if not settings.anomaly_report.is_file() or not settings.market_silver.is_file():
        pytest.skip('Local persisted datasets are absent')
    paths = [settings.anomaly_report,settings.market_silver]
    before = [(p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]
    with settings.anomaly_report.open() as handle:
        events = list(csv.DictReader(handle))
    with settings.market_silver.open() as handle:
        observations = list(csv.DictReader(handle))
    with client(ROOT) as c:
        a = c.get('/anomalies/summary').json()
        assert a['count'] == len(events)
        assert a['maximum_price'] == max(float(r['price_eur_mwh']) for r in events)
        assert a['average_load_mw'] == pytest.approx(statistics.mean(float(r['load_mw']) for r in events))
        s = c.get('/market/summary').json()
        assert s['matched_rows'] == len(observations)
        assert s['mean_load_mw'] == pytest.approx(statistics.mean(float(r['load_mw']) for r in observations))
        assert s['sample_price_std'] == pytest.approx(statistics.stdev(float(r['price_eur_mwh']) for r in observations))
        chart = c.get('/market/chart?max_points=2000').json()
        assert chart['row_count'] <= 2000
        assert max(p['price_eur_mwh'] for p in chart['points']) == max(float(r['price_eur_mwh']) for r in observations)
        assert c.get('/operations/summary').status_code == 200
    assert before == [(p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]


def test_summary_missing_empty_and_corrupt_operational_database(tmp_path):
    with client(tmp_path) as c:
        assert c.get('/market/summary').status_code == 404
        assert c.get('/market/chart').status_code == 404
        path = market(tmp_path, [])
        assert c.get('/market/summary').json()['latest_observation'] is None
        assert c.get('/market/chart').json()['points'] == []
        path.write_text('timestamp,secret\nnot-a-time,private\n')
        response = c.get('/market/summary')
        assert response.status_code == 503 and 'private' not in response.text
        db = APISettings.from_root(tmp_path).operational_database
        db.parent.mkdir(parents=True)
        db.write_bytes(b'corrupt private operational evidence')
        response = c.get('/operations/summary')
        assert response.status_code == 503 and 'private' not in response.text
