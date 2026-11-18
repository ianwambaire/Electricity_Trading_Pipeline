"""Offline production publication tests using isolated stores and synthetic evidence."""
import contextlib
import datetime as dt
import errno
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from test_automatic_publication import FLOW, fake_api
from test_operational_capture_correction import actual_writer_fixture
from test_current_operations import association, make_withheld  # pytest fixture and helper
from test_inference_evidence import captured  # pytest fixture
from test_forecast_publication import storage
from test_operational_terminal import STATE, fixture_source, source_api, stable  # pytest fixture
from shared.operational_evidence_producer import associate, from_snapshot, receipt_bundle

ROOT = Path(__file__).resolve().parents[1]


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


def test_snapshot_adapter_reads_operational_evidence_in_read_only_transaction(
        tmp_path, writer, association):
    make_withheld(association, with_incident=False)
    source = tmp_path.resolve() / 'producer.db'
    target = source.with_name('snapshot.db')
    with contextlib.closing(sqlite3.connect(source)) as db:
        db.executescript("""
            CREATE TABLE pipeline_runs(id INTEGER PRIMARY KEY, run_time, status, message);
            CREATE TABLE pipeline_stage_timings(run_id, stage_name, start_timestamp_utc,
                                                end_timestamp_utc, status);
            CREATE TABLE operational_incidents(timestamp_utc, component, event_type, details_json);
            CREATE TABLE data_quality_results(id, check_time, check_name, status);
        """)
        db.execute('INSERT INTO pipeline_runs VALUES (1, :run_time, :status, :message)',
                   association['records'][0])
        db.execute('INSERT INTO pipeline_stage_timings VALUES '
                   '(:run_id, :stage_name, :start_timestamp_utc, :end_timestamp_utc, :status)',
                   association['stages'][0])
        db.commit()
    original = source.read_bytes()
    writer.backup(source, target, os.getuid())
    snapshot = target.read_bytes()
    adapter = writer.SnapshotSource(source.parent, os.getuid(), target)
    args = {key: association[key] for key in
            ('flow', 'tasks', 'receipts', 'expected_deployment', 'observed_at')}

    with adapter.snapshot() as reader:
        raw, digest = from_snapshot(reader, **args)
        evidence = writer.operational_evidence.validate(raw, digest, args['observed_at'])
        assert evidence['inference']['outcome'] == 'WITHHELD'
        assert evidence['delivery']['outcome'] == 'SKIPPED_WITHHELD'
        assert reader.in_transaction
        assert reader.execute('PRAGMA query_only').fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            reader.execute('DELETE FROM pipeline_runs')
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        reader.execute('SELECT 1')

    # The read-only URI still prevents a write if query_only is disabled.
    with pytest.raises(sqlite3.OperationalError, match='readonly'):
        with adapter.snapshot() as failed_reader:
            failed_reader.execute('PRAGMA query_only=OFF')
            failed_reader.execute('DELETE FROM pipeline_runs')
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        failed_reader.execute('SELECT 1')
    assert source.read_bytes() == original
    assert target.read_bytes() == snapshot


@pytest.mark.parametrize('replace_with_symlink', [False, True])
def test_production_receipt_read_without_noatime_capability(
        tmp_path, writer, stable, monkeypatch, replace_with_symlink):
    with monkeypatch.context() as patch:
        source, database = fixture_source(stable, tmp_path, patch)
    adapter = writer.SnapshotSource(source.root, source.owner, database)
    api, _ = source_api(stable)
    actual_open = os.open
    noatime = getattr(os, 'O_NOATIME', 1 << 30)
    monkeypatch.setattr(os, 'O_NOATIME', noatime, raising=False)
    receipt_dir = next((source.root / writer.RECEIPTS).iterdir())
    calls = []

    def restricted_open(path, flags, *args, **kwargs):
        if path in writer.operational_capture.NAMES:
            calls.append(flags)
            if flags & noatime:
                raise PermissionError(errno.EPERM, os.strerror(errno.EPERM))
            if replace_with_symlink:
                (receipt_dir / path).unlink()
                (receipt_dir / path).symlink_to(database)
        return actual_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, 'open', restricted_open)
    flow_id = stable['flow']['id']
    if replace_with_symlink:
        with pytest.raises(OSError) as error:
            writer.operational_capture.capture_terminal(flow_id, STATE, source=adapter, api=api,
                                                        clock=lambda: stable['observed_at'])
        assert error.value.errno == errno.ELOOP
        count = 1
    else:
        assert writer.operational_capture.capture_terminal(
            flow_id, STATE, source=adapter, api=api,
            clock=lambda: stable['observed_at']) == associate(**stable)
        count = len(writer.operational_capture.NAMES)
    assert calls == [os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK] * count


def test_production_capture_normalizes_only_persisted_issue_timestamps(
        tmp_path, writer, stable, monkeypatch):
    facts = actual_writer_fixture(stable)
    companion = tmp_path / 'operational_evidence_producer.py'
    reviewed = ROOT / 'deploy/staging/operational-capture-correction-v1' / companion.name
    companion.write_bytes(reviewed.read_bytes())
    monkeypatch.setattr(writer, '__file__', str(tmp_path / 'writer.py'))
    with monkeypatch.context() as patch:
        source, database = fixture_source(facts, tmp_path, patch)
    adapter = writer.SnapshotSource(source.root, source.owner, database)
    api, calls = source_api(facts)
    receipt_dir = next((source.root / writer.RECEIPTS).iterdir())
    receipt_before = {p.name: p.read_bytes() for p in receipt_dir.iterdir()}
    db_before = database.read_bytes()
    issue = json.loads(facts['records'][0]['message'])['next24h_forecast_issue_time']
    assert issue[10] == ' '
    observed = facts['observed_at'] + dt.timedelta(hours=3)
    # Exercise the actual terminal capture path used by run(), including SQLite.
    raw, digest = writer.capture_terminal(facts['flow']['id'], STATE, source=adapter, api=api,
                                          clock=lambda: observed)
    evidence = writer.operational_evidence.validate(raw, digest, observed)
    assert evidence['inference']['issue_time'] == issue.replace(' ', 'T', 1)
    bundle, receipt_digest = receipt_bundle(facts['receipts'][0], observed)
    assert evidence['delivery']['bundle_sha256'] == receipt_digest
    bundle_bytes = json.dumps(bundle, sort_keys=True, separators=(',', ':')).encode()
    with pytest.raises(writer.forecast_publication.ExpiredPublication):
        writer.forecast_publication.validate(bundle_bytes, receipt_digest, observed)
    assert calls == [False, True, False]
    assert database.read_bytes() == db_before
    assert {p.name: p.read_bytes() for p in receipt_dir.iterdir()} == receipt_before
    companion.write_bytes(companion.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='EVIDENCE_READER_HASH'):
        writer.capture_terminal(facts['flow']['id'], STATE, source=adapter, api=api)
    assert calls == [False, True, False]


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
    monkeypatch.setattr(writer, 'capture_terminal', lambda *a, **k: (b'ops', 'hash'))
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
    # The worker generates these reports at runtime. Keep the frozen model
    # artifacts real, but supply generated reports in the isolated fixture.
    reports = {
        writer.REPORTS / 'actual_vs_predicted.csv':
            'timestamp,actual_price,predicted_price\n2026-11-17T11:00:00Z,23,22\n',
        writer.REPORTS / 'detected_anomalies.csv':
            'timestamp,price_eur_mwh\n2026-11-17T11:00:00Z,23\n',
        writer.REPORTS / 'feature_importance.csv':
            'feature,importance,signed_coefficient\nprice_eur_mwh,1,1\n',
    }
    for path in writer.REQUIRED:
        target = source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if path in (writer.SILVER, writer.PRICE):
            target.write_text('timestamp,price_eur_mwh\n2026-11-17T11:00:00Z,23\n')
        elif path in reports:
            target.write_text(reports[path])
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
    for path, content in reports.items():
        assert (folder / path).read_text() == content
    assert (folder / writer.OPTIONAL[-1]).read_bytes() == old
    (source / writer.MANIFEST.with_name('next24h_model.joblib')).write_bytes(b'tampered')
    replacement = tmp_path / 'replacement'
    replacement.mkdir()
    with pytest.raises(ValueError, match='MODEL_PROVENANCE'):
        writer.stage_data(source, replacement, os.getuid(), now)
