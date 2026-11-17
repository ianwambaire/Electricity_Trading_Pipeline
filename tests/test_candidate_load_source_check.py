"""Offline candidate-bound workflow tests. Never contacts host, AWS or ENTSO-E."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'deploy/staging/forecast-publication/load-source-check-aws-v4'
V2 = ROOT / 'deploy/staging/forecast-publication/load-source-check-aws-v2'
V3 = ROOT / 'deploy/staging/forecast-publication/load-source-check-aws-v3'
CANDIDATE = ROOT / 'deploy/staging/forecast-publication/sdk-baseline-urllib3-2.8.0'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


r = module(HERE / 'run.py', 'v4_runner_test')
base = module(ROOT / 'tests/test_load_source_aws_adapter.py', 'retained_v2_test_helpers')
v3tests = module(ROOT / 'tests/test_sdk_verification_v3.py', 'retained_v3_test_helpers')
reference = module(CANDIDATE / 'reference.py', 'candidate_byte_reference')


@pytest.fixture(scope='module')
def held():
    return reference.held_reference(ROOT / 'venv/lib/python3.14/site-packages')


@pytest.fixture
def case(tmp_path, held):
    site = tmp_path / '.venv-prod/lib/python3.14/site-packages'
    for name, raw in held.items():
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        path.write_bytes(raw)
        path.chmod(0o644)
    old = base.inspector()
    old['H']['ROOT'] = tmp_path
    space = {'__name__': 'candidate_fixture', 'H': old['H'], 'AWS': old['AWS'],
             'PROVIDER': old['PROVIDER'], 'CORE': old['CORE'], 'SOURCE_HASHES': {},
             'CHILD_SOURCE': b'held-fixture-child', 'SDK_LOCK': reference.baseline(),
             'FLOW_SOURCE': (V2 / 'inspect.py').read_bytes(), 'VERIFIER_SOURCE': (V3 / 'inspect.py').read_bytes()}
    exec(compile((HERE / 'inspect.py').read_bytes(), '<candidate-fixture>', 'exec'), space)
    view = v3tests.LinuxView()
    space['os'] = space['VERIFIER']['os'] = view
    return space, site


def workflow(case):
    space, site = case
    f, v = space['FLOW'], space['VERIFIER']
    events = []
    original = f['sdk_files']
    def gate():
        result = original()
        events.append('sdk-215')
        return result
    f['sdk_files'] = gate
    f['root_runtime'] = lambda: events.append('runtime')
    snapshot = b'timestamp,load_mw\n2026-11-03T15:00:00Z,12345\n'
    def capture(path, owner, limit, **kwargs):
        raw = b'POWERFLOW_SECRETS_BACKEND=ssm' if path.name == '.env' else snapshot if path.name == 'load.csv' else b'code'
        return raw, (1, 2, 3, 4, 5)
    h = f['H']
    h.update(capture=capture, worker=lambda: '123', worker_environment=lambda _: {},
             deployment_environment=lambda: {}, drop_identity=lambda: events.append('permanent-drop'),
             WORKER_SHA=hashlib.sha256(b'code').hexdigest())
    f['resource'] = types.SimpleNamespace(setrlimit=lambda *args: None, RLIMIT_CORE=4)
    def secret(env, content):
        assert events == ['runtime', 'sdk-215', 'permanent-drop']
        assert v['STATE']['verified_files'] == 215 and content == reference.held_reference(ROOT / 'venv/lib/python3.14/site-packages')
        events.append('aws-secret')
        f['ROLE'] = True
        return 'fixture-entsoe-secret'
    f['get_aws_secret'] = secret
    def source(callback):
        assert events[-1] == 'aws-secret' and callback('ENTSOE_API_KEY') == 'fixture-entsoe-secret'
        events.append('fixed-source')
        return b'<Acknowledgement_MarketDocument><Reason><code>999</code><text>No matching data found</text></Reason></Acknowledgement_MarketDocument>', None
    f['CORE']['request_source'] = source
    return f, v, events


def validate(value):
    schema = {'__name__': 'candidate_schema', 'H': {'ROOT': Path('/')}, 'SDK_LOCK': reference.baseline()}
    exec(compile((V3 / 'inspect.py').read_bytes(), '<schema>', 'exec'), schema)
    return r.validate_report(value, lambda x: base.r.validate_report(x, base.old.validate_report), schema)


def test_all_215_candidate_files_match(case, held):
    space, _ = case
    assert space['FLOW']['sdk_files']() == held
    assert space['VERIFIER']['STATE'] == {'dependency_id': None, 'category': None, 'stage': 'COMPLETE', 'verified_files': 215}


def test_complete_workflow_order_and_bounded_sanitized_comparison(case):
    f, v, events = workflow(case)
    value = f['inspect']()
    assert events == ['runtime', 'sdk-215', 'permanent-drop', 'aws-secret', 'fixed-source']
    assert validate(value)['status'] == 'PASS'
    assert [item['timestamp'] for item in value['comparison']['targets']] == [
        '2026-11-03T15:15:00+00:00', '2026-11-03T15:30:00+00:00', '2026-11-03T15:45:00+00:00']
    assert 'fixture-entsoe-secret' not in json.dumps(value) and '12345' not in json.dumps(value)


@pytest.mark.parametrize('fault,category', [
    ('missing', 'FILE_MISSING'), ('changed', 'HASH_MISMATCH'), ('owner', 'OWNER_MISMATCH'),
    ('permission', 'PERMISSION_MISMATCH'), ('symlink', 'SYMLINK_OR_PATH_VIOLATION'),
    ('extra-code', 'SDK_VERSION_OR_LAYOUT_MISMATCH'), ('extra-version', 'SDK_VERSION_OR_LAYOUT_MISMATCH'),
    ('metadata-owner', 'OWNER_MISMATCH'), ('metadata-permission', 'PERMISSION_MISMATCH'),
    ('wrong-version', 'FILE_MISSING'), ('wrong-metadata', 'SDK_VERSION_OR_LAYOUT_MISMATCH')])
def test_failed_integrity_never_reaches_privilege_drop_or_authentication(case, capsys, fault, category):
    space, site = case
    f, _, events = workflow(case)
    path = site / 'urllib3/util/retry.py'
    if fault == 'missing': path.unlink()
    elif fault == 'changed': path.write_bytes(b'UNTRUSTED_LOCAL_TEST_CONTENT')
    elif fault == 'owner': space['os'].owners[path.stat().st_ino] = 2000
    elif fault == 'permission': path.chmod(0o666)
    elif fault == 'symlink':
        path.unlink(); path.symlink_to('/private-data-must-not-be-read')
    elif fault == 'extra-code': (site / 'urllib3/UNAPPROVED_PRIVATE.py').write_bytes(b'ignored-code-must-fail')
    elif fault == 'extra-version': (site / 'urllib3-2.7.0.dist-info').mkdir()
    elif fault == 'metadata-owner': space['os'].owners[(site / 'urllib3-2.8.0.dist-info').stat().st_ino] = 2000
    elif fault == 'metadata-permission': (site / 'urllib3-2.8.0.dist-info').chmod(0o777)
    elif fault == 'wrong-version': (site / 'urllib3-2.8.0.dist-info/METADATA').unlink()
    elif fault == 'wrong-metadata':
        (site / 'urllib3-2.8.0.dist-info/METADATA').write_bytes(b'Name: urllib3\nVersion: 2.7.0\n')
    assert f['main']() == 1
    value = json.loads(capsys.readouterr().out)
    assert value['sdk_verification']['category'] == category
    assert events == ['runtime']
    assert value['credential_backend'] == 'UNVERIFIED' and value['source_request'] == 'NOT_ATTEMPTED'
    assert not value['iam_role_verified'] and value['comparison'] is None
    assert validate(value)['status'] == 'BLOCKED'
    for forbidden in ['UNTRUSTED', 'UNAPPROVED_PRIVATE', 'private-data-must-not-be-read', '12345']:
        assert forbidden not in json.dumps(value)


def test_identity_failure_never_reaches_credentials_or_source(case, capsys):
    f, _, events = workflow(case)
    def drop(): raise base.sdk.Blocked('SDK_IDENTITY_REJECTED')
    f['H']['drop_identity'] = drop
    assert f['main']() == 1
    value = json.loads(capsys.readouterr().out)
    assert events == ['runtime', 'sdk-215'] and value['cause'] == 'SDK_IDENTITY_REJECTED'
    assert validate(value)['sdk_verification']['stage'] == 'COMPLETE'


def test_runtime_failure_before_sdk_authentication_and_source(case, capsys):
    f, _, events = workflow(case)
    def runtime(): raise base.sdk.Blocked('SDK_RUNTIME_MISMATCH')
    f['root_runtime'] = runtime
    assert f['main']() == 1
    value = json.loads(capsys.readouterr().out)
    assert not events and value['sdk_verification']['stage'] == 'NOT_STARTED'
    assert validate(value)['cause'] == 'SDK_RUNTIME_MISMATCH'


def test_candidate_and_payload_exact_binding():
    m = json.loads((HERE / 'MANIFEST.json').read_bytes())
    blobs = {name:r.read(ROOT / name) for name in m['artifacts']}
    assert r.sha(r.assemble(blobs)) == m['payload_sha256']
    lock = r.candidate_lock(blobs)
    assert lock == reference.baseline()
    assert lock['versions']['urllib3'] == '2.8.0' and len(lock['files']) == 215
    for name, item in m['artifacts'].items():
        assert item == {'bytes': len(blobs[name]), 'sha256': r.sha(blobs[name])}
    # Candidate records are inside the actual child verification envelope too.
    payload = r.assemble(blobs)
    context = {}
    tree = ast.parse(payload)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'S' for t in node.targets):
            for key, value in zip(node.value.keys, node.value.values):
                if key.value == '__name__': value.value = 'offline_assembled_definitions'
    exec(compile(tree, '<offline-payload-definitions>', 'exec'), context)
    assembled = context['S']
    assert assembled['SDK_LOCK'] == lock and assembled['VERIFIER']['SDK_LOCK'] == lock
    child = ast.parse(assembled['CHILD_SOURCE'])
    node = next(n for n in child.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SDK_FILES' for t in n.targets))
    assert ast.literal_eval(node.value) == lock['files']
    assert sum(record['bytes'] for record in lock['files'].values()) < 6_000_000


@pytest.mark.parametrize('key', ['lock','wheel'])
def test_candidate_tamper_prevents_assembly(key):
    m = json.loads((HERE / 'MANIFEST.json').read_bytes())
    blobs = {name:r.read(ROOT / name) for name in m['artifacts']}
    blobs[r.CANDIDATE + 'SDK-LOCK.json' if key == 'lock' else r.WHEEL] += b'x'
    with pytest.raises(ValueError): r.assemble(blobs)


@pytest.mark.parametrize('fault', ['path', 'count', 'category'])
def test_output_schema_rejects_private_unrecognized_details(case, fault):
    f, _, _ = workflow(case)
    value = f['inspect']()
    detail = value['sdk_verification']
    if fault == 'path': detail['dependency_id'] = '/PRIVATE/path'
    elif fault == 'count': detail['verified_files'] = 214
    else: detail['category'] = 'SECRET'
    with pytest.raises(ValueError): validate(value)


def test_python39_grammar_and_fixed_remote_command():
    for path in [HERE / 'run.py', HERE / 'inspect.py', HERE / 'build.py']:
        ast.parse(path.read_bytes(), feature_version=(3,9))
    assert r.REMOTE == base.r.REMOTE
    assert r.LIMITS == base.r.LIMITS
    source = (HERE / 'inspect.py').read_text()
    assert 'boto3' not in source and 'urlopen' not in source and 'connect(' not in source
    tree = ast.parse(source)
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr in {'write', 'unlink', 'rename', 'chmod', 'chown', 'mkdir'} for n in ast.walk(tree))


@pytest.mark.parametrize('failure', [None, 'LOCAL_TIMEOUT', 'SSH_FAILURE'])
def test_one_bounded_supervisor_attempt_and_private_capture(tmp_path, failure):
    calls = []
    (tmp_path / 'preflight').mkdir()
    wrapper = {'profile': lambda: 'fixture', 'ssh_argv': lambda p: ['ssh-fixture', 'target-fixture', 'old-command'],
               'PRIVATE': tmp_path, 'failure_category': lambda code, stderr: 'SSH_FAILURE'}
    def supervise(argv, **kwargs):
        calls.append((argv, kwargs))
        return {'returncode': 0 if failure is None else 255, 'failure': failure,
                'stdout': b'{"status":"PASS"}', 'stderr': b'RAW_PRIVATE_DIAGNOSTICS'}
    mask = os.umask(0o077)
    try:
        result = r.execute(b'held-payload', wrapper, supervise, lambda value: value)
    finally:
        os.umask(mask)
    assert len(calls) == 1
    assert calls[0] == (['ssh-fixture', 'target-fixture', r.REMOTE],
                       {'input': b'held-payload', 'timeout': 90, 'limit': 16384, 'grace': 5})
    path = next((tmp_path / 'preflight').glob('load-source-aws-v4-*/assessment.json'))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert 'RAW_PRIVATE' not in path.read_text() and result['failure_category'] == failure
