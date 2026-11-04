"""Hash-bound AWS-backed fixed load-source inspection; separate authorization required."""
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
OWN = 'deploy/staging/forecast-publication/load-source-check-aws-v4/'
V2 = 'deploy/staging/forecast-publication/load-source-check-aws-v2/'
V2_SHA = 'caafdcadedaa3fc899cd63e5005bd0f803990bea05ddba477c4f56815011c0e2'
V3 = 'deploy/staging/forecast-publication/load-source-check-aws-v3/'
V3_SHA = '0e4b9f45318804cb3d94ac193c09bbcc3a1e042d37400b7ba4a1246b9c8172b5'
CANDIDATE = 'deploy/staging/forecast-publication/sdk-baseline-urllib3-2.8.0/'
CANDIDATE_SHA = 'e169563689408ac806b097dc0b9e69e374fa82dea6b3a706a05bde802844d25d'
LOCK_SHA = '4ff10a67faafbe36031e960e0afbce696187b7e3928da396e248ffc7ffdb2421'
WHEEL = CANDIDATE + 'reference/urllib3-2.8.0-py3-none-any.whl'
WHEEL_SHA = '0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3'
OLD = 'deploy/staging/forecast-publication/load-source-check/'
WRAPPER = 'deploy/staging/forecast-consistency-release/run_preflight.py'
BASE = 'deploy/staging/forecast-consistency-release/preflight_readonly.py'
NEW_FILES = {OWN + name for name in ['run.py', 'inspect.py', 'build.py', 'REVIEW.md']}
NEW_FILES.add('tests/test_candidate_load_source_check.py')
REMOTE = 'sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -'
LIMITS = {'remote_seconds': 60, 'local_seconds': 90, 'escalation_seconds': 5, 'attempts': 1, 'capture_bytes': 16384}


def need(ok):
    if not ok:
        raise ValueError('aws_source_binding_or_output_rejected')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW), 'rb') as stream:
        need(stat.S_ISREG(os.fstat(stream.fileno()).st_mode))
        data = stream.read(2_000_001)
    need(len(data) <= 2_000_000)
    return data


def namespace(raw, name, file=None):
    result = {'__name__': name}
    if file:
        result['__file__'] = str(file)
    exec(compile(raw, '<verified-' + name + '>', 'exec'), result)
    return result


def reviewed_artifacts():
    result = {}
    for path, expected in [(V2 + 'MANIFEST.json', V2_SHA), (V3 + 'MANIFEST.json', V3_SHA),
                           (CANDIDATE + 'MANIFEST.json', CANDIDATE_SHA)]:
        raw = read(ROOT / path)
        need(sha(raw) == expected)
        source = json.loads(raw)
        for name, item in source['artifacts'].items():
            need(name not in result or result[name] == item)
            result[name] = item
        result[path] = {'bytes': len(raw), 'sha256': sha(raw)}
    return result


def candidate_lock(blobs):
    raw = blobs[CANDIDATE + 'SDK-LOCK.json']
    need(sha(raw) == LOCK_SHA and sha(blobs[WHEEL]) == WHEEL_SHA)
    reference = namespace(blobs[CANDIDATE + 'reference.py'], 'retained_reference', ROOT / (CANDIDATE + 'reference.py'))
    selected = reference['wheel_files'](blobs[WHEEL])
    expected = json.loads(blobs[V2 + 'SDK-LOCK.json'])
    need(sha(blobs[V2 + 'SDK-LOCK.json']) == reference['LOCK_SHA'])
    expected['files'] = {n: entry for n, entry in expected['files'].items()
                         if not n.startswith(('urllib3/', 'urllib3-'))}
    expected['files'].update({n: {'bytes': len(raw), 'sha256': sha(raw)} for n, raw in selected.items()})
    expected['versions']['urllib3'] = '2.8.0'
    lock = json.loads(raw)
    need(lock == expected and len(lock['files']) == 215)
    return lock


def assemble(blobs):
    lock = candidate_lock(blobs)
    v2 = namespace(blobs[V2 + 'run.py'], 'retained_v2_builder', ROOT / (V2 + 'run.py'))
    # The old builder's only dependency-version literal changes. No runtime
    # argument can choose another version; the entire candidate is pinned above.
    source = ast.get_source_segment(blobs[V2 + 'run.py'].decode(), next(
        n for n in ast.parse(blobs[V2 + 'run.py']).body if isinstance(n, ast.FunctionDef) and n.name == 'assemble'))
    original = "'urllib3': '2.7.0'"
    need(source.count(original) == 1)
    exec(compile(source.replace(original, "'urllib3': '2.8.0'", 1), '<candidate-bound-builder>', 'exec'), v2)
    inputs = dict(blobs)
    # These are explicitly supplied retained bytes, not replacement files on disk.
    inputs[V2 + 'SDK-LOCK.json'] = blobs[CANDIDATE + 'SDK-LOCK.json']
    inputs[V2 + 'inspect.py'] = (b'FLOW_SOURCE=' + repr(blobs[V2 + 'inspect.py']).encode() + b'\n'
        + b'VERIFIER_SOURCE=' + repr(blobs[V3 + 'inspect.py']).encode() + b'\n'
        + blobs[OWN + 'inspect.py'])
    return v2['assemble'](inputs)


def validate_report(report, old_validator, verifier):
    need(type(report) is dict and set(report) == {'status', 'phase', 'cause', 'credential_backend',
         'iam_role_verified', 'source_request', 'comparison', 'sdk_verification'})
    ordinary = {key: value for key, value in report.items() if key != 'sdk_verification'}
    old_validator(ordinary)
    detail = report['sdk_verification']
    need(type(detail) is dict and set(detail) == {'dependency_id', 'category', 'stage', 'verified_files'})
    need(detail['stage'] in verifier['STAGES'] and type(detail['verified_files']) is int
         and 0 <= detail['verified_files'] <= 215)
    if detail['stage'] == 'NOT_STARTED':
        need(detail == {'dependency_id': None, 'category': None, 'stage': 'NOT_STARTED', 'verified_files': 0})
    elif detail['stage'] == 'COMPLETE':
        need(detail == {'dependency_id': None, 'category': None, 'stage': 'COMPLETE', 'verified_files': 215})
    else:
        need(detail['dependency_id'] in verifier['approved_ids']() and detail['category'] in verifier['CATEGORIES'])
    if report['status'] == 'PASS' or report['source_request'] != 'NOT_ATTEMPTED' or report['iam_role_verified']:
        need(detail['stage'] == 'COMPLETE')
    return report


def verify(expected):
    need(type(expected) is str and re.fullmatch('[0-9a-f]{64}', expected) is not None)
    raw = read(HERE / 'MANIFEST.json')
    need(sha(raw) == expected)
    m = json.loads(raw)
    need(set(m) == {'version', 'candidate_manifest_sha256', 'sdk_lock_sha256', 'wheel_sha256',
                   'limits', 'artifacts', 'payload_sha256'})
    need(m['version'] == 4 and m['candidate_manifest_sha256'] == CANDIDATE_SHA
         and m['sdk_lock_sha256'] == LOCK_SHA and m['wheel_sha256'] == WHEEL_SHA and m['limits'] == LIMITS)
    reviewed = reviewed_artifacts()
    need(set(m['artifacts']) == set(reviewed) | NEW_FILES)
    blobs = {}
    for name, item in m['artifacts'].items():
        raw = read(ROOT / name)
        need(item == {'bytes': len(raw), 'sha256': sha(raw)})
        blobs[name] = raw
    need(all(m['artifacts'][name] == entry for name, entry in reviewed.items()))
    payload = assemble(blobs)
    need(len(payload) <= 300000 and sha(payload) == m['payload_sha256'])
    wrapper = namespace(blobs[WRAPPER], 'verified_ssh', ROOT / WRAPPER)
    wrapper['profile']()
    old = namespace(blobs[OLD + 'run.py'], 'verified_original_helpers', ROOT / (OLD + 'run.py'))
    supervisor = namespace(old['bounded_source'](blobs[BASE]), 'verified_supervisor')['bounded_run']
    base = namespace(blobs[V2 + 'run.py'], 'verified_sdk_schema', ROOT / (V2 + 'run.py'))
    schema = namespace(blobs[OWN + 'run.py'], 'verified_v4_schema', HERE / 'run.py')['validate_report']
    verifier = {'__name__': 'verified_candidate_schema', 'H': {'ROOT': Path('/')}, 'SDK_LOCK': candidate_lock(blobs)}
    exec(compile(blobs[V3 + 'inspect.py'], '<verified-v3-schema>', 'exec'), verifier)
    return payload, wrapper, supervisor, lambda report: schema(report, lambda value: base['validate_report'](value, old['validate_report']), verifier)


def execute(payload, wrapper, supervisor, validator):
    argv = wrapper['ssh_argv'](wrapper['profile']())
    argv[-1] = REMOTE
    os.umask(0o077)
    folder = Path(tempfile.mkdtemp(prefix='load-source-aws-v4-', dir=wrapper['PRIVATE'] / 'preflight'))
    response = supervisor(argv, input=payload, timeout=90, limit=16384, grace=5)
    summary = {'exit_status': response['returncode'], 'failure_category': response['failure'], 'report': None}
    if not response['failure']:
        try:
            report = validator(json.loads(response['stdout']))
            need(response['returncode'] == (0 if report['status'] == 'PASS' else 1))
            summary['report'] = report
        except Exception:
            summary['failure_category'] = wrapper['failure_category'](response['returncode'], response['stderr']) if response['returncode'] else 'UNEXPECTED_OUTPUT'
    with os.fdopen(os.open(folder / 'assessment.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'w') as stream:
        json.dump(summary, stream, sort_keys=True, indent=2, allow_nan=False)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--local-check', action='store_true')
    args = parser.parse_args()
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
