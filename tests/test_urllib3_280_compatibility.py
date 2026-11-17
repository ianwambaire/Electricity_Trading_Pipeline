"""Real independently pinned SDK code, mocked transports, no AWS/source requests."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'deploy/staging/forecast-publication/sdk-baseline-urllib3-2.8.0'
spec = importlib.util.spec_from_file_location('independent_urllib3_reference_test', HERE / 'reference.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def smoke_source():
    # Reuse the exact established SDK protocol tests; substitute only reference bytes.
    r.verify_sources()
    old = (ROOT / 'tests/test_load_source_aws_adapter.py').read_text()
    node = next(n for n in ast.parse(old).body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'SMOKE' for t in n.targets))
    source = ast.literal_eval(node.value)
    needle = "def denied(*args,**kwargs):raise AssertionError('REAL_NETWORK_FORBIDDEN')"
    replacement = """attempted_side_effects=[]
def denied(*args,**kwargs):
 attempted_side_effects.append('network')
 raise AssertionError('REAL_NETWORK_FORBIDDEN')
def audit(event,args):
 if event in {'socket.connect','socket.getaddrinfo','socket.gethostbyname','socket.sendto','subprocess.Popen','os.system','os.fork'}:
  attempted_side_effects.append('network_or_process')
  raise AssertionError('SIDE_EFFECT_FORBIDDEN')
 if event=='open':
  mode=args[1];flags=args[2]
  if (isinstance(mode,str) and any(v in mode for v in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)):
   attempted_side_effects.append('file_write')
   raise AssertionError('FILE_WRITE_FORBIDDEN')
sys.addaudithook(audit)
socket.socket.connect_ex=denied"""
    assert source.count(needle) == 1
    source = source.replace(needle, replacement)
    needle = "files={name:(site/name).read_bytes() for name in lock['files']}"
    replacement = """spec=importlib.util.spec_from_file_location('reference280',root/'deploy/staging/forecast-publication/sdk-baseline-urllib3-2.8.0/reference.py')
reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
files=reference.held_reference(site)
assert all(reference.baseline()['files'][n]=={'bytes':len(raw),'sha256':reference.digest(raw)} for n,raw in files.items())"""
    assert source.count(needle) == 1
    source = source.replace(needle, replacement)
    needle = 'import urllib3.connectionpool,urllib3.response'
    replacement = """import urllib3.connectionpool,urllib3.response,urllib3
assert urllib3.__version__=='2.8.0'
assert sys.version_info[:2]==(3,14)
import inspect
assert {'self','method','url','redirect','retries','preload_content'} <= set(inspect.signature(urllib3.connectionpool.HTTPConnectionPool.urlopen).parameters)
assert {'self','amt','decode_content'} <= set(inspect.signature(urllib3.response.HTTPResponse.stream).parameters)"""
    assert source.count(needle) == 1
    source = source.replace(needle, replacement)
    return source + "\nassert attempted_side_effects==[], 'SDK_ATTEMPTED_SIDE_EFFECT'\n"


@pytest.mark.parametrize('backend,scenario,expected', [
    ('ssm', 'success', 'PASS'), ('secretsmanager', 'success', 'PASS'),
    ('secretsmanager', 'binary', 'PASS'), ('ssm', 'denied', 'AWS_ACCESS_DENIED'),
    ('secretsmanager', 'denied', 'AWS_ACCESS_DENIED'), ('ssm', 'missing', 'AWS_EMPTY_SECRET'),
    ('ssm', 'body_bound', 'AWS_RESPONSE_BOUND'), ('ssm', 'header_bound', 'AWS_RESPONSE_BOUND'),
    ('ssm', 'imds_v1', 'AWS_ROLE_UNVERIFIED'), ('ssm', 'server_error', 'AWS_ACCESS_FAILED'),
    ('ssm', 'redirect', 'AWS_REQUEST_REJECTED'), ('ssm', 'bad_url', 'AWS_REQUEST_REJECTED'),
    ('ssm', 'bad_method', 'AWS_REQUEST_REJECTED'), ('ssm', 'mutation_target', 'AWS_REQUEST_REJECTED'),
    ('ssm', 'bad_identifier', 'AWS_REQUEST_REJECTED'), ('ssm', 'duplicate_identifier', 'AWS_REQUEST_REJECTED'),
])
def test_original_sdk_adapter_with_reference_urllib3_280(backend, scenario, expected):
    completed = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', smoke_source(), str(ROOT), backend, scenario],
                               capture_output=True, timeout=15, check=True)
    value = json.loads(completed.stdout)
    assert value['outcome'] == expected and value['real_network_calls'] == 0
    assert value['loaded'] > 100
    assert b'PRIVATE' not in completed.stdout and b'fixture-entsoe' not in completed.stdout


def test_reference_wheel_record_metadata_and_expected_inventory():
    files = r.wheel_files()
    assert len(files) == 37 and len(r.baseline()['files']) == 215
    assert r.verify_provenance()['local_sigstore_signature_verification'] is False
    old = r.old_lock()
    new = r.baseline()
    for name, entry in old['files'].items():
        if not name.startswith(('urllib3/', 'urllib3-')):
            assert new['files'][name] == entry
    assert 'urllib3-2.7.0.dist-info/METADATA' not in new['files']
    assert new['versions'] == {**old['versions'], 'urllib3': '2.8.0'}


def test_reference_tamper_fails_before_zip_or_execution():
    with pytest.raises(ValueError, match='independent_sdk_reference_rejected'):
        r.wheel_files(b'not an independently verified wheel')


def test_declared_dependency_constraints_and_python314():
    from email.parser import BytesParser
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    old = r.old_lock()
    held = r.held_reference(ROOT / 'venv/lib/python3.14/site-packages')
    all_versions = r.baseline()['versions']
    for name, raw in held.items():
        if not name.endswith('.dist-info/METADATA'):
            continue
        metadata = BytesParser().parsebytes(raw, headersonly=True)
        assert metadata['Version'] == all_versions[metadata['Name']]
        py = metadata.get('Requires-Python', '')
        assert SpecifierSet(py).contains('3.14.7')
        for declaration in metadata.get_all('Requires-Dist', []):
            req = Requirement(declaration)
            if req.marker and not req.marker.evaluate({'python_version':'3.14', 'python_full_version':'3.14.7', 'extra':''}):
                continue
            assert req.name in all_versions and req.specifier.contains(all_versions[req.name])
    assert old['versions']['boto3'] == old['versions']['botocore'] == '1.43.98'
    from importlib import metadata as installed
    botocore = installed.distribution('botocore')
    requirement = next(Requirement(line) for line in botocore.requires if line.startswith('urllib3 '))
    assert requirement.specifier.contains('2.8.0') and not requirement.specifier.contains('3.0.0')


def test_new_lock_and_manifest_integrity():
    value = json.loads((HERE / 'MANIFEST.json').read_bytes())
    for name, entry in value['artifacts'].items():
        raw = (ROOT / name).read_bytes()
        assert entry == {'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()}
    assert json.loads((HERE / 'SDK-LOCK.json').read_bytes()) == r.baseline()
    assert r.digest((r.V2 / 'SDK-LOCK.json').read_bytes()) == r.LOCK_SHA


def test_python39_reference_bootstrap_and_no_network_or_installation_functions():
    for name in ['reference.py', 'build.py']:
        tree = ast.parse((HERE / name).read_bytes(), feature_version=(3,9))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(n.name.split('.')[0] not in {'socket','boto3','botocore','urllib3','requests','subprocess'} for n in node.names)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {'urlopen','connect','client','system','popen','extract','extractall'}
