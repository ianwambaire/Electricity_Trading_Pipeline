"""One hash-bound urllib3 metadata observation. Separate remote authorization required."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
OWN = 'deploy/staging/forecast-publication/urllib3-metadata-inspection/'
V2 = 'deploy/staging/forecast-publication/load-source-check-aws-v2/'
V2_SHA = 'caafdcadedaa3fc899cd63e5005bd0f803990bea05ddba477c4f56815011c0e2'
LOCK_SHA = 'da19f5a81c7741d19333e7bfcc25004c50fe2c83e31642c9f39c828518de35c4'
OLD = 'deploy/staging/forecast-publication/load-source-check/'
WRAPPER = 'deploy/staging/forecast-consistency-release/run_preflight.py'
BASE = 'deploy/staging/forecast-consistency-release/preflight_readonly.py'
NEW_FILES = {OWN + name for name in ['run.py', 'inspect.py', 'build.py', 'REVIEW.md']}
NEW_FILES.add('tests/test_urllib3_metadata_inspection.py')
V3 = 'deploy/staging/forecast-publication/load-source-check-aws-v3/'
V3_SHA = '0e4b9f45318804cb3d94ac193c09bbcc3a1e042d37400b7ba4a1246b9c8172b5'
REMOTE = 'sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -'
LIMITS = {'remote_seconds': 60, 'local_seconds': 90, 'escalation_seconds': 5, 'attempts': 1, 'capture_bytes': 16384}


def need(ok):
    if not ok:
        raise ValueError('sdk_diagnostic_binding_or_output_rejected')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW), 'rb') as stream:
        need(stat.S_ISREG(os.fstat(stream.fileno()).st_mode))
        raw = stream.read(2_000_001)
    need(len(raw) <= 2_000_000)
    return raw


def namespace(raw, name, file=None):
    result = {'__name__': name}
    if file:
        result['__file__'] = str(file)
    exec(compile(raw, '<verified-' + name + '>', 'exec'), result)
    return result


def select_source(raw, functions, classes=(), assignments=()):
    text = raw.decode()
    nodes = []
    found = set()
    for node in ast.parse(text).body:
        take = isinstance(node, ast.FunctionDef) and node.name in functions
        if take:
            found.add(node.name)
        take = take or isinstance(node, ast.ClassDef) and node.name in classes
        take = take or isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in assignments
        if take:
            nodes.append(ast.get_source_segment(text, node))
    need(found == set(functions) and all(n is not None for n in nodes))
    return ('\n\n'.join(nodes) + '\n').encode()


def assemble(blobs):
    v2 = namespace(blobs[V2 + 'run.py'], 'retained_v2_builder', ROOT / (V2 + 'run.py'))
    need(sha(blobs[V2 + 'SDK-LOCK.json']) == LOCK_SHA)
    lock = json.loads(blobs[V2 + 'SDK-LOCK.json'])
    host = b'import os,stat\nfrom pathlib import Path\n' + select_source(
        v2['host_source'](blobs[OLD + 'inspect.py']), {'need', 'capture'}, {'Stop'}, {'ROOT'})
    runtime = b'import stat,hashlib\nfrom pathlib import Path\n' + select_source(
        blobs[V2 + 'inspect.py'], {'_root_runtime'}, (), {'RUNTIME', 'RUNTIME_SHA', 'RUNTIME_IDENTITY'})
    fs = b'import os,stat,errno\nfrom pathlib import Path\n' + select_source(
        blobs[V3 + 'inspect.py'], {'location', 'fail', 'require', 'identity', 'filesystem_failure', 'directory_fd', 'metadata'},
        {'VerificationFailure'}, {'CATEGORIES'})
    text = "H={'__name__':'verified_capture'}\nexec(compile(" + repr(host) + ",'<verified-capture>','exec'),H)\n"
    text += "R={'__name__':'verified_runtime','H':H,'need':H['need']}\nexec(compile(" + repr(runtime) + ",'<verified-runtime>','exec'),R)\n"
    text += "F={'__name__':'verified_filesystem'}\nexec(compile(" + repr(fs) + ",'<verified-filesystem>','exec'),F)\n"
    text += "S={'__name__':'__main__','H':H,'F':F,'SDK_LOCK':" + repr(lock) + ",'RUNTIME_CHECK':R['_root_runtime']}\n"
    text += "exec(compile(" + repr(blobs[OWN + 'inspect.py']) + ",'<verified-metadata>','exec'),S)\n"
    return text.encode()


def validate_report(report, verifier):
    return verifier['validate_report'](report)


def verify(expected):
    need(type(expected) is str and re.fullmatch('[0-9a-f]{64}', expected) is not None)
    raw = read(HERE / 'MANIFEST.json')
    need(sha(raw) == expected)
    m = json.loads(raw)
    need(set(m) == {'version', 'action', 'v2_manifest_sha256', 'sdk_lock_sha256', 'limits', 'artifacts', 'payload_sha256'})
    need(m['version'] == 1 and m['action'] == 'urllib3-metadata-only' and m['v2_manifest_sha256'] == V2_SHA
         and m['sdk_lock_sha256'] == LOCK_SHA and m['limits'] == LIMITS)
    v3raw = read(ROOT / (V3 + 'MANIFEST.json'))
    need(sha(v3raw) == V3_SHA)
    original = json.loads(v3raw)
    need(set(m['artifacts']) == set(original['artifacts']) | NEW_FILES | {V3 + 'MANIFEST.json'})
    blobs = {}
    for name, item in m['artifacts'].items():
        content = read(ROOT / name)
        need(item == {'bytes': len(content), 'sha256': sha(content)})
        blobs[name] = content
    need(all(m['artifacts'][name] == item for name, item in original['artifacts'].items()))
    payload = assemble(blobs)
    need(len(payload) <= 150000 and sha(payload) == m['payload_sha256'])
    wrapper = namespace(blobs[WRAPPER], 'verified_ssh', ROOT / WRAPPER)
    wrapper['profile']()
    old = namespace(blobs[OLD + 'run.py'], 'verified_old_helpers', ROOT / (OLD + 'run.py'))
    supervisor = namespace(old['bounded_source'](blobs[BASE]), 'verified_supervisor')['bounded_run']
    validator = namespace(blobs[OWN + 'run.py'], 'verified_output_validator', HERE / 'run.py')['validate_report']
    verifier = {'__name__': 'verified_sdk_schema', 'H': {'ROOT': Path('/')},
                'F': {}, 'SDK_LOCK': json.loads(blobs[V2 + 'SDK-LOCK.json'])}
    exec(compile(blobs[OWN + 'inspect.py'], '<verified-sdk-schema>', 'exec'), verifier)
    return payload, wrapper, supervisor, lambda result: validator(result, verifier)


def execute(payload, wrapper, supervisor, validator):
    argv = wrapper['ssh_argv'](wrapper['profile']())
    argv[-1] = REMOTE
    os.umask(0o077)
    folder = Path(tempfile.mkdtemp(prefix='urllib3-metadata-', dir=wrapper['PRIVATE'] / 'preflight'))
    result = supervisor(argv, input=payload, timeout=90, limit=16384, grace=5)
    summary = {'exit_status': result['returncode'], 'failure_category': result['failure'], 'report': None}
    if not result['failure']:
        try:
            report = validator(json.loads(result['stdout']))
            need(result['returncode'] == (0 if report['status'] == 'PASS' else 1))
            summary['report'] = report
        except Exception:
            summary['failure_category'] = wrapper['failure_category'](result['returncode'], result['stderr']) if result['returncode'] else 'UNEXPECTED_OUTPUT'
    with os.fdopen(os.open(folder / 'assessment.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'w') as stream:
        json.dump(summary, stream, sort_keys=True, indent=2, allow_nan=False)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest-sha256', required=True)
    p.add_argument('--local-check', action='store_true')
    args = p.parse_args()
    try:
        payload, wrapper, supervisor, validator = verify(args.manifest_sha256)
        if args.local_check:
            print('{"local_integrity":"PASS","remote_attempts":0}')
            return 0
        result = execute(payload, wrapper, supervisor, validator)
    except Exception:
        result = {'exit_status': None, 'failure_category': 'LOCAL_VERIFICATION_OR_CAPTURE_FAILURE', 'report': None}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['report'] and result['report']['status'] == 'PASS' and result['failure_category'] is None else 1


if __name__ == '__main__':
    raise SystemExit(main())
