"""All credentials, host metadata and transports are synthetic; no SSH/source I/O."""
import ast
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import ssl
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'deploy/staging/forecast-publication/load-source-check'


def module(name):
    spec = importlib.util.spec_from_file_location('test_load_' + name, HERE / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


r = module('run')
i = module('inspect')
c = module('check')


@pytest.fixture
def adapter(monkeypatch):
    parser = r.namespace((HERE / 'vendor/parser.py').read_bytes(), 'verified_dotenv_parser')
    variables = r.namespace((HERE / 'vendor/variables.py').read_bytes(), 'verified_dotenv_variables')
    provider = r.namespace(r.provider_source((ROOT / r.PROVIDER).read_bytes()), 'verified_provider')
    for key, value in {'PARSER': parser, 'VARIABLES': variables, 'PROVIDER': provider, 'CORE': c.__dict__}.items():
        monkeypatch.setattr(i, key, value, raising=False)
    return i


def test_existing_provider_and_dotenv_precedence(adapter):
    raw = b'export ENTSOE_API_KEY="${PREFIX:-default}-secret"\nPOWERFLOW_HISTORY_START_DATE=2020-01-02\n'
    env, start = adapter.configured_environment(raw, {'PREFIX': 'worker'}, {})
    assert env['ENTSOE_API_KEY'] == 'worker-secret'
    assert adapter.PROVIDER['get_secret']('ENTSOE_API_KEY', environment=env) == 'worker-secret'
    assert start == dt.datetime(2020, 1, 2, tzinfo=dt.timezone.utc)
    env, _ = adapter.configured_environment(raw, {'ENTSOE_API_KEY': 'worker-token'}, {'ENTSOE_API_KEY': 'deployment-token'})
    assert env['ENTSOE_API_KEY'] == 'deployment-token'


@pytest.mark.parametrize('backend', ['ssm', 'secretsmanager'])
def test_aws_backend_never_falls_back_or_imports_sdk(adapter, backend):
    with pytest.raises(adapter.Stop, match='AUTH_BACKEND_REQUIRES_VERIFIED_SDK'):
        adapter.configured_environment(b'ENTSOE_API_KEY=fallback-secret', {'POWERFLOW_SECRETS_BACKEND': backend}, {})
    assert 'boto3' not in adapter.PROVIDER


def test_missing_token_remains_missing(adapter):
    env, _ = adapter.configured_environment(b'', {}, {})
    with pytest.raises(adapter.PROVIDER['SecretConfigurationError']):
        adapter.PROVIDER['get_secret']('ENTSOE_API_KEY', environment=env)


@pytest.mark.parametrize('raw,inherited,code', [
    (b'ENTSOE_API_KEY="bad', {}, 'ENV_SYNTAX'),
    (b'ENTSOE_ENDPOINT_URL=https://evil.invalid/SECRET', {}, 'ENDPOINT_DRIFT'),
    (b'POWERFLOW_HISTORY_START_DATE=SECRET', {}, 'HISTORY_CONFIGURATION'),
    (b'', {'ENTSOE_ENDPOINT_URL': 'http://web-api.tp.entsoe.eu/api'}, 'ENDPOINT_DRIFT'),
])
def test_configuration_rejection(adapter, raw, inherited, code):
    with pytest.raises(adapter.Stop, match=code):
        adapter.configured_environment(raw, inherited, {})


def test_dotenv_disabled_preserved(adapter):
    env, _ = adapter.configured_environment(b'ENTSOE_API_KEY=SECRET', {'PYTHON_DOTENV_DISABLED': 'true'}, {})
    assert 'ENTSOE_API_KEY' not in env


def test_tls_context_verified_without_connecting():
    # Constructor does not resolve or connect. Test the real stdlib TLS default,
    # not a mocked claim about certificate verification.
    connection = c.http.client.HTTPSConnection(c.HOST, timeout=5)
    try:
        assert connection._context.verify_mode == ssl.CERT_REQUIRED
        assert connection._context.check_hostname is True
    finally:
        connection.close()


def deployment():
    return {'id': i.DEP, 'entrypoint': 'src/scheduled_pipeline.py:powerflow_entsoe_pipeline',
            'work_pool_name': 'electricity-pool', 'job_variables': {'env': {'POWERFLOW_AUTO_PUBLICATION_ENABLED': 'true'}}}


def pool():
    return {'type': 'process', 'base_job_template': {'job_configuration': {'env': '{{ env }}'},
                                                  'variables': {'properties': {'env': {'default': {}}}}}}


def test_exact_prefect_reads():
    calls = []
    def api(path):
        calls.append(path)
        return deployment() if path.startswith('/deployments/') else pool()
    assert i.deployment_environment(api) == {'POWERFLOW_AUTO_PUBLICATION_ENABLED': 'true'}
    assert calls == ['/deployments/' + i.DEP, '/work_pools/electricity-pool']


@pytest.mark.parametrize('change', ['identity', 'command', 'env', 'pool'])
def test_prefect_drift_rejected(change):
    d, p = deployment(), pool()
    if change == 'identity':
        d['id'] = 'unapproved'
    elif change == 'command':
        d['job_variables']['command'] = 'arbitrary-command'
    elif change == 'env':
        d['job_variables']['env'] = {'key': None}
    else:
        p['base_job_template']['job_configuration']['env'] = 'unexpected'
    with pytest.raises(i.Stop):
        i.deployment_environment(lambda path: d if path.startswith('/deployments/') else p)


def test_only_fixed_gets_no_redirects_or_proxy(monkeypatch):
    requests = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return requests[-1].full_url
        def read(self, limit):
            assert limit == 100001
            return b'{}'
    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            assert timeout == 3 and request.get_method() == 'GET'
            return Response()
    handlers = []
    def build(*args):
        handlers.extend(args)
        return Opener()
    monkeypatch.setattr(i.urllib.request, 'build_opener', build)
    assert i.prefect('/deployments/' + i.DEP) == {}
    assert requests[0].full_url == 'http://127.0.0.1:4200/api/deployments/' + i.DEP
    assert handlers[0].proxies == {}
    with pytest.raises(i.Stop, match='HTTP_STATUS'):
        handlers[1].redirect_request(None, None, None, None, None, None)
    for path in ['/deployments/' + i.DEP + '?x=1', '//evil.invalid', '/flow_runs/filter', '/deployments/other']:
        with pytest.raises(i.Stop):
            i.prefect(path)
    assert len(requests) == 1


def test_capture_metadata_no_follow_bounds(tmp_path):
    path = tmp_path / 'file'
    path.write_bytes(b'private fixture')
    path.chmod(0o600)
    assert i.capture(path, os.getuid(), 100, secret=True)[0] == b'private fixture'
    with pytest.raises(i.Stop, match='READ_BOUND'):
        i.capture(path, os.getuid(), 2)
    link = tmp_path / 'link'
    link.symlink_to(path)
    with pytest.raises(OSError):
        i.capture(link, os.getuid(), 100)
    path.chmod(0o666)
    with pytest.raises(i.Stop, match='READ_METADATA'):
        i.capture(path, os.getuid(), 100)
    with pytest.raises(i.Stop):
        i.capture(tmp_path / '..' / 'escape', os.getuid(), 100)


def test_permanent_identity_drop_and_environment_clear(monkeypatch):
    calls = []
    env = {'SSL_CERT_FILE': 'untrusted', 'HTTPS_PROXY': 'untrusted'}
    fake = types.SimpleNamespace(geteuid=lambda: 0, setgroups=lambda x: calls.append(('groups', x)),
        setresgid=lambda *x: calls.append(('gid', x)), setresuid=lambda *x: calls.append(('uid', x)),
        getresuid=lambda: (1000, 1000, 1000), getresgid=lambda: (1000, 1000, 1000), getgroups=lambda: [], environ=env)
    monkeypatch.setattr(i, 'os', fake)
    monkeypatch.setattr(i, 'pwd', types.SimpleNamespace(getpwnam=lambda _: types.SimpleNamespace(pw_uid=1000, pw_gid=1000)))
    i.drop_identity()
    assert calls == [('groups', []), ('gid', (1000, 1000, 1000)), ('uid', (1000, 1000, 1000))]
    assert env == {'PATH': '/usr/bin:/bin', 'LANG': 'C'}


def test_fixed_systemctl_only(monkeypatch):
    calls = []
    def run(argv, **kw):
        calls.append((argv, kw))
        return {'failure': None, 'returncode': 0, 'stdout': (
            'User=ec2-user\nGroup=ec2-user\nActiveState=active\nSubState=running\nMainPID=123\nWorkingDirectory=' + str(i.ROOT) + '\n').encode()}
    monkeypatch.setattr(i, 'BOUNDED', run, raising=False)
    assert i.worker() == '123'
    assert calls == [(['/usr/bin/systemctl', 'show', i.UNIT, '--no-pager', '--property=ActiveState,SubState,User,Group,MainPID,WorkingDirectory'], {'timeout': 5, 'limit': 4096, 'grace': 1})]


def fixture_inspection(adapter, monkeypatch):
    snapshot = b'timestamp,load_mw\n2026-11-03T15:00:00Z,12345\n'
    hashes = {'src/powerflow_secrets.py': hashlib.sha256(b'code').hexdigest()}
    monkeypatch.setattr(i, 'SOURCE_HASHES', hashes, raising=False)
    monkeypatch.setattr(i, 'WORKER_SHA', hashlib.sha256(b'code').hexdigest())
    def capture(path, *args, **kwargs):
        raw = b'ENTSOE_API_KEY=SECRET' if path.name == '.env' else snapshot if path.name == 'load.csv' else b'code'
        return raw, (1, 2, 3, 4, 5)
    monkeypatch.setattr(i, 'capture', capture)
    monkeypatch.setattr(i, 'worker', lambda: '123')
    monkeypatch.setattr(i, 'worker_environment', lambda _: {})
    monkeypatch.setattr(i, 'deployment_environment', lambda: {})
    phases = []
    monkeypatch.setattr(i, 'drop_identity', lambda: phases.append('dropped'))
    return phases


def test_full_mocked_flow_drops_before_one_source_request(adapter, monkeypatch):
    phases = fixture_inspection(adapter, monkeypatch)
    source = b'<Acknowledgement_MarketDocument><Reason><code>999</code><text>No matching data found</text></Reason></Acknowledgement_MarketDocument>'
    def request(provider):
        assert phases == ['dropped']
        assert provider('ENTSOE_API_KEY') == 'SECRET'
        phases.append('requested')
        return source, None
    monkeypatch.setitem(i.CORE, 'request_source', request)
    report = i.inspect()
    assert r.validate_report(report)['status'] == 'PASS'
    assert phases == ['dropped', 'requested']
    assert 'SECRET' not in json.dumps(report)


def test_profile_drift_prevents_request(adapter, monkeypatch):
    phases = fixture_inspection(adapter, monkeypatch)
    monkeypatch.setattr(i, 'worker', iter(['123', '124']).__next__)
    with pytest.raises(i.Stop, match='PROFILE_DRIFT'):
        i.inspect()
    assert phases == []


@pytest.mark.parametrize('error', [RuntimeError('SECRET raw failure'), i.Stop('SECRET'), FileNotFoundError('/private/SECRET')])
def test_main_sanitizes_failures(adapter, monkeypatch, capsys, error):
    def fail(): raise error
    monkeypatch.setattr(i, 'inspect', fail)
    assert i.main() == 1
    result = capsys.readouterr().out
    assert 'SECRET' not in result
    assert r.validate_report(json.loads(result))['cause'] == 'EVIDENCE_UNVERIFIED'


def test_output_validator_rejects_secret_fields():
    with pytest.raises(ValueError):
        r.validate_report({'status': 'BLOCKED', 'phase': 'INITIAL', 'cause': 'SECRET', 'comparison': None})
    with pytest.raises(ValueError):
        r.validate_report({'status': 'BLOCKED', 'phase': 'INITIAL', 'cause': 'WORKER_STATE', 'comparison': None, 'raw': 'SECRET'})


def test_verified_dependency_closure_and_payload():
    manifest = json.loads((HERE / 'REMOTE-MANIFEST.json').read_bytes())
    assert set(manifest['artifacts']) == r.ARTIFACTS
    blobs = {name: (ROOT / name).read_bytes() for name in r.ARTIFACTS}
    for name, raw in blobs.items():
        assert manifest['artifacts'][name] == {'bytes': len(raw), 'sha256': r.sha(raw)}
    assert r.sha(r.assemble(blobs)) == manifest['payload_sha256']
    assert b'INSTALL' not in r.assemble(blobs)


@pytest.mark.parametrize('defect', ['bytes', 'size', 'dependency', 'payload'])
def test_mismatch_before_profile_or_connection(monkeypatch, defect):
    raw = (HERE / 'REMOTE-MANIFEST.json').read_bytes()
    m = json.loads(raw)
    name = next(iter(m['artifacts']))
    if defect == 'bytes': m['artifacts'][name]['sha256'] = '0' * 64
    elif defect == 'size': m['artifacts'][name]['bytes'] += 1
    elif defect == 'dependency': m['artifacts']['unexpected.py'] = m['artifacts'][name]
    else: m['payload_sha256'] = '0' * 64
    modified = json.dumps(m).encode()
    original = r.read
    monkeypatch.setattr(r, 'read', lambda path: modified if path.name == 'REMOTE-MANIFEST.json' else original(path))
    monkeypatch.setattr(r, 'namespace', lambda *args, **kwargs: pytest.fail('executable loaded before rejection'))
    with pytest.raises(ValueError): r.verify(r.sha(modified))


@pytest.mark.parametrize('code,stderr,category', [(255, b'Host key verification failed', 'HOST_KEY_FAILURE'), (1, b'sudo: SECRET', 'SUDO_FAILURE'), (255, b'SECRET', 'SSH_FAILURE')])
def test_ssh_failure_one_attempt_private_sanitized(tmp_path, code, stderr, category):
    wrapper = r.namespace((ROOT / r.WRAPPER).read_bytes(), 'test_pinned_wrapper', ROOT / r.WRAPPER)
    private = tmp_path / 'private'
    (private / 'preflight').mkdir(parents=True)
    wrapper['PRIVATE'] = private
    wrapper['profile'] = lambda: {'target': 'private-target', 'known_hosts': '/private/pinned', 'identity_file': '/private/key'}
    calls = []
    def supervisor(argv, **kwargs):
        calls.append((argv, kwargs))
        return {'returncode': code, 'failure': None, 'stdout': b'SECRET', 'stderr': stderr}
    result = r.execute(b'VERIFIED_BYTES', wrapper, supervisor, r.validate_report)
    assert result['failure_category'] == category and len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[-1] == r.REMOTE
    assert 'StrictHostKeyChecking=yes' in argv and 'ConnectionAttempts=1' in argv and 'BatchMode=yes' in argv
    assert kwargs == {'input': b'VERIFIED_BYTES', 'timeout': 90, 'limit': 16384, 'grace': 5}
    evidence = next((private / 'preflight').glob('*/assessment.json'))
    assert 'SECRET' not in evidence.read_text()
    assert evidence.stat().st_mode & 0o777 == 0o600
    assert evidence.parent.stat().st_mode & 0o777 == 0o700
    assert list(evidence.parent.iterdir()) == [evidence]


def test_toctou_verified_bytes_survive_source_change(monkeypatch):
    manifest = (HERE / 'REMOTE-MANIFEST.json').read_bytes()
    calls = []
    original_read = r.read
    def read(path):
        calls.append(str(path))
        return original_read(path)
    monkeypatch.setattr(r, 'read', read)
    original_ns = r.namespace
    def namespace(raw, name, file=None):
        result = original_ns(raw, name, file)
        if name == 'pinned_ssh_wrapper': result['profile'] = lambda: {}
        return result
    monkeypatch.setattr(r, 'namespace', namespace)
    payload, _, supervisor, validator = r.verify(r.sha(manifest))
    # Replace all subsequent pathname reads with malicious bytes. Execution and
    # validation continue to use the already retained source, never reopening it.
    monkeypatch.setattr(r, 'read', lambda _: b'raise AssertionError("changed")')
    assert b'SECRET_CHANGED_EXECUTABLE' not in payload
    report = {'status': 'BLOCKED', 'phase': 'INITIAL', 'cause': 'WORKER_STATE', 'comparison': None}
    assert validator(report) == report
    assert callable(supervisor)
    assert len(calls) == 1 + len(r.ARTIFACTS)


def test_local_check_cannot_invoke_execute(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['run.py', '--manifest-sha256', '0' * 64, '--local-check'])
    monkeypatch.setattr(r, 'verify', lambda _: (b'held', {}, None, None))
    monkeypatch.setattr(r, 'execute', lambda *args: pytest.fail('local-check attempted SSH'))
    assert r.main() == 0
    assert json.loads(capsys.readouterr().out)['remote_attempts'] == 0


def test_supervisor_timeout_is_local_and_bounded():
    run = r.namespace(r.bounded_source((ROOT / r.BASE).read_bytes()), 'local_bound_test')['bounded_run']
    result = run([sys.executable, '-I', '-S', '-B', '-c', 'import time;time.sleep(5)'], timeout=.03, grace=.03, limit=100)
    assert result['failure'] == 'TIMEOUT'


def test_payload_imports_only_verified_dependencies_without_execution():
    blobs = {name: (ROOT / name).read_bytes() for name in r.ARTIFACTS}
    payload = r.assemble(blobs)
    tree = ast.parse(payload, feature_version=(3, 9))
    # Keep all original dependency compilation; suppress only the dispatcher
    # __main__ guard so this local syntax/runtime test cannot perform host I/O.
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'S' for t in n.targets))
    for key, value in zip(node.value.keys, node.value.values):
        if key.value == '__name__': value.value = 'test_adapter_import_only'
    namespace = {}
    exec(compile(ast.fix_missing_locations(tree), '<offline-payload-import>', 'exec'), namespace)
    assert namespace['S']['PROVIDER']['secrets_backend']({'POWERFLOW_SECRETS_BACKEND': 'env'}) == 'env'
    assert callable(namespace['S']['CORE']['request_source'])


def test_python39_and_readonly_dependency_scope():
    for name in ['check.py', 'inspect.py', 'run.py', 'build_remote.py', 'vendor/parser.py', 'vendor/variables.py']:
        ast.parse((HERE / name).read_text(), feature_version=(3, 9))
    tree = ast.parse((HERE / 'inspect.py').read_text())
    names = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not names & {'mkdir', 'unlink', 'replace', 'rename', 'chmod', 'chown', 'write_bytes', 'write_text', 'connect'}
    assert 'subprocess' not in {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}
    assert '-I -S -B -' in r.REMOTE and '60s' in r.REMOTE and '--kill-after=5s' in r.REMOTE
