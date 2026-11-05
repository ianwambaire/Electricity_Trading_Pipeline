"""Fixed-source terminal operational capture. No scheduler or forecast writer.

Installed privilege boundary re-reads Prefect and persisted facts independently;
worker arguments identify only one flow and terminal state, never content/paths.
"""
import contextlib
import datetime as dt
import http.client
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import time

from .operational_evidence import InvalidEvidence, identifier, require, timestamp, UTC
from .operational_evidence_producer import bounded_json, from_snapshot, natural
from .operational_evidence_store import opened, publish_terminal

PRODUCTION = Path('/home/ec2-user/Electricity_Trading_Pipeline')
PUBLICATION = Path('/srv/powerflow/operational-publications')
DEPLOYMENT = '47e5ef51-26d0-44b6-b119-2c40d0e77397'
NAMES = {'forecast.csv', 'provenance.json', 'model.json', 'evidence.json', 'integrity.json'}


def query(flow_id, tasks=False):
    identifier(flow_id)
    require(type(tasks) is bool, 'PREFECT_SCOPE')
    path = '/api/task_runs/filter' if tasks else '/api/flow_runs/' + flow_id
    body = json.dumps({'task_runs': {'flow_run_id': {'any_': [flow_id]}}, 'limit': 100}) if tasks else None
    connection = http.client.HTTPConnection('127.0.0.1', 4200, timeout=3)
    try:
        connection.request('POST' if tasks else 'GET', path, body=body, headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        require(response.status == 200 and (response.getheader('Content-Type') or '').split(';')[0] == 'application/json', 'PREFECT_HTTP')
        raw = response.read(1000001); require(len(raw) <= 1000000, 'PREFECT_BOUND')
        def pairs(items):
            out = {}
            for key, value in items:
                require(key not in out, 'PREFECT_JSON'); out[key] = value
            return out
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: require(False, 'PREFECT_JSON'))
        require(type(result) is list and len(result) < 100 if tasks else type(result) is dict, 'PREFECT_SCHEMA')
        return result
    finally:
        connection.close()


def directory(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'SOURCE_PATH')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in path.parts[1:]:
            nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = nxt
        return fd
    except Exception:
        os.close(fd); raise


def signature(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


class Source:
    """Fixed production paths in installed entrypoint; overrides for offline fixtures."""
    def __init__(self, root=PRODUCTION, owner=1000):
        self.root, self.owner = Path(root), owner

    def file(self, folder, name, limit=100000):
        require(name in NAMES and Path(folder).parent == self.root/'data/reports/next24h_inference', 'SOURCE_PATH')
        identifier(Path(folder).name)
        parent = directory(folder)
        try:
            require(os.fstat(parent).st_uid == self.owner and not os.fstat(parent).st_mode & 0o022, 'SOURCE_METADATA')
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_NOATIME', 0), dir_fd=parent)
            with os.fdopen(fd, 'rb') as stream:
                before = os.fstat(stream.fileno())
                require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == self.owner and not before.st_mode & 0o077 and before.st_size <= limit, 'SOURCE_METADATA')
                raw = stream.read(limit+1)
                require(len(raw) <= limit and signature(before) == signature(os.fstat(stream.fileno())) == signature(os.stat(name, dir_fd=parent, follow_symlinks=False)), 'SOURCE_CHANGED')
                return raw
        finally:
            os.close(parent)

    @contextlib.contextmanager
    def snapshot(self):
        parent = directory(self.root/'database'); fd = None; connection = None
        def journals():
            for suffix in ('-wal', '-shm', '-journal'):
                try:info = os.stat('electricity_trading.db'+suffix, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:continue
                require(stat.S_ISREG(info.st_mode) and info.st_size == 0, 'ACTIVE_JOURNAL')
        try:
            require(os.fstat(parent).st_uid == self.owner and not os.fstat(parent).st_mode & 0o022, 'SOURCE_METADATA')
            journals()
            fd = os.open('electricity_trading.db', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_NOATIME', 0), dir_fd=parent)
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_uid == self.owner and before.st_nlink == 1 and not before.st_mode & 0o022 and before.st_size <= 64*1024*1024, 'DATABASE_METADATA')
            # Linux /proc descriptor pins the approved inode. No WAL recovery,
            # journaling-mode change or SQLite sidecar creation is permitted.
            connection = sqlite3.connect('file:/proc/self/fd/'+str(fd)+'?mode=ro&immutable=1', uri=True, timeout=.25)
            # Some trusted Python builds omit extension loading entirely. Where
            # available explicitly disable it; the authorizer below also denies
            # every SQL function except substr (including load_extension).
            if hasattr(connection, 'enable_load_extension'):
                connection.enable_load_extension(False)
            connection.execute('PRAGMA query_only=ON'); connection.execute('BEGIN')
            tables = {'pipeline_runs', 'pipeline_stage_timings', 'operational_incidents'}
            connection.set_authorizer(lambda action, a, b, *_: sqlite3.SQLITE_OK if
                action == sqlite3.SQLITE_SELECT or action == sqlite3.SQLITE_READ and a in tables or
                action == sqlite3.SQLITE_FUNCTION and b == 'substr' or action == sqlite3.SQLITE_PRAGMA and a == 'query_only' and b is None else sqlite3.SQLITE_DENY)
            yield connection
            connection.close(); connection = None
            journals()
            require(signature(before) == signature(os.fstat(fd)) == signature(os.stat('electricity_trading.db', dir_fd=parent, follow_symlinks=False)), 'DATABASE_CHANGED')
        finally:
            if connection is not None:connection.close()
            if fd is not None:os.close(fd)
            os.close(parent)

    def capture(self, connection, flow):
        # Read only summaries in this exact terminal flow interval. The stable
        # identity is mandatory; old temporal-only records are never upgraded.
        deadline = time.monotonic()+2
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        try:
            cursor = connection.execute('SELECT substr(message,1,262145) FROM pipeline_runs WHERE run_time>=? AND run_time<=? LIMIT 13', (flow['start_time'], flow['end_time']))
            rows = cursor.fetchmany(13); require(len(rows) <= 12, 'RECORD_BOUND')
        finally:
            connection.set_progress_handler(None, 0)
        matches = [value for (raw,) in rows for value in [bounded_json(raw)] if value.get('prefect_flow_run_id') == flow['id']]
        require(len(matches) == 1, 'STABLE_IDENTITY_REQUIRED')
        summary = matches[0]
        receipt = summary.get('next24h_inference_receipt_id')
        if summary.get('next24h_forecast_status') not in {'GENERATED', 'UNCHANGED'}:
            require(receipt is None, 'UNEXPECTED_RECEIPT'); return []
        identifier(receipt)
        folder = self.root/'data/reports/next24h_inference'/receipt
        parent = directory(folder)
        try:
            with os.scandir(parent) as entries:
                names = []
                for entry in entries:
                    require(len(names) < 5 and not entry.is_symlink() and entry.is_file(follow_symlinks=False), 'RECEIPT_INVENTORY')
                    names.append(entry.name)
                require(set(names) == NAMES, 'RECEIPT_INVENTORY')
        finally:os.close(parent)
        return [{name: self.file(folder, name) for name in NAMES}]


def capture_terminal(flow_id, state_id, *, source=None, api=query, clock=lambda: dt.datetime.now(UTC)):
    identifier(flow_id); identifier(state_id)
    flow = api(flow_id)
    require(flow.get('id') == flow_id and flow.get('state', {}).get('id') == state_id, 'TERMINAL_STATE_CHANGED')
    natural(flow, DEPLOYMENT, clock())  # authoritative fresh read, never hook timestamps
    require(type(flow.get('run_count')) is int and flow['run_count'] == 1, 'FLOW_RETRY_UNVERIFIED')
    tasks = api(flow_id, tasks=True)
    source = source or Source()
    with source.snapshot() as connection:
        receipts = source.capture(connection, flow)
        raw, digest = from_snapshot(connection, flow, tasks, receipts, expected_deployment=DEPLOYMENT,
                                    observed_at=clock(), stable_identity=True)
    # Detect state transitions while capturing, rather than publish mixed runs.
    again = api(flow_id)
    require(all(again.get(k) == flow.get(k) for k in ('id', 'deployment_id', 'auto_scheduled', 'expected_start_time', 'start_time', 'end_time', 'state', 'run_count')), 'TERMINAL_STATE_CHANGED')
    return raw, digest


def deliver_terminal(flow_id, state_id, *, capture=capture_terminal, root=PUBLICATION,
                     publisher=publish_terminal, clock=lambda: dt.datetime.now(UTC)):
    try:
        raw, digest = capture(flow_id, state_id)
    except Exception:
        return {'status': 'FAILED', 'reason': 'CAPTURE_UNVERIFIED'}
    try:
        return publisher(root, raw, digest, clock=clock)
    except Exception:
        # Could be before OR after atomic activation; no retry or rollback.
        return {'status': 'FAILED', 'reason': 'OPERATIONAL_STORE_UNCERTAIN'}


def main(argv):
    # No root/source/body/SQL/URL/env-configurable arguments.
    try:
        require(os.getuid() == os.geteuid() == 0 and sys.platform == 'linux' and hasattr(os, 'O_NOATIME'), 'LINUX_ROOT_REQUIRED')
        require(len(argv) == 4 and argv[0] == '--flow-run' and argv[2] == '--state', 'ARGUMENTS')
        identifier(argv[1]); identifier(argv[3])
        # Provisioning/permissions are a separate authorization; never fix them here.
        for path in (PUBLICATION, *PUBLICATION.parents):
            fd = directory(path)
            try:
                info = os.fstat(fd)
                require(info.st_uid == 0 and not info.st_mode & 0o022, 'STORE_ANCESTRY')
            finally:os.close(fd)
        for path in (PUBLICATION, PUBLICATION/'releases'):
            fd = directory(path)
            try:
                info = os.fstat(fd)
                require(info.st_uid == 0 and info.st_gid == 992 and stat.S_IMODE(info.st_mode) == 0o750, 'STORE_METADATA')
            finally:os.close(fd)
        with opened(PUBLICATION):
            pass  # Verify namespace marker before any Prefect/source access.
        result = deliver_terminal(argv[1], argv[3])
        return result, 1 if result['status'] == 'FAILED' else 0
    except InvalidEvidence:
        return {'status': 'FAILED', 'reason': 'EVIDENCE_REJECTED'}, 1
    except Exception:
        # Includes unavailable source/SQLite/helper and uncertain post-switch fsync.
        # No raw exceptions, paths, data or automatic retries/rollback.
        return {'status': 'FAILED', 'reason': 'CAPTURE_OR_STORE_UNVERIFIED'}, 1
