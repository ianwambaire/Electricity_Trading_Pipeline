"""One fixed read-only source check; live execution needs separate authorization."""
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
OWN = 'deploy/staging/forecast-publication/load-source-check/'
WRAPPER = 'deploy/staging/forecast-consistency-release/run_preflight.py'
BASE = 'deploy/staging/forecast-consistency-release/preflight_readonly.py'
PROVIDER = 'src/powerflow_secrets.py'
CONTRACTS = {'src/ingestion/fetch_entsoe_data.py', 'src/ingestion/incremental_utils.py',
             'src/ingestion/historical_range.py', 'src/scheduled_pipeline.py', PROVIDER}
ARTIFACTS = CONTRACTS | {WRAPPER, BASE, OWN + 'check.py', OWN + 'inspect.py',
    OWN + 'run.py', OWN + 'build_remote.py', OWN + 'REMOTE-REVIEW.md',
    OWN + 'vendor/parser.py', OWN + 'vendor/variables.py', OWN + 'vendor/LICENSE.python-dotenv',
    'tests/test_load_source_adapter.py', 'tests/test_load_source_check.py'}
REMOTE = 'sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        need(stat.S_ISREG(os.fstat(stream.fileno()).st_mode))
        raw = stream.read(2_000_001)
    need(len(raw) <= 2_000_000)
    return raw


def need(ok):
    if not ok:
        raise ValueError('local_binding_or_output_rejected')


def namespace(raw, name, file=None):
    ns = {'__name__': name}
    if file is not None:
        ns['__file__'] = str(file)
    exec(compile(raw, '<verified-' + name + '>', 'exec'), ns)
    return ns


def bounded_source(raw):
    tree = ast.parse(raw)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'bounded_run']
    need(len(functions) == 1)
    # Preserve the exact original text: ast.unparse formatting varies between
    # Python 3.9 and 3.14 and would otherwise change the assembled payload hash.
    segment = ast.get_source_segment(raw.decode(), functions[0])
    need(segment is not None)
    return b'import os,subprocess,selectors,signal,time\n' + segment.encode()


def provider_source(raw):
    tree = ast.parse(raw)
    imports = [n for n in tree.body if isinstance(n, ast.Import) and any(a.name == 'boto3' for a in n.names)]
    need(len(imports) == 1 and len(imports[0].names) == 1)
    # Env backend uses the unchanged provider. AWS code remains uncalled and
    # unimportable: the host adapter rejects those configured backends first.
    lines = raw.decode().splitlines(keepends=True)
    node = imports[0]
    need(node.col_offset == 0)
    return ''.join(lines[:node.lineno - 1] + lines[node.end_lineno:]).encode()


def assemble(blobs):
    hashes = {name: sha(blobs[name]) for name in sorted(CONTRACTS)}
    out = "B=" + repr(bounded_source(blobs[BASE])) + "\n"
    out += "N={'__name__':'verified_bound'};exec(compile(B,'<bound>','exec'),N)\n"
    for symbol, path, raw in [
        ('CORE', 'check', blobs[OWN + 'check.py']),
        ('PARSER', 'dotenv_parser', blobs[OWN + 'vendor/parser.py']),
        ('VARIABLES', 'dotenv_variables', blobs[OWN + 'vendor/variables.py']),
        ('PROVIDER', 'existing_secret_provider', provider_source(blobs[PROVIDER])),
    ]:
        out += symbol + "={'__name__':" + repr(path) + "};exec(compile(" + repr(raw) + ",'<" + path + ">','exec')," + symbol + ")\n"
    out += "S={'__name__':'__main__','CORE':CORE,'PARSER':PARSER,'VARIABLES':VARIABLES,'PROVIDER':PROVIDER,'BOUNDED':N['bounded_run'],'SOURCE_HASHES':" + repr(hashes) + "}\n"
    out += "exec(compile(" + repr(blobs[OWN + 'inspect.py']) + ",'<verified-load-source-adapter>','exec'),S)\n"
    return out.encode()


def validate_report(report):
    need(type(report) is dict and set(report) == {'status', 'phase', 'cause', 'comparison'})
    need(report['status'] in {'PASS', 'BLOCKED'})
    need(report['phase'] in {'INITIAL', 'SOURCE_BINDINGS', 'CONFIGURATION', 'SNAPSHOT', 'IDENTITY', 'AUTHENTICATION', 'SOURCE_REQUEST', 'COMPARISON'})
    cause = report['cause']
    allowed = {'READ_BOUND', 'READ_METADATA', 'READ_DRIFT', 'SOURCE_DRIFT', 'WORKER_STATE',
        'WORKER_IDENTITY', 'WORKER_PROCESS', 'WORKER_ENV', 'DEPLOYMENT_IDENTITY', 'DEPLOYMENT_ENV',
        'POOL_TEMPLATE', 'HTTP_BOUND', 'HTTP_STATUS', 'ENV_SYNTAX', 'ENDPOINT_DRIFT',
        'HISTORY_CONFIGURATION', 'AUTH_BACKEND_REQUIRES_VERIFIED_SDK', 'IDENTITY_DROP',
        'PROFILE_DRIFT', 'SNAPSHOT_DRIFT', 'DEPENDENCY_RUNTIME', 'EVIDENCE_UNVERIFIED',
        'AUTH_UNAVAILABLE', 'SOURCE_HTTP_FAILURE', 'SOURCE_BODY_BOUND', 'SOURCE_ENCODING',
        'SOURCE_DEADLINE', 'SOURCE_REQUEST_FAILURE', 'XML_DECLARATION', 'SOURCE_ACK_FAILURE',
        'DOCUMENT_TYPE', 'PROCESS_TYPE', 'SERIES_COUNT', 'AREA', 'UNIT', 'CURVE_TYPE',
        'PERIOD_COUNT', 'RESOLUTION_MISMATCH', 'PERIOD_GRID', 'PERIOD_BOUND', 'POINT_COUNT',
        'POINT_POSITION', 'DUPLICATE_SOURCE', 'SNAPSHOT_BOUND', 'SNAPSHOT_SCHEMA',
        'SNAPSHOT_ROW_BOUND', 'DUPLICATE_SNAPSHOT', 'EMPTY_SNAPSHOT', 'TIMEZONE_MISSING', 'MALFORMED_EVIDENCE'}
    if report['status'] == 'BLOCKED':
        need(cause in allowed and report['comparison'] is None)
        return report
    need(cause is None and report['phase'] == 'COMPARISON')
    c = report['comparison']
    need(type(c) is dict and set(c) == {'status', 'source_code', 'observed_at_utc',
        'source_sha256', 'snapshot_sha256', 'query_start_utc', 'query_end_exclusive_utc',
        'targets', 'historical_source_availability', 'ingestion_cause'})
    need(c['status'] == 'CHECKED' and c['source_code'] in {'NO_MATCHING_DATA', 'OBSERVATIONS'})
    need(c['historical_source_availability'] == c['ingestion_cause'] == 'UNVERIFIED')
    for key in ('source_sha256', 'snapshot_sha256'):
        need(type(c[key]) is str and re.fullmatch('[0-9a-f]{64}', c[key]) is not None)
    for key in ('observed_at_utc', 'query_start_utc', 'query_end_exclusive_utc'):
        need(type(c[key]) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+00:00', c[key]) is not None)
    need(type(c['targets']) is list and len(c['targets']) == 3)
    for minute, row in zip((15, 30, 45), c['targets']):
        need(type(row) is dict and set(row) == {'timestamp', 'source', 'snapshot', 'normal_overlap_revisits'})
        need(row['timestamp'] == '2026-11-03T15:' + str(minute) + ':00+00:00')
        need(row['source'] in {'PRESENT', 'ABSENT', 'INCOMPLETE'} and row['snapshot'] in {'PRESENT', 'ABSENT', 'INCOMPLETE'})
        need(type(row['normal_overlap_revisits']) is bool)
    return report


def verify(expected):
    need(re.fullmatch('[0-9a-f]{64}', expected) is not None)
    raw = read(HERE / 'REMOTE-MANIFEST.json')
    need(sha(raw) == expected)
    manifest = json.loads(raw)
    need(set(manifest) == {'version', 'action', 'artifacts', 'payload_sha256', 'limits', 'authentication'})
    need(manifest['version'] == 1 and manifest['action'] == 'fixed-load-source-check')
    need(manifest['limits'] == {'remote_seconds': 60, 'local_seconds': 90, 'escalation_seconds': 5, 'attempts': 1, 'capture_bytes': 16384})
    need(manifest['authentication'] == 'existing-env-provider-only-aws-fail-closed')
    need(set(manifest['artifacts']) == ARTIFACTS)
    blobs = {}
    for name, item in manifest['artifacts'].items():
        data = read(ROOT / name)
        need(set(item) == {'bytes', 'sha256'} and item['bytes'] == len(data) and item['sha256'] == sha(data))
        blobs[name] = data
    payload = assemble(blobs)
    need(len(payload) <= 200000 and sha(payload) == manifest['payload_sha256'])
    wrapper = namespace(blobs[WRAPPER], 'pinned_ssh_wrapper', ROOT / WRAPPER)
    wrapper['profile']()
    supervisor = namespace(bounded_source(blobs[BASE]), 'retained_supervisor')['bounded_run']
    # Output validation too is compiled from retained verified wrapper bytes.
    validator = namespace(blobs[OWN + 'run.py'], 'retained_output_validator', HERE / 'run.py')['validate_report']
    return payload, wrapper, supervisor, validator


def execute(payload, wrapper, supervisor, validator):
    profile = wrapper['profile']()
    argv = wrapper['ssh_argv'](profile)
    argv[-1] = REMOTE
    os.umask(0o077)
    folder = Path(tempfile.mkdtemp(prefix='load-source-', dir=wrapper['PRIVATE'] / 'preflight'))
    result = supervisor(argv, input=payload, timeout=90, limit=16384, grace=5)
    summary = {'exit_status': result['returncode'], 'failure_category': result['failure'], 'report': None}
    # Never persist raw output: sanitize through the strict schema first. Even an
    # unexpected remote traceback or secret-like diagnostic cannot enter evidence.
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--local-check', action='store_true')
    args = parser.parse_args()
    try:
        payload, wrapper, supervisor, validator = verify(args.manifest_sha256)
        if args.local_check:
            print('{"local_integrity":"PASS","remote_attempts":0}')
            return 0
        summary = execute(payload, wrapper, supervisor, validator)
    except Exception:
        summary = {'exit_status': None, 'failure_category': 'LOCAL_VERIFICATION_OR_CAPTURE_FAILURE', 'report': None}
    print(json.dumps(summary, sort_keys=True, allow_nan=False))
    return 0 if summary['report'] and summary['report']['status'] == 'PASS' and summary['failure_category'] is None else 1


if __name__ == '__main__':
    raise SystemExit(main())
