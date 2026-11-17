"""Offline production publication tests using isolated stores and synthetic evidence."""
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from test_automatic_publication import FLOW, fake_api
from test_inference_evidence import captured  # pytest fixture
from test_forecast_publication import storage

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'deploy/staging/forecast-publication'


@pytest.fixture
def writer(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    spec = importlib.util.spec_from_file_location(
        'production_writer', ROOT / 'deploy/production-publication/writer.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_online_wal_backup_only_copies_committed_rows(tmp_path, writer):
    source = tmp_path.resolve() / 'producer.db'
    target = tmp_path / 'snapshot.db'
    with contextlib.closing(sqlite3.connect(source)) as producer:
        assert producer.execute('PRAGMA journal_mode=wal').fetchone()[0] == 'wal'
        producer.execute('CREATE TABLE pipeline_runs(id,run_time,status,message)')
        producer.execute('CREATE TABLE data_quality_results(id,check_time,check_name,status)')
        producer.execute("INSERT INTO pipeline_runs VALUES (1, 'now', 'SUCCESS', '{}')")
        producer.commit()
        producer.execute("INSERT INTO pipeline_runs VALUES (2, 'now', 'RUNNING', '{}')")
        wal = source.with_name(source.name + '-wal')
        before = hashlib.sha256(wal.read_bytes()).hexdigest()
        writer.backup(source, target, os.getuid())
        with contextlib.closing(sqlite3.connect(target)) as replica:
            assert replica.execute('SELECT id FROM pipeline_runs').fetchall() == [(1,)]
            assert replica.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
        assert hashlib.sha256(wal.read_bytes()).hexdigest() == before
        assert producer.execute('SELECT count(*) FROM pipeline_runs').fetchone()[0] == 2
    assert not (tmp_path / 'snapshot.db-wal').exists()


def test_invalid_database_never_replaces_previous_pointer(tmp_path, writer):
    source = tmp_path.resolve() / 'producer.db'
    with contextlib.closing(sqlite3.connect(source)) as db:
        db.execute('CREATE TABLE irrelevant(id)')
    root = tmp_path / 'data'
    root.mkdir()
    (root / 'current').symlink_to('releases/' + 'a' * 64)
    with pytest.raises(sqlite3.OperationalError):
        writer.backup(source, tmp_path / 'snapshot.db', os.getuid())
    assert writer.data_pointer(root) == 'a' * 64


def test_data_switch_and_hash_checked_recovery(tmp_path, writer):
    root = tmp_path / 'data'
    (root / 'releases').mkdir(parents=True)
    paths = [*writer.REQUIRED, writer.DB]

    def snapshot(content):
        folder = root / '.fixture'
        folder.mkdir()
        for path in paths:
            (folder / path.parent).mkdir(parents=True, exist_ok=True)
            (folder / path).write_bytes(content)
        hashes = {str(path): hashlib.sha256(content).hexdigest() for path in paths}
        raw = json.dumps({'files': hashes}).encode()
        (folder / 'snapshot.json').write_bytes(raw)
        return folder, hashlib.sha256(raw).hexdigest()

    first, old = snapshot(b'first')
    writer.install_data(root, first, old)
    second, new = snapshot(b'second')
    writer.install_data(root, second, new)
    assert (root / 'current' / writer.DB).read_bytes() == b'second'
    writer.install_data(root, root / 'unused', old)
    assert (root / 'current' / writer.DB).read_bytes() == b'first'
    (root / 'releases' / new / writer.DB).write_bytes(b'changed')
    with pytest.raises(ValueError, match='SNAPSHOT_FILE_HASH'):
        writer.install_data(root, root / 'unused', new)
    assert writer.data_pointer(root) == old


@pytest.mark.parametrize(('hour', 'expected'), [(11, None), (12, 'MARKET_FRESHNESS'),
                                                 (8, 'MARKET_FRESHNESS')])
def test_market_completed_hour_and_freshness(tmp_path, writer, hour, expected):
    csv = tmp_path / 'market.csv'
    now = dt.datetime(2026, 11, 17, 12, 30, tzinfo=dt.timezone.utc)
    csv.write_text(f'timestamp,price_eur_mwh\n2026-11-17T{hour:02}:00:00+00:00,23\n')

    def validate():
        return writer.validate_market(csv, now, 'timestamp', 'price_eur_mwh',
                                      dt.timedelta(hours=3), completed_hour=True)

    if expected:
        with pytest.raises(ValueError, match=expected):
            validate()
    else:
        assert validate() == '2026-11-17T11:00:00+00:00'


def test_production_forecast_sink_cannot_touch_staging(tmp_path, writer, captured, monkeypatch):
    directory, _, _, _, timestamp = captured
    proof = json.loads((directory / 'evidence.json').read_bytes())
    now = timestamp.to_pydatetime()
    staging = tmp_path / 'never-touch'
    production = storage(tmp_path)
    monkeypatch.setattr(writer.automatic, 'RECEIPTS', directory.parent)
    monkeypatch.setattr(writer.automatic, 'HISTORY', tmp_path / 'history.csv')
    monkeypatch.setattr(writer.automatic, 'PUBLICATION', staging)
    deliver = writer.automatic.deliver
    publish = writer.publish.publish_automatic
    monkeypatch.setattr(writer.automatic, 'deliver',
                        lambda *args, **kw: deliver(*args, **kw, api=fake_api(proof, now), now=now))
    monkeypatch.setattr(writer.publish, 'publish_automatic',
                        lambda *args: publish(*args, clock=lambda: now))
    with pytest.raises(ValueError, match='RECEIPT_RELEASE_BINDING'):
        writer.deliver_forecast(directory.name, FLOW, production, '0' * 64, os.getuid())
    assert writer.publish.pointer(production) is None
    digest = proof['inference']['release_manifest_sha256']
    assert writer.deliver_forecast(directory.name, FLOW, production, digest, os.getuid()) == 'PUBLISHED'
    assert len(writer.forecast_publication.read_active(production, now)['forecasts']) == 24
    assert not staging.exists()


def test_withholding_updates_other_stores_without_issuing_forecast(tmp_path, writer, monkeypatch):
    root = tmp_path / 'published'
    (root / 'data/releases').mkdir(parents=True)
    now = writer.utcnow()
    observed = now - dt.timedelta(hours=2)
    monkeypatch.setattr(writer, 'discover',
                        lambda _: {'id': 'flow', 'state': {'id': 'state'}})
    monkeypatch.setattr(writer, 'stage_data', lambda *args: ('data', {str(writer.PRICE): 'price', str(writer.MANIFEST): 'manifest'}))
    monkeypatch.setattr(writer.operational_capture, 'capture_terminal', lambda *a, **k: (b'ops', 'hash'))
    monkeypatch.setattr(writer.operational_evidence, 'validate',
                        lambda *a: {'inference': {'outcome': 'WITHHELD', 'receipt_id': None}})
    monkeypatch.setattr(writer, 'build_realized', lambda *a: {'state': 'READY',
                        'sources': {'prices_sha256': 'price'}, 'observed_through': observed.isoformat()})
    monkeypatch.setattr(writer, 'deliver_forecast', lambda *a: pytest.fail('unexpected inference'))
    calls = []
    @contextlib.contextmanager
    def opened(_):
        yield None, None

    monkeypatch.setattr(writer.operational_evidence_store, 'opened', opened)
    monkeypatch.setattr(writer.operational_evidence_store, 'pointer', lambda _: None)
    def publish_terminal(path, raw, _):
        assert json.loads(raw)['delivery']['outcome'] == 'SKIPPED_WITHHELD'
        calls.append(path)
        return {'status': 'PUBLISHED'}

    monkeypatch.setattr(writer.operational_evidence_store, 'publish_terminal', publish_terminal)
    monkeypatch.setattr(writer.realized_report_store, 'publish',
                        lambda *a: calls.append(a[0]) or 'realized')
    monkeypatch.setattr(writer, 'install_data', lambda *a: calls.append(a[0]))
    writer.run(tmp_path, root, os.getuid())
    assert calls == [root / 'operations', root / 'realized', root / 'data']


def test_complete_snapshot_with_frozen_model_and_dated_metadata(tmp_path, writer):
    source = tmp_path.resolve() / 'source'
    folder = tmp_path.resolve() / 'candidate'
    folder.mkdir()
    now = dt.datetime(2026, 11, 17, 12, 30, tzinfo=dt.timezone.utc)
    import shutil
    for path in writer.REQUIRED:
        target = source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if path in (writer.SILVER, writer.PRICE):
            target.write_text('timestamp,price_eur_mwh\n2026-11-17T11:00:00Z,23\n')
        else:
            shutil.copyfile(ROOT / path, target)
    diagnostic = source / writer.OPTIONAL[-1]
    diagnostic.parent.mkdir()
    old = b'{"generated_at_utc":"2026-10-19T07:52:09+00:00"}\n'
    diagnostic.write_bytes(old)
    (source / writer.DB.parent).mkdir()
    with contextlib.closing(sqlite3.connect(source / writer.DB)) as db:
        db.execute('CREATE TABLE pipeline_runs(id,run_time,status,message)')
        db.execute('CREATE TABLE data_quality_results(id,check_time,check_name,status)')
    digest, _ = writer.stage_data(source, folder, os.getuid(), now)
    writer.verify_data(folder, digest)
    assert (folder / writer.OPTIONAL[-1]).read_bytes() == old
    (source / writer.MANIFEST.with_name('next24h_model.joblib')).write_bytes(b'tampered')
    replacement = tmp_path / 'replacement'
    replacement.mkdir()
    with pytest.raises(ValueError, match='MODEL_PROVENANCE'):
        writer.stage_data(source, replacement, os.getuid(), now)
