"""Local subprocesses and synthetic errors only. Never SSH or production reads."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('include_runner', ROOT / 'deploy/staging/run-nginx-include-diagnostic.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
SUPERVISOR = ROOT / 'deploy/remediation/a3-bounded-local.py'


@pytest.mark.parametrize('error,expected', [
    (b'kex_exchange_identification: Connection closed by remote host\n', 'ssh_connection_closed'),
    (b'Connection reset by peer\n', 'ssh_connection_reset'),
    (b'channel 0: open failed: channel open failed\n', 'ssh_remote_execution_channel_failure'),
    (b'ssh_dispatch_run_fatal: transport error\n', 'ssh_protocol_or_channel_failure'),
    (b'client_loop: send disconnect: Broken pipe\n', 'ssh_broken_pipe'),
    (b'Connection timed out\n', 'ssh_connection_timeout'),
    (b'WARNING: connection is not using a post-quantum key exchange algorithm.\n', 'ssh_or_supervisor_exit_255_unclassified'),
])
def test_safe_transport_categories(error, expected):
    report = m.classify(255, b'', error + b'sensitive-example-value\n')
    assert report['failure_category'] == expected
    assert 'sensitive-example-value' not in json.dumps(report)


def test_remote_python_traceback_and_no_exception_message_exposure():
    error = b'Traceback (most recent call last):\n  File "<stdin>", line 1\nRuntimeError: secret-example\n'
    report = m.classify(1, b'', error)
    assert report['failure_category'] == 'remote_python_traceback'
    assert report['observed_python_exception_types'] == ['RuntimeError']
    assert 'secret-example' not in json.dumps(report)


def test_json_rejection_does_not_change_observed_status():
    report = m.classify(0, b'12345\n', b'')
    assert report['diagnostic_exit_status'] == 0
    assert report['failure_category'] == 'unexpected_json_type'
    report = m.classify(0, b'{broken', b'')
    assert report['failure_category'] == 'stdout_not_valid_json'


def test_mocked_failure_called_once_and_captures_privately(tmp_path):
    calls = []
    def fake(command, **kw):
        calls.append((command, kw))
        assert kw['input'] == (ROOT / 'deploy/staging/diagnose-nginx-include.py').read_bytes()
        return SimpleNamespace(returncode=255, stdout=b'', stderr=b'Connection reset by peer\n')
    code, report = m.run_once(ROOT, execute=fake, capture_parent=tmp_path)
    assert code == 255 and len(calls) == 1
    directory = Path(report['private_capture_directory'])
    assert directory.stat().st_mode & 0o777 == 0o700
    for name in ('stdout', 'stderr', 'result.json'):
        assert (directory / name).stat().st_mode & 0o777 == 0o600
    assert report['failure_category'] == 'ssh_connection_reset'


def test_real_local_supervisor_preserves_stdin_and_output():
    payload = b'import sys,json; print(json.dumps({"marker":12345})); sys.stderr.write("synthetic-stderr\\n")\n'
    result = subprocess.run([sys.executable, '-B', str(SUPERVISOR), '--',
                             sys.executable, '-I', '-S', '-B', '-'], input=payload, capture_output=True)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {'marker': 12345}
    assert result.stderr == b'synthetic-stderr\n'


@pytest.mark.parametrize('exit_code', [1, 7, 124, 255])
def test_real_local_supervisor_preserves_positive_exit_codes(exit_code):
    result = subprocess.run([sys.executable, '-B', str(SUPERVISOR), '--',
                            sys.executable, '-I', '-S', '-B', '-c',
                            'raise SystemExit(' + str(exit_code) + ')'], capture_output=True)
    assert result.returncode == exit_code


def test_signal_exit_can_also_become_255():
    child = 'import signal,os; signal.signal(signal.SIGHUP,signal.SIG_DFL); os.kill(os.getpid(),signal.SIGHUP)'
    direct = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', child], capture_output=True)
    wrapped = subprocess.run([sys.executable, '-B', str(SUPERVISOR), '--',
                             sys.executable, '-I', '-S', '-B', '-c', child], capture_output=True)
    assert direct.returncode == -1 and wrapped.returncode == 255


def test_payload_can_raise_before_json_without_exception_boundary(monkeypatch,capsys):
    spec = importlib.util.spec_from_file_location('original_payload', ROOT / 'deploy/staging/diagnose-nginx-include.py')
    payload = importlib.util.module_from_spec(spec); spec.loader.exec_module(payload)
    monkeypatch.setattr(payload.os, 'geteuid', lambda: 0)
    def fail(): raise RuntimeError('synthetic-example')
    monkeypatch.setattr(payload, 'inspect', fail)
    with pytest.raises(RuntimeError): payload.main()
    assert capsys.readouterr().out == ''
