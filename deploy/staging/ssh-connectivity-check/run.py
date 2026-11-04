"""One pinned SSH connection running only /usr/bin/true; authorization required.

Raw transport output is classified in memory and never printed or persisted.
--local-check verifies files and the pinned profile without invoking SSH.
"""
import argparse
import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OWN = 'deploy/staging/ssh-connectivity-check/'
WRAPPER = 'deploy/staging/forecast-consistency-release/run_preflight.py'
BASE = 'deploy/staging/forecast-consistency-release/preflight_readonly.py'
PINNED_SOURCES = {
    WRAPPER: '0598ec061225a70fbe8f418f337299afaf242e4d463780d34e6b594aa8e0a48a',
    BASE: 'bbd94119fbed5b7e0d6c154167fa44ec32e3a0733c3d49c02521c5bfbf126463',
}
ARTIFACTS = {WRAPPER, BASE, OWN + 'run.py', OWN + 'build.py',
             OWN + 'REVIEW.md', 'tests/test_ssh_connectivity_check.py'}
LIMITS = {'connection_seconds': 10, 'supervisor_seconds': 20,
          'escalation_seconds': 5, 'stream_bytes': 32768, 'attempts': 1}
REMOTE = '/usr/bin/true'
EXTRA_OPTIONS = (
    'PreferredAuthentications=publickey', 'PubkeyAuthentication=yes',
    'PasswordAuthentication=no', 'KbdInteractiveAuthentication=no',
    'GSSAPIAuthentication=no', 'HostbasedAuthentication=no',
    'NumberOfPasswordPrompts=0', 'RequestTTY=no', 'StdinNull=yes',
    'ForwardX11=no', 'ProxyCommand=none', 'ProxyJump=none',
)


def need(ok):
    if not ok:
        raise ValueError('connectivity_binding_rejected')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        need(stat.S_ISREG(os.fstat(stream.fileno()).st_mode))
        raw = stream.read(2000001)
    need(len(raw) <= 2000000)
    return raw


def namespace(raw, name, file=None):
    result = {'__name__': name}
    if file is not None:
        result['__file__'] = str(file)
    exec(compile(raw, '<verified-' + name + '>', 'exec'), result)
    return result


def bounded_source(raw):
    tree = ast.parse(raw)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'bounded_run']
    need(len(nodes) == 1)
    source = ast.get_source_segment(raw.decode(), nodes[0])
    need(source is not None)
    return b'import os,subprocess,selectors,signal,time\n' + source.encode()


def ssh_argv(wrapper, profile):
    argv = wrapper['ssh_argv'](profile)
    need(argv[:4] == ['/usr/bin/ssh', '-F', '/dev/null', '-T'])
    need(argv[-2] == profile['target'] and argv.count('LogLevel=ERROR') == 1)
    # DEBUG1 emits connection/authentication/session milestones. Only allowlisted
    # classifications and booleans may leave memory, never these raw messages.
    argv[argv.index('LogLevel=ERROR')] = 'LogLevel=DEBUG1'
    for option in ('StrictHostKeyChecking=yes', 'BatchMode=yes', 'IdentitiesOnly=yes',
                   'ConnectionAttempts=1', 'ConnectTimeout=10', 'IdentityAgent=none',
                   'ForwardAgent=no', 'ClearAllForwardings=yes', 'PermitLocalCommand=no',
                   'ControlMaster=no', 'ControlPath=none', 'UpdateHostKeys=no'):
        need(option in argv)
    return argv[:-2] + [part for option in EXTRA_OPTIONS for part in ('-o', option)] + [profile['target'], REMOTE]


def classify(result):
    """Sanitized event codes only; absence of a milestone remains UNVERIFIED."""
    need(set(result) == {'returncode', 'stdout', 'stderr', 'failure'})
    code, out, err, failure = (result[k] for k in ('returncode', 'stdout', 'stderr', 'failure'))
    need(type(code) is int and type(out) is bytes and type(err) is bytes)
    need(len(out) <= 32768 and len(err) <= 32768 and failure in {None, 'TIMEOUT', 'OUTPUT_LIMIT'})
    lines = err.lower().splitlines()
    debug = [line for line in lines if line.startswith(b'debug1: ')]
    has = lambda fragment: any(fragment in line for line in debug)
    events = set()
    if has(b'connection established.'):
        events.add('TCP_CONNECTED')
    if has(b'ssh2_msg_newkeys received'):
        events.add('SSH_KEY_EXCHANGE_COMPLETED')
    if any(line.startswith(b'debug1: host ') and b' is known and matches the ' in line and b' host key.' in line for line in debug):
        events.add('PINNED_HOST_KEY_MATCHED')
    if any((line.startswith(b'authenticated to ') and line.endswith(b' using "publickey".'))
           or line == b'debug1: authentication succeeded (publickey).' for line in lines):
        events.add('PUBLIC_KEY_AUTHENTICATED')
    if b'debug1: sending command: /usr/bin/true' in debug:
        events.add('FIXED_COMMAND_REQUESTED')
    if any(re.fullmatch(rb'debug1: exit status -?[0-9]+', line) and
           int(line.rsplit(b' ', 1)[1]) == code for line in debug):
        events.add('REMOTE_EXIT_STATUS_RECEIVED')

    if failure:
        category = 'SUPERVISOR_TIMEOUT' if failure == 'TIMEOUT' else 'OUTPUT_LIMIT'
    elif code == 0:
        category = 'REMOTE_COMMAND_OK' if not out else 'UNEXPECTED_REMOTE_OUTPUT'
    elif any(b'host key verification failed' in line or b'remote host identification has changed' in line for line in lines):
        category = 'HOST_KEY_VERIFICATION_FAILURE'
    elif any(b'could not resolve hostname' in line or b'temporary failure in name resolution' in line for line in lines):
        category = 'DNS_RESOLUTION_FAILURE'
    elif any((b'connect to host ' in line or line.startswith(b'socket: ')) and
             (b'operation not permitted' in line or b'permission denied' in line) for line in lines):
        category = 'NETWORK_ACCESS_DENIED'
    elif any(b'connection refused' in line for line in lines):
        category = 'CONNECTION_REFUSED'
    elif any(b'network is unreachable' in line or b'no route to host' in line or b"can't assign requested address" in line for line in lines):
        category = 'NETWORK_UNREACHABLE'
    elif any(b'connection timed out' in line or b'operation timed out' in line or b'connection timeout' in line for line in lines):
        category = 'SSH_HANDSHAKE_TIMEOUT' if 'TCP_CONNECTED' in events else 'CONNECTION_TIMEOUT'
    elif any(line.startswith((b'load key ', b'identity file ')) and
             (b'permission denied' in line or b'no such file' in line or b'invalid format' in line) for line in lines):
        category = 'IDENTITY_FAILURE'
    elif any(b'permission denied (' in line or b'no more authentication methods to try' in line or b'authentication failed' in line for line in lines):
        category = 'AUTHENTICATION_FAILURE'
    elif any(b'kex_exchange_identification:' in line or b'unable to negotiate with ' in line for line in lines):
        category = 'SSH_HANDSHAKE_FAILURE'
    elif 'PUBLIC_KEY_AUTHENTICATED' in events or 'FIXED_COMMAND_REQUESTED' in events or 'REMOTE_EXIT_STATUS_RECEIVED' in events:
        category = 'REMOTE_COMMAND_OR_SESSION_FAILURE'
    else:
        category = 'UNCLASSIFIED_SSH_FAILURE'

    # A successful fixed SSH command proves all preceding transport phases.
    # Sending a command alone proves only that a request was sent, not execution.
    execution = code == 0 and failure is None or 'REMOTE_EXIT_STATUS_RECEIVED' in events
    authentication = execution or 'PUBLIC_KEY_AUTHENTICATED' in events
    handshake = authentication or 'SSH_KEY_EXCHANGE_COMPLETED' in events
    tcp = handshake or 'TCP_CONNECTED' in events
    known = lambda value: 'VERIFIED' if value else 'UNVERIFIED'
    return {
        'status': 'PASS' if category == 'REMOTE_COMMAND_OK' else 'PARTIAL' if category == 'UNEXPECTED_REMOTE_OUTPUT' else 'BLOCKED',
        'exit_status': code, 'classification': category,
        'tcp_connection': known(tcp), 'ssh_handshake': known(handshake),
        'pinned_host_key': known(authentication or 'PINNED_HOST_KEY_MATCHED' in events),
        'authentication': known(authentication),
        'remote_command_requested': known(execution or 'FIXED_COMMAND_REQUESTED' in events),
        'remote_command_execution': known(execution),
        'events': sorted(events), 'stdout_bytes_captured': len(out), 'stderr_bytes_captured': len(err),
    }


def verify(expected):
    need(type(expected) is str and re.fullmatch('[0-9a-f]{64}', expected) is not None)
    raw = read(HERE / 'MANIFEST.json')
    need(sha(raw) == expected)
    manifest = json.loads(raw)
    need(set(manifest) == {'version', 'action', 'limits', 'remote_command', 'artifacts', 'supervisor_sha256'})
    need(manifest['version'] == 1 and manifest['action'] == 'connectivity-only')
    need(manifest['limits'] == LIMITS and manifest['remote_command'] == REMOTE)
    need(set(manifest['artifacts']) == ARTIFACTS)
    blobs = {}
    for name, item in manifest['artifacts'].items():
        content = read(ROOT / name)
        need(item == {'bytes': len(content), 'sha256': sha(content)})
        blobs[name] = content
    for name, expected_sha in PINNED_SOURCES.items():
        need(sha(blobs[name]) == expected_sha)
    supervisor = bounded_source(blobs[BASE])
    need(sha(supervisor) == manifest['supervisor_sha256'])
    wrapper = namespace(blobs[WRAPPER], 'pinned_ssh_profile', ROOT / WRAPPER)
    # No SSH: profile checks the approved destination/hash/known-hosts and key
    # metadata, never the private key contents. Secrets are never printed.
    profile = wrapper['profile']()
    retained = namespace(blobs[OWN + 'run.py'], 'retained_connectivity_runner', HERE / 'run.py')
    retained['ssh_argv'](wrapper, profile)
    bound = namespace(supervisor, 'retained_supervisor')['bounded_run']
    return wrapper, bound, retained['ssh_argv'], retained['classify']


def execute(wrapper, supervisor, command, classifier):
    # Fresh profile verification before the one and only possible connection.
    argv = command(wrapper, wrapper['profile']())
    os.umask(0o077)
    folder = Path(tempfile.mkdtemp(prefix='ssh-connectivity-', dir=wrapper['PRIVATE'] / 'preflight'))
    try:
        result = supervisor(argv, input=b'', timeout=20, limit=32768, grace=5)
    except OSError as error:
        # A local process-start error is distinct from an SSH transport exit.
        # Never retain exception text, executable paths or command arguments.
        report = {'status': 'BLOCKED', 'classification': 'LOCAL_SSH_START_FAILURE',
                  'exit_status': None, 'errno': error.errno if type(error.errno) is int else None}
    else:
        report = classifier(result)
    report['observed_at_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    with os.fdopen(os.open(folder / 'assessment.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'w') as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--local-check', action='store_true')
    args = parser.parse_args()
    try:
        wrapper, supervisor, command, classifier = verify(args.manifest_sha256)
        if args.local_check:
            print('{"local_integrity":"PASS","remote_attempts":0}')
            return 0
        report = execute(wrapper, supervisor, command, classifier)
    except Exception:
        report = {'status': 'BLOCKED', 'classification': 'LOCAL_VERIFICATION_OR_CAPTURE_FAILURE'}
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
