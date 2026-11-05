"""Synthetic offline fixtures only. No production files, DB, network or models."""
import ast
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from shared import operational_evidence as c
from shared import operational_evidence_store as store

NOW = dt.datetime(2026, 11, 5, 6, 48, tzinfo=dt.timezone.utc)
FLOW = '11111111-1111-4111-8111-111111111111'
RECEIPT = '22222222-2222-4222-8222-222222222222'


def fixture():
    return {'version': 1, 'observed_at': '2026-11-05T06:48:00Z',
            'execution': {'flow_run_id': FLOW, 'deployment_id': '33333333-3333-4333-8333-333333333333',
                          'pipeline_run_id': 'a' * 32, 'scheduled_at': '2026-11-05T06:45:00Z',
                          'started_at': '2026-11-05T06:45:01Z', 'completed_at': '2026-11-05T06:47:00Z', 'outcome': 'COMPLETED'},
            'inference': {'outcome': 'GENERATED', 'task_run_id': '44444444-4444-4444-8444-444444444444',
                          'receipt_id': RECEIPT, 'issue_time': '2026-11-05T04:00:00Z', 'withholding': None},
            'delivery': {'outcome': 'PUBLISHED', 'receipt_id': RECEIPT, 'bundle_sha256': 'b' * 64, 'published_at': None},
            'provenance': {'source': 'PREFECT_AND_PERSISTED_PIPELINE', 'origin': 'NATURAL_SCHEDULE',
                           'flow_run_id': FLOW, 'pipeline_run_id': 'a' * 32, 'task_flow_run_id': FLOW}}


def encoded(b):
    raw = c.canonical(b)
    return raw, hashlib.sha256(raw).hexdigest()


def root_at(tmp_path):
    root = tmp_path.resolve() / 'operations'
    root.mkdir(mode=0o750)
    (root / 'releases').mkdir(mode=0o750)
    (root / 'contract').write_bytes(store.MARKER)
    (root / 'contract').chmod(0o640)
    return root


def test_valid_and_role_separation():
    raw, digest = encoded(fixture())
    pub = c.view(raw, digest, now=NOW)
    admin = c.view(raw, digest, now=NOW, admin=True)
    assert pub['status'] == admin['status'] == 'VALID'
    assert pub['evidence_id'] == admin['evidence_id']
    assert pub['current_execution'] == admin['current_execution']
    assert pub['forecast_eligibility'] == 'NOT_ASSESSED'
    assert 'admin' not in pub and RECEIPT not in json.dumps(pub) and FLOW not in json.dumps(pub)
    assert admin['admin']['inference']['receipt_id'] == RECEIPT
    assert admin['admin']['delivery']['published_at'] is None


@pytest.mark.parametrize('offset,status', [(86, 'VALID'), (87, 'STALE'), (88, 'STALE')])
def test_stale_boundary_is_scheduled_time_not_observation(offset, status):
    raw, digest = encoded(fixture())
    result = c.view(raw, digest, now=NOW + dt.timedelta(minutes=offset), admin=True)
    assert result['status'] == status
    if status == 'STALE':
        assert result['current_execution'] is None and 'admin' not in result


def test_reobserving_old_run_cannot_refresh_it():
    b = fixture(); b['observed_at'] = '2026-11-05T09:00:00Z'
    assert c.view(*encoded(b), now=NOW + dt.timedelta(hours=3))['status'] == 'STALE'


@pytest.mark.parametrize('bad', ['2026-11-05T06:48:00', '2026-11-05T09:48:00+03:00', 'yesterday', '2026-02-31T06:48:00Z', None, {}])
def test_bad_utc_timestamps(bad):
    b = fixture(); b['observed_at'] = bad
    assert c.view(*encoded(b), now=NOW)['status'] == 'INVALID'


@pytest.mark.parametrize('section,key,value', [
    ('provenance', 'flow_run_id', RECEIPT), ('provenance', 'pipeline_run_id', 'c'*32),
    ('provenance', 'task_flow_run_id', RECEIPT), ('provenance', 'origin', 'MANUAL'),
    ('execution', 'flow_run_id', '../../escape'), ('execution', 'pipeline_run_id', FLOW),
    ('execution', 'outcome', 'SUCCESS'), ('execution', 'outcome', []),
    ('execution', 'completed_at', '2026-11-05T06:44:00Z'),
    ('delivery', 'receipt_id', FLOW), ('delivery', 'bundle_sha256', '../secret'),
    ('delivery', 'published_at', '2026-11-05T09:00:00Z'),
    ('inference', 'receipt_id', None), ('inference', 'task_run_id', None),
    ('inference', 'withholding', {'reason': 'secret-value', 'gate': 'UNKNOWN'}),
])
def test_conflicting_or_malformed_fields(section, key, value):
    b = fixture(); b[section][key] = value
    assert c.view(*encoded(b), now=NOW)['status'] == 'INVALID'


def withheld():
    b = fixture()
    b['inference'].update(outcome='WITHHELD', receipt_id=None, issue_time=None,
                          withholding={'reason': 'INPUTS_UNAVAILABLE', 'gate': 'JOINT_PRICE_LOAD_HOUR'})
    b['delivery'].update(outcome='SKIPPED_WITHHELD', receipt_id=None, bundle_sha256=None)
    return b


def test_withholding_missing_receipt_expected_and_detail_admin_only():
    b = withheld()
    pub = c.view(*encoded(b), now=NOW)
    adm = c.view(*encoded(b), now=NOW, admin=True)
    assert pub['status'] == adm['status'] == 'VALID'
    assert 'JOINT_PRICE_LOAD_HOUR' not in json.dumps(pub)
    assert adm['admin']['inference']['withholding']['gate'] == 'JOINT_PRICE_LOAD_HOUR'
    b['inference']['withholding'] = None
    assert c.view(*encoded(b), now=NOW)['status'] == 'VALID'  # unknown detail is not invented


@pytest.mark.parametrize('outcome', ['PUBLISHED', 'SKIPPED_DUPLICATE', 'SKIPPED_EXPIRED', 'REJECTED_OLDER_ISSUE'])
def test_withheld_cannot_claim_generated_delivery(outcome):
    b = withheld(); b['delivery']['outcome'] = outcome
    assert c.view(*encoded(b), now=NOW)['status'] == 'INVALID'


def test_pipeline_failure_is_independent_of_prior_inference_success():
    b = fixture(); b['execution']['outcome'] = 'FAILED'
    assert c.view(*encoded(b), now=NOW)['status'] == 'VALID'
    b['delivery'].update(outcome='FAILED', receipt_id=None, bundle_sha256=None)
    assert c.view(*encoded(b), now=NOW)['status'] == 'VALID'


def test_missing_invalid_and_no_historical_fallback(tmp_path):
    assert c.view(now=NOW)['status'] == 'MISSING'
    assert store.read_current(tmp_path / 'missing', now=NOW)['status'] == 'MISSING'
    for raw in [b'{}', b'{"version":1,"version":1}', b'{"secret":"do-not-expose"}', b'[' * 2000, b'x' * (c.MAX_BYTES+1)]:
        result = c.view(raw, hashlib.sha256(raw).hexdigest(), now=NOW)
        assert result['status'] == 'INVALID' and result['current_execution'] is None
        assert 'do-not-expose' not in json.dumps(result)
    root = root_at(tmp_path)
    assert store.read_current(root, now=NOW)['status'] == 'MISSING'
    os.symlink('releases/' + 'a'*64, root/'current')
    assert store.read_current(root, now=NOW)['status'] == 'INVALID'


def test_atomic_publication_and_recovery(tmp_path):
    root = root_at(tmp_path)
    one, h1 = encoded(fixture())
    store.publish(root, one, h1, None, clock=lambda: NOW)
    b = fixture(); b['observed_at'] = '2026-11-05T06:49:00Z'
    two, h2 = encoded(b)
    result = store.publish(root, two, h2, h1, clock=lambda: NOW+dt.timedelta(minutes=1))
    assert result['previous'] == h1
    assert store.read_current(root, now=NOW+dt.timedelta(minutes=1))['evidence_id'] == h2
    store.restore(root, h2, h1, clock=lambda: NOW+dt.timedelta(minutes=1))
    assert store.read_current(root, now=NOW+dt.timedelta(minutes=1))['evidence_id'] == h1
    assert (root/'releases'/h2/'evidence.json').read_bytes() == two
    assert store.publish(root, one, h1, h1, clock=lambda: NOW)['outcome'] == 'UNCHANGED'
    with pytest.raises(c.InvalidEvidence, match='STALE'):
        store.restore(root, h1, h2, clock=lambda: NOW+dt.timedelta(hours=2))


@pytest.mark.parametrize('failure', ['replace', 'file_fsync', 'recheck_expiry'])
def test_failed_update_keeps_previous_pointer(tmp_path, monkeypatch, failure):
    root = root_at(tmp_path); raw, old = encoded(fixture())
    store.publish(root, raw, old, None, clock=lambda: NOW)
    b = fixture(); b['observed_at'] = '2026-11-05T06:49:00Z'; new, digest = encoded(b)
    clock = lambda: NOW+dt.timedelta(minutes=1)
    if failure == 'replace':
        monkeypatch.setattr(store.os, 'replace', lambda *a, **k: (_ for _ in ()).throw(OSError('private detail')))
    elif failure == 'file_fsync':
        monkeypatch.setattr(store.os, 'fsync', lambda *a: (_ for _ in ()).throw(OSError('private detail')))
    else:
        times = iter([NOW+dt.timedelta(minutes=1)]*3 + [NOW+dt.timedelta(hours=2)])
        clock = lambda: next(times)
    with pytest.raises((OSError, c.InvalidEvidence)):
        store.publish(root, new, digest, old, clock=clock)
    assert store.read_current(root, now=NOW+dt.timedelta(minutes=1))['evidence_id'] == old


@pytest.mark.parametrize('iteration', range(100))
def test_concurrent_readers_never_mix_content(tmp_path, iteration):
    root = root_at(tmp_path); raw, old = encoded(fixture())
    store.publish(root, raw, old, None, clock=lambda: NOW)
    b = fixture(); b['observed_at'] = '2026-11-05T06:49:00Z'; new, digest = encoded(b)
    def reader(_):
        return [store.read_current(root, now=NOW+dt.timedelta(minutes=1)) for _ in range(25)]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(reader, n) for n in range(4)]
        store.publish(root, new, digest, old, clock=lambda: NOW+dt.timedelta(minutes=1))
        results = [r for f in futures for r in f.result()]
    assert all(r['status'] == 'VALID' and r['evidence_id'] in {old, digest} for r in results), json.dumps([r for r in results if r['status'] != 'VALID'])
    assert all(r['observed_at'] == ('2026-11-05T06:48:00Z' if r['evidence_id'] == old else '2026-11-05T06:49:00Z') for r in results)


def test_conflict_older_run_and_terminal_drift_rejected(tmp_path):
    root = root_at(tmp_path); raw, digest = encoded(fixture())
    store.publish(root, raw, digest, None, clock=lambda: NOW)
    with pytest.raises(c.InvalidEvidence, match='CONFLICT'):
        store.publish(root, raw, digest, None, clock=lambda: NOW)
    b = fixture(); b['execution']['scheduled_at'] = '2026-11-05T05:45:00Z'
    with pytest.raises(c.InvalidEvidence, match='OLDER_RUN'):
        store.publish(root, *encoded(b), digest, clock=lambda: NOW)
    b = fixture(); b['execution']['outcome'] = 'FAILED'
    with pytest.raises(c.InvalidEvidence, match='TERMINAL_DRIFT'):
        store.publish(root, *encoded(b), digest, clock=lambda: NOW)


@pytest.mark.parametrize('kind', ['root_link', 'release_link', 'pointer_escape', 'writable_root', 'incomplete_release', 'missing_marker'])
def test_unsafe_store_fails_closed(tmp_path, kind):
    root = root_at(tmp_path); raw, digest = encoded(fixture())
    if kind == 'root_link':
        alias = tmp_path.resolve()/'alias'; alias.symlink_to(root); root = alias
    elif kind == 'release_link':
        (root/'releases').rmdir(); (root/'releases').symlink_to(tmp_path.resolve())
    elif kind == 'pointer_escape':
        os.symlink('../../outside', root/'current')
    elif kind == 'writable_root':root.chmod(0o777)
    elif kind == 'incomplete_release':(root/'releases'/digest).mkdir(mode=0o750)
    else:(root/'contract').unlink()
    with pytest.raises((OSError, c.InvalidEvidence)):
        store.publish(root, raw, digest, None, clock=lambda: NOW)


def test_forecast_store_is_never_modified(tmp_path):
    forecast = tmp_path.resolve()/'forecast-publications'
    forecast.mkdir(); (forecast/'current').symlink_to('releases/'+'c'*64)
    (forecast/'sentinel').write_bytes(b'untouched forecast bytes')
    before = sorted((p.name, p.readlink().as_posix() if p.is_symlink() else p.read_bytes()) for p in forecast.iterdir())
    with pytest.raises((OSError, c.InvalidEvidence)):
        store.publish(forecast, *encoded(fixture()), None, clock=lambda: NOW)
    operations = root_at(tmp_path)
    store.publish(operations, *encoded(fixture()), None, clock=lambda: NOW)
    after = sorted((p.name, p.readlink().as_posix() if p.is_symlink() else p.read_bytes()) for p in forecast.iterdir())
    assert before == after


def test_python39_and_dependency_boundary():
    for module in (c, store):
        text = Path(module.__file__).read_text()
        tree = ast.parse(text, feature_version=(3, 9))
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        assert all(not any(x in ast.unparse(n) for x in ('boto', 'requests', 'sqlite', 'prefect', 'forecast_publication')) for n in imports)
        assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {'eval', 'exec'} for n in ast.walk(tree))


@pytest.mark.parametrize('outcome', ['SCHEDULED', 'PENDING', 'RUNNING', 'FAILED', 'CANCELLED', 'CRASHED'])
def test_noncompleted_execution_is_explicit(outcome):
    b = fixture(); b['execution']['outcome'] = outcome
    b['inference'].update(outcome='NOT_RUN', task_run_id=None, receipt_id=None, issue_time=None)
    b['delivery'].update(outcome='NOT_RUN', receipt_id=None, bundle_sha256=None)
    b['provenance']['task_flow_run_id'] = None
    if outcome in {'SCHEDULED', 'PENDING'}:
        b['execution'].update(started_at=None, completed_at=None, pipeline_run_id=None)
        b['provenance']['pipeline_run_id'] = None
    if outcome == 'RUNNING':b['execution']['completed_at'] = None
    result = c.view(*encoded(b), now=NOW)
    assert result['status'] == 'VALID'
    assert result['current_execution']['execution_outcome'] == outcome
    assert result['forecast_eligibility'] == 'NOT_ASSESSED'


def test_current_file_symlink_and_hash_tamper_rejected(tmp_path):
    root = root_at(tmp_path); raw, digest = encoded(fixture())
    store.publish(root, raw, digest, None, clock=lambda: NOW)
    evidence = root/'releases'/digest/'evidence.json'
    evidence.write_bytes(raw + b' ')
    assert store.read_current(root, now=NOW)['status'] == 'INVALID'
    evidence.unlink(); evidence.symlink_to(root/'contract')
    assert store.read_current(root, now=NOW)['status'] == 'INVALID'


def test_permissions_and_ownership_fail_closed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    root = root_at(tmp_path); raw, digest = encoded(fixture())
    store.publish(root, raw, digest, None, clock=lambda: NOW)
    evidence = root/'releases'/digest/'evidence.json'
    evidence.chmod(0o666)
    assert store.read_current(root, now=NOW)['status'] == 'INVALID'
    evidence.chmod(0o640)
    real = store.os.fstat
    def unexpected_owner(fd):
        original = real(fd)
        return SimpleNamespace(st_mode=original.st_mode, st_uid=os.geteuid()+10001)
    monkeypatch.setattr(store.os, 'fstat', unexpected_owner)
    assert store.read_current(root, now=NOW)['status'] == 'INVALID'


def test_post_switch_sync_failure_is_uncertain_success(tmp_path, monkeypatch):
    root = root_at(tmp_path); raw, old = encoded(fixture())
    store.publish(root, raw, old, None, clock=lambda: NOW)
    b = fixture(); b['observed_at'] = '2026-11-05T06:49:00Z'; raw, digest = encoded(b)
    real = store.os.fsync
    inode = root.stat().st_ino
    def failed_root_sync(fd):
        if os.fstat(fd).st_ino == inode:raise OSError('sync failure')
        real(fd)
    monkeypatch.setattr(store.os, 'fsync', failed_root_sync)
    with pytest.raises(OSError):
        store.publish(root, raw, digest, old, clock=lambda: NOW+dt.timedelta(minutes=1))
    assert store.read_current(root, now=NOW+dt.timedelta(minutes=1))['evidence_id'] == digest
    assert (root/'releases'/old/'evidence.json').is_file()


def test_restrictive_umask_does_not_remove_reader_access(tmp_path):
    root = root_at(tmp_path); raw, digest = encoded(fixture())
    mask = os.umask(0o077)
    try:store.publish(root, raw, digest, None, clock=lambda: NOW)
    finally:os.umask(mask)
    assert (root/'releases'/digest).stat().st_mode & 0o777 == 0o750
    assert (root/'releases'/digest/'evidence.json').stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize('issue', ['2026-11-05T06:46:00Z', '2026-11-05T04:00:01Z'])
def test_issue_cannot_postdate_start_or_be_off_hour(issue):
    b = fixture(); b['inference']['issue_time'] = issue
    with pytest.raises(c.InvalidEvidence):c.validate(*encoded(b), NOW)


def test_alternate_utc_spelling_cannot_bypass_identity_guard(tmp_path):
    root = root_at(tmp_path); raw, old = encoded(fixture())
    store.publish(root, raw, old, None, clock=lambda: NOW)
    b = fixture(); b['execution']['scheduled_at'] = '2026-11-05T06:45:00+00:00'
    b['execution']['flow_run_id'] = RECEIPT
    b['provenance'].update(flow_run_id=RECEIPT, task_flow_run_id=RECEIPT)
    with pytest.raises(c.InvalidEvidence, match='IDENTITY'):
        store.publish(root, *encoded(b), old, clock=lambda: NOW)


def test_reader_pins_old_pointer_even_when_unlinked_during_read(tmp_path, monkeypatch):
    root = root_at(tmp_path); raw, old = encoded(fixture())
    store.publish(root, raw, old, None, clock=lambda: NOW)
    b = fixture(); b['observed_at'] = '2026-11-05T06:49:00Z'; new, digest = encoded(b)
    store.publish(root, new, digest, old, clock=lambda: NOW+dt.timedelta(minutes=1))
    store.restore(root, digest, old, clock=lambda: NOW+dt.timedelta(minutes=1))
    pending = root/'.fixture-pointer'; pending.write_text(digest+'\n'); pending.chmod(0o640)
    inode = (root/'current').stat().st_ino
    original = store.metadata
    switched = []
    def replace_after_open(fd, directory=False):
        if not switched and os.fstat(fd).st_ino == inode:
            os.replace(pending, root/'current'); switched.append(True)
            assert os.fstat(fd).st_nlink == 0
        return original(fd, directory)
    monkeypatch.setattr(store, 'metadata', replace_after_open)
    selected = store.read_current(root, now=NOW+dt.timedelta(minutes=1))
    assert switched and selected['status'] == 'VALID' and selected['evidence_id'] == old
    assert store.read_current(root, now=NOW+dt.timedelta(minutes=1))['evidence_id'] == digest


@pytest.mark.parametrize('raw', [b'releases/' + b'a'*64, b'x'*20000, b'../private\n'])
def test_pointer_is_exact_bounded_hash_only(tmp_path, raw):
    root = root_at(tmp_path)
    (root/'current').write_bytes(raw); (root/'current').chmod(0o640)
    result = store.read_current(root, now=NOW)
    assert result['status'] == 'INVALID' and result['current_execution'] is None
