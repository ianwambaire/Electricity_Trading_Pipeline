"""PROPOSED capture-only deployment. No inference, service mutation or Git command."""
import base64
import datetime as dt
import hashlib
import http.client
import importlib.metadata
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import subprocess
import sys
import uuid
import urllib.request

CONFIG = __CONFIG__
ROOT = Path('/home/ec2-user/Electricity_Trading_Pipeline')
BACKUP = Path('/home/ec2-user/powerflow-inference-evidence-backup-20261031-v1')
RECEIPTS = ROOT/'data/reports/next24h_inference'
PROC = Path('/proc')
DEP = '47e5ef51-26d0-44b6-b119-2c40d0e77397'
UNITS = ['powerflow-api.service', 'powerflow-streamlit.service',
         'powerflow-prefect-worker.service', 'powerflow-prefect-server.service',
         'postgresql.service', 'powerflow-candidate-api.service']
BASELINES = ['/etc/nginx/conf.d/powerflow.conf', '/etc/nginx/conf.d/powerflow-staging-https.conf',
             '/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem']
FORECASTS = ['data/reports/next24h_forecast.csv', 'data/reports/next24h_forecast_history.csv',
            'data/reports/next24h_forecast_provenance.json']
INSTALL_ORDER = ['src/models/inference_evidence.py', 'src/models/next24h.py', 'src/models/next24h_production.py']
RESULT = {'stage': 'preflight', 'installed': [], 'created_paths': [], 'temporary_paths': [],
          'modifications_started': False, 'automatic_rollback': False, 'service_restart': False}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def read(path):
    with os.fdopen(os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NOATIME), 'rb') as stream:
        raw = stream.read(2_000_001)
    require(len(raw) <= 2_000_000, 'file_read_bound')
    return raw


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def api(path, body=None):
    request = urllib.request.Request('http://127.0.0.1:4200/api'+path,
        data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    # Never route loopback API queries through inherited proxy configuration.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=3) as response:
        raw = response.read(1_000_001)
    require(len(raw) <= 1_000_000, 'prefect_bound')
    return json.loads(raw)


def deployment_configuration():
    d = api('/deployments/'+DEP)
    s = d.get('schedules', [])
    g = d.get('global_concurrency_limit') or {}
    require(d.get('id') == DEP and d.get('name') == 'powerflow-entsoe-pipeline'
            and d.get('entrypoint') == 'src/scheduled_pipeline.py:powerflow_entsoe_pipeline'
            and d.get('paused') is False, 'deployment_drift')
    require(len(s) == 1 and s[0].get('id') == '9319f665-9836-4120-9801-031e23ad2b4a'
            and s[0].get('active') is True
            and s[0].get('schedule') == {'cron': '45 * * * *', 'timezone': 'UTC', 'day_or': True}, 'schedule_drift')
    require(g.get('limit') == 1 and g.get('active') is True
            and d.get('concurrency_options') is None, 'concurrency_or_collision_drift')
    return {'id': DEP, 'schedule_id': s[0]['id'], 'schedule': s[0]['schedule'],
            'schedule_active': True, 'paused': False, 'concurrency_limit': 1,
            'concurrency_active': True, 'collision_policy': d.get('concurrency_options'),
            'active_slots': g.get('active_slots')}


def process_visibility():
    with (PROC/'self/mountinfo').open('r') as stream:
        raw = stream.read(1_000_001)
    require(len(raw) <= 1_000_000, 'mountinfo_bound')
    mounts = []
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) > 6 and fields[4] == '/proc':
            separator = fields.index('-')
            require(fields[3] == '/' and fields[separator+1] == 'proc', 'process_visibility_unverified')
            options = (fields[5]+','+fields[separator+3]).split(',')
            require(not any(option.startswith('hidepid=') and option != 'hidepid=0' for option in options),
                    'process_visibility_restricted')
            mounts.append(True)
    require(len(mounts) == 1, 'process_visibility_unverified')
    return {'proc_mount_verified': True, 'hidepid_disabled': True}


def ingestion_processes():
    """Inspect visible-process argv for fixed markers; never report argv or environments."""
    visibility = process_visibility()
    entries = [p for p in PROC.iterdir() if p.name.isdigit()]
    require(len(entries) < 32768, 'process_scan_bound')
    matched = []
    scanned = 0
    for entry in entries:
        try:
            owner = entry.stat().st_uid
            if int(entry.name) == os.getpid():
                continue
            with (entry/'cmdline').open('rb') as stream:
                raw = stream.read(65537)
            require(len(raw) <= 65536, 'process_argv_bound')
            scanned += 1
            arguments = raw.replace(b'\0', b' ')
            role = None
            if b'fetch_entsoe_data' in arguments:
                role = 'ingestion'
            elif any(marker in arguments for marker in (b'scheduled_pipeline', b'prefect.engine', b'prefect.flow_engine')):
                role = 'pipeline_engine'
            if role:
                matched.append({'pid': int(entry.name), 'uid': owner, 'role': role})
        except (FileNotFoundError, ProcessLookupError):
            continue  # Process exited during the scan; no live argv was missed.
        except PermissionError:
            raise RuntimeError('process_scan_permission_denied') from None
    return {'scope': 'all_visible_uids', 'complete': True, 'visibility': visibility,
            'scanned_processes': scanned, 'matches': matched}


def no_ingestion():
    result = ingestion_processes()
    require(not result['matches'], 'active_ingestion_or_pipeline_process')
    return result


def idle(now=None):
    configuration = deployment_configuration()
    require(configuration['active_slots'] == 0, 'concurrency_not_idle')
    now = now or dt.datetime.now(dt.timezone.utc)
    next_time = now.replace(minute=45, second=0, microsecond=0)
    if next_time <= now:
        next_time += dt.timedelta(hours=1)
    require((next_time-now).total_seconds() >= 600, 'schedule_window_under_ten_minutes')
    active = api('/flow_runs/filter', {'deployments': {'id': {'any_': [DEP]}},
        'flow_runs': {'state': {'type': {'any_': ['RUNNING','PENDING','CANCELLING','PAUSED']}}}, 'limit': 20})
    require(not active, 'active_prefect_run')
    queued = api('/flow_runs/filter', {'deployments': {'id': {'any_': [DEP]}},
        'flow_runs': {'state': {'type': {'any_': ['SCHEDULED']}}}, 'sort': 'EXPECTED_START_TIME_ASC', 'limit': 4})
    scheduled = []
    for run in queued:
        require(run.get('deployment_id') == DEP and isinstance(run.get('id'), str), 'queued_run_identity')
        stamp = dt.datetime.fromisoformat(run['expected_start_time'].replace('Z', '+00:00'))
        require(stamp.tzinfo is not None, 'queued_run_timezone')
        require(stamp >= now+dt.timedelta(minutes=10), 'imminent_queued_run')
        scheduled.append({'id': run['id'], 'scheduled_utc': stamp.isoformat()})
    require(len({r['scheduled_utc'] for r in scheduled}) == len(scheduled), 'duplicate_scheduled_runs')
    processes = no_ingestion()
    return {'configuration': configuration, 'process_scan': processes,
            'next_cron_utc': next_time.isoformat(), 'next_queued_run': scheduled[0] if scheduled else None}


def resources():
    mem = {}
    for line in (PROC/'meminfo').read_text().splitlines():
        key = line.split(':', 1)[0]
        if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            value = line.split()
            require(len(value) == 3 and value[2] == 'kB', 'memory_units')
            mem[key] = int(value[1])*1024
    require(set(mem) == {'MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'}, 'memory_counters_missing')
    require(0 <= mem['MemAvailable'] <= mem['MemTotal'] and 0 <= mem['SwapFree'] <= mem['SwapTotal'], 'memory_counters_invalid')
    fs = os.statvfs(ROOT)
    result = {**mem, 'swap_used_bytes': mem['SwapTotal']-mem['SwapFree'],
              'disk_total_bytes': fs.f_blocks*fs.f_frsize,
              'disk_available_bytes': fs.f_bavail*fs.f_frsize,
              'disk_used_bytes': (fs.f_blocks-fs.f_bfree)*fs.f_frsize}
    require(result['disk_available_bytes'] >= 0 and result['disk_used_bytes'] >= 0, 'disk_counters_invalid')
    return result


def require_capacity(value):
    require(value['MemAvailable'] >= 768*1024**2, 'available_ram_below_768_mib')
    require(value['disk_available_bytes'] >= 2*1024**3, 'disk_below_2_gib')
    # No swap-used threshold was reviewed: report it, validate counters, never invent one.


def identities():
    result = subprocess.run(['/usr/bin/systemctl', 'show', *UNITS,
        '--property=Id,User,Group,MainPID,ActiveState,SubState,ActiveEnterTimestampMonotonic,WorkingDirectory'],
        capture_output=True, timeout=5)
    require(result.returncode == 0, 'service_inspection_failed')
    services = {}
    for block in result.stdout.decode().strip().split('\n\n'):
        entry = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
        if 'Id' in entry:
            require(entry['Id'] not in services, 'duplicate_service_identity')
            services[entry['Id']] = entry
    require(set(services) == set(UNITS), 'service_inventory_incomplete')
    require(all(entry.get('ActiveState') == 'active' and entry.get('SubState') == 'running'
                and int(entry.get('MainPID', '0')) > 0 for entry in services.values()), 'service_not_operational')
    return services


def baselines():
    result = subprocess.run(['/usr/bin/sudo', '-n', '/usr/bin/sha256sum', *BASELINES], capture_output=True, timeout=5)
    require(result.returncode == 0, 'baseline_hash_read_failed')
    lines = result.stdout.decode().splitlines()
    require(len(lines) == len(BASELINES), 'baseline_count')
    values = {}
    for line, name in zip(lines, BASELINES):
        value, path = line.split(None, 1)
        require(path == name and re.fullmatch('[0-9a-f]{64}', value), 'baseline_identity')
        values[name] = value
    return values


def hashes_forecasts():
    return {name: digest(read(ROOT/name)) for name in FORECASTS}


class LoopbackHTTPS(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection(('127.0.0.1', 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def http_get(port, path, tls=False):
    connection = (LoopbackHTTPS('staging.powerflowenergy.dev', timeout=2,
                  context=ssl.create_default_context()) if tls
                  else http.client.HTTPConnection('127.0.0.1', port, timeout=2))
    try:
        connection.request('GET', path, headers={'Host': 'staging.powerflowenergy.dev' if tls else '127.0.0.1', 'Connection': 'close'})
        response = connection.getresponse()
        body = response.read(1_000_001)
        require(len(body) <= 1_000_000, 'http_body_bound')
        require(response.status == 200, 'availability_http_status')
        return body
    finally:
        connection.close()


def availability():
    checks = {}
    for label, port, path, expected in (
        ('production_api', 8000, '/health', 'ok'), ('candidate_api', 8010, '/health', 'ok'),
        ('candidate_readiness', 8010, '/ready', 'ready')):
        body = http_get(port, path)
        require(json.loads(body).get('status') == expected, 'availability_payload:'+label)
        checks[label] = 200
    require(http_get(8501, '/_stcore/health').strip() == b'ok', 'streamlit_health_payload')
    checks['streamlit'] = 200
    html = http_get(443, '/', tls=True)
    require(b'<div id="root"></div>' in html, 'react_root_missing')
    assets = re.findall(rb'(?:src|href)="(/assets/[A-Za-z0-9_.-]+\.js)"', html)
    require(assets, 'react_entry_asset_missing')
    require(http_get(443, assets[0].decode('ascii'), tls=True), 'react_entry_asset_empty')
    require(json.loads(http_get(443, '/api/health', tls=True)).get('status') == 'ok', 'staging_proxy_health_payload')
    checks.update(staging_https=200, react_entry_asset=200, staging_api_proxy=200, tls_hostname_chain_verified=True)
    return checks


def verify_private_directory(path):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and not path.is_symlink() and info.st_uid == 1000
            and info.st_gid == 1000 and stat.S_IMODE(info.st_mode) == 0o700, 'private_directory_permissions')
    return {'uid': info.st_uid, 'gid': info.st_gid, 'mode': '0700', 'symlink': False}


def verify_backups():
    result = {'directory': verify_private_directory(BACKUP), 'files': {}}
    for name, item in CONFIG['files'].items():
        if item['previous_sha256'] is None:
            continue
        path = BACKUP/Path(name).name
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and info.st_gid == 1000
                and stat.S_IMODE(info.st_mode) == 0o600, 'backup_permissions')
        require(digest(read(path)) == item['previous_sha256'], 'backup_readback')
        result['files'][name] = {'sha256': item['previous_sha256'], 'mode': '0600', 'uid': 1000, 'gid': 1000}
    return result


def private_write(path, raw, mode):
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, mode)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY|os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace_code(name, raw):
    idle()  # Includes the independent process scan, immediately before each replacement.
    temporary = ROOT/'src/models'/('.evidence-'+uuid.uuid4().hex+'.tmp')
    RESULT['temporary_paths'].append(str(temporary))
    private_write(temporary, raw, 0o644)
    require(digest(read(temporary)) == digest(raw), 'temporary_code_hash')
    os.replace(temporary, ROOT/name)
    RESULT['modifications_started'] = True
    RESULT['installed'].append(name)
    RESULT['temporary_paths'].remove(str(temporary))
    sync_directory(ROOT/'src/models')


def preflight(action):
    require(action in ['apply', 'rollback'], 'action')
    require(os.geteuid() == 1000 and os.getegid() == 1000 and ROOT.resolve(strict=True) == ROOT, 'identity_or_root')
    require(sys.version_info[:3] == (3, 14, 7), 'python_patch_drift')
    for name, version in CONFIG['packages'].items():
        require(importlib.metadata.version(name) == version, 'package_drift')
    require(read(ROOT/'.git/HEAD').decode().strip() == 'ref: refs/heads/main', 'branch_drift')
    require(read(ROOT/'.git/refs/heads/main').decode().strip() == CONFIG['revision'], 'revision_drift')
    for name, h in CONFIG['dependencies'].items():
        require(digest(read(ROOT/name)) == h, 'dependency_drift:'+name)
    before = {'idle': idle(), 'services': identities(), 'configuration': baselines(),
              'forecasts': hashes_forecasts(), 'availability': availability()}
    for parent in [ROOT/'src', ROOT/'src/models', ROOT/'data', ROOT/'data/reports']:
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and not parent.is_symlink() and info.st_uid == 1000
                and info.st_gid == 1000 and not info.st_mode & 0o022, 'parent_permissions')
    payload = {}
    if action == 'apply':
        require(not os.path.lexists(BACKUP) and not os.path.lexists(RECEIPTS), 'backup_or_receipt_conflict')
        for name, item in CONFIG['files'].items():
            raw = base64.b64decode(item['base64'], validate=True)
            require(digest(raw) == item['sha256'], 'payload_hash')
            compile(raw, name, 'exec')
            expected = item['previous_sha256']
            if expected is None:
                require(not os.path.lexists(ROOT/name), 'new_file_conflict')
            else:
                info = (ROOT/name).lstat()
                require(stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and info.st_gid == 1000
                        and stat.S_IMODE(info.st_mode) == 0o644, 'code_permissions')
                require(digest(read(ROOT/name)) == expected, 'code_drift:'+name)
            payload[name] = raw
    else:
        verify_private_directory(RECEIPTS)
        verify_backups()
        for name, item in CONFIG['files'].items():
            require(digest(read(ROOT/name)) == item['sha256'], 'rollback_current_drift')
            if item['previous_sha256'] is not None:
                payload[name] = read(BACKUP/Path(name).name)
    # Last read-only gates before the first filesystem mutation.
    before['idle'] = idle()
    RESULT['resources_before'] = resources()
    require_capacity(RESULT['resources_before'])
    return before, payload


def postflight(before, action):
    RESULT['stage'] = 'post_resources'
    RESULT['resources_after'] = resources()
    require_capacity(RESULT['resources_after'])
    RESULT['stage'] = 'post_directories_backups'
    RESULT['receipt_directory'] = verify_private_directory(RECEIPTS)
    RESULT['backup_verification'] = verify_backups()
    expected = {name: item['sha256'] if action == 'apply' or item['previous_sha256'] is None
                else item['previous_sha256'] for name, item in CONFIG['files'].items()}
    RESULT['source_hashes'] = {name: digest(read(ROOT/name)) for name in expected}
    require(RESULT['source_hashes'] == expected, 'installed_hash')
    RESULT['stage'] = 'post_prefect'
    after_idle = idle()
    require(after_idle['configuration'] == before['idle']['configuration'], 'prefect_configuration_changed')
    RESULT['prefect_configuration_preserved'] = True
    RESULT['next_prefect_run'] = after_idle['next_queued_run']
    RESULT['next_cron_utc'] = after_idle['next_cron_utc']
    RESULT['ingestion_absent_post'] = after_idle['process_scan']
    RESULT['stage'] = 'post_availability'
    RESULT['availability_after'] = availability()
    RESULT['stage'] = 'preservation'
    RESULT['services_preserved'] = before['services'] == identities()
    require(RESULT['services_preserved'], 'service_identity_changed')
    RESULT['routing_certificates_preserved'] = before['configuration'] == baselines()
    require(RESULT['routing_certificates_preserved'], 'routing_certificate_changed')
    RESULT['forecasts_preserved'] = before['forecasts'] == hashes_forecasts()
    require(RESULT['forecasts_preserved'], 'forecast_changed_during_idle_install')


def failure(error):
    if RESULT['installed']:
        rollback = RESULT.get('action') == 'rollback'
        expected = {'src/models/next24h_production.py', 'src/models/next24h.py'} if rollback else set(INSTALL_ORDER)
        complete = set(RESULT['installed']) == expected
        state = ('ROLLBACK_VERIFICATION_FAILED' if complete else 'PARTIAL_ROLLBACK') if rollback else (
            'SOURCE_INSTALLED_VERIFICATION_FAILED' if complete else 'PARTIAL_SOURCE_INSTALL')
    elif RESULT['modifications_started']:
        state = 'PREPARATION_ARTIFACTS_ONLY'
    else:
        state = 'NOT_STARTED'
    RESULT.update(status='STOPPED', installation_state=state, error_type=type(error).__name__,
                  reason=str(error) if isinstance(error, RuntimeError) else 'unexpected_error_raw_details_withheld')
    return RESULT


def main(action):
    os.umask(0o077)
    RESULT['action'] = action
    before, payload = preflight(action)
    RESULT['availability_before'] = before['availability']
    RESULT['prefect_before'] = before['idle']
    if action == 'apply':
        RESULT['stage'] = 'backups'
        BACKUP.mkdir(mode=0o700)
        RESULT['modifications_started'] = True
        RESULT['created_paths'].append(str(BACKUP))
        for name, item in CONFIG['files'].items():
            if item['previous_sha256'] is not None:
                raw = read(ROOT/name)
                require(digest(raw) == item['previous_sha256'], 'source_changed_before_backup')
                private_write(BACKUP/Path(name).name, raw, 0o600)
        verify_backups()
        private_write(BACKUP/'deployment.json', json.dumps({'files': {name: {k: v for k, v in item.items() if k != 'base64'}
            for name, item in CONFIG['files'].items()}, 'services': before['services'],
            'configuration': before['configuration'], 'forecasts': before['forecasts']}, sort_keys=True).encode(), 0o600)
        sync_directory(BACKUP)
        RESULT['stage'] = 'receipt_directory'
        RECEIPTS.mkdir(mode=0o700)
        RESULT['created_paths'].append(str(RECEIPTS))
        verify_private_directory(RECEIPTS)
        sync_directory(RECEIPTS.parent)
        RESULT['stage'] = 'code_install'
        for name in INSTALL_ORDER:
            replace_code(name, payload[name])
    else:
        RESULT['stage'] = 'rollback'
        for name in ['src/models/next24h_production.py', 'src/models/next24h.py']:
            replace_code(name, payload[name])
            RESULT['modifications_started'] = True
        # Retain helper, receipts, backups and all partial artifacts; delete nothing.
    postflight(before, action)
    RESULT.update(stage='complete', installation_state='COMPLETE',
                  status='CAPTURE_CODE_INSTALLED' if action == 'apply' else 'CODE_ROLLED_BACK',
                  live_receipt_verification='pending_normal_scheduled_run')


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 2, 'one_action_required')
        main(sys.argv[1])
        print(json.dumps(RESULT))
    except Exception as error:
        print(json.dumps(failure(error)))
        raise SystemExit(1)
