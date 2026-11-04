"""Offline passive SDK verifier fixtures. No remote commands or credentials."""
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'deploy/staging/forecast-publication/load-source-check-aws-v3'
V2 = ROOT / 'deploy/staging/forecast-publication/load-source-check-aws-v2'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


r = module(HERE / 'run.py', 'sdk_v3_runner_test')
v2 = module(V2 / 'run.py', 'sdk_v2_runner_test')


class LinuxView:
    """Real temporary filesystem; simulate only Linux pipeline owner IDs."""
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


def verifier(lock, site):
    space = {'__name__': 'sdk_v3_fixture', 'H': {'ROOT': Path('/fixture')}, 'SDK_LOCK': lock}
    exec(compile((HERE / 'inspect.py').read_bytes(), '<sdk-v3-fixture>', 'exec'), space)
    space['SITE'] = site
    space['os'] = LinuxView()
    return space


@pytest.fixture
def fixture(tmp_path):
    files = {'pkg/__init__.py': b'# approved fixture\n', 'pkg/data.json': b'{"fixture":true}',
             'pkg-1.0.dist-info/METADATA': b'Name: pkg\nVersion: 1.0\n'}
    for name, raw in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.parent.chmod(0o755)
        p.write_bytes(raw)
        p.chmod(0o644)
    lock = {'files': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in files.items()},
            'code_roots': ['pkg'], 'versions': {'pkg': '1.0'}, 'runtime': [3, 14], 'version': 1}
    return verifier(lock, tmp_path), files


def failure(space):
    with pytest.raises(space['VerificationFailure']):
        space['sdk_files']()
    return space['STATE']


def test_all_match_and_zero_sdk_or_network_access(fixture):
    space, files = fixture
    assert space['sdk_files']() == files
    assert space['STATE'] == {'dependency_id': None, 'category': None, 'stage': 'COMPLETE', 'verified_files': 3}


@pytest.mark.parametrize('name,stage,count', [('pkg/__init__.py', 'CODE_INVENTORY', 0),
                                           ('pkg/data.json', 'FILE_METADATA', 2)])
def test_missing_approved_file(fixture, name, stage, count):
    space, _ = fixture
    (space['SITE'] / name).unlink()
    report = failure(space)
    assert report == {'dependency_id': name, 'category': 'FILE_MISSING', 'stage': stage, 'verified_files': count}


def test_hash_and_size_change(fixture):
    space, _ = fixture
    (space['SITE'] / 'pkg/data.json').write_bytes(b'PRIVATE_CONTENT_CHANGED')
    report = failure(space)
    assert report == {'dependency_id': 'pkg/data.json', 'category': 'HASH_MISMATCH', 'stage': 'FILE_INTEGRITY', 'verified_files': 2}
    assert 'PRIVATE' not in json.dumps(report)


@pytest.mark.parametrize('mode', [0o666, 0o200])
def test_permissions_not_relaxed(fixture, mode):
    space, _ = fixture
    (space['SITE'] / 'pkg/data.json').chmod(mode)
    report = failure(space)
    assert report['category'] == 'PERMISSION_MISMATCH' and report['stage'] == 'FILE_METADATA'
    assert report['dependency_id'] == 'pkg/data.json'


def test_owner_not_relaxed(fixture):
    space, _ = fixture
    inode = (space['SITE'] / 'pkg/data.json').stat().st_ino
    space['os'].owners[inode] = 2000
    assert failure(space)['category'] == 'OWNER_MISMATCH'


def test_directory_owner_has_safe_approved_id(fixture):
    space, _ = fixture
    space['os'].owners[(space['SITE'] / 'pkg').stat().st_ino] = 2000
    report = failure(space)
    assert report['category'] == 'OWNER_MISMATCH' and report['stage'] == 'CODE_DIRECTORY'
    assert report['dependency_id'] in {'pkg', 'SDK_PACKAGE:pkg'}


def test_file_type_mismatch(fixture):
    space, _ = fixture
    p = space['SITE'] / 'pkg/data.json'
    p.unlink()
    p.mkdir()
    assert failure(space)['category'] == 'FILE_TYPE_MISMATCH'


def test_symlink_does_not_read_target(fixture, tmp_path):
    space, _ = fixture
    p = space['SITE'] / 'pkg/data.json'
    p.unlink()
    p.symlink_to(tmp_path / 'PRIVATE_UNAPPROVED_TARGET')
    report = failure(space)
    assert report['category'] == 'SYMLINK_OR_PATH_VIOLATION'
    assert report['dependency_id'] == 'pkg/data.json' and 'PRIVATE' not in json.dumps(report)


def test_substitution_between_metadata_and_open(fixture, tmp_path):
    space, _ = fixture
    p = space['SITE'] / 'pkg/data.json'
    called = []
    def substitute(name, flags):
        if name == 'data.json' and not flags & os.O_DIRECTORY and not called:
            called.append(True)
            p.unlink()
            p.symlink_to(tmp_path / 'PRIVATE_TARGET')
    space['os'].before_open = substitute
    report = failure(space)
    assert report['category'] == 'SYMLINK_OR_PATH_VIOLATION' and report['stage'] == 'FILE_OPEN'
    assert report['verified_files'] == 2 and called == [True]


def test_unknown_inventory_name_never_reported(fixture):
    space, _ = fixture
    (space['SITE'] / 'pkg/PRIVATE_SECRET_FILENAME.py').write_bytes(b'PRIVATE_BODY')
    report = failure(space)
    assert report['category'] == 'SDK_VERSION_OR_LAYOUT_MISMATCH'
    assert report['dependency_id'] == 'SDK_INVENTORY'
    assert 'PRIVATE' not in json.dumps(report)


def test_native_extension_layout_rejected_without_disclosure(fixture):
    space, _ = fixture
    (space['SITE'] / 'pkg/PRIVATE_NATIVE.so').write_bytes(b'private fixture')
    report = failure(space)
    assert report['category'] == 'SDK_VERSION_OR_LAYOUT_MISMATCH'
    assert report['dependency_id'] == 'SDK_PACKAGE:pkg'


def test_changed_metadata_version_not_accepted_or_disclosed(fixture):
    space, _ = fixture
    (space['SITE'] / 'pkg-1.0.dist-info/METADATA').write_bytes(b'Name: pkg\nVersion: PRIVATE_INSTALLED_VERSION\n')
    report = failure(space)
    assert report['category'] == 'SDK_VERSION_OR_LAYOUT_MISMATCH'
    assert report['dependency_id'] == 'pkg-1.0.dist-info/METADATA' and report['verified_files'] == 0
    assert 'PRIVATE' not in json.dumps(report)


def test_multiple_mismatches_fail_deterministically_at_first_check(fixture):
    space, _ = fixture
    (space['SITE'] / 'pkg-1.0.dist-info/METADATA').write_bytes(b'Name: pkg\nVersion: 1.0\nPRIVATE_CHANGE\n')
    (space['SITE'] / 'pkg/data.json').write_bytes(b'PRIVATE_SECOND_CHANGE')
    report = dict(failure(space))
    assert report == dict(failure(space))
    assert report['dependency_id'] == 'pkg-1.0.dist-info/METADATA' and report['verified_files'] == 0
    assert report['category'] == 'HASH_MISMATCH'


def test_unknown_os_error_sanitized(fixture):
    space, _ = fixture
    def bad(*args, **kwargs): raise OSError(errno.EIO, 'PRIVATE_PATH_OR_TOKEN')
    space['capture_file'] = bad
    report = failure(space)
    assert report['category'] == 'OTHER_VERIFICATION_FAILURE'
    assert 'PRIVATE' not in json.dumps(report)


def test_matching_sdk_bytes_equal_v2_accepted_bytes(fixture):
    space, files = fixture
    # Exercise V2's actual verifier under the same owner-ID view. All acceptance
    # requirements remain present; diagnostic granularity does not change bytes.
    h = {'__name__': 'v2_host'}
    exec(compile(v2.host_source((ROOT / v2.OLD / 'inspect.py').read_bytes()), '<v2-host>', 'exec'), h)
    aws = module(V2 / 'sdk.py', 'v2_error_type')
    context = {'__name__': 'v2_inspector', 'H': h, 'AWS': aws.__dict__, 'SDK_LOCK': space['SDK_LOCK']}
    exec(compile((V2 / 'inspect.py').read_bytes(), '<v2-verifier>', 'exec'), context)
    context['SITE'] = space['SITE']
    context['os'] = h['os'] = space['os']
    assert context['sdk_files']() == space['sdk_files']() == files


def test_main_never_continues_to_credentials_or_source(fixture, capsys):
    space, _ = fixture
    space['resource'] = types.SimpleNamespace(setrlimit=lambda *a: None, RLIMIT_CORE=4)
    space['RUNTIME_CHECK'] = lambda: None
    assert space['main']() == 0
    report = json.loads(capsys.readouterr().out)
    assert r.validate_report(report, space)['status'] == 'PASS'
    assert report['aws_attempted'] is report['source_attempted'] is False
    (space['SITE'] / 'pkg/data.json').unlink()
    assert space['main']() == 1
    report = json.loads(capsys.readouterr().out)
    assert r.validate_report(report, space)['status'] == 'BLOCKED'
    assert report['aws_attempted'] is report['source_attempted'] is False


@pytest.mark.parametrize('field,value', [('dependency_id', '/PRIVATE/HOST/PATH'),
                                      ('dependency_id', 'pkg/PRIVATE.py'),
                                      ('category', 'PRIVATE_SECRET'), ('stage', 'PRIVATE_STAGE'),
                                      ('verified_files', True)])
def test_validator_rejects_unapproved_output(fixture, field, value):
    space, _ = fixture
    report = {'status': 'BLOCKED', 'runtime_verified': True, 'aws_attempted': False, 'source_attempted': False,
              'sdk_verification': {'dependency_id': 'pkg/data.json', 'category': 'HASH_MISMATCH', 'stage': 'FILE_INTEGRITY', 'verified_files': 2}}
    report['sdk_verification'][field] = value
    with pytest.raises(ValueError): r.validate_report(report, space)


def test_manifest_exact_closure_and_original_lock():
    m = json.loads((HERE / 'MANIFEST.json').read_bytes())
    original = (V2 / 'MANIFEST.json').read_bytes()
    assert r.sha(original) == r.V2_SHA
    blobs = {}
    for name, item in m['artifacts'].items():
        blobs[name] = (ROOT / name).read_bytes()
        assert item == {'bytes': len(blobs[name]), 'sha256': r.sha(blobs[name])}
    assert r.sha(r.assemble(blobs)) == m['payload_sha256']
    assert r.sha((V2 / 'SDK-LOCK.json').read_bytes()) == r.LOCK_SHA


def test_payload_excludes_sdk_credential_source_and_child_code():
    m = json.loads((HERE / 'MANIFEST.json').read_bytes())
    payload = r.assemble({name: (ROOT / name).read_bytes() for name in m['artifacts']})
    assert b'def get_aws_secret' not in payload and b'def child_run' not in payload
    assert b'def configured_environment' not in payload and b'def get_secret' not in payload
    assert b'import boto3' not in payload and b'169.254.169.254' not in payload
    assert b'urlopen' not in payload and b'web-api.tp.entsoe.eu' not in payload


def test_python39_and_no_mutation_code():
    import ast
    for path in [HERE / 'run.py', HERE / 'inspect.py', HERE / 'build.py']:
        ast.parse(path.read_text(), feature_version=(3, 9))
    tree = ast.parse((HERE / 'inspect.py').read_text())
    names = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not names & {'Popen', 'connect', 'mkdir', 'chmod', 'chown', 'unlink', 'rename', 'write', 'write_text', 'write_bytes'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'replace':
            # Distribution-name normalization is string processing, not Path.replace.
            assert isinstance(node.func.value, ast.Name) and node.func.value.id == 'package'
            assert [arg.value for arg in node.args] == ['-', '_']
