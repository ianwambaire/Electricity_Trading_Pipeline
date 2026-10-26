import hashlib
import json
from pathlib import Path
import subprocess

repo = Path('/Users/iannganga/Desktop/electricity-trading-pipeline')
supervisor = repo / 'deploy/remediation/a3-bounded-local.py'
assert hashlib.sha256(supervisor.read_bytes()).hexdigest() == (
    '9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40'
)

payload = r'''
import glob
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess

ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'}
STATE = Path('/var/lib/powerflow-staging-https-20261026')
STAGING = Path('/etc/nginx/conf.d/powerflow-staging-acme.conf')
PROBE = Path(
    '/var/www/powerflow-staging-acme/'
    '.well-known/acme-challenge/preflight-probe'
)
HOST = 'staging.powerflowenergy.dev'
URL = '/.well-known/acme-challenge/preflight-probe'
EXPECTED_PROBE = b'powerflow-staging-acme-preflight\n'

def run(args, **kwargs):
    try:
        result = subprocess.run(
            args, capture_output=True, timeout=3, env=ENV, **kwargs
        )
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return 124, b''
    except OSError:
        return 127, b''

def metadata(path):
    try:
        item = os.lstat(path)
        return {
            'path': str(path),
            'exists': True,
            'symlink': stat.S_ISLNK(item.st_mode),
            'directory': stat.S_ISDIR(item.st_mode),
            'regular_file': stat.S_ISREG(item.st_mode),
            'mode': oct(stat.S_IMODE(item.st_mode)),
            'uid': item.st_uid,
            'gid': item.st_gid,
            'bytes': item.st_size,
        }
    except FileNotFoundError:
        return {'path': str(path), 'exists': False}
    except OSError:
        return {'path': str(path), 'status': 'UNREADABLE_METADATA'}

def baseline_check(baseline, expected_paths):
    # Never follow paths supplied by an unchecked manifest.
    try:
        if baseline.stat().st_size > 4096:
            return {'status': 'INVALID_BASELINE'}
        entries = {}
        for line in baseline.read_text().splitlines():
            match = re.fullmatch(r'([0-9a-f]{64})  (/.+)', line)
            if not match or match[2] in entries:
                return {'status': 'INVALID_BASELINE'}
            entries[match[2]] = match[1]
        if set(entries) != set(expected_paths):
            return {'status': 'UNEXPECTED_BASELINE_PATHS'}
        results = {}
        for name in expected_paths:
            digest = hashlib.sha256()
            with open(name, 'rb') as handle:
                for block in iter(lambda: handle.read(65536), b''):
                    digest.update(block)
            results[name] = digest.hexdigest() == entries[name]
        return {'status': 'CHECKED', 'matches': results}
    except OSError:
        return {'status': 'UNREADABLE'}

# Bounded on-disk include hierarchy; never use nginx -t/-T.
config_root = Path('/etc/nginx')
seen = set()
edges = []
summaries = []
limitations = []
total_bytes = 0

def inspect_config(path, depth=0):
    global total_bytes
    path = Path(path)
    resolved = path.resolve()
    if config_root not in resolved.parents:
        raise ValueError('include_outside_etc_nginx')
    if depth > 8 or len(seen) >= 32:
        raise ValueError('include_depth_or_count_limit')
    if resolved in seen:
        return
    if not resolved.is_file() or resolved.stat().st_size > 65536:
        raise ValueError('configuration_file_type_or_size')
    seen.add(resolved)
    raw = resolved.read_bytes()
    total_bytes += len(raw)
    if total_bytes > 524288:
        raise ValueError('configuration_total_size_limit')

    # Tokens are retained only in memory; emit allowlisted summaries.
    lexer = shlex.shlex(
        raw.decode('utf-8'), posix=True, punctuation_chars='{};'
    )
    lexer.whitespace_split = True
    lexer.commenters = '#'
    tokens = list(lexer)
    directives = []
    current = []
    for token in tokens:
        if token in (';', '{', '}'):
            if current:
                directives.append(current)
            current = []
        else:
            current.append(token)

    listens = []
    exact_names = []
    includes = []
    location_summaries = []
    returns = []
    other_names = 0
    for directive in directives:
        name, args = directive[0], directive[1:]
        if name == 'include' and len(args) == 1:
            includes.append(args[0])
        elif name == 'listen' and args:
            value = args[0]
            listens.append({
                'address': value if value in {
                    '80', '[::]:80', '0.0.0.0:80',
                    '127.0.0.1:80', '443', '[::]:443',
                } else '[other address redacted]',
                'default_server': 'default_server' in args,
            })
        elif name == 'server_name':
            exact_names.extend(value for value in args if value in {
                HOST, 'powerflowenergy.dev', 'www.powerflowenergy.dev',
            })
            other_names += sum(value not in {
                HOST, 'powerflowenergy.dev', 'www.powerflowenergy.dev',
            } for value in args)
        elif name == 'location':
            location_summaries.append({
                'exact_reviewed_acme_location':
                    args == ['^~', '/.well-known/acme-challenge/'],
                'root_location': args == ['/'],
                'regex_location': bool(args and args[0] in ('~', '~*')),
            })
        elif name == 'return' and args:
            returns.append(args[0] if args[0].isdigit() else '[nonstatus]')
    summaries.append({
        'file': str(path),
        'listen_directives': listens,
        'known_server_names': exact_names,
        'other_server_name_count': other_names,
        'locations': location_summaries,
        'return_statuses': returns,
        'reviewed_webroot_directive_present': any(
            d == ['root', '/var/www/powerflow-staging-acme']
            for d in directives
        ),
        'reviewed_try_files_present': any(
            d == ['try_files', '$uri', '=404'] for d in directives
        ),
        'rewrite_directive_count':
            sum(d[0] == 'rewrite' for d in directives),
        'alias_directive_count':
            sum(d[0] == 'alias' for d in directives),
    })

    for pattern in includes:
        candidate = Path(pattern)
        if not candidate.is_absolute():
            candidate = config_root / candidate
        if '..' in candidate.parts or config_root not in candidate.parents:
            raise ValueError('unsupported_include_path')
        if candidate == config_root / 'mime.types':
            edges.append({
                'from': str(path),
                'to': str(candidate),
                'status': 'MIME_TABLE_NOT_READ',
            })
            continue
        matches = sorted(glob.glob(str(candidate)))
        if len(matches) > 32:
            raise ValueError('include_match_limit')
        if not matches:
            edges.append({
                'from': str(path),
                'to': str(candidate),
                'status': 'NO_MATCH',
            })
        for match in matches:
            edges.append({'from': str(path), 'to': match})
            inspect_config(match, depth + 1)

try:
    inspect_config(config_root / 'nginx.conf')
    config_status = 'BOUNDED_INSPECTION_COMPLETE'
except (OSError, ValueError, UnicodeError):
    config_status = 'INCOMPLETE'
    limitations.append('Include inspection encountered an unsupported path/parser limit')

# Listener output contains only socket/process-name metadata, never argv.
listener_code, listener_bytes = run([
    '/usr/sbin/ss', '-ltnp', 'sport = :80',
])
listeners = listener_bytes.decode(errors='replace').splitlines()

# Worker IDs only; no command arguments.
process_code, process_bytes = run([
    '/usr/bin/ps', '-C', 'nginx',
    '-o', 'pid=,uid=,gid=,comm=',
])
workers = []
processes = []
for line in process_bytes.decode(errors='replace').splitlines():
    values = line.split()
    if len(values) != 4 or values[3] != 'nginx':
        continue
    pid, uid, gid = map(int, values[:3])
    processes.append({'pid': pid, 'uid': uid, 'gid': gid})
    if uid != 0:
        workers.append((pid, uid, gid))
if len(workers) > 8:
    raise ValueError('worker_count_limit')

parents = [
    '/', '/var', '/var/www',
    '/var/www/powerflow-staging-acme',
    '/var/www/powerflow-staging-acme/.well-known',
    '/var/www/powerflow-staging-acme/.well-known/acme-challenge',
]

# Test DAC traversal/readability using worker UID/GID/supplementary groups.
# This does not reproduce the worker's SELinux domain.
worker_results = []
for pid, uid, gid in workers:
    status_path = Path('/proc') / str(pid) / 'status'
    try:
        status = status_path.read_text()
        groups_line = next(
            line for line in status.splitlines()
            if line.startswith('Groups:')
        )
        groups = [int(value) for value in groups_line.split()[1:]]
        child_code = (
            "import json,os;"
            "paths=" + repr(parents) + ";"
            "probe=" + repr(str(PROBE)) + ";"
            "out={'traversal':{p:os.access(p,os.X_OK) for p in paths},"
            "'probe_readable':os.access(probe,os.R_OK)};"
            "print(json.dumps(out))"
        )
        code, output = run([
            '/usr/bin/python3', '-I', '-S', '-B', '-c', child_code,
        ], user=uid, group=gid, extra_groups=groups)
        result = json.loads(output) if code == 0 else {
            'status': 'CREDENTIAL_TEST_FAILED', 'exit_status': code
        }
    except (OSError, StopIteration, ValueError):
        result = {'status': 'WORKER_METADATA_UNAVAILABLE'}
    worker_results.append({'pid': pid, 'uid': uid, 'gid': gid, **result})

try:
    probe_bytes = PROBE.read_bytes() if PROBE.stat().st_size <= 4096 else None
    probe_content_matches = probe_bytes == EXPECTED_PROBE
except OSError:
    probe_content_matches = None

# Exactly one IPv4 loopback HTTP request. No DNS, redirects or body output.
http_result = {}
connection = http.client.HTTPConnection('127.0.0.1', 80, timeout=3)
try:
    connection.request('GET', URL, headers={'Host': HOST})
    response = connection.getresponse()
    allowed = {'server', 'content-type', 'content-length', 'connection'}
    http_result = {
        'status': response.status,
        'safe_headers': {
            name.lower(): value
            for name, value in response.getheaders()
            if name.lower() in allowed
        },
        'location_header_present': response.getheader('Location') is not None,
    }
except OSError:
    http_result = {'status': 'REQUEST_FAILED'}
finally:
    connection.close()

production_preservation = baseline_check(
    STATE / 'production-before.sha256',
    [
        '/etc/nginx/conf.d/powerflow.conf',
        '/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem',
    ],
)
staging_config_preservation = baseline_check(
    STATE / 'staging-http.sha256', [str(STAGING)]
)

service_code, service_output = run([
    '/usr/bin/systemctl', 'show',
    'powerflow-api.service', 'powerflow-streamlit.service',
    '--property=Id,MainPID,ActiveState,SubState',
])
try:
    baseline = (STATE / 'services-before').read_bytes()
    service_matches = service_code == 0 and service_output == baseline
except OSError:
    service_matches = None

print(json.dumps({
    'configuration_inspection_status': config_status,
    'include_hierarchy': edges,
    'configuration_summaries': summaries,
    'staging_config_present': STAGING.exists(),
    'staging_config_reached_by_includes': STAGING.resolve() in seen,
    'staging_config_matches_failed_setup_baseline':
        staging_config_preservation,
    'exact_staging_server_name_occurrences': sum(
        item['known_server_names'].count(HOST) for item in summaries
    ),
    'port80_listener_exit_status': listener_code,
    'port80_listeners': listeners,
    'nginx_process_metadata_exit_status': process_code,
    'nginx_processes': processes,
    'path_metadata': [metadata(p) for p in parents] + [metadata(PROBE)],
    'probe_matches_expected_public_content': probe_content_matches,
    'worker_DAC_checks': worker_results,
    'loopback_http': http_result,
    'production_configuration_and_certificate': production_preservation,
    'production_API_Streamlit_service_identity_matches':
        service_matches,
    'limitations': limitations + [
        'On-disk token inspection is not full Nginx parsing or proof of loaded configuration',
        'Location summaries identify possible interception, not definitive runtime selection',
        'Worker DAC tests do not reproduce SELinux/AppArmor confinement',
        'HTTP request can generate normal access/error logs',
    ],
}, indent=2))
'''.encode()

command = [
    str(repo / 'venv/bin/python'), '-B', str(supervisor), '--',
    'ssh', '-F', '/dev/null',
    '-i', '/Users/iannganga/.ssh/powerflow-key.pem',
    '-o', 'BatchMode=yes',
    '-o', 'IdentitiesOnly=yes',
    '-o', 'IdentityAgent=none',
    '-o', 'StrictHostKeyChecking=yes',
    '-o', 'UpdateHostKeys=no',
    '-o', 'UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts',
    '-o', 'ForwardAgent=no',
    '-o', 'RequestTTY=no',
    '-o', 'ConnectTimeout=10',
    '-o', 'ServerAliveInterval=10',
    '-o', 'ServerAliveCountMax=3',
    '-T', 'ec2-user@3.228.243.164',
    'sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s '
    '60s /usr/bin/python3 -I -S -B -',
]

result = subprocess.run(
    command, input=payload, capture_output=True, cwd=repo,
)
print('Diagnostic exit status:', result.returncode)
if result.stdout:
    try:
        report = json.loads(result.stdout)
    except (ValueError, UnicodeDecodeError):
        print('STOP: unexpected output; raw output withheld.')
        raise SystemExit(1)
    print(json.dumps(report, indent=2))
else:
    # Local reporting only: no new remote calls, file capture or retries.
    error = result.stderr.decode(errors='replace').lower()
    category = 'unclassified_no_report'
    if 'host key verification failed' in error or 'remote host identification has changed' in error:
        category = 'ssh_host_key_verification_failed'
    elif 'permission denied (publickey' in error:
        category = 'ssh_public_key_authentication_failed'
    elif 'connection timed out' in error or 'operation timed out' in error:
        category = 'ssh_connection_timeout'
    elif 'connection refused' in error:
        category = 'ssh_connection_refused'
    elif 'no route to host' in error:
        category = 'ssh_no_route_to_host'
    elif 'sudo:' in error:
        category = 'remote_sudo_error'
    elif result.returncode == 124:
        category = 'bounded_execution_timeout'
    elif result.returncode == 255:
        category = 'ssh_failed_cause_unclassified'
    print(json.dumps({
        'diagnostic_exit_status': result.returncode,
        'report_produced': False,
        'failure_category': category,
        'raw_stderr_withheld': True,
        'remote_checks_completed': 'unknown',
        'retry_performed': False,
    }, indent=2))
raise SystemExit(result.returncode)
