"""Offline tests only: the real SSH executable is never invoked."""
import ast
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'deploy/staging/ssh-connectivity-check'
spec = importlib.util.spec_from_file_location('connectivity_test_runner', HERE / 'run.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def result(code=255, stderr=b'', stdout=b'', failure=None):
    return {'returncode': code, 'stderr': stderr, 'stdout': stdout, 'failure': failure}


@pytest.mark.parametrize('stderr,category', [
    (b'ssh: Could not resolve hostname PRIVATE: nodename nor servname provided', 'DNS_RESOLUTION_FAILURE'),
    (b'ssh: connect to host PRIVATE port 22: Connection timed out', 'CONNECTION_TIMEOUT'),
    (b'ssh: connect to host PRIVATE port 22: Connection refused', 'CONNECTION_REFUSED'),
    (b'ssh: connect to host PRIVATE port 22: Network is unreachable', 'NETWORK_UNREACHABLE'),
    (b'ssh: connect to host PRIVATE port 22: No route to host', 'NETWORK_UNREACHABLE'),
    (b'ssh: connect to host PRIVATE port 22: Operation not permitted', 'NETWORK_ACCESS_DENIED'),
    (b'ssh: connect to host PRIVATE port 22: Permission denied', 'NETWORK_ACCESS_DENIED'),
    (b'Host key verification failed.', 'HOST_KEY_VERIFICATION_FAILURE'),
    (b'WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!', 'HOST_KEY_VERIFICATION_FAILURE'),
    (b'PRIVATE_USER@PRIVATE: Permission denied (publickey).', 'AUTHENTICATION_FAILURE'),
    (b'debug1: No more authentication methods to try.', 'AUTHENTICATION_FAILURE'),
    (b'Load key "/PRIVATE_KEY": invalid format', 'IDENTITY_FAILURE'),
    (b'kex_exchange_identification: Connection closed by remote host', 'SSH_HANDSHAKE_FAILURE'),
    (b'Unable to negotiate with PRIVATE port 22: no matching host key type found', 'SSH_HANDSHAKE_FAILURE'),
    (b'PRIVATE secret-token unrecognized failure', 'UNCLASSIFIED_SSH_FAILURE'),
])
def test_transport_classification_and_redaction(stderr, category):
    report = r.classify(result(stderr=stderr))
    assert report['classification'] == category
    assert 'PRIVATE' not in json.dumps(report) and 'secret-token' not in json.dumps(report)
    assert report['authentication'] == report['remote_command_execution'] == 'UNVERIFIED'


def test_phases_do_not_infer_missing_milestones():
    report = r.classify(result(stderr=b'debug1: Connection established.\nConnection timed out during banner exchange'))
    assert report['classification'] == 'SSH_HANDSHAKE_TIMEOUT'
    assert report['tcp_connection'] == 'VERIFIED' and report['ssh_handshake'] == 'UNVERIFIED'
    report = r.classify(result(stderr=b'debug1: SSH2_MSG_NEWKEYS received\nconnection closed'))
    assert report['ssh_handshake'] == report['tcp_connection'] == 'VERIFIED'
    assert report['authentication'] == 'UNVERIFIED'


def test_authenticated_session_failure_is_not_remote_execution():
    raw = (b'Authenticated to PRIVATE ([PRIVATE_IP]:22) using "publickey".\n'
           b'debug1: Sending command: /usr/bin/true\nConnection closed')
    report = r.classify(result(stderr=raw))
    assert report['classification'] == 'REMOTE_COMMAND_OR_SESSION_FAILURE'
    assert report['authentication'] == report['remote_command_requested'] == 'VERIFIED'
    assert report['remote_command_execution'] == 'UNVERIFIED'
    assert 'PRIVATE' not in json.dumps(report)


def test_remote_nonzero_exit_and_success():
    raw = b'debug1: Sending command: /usr/bin/true\ndebug1: Exit status 127'
    report = r.classify(result(127, stderr=raw))
    assert report['classification'] == 'REMOTE_COMMAND_OR_SESSION_FAILURE'
    assert report['remote_command_execution'] == 'VERIFIED'
    report = r.classify(result(0))
    assert report['status'] == 'PASS' and report['classification'] == 'REMOTE_COMMAND_OK'
    for key in ['tcp_connection', 'ssh_handshake', 'pinned_host_key', 'authentication', 'remote_command_requested', 'remote_command_execution']:
        assert report[key] == 'VERIFIED'


def test_host_key_event_and_no_output_retention():
    raw = b"debug1: Host 'PRIVATE' is known and matches the ED25519 host key.\nPRIVATE_SECRET"
    report = r.classify(result(stderr=raw))
    assert report['pinned_host_key'] == 'VERIFIED' and report['authentication'] == 'UNVERIFIED'
    assert report['events'] == ['PINNED_HOST_KEY_MATCHED']
    assert 'PRIVATE' not in json.dumps(report)
    report = r.classify(result(0, stdout=b'PRIVATE_SERVER_BANNER'))
    assert report['status'] == 'PARTIAL' and report['classification'] == 'UNEXPECTED_REMOTE_OUTPUT'
    assert 'PRIVATE' not in json.dumps(report)


@pytest.mark.parametrize('failure,category', [('TIMEOUT', 'SUPERVISOR_TIMEOUT'), ('OUTPUT_LIMIT', 'OUTPUT_LIMIT')])
def test_supervisor_failure_does_not_claim_success(failure, category):
    report = r.classify(result(-15, stderr=b'PRIVATE', failure=failure))
    assert report['classification'] == category and report['remote_command_execution'] == 'UNVERIFIED'


def wrapper():
    value = r.namespace((ROOT / r.WRAPPER).read_bytes(), 'test_pinned_wrapper', ROOT / r.WRAPPER)
    value['profile'] = lambda: {'target': 'PRIVATE_TARGET', 'identity_file': '/PRIVATE_KEY', 'known_hosts': '/PRIVATE_KNOWN_HOSTS'}
    return value


def test_exact_fixed_argv_and_authentication_policy():
    w = wrapper()
    argv = r.ssh_argv(w, w['profile']())
    expected = w['ssh_argv'](w['profile']())
    expected[expected.index('LogLevel=ERROR')] = 'LogLevel=DEBUG1'
    expected = expected[:-2] + [part for option in r.EXTRA_OPTIONS for part in ('-o', option)] + ['PRIVATE_TARGET', '/usr/bin/true']
    assert argv == expected
    assert argv[:6] == ['/usr/bin/ssh', '-F', '/dev/null', '-T', '-i', '/PRIVATE_KEY']
    for option in ['StrictHostKeyChecking=yes', 'UserKnownHostsFile=/PRIVATE_KNOWN_HOSTS',
                   'GlobalKnownHostsFile=/dev/null', 'IdentitiesOnly=yes', 'BatchMode=yes',
                   'ConnectTimeout=10', 'ConnectionAttempts=1', 'IdentityAgent=none',
                   'PasswordAuthentication=no', 'KbdInteractiveAuthentication=no',
                   'PreferredAuthentications=publickey', 'StdinNull=yes', 'ProxyCommand=none']:
        assert option in argv
    assert not any('sudo' in item for item in argv)


def test_unsafe_wrapper_flags_rejected():
    w = wrapper()
    original = w['ssh_argv']
    w['ssh_argv'] = lambda profile: [x.replace('StrictHostKeyChecking=yes', 'StrictHostKeyChecking=no') for x in original(profile)]
    with pytest.raises(ValueError):
        r.ssh_argv(w, w['profile']())


@pytest.mark.parametrize('response', [result(0), result(stderr=b'PRIVATE: Connection refused'), result(-15, failure='TIMEOUT')])
def test_one_attempt_and_only_sanitized_private_evidence(tmp_path, response):
    w = wrapper()
    w['PRIVATE'] = tmp_path
    (tmp_path / 'preflight').mkdir()
    calls = []
    def supervisor(argv, **kwargs):
        calls.append((argv, kwargs))
        return response
    report = r.execute(w, supervisor, r.ssh_argv, r.classify)
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[-1] == '/usr/bin/true'
    assert kwargs == {'input': b'', 'timeout': 20, 'limit': 32768, 'grace': 5}
    evidence = next((tmp_path / 'preflight').glob('*/assessment.json'))
    assert json.loads(evidence.read_text()) == report
    assert evidence.stat().st_mode & 0o777 == 0o600
    assert evidence.parent.stat().st_mode & 0o777 == 0o700
    assert list(evidence.parent.iterdir()) == [evidence]
    assert 'PRIVATE' not in evidence.read_text()


def test_actual_supervisor_timeout_uses_only_local_child():
    bound = r.namespace(r.bounded_source((ROOT / r.BASE).read_bytes()), 'local_bound_test')['bounded_run']
    response = bound([sys.executable, '-I', '-S', '-B', '-c', 'import time;time.sleep(5)'], timeout=.03, grace=.03)
    assert response['failure'] == 'TIMEOUT'


def test_local_ssh_start_failure_is_sanitized_and_saved(tmp_path):
    w = wrapper()
    w['PRIVATE'] = tmp_path
    (tmp_path / 'preflight').mkdir()
    calls = []
    def fail(*args, **kwargs):
        calls.append(True)
        raise PermissionError(1, 'PRIVATE: operation not permitted', '/PRIVATE_KEY')
    report = r.execute(w, fail, r.ssh_argv, r.classify)
    assert len(calls) == 1
    assert report['classification'] == 'LOCAL_SSH_START_FAILURE' and report['errno'] == 1
    evidence = next((tmp_path / 'preflight').glob('*/assessment.json'))
    assert json.loads(evidence.read_text()) == report
    assert 'PRIVATE' not in evidence.read_text()


def test_manifest_and_complete_executable_closure():
    manifest = json.loads((HERE / 'MANIFEST.json').read_bytes())
    assert set(manifest['artifacts']) == r.ARTIFACTS
    for name, item in manifest['artifacts'].items():
        raw = (ROOT / name).read_bytes()
        assert item == {'bytes': len(raw), 'sha256': r.sha(raw)}
    assert manifest['remote_command'] == '/usr/bin/true'
    assert manifest['supervisor_sha256'] == r.sha(r.bounded_source((ROOT / r.BASE).read_bytes()))


@pytest.mark.parametrize('mutation', ['manifest', 'hash', 'size', 'extra_dependency', 'command', 'supervisor'])
def test_integrity_rejection_before_profile_or_ssh(monkeypatch, mutation):
    original = (HERE / 'MANIFEST.json').read_bytes()
    m = json.loads(original)
    name = next(iter(m['artifacts']))
    if mutation == 'hash': m['artifacts'][name]['sha256'] = '0' * 64
    elif mutation == 'size': m['artifacts'][name]['bytes'] += 1
    elif mutation == 'extra_dependency': m['artifacts']['unexpected.py'] = m['artifacts'][name]
    elif mutation == 'command': m['remote_command'] = 'arbitrary command'
    elif mutation == 'supervisor': m['supervisor_sha256'] = '0' * 64
    modified = json.dumps(m).encode()
    original_read = r.read
    monkeypatch.setattr(r, 'read', lambda path: modified if path.name == 'MANIFEST.json' else original_read(path))
    monkeypatch.setattr(r, 'namespace', lambda *args, **kwargs: pytest.fail('loaded executable before rejecting mismatch'))
    with pytest.raises(ValueError):
        r.verify(r.sha(original) if mutation == 'manifest' else r.sha(modified))


def test_retained_executable_bytes_not_reopened(monkeypatch):
    raw = (HERE / 'MANIFEST.json').read_bytes()
    namespace = r.namespace
    def load(data, name, file=None):
        value = namespace(data, name, file)
        if name == 'pinned_ssh_profile': value['profile'] = wrapper()['profile']
        return value
    monkeypatch.setattr(r, 'namespace', load)
    w, supervisor, command, classifier = r.verify(r.sha(raw))
    monkeypatch.setattr(r, 'read', lambda _: pytest.fail('reopened changed executable'))
    assert command(w, w['profile']())[-1] == '/usr/bin/true'
    assert classifier(result(0))['status'] == 'PASS'
    assert callable(supervisor)


def test_profile_failure_prevents_supervisor_creation(monkeypatch):
    namespace = r.namespace
    def load(data, name, file=None):
        assert name != 'retained_supervisor'
        value = namespace(data, name, file)
        if name == 'pinned_ssh_profile':
            def bad_profile(): raise ValueError('private identity drift')
            value['profile'] = bad_profile
        return value
    monkeypatch.setattr(r, 'namespace', load)
    with pytest.raises(ValueError):
        r.verify(r.sha((HERE / 'MANIFEST.json').read_bytes()))


def test_local_check_no_execution(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['run.py', '--manifest-sha256', '0' * 64, '--local-check'])
    monkeypatch.setattr(r, 'verify', lambda _: ({}, None, None, None))
    monkeypatch.setattr(r, 'execute', lambda *args: pytest.fail('local check attempted connection'))
    assert r.main() == 0
    assert json.loads(capsys.readouterr().out)['remote_attempts'] == 0


def test_no_command_override_cli(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['run.py', '--manifest-sha256', '0' * 64, '--command', 'unsafe'])
    with pytest.raises(SystemExit): r.main()


def test_python39_and_no_application_or_source_interfaces():
    for path in [HERE / 'run.py', HERE / 'build.py']:
        ast.parse(path.read_text(), feature_version=(3, 9))
    tree = ast.parse((HERE / 'run.py').read_text())
    imports = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}
    assert not imports & {'requests', 'urllib.request', 'http.client', 'sqlite3', 'boto3', 'pandas'}
    assert r.REMOTE == '/usr/bin/true'
    assert 'load-source-check' not in (HERE / 'run.py').read_text()
