"""Local runner; separate approval required for one apply OR rollback. Never retries."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT/'deploy/staging/inference-evidence-deployment'
P = PACKAGE/'deploy-capture.py'
S = ROOT/'deploy/remediation/a3-bounded-local.py'
EXPECTED = '81f2620e5da581fc5e81bdca4683b97491cdf28f97410f6a02e1b3a15beb16a7'
SUPERVISOR = '9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40'
OPTIONS = ['-i', '/Users/iannganga/.ssh/powerflow-key.pem', '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
           '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts',
           '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=1', '-o', 'ServerAliveInterval=10',
           '-o', 'ServerAliveCountMax=2', '-o', 'LogLevel=ERROR']


def verify_package():
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if sha(P) != EXPECTED or sha(S) != SUPERVISOR:
        raise RuntimeError('payload_or_supervisor_hash')
    manifest = json.loads((PACKAGE/'MANIFEST.json').read_bytes())
    expected_names = {'preflight.py', 'run-preflight.py', 'PREFLIGHT-RESULTS.json',
        'BASELINE-COMPARISON.json', 'deploy-template.py', 'deploy-capture.py',
        'run-deployment.py', 'DEPLOYMENT-REVIEW-RESULTS.json'}
    if set(manifest['files']) != expected_names:
        raise RuntimeError('local_manifest_inventory')
    for name, expected in manifest['files'].items():
        if sha(PACKAGE/name) != expected:
            raise RuntimeError('local_artifact_hash')
    if set(manifest['sources']) != {'src/models/next24h.py', 'src/models/next24h_production.py', 'src/models/inference_evidence.py'} or manifest['supervisor_sha256'] != SUPERVISOR:
        raise RuntimeError('local_source_inventory')
    for name, entry in manifest['sources'].items():
        if sha(ROOT/name) != entry['new_sha256']:
            raise RuntimeError('local_source_hash')
    if sha(ROOT/'tests/test_inference_capture_deployment.py') != manifest['test_file_sha256']:
        raise RuntimeError('local_test_hash')


def summarize(code, raw):
    if not raw:
        return {'report_produced': False, 'failure_category': 'transport_or_remote_error',
                'remote_installation_state': 'UNKNOWN', 'automatic_retry': False, 'exit': code}
    try:
        report = json.loads(raw)
        if not isinstance(report, dict) or 'stage' not in report:
            raise ValueError('report_shape')
    except (ValueError, UnicodeError):
        return {'report_produced': False, 'failure_category': 'invalid_json',
                'remote_installation_state': 'UNKNOWN', 'automatic_retry': False, 'exit': code}
    return report


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ['apply', 'rollback']:
        raise RuntimeError('one_action_required')
    try:
        verify_package()  # No SSH/capture creation until every local integrity check passes.
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'stage': 'local_integrity', 'remote_installation_state': 'NOT_STARTED', 'retry': False}))
        return 1
    os.umask(0o077)
    capture = Path(tempfile.mkdtemp(prefix='powerflow-inference-deployment-', dir='/private/tmp'))
    command = ['ssh', *OPTIONS, 'ec2-user@3.228.243.164',
        '/usr/bin/timeout --signal=TERM --kill-after=5s 90s '
        '/home/ec2-user/Electricity_Trading_Pipeline/.venv-prod/bin/python -I -B - '+sys.argv[1]]
    code = 124
    with P.open('rb') as source, (capture/'stdout.json').open('xb') as out, (capture/'stderr.private').open('xb') as err:
        try:
            result = subprocess.run([sys.executable, str(S), '--', *command],
                stdin=source, stdout=out, stderr=err, timeout=190)
            code = result.returncode
        except subprocess.TimeoutExpired:
            pass  # Supervisor already enforces180+5s; remote state remains unverified.
    print(json.dumps({'exit': code, 'capture': str(capture), 'retry': False, 'action': sys.argv[1]}))
    print(json.dumps(summarize(code, (capture/'stdout.json').read_bytes()), indent=2))
    return code


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'remote_state': 'UNVERIFIED', 'raw_error_withheld': True, 'retry': False}))
        raise SystemExit(1)
