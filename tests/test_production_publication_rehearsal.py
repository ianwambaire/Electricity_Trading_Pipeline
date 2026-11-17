"""Rehearse all four stores offline using the production writer and API readers."""
import contextlib
from dataclasses import replace
import datetime as dt
import io
import json
import os
import shutil
import sqlite3
import stat

from fastapi.testclient import TestClient
import pandas as pd
import pytest

from api import current_operations, forecast_source, realized_reporting
from api.app import APISettings, create_app
from api.market_data import VALUE_FIELDS
from models.inference_evidence import receipt
from test_current_operations import association, summary  # pytest fixture and helper
from test_forecast_publication import ISSUE
from test_operational_terminal import fixture_source, source_api, stable  # pytest fixture and helpers
from test_production_publication import ROOT, writer  # pytest fixture


def stage_fixture(writer, facts, tmp_path, monkeypatch, expired):
    offset = dt.timedelta(hours=int(expired))
    for item in [facts['flow'], *facts['tasks'], *facts['records'], *facts['stages']]:
        for key in ('expected_start_time', 'start_time', 'end_time', 'run_time',
                    'start_timestamp_utc', 'end_timestamp_utc'):
            if key in item:
                item[key] = (dt.datetime.fromisoformat(item[key]) + offset).isoformat()
    original = facts['receipts'][0]
    proof = json.loads(original['evidence.json'])
    provenance = json.loads(original['provenance.json'])
    provenance.pop('inference_evidence')
    for key in ('started_at', 'issued_at', 'completed_at'):
        proof['execution'][key] = (dt.datetime.fromisoformat(proof['execution'][key]) + offset).isoformat()
    provenance['weather_acquired_at_utc'] = (
        dt.datetime.fromisoformat(provenance['weather_acquired_at_utc']) + offset).isoformat()
    frame = pd.read_csv(io.BytesIO(original['forecast.csv']))
    for key in ('forecast_issue_time', 'target_timestamp'):
        frame[key] = pd.to_datetime(frame[key], utc=True)
    matrix = pd.DataFrame([proof['inference']['feature_values']],
                          columns=proof['inference']['feature_names'])
    facts['receipts'] = [receipt(frame, provenance, (ROOT / writer.MANIFEST).read_bytes(),
                                 matrix, proof['inputs'], proof['inference']['source_sha256'],
                                 proof['execution'])]
    summary(facts, next24h_forecast_issue_time=str(frame.iloc[0]['forecast_issue_time']))
    with monkeypatch.context() as patch:
        source, db = fixture_source(facts, tmp_path, patch)
    with contextlib.closing(sqlite3.connect(db)) as conn:
        conn.execute('CREATE TABLE data_quality_results(id, check_time, check_name, status)')
    now = ISSUE + dt.timedelta(hours=2, minutes=5) + offset
    for path in writer.REQUIRED:
        target = source.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if path == writer.SILVER:
            target.write_text(','.join(['timestamp', *VALUE_FIELDS]) + '\n' +
                              ','.join([ISSUE.isoformat(), *['100'] * len(VALUE_FIELDS)]) + '\n')
        elif path == writer.PRICE:
            target.write_text('timestamp,price_eur_mwh\n' + ''.join(
                f'{(ISSUE + dt.timedelta(minutes=15*i)).isoformat()},100\n'
                for i in range(1 + int((now-ISSUE).total_seconds()//900))))
        elif path.name == 'actual_vs_predicted.csv':
            target.write_text(f'timestamp,actual_price,predicted_price\n{ISSUE.isoformat()},100,100\n')
        elif path.name == 'detected_anomalies.csv':
            target.write_text(f'timestamp,price_eur_mwh\n{ISSUE.isoformat()},100\n')
        elif path.name == 'feature_importance.csv':
            target.write_text('feature,importance,signed_coefficient\nprice_eur_mwh,1,1\n')
        else:
            shutil.copyfile(ROOT / path, target)
    frame.assign(issued_at_utc=proof['execution']['completed_at']).to_csv(
        source.root / writer.HISTORY, index=False)
    return source.root, db, now


def bind_fixture(writer, source, facts, now, monkeypatch):
    api, _ = source_api(facts)

    def forecast_api(path, body=None):
        if path == '/task_runs/filter':
            return api(facts['flow']['id'], tasks=True)
        assert path == '/flow_runs/' + facts['flow']['id']
        return api(facts['flow']['id'])

    capture = writer.capture_terminal
    automatic = writer.automatic.deliver
    publish = writer.publish.publish_automatic
    operations = writer.operational_evidence_store.publish_terminal
    realized = writer.build_realized
    monkeypatch.setattr(writer, 'utcnow', lambda: now)
    monkeypatch.setattr(writer, 'discover', lambda _: facts['flow'])
    monkeypatch.setattr(writer, 'capture_terminal',
                        lambda *a, **kw: capture(*a, **kw, api=api, clock=lambda: now))
    monkeypatch.setattr(writer, 'build_realized', lambda *a: realized(*a, now=now))
    monkeypatch.setattr(writer.automatic, 'RECEIPTS', source / writer.RECEIPTS)
    monkeypatch.setattr(writer.automatic, 'HISTORY', source / writer.HISTORY)
    monkeypatch.setattr(writer.automatic, 'deliver',
                        lambda *a, **kw: automatic(*a, **kw, api=forecast_api, now=now))
    monkeypatch.setattr(writer.publish, 'publish_automatic', lambda *a: publish(*a, clock=lambda: now))
    monkeypatch.setattr(writer.operational_evidence_store, 'publish_terminal',
                        lambda *a: operations(*a, clock=lambda: now))


def check_api_reads(namespace, now, published, monkeypatch):
    active_forecast = forecast_source.availability.read_active
    current_evidence = current_operations.read_current
    realized_status = realized_reporting.evaluation
    observed = now
    monkeypatch.setattr(forecast_source.availability, 'read_active',
                        lambda root: active_forecast(root, now=now))
    monkeypatch.setattr(current_operations, 'read_current',
                        lambda root, *, now, admin: current_evidence(root, now=observed, admin=admin))
    monkeypatch.setattr(realized_reporting, 'evaluation', lambda root: realized_status(root, now=now))
    settings = replace(
        APISettings.from_root(namespace / 'data/current'),
        next24_publication_root=namespace / 'forecast',
        operational_publication_root=namespace / 'operations',
        realized_publication_root=namespace / 'realized',
        price_only_fallback_path=None,
    )
    with TestClient(create_app(settings)) as client:
        for route in ('/market/history', '/forecast/one-hour', '/operations/current',
                      '/forecast/realized-evaluation'):
            response = client.get(route)
            assert response.status_code == 200, (route, response.text)
        assert client.get('/operations/current').json()['status'] == 'VALID'
        assert client.get('/admin/operations/current').status_code == 401
        forecast = client.get('/forecast/next24')
        if published:
            assert forecast.status_code == 200 and forecast.json()['row_count'] == 24
            assert forecast.json()['publication']['status'] == 'VALID'
        else:
            assert forecast.status_code == 503
            assert forecast.json()['detail']['code'] == 'FORECAST_WITHHELD'


@pytest.mark.parametrize('case', ['fresh', 'expired', 'tampered', 'invalid'])
def test_production_writer_to_reader_rehearsal(tmp_path, writer, stable, monkeypatch, capsys, case):
    source, db, now = stage_fixture(writer, stable, tmp_path, monkeypatch, case == 'expired')
    bind_fixture(writer, source, stable, now, monkeypatch)
    namespace = tmp_path.resolve() / 'publication'
    for store in ('data', 'forecast', 'operations', 'realized'):
        (namespace / store / 'releases').mkdir(parents=True)
    for store, module in [('operations', writer.operational_evidence_store),
                          ('realized', writer.realized_report_store)]:
        marker = namespace / store / 'contract'
        marker.write_bytes(module.MARKER)
        marker.chmod(0o640)
    if case == 'tampered':
        output = next((source / writer.RECEIPTS).glob('*/forecast.csv'))
        output.write_bytes(output.read_bytes() + b'\n')
    if case == 'invalid':
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE pipeline_runs SET message=json_set(message, "
                         "'$.next24h_forecast_issue_time','2026-01-05 08:00:00')")
    original = db.read_bytes()
    if case in ('tampered', 'invalid'):
        code = 'RECEIPT_INTEGRITY' if case == 'tampered' else 'TIMESTAMP'
        with pytest.raises(writer.operational_evidence.InvalidEvidence, match=code):
            writer.run(source, namespace, os.getuid())
        assert not list(namespace.glob('*/current'))
        assert db.read_bytes() == original
        return

    writer.run(source, namespace, os.getuid())
    outcome = json.loads(capsys.readouterr().out)
    writer.check(namespace)
    check = json.loads(capsys.readouterr().out)
    assert db.read_bytes() == original
    assert check['data'] == outcome['data']
    assert check['realized'] == outcome['realized']
    assert check['operations']
    assert check['forecast_rows'] == (0 if case == 'expired' else 24)
    assert outcome['forecast'] == ('SKIPPED_EXPIRED' if case == 'expired' else 'PUBLISHED')
    check_api_reads(namespace, now, case == 'fresh', monkeypatch)
    for current in (namespace / 'data/current', namespace / 'operations/current',
                    namespace / 'realized/current'):
        assert current.exists()
        assert not stat.S_IMODE(current.stat().st_mode) & 0o022
    # Simulate the approved rollback in the disposable namespace.
    for current in namespace.glob('*/current'):
        current.rename(current.with_name('.withdrawn-rehearsal'))
    assert not list(namespace.glob('*/current'))
    assert (namespace / 'data/releases' / check['data']).is_dir()
    with pytest.raises(ValueError, match='MISSING_DATA'):
        writer.check(namespace)
