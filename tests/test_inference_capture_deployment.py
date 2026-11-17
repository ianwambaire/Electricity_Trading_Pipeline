"""Local/mocked validation only. No test connects to SSH, HTTP or production."""
import ast
import base64
import copy
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import runpy
import stat
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT/'deploy/staging/inference-evidence-deployment'
NOW = dt.datetime(2026, 10, 31, 10, 0, tzinfo=dt.timezone.utc)


def module():
    data = runpy.run_path(str(PACKAGE/'deploy-capture.py'), run_name='local_test_only')
    return data['main'].__globals__


def deployment():
    return {'id': '47e5ef51-26d0-44b6-b119-2c40d0e77397', 'name': 'powerflow-entsoe-pipeline',
            'entrypoint': 'src/scheduled_pipeline.py:powerflow_entsoe_pipeline', 'paused': False,
            'schedules': [{'id': '9319f665-9836-4120-9801-031e23ad2b4a', 'active': True,
                          'schedule': {'cron': '45 * * * *', 'timezone': 'UTC', 'day_or': True}}],
            'global_concurrency_limit': {'limit': 1, 'active': True, 'active_slots': 0}, 'concurrency_options': None}


def idle_api(m, monkeypatch, dep=None, active=None, queued=None):
    def fake(path, body=None):
        if path.startswith('/deployments/'):
            return copy.deepcopy(dep if dep is not None else deployment())
        assert path == '/flow_runs/filter'
        kinds = body['flow_runs']['state']['type']['any_']
        return copy.deepcopy(queued or []) if kinds == ['SCHEDULED'] else copy.deepcopy(active or [])
    monkeypatch.setitem(m, 'api', fake)
    monkeypatch.setitem(m, 'ingestion_processes', lambda: {'complete': True, 'matches': []})


def capacity():
    return {'MemTotal': 2*1024**3, 'MemAvailable': 800*1024**2, 'SwapTotal': 4*1024**3,
            'SwapFree': 3*1024**3, 'swap_used_bytes': 1024**3, 'disk_available_bytes': 3*1024**3,
            'disk_total_bytes': 20*1024**3, 'disk_used_bytes': 17*1024**3}


def test_exact_three_payloads_and_support_hashes():
    config = module()['CONFIG']
    assert set(config['files']) == {'src/models/next24h.py', 'src/models/next24h_production.py', 'src/models/inference_evidence.py'}
    for path, item in config['files'].items():
        raw = base64.b64decode(item['base64'], validate=True)
        assert raw == (ROOT/path).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item['sha256']
        compile(raw, path, 'exec')
    for path, digest in config['dependencies'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == digest


def test_original_preflight_evidence_is_not_rewritten():
    report = json.loads((PACKAGE/'PREFLIGHT-RESULTS.json').read_text())
    assert report['read_only'] and report['stage'] == 'complete' and not report['errors']
    assert report['schedule_verified'] and not report['active_runs']
    assert all(v['matches'] for v in json.loads((PACKAGE/'BASELINE-COMPARISON.json').read_text()).values())


def test_service_gate_is_stable_and_includes_staging():
    m = module()
    tree = ast.parse((PACKAGE/'deploy-capture.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'identities')
    assert 'MemoryCurrent' not in ast.unparse(function)
    assert 'MainPID' in ast.unparse(function)
    assert 'powerflow-candidate-api.service' in m['UNITS']


def test_no_production_triggers_or_service_mutations():
    source = (PACKAGE/'deploy-capture.py').read_text()
    tree = ast.parse(source)
    # Inspect commands, not harmless report keys such as service_restart.
    literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    for forbidden in ['restart', 'reload', 'PATCH', 'git rev-parse', 'set_state']:
        assert forbidden not in literals
    assert 'model.predict(' not in source and 'run_next24h_forecast(' not in source
    assert 'schedule_window_under_ten_minutes' in source and 'source_changed_before_backup' in source


class Entry:
    def __init__(self, pid, raw=b'', uid=1000, error=None):
        self.name, self.raw, self.uid, self.error = str(pid), raw, uid, error
    def stat(self):
        return SimpleNamespace(st_uid=self.uid)
    def __truediv__(self, child):
        assert child == 'cmdline'
        return self
    def open(self, mode):
        if self.error:
            raise self.error
        return io.BytesIO(self.raw)


@pytest.mark.parametrize('command,role', [
    (b'python\0src/ingestion/fetch_entsoe_data.py\0--mode\0incremental', 'ingestion'),
    (b'python\0-m\0ingestion.fetch_entsoe_data', 'ingestion'),
    (b'python\0src/scheduled_pipeline.py', 'pipeline_engine'),
    (b'python\0-m\0prefect.engine', 'pipeline_engine'),
    (b'python\0-m\0prefect.flow_engine', 'pipeline_engine')])
def test_independent_process_scan_detects_other_uid_ingestion(monkeypatch, command, role):
    m = module()
    monkeypatch.setitem(m, 'process_visibility', lambda: {'hidepid_disabled': True})
    monkeypatch.setitem(m, 'PROC', SimpleNamespace(iterdir=lambda: [Entry(999001, command, uid=0)]))
    result = m['ingestion_processes']()
    assert result['matches'] == [{'pid': 999001, 'uid': 0, 'role': role}]
    with pytest.raises(RuntimeError, match='active_ingestion_or_pipeline_process'):
        m['no_ingestion']()


def test_process_scan_redacts_arguments_and_handles_exit_race(monkeypatch):
    m = module()
    monkeypatch.setitem(m, 'process_visibility', lambda: {'hidepid_disabled': True})
    entries = [Entry(999001, b'prefect worker start SECRET_VALUE'), Entry(999002, error=FileNotFoundError())]
    monkeypatch.setitem(m, 'PROC', SimpleNamespace(iterdir=lambda: entries))
    result = m['no_ingestion']()
    assert result['complete'] and not result['matches']
    assert 'SECRET_VALUE' not in repr(result)


def test_inaccessible_process_scan_fails_closed(monkeypatch):
    m = module()
    monkeypatch.setitem(m, 'process_visibility', lambda: {'hidepid_disabled': True})
    monkeypatch.setitem(m, 'PROC', SimpleNamespace(iterdir=lambda: [Entry(999001, error=PermissionError())]))
    with pytest.raises(RuntimeError, match='process_scan_permission_denied'):
        m['no_ingestion']()


@pytest.mark.parametrize('mutation,reason', [('cron', 'schedule_drift'), ('timezone', 'schedule_drift'),
    ('duplicate', 'schedule_drift'), ('concurrency', 'concurrency_or_collision_drift'),
    ('collision', 'concurrency_or_collision_drift'), ('slots', 'concurrency_not_idle')])
def test_prefect_configuration_drift_blocks(monkeypatch, mutation, reason):
    m = module(); dep = deployment()
    if mutation == 'cron': dep['schedules'][0]['schedule']['cron'] = '0 * * * *'
    if mutation == 'timezone': dep['schedules'][0]['schedule']['timezone'] = 'Europe/Berlin'
    if mutation == 'duplicate': dep['schedules'] *= 2
    if mutation == 'concurrency': dep['global_concurrency_limit']['limit'] = 2
    if mutation == 'collision': dep['concurrency_options'] = {'collision_strategy': 'CANCEL_NEW'}
    if mutation == 'slots': dep['global_concurrency_limit']['active_slots'] = 1
    idle_api(m, monkeypatch, dep=dep)
    with pytest.raises(RuntimeError, match=reason): m['idle'](NOW)


def test_prefect_active_queued_and_schedule_window_guards(monkeypatch):
    m = module(); idle_api(m, monkeypatch, active=[{'id': 'active'}])
    with pytest.raises(RuntimeError, match='active_prefect_run'): m['idle'](NOW)
    idle_api(m, monkeypatch, queued=[{'id': 'queued', 'deployment_id': m['DEP'], 'expected_start_time': '2026-10-31T10:05:00Z'}])
    with pytest.raises(RuntimeError, match='imminent_queued_run'): m['idle'](NOW)
    idle_api(m, monkeypatch)
    with pytest.raises(RuntimeError, match='schedule_window_under_ten_minutes'): m['idle'](NOW.replace(minute=40))
    result = m['idle'](NOW)
    assert result['next_cron_utc'] == '2026-10-31T10:45:00+00:00'


def test_resource_measurement_includes_swap_and_disk(monkeypatch, tmp_path):
    m = module(); mem = tmp_path/'meminfo'
    mem.write_text('MemTotal: 2097152 kB\nMemAvailable: 819200 kB\nSwapTotal: 4194304 kB\nSwapFree: 3145728 kB\n')
    monkeypatch.setitem(m, 'PROC', tmp_path)
    monkeypatch.setattr(m['os'], 'statvfs', lambda _: SimpleNamespace(f_blocks=20, f_bavail=3, f_bfree=4, f_frsize=1024**3))
    result = m['resources']()
    assert result['swap_used_bytes'] == 1024**3 and result['disk_used_bytes'] == 16*1024**3
    m['require_capacity'](result)
    mem.write_text('MemTotal: 2097152 kB\nMemAvailable: 819200 kB\nSwapTotal: 2 kB\nSwapFree: 3 kB\n')
    with pytest.raises(RuntimeError, match='memory_counters_invalid'): m['resources']()


@pytest.mark.parametrize('field,value,reason', [('MemAvailable', 768*1024**2-1, 'available_ram_below'),
    ('disk_available_bytes', 2*1024**3-1, 'disk_below')])
def test_reviewed_capacity_guards_reject(monkeypatch, field, value, reason):
    m = module(); result = capacity(); result[field] = value
    with pytest.raises(RuntimeError, match=reason): m['require_capacity'](result)
    result = capacity(); result['MemAvailable'] = 768*1024**2; result['disk_available_bytes'] = 2*1024**3
    m['require_capacity'](result)


class PrivatePath:
    def __init__(self, *, mode=0o700, uid=1000, gid=1000, symlink=False, regular=False):
        self.info = SimpleNamespace(st_mode=(stat.S_IFREG if regular else stat.S_IFDIR)|mode, st_uid=uid, st_gid=gid)
        self.link = symlink
    def lstat(self): return self.info
    def is_symlink(self): return self.link


@pytest.mark.parametrize('kwargs', [{'mode': 0o755}, {'mode': 0o770}, {'uid': 0}, {'gid': 0}, {'symlink': True}, {'regular': True}])
def test_private_receipt_directory_permissions_fail_closed(kwargs):
    m = module()
    with pytest.raises(RuntimeError, match='private_directory_permissions'):
        m['verify_private_directory'](PrivatePath(**kwargs))
    assert m['verify_private_directory'](PrivatePath()) == {'uid': 1000, 'gid': 1000, 'mode': '0700', 'symlink': False}


def availability_mock(m, monkeypatch, broken=None):
    def get(port, path, tls=False):
        if broken == (port, path):
            raise RuntimeError('availability_http_status')
        if port == 8000 or path in ['/health', '/api/health']: return b'{"status":"ok"}'
        if path == '/ready': return b'{"status":"ready"}'
        if port == 8501: return b'ok'
        assert tls
        if path == '/': return b'<div id="root"></div><script src="/assets/index-test.js"></script>'
        return b'export const loaded = true;'
    monkeypatch.setitem(m, 'http_get', get)


@pytest.mark.parametrize('broken', [(8000, '/health'), (8010, '/health'), (8010, '/ready'),
    (8501, '/_stcore/health'), (443, '/'), (443, '/assets/index-test.js'), (443, '/api/health')])
def test_unavailable_production_or_staging_blocks(monkeypatch, broken):
    m = module(); availability_mock(m, monkeypatch, broken)
    with pytest.raises(RuntimeError, match='availability_http_status'): m['availability']()


def test_availability_verifies_react_entry_and_api_payloads(monkeypatch):
    m = module(); availability_mock(m, monkeypatch)
    assert m['availability']() == {'production_api': 200, 'candidate_api': 200, 'candidate_readiness': 200,
        'streamlit': 200, 'staging_https': 200, 'react_entry_asset': 200, 'staging_api_proxy': 200, 'tls_hostname_chain_verified': True}
    monkeypatch.setitem(m, 'http_get', lambda *args, **kwargs: b'{"status":"not_ready"}')
    with pytest.raises(RuntimeError, match='availability_payload'): m['availability']()


def test_tls_has_no_verification_bypass():
    source = (PACKAGE/'deploy-template.py').read_text()
    assert 'ssl.create_default_context()' in source and 'server_hostname=self.host' in source
    assert 'CERT_NONE' not in source and 'check_hostname=False' not in source


def test_services_require_all_active_units_and_match_stable_fields(monkeypatch):
    m = module()
    def response(inactive=False):
        return '\n\n'.join('Id='+name+'\nMainPID=123\nActiveState=active\nSubState='+('dead' if inactive else 'running')
                            for name in m['UNITS']).encode()
    monkeypatch.setattr(m['subprocess'], 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=response()))
    assert set(m['identities']()) == set(m['UNITS'])
    monkeypatch.setattr(m['subprocess'], 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=response(True)))
    with pytest.raises(RuntimeError, match='service_not_operational'): m['identities']()


class VirtualPath:
    def __init__(self, name, writes): self.name, self.writes = name, writes
    def __truediv__(self, child): return VirtualPath(self.name+'/'+str(child), self.writes)
    def __fspath__(self): return self.name
    def resolve(self, strict=True): return self
    def lstat(self):
        return SimpleNamespace(st_uid=1000, st_gid=1000, st_mode=(stat.S_IFREG|0o644) if self.name.endswith('.py') else (stat.S_IFDIR|0o755))
    def is_symlink(self): return False
    def mkdir(self, **kwargs): self.writes.append(self.name); raise AssertionError('unexpected write')


def virtual_preflight(m, monkeypatch):
    writes = []; root = VirtualPath('/__powerflow_mock_nonexistent__', writes)
    monkeypatch.setitem(m, 'ROOT', root)
    monkeypatch.setitem(m, 'BACKUP', VirtualPath('/__powerflow_mock_backup__', writes))
    monkeypatch.setitem(m, 'RECEIPTS', VirtualPath('/__powerflow_mock_receipts__', writes))
    monkeypatch.setattr(m['os'], 'geteuid', lambda: 1000)
    monkeypatch.setattr(m['os'], 'getegid', lambda: 1000)
    monkeypatch.setitem(m, 'sys', SimpleNamespace(version_info=(3,14,7)))
    config = copy.deepcopy(m['CONFIG']); monkeypatch.setitem(m, 'CONFIG', config)
    monkeypatch.setitem(m, 'importlib', SimpleNamespace(metadata=SimpleNamespace(version=lambda name: config['packages'][name])))
    def read(path):
        path = str(path.__fspath__())
        if path.endswith('/.git/HEAD'): return b'ref: refs/heads/main'
        if path.endswith('/.git/refs/heads/main'): return config['revision'].encode()
        name = path.removeprefix('/__powerflow_mock_nonexistent__/')
        return ('old:'+name).encode()
    for name in config['dependencies']: config['dependencies'][name] = hashlib.sha256(('old:'+name).encode()).hexdigest()
    for name,item in config['files'].items():
        if item['previous_sha256'] is not None: item['previous_sha256'] = hashlib.sha256(('old:'+name).encode()).hexdigest()
    monkeypatch.setitem(m, 'read', read)
    idle_api(m, monkeypatch)
    original_idle = m['idle']; monkeypatch.setitem(m, 'idle', lambda: original_idle(NOW))
    monkeypatch.setitem(m, 'identities', lambda: {'stable': 'services'})
    monkeypatch.setitem(m, 'baselines', lambda: {'stable': 'routing'})
    monkeypatch.setitem(m, 'hashes_forecasts', lambda: {'stable': 'forecasts'})
    monkeypatch.setitem(m, 'availability', lambda: {'all': 200})
    monkeypatch.setitem(m, 'resources', capacity)
    return writes


@pytest.mark.parametrize('guard', ['ingestion', 'prefect', 'ram', 'disk', 'availability', 'identity', 'source'])
def test_failed_preflight_performs_no_remote_filesystem_write(monkeypatch, guard):
    m = module(); writes = virtual_preflight(m, monkeypatch)
    if guard == 'ingestion': monkeypatch.setitem(m, 'ingestion_processes', lambda: {'matches': [{'pid': 999001, 'role': 'ingestion'}]})
    if guard == 'prefect':
        original = m['api']
        def active(path, body=None):
            if body and body.get('flow_runs', {}).get('state', {}).get('type', {}).get('any_', []) != ['SCHEDULED']: return [{'id': 'running'}]
            return original(path, body)
        monkeypatch.setitem(m, 'api', active)
    if guard in ['ram', 'disk']:
        value = capacity(); value['MemAvailable' if guard == 'ram' else 'disk_available_bytes'] = 0
        monkeypatch.setitem(m, 'resources', lambda: value)
    if guard == 'availability': monkeypatch.setitem(m, 'availability', lambda: (_ for _ in ()).throw(RuntimeError('availability_http_status')))
    if guard == 'identity': monkeypatch.setattr(m['os'], 'geteuid', lambda: 0)
    if guard == 'source': m['CONFIG']['dependencies']['src/scheduled_pipeline.py'] = '0'*64
    with pytest.raises(RuntimeError): m['main']('apply')
    assert writes == [] and m['RESULT']['installed'] == [] and not m['RESULT']['modifications_started']


def test_successful_preflight_is_read_only(monkeypatch):
    m = module(); writes = virtual_preflight(m, monkeypatch)
    before, payload = m['preflight']('apply')
    assert set(payload) == set(m['CONFIG']['files']) and before['idle']['configuration']['concurrency_limit'] == 1
    assert not writes and not m['RESULT']['modifications_started']


def test_exclusive_writes_never_follow_symlinks(tmp_path):
    m = module(); path = tmp_path/'private'; m['private_write'](path,b'one',0o600)
    with pytest.raises(FileExistsError): m['private_write'](path,b'two',0o600)
    link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(FileExistsError):m['private_write'](link,b'two',0o600)
    assert path.read_bytes()==b'one'


@pytest.mark.parametrize('installed,started,state', [([],False,'NOT_STARTED'),([],True,'PREPARATION_ARTIFACTS_ONLY'),
    (['src/models/inference_evidence.py'],True,'PARTIAL_SOURCE_INSTALL'),
    (['src/models/inference_evidence.py','src/models/next24h.py','src/models/next24h_production.py'],True,'SOURCE_INSTALLED_VERIFICATION_FAILED')])
def test_partial_installation_detection(installed,started,state):
    m=module();m['RESULT'].update(installed=installed,modifications_started=started)
    result=m['failure'](RuntimeError('injected'))
    assert result['installation_state']==state and result['automatic_rollback'] is False


def post_mocks(m, monkeypatch):
    idle_api(m,monkeypatch);original_idle=m['idle'];monkeypatch.setitem(m,'idle',lambda:original_idle(NOW))
    expected={name:item['sha256'] for name,item in m['CONFIG']['files'].items()}
    monkeypatch.setitem(m,'resources',capacity)
    monkeypatch.setitem(m,'verify_private_directory',lambda path:{'uid':1000,'gid':1000,'mode':'0700'})
    monkeypatch.setitem(m,'verify_backups',lambda:{'files':'verified'})
    monkeypatch.setitem(m,'read',lambda path: str(path).encode())
    monkeypatch.setitem(m,'digest',lambda raw:expected[raw.decode().removeprefix(str(m['ROOT'])+'/')])
    monkeypatch.setitem(m,'availability',lambda:{'all':200})
    monkeypatch.setitem(m,'identities',lambda:{'services':'stable'})
    monkeypatch.setitem(m,'baselines',lambda:{'routing':'stable'})
    monkeypatch.setitem(m,'hashes_forecasts',lambda:{'forecasts':'stable'})
    return {'idle':{'configuration':m['deployment_configuration']()},'services':{'services':'stable'},
            'configuration':{'routing':'stable'},'forecasts':{'forecasts':'stable'}}


def test_postflight_reports_resources_and_all_preservation(monkeypatch):
    m=module();before=post_mocks(m,monkeypatch);m['postflight'](before,'apply')
    result=m['RESULT'];assert result['resources_after']['swap_used_bytes']==1024**3
    assert result['receipt_directory']['mode']=='0700' and result['backup_verification']
    assert result['prefect_configuration_preserved'] and result['services_preserved'] and result['routing_certificates_preserved'] and result['forecasts_preserved']


@pytest.mark.parametrize('guard', ['directory','backup','source','prefect','availability','services','routing','forecasts','capacity'])
def test_postflight_failed_checks_report_installed_state_without_rollback(monkeypatch,guard):
    m=module();before=post_mocks(m,monkeypatch);m['RESULT'].update(installed=list(m['INSTALL_ORDER']),modifications_started=True)
    if guard in ['directory','backup','availability']:
        name={'directory':'verify_private_directory','backup':'verify_backups','availability':'availability'}[guard]
        monkeypatch.setitem(m,name,lambda *a:(_ for _ in ()).throw(RuntimeError('injected_'+guard)))
    if guard=='source':monkeypatch.setitem(m,'digest',lambda _: '0'*64)
    if guard=='prefect':before['idle']['configuration']['collision_policy']='changed'
    if guard=='services':monkeypatch.setitem(m,'identities',lambda:{'services':'changed'})
    if guard=='routing':monkeypatch.setitem(m,'baselines',lambda:{'routing':'changed'})
    if guard=='forecasts':monkeypatch.setitem(m,'hashes_forecasts',lambda:{'forecasts':'changed'})
    if guard=='capacity':
        value=capacity();value['MemAvailable']=0;monkeypatch.setitem(m,'resources',lambda:value)
    with pytest.raises(RuntimeError) as error:m['postflight'](before,'apply')
    assert m['failure'](error.value)['installation_state']=='SOURCE_INSTALLED_VERIFICATION_FAILED'
    assert 'resources_after' in m['RESULT'] and not m['RESULT']['automatic_rollback']


def test_runner_does_not_claim_no_changes_without_remote_report():
    runner=runpy.run_path(str(PACKAGE/'run-deployment.py'),run_name='local_test_only')
    for code,raw in [(255,b''),(124,b''),(1,b'not JSON')]:
        result=runner['summarize'](code,raw)
        assert result['remote_installation_state']=='UNKNOWN' and result['exit']==code
    data={'stage':'code_install','installation_state':'PARTIAL_SOURCE_INSTALL'}
    assert runner['summarize'](1,json.dumps(data).encode())==data


def test_runner_retains_hash_binding_and_existing_timeouts():
    raw=(PACKAGE/'deploy-capture.py').read_bytes();runner=(PACKAGE/'run-deployment.py').read_text()
    # Generator refreshes the payload binding before final package verification.
    assert '90s' in runner and 'kill-after=5s' in runner and 'StrictHostKeyChecking=yes' in runner
    assert 'timeout=190' in runner and 'verify_package()' in runner
    ast.parse(runner);compile(raw,'payload','exec')


@pytest.mark.parametrize('option,valid', [('rw',True),('rw,hidepid=0',True),('rw,hidepid=1',False),('rw,hidepid=2',False)])
def test_hidden_process_mount_fails_closed(monkeypatch,tmp_path,option,valid):
    m=module();(tmp_path/'self').mkdir();(tmp_path/'self/mountinfo').write_text('1 0 0:1 / /proc '+option+' - proc proc rw\n')
    monkeypatch.setitem(m,'PROC',tmp_path)
    if valid:assert m['process_visibility']()['hidepid_disabled']
    else:
        with pytest.raises(RuntimeError,match='process_visibility_restricted'):m['process_visibility']()


@pytest.mark.parametrize('failure', [None,'first_replace','second_replace','postflight'])
def test_real_local_apply_and_partial_installation_preserve_original_backups(monkeypatch,tmp_path,failure):
    m=module();root=tmp_path/'application';models=root/'src/models';models.mkdir(parents=True)
    reports=root/'data/reports';reports.mkdir(parents=True)
    backup=tmp_path/'backup';receipts=reports/'next24h_inference'
    config=copy.deepcopy(m['CONFIG']);payload={}
    for name,item in config['files'].items():
        payload[name]=base64.b64decode(item['base64'])
        if item['previous_sha256'] is not None:
            raw=('original '+name).encode();(root/name).write_bytes(raw)
            item['previous_sha256']=hashlib.sha256(raw).hexdigest()
    historical=reports/'historical';historical.write_bytes(b'untouched')
    for name,value in [('ROOT',root),('BACKUP',backup),('RECEIPTS',receipts),('CONFIG',config)]:monkeypatch.setitem(m,name,value)
    monkeypatch.setitem(m,'read',lambda p:Path(p).read_bytes())
    monkeypatch.setitem(m,'idle',lambda:{})
    monkeypatch.setitem(m,'preflight',lambda action:({'availability':{'all':200},'idle':{},'services':{},'configuration':{},'forecasts':{}},payload))
    def private_directory(path):
        assert not path.is_symlink() and path.stat().st_mode&0o777==0o700
        return {'mode':'0700'}
    monkeypatch.setitem(m,'verify_private_directory',private_directory)
    def backups():
        private_directory(backup)
        for name,item in config['files'].items():
            if item['previous_sha256'] is not None:
                path=backup/Path(name).name
                assert path.stat().st_mode&0o777==0o600
                assert hashlib.sha256(path.read_bytes()).hexdigest()==item['previous_sha256']
        return {'files':'PASS'}
    monkeypatch.setitem(m,'verify_backups',backups)
    def postflight(*args):
        if failure=='postflight':raise RuntimeError('availability_http_status')
        for name,raw in payload.items():assert (root/name).read_bytes()==raw
    monkeypatch.setitem(m,'postflight',postflight)
    original=m['os'].replace;calls=[]
    def replace(source,destination):
        calls.append(str(destination))
        if (failure=='first_replace' and len(calls)==1) or (failure=='second_replace' and len(calls)==2):
            raise OSError('injected local filesystem error')
        return original(source,destination)
    monkeypatch.setattr(m['os'],'replace',replace)
    try:
        if failure:
            with pytest.raises((RuntimeError,OSError)) as error:m['main']('apply')
            result=m['failure'](error.value)
            expected={'first_replace':'PREPARATION_ARTIFACTS_ONLY','second_replace':'PARTIAL_SOURCE_INSTALL',
                      'postflight':'SOURCE_INSTALLED_VERIFICATION_FAILED'}[failure]
            assert result['installation_state']==expected
            assert not result['automatic_rollback']
            if failure in ['first_replace','second_replace']:assert result['temporary_paths']
        else:
            m['main']('apply');assert m['RESULT']['installation_state']=='COMPLETE'
    finally:
        assert historical.read_bytes()==b'untouched'
        backups();private_directory(receipts)


@pytest.mark.parametrize('failure', ['mode','owner','group','hash'])
def test_backup_permissions_and_hash_readback_are_enforced(monkeypatch,failure):
    m=module();raw=b'old'
    m['CONFIG']['files']={'src/models/next24h.py':{'previous_sha256':hashlib.sha256(raw).hexdigest()}}
    class BackupPath(PrivatePath):
        def __truediv__(self,name):
            assert name=='next24h.py'
            return PrivatePath(regular=True,mode=0o644 if failure=='mode' else 0o600,
                               uid=0 if failure=='owner' else 1000,gid=0 if failure=='group' else 1000)
    monkeypatch.setitem(m,'BACKUP',BackupPath())
    monkeypatch.setitem(m,'read',lambda _: b'corrupt' if failure=='hash' else raw)
    with pytest.raises(RuntimeError,match='backup_permissions|backup_readback'):m['verify_backups']()


def test_runner_local_integrity_failure_never_invokes_ssh_or_creates_capture(monkeypatch,capsys):
    data=runpy.run_path(str(PACKAGE/'run-deployment.py'),run_name='local_test_only');m=data['main'].__globals__
    monkeypatch.setitem(m,'sys',SimpleNamespace(argv=['runner','apply']))
    monkeypatch.setitem(m,'verify_package',lambda:(_ for _ in ()).throw(RuntimeError('hash')))
    def forbidden(*args,**kwargs):raise AssertionError('No subprocess/capture allowed on failed local integrity')
    monkeypatch.setattr(m['subprocess'],'run',forbidden);monkeypatch.setattr(m['tempfile'],'mkdtemp',forbidden)
    assert m['main']()==1
    assert json.loads(capsys.readouterr().out)['remote_installation_state']=='NOT_STARTED'


def test_tls_certificate_failure_propagates_and_closes_socket(monkeypatch):
    m=module();closed=[]
    raw=SimpleNamespace(close=lambda:closed.append(True))
    monkeypatch.setattr(m['socket'],'create_connection',lambda *a,**k:raw)
    def wrap(sock,server_hostname):
        assert sock is raw and server_hostname=='staging.powerflowenergy.dev'
        raise m['ssl'].SSLCertVerificationError('untrusted certificate')
    connection=m['LoopbackHTTPS'].__new__(m['LoopbackHTTPS'])
    connection.host='staging.powerflowenergy.dev';connection.timeout=2
    connection._context=SimpleNamespace(wrap_socket=wrap)
    with pytest.raises(m['ssl'].SSLCertVerificationError):connection.connect()
    assert closed==[True]


def test_current_packet_full_integrity():
    runner=runpy.run_path(str(PACKAGE/'run-deployment.py'),run_name='local_test_only')
    runner['verify_package']()


@pytest.mark.parametrize('kind',['artifact','source','inventory'])
def test_local_packet_drift_is_rejected_before_execution(monkeypatch,tmp_path,kind):
    runner=runpy.run_path(str(PACKAGE/'run-deployment.py'),run_name='local_test_only');m=runner['main'].__globals__
    manifest=json.loads((PACKAGE/'MANIFEST.json').read_bytes())
    for name in manifest['files']:(tmp_path/name).write_bytes((PACKAGE/name).read_bytes())
    if kind=='artifact':(tmp_path/'deploy-template.py').write_text('modified')
    if kind=='source':manifest['sources']['src/models/next24h.py']['new_sha256']='0'*64
    if kind=='inventory':manifest['files'].pop('preflight.py')
    (tmp_path/'MANIFEST.json').write_text(json.dumps(manifest))
    monkeypatch.setitem(m,'PACKAGE',tmp_path);monkeypatch.setitem(m,'P',tmp_path/'deploy-capture.py')
    with pytest.raises(RuntimeError):m['verify_package']()
