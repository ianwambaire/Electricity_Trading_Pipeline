"""One-way production publication from persisted producer evidence. No inference."""
import contextlib
import datetime as dt
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import sys
import time
from types import FunctionType, SimpleNamespace
import uuid

import pandas as pd

from api.model_summaries import model_summaries
from models.realized_reporting import build as build_realized
from shared import forecast_availability, forecast_publication, operational_capture, operational_evidence
from shared import operational_evidence_store, realized_report_store
from shared.operational_evidence_producer import latest_natural

# These three already-reviewed tools are copied from a pinned Git revision.
import automatic
import prepare
import publish

SOURCE = operational_capture.PRODUCTION
ROOT = Path('/srv/powerflow/production-published')
DB = Path('database/electricity_trading.db')
SILVER = Path('data/processed/silver_electricity_market_data.csv')
PRICE = Path('data/raw/entsoe/prices.csv')
REPORTS = Path('data/reports')
MODELS = Path('artifacts/models')
MANIFEST = MODELS / 'releases/next24h/next24h_release_manifest.json'
HISTORY = REPORTS / 'next24h_forecast_history.csv'
RECEIPTS = REPORTS / 'next24h_inference'
REQUIRED = (
    SILVER, PRICE, REPORTS / 'actual_vs_predicted.csv',
    REPORTS / 'detected_anomalies.csv', REPORTS / 'final_holdout_metrics.csv',
    REPORTS / 'feature_importance.csv', MANIFEST,
    MODELS / 'final_model_release_manifest.json', MODELS / 'final_gold_model.joblib',
    MODELS / 'final_gold_model_features.joblib',
    MANIFEST.with_name('next24h_model.joblib'),
    MANIFEST.with_name('next24h_feature_contract.joblib'),
)
OPTIONAL = tuple(REPORTS / name for name in (
    'next24h_realized_errors.csv', 'monitoring/forecast_vintage_health.json',
    'monitoring/next24h_exogenous_silver_quality.json',
))
LIMIT = 64 * 1024 * 1024
MIN_FREE = 1024**3
MAX_RETAINED = 3 * 1024**3
DIGEST = re.compile(r'[0-9a-f]{64}')


def require(ok, code):
    if not ok:
        raise ValueError(code)


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write(path, raw):
    with path.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def backup(source, target, owner):
    # Unlike immutable=1, mode=ro uses SQLite's live snapshot/locking protocol,
    # including committed WAL contents. The unit mounts the source read-only.
    require(source.resolve(strict=True) == source, 'DATABASE_PATH')
    info = source.stat()
    require(source.is_file() and info.st_uid == owner and not info.st_mode & 0o022
            and info.st_nlink == 1 and 0 < info.st_size <= LIMIT, 'DATABASE_METADATA')
    deadline = time.monotonic() + 20

    def check(*_):
        if time.monotonic() >= deadline:
            raise TimeoutError('DATABASE_BACKUP_DEADLINE')

    with contextlib.closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=.25)) as reader:
        reader.execute('PRAGMA query_only=ON')
        require(reader.execute('PRAGMA page_count').fetchone()[0] *
                reader.execute('PRAGMA page_size').fetchone()[0] <= LIMIT, 'DATABASE_SIZE')
        with contextlib.closing(sqlite3.connect(target)) as snapshot:
            reader.backup(snapshot, pages=128, progress=check, sleep=.05)
            require(snapshot.execute('PRAGMA journal_mode=DELETE').fetchone()[0] == 'delete', 'DATABASE_JOURNAL')
            snapshot.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            require(snapshot.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'DATABASE_INTEGRITY')
            snapshot.execute('SELECT id,run_time,status,message FROM pipeline_runs LIMIT 0')
            snapshot.execute('SELECT id,check_time,check_name,status FROM data_quality_results LIMIT 0')
    require(target.stat().st_size <= LIMIT and source.stat().st_ino == info.st_ino, 'DATABASE_CHANGED')
    with target.open('rb') as handle:
        os.fsync(handle.fileno())


def read_input(source, path, owner):
    return automatic.capture(source / path.parent, path.name, owner, LIMIT)


def validate_market(path, now, timestamp_column, value_column, age, *, completed_hour=False):
    frame = pd.read_csv(path, usecols=[timestamp_column, value_column], nrows=400_001)
    times = pd.to_datetime(frame[timestamp_column], utc=True, format='mixed', errors='raise')
    require(0 < len(frame) <= 400_000 and not times.isna().any() and times.is_unique
            and times.is_monotonic_increasing, 'MARKET_TIMESTAMPS')
    latest = times.iloc[-1].to_pydatetime()
    if completed_hour:
        require(latest.minute == latest.second == latest.microsecond == 0, 'SILVER_NOT_HOURLY')
    require(now - age <= latest <= now - dt.timedelta(hours=int(completed_hour)),
            'MARKET_FRESHNESS')
    require(pd.notna(frame[value_column].iloc[-1]) and
            float('-inf') < float(frame[value_column].iloc[-1]) < float('inf'), 'MARKET_VALUE')
    return latest.isoformat()


def stage_data(source, folder, owner, now):
    hashes = {}
    for path in (*REQUIRED, *OPTIONAL):
        try:
            raw = read_input(source, path, owner)
        except FileNotFoundError:
            if path in OPTIONAL:
                continue
            raise
        (folder / path.parent).mkdir(parents=True, exist_ok=True)
        write(folder / path, raw)
        hashes[str(path)] = hashlib.sha256(raw).hexdigest()

    (folder / DB.parent).mkdir()
    backup(source / DB, folder / DB, owner)
    with (folder / DB).open('rb') as handle:
        hashes[str(DB)] = hashlib.file_digest(handle, 'sha256').hexdigest()

    silver = validate_market(folder / SILVER, now, 'timestamp', 'price_eur_mwh',
                             dt.timedelta(hours=24), completed_hour=True)
    price = validate_market(folder / PRICE, now, 'timestamp', 'price_eur_mwh', dt.timedelta(hours=3))
    manifest = json.loads((folder / MANIFEST).read_bytes())
    require(manifest['release_id'] == forecast_publication.RELEASE and
            hashes[str(MANIFEST.with_name('next24h_model.joblib'))] == manifest['model_sha256'] ==
            forecast_publication.MODEL_HASH and
            hashes[str(MANIFEST.with_name('next24h_feature_contract.joblib'))] ==
            manifest['feature_contract_sha256'] == forecast_publication.CONTRACT_HASH, 'MODEL_PROVENANCE')
    summaries = {model.key: model for model in model_summaries(folder).models}
    require(all(model.metadata_status == 'available' for model in summaries.values()) and
            summaries['next24h'].artifact_status == 'integrity_verified' and
            summaries['one_hour'].artifact_status == 'present_not_integrity_verified',
            'MODEL_METADATA')
    require(all(hashes[str(p)] == hashlib.sha256(read_input(source, p, owner)).hexdigest()
                for p in (*REQUIRED, *OPTIONAL) if str(p) in hashes), 'SOURCE_CHANGED')
    raw = json.dumps({'files': hashes, 'silver_through': silver, 'prices_through': price},
                     sort_keys=True).encode() + b'\n'
    write(folder / 'snapshot.json', raw)
    return hashlib.sha256(raw).hexdigest(), hashes


def data_pointer(root):
    current = root / 'current'
    if not os.path.lexists(current):
        return None
    target = os.readlink(current)
    require(target.startswith('releases/') and DIGEST.fullmatch(target[9:]), 'DATA_POINTER')
    return target[9:]


def install_data(root, folder, digest):
    destination = root / 'releases' / digest
    if data_pointer(root) == digest:
        verify_data(destination, digest)
        return
    if destination.exists():
        verify_data(destination, digest)
    else:
        for directory, _, files in os.walk(folder, topdown=False):
            for name in files:
                (Path(directory) / name).chmod(0o640)
            Path(directory).chmod(0o750)
            syncdir(Path(directory))
        os.rename(folder, destination)
        syncdir(destination.parent)
        verify_data(destination, digest)
    pending = root / ('.next-' + uuid.uuid4().hex)
    os.symlink('releases/' + digest, pending)
    os.replace(pending, root / 'current')
    syncdir(root)


def verify_data(folder, digest):
    raw = (folder / 'snapshot.json').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == digest, 'SNAPSHOT_DIGEST')
    files = json.loads(raw)['files']
    allowed = set(map(str, (*REQUIRED, *OPTIONAL, DB)))
    require(set(map(str, (*REQUIRED, DB))) <= files.keys() <= allowed, 'SNAPSHOT_ALLOWLIST')
    paths = list(folder.rglob('*'))
    require(not folder.is_symlink() and all(not p.is_symlink() and
            (p.is_dir() or p.is_file()) for p in paths), 'SNAPSHOT_PATH')
    inventory = {str(p.relative_to(folder)) for p in paths if p.is_file()}
    require(inventory == files.keys() | {'snapshot.json'}, 'SNAPSHOT_INVENTORY')
    for path, checksum in files.items():
        with (folder / path).open('rb') as handle:
            require(hashlib.file_digest(handle, 'sha256').hexdigest() == checksum, 'SNAPSHOT_FILE_HASH')


def discover(now):
    connection = http.client.HTTPConnection('127.0.0.1', 4200, timeout=4)
    try:
        body = json.dumps({'deployments': {'id': {'any_': [operational_capture.DEPLOYMENT]}},
                           'flow_runs': {'expected_start_time': {'before_': now.isoformat()}},
                           'sort': 'EXPECTED_START_TIME_DESC', 'limit': 20})
        connection.request('POST', '/api/flow_runs/filter', body, {'Content-Type': 'application/json'})
        response = connection.getresponse()
        raw = response.read(1_048_577)
        require(response.status == 200 and len(raw) <= 1_048_576, 'PREFECT_DISCOVERY')
        return latest_natural(json.loads(raw), operational_capture.DEPLOYMENT, now)
    finally:
        connection.close()


class SnapshotSource(operational_capture.Source):
    def __init__(self, source, owner, snapshot):
        super().__init__(source, owner)
        self.snapshot_path = snapshot

    @contextlib.contextmanager
    def snapshot(self):
        with contextlib.closing(sqlite3.connect(
            self.snapshot_path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            yield db


def deliver_forecast(receipt, flow, destination, manifest_hash, owner):
    def build(forecast, provenance, model, evidence, expected, now):
        # automatic.deliver has pinned all five source byte strings before
        # calling the builder. Bind those same bytes, never a second read.
        proof = forecast_publication.decode(builder.safe_file(evidence))
        require(proof['inference']['release_manifest_sha256'] == manifest_hash,
                'RECEIPT_RELEASE_BINDING')
        return pinned_build(forecast, provenance, model, evidence, expected, now)

    def publish_production(_, raw, checksum):
        return publish.publish_automatic(destination, raw, checksum)

    # prepare.build resolves safe_file from its module. Use a private callable
    # with its own globals to leave the imported staging tools unchanged.
    prepare_build = FunctionType(prepare.build.__code__, dict(vars(prepare)))
    builder = SimpleNamespace(safe_file=prepare.safe_file, build=build)

    def pinned_build(*args):
        prepare_build.__globals__['safe_file'] = builder.safe_file
        return prepare_build(*args)

    return automatic.deliver(receipt, flow, forecast_publication, builder,
                             SimpleNamespace(publish_automatic=publish_production),
                             owner=owner)['status']


def publish_operations(root, forecast, evidence, manifest_hash, owner):
    with operational_evidence_store.opened(root) as (directory, releases):
        current = operational_evidence_store.pointer(directory)
        if current:
            prior = operational_evidence.validate(
                operational_evidence_store.content(releases, current), current, utcnow())
            if prior['execution']['flow_run_id'] == evidence['execution']['flow_run_id']:
                return 'SKIPPED_DUPLICATE', 'ALREADY_EVALUATED'

    # Persisted delivery outcomes describe the producer's original destination.
    # Rebind the operations projection to this production writer's own outcome.
    receipt = evidence['inference']['receipt_id']
    forecast_status = 'NO_NEW_PRIMARY'
    delivery = 'SKIPPED_WITHHELD' if evidence['inference']['outcome'] == 'WITHHELD' else 'NOT_RUN'
    bundle_hash = None
    if receipt:
        forecast_status = deliver_forecast(receipt, evidence['execution']['flow_run_id'],
                                           forecast, manifest_hash, owner)
        delivery = forecast_status
        if delivery == 'PUBLISHED':
            bundle_hash = publish.pointer(forecast)
    now = utcnow()
    evidence['observed_at'] = now.isoformat()
    evidence['delivery'] = dict(outcome=delivery, receipt_id=receipt,
                                bundle_sha256=bundle_hash, published_at=None)
    raw = operational_evidence.canonical(evidence)
    result = operational_evidence_store.publish_terminal(root, raw, hashlib.sha256(raw).hexdigest())
    return result['status'], forecast_status


def run(source, root, owner):
    require(shutil.disk_usage(root).free >= MIN_FREE, 'DISK_RESERVE')
    # A cap preserves rollback evidence and protects the shared disk. Raise
    # before any publication, pending an operator-reviewed retention action.
    retained = sum(p.stat().st_size for p in root.glob('*/releases/**/*') if p.is_file())
    require(retained < MAX_RETAINED, 'PUBLICATION_RETENTION_LIMIT')
    flow = discover(utcnow())
    with tempfile.TemporaryDirectory(prefix='.partial-', dir=root / 'data/releases') as temp:
        folder = Path(temp)
        digest, hashes = stage_data(source, folder, owner, utcnow())
        ops, ops_digest = operational_capture.capture_terminal(
            flow['id'], flow['state']['id'], source=SnapshotSource(source, owner, folder / DB))
        evidence = operational_evidence.validate(ops, ops_digest, utcnow())
        realized = build_realized(source / HISTORY, folder / PRICE, source / RECEIPTS)
        require(realized['state'] == 'READY' and realized['sources']['prices_sha256'] ==
                hashes[str(PRICE)] and realized['observed_through'] is not None and
                forecast_publication.time(realized['observed_through']) >=
                utcnow() - dt.timedelta(hours=4), 'REALIZED_INPUTS')
        staged_bytes = sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())
        require(shutil.disk_usage(root).free >= MIN_FREE, 'DISK_RESERVE')
        # Account for the separate immutable report plus bounded JSON evidence.
        require(retained + staged_bytes + len(realized_report_store.encode(realized)) +
                operational_evidence.MAX_BYTES + forecast_publication.MAX_BYTES <= MAX_RETAINED,
                'PUBLICATION_RETENTION_LIMIT')
        ops_status, forecast_status = publish_operations(root / 'operations', root / 'forecast',
                                                           evidence, hashes[str(MANIFEST)], owner)
        realized_digest = realized_report_store.publish(root / 'realized', realized)
        install_data(root / 'data', folder, digest)
        print(json.dumps({'data': digest, 'forecast': forecast_status, 'operations': ops_status,
                          'realized': realized_digest, 'flow': flow['id']}), flush=True)


def check(root):
    """Read through the same contracts the production API uses."""
    now = utcnow()
    digest = data_pointer(root / 'data')
    require(digest is not None, 'MISSING_DATA')
    folder = root / 'data/releases' / digest
    verify_data(folder, digest)
    metadata = json.loads((folder / 'snapshot.json').read_bytes())
    require(forecast_publication.time(metadata['silver_through']) >= now - dt.timedelta(hours=24)
            and forecast_publication.time(metadata['prices_through']) >= now - dt.timedelta(hours=3),
            'MARKET_FRESHNESS')
    from api.database import read_snapshot
    with read_snapshot(folder / DB) as db:
        db.execute('SELECT id,run_time,status,message FROM pipeline_runs LIMIT 0')
        db.execute('SELECT id,check_time,check_name,status FROM data_quality_results LIMIT 0')
    operations = operational_evidence_store.read_current(root / 'operations', now=now)
    require(operations['status'] == 'VALID', 'OPERATIONS_NOT_CURRENT')
    realized, realized_digest = realized_report_store.read_active(root / 'realized', now)
    require(realized['state'] == 'READY' and now - forecast_publication.time(realized['generated_at'])
            < dt.timedelta(minutes=90), 'REALIZED_NOT_CURRENT')
    try:
        forecast = forecast_availability.read_active(root / 'forecast', now)
    except (forecast_publication.MissingPublication, forecast_publication.ExpiredPublication):
        forecast = None
    print(json.dumps({'data': digest, 'operations': operations['evidence_id'],
                      'realized': realized_digest, 'forecast_rows': len(forecast['forecasts']) if forecast else 0,
                      'future_targets': sum(forecast_publication.time(row['target_time']) > now
                                            for row in forecast['forecasts']) if forecast else 0,
                      'issue': forecast['provenance']['issue_time'] if forecast else None}))


def main():
    import grp
    import pwd
    os.umask(0o027)
    require(os.geteuid() == 0 and grp.getgrnam('powerflow-api').gr_gid == 992 and
            pwd.getpwnam('ec2-user').pw_uid == 1000, 'PUBLISHER_IDENTITY')
    for path in (ROOT, *ROOT.parents, ROOT / 'data', ROOT / 'data/releases',
                 *(ROOT / name / suffix for name in ('forecast', 'operations', 'realized')
                   for suffix in ('', 'releases'))):
        require(path.is_dir() and path.resolve() == path and path.stat().st_uid == 0 and
                not path.stat().st_mode & 0o022, 'PUBLICATION_PATH')
    # GID inheritance is needed for immutable operational and realized files.
    for name in ('data', 'forecast', 'operations', 'realized'):
        for path in (ROOT / name, ROOT / name / 'releases'):
            require(path.stat().st_gid == 992 and path.stat().st_mode & 0o2000,
                    'PUBLICATION_GROUP')
    descriptor = os.open(ROOT / '.writer.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(SOURCE, ROOT, 1000)


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['--check']:
            check(ROOT)
        else:
            require(not sys.argv[1:], 'ARGUMENTS')
            main()
    except Exception as error:
        # Source paths, SQL contents and provider errors do not enter the journal.
        code = str(error)
        print(json.dumps({'status': 'FAILED', 'type': type(error).__name__,
                          'code': code if re.fullmatch('[A-Z_]{3,64}', code) else 'UNCLASSIFIED'}),
              flush=True)
        raise SystemExit(1)
