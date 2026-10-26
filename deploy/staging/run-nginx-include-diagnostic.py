#!/usr/bin/env python3
"""Local runner only: unchanged remote diagnostic, one bounded SSH call, private captures."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

ROOT = Path('/Users/iannganga/Desktop/electricity-trading-pipeline')
BINDINGS = {
    'deploy/staging/diagnose-nginx-include.py': '4e8593d3cbb31fbf38030c56593695fc687ef0c418367f59af580f08216ac07c',
    'deploy/staging/activate-staging-https.py': '82cf59096afd5ee61d326f866fa426adcfa536913620b5feeaf4777c87d7983f',
    'deploy/remediation/a3-bounded-local.py': '9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40',
}


def failure_category(code, stderr):
    """Return fixed labels only. Never return exception messages or stderr lines."""
    text = stderr.decode('utf-8', errors='replace').lower()
    rules = [
        (('host key verification failed', 'remote host identification has changed'), 'ssh_host_key_verification_failed'),
        (('permission denied (publickey',), 'ssh_public_key_authentication_failed'),
        (('connection timed out', 'operation timed out'), 'ssh_connection_timeout'),
        (('connection refused',), 'ssh_connection_refused'),
        (('no route to host', 'network is unreachable'), 'ssh_network_unreachable'),
        (('connection reset by peer',), 'ssh_connection_reset'),
        (('connection closed', 'closed by remote host'), 'ssh_connection_closed'),
        (('broken pipe',), 'ssh_broken_pipe'),
        (('kex_exchange_identification:', 'ssh_exchange_identification:', 'ssh_dispatch_run_fatal:'), 'ssh_protocol_or_channel_failure'),
        (('exec request failed', 'channel open failed'), 'ssh_remote_execution_channel_failure'),
        (('sudo:',), 'remote_sudo_error'),
    ]
    for patterns, label in rules:
        if any(pattern in text for pattern in patterns): return label
    if 'file "<stdin>"' in text and any(x in text for x in ('syntaxerror:', 'indentationerror:', 'taberror:')):
        return 'remote_python_syntax_error'
    if 'traceback (most recent call last):' in text:
        return 'remote_python_traceback' if 'file "<stdin>"' in text else 'python_traceback_origin_unverified'
    if code is not None and code < 0: return 'local_supervisor_terminated_by_signal'
    if code == 124: return 'timeout_or_exit_124_origin_unverified'
    if code == 255: return 'ssh_or_supervisor_exit_255_unclassified'
    return 'no_report_cause_unconfirmed'


def classify(code, stdout, stderr):
    report = {'diagnostic_exit_status': code, 'stdout_bytes': len(stdout),
              'stderr_bytes': len(stderr), 'report_produced': False,
              'raw_stderr_withheld': True, 'retry_performed': False}
    if stdout:
        try: diagnostic = json.loads(stdout)
        except (ValueError, UnicodeDecodeError):
            report['failure_category'] = 'stdout_not_valid_json'
        else:
            if isinstance(diagnostic, dict):
                report['report_produced'] = True
                report['diagnostic_report'] = diagnostic
            else: report['failure_category'] = 'unexpected_json_type'
    else: report['failure_category'] = failure_category(code, stderr)
    # Only allowlisted exception type names, not messages or tracebacks.
    matches = re.findall(rb'(?m)^(SyntaxError|IndentationError|TabError|ModuleNotFoundError|ImportError|RuntimeError|RecursionError|TypeError|ValueError|OSError|PermissionError|FileNotFoundError):', stderr)
    if matches: report['observed_python_exception_types'] = sorted({m.decode() for m in matches})
    return report


def save_private(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(data)


def run_once(repo=ROOT, execute=subprocess.run, capture_parent=None):
    blobs = {name: (repo / name).read_bytes() for name in BINDINGS}
    for name, expected in BINDINGS.items():
        if hashlib.sha256(blobs[name]).hexdigest() != expected:
            return 1, {'report_produced': False, 'failure_category': 'local_hash_mismatch',
                       'ssh_invoked': False, 'retry_performed': False}
    payload = blobs['deploy/staging/diagnose-nginx-include.py']
    command = [
        str(repo / 'venv/bin/python'), '-B', str(repo / 'deploy/remediation/a3-bounded-local.py'), '--',
        'ssh', '-F', '/dev/null', '-i', '/Users/iannganga/.ssh/powerflow-key.pem',
        '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'UpdateHostKeys=no',
        '-o', 'UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts',
        '-o', 'ForwardAgent=no', '-o', 'RequestTTY=no', '-o', 'ConnectTimeout=10',
        '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=3',
        '-T', 'ec2-user@3.228.243.164',
        'sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s '
        '45s /usr/bin/python3 -I -S -B -',
    ]
    capture = Path(tempfile.mkdtemp(prefix='powerflow-nginx-include-', dir=capture_parent))
    capture.chmod(0o700)
    started = time.monotonic()
    try:
        result = execute(command, input=payload, capture_output=True, cwd=repo)
        save_private(capture / 'stdout', result.stdout)
        save_private(capture / 'stderr', result.stderr)
        report = classify(result.returncode, result.stdout, result.stderr)
        exit_code = result.returncode if result.returncode != 0 else (0 if report['report_produced'] else 1)
    except OSError as error:
        report = {'diagnostic_exit_status': None, 'report_produced': False,
                  'failure_category': 'local_spawn_or_capture_failure',
                  'safe_errno': error.errno, 'raw_stderr_withheld': True, 'retry_performed': False}
        exit_code = 1
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    report['private_capture_directory'] = str(capture)
    report['remote_payload_sha256'] = hashlib.sha256(payload).hexdigest()
    report['exit_status_note'] = 'Status is from supervisor; child signal exits may be encoded modulo256;124 is a timeout/status sentinel.'
    save_private(capture / 'result.json', (json.dumps(report, indent=2) + '\n').encode())
    return exit_code, report


def main():
    try: code, report = run_once()
    except (OSError, ValueError):
        code, report = 1, {'report_produced': False, 'failure_category': 'local_preflight_failure',
                           'retry_performed': False}
    print(json.dumps(report, indent=2))
    return code


if __name__ == '__main__': raise SystemExit(main())
