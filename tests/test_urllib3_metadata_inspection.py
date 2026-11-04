"""Offline bounded metadata observations; no SDK imports or remote activity."""
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
HERE = ROOT / 'deploy/staging/forecast-publication/urllib3-metadata-inspection'
V3 = ROOT / 'deploy/staging/forecast-publication/load-source-check-aws-v3'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


r = module(HERE / 'run.py', 'metadata_runner_test')


class LinuxView:
    """Temporary real files; only Linux owner IDs and injected races simulated."""
    def __init__(self):
        self.owners = {}
        self.before_open = None
    def __getattr__(self, name): return getattr(os, name)
    def view(self, info):
        values = {name: getattr(info, name) for name in ['st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode']}
        values.update(st_uid=self.owners.get(info.st_ino, 1000), st_gid=1000)
        return types.SimpleNamespace(**values)
    def stat(self, *args, **kwargs): return self.view(os.stat(*args, **kwargs))
    def fstat(self, *args): return self.view(os.fstat(*args))
    def open(self, path, flags, *args, **kwargs):
        if self.before_open:
            self.before_open(path, flags)
        return os.open(path, flags, *args, **kwargs)


@pytest.fixture
def fixture(tmp_path):
    original = b'Name: urllib3\nVersion: 2.7.0\n\nFixture metadata description\n'
    lock = {'files': {'urllib3-2.7.0.dist-info/METADATA': {'bytes': len(original), 'sha256': hashlib.sha256(original).hexdigest()}}}
    raw = (V3 / 'inspect.py').read_bytes()
    fs = {'__name__': 'fs_fixture'}
    source = b'import os,stat,errno\nfrom pathlib import Path\n' + r.select_source(raw,
        {'location', 'fail', 'require', 'identity', 'filesystem_failure', 'directory_fd', 'metadata'},
        {'VerificationFailure'}, {'CATEGORIES'})
    exec(compile(source, '<fixture-fs>', 'exec'), fs)
    space = {'__name__': 'metadata_fixture', 'H': {'ROOT': tmp_path}, 'F': fs, 'SDK_LOCK': lock,
             'RUNTIME_CHECK': lambda: None}
    exec(compile((HERE / 'inspect.py').read_bytes(), '<fixture-inspector>', 'exec'), space)
    space['SITE'] = tmp_path
    view = LinuxView()
    space['os'] = fs['os'] = view
    def install(version='2.7.0', content=None):
        path = tmp_path / ('urllib3-' + version + '.dist-info')
        path.mkdir(mode=0o755)
        (path / 'METADATA').write_bytes(content if content is not None else original.replace(b'2.7.0', version.encode()))
        (path / 'METADATA').chmod(0o644)
        return path
    return space, install


def report(space, capsys):
    code = space['main']()
    result = json.loads(capsys.readouterr().out)
    assert code == (0 if result['status'] == 'PASS' else 1)
    return result


def test_expected_layout(fixture, capsys):
    s, install = fixture
    install()
    value = report(s, capsys)
    assert value['status'] == 'PASS' and value['layout'] == 'EXPECTED'
    assert value['expected_directory'] and value['expected_metadata']
    assert value['entries'] == [{'identifier': 'urllib3-2.7.0.dist-info/METADATA', 'version': '2.7.0', 'classification': 'LOCK_MATCH'}]


def test_different_version_not_accepted_as_sdk_match(fixture, capsys):
    s, install = fixture
    install('2.6.0')
    value = report(s, capsys)
    assert value['layout'] == 'DIFFERENT_VERSION' and not value['expected_directory']
    assert value['entries'][0]['classification'] == 'VERSION_MISMATCH'


def test_missing_directory(fixture, capsys):
    s, _ = fixture
    value = report(s, capsys)
    assert value['layout'] == 'MISSING' and value['entries'] == []


def test_missing_metadata(fixture, capsys):
    s, install = fixture
    (install() / 'METADATA').unlink()
    value = report(s, capsys)
    assert value['layout'] == 'INCOMPLETE' and value['expected_directory'] and not value['expected_metadata']


def test_multiple_directories(fixture, capsys):
    s, install = fixture
    install('2.6.0'); install()
    value = report(s, capsys)
    assert value['layout'] == 'MULTIPLE' and len(value['entries']) == 2


@pytest.mark.parametrize('raw', [b'Name: PRIVATE\nVersion: 2.7.0\n', b'Name: urllib3\nVersion: SECRET\n',
                                b'Name: urllib3\nVersion: 2.7.0\nVersion: 2.7.0\n',
                                b'No headers\n', b'Name: urllib3\n\nVersion: 2.7.0\n'])
def test_malformed_metadata_redacted(fixture, capsys, raw):
    s, install = fixture
    install(content=raw)
    value = report(s, capsys)
    assert value['failure']['category'] == 'MALFORMED_METADATA'
    assert 'SECRET' not in json.dumps(value) and 'PRIVATE' not in json.dumps(value)


def test_hash_mismatch_keeps_lock_unchanged(fixture, capsys):
    s, install = fixture
    original = json.dumps(s['SDK_LOCK'], sort_keys=True)
    install(content=b'Name: urllib3\nVersion: 2.7.0\n\nDifferent description\n')
    value = report(s, capsys)
    assert value['layout'] == 'HASH_MISMATCH'
    assert json.dumps(s['SDK_LOCK'], sort_keys=True) == original


@pytest.mark.parametrize('target', ['directory', 'metadata'])
def test_symlinks(fixture, capsys, target):
    s, install = fixture
    path = install()
    if target == 'directory':
        path.rename(s['SITE'] / 'outside')
        path.symlink_to(s['SITE'] / 'outside', target_is_directory=True)
    else:
        (path / 'METADATA').unlink()
        (path / 'METADATA').symlink_to('/private-secret-not-read')
    value = report(s, capsys)
    assert value['status'] == 'BLOCKED' and value['failure']['category'] == 'SYMLINK_OR_PATH_VIOLATION'
    assert 'private-secret' not in json.dumps(value)


def test_metadata_substitution(fixture, capsys):
    s, install = fixture
    path = install()
    def substitute(name, flags):
        if name == 'METADATA':
            s['os'].before_open = None
            (path / 'METADATA').rename(path / 'old')
            (path / 'METADATA').write_bytes(b'Name: urllib3\nVersion: 2.7.0\n')
    s['os'].before_open = substitute
    value = report(s, capsys)
    assert value['status'] == 'BLOCKED' and value['failure']['category'] == 'SYMLINK_OR_PATH_VIOLATION'


@pytest.mark.parametrize('directory', [True, False])
def test_owner_violation(fixture, capsys, directory):
    s, install = fixture
    path = install()
    s['os'].owners[(path if directory else path / 'METADATA').stat().st_ino] = 2000
    value = report(s, capsys)
    assert value['failure']['category'] == 'OWNER_MISMATCH'


@pytest.mark.parametrize('directory,mode', [(True, 0o777), (False, 0o666), (False, 0o200)])
def test_permission_violation(fixture, capsys, directory, mode):
    s, install = fixture
    path = install()
    (path if directory else path / 'METADATA').chmod(mode)
    assert report(s, capsys)['failure']['category'] == 'PERMISSION_MISMATCH'


def test_unexpected_names_masked_unrelated_entries_not_opened(fixture, capsys):
    s, _ = fixture
    (s['SITE'] / 'unrelated-secret').write_text('not inspected')
    assert report(s, capsys)['layout'] == 'MISSING'
    (s['SITE'] / 'urllib3-PRIVATE.dist-info').mkdir()
    value = report(s, capsys)
    assert value['failure']['category'] == 'UNEXPECTED_LAYOUT'
    assert value['failure']['dependency_id'] == 'URLLIB3_METADATA'
    assert 'PRIVATE' not in json.dumps(value) and 'unrelated-secret' not in json.dumps(value)


def test_metadata_bound(fixture, capsys):
    s, install = fixture
    install(content=b'x' * 65537)
    assert report(s, capsys)['failure']['category'] == 'BOUND_EXCEEDED'


def test_directory_count_bound(fixture, capsys):
    s, install = fixture
    for i in range(9): install('2.' + str(i))
    assert report(s, capsys)['failure']['category'] == 'BOUND_EXCEEDED'


@pytest.mark.parametrize('target', ['directory', 'metadata'])
def test_conflicting_file_type(fixture, capsys, target):
    s, install = fixture
    if target == 'directory':
        (s['SITE'] / 'urllib3-2.7.0.dist-info').write_text('not a directory')
    else:
        path = install()
        (path / 'METADATA').unlink()
        (path / 'METADATA').mkdir()
    assert report(s, capsys)['failure']['category'] == 'FILE_TYPE_MISMATCH'


def test_site_symlink_rejected(fixture, capsys, tmp_path):
    s, install = fixture
    install()
    s['SITE'] = tmp_path / 'link'
    s['SITE'].symlink_to(tmp_path, target_is_directory=True)
    assert report(s, capsys)['failure']['category'] == 'SYMLINK_OR_PATH_VIOLATION'


def test_no_file_or_metadata_mutations(fixture, capsys):
    s, install = fixture
    install()
    def snapshot():
        return {str(p.relative_to(s['SITE'])): (p.lstat().st_mode, p.lstat().st_mtime_ns,
                p.read_bytes() if p.is_file() else None) for p in s['SITE'].rglob('*')}
    before = snapshot()
    assert report(s, capsys)['status'] == 'PASS'
    assert snapshot() == before


def test_runtime_failure_has_no_metadata_access(fixture, capsys):
    s, _ = fixture
    def runtime(): raise ValueError('/PRIVATE SECRET')
    s['RUNTIME_CHECK'] = runtime
    def forbidden(*args, **kwargs): pytest.fail('metadata lookup after runtime failure')
    s['os'].before_open = forbidden
    value = report(s, capsys)
    assert value['failure']['stage'] == 'RUNTIME' and not value['runtime_verified']
    assert 'PRIVATE' not in json.dumps(value)


@pytest.mark.parametrize('identifier', ['../METADATA', '/private/path', 'urllib3-SECRET.dist-info/METADATA'])
def test_output_rejects_unapproved_identifiers(fixture, capsys, identifier):
    s, _ = fixture
    s['RUNTIME_CHECK'] = lambda: (_ for _ in ()).throw(ValueError())
    value = report(s, capsys)
    value['failure']['dependency_id'] = identifier
    with pytest.raises(ValueError): s['validate_report'](value)


def test_remote_read_only_and_python39():
    for path in [HERE / 'inspect.py', HERE / 'run.py', HERE / 'build.py']:
        tree = ast.parse(path.read_bytes(), feature_version=(3, 9))
        if path.name != 'inspect.py': continue
        imports = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}
        assert imports <= {'hashlib', 'json', 'os', 're', 'resource', 'stat'}
        forbidden = {'write', 'write_text', 'write_bytes', 'unlink', 'remove', 'rename', 'replace', 'mkdir', 'chmod', 'chown',
                     'system', 'popen', 'execve', 'spawn', 'connect', 'urlopen', 'request', 'client'}
        assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in forbidden for n in ast.walk(tree))
        assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {'exec', 'eval', '__import__'} for n in ast.walk(tree))


def test_manifest_closure_and_payload():
    m = json.loads((HERE / 'MANIFEST.json').read_bytes())
    blobs = {name:r.read(ROOT / name) for name in m['artifacts']}
    for name, raw in blobs.items():
        assert m['artifacts'][name] == {'bytes': len(raw), 'sha256': r.sha(raw)}
    payload = r.assemble(blobs)
    assert r.sha(payload) == m['payload_sha256']
    assert r.sha(blobs[r.V3 + 'MANIFEST.json']) == r.V3_SHA
    assert r.sha(blobs[r.V2 + 'SDK-LOCK.json']) == r.LOCK_SHA
    for forbidden in [b'get_aws_secret', b'import boto3', b'configured_environment', b'child_run', b'urlopen', b'IMDS']:
        assert forbidden not in payload


@pytest.mark.parametrize('failure', [None, 'LOCAL_TIMEOUT', 'SSH_FAILURE'])
def test_one_bounded_supervisor_attempt_and_private_sanitized_evidence(tmp_path, failure):
    calls = []
    (tmp_path / 'preflight').mkdir()
    wrapper = {'profile': lambda: 'fixture-profile', 'ssh_argv': lambda p: ['fixture-ssh', 'fixed-target', 'old-command'],
               'PRIVATE': tmp_path, 'failure_category': lambda code, err: 'SSH_FAILURE'}
    value = {'fixture': 'safe'}
    def supervise(argv, **kwargs):
        calls.append((argv, kwargs))
        return {'returncode': 0 if failure is None else 255, 'failure': failure,
                'stdout': json.dumps({'status': 'PASS'}).encode(), 'stderr': b'PRIVATE_RAW_DIAGNOSTIC'}
    old_mask = os.umask(0o077)
    try:
        result = r.execute(b'held-payload', wrapper, supervise, lambda raw: {'status': 'PASS', **value})
    finally:
        os.umask(old_mask)
    assert len(calls) == 1
    assert calls[0] == (['fixture-ssh', 'fixed-target', r.REMOTE],
                        {'input': b'held-payload', 'timeout': 90, 'limit': 16384, 'grace': 5})
    evidence = list((tmp_path / 'preflight').glob('urllib3-metadata-*/assessment.json'))
    assert len(evidence) == 1
    assert stat.S_IMODE(evidence[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(evidence[0].parent.stat().st_mode) == 0o700
    assert 'PRIVATE_RAW' not in evidence[0].read_text()
    assert result['failure_category'] == failure
