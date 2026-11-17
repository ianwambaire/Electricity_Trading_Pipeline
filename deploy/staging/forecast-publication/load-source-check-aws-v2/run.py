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
OWN = 'deploy/staging/forecast-publication/load-source-check-aws-v2/'
OLD = 'deploy/staging/forecast-publication/load-source-check/'
ORIGINAL = OLD + 'REMOTE-MANIFEST.json'
ORIGINAL_SHA = 'd4fec87a1eab63c1671b1d6820db10aca0ee7618633b079dad6fc91eaf089065'
WRAPPER = 'deploy/staging/forecast-consistency-release/run_preflight.py'
BASE = 'deploy/staging/forecast-consistency-release/preflight_readonly.py'
PROVIDER = 'src/powerflow_secrets.py'
NEW_FILES = {OWN + name for name in ['run.py', 'inspect.py', 'sdk.py', 'SDK-LOCK.json', 'lock_sdk.py', 'build.py', 'REVIEW.md']}
NEW_FILES |= {'tests/test_load_source_aws_adapter.py'}
REMOTE = 'sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -'
LIMITS = {'remote_seconds': 60, 'local_seconds': 90, 'escalation_seconds': 5, 'attempts': 1, 'capture_bytes': 16384}
SDK_CAUSES = {'AWS_CONFIGURATION_REJECTED', 'AWS_ROLE_UNVERIFIED', 'AWS_ACCESS_FAILED',
    'AWS_ACCESS_DENIED', 'AWS_SECRET_NOT_FOUND', 'AWS_DECRYPTION_FAILED', 'AWS_REQUEST_REJECTED',
    'AWS_RESPONSE_BOUND', 'AWS_EMPTY_SECRET', 'SDK_RUNTIME_MISMATCH', 'SDK_IMPORT_REJECTED',
    'SDK_IDENTITY_REJECTED', 'SDK_DEPENDENCY_MISMATCH', 'SDK_MODEL_REJECTED', 'SDK_TLS_REJECTED',
    'SDK_INVENTORY_MISMATCH', 'SDK_PROCESS_TIMEOUT', 'SDK_OUTPUT_BOUND', 'SDK_PROCESS_FAILURE', 'SDK_UNEXPECTED_OUTPUT'}


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


def original_manifest(raw):
    need(sha(raw) == ORIGINAL_SHA)
    return json.loads(raw)


def host_source(raw):
    """Reuse host helpers, remove env-only gate, permit fixed SDK owner pair."""
    text = raw.decode()
    tree = ast.parse(text)
    guards = [n for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and isinstance(n.value.func, ast.Name) and n.value.func.id == 'need'
              and len(n.value.args) == 2 and isinstance(n.value.args[1], ast.Constant)
              and n.value.args[1].value == 'AUTH_BACKEND_REQUIRES_VERIFIED_SDK']
    need(len(guards) == 1)
    guard = guards[0]
    need(ast.dump(guard.value.args[0], include_attributes=False) == ast.dump(ast.parse("backend == 'env'", mode='eval').body, include_attributes=False))
    lines = text.splitlines(keepends=True)
    for line in range(guard.lineno - 1, guard.end_lineno):
        lines[line] = '\n'
    text = ''.join(lines)
    owner_checks = [n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Compare)
                    and ast.dump(n, include_attributes=False) == ast.dump(ast.parse('before.st_uid == owner', mode='eval').body, include_attributes=False)]
    need(len(owner_checks) == 1 and text.count('before.st_uid == owner') == 1)
    # Scalar owner checks for environment, source, procfs and runtime stay exact.
    # SDK code/data alone may be root- or pipeline-owned; never use a separate
    # pathname stat to choose an owner before a no-follow anchored capture.
    text = text.replace('before.st_uid == owner',
        '(before.st_uid == owner if isinstance(owner, int) else owner == (0, 1000) and before.st_uid in owner '
        'and bool(before.st_mode & (0o400 if before.st_uid == 1000 else 0o040 if before.st_gid == 1000 else 0o004)))', 1)
    tree = ast.parse(text)
    functions = {'need', 'capture', 'worker', 'worker_environment', 'prefect', 'deployment_environment', 'configured_environment', 'drop_identity'}
    constants = {'ROOT', 'DEP', 'UNIT', 'WORKER_SHA', 'CAUSES'}
    selected = []
    found = set()
    for node in tree.body:
        take = isinstance(node, (ast.Import, ast.ImportFrom))
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            take = True
            found.add(node.name)
        if isinstance(node, ast.ClassDef) and node.name == 'Stop':
            take = True
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in constants:
            take = True
        if take:
            selected.append(ast.get_source_segment(text, node))
    need(found == functions and all(s is not None for s in selected))
    return ('\n\n'.join(selected) + '\n').encode()


def assemble(blobs):
    old = namespace(blobs[OLD + 'run.py'], 'original_assembly', ROOT / (OLD + 'run.py'))
    lock = json.loads(blobs[OWN + 'SDK-LOCK.json'])
    need(set(lock) == {'version', 'runtime', 'versions', 'code_roots', 'files'} and lock['version'] == 1 and lock['runtime'] == [3, 14])
    need(lock['code_roots'] == ['boto3', 'botocore', 's3transfer', 'jmespath', 'dateutil', 'urllib3', 'six.py'])
    need(lock['versions'] == {'boto3': '1.43.98', 'botocore': '1.43.98', 's3transfer': '0.19.2',
         'jmespath': '1.1.0', 'python-dateutil': '2.9.0.post0', 'urllib3': '2.7.0', 'six': '1.17.0'})
    need(0 < len(lock['files']) <= 300)
    for name, item in lock['files'].items():
        need(not Path(name).is_absolute() and '..' not in Path(name).parts
             and re.fullmatch(r'[A-Za-z0-9_./+-]+', name) is not None)
        code = name == 'six.py' or name.endswith('.py') and name.split('/')[0] in lock['code_roots']
        data = name.startswith('botocore/data/') and name.endswith(('.json', '.json.gz'))
        metadata = name.endswith('.dist-info/METADATA') and len(Path(name).parts) == 2
        need(code or data or metadata)
        need(set(item) == {'bytes', 'sha256'} and type(item['bytes']) is int and 0 <= item['bytes'] <= 2_000_000
             and re.fullmatch('[0-9a-f]{64}', item['sha256']) is not None)
    hashes = {name: sha(blobs[name]) for name in sorted(old['CONTRACTS'])}
    child = "PROVIDER={'__name__':'retained_provider'}\nexec(compile(" + repr(old['provider_source'](blobs[PROVIDER])) + ",'<retained-provider>','exec'),PROVIDER)\n"
    child += 'SDK_FILES=' + repr(lock['files']) + '\n'
    child += "exec(compile(" + repr(blobs[OWN + 'sdk.py']) + ",'<verified-aws-sdk-adapter>','exec'),{'__name__':'__main__','PROVIDER':PROVIDER,'SDK_FILES':SDK_FILES})\n"
    need(len(child.encode()) <= 100000)
    text = "BOUND={'__name__':'verified_supervisor'}\nexec(compile(" + repr(old['bounded_source'](blobs[BASE])) + ",'<verified-bound>','exec'),BOUND)\n"
    for name, raw in [('CORE', blobs[OLD + 'check.py']), ('PARSER', blobs[OLD + 'vendor/parser.py']),
                      ('VARIABLES', blobs[OLD + 'vendor/variables.py']), ('PROVIDER', old['provider_source'](blobs[PROVIDER])),
                      ('AWS', blobs[OWN + 'sdk.py'])]:
        text += name + "={'__name__':" + repr('verified_' + name) + "}\nexec(compile(" + repr(raw) + ",'<verified-dependency>','exec')," + name + ')\n'
    text += "H={'__name__':'verified_host','PROVIDER':PROVIDER,'PARSER':PARSER,'VARIABLES':VARIABLES,'BOUNDED':BOUND['bounded_run']}\n"
    text += "exec(compile(" + repr(host_source(blobs[OLD + 'inspect.py'])) + ",'<verified-host>','exec'),H)\n"
    text += "S={'__name__':'__main__','H':H,'AWS':AWS,'PROVIDER':PROVIDER,'CORE':CORE,'SDK_LOCK':" + repr(lock) + ",'SOURCE_HASHES':" + repr(hashes) + ",'CHILD_SOURCE':" + repr(child.encode()) + '}\n'
    text += "exec(compile(" + repr(blobs[OWN + 'inspect.py']) + ",'<verified-aws-source-inspector>','exec'),S)\n"
    return text.encode()


def validate_report(report, old_validator):
    need(type(report) is dict and set(report) == {'status', 'phase', 'cause', 'credential_backend', 'iam_role_verified', 'source_request', 'comparison'})
    need(report['status'] in {'PASS', 'BLOCKED'} and report['phase'] in {'INITIAL', 'SOURCE_BINDINGS', 'CONFIGURATION', 'SDK_VERIFICATION', 'IDENTITY', 'AUTHENTICATION', 'SOURCE_REQUEST', 'COMPARISON'})
    need(report['credential_backend'] in {'UNVERIFIED', 'env', 'ssm', 'secretsmanager'})
    need(type(report['iam_role_verified']) is bool and report['source_request'] in {'NOT_ATTEMPTED', 'ATTEMPTED', 'COMPLETED'})
    if report['status'] == 'PASS':
        need(report['phase'] == 'COMPARISON' and report['credential_backend'] in {'ssm', 'secretsmanager'}
             and report['iam_role_verified'] and report['source_request'] == 'COMPLETED')
        old_validator({'status': 'PASS', 'phase': 'COMPARISON', 'cause': report['cause'], 'comparison': report['comparison']})
    else:
        need(report['comparison'] is None)
        if report['cause'] not in SDK_CAUSES:
            old_validator({'status': 'BLOCKED', 'phase': 'INITIAL', 'cause': report['cause'], 'comparison': None})
    return report


def verify(expected):
    need(type(expected) is str and re.fullmatch('[0-9a-f]{64}', expected) is not None)
    raw = read(HERE / 'MANIFEST.json')
    need(sha(raw) == expected)
    m = json.loads(raw)
    need(set(m) == {'version', 'supersedes_manifest_sha256', 'artifacts', 'payload_sha256', 'limits'})
    need(m['version'] == 2 and m['supersedes_manifest_sha256'] == ORIGINAL_SHA and m['limits'] == LIMITS)
    original = original_manifest(read(ROOT / ORIGINAL))
    need(set(m['artifacts']) == set(original['artifacts']) | NEW_FILES | {ORIGINAL})
    blobs = {}
    for name, item in m['artifacts'].items():
        content = read(ROOT / name)
        need(item == {'bytes': len(content), 'sha256': sha(content)})
        blobs[name] = content
    for name, item in original['artifacts'].items():
        need(m['artifacts'][name] == item)
    need(sha(blobs[ORIGINAL]) == ORIGINAL_SHA)
    payload = assemble(blobs)
    need(len(payload) <= 300000 and sha(payload) == m['payload_sha256'])
    wrapper = namespace(blobs[WRAPPER], 'verified_ssh_wrapper', ROOT / WRAPPER)
    wrapper['profile']()
    old = namespace(blobs[OLD + 'run.py'], 'verified_original_runner', ROOT / (OLD + 'run.py'))
    supervisor = namespace(old['bounded_source'](blobs[BASE]), 'verified_supervisor')['bounded_run']
    validator = namespace(blobs[OWN + 'run.py'], 'verified_result_validator', HERE / 'run.py')['validate_report']
    return payload, wrapper, supervisor, lambda report: validator(report, old['validate_report'])


def execute(payload, wrapper, supervisor, validator):
    argv = wrapper['ssh_argv'](wrapper['profile']())
    argv[-1] = REMOTE
    os.umask(0o077)
    folder = Path(tempfile.mkdtemp(prefix='load-source-aws-v2-', dir=wrapper['PRIVATE'] / 'preflight'))
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
