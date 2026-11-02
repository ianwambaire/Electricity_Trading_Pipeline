"""Synthetic filesystem and mock services only. No SSH or actual service action."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import ast
import errno
import pytest

ROOT=Path(__file__).resolve().parents[1];DIR=ROOT/'deploy/staging/forecast-consistency-deployment'
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
D=load('deploy_job',DIR/'deploy.py');R=load('deploy_runner',DIR/'run.py')
VALIDATE_ROLLBACK=D.validate_rollback


def inputs():
    # Full key counts from a non-private source manifest are unnecessary; isolated
    # fixtures cover each path class and the explicit selector gate.
    result={}
    for prefix,count in [('api/',26),('static/',37)]:
        for n in range(count):
            name=prefix+('src/api/forecast_source.py' if prefix=='api/' and n==0 else 'index.html' if prefix=='static/' and n==0 else 'assets/new-123.js' if prefix=='static/' and n==1 else 'asset'+str(n))
            raw=b'<div id="root"></div><script src="/assets/new-123.js"></script>' if name=='static/index.html' else b'synthetic'
            result[name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'base64':base64.b64encode(raw).decode()}
    return {'files':result}


@pytest.fixture
def host(tmp_path,monkeypatch):
    api_parent=tmp_path/'api';static_parent=tmp_path/'static';control_parent=tmp_path/'private'
    for p in (api_parent,static_parent,control_parent):p.mkdir()
    old_api=api_parent/'old';old_static=static_parent/'old';old_api.mkdir();old_static.mkdir()
    (old_api/'src').mkdir();(old_api/'src/old.py').write_bytes(b'old-code')
    (old_static/'index.html').write_bytes(b'old-html');(old_static/'assets').mkdir();(old_static/'assets/old-123.js').write_bytes(b'old-asset')
    (old_api/'.venv-api').mkdir();env=tmp_path/'api.env';raw=b'PUBLIC=unchanged\n';env.write_bytes(raw);env.chmod(0o600)
    backend=tmp_path/'current-api';static=tmp_path/'current-static';backend.symlink_to(old_api);static.symlink_to(old_static)
    for key,value in {'API':api_parent/D.ID,'STATIC':static_parent/D.ID,'CONTROL':control_parent/'control','BACKEND_LINK':backend,'STATIC_LINK':static,'ENV':env,'OVERLAY':tmp_path/'ABSENT','ENV_BASELINE':D.sha(raw),'BACKEND_TARGET_SHA':D.sha(str(old_api).encode()),'STATIC_TARGET_SHA':D.sha(str(old_static).encode()),'CONFIG':inputs(),'CHANGED':False,'PHASE':'PREFLIGHT'}.items():monkeypatch.setattr(D,key,value,raising=False)
    calls=[];monkeypatch.setattr(D,'safe',lambda p:None);monkeypatch.setattr(D.os,'geteuid',lambda:0)
    monkeypatch.setattr(D.os,'fchown',lambda *a:None);monkeypatch.setattr(D.os,'chown',lambda *a:None)
    original=Path.lstat
    def rootstat(path,*a,**kw):
        st=original(path,*a,**kw);parts=list(st);parts[4]=parts[5]=0;return os.stat_result(parts)
    monkeypatch.setattr(Path,'lstat',rootstat)
    monkeypatch.setattr(D,'read',lambda p,limit=0:Path(p).read_bytes())
    monkeypatch.setattr(D,'production',lambda:'a'*64);monkeypatch.setattr(D,'idle_capacity',lambda extra:{'available_bytes':900*1024**2,'swap_used_bytes':0})
    monkeypatch.setattr(D,'runtime',lambda target:calls.append(('runtime',target)))
    monkeypatch.setattr(D,'run',lambda command:calls.append(('service',command)))
    monkeypatch.setattr(D,'candidate_ready',lambda:calls.append(('ready',None)))
    monkeypatch.setattr(D,'missing_acceptance',lambda:calls.append(('missing',None)))
    monkeypatch.setattr(D,'validate_rollback',lambda record:None)
    monkeypatch.setattr(D,'BASE',{'INSTALLED_HASHES':{'src/old.py':D.sha(b'old-code')},'passive_installation':lambda:({},True),'canonical':lambda p,parent:p.resolve(strict=True)},raising=False)
    monkeypatch.setattr(D,'probe',lambda port,path,status: (static.resolve()/('index.html' if path=='/' else path.lstrip('/'))).read_bytes() if path=='/' or path.startswith('/assets/') else b'{}')
    return SimpleNamespace(old_api=old_api,old_static=old_static,env=raw,calls=calls)


def test_apply_and_independent_rollback_preserve_originals(host):
    before=(host.old_static/'assets/old-123.js').read_bytes()
    result=D.apply();assert result['status']=='DEPLOYED'
    assert D.BACKEND_LINK.resolve()==D.API and D.STATIC_LINK.resolve()==D.STATIC
    assert D.ENV.read_bytes()==host.env+D.KEY+b'=/srv/powerflow/forecast-publications\n'
    assert (D.CONTROL/'previous-api.env').read_bytes()==host.env
    assert (D.STATIC/'assets/old-123.js').read_bytes()==before
    assert not D.OVERLAY.exists()
    result=D.rollback();assert result['status']=='ROLLED_BACK'
    assert D.BACKEND_LINK.resolve()==host.old_api and D.STATIC_LINK.resolve()==host.old_static
    assert D.ENV.read_bytes()==host.env and (host.old_static/'assets/old-123.js').read_bytes()==before
    assert all(command==['/usr/bin/systemctl','restart',D.UNIT] for label,command in host.calls if label=='service')


@pytest.mark.parametrize('failure',['capacity','env','source','destination','input'])
def test_preflight_failures_write_nothing(host,monkeypatch,failure):
    if failure=='capacity':monkeypatch.setattr(D,'idle_capacity',lambda extra:(_ for _ in ()).throw(D.Stop('RAM_GATE')))
    if failure=='env':D.ENV.write_bytes(b'drift')
    if failure=='source':(host.old_api/'src/old.py').write_bytes(b'drift')
    if failure=='destination':D.API.mkdir()
    if failure=='input':next(iter(D.CONFIG['files'].values()))['sha256']='0'*64
    with pytest.raises(D.Stop):D.apply()
    assert not D.CHANGED and not D.CONTROL.exists() and not D.STATIC.exists()
    assert D.BACKEND_LINK.resolve()==host.old_api and D.STATIC_LINK.resolve()==host.old_static


def test_failure_after_backend_switch_never_activates_static_or_rolls_back(host,monkeypatch):
    monkeypatch.setattr(D,'missing_acceptance',lambda:(_ for _ in ()).throw(D.Stop('CACHE_MISMATCH')))
    with pytest.raises(D.Stop):D.apply()
    assert D.CHANGED and D.BACKEND_LINK.resolve()==D.API and D.STATIC_LINK.resolve()==host.old_static
    assert D.ENV.read_bytes()!=host.env and (D.CONTROL/'previous-api.env').read_bytes()==host.env


def test_rollback_rejects_environment_drift(host):
    D.apply();D.ENV.write_bytes(b'unexpected-change')
    with pytest.raises(D.Stop,match='ROLLBACK_ENV_DRIFT'):D.rollback()
    assert D.BACKEND_LINK.resolve()==D.API


def test_missing_acceptance_requires_exact_status_code_and_no_store(monkeypatch):
    monkeypatch.setattr(D,'OVERLAY',Path('/synthetic-definitely-absent'))
    def api(path):
        if path=='/forecast/next24':return 503,{'Cache-Control':'no-store'},b'{"detail":{"code":"FORECAST_WITHHELD"}}'
        if path=='/operations/summary':return 200,{},b'{"forecast_status":"MISSING_PUBLICATION","health":"Historical snapshot","completeness_note":"Historical operational snapshot only"}'
        if path=='/forecast/one-hour?limit=24&offset=0':return 200,{},b'{"row_count":1,"total_rows":1,"limit":24,"offset":0,"has_more":false,"forecasts":[{}]}'
        return (401 if path.startswith('/admin/') else 200),{},b'{}'
    monkeypatch.setattr(D,'request_api',api);D.missing_acceptance()
    monkeypatch.setattr(D,'request_api',lambda p:(500,{},b'{}'))
    with pytest.raises(D.Stop):D.missing_acceptance()


def test_no_proposals_or_data_installed():
    tree=ast.parse((DIR/'deploy.py').read_text(),feature_version=(3,9))
    source=(DIR/'deploy.py').read_text();assert "install_tree(API,'api/')" in source and "install_tree(STATIC,'static/')" in source
    assert 'pip install' not in source and 'nginx -t' not in source and 'os.unlink' not in source
    assert "OVERLAY.mkdir" not in source and "'restart',UNIT" in source
    assert tree is not None


def test_manifest_dependency_and_retained_release_hashes():
    manifest=json.loads((DIR/'MANIFEST.json').read_bytes())
    assert set(manifest['artifacts'])==R.ARTIFACTS
    for name,item in manifest['artifacts'].items():
        raw=(ROOT/name).read_bytes();assert len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256']


def test_bad_manifest_stops_before_private_binding(monkeypatch):
    monkeypatch.setattr(R,'namespace',lambda *a:pytest.fail('Unverified code must not load'))
    with pytest.raises(ValueError):R.verify('0'*64,'apply')


@pytest.mark.parametrize('failure',[None,'unit_memory','effective_memory','swap','bpf','listener','uid'])
def test_runtime_security_gates_require_actual_effective_evidence(monkeypatch,failure):
    c={'ActiveState':'active','SubState':'running','User':'powerflow-api','Group':'powerflow-api','MemoryHigh':str(384*1024**2),'MemoryMax':str(512*1024**2),'MemorySwapMax':'0','ProtectSystem':'strict','ProtectHome':'yes','NoNewPrivileges':'yes','PrivateTmp':'yes','PrivateDevices':'yes','ProtectKernelTunables':'yes','ProtectKernelModules':'yes','ProtectControlGroups':'yes','RestrictSUIDSGID':'yes','CapabilityBoundingSet':'','AmbientCapabilities':'','TasksMax':'64','RestrictAddressFamilies':'AF_UNIX AF_INET AF_INET6','IPAddressDeny':'169.254.169.254 fd00:ec2::254','MainPID':'42','ControlGroup':'/system.slice/'+D.UNIT}
    if failure=='unit_memory':c['MemoryMax']='1024'
    status=b'Uid:\t992\t992\t992\t992\nGid:\t992\t992\t992\t992\nNoNewPrivs:\t1\nSeccomp:\t2\nCapEff:\t0000000000000000\n'
    if failure=='uid':status=status.replace(b'Uid:\t992',b'Uid:\t0')
    def read(path,limit=0):
        path=str(path)
        if path=='/proc/42/status':return status
        if path=='/proc/42/cmdline':return b'uvicorn\0--workers\x001\0'
        if path=='/proc/net/tcp':return b'header\n0: '+(b'00000000' if failure=='listener' else b'0100007F')+b':1F4A 00000000:0000 0A 0 0 0 0 0 123\n'
        if path=='/proc/net/tcp6':return b'header\n'
        values={'memory.high':384*1024**2,'memory.max':1024 if failure=='effective_memory' else 512*1024**2,'memory.swap.max':0,'memory.swap.current':1 if failure=='swap' else 0}
        return str(values[Path(path).name]).encode()
    expected=Path('/synthetic-backend');original_resolve=Path.resolve;original_iter=Path.iterdir
    monkeypatch.setattr(Path,'resolve',lambda self,*a,**k:expected if str(self)=='/proc/42/cwd' else original_resolve(self,*a,**k))
    monkeypatch.setattr(Path,'iterdir',lambda self:iter([Path('/synthetic-fd')]) if str(self)=='/proc/42/fd' else original_iter(self))
    monkeypatch.setattr(D.os,'readlink',lambda path:'socket:[123]')
    monkeypatch.setattr(D,'read',read)
    monkeypatch.setattr(D,'BASE',{'services':lambda:{D.UNIT:c},'bpf':lambda value:({},failure!='bpf')},raising=False)
    if failure:
        with pytest.raises(D.Stop):D.runtime(expected)
    else:D.runtime(expected)


def test_restart_command_allowlist_cannot_target_production(monkeypatch):
    monkeypatch.setattr(D,'BASE',{'bounded_run':lambda *a,**k:pytest.fail('No command allowed')},raising=False)
    for command in [['/usr/bin/systemctl','restart','powerflow-api.service'],['/usr/bin/systemctl','stop',D.UNIT],['/bin/sh','-c','anything']]:
        with pytest.raises(D.Stop,match='COMMAND_SCOPE'):D.run(command)


def test_rollback_validator_uses_existing_strict_schema():
    helper=load('rollback_schema',ROOT/'deploy/staging/forecast-consistency-release/rollback_state.py')
    record={'schema_version':1,'previous_backend':'/opt/powerflow/releases/old-api','previous_static':'/var/www/powerflow-staging/releases/old-static','installed_backend':str(D.API),'installed_static':str(D.STATIC),'original_env_sha256':'0'*64,'installed_env_sha256':'1'*64,'environment_backup':'/var/lib/powerflow-staging/forecast-consistency-20261101-v1/previous-api.env','environment_uid':0,'environment_gid':0,'environment_mode':'0600'}
    assert helper.validate(record)==record
    with pytest.raises(ValueError):helper.validate(dict(record,previous_backend='/home/unsafe'))


def success_report(action):
    value={'status':'DEPLOYED' if action=='apply' else 'ROLLED_BACK','phase':'COMPLETE' if action=='apply' else 'ROLLED_BACK','production_preserved':True}
    if action=='apply':value.update(missing_publication_verified=True,resources_before={'available_bytes':800*1024**2,'swap_used_bytes':0})
    return value


@pytest.mark.parametrize('action',['apply','rollback'])
def test_report_requires_action_specific_complete_success(action):
    valid=success_report(action);assert R.validate_report(valid,action,0)==valid
    for key in valid:
        broken=dict(valid);del broken[key]
        with pytest.raises(ValueError):R.validate_report(broken,action,0)
    with pytest.raises(ValueError):R.validate_report(success_report('rollback' if action=='apply' else 'apply'),action,0)
    with pytest.raises(ValueError):R.validate_report(valid,action,1)
    with pytest.raises(ValueError):R.validate_report(dict(valid,production_preserved=False),action,0)
    with pytest.raises(ValueError):R.validate_report(dict(valid,phase='PRIVATE_SENTINEL'),action,0)


@pytest.mark.parametrize('change',[{'missing_publication_verified':False},{'resources_before':{'available_bytes':0,'swap_used_bytes':0}},{'resources_before':{'available_bytes':True,'swap_used_bytes':0}}])
def test_false_apply_assurance_rejected(change):
    with pytest.raises(ValueError):R.validate_report(dict(success_report('apply'),**change),'apply',0)


def test_failed_apply_cannot_claim_success_or_automatic_rollback():
    report={'status':'PARTIAL','phase':'BACKEND_ACTIVATION','reason':'STARTUP_READINESS','automatic_rollback':False}
    assert R.validate_report(report,'apply',1)==report
    for changed in [dict(report,automatic_rollback=True),dict(report,reason='PRIVATE_SENTINEL'),dict(report,status='DEPLOYED')]:
        with pytest.raises(ValueError):R.validate_report(changed,'apply',1)
    with pytest.raises(ValueError):R.validate_report(report,'rollback',1)


def test_corrupt_backup_blocks_before_env_or_pointer_change(host,monkeypatch):
    original=D.create
    def corrupt(path,raw,mode=0o600):
        original(path,raw,mode)
        if path.name=='previous-api.env':path.write_bytes(b'corrupt')
    monkeypatch.setattr(D,'create',corrupt)
    with pytest.raises(D.Stop,match='BACKUP_ENV_VERIFY'):D.apply()
    assert D.ENV.read_bytes()==host.env and D.BACKEND_LINK.resolve()==host.old_api and D.STATIC_LINK.resolve()==host.old_static
    assert not D.API.exists() and not any(k=='service' for k,v in host.calls)


def test_late_isolation_failure_stops_before_activation(host,monkeypatch):
    calls=[]
    def runtime(target):
        calls.append(target)
        if len(calls)==2:raise D.Stop('SANDBOX_PROPERTIES')
    monkeypatch.setattr(D,'runtime',runtime)
    with pytest.raises(D.Stop,match='SANDBOX_PROPERTIES'):D.apply()
    assert len(calls)==2 and D.ENV.read_bytes()==host.env and D.BACKEND_LINK.resolve()==host.old_api
    assert not any(k=='service' for k,v in host.calls)


@pytest.mark.parametrize('name',['cache-control','Cache-Control','CACHE-CONTROL','cAcHe-CoNtRoL'])
@pytest.mark.parametrize('value',['no-store','No-Store','private, no-store'])
def test_missing_forecast_accepts_case_insensitive_http_fields(name,value):
    D.validate_missing_forecast(503,{name:value},b'{"detail":{"code":"FORECAST_WITHHELD"}}')


@pytest.mark.parametrize('code,headers,body,reason',[
    (500,{'cache-control':'no-store'},b'{"detail":{"code":"FORECAST_WITHHELD"}}','STATUS_MISMATCH'),
    (200,{'cache-control':'no-store'},b'{"detail":{"code":"FORECAST_WITHHELD"}}','STATUS_MISMATCH'),
    (503,{'cache-control':'no-store'},b'PRIVATE_SENTINEL','BODY_MISMATCH'),
    (503,{'cache-control':'no-store'},b'{"detail":{"code":"WRONG"}}','BODY_MISMATCH'),
    (503,{},b'{"detail":{"code":"FORECAST_WITHHELD"}}','CACHE_MISMATCH'),
    (503,{'cache-control':'public'},b'{"detail":{"code":"FORECAST_WITHHELD"}}','CACHE_MISMATCH'),
    (503,{'cache-control':'x-no-store'},b'{"detail":{"code":"FORECAST_WITHHELD"}}','CACHE_MISMATCH'),
    (503,{'cache-control':'no-store-invalid'},b'{"detail":{"code":"FORECAST_WITHHELD"}}','CACHE_MISMATCH'),
])
def test_missing_forecast_rejects_individual_mismatches_safely(code,headers,body,reason):
    with pytest.raises(D.Stop,match=reason) as caught:D.validate_missing_forecast(code,headers,body)
    assert str(caught.value)==reason and 'PRIVATE_SENTINEL' not in str(caught.value)
    report={'status':'PARTIAL','phase':'BACKEND_ACTIVATION','reason':reason,'automatic_rollback':False}
    assert R.validate_report(report,'apply',1)==report


@pytest.mark.parametrize('mode',['missing_root','missing_pointer','invalid','expired'])
def test_asgi_response_through_http_client_preserves_fail_closed_contract(tmp_path,monkeypatch,mode):
    import io
    import http.client
    from datetime import timedelta
    from joserfc import jwk
    from test_forecast_source_consistency import make_client,write_bundle
    from test_forecast_publication import fixture,NOW
    client,settings,root,clock,reads=make_client(tmp_path,monkeypatch,jwk.RSAKey.generate_key(2048,parameters={'kid':'key-one','alg':'RS256','use':'sig'}))
    if mode=='missing_pointer':root.mkdir();(root/'releases').mkdir()
    if mode=='invalid':write_bundle(root,{'version':1})
    if mode=='expired':write_bundle(root,fixture());clock[0]=NOW+timedelta(hours=4)
    with client:
        response=client.get('/forecast/next24')
        wire=b'HTTP/1.1 '+str(response.status_code).encode()+b' Response\r\n'+b''.join(k+b': '+v+b'\r\n' for k,v in response.headers.raw)+b'\r\n'+response.content
        class Socket:
            def makefile(self,*args):return io.BytesIO(wire)
        parsed=http.client.HTTPResponse(Socket());parsed.begin();headers=dict(parsed.getheaders());body=parsed.read()
        assert parsed.status==503 and json.loads(body)=={'detail':{'code':'FORECAST_WITHHELD'}}
        assert headers.get('cache-control')=='no-store'
        # This is the exact previous faulty predicate; HTTPResponse preserves the
        # lowercase ASGI field name, while the dictionary does not fold casing.
        assert 'no-store' not in headers.get('Cache-Control','')
        D.validate_missing_forecast(parsed.status,headers,body)
        summary=client.get('/operations/summary').json()
        assert summary['forecast_status']==('MISSING_PUBLICATION' if mode.startswith('missing') else 'EXPIRED' if mode=='expired' else 'WITHHELD')
        assert summary['health']=='Historical snapshot'
        assert response.json().get('forecasts') is None


@pytest.fixture
def retained(host,monkeypatch):
    D.apply();D.rollback()
    legacy=D.CONTROL
    previous={str(p.relative_to(legacy)):p.read_bytes() for p in legacy.iterdir() if p.is_file()}
    monkeypatch.setattr(D,'LEGACY_CONTROL',legacy)
    monkeypatch.setattr(D,'TRANSACTION_PARENT',legacy.parent/'transactions',raising=False)
    D.CONFIG['transaction_id']='1'*32
    # Exercise real transaction validation; only production-prefix path validation
    # is separately covered because this filesystem fixture lives under tmp_path.
    monkeypatch.setattr(D,'validate_rollback',VALIDATE_ROLLBACK)
    monkeypatch.setattr(D,'ROLLBACK',{'valid_target':lambda value,prefix:value},raising=False)
    D.CHANGED=False;D.PHASE='PREFLIGHT'
    return SimpleNamespace(host=host,legacy=legacy,previous=previous)


def assert_legacy_unchanged(retained):
    assert {str(p.relative_to(retained.legacy)):p.read_bytes() for p in retained.legacy.iterdir() if p.is_file()}==retained.previous


def test_reactivation_reuses_exact_files_and_new_private_transaction(retained):
    before_api={str(p.relative_to(D.API)):p.read_bytes() for p in D.API.rglob('*') if p.is_file()}
    before_static={str(p.relative_to(D.STATIC)):p.read_bytes() for p in D.STATIC.rglob('*') if p.is_file()}
    result=D.reactivate();assert result['status']=='DEPLOYED'
    assert D.CONTROL!=retained.legacy and D.CONTROL.name=='1'*32
    record=json.loads((D.CONTROL/'state.json').read_bytes());assert record['transaction_id']=='1'*32
    assert (D.CONTROL/'previous-api.env').read_bytes()==retained.host.env
    assert_legacy_unchanged(retained)
    assert before_api=={str(p.relative_to(D.API)):p.read_bytes() for p in D.API.rglob('*') if p.is_file()}
    assert before_static=={str(p.relative_to(D.STATIC)):p.read_bytes() for p in D.STATIC.rglob('*') if p.is_file()}
    D.rollback();assert D.ENV.read_bytes()==retained.host.env
    assert D.BACKEND_LINK.resolve()==retained.host.old_api and D.STATIC_LINK.resolve()==retained.host.old_static
    assert_legacy_unchanged(retained)


@pytest.mark.parametrize('problem',['modified','missing','extra_file','extra_dir','symlink','stale_record','wrong_target','collision','parent_symlink','parent_mode'])
def test_retained_drift_rejected_without_candidate_mutation(retained,problem):
    if problem=='modified':(D.API/'asset1').write_bytes(b'drift')
    if problem=='missing':(D.STATIC/'asset2').unlink()
    if problem=='extra_file':(D.API/'unexpected.py').write_bytes(b'extra')
    if problem=='extra_dir':(D.STATIC/'unexpected').mkdir()
    if problem=='symlink':(D.API/'asset1').unlink();(D.API/'asset1').symlink_to('/synthetic-outside')
    if problem in ('stale_record','wrong_target'):
        record=json.loads((retained.legacy/'state.json').read_bytes())
        record['phase' if problem=='stale_record' else 'new_backend']='COMPLETE' if problem=='stale_record' else '/synthetic-wrong'
        (retained.legacy/'state.json').write_text(json.dumps(record));(retained.legacy/'state.json').chmod(0o600)
    if problem=='parent_symlink':D.TRANSACTION_PARENT.symlink_to(retained.legacy,target_is_directory=True)
    if problem=='parent_mode':D.TRANSACTION_PARENT.mkdir(mode=0o755)
    if problem=='collision':
        D.TRANSACTION_PARENT.mkdir(mode=0o700);(D.TRANSACTION_PARENT/('1'*32)).mkdir(mode=0o700)
    calls=len(retained.host.calls)
    with pytest.raises((D.Stop,OSError)):D.reactivate()
    assert not D.CHANGED and D.ENV.read_bytes()==retained.host.env
    assert D.BACKEND_LINK.resolve()==retained.host.old_api and D.STATIC_LINK.resolve()==retained.host.old_static
    assert not any(k=='service' for k,v in retained.host.calls[calls:])


def test_partial_reactivation_can_roll_back_only_new_transaction(retained,monkeypatch):
    monkeypatch.setattr(D,'missing_acceptance',lambda:(_ for _ in ()).throw(D.Stop('CACHE_MISMATCH')))
    with pytest.raises(D.Stop):D.reactivate()
    new=D.CONTROL;assert new!=retained.legacy and D.BACKEND_LINK.resolve()==D.API
    D.rollback();assert D.CONTROL==new and D.ENV.read_bytes()==retained.host.env
    assert json.loads((new/'state.json').read_bytes())['phase']=='ROLLED_BACK'
    assert_legacy_unchanged(retained)


def test_transaction_record_cannot_be_substituted(monkeypatch):
    rb=load('pure_rollback_targets',ROOT/'deploy/staging/forecast-consistency-release/rollback_state.py')
    monkeypatch.setattr(D,'ROLLBACK',vars(rb),raising=False)
    monkeypatch.setattr(D,'CONFIG',{'files':{},'transaction_id':'a'*32},raising=False)
    monkeypatch.setattr(D,'CONTROL',D.TRANSACTION_PARENT/('a'*32))
    record={'version':1,'transaction_id':'a'*32,'previous_backend':'/opt/powerflow/releases/old','previous_static':'/var/www/powerflow-staging/releases/old','new_backend':str(D.API),'new_static':str(D.STATIC),'previous_service_state':'active','original_env_sha256':D.ENV_BASELINE,'installed_env_sha256':'1'*64,'production_fingerprint':'2'*64,'legacy_record_sha256':'3'*64,'old_static_files':{},'retained_assets':{},'phase':'BACKUPS'}
    D.validate_transaction_record(record)
    with pytest.raises(D.Stop):D.validate_transaction_record(dict(record,transaction_id='b'*32))


def test_reactivation_rechecks_retained_hashes_at_activation_boundary(retained,monkeypatch):
    count=[0]
    def capacity(extra):
        count[0]+=1
        if count[0]==2:(D.API/'asset1').write_bytes(b'late drift')
        return {'available_bytes':900*1024**2,'swap_used_bytes':0}
    monkeypatch.setattr(D,'idle_capacity',capacity)
    with pytest.raises(D.Stop,match='RETAINED_FILE_HASH'):D.reactivate()
    assert D.ENV.read_bytes()==retained.host.env and D.BACKEND_LINK.resolve()==retained.host.old_api
    assert_legacy_unchanged(retained)


def test_reactivation_corrupt_fresh_backup_blocks_candidate_changes(retained,monkeypatch):
    original=D.create
    def corrupt(path,raw,mode=0o600):
        original(path,raw,mode)
        if path.name=='previous-api.env':path.write_bytes(b'bad backup')
    monkeypatch.setattr(D,'create',corrupt)
    with pytest.raises(D.Stop,match='BACKUP_ENV_VERIFY'):D.reactivate()
    assert D.ENV.read_bytes()==retained.host.env and D.BACKEND_LINK.resolve()==retained.host.old_api
    assert_legacy_unchanged(retained)


@pytest.mark.parametrize('step',sorted(D.BACKEND_STEPS))
@pytest.mark.parametrize('error,cause',[
    (PermissionError(13,'PRIVATE_SENTINEL','/secret/path'),'PERMISSION_DENIED'),
    (FileNotFoundError(2,'PRIVATE_SENTINEL','/secret/path'),'MISSING_FILE'),
    (TimeoutError('PRIVATE_SENTINEL'),'TIMEOUT'),
    (OSError(5,'PRIVATE_SENTINEL'),'OS_ERROR'),
    (ValueError('PRIVATE_SENTINEL'),'VALUE_ERROR'),
    (KeyError('PRIVATE_SENTINEL'),'MISSING_KEY'),
    (RuntimeError('PRIVATE_SENTINEL'),'UNEXPECTED_EXCEPTION'),
])
def test_backend_unexpected_exceptions_have_safe_substep_codes(step,error,cause):
    def fail():raise error
    with pytest.raises(D.Stop) as caught:D.backend_step(step,fail)
    reason='BACKEND_'+step+'_'+cause
    assert str(caught.value)==reason and 'PRIVATE_SENTINEL' not in str(caught.value)
    report={'status':'PARTIAL','phase':'BACKEND_ACTIVATION','reason':reason,'automatic_rollback':False}
    assert R.validate_report(report,'reactivate',1)==report


def test_backend_substep_preserves_explicit_gate_and_return_value():
    original=D.Stop('SANDBOX_PROPERTIES')
    def fail():raise original
    with pytest.raises(D.Stop) as caught:D.backend_step('RUNTIME',fail)
    assert caught.value is original
    assert D.backend_step('RECORD_SAVE',lambda a,b:a+b,1,2)==3
    with pytest.raises(D.Stop,match='ACTION_SCOPE'):D.backend_step('UNREVIEWED',lambda:pytest.fail('Not reached'))


@pytest.mark.parametrize('step',sorted(D.BACKEND_STEPS))
def test_activation_failure_identifies_substep_and_never_switches_static(retained,monkeypatch,step):
    original=D.backend_step;seen=[]
    def execute(label,function,*args):
        seen.append(label)
        if label==step:
            def fail():raise PermissionError(13,'PRIVATE_SENTINEL')
            return original(label,fail)
        return original(label,function,*args)
    monkeypatch.setattr(D,'backend_step',execute)
    with pytest.raises(D.Stop,match='BACKEND_'+step+'_PERMISSION_DENIED'):D.reactivate()
    assert seen[-1]==step and D.PHASE=='BACKEND_ACTIVATION'
    assert D.STATIC_LINK.resolve()==retained.host.old_static
    assert_legacy_unchanged(retained)


@pytest.fixture
def diagnostic(retained,monkeypatch):
    D.reactivate();D.rollback();D.PHASE='PREFLIGHT';D.CHANGED=False
    calls=[]
    def command(argv,**kwargs):
        calls.append((argv,kwargs))
        assert argv==['/usr/bin/systemctl','show',D.UNIT,'--property='+D.SERVICE_PROPERTIES]
        assert kwargs=={'timeout':8,'limit':16384,'grace':5}
        return {'returncode':0,'failure':None,'stderr':b'PRIVATE_SENTINEL',
            'stdout':('Id='+D.UNIT+'\nUser=powerflow-api\nGroup=powerflow-api\nActiveState=active\nSubState=running\nResult=success\nExecMainCode=0\nExecMainStatus=0\nStatusErrno=0\nNRestarts=0\n').encode()}
    monkeypatch.setitem(D.BASE,'bounded_run',command)
    for name in ('create','atomic_file','pointer','state_save','run','candidate_ready','runtime','request_api','probe','idle_capacity','production'):
        monkeypatch.setattr(D,name,lambda *a,**kw:pytest.fail('Diagnostic must not mutate, probe or inspect unrelated services'))
    return retained,calls


def test_readonly_diagnostic_uses_only_candidate_metadata_and_preserves_all_files(diagnostic):
    retained,calls=diagnostic
    root=retained.legacy.parent.parent
    before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result=D.diagnose_backend();assert R.validate_report(result,'diagnose-backend',0)==result
    assert result['status']=='DIAGNOSTIC_COMPLETE' and result['historical_failure_proven'] is False
    for key in ('candidate_active','candidate_running','unit_identity_match','transaction_record_valid','transaction_rolled_back','backup_hash_valid','backend_original','static_original','env_original','env_safe','parent_permissions_safe'):assert result['facts'][key] is True
    assert result['facts']['backend_release'] is False and result['facts']['env_installed'] is False
    assert before=={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert len(calls)==1 and not D.CHANGED
    assert 'PRIVATE_SENTINEL' not in json.dumps(result)
    assert_legacy_unchanged(retained)


@pytest.mark.parametrize('failure',['timeout','exit','output','unknown_property','bad_record','permission'])
def test_diagnostic_failures_are_unverified_and_redacted(diagnostic,monkeypatch,failure):
    retained,_=diagnostic
    if failure in ('timeout','exit','output','unknown_property'):
        monkeypatch.setitem(D.BASE,'bounded_run',lambda *a,**k:{'returncode':1 if failure=='exit' else 0,'failure':'TIMEOUT' if failure=='timeout' else 'OUTPUT_LIMIT' if failure=='output' else None,'stdout':b'Environment=PRIVATE_SENTINEL\n','stderr':b'PRIVATE_SENTINEL'})
    if failure=='bad_record':
        record=json.loads((D.CONTROL/'state.json').read_bytes());record['transaction_id']='b'*32
        (D.CONTROL/'state.json').write_text(json.dumps(record))
    if failure=='permission':monkeypatch.setattr(D,'safe',lambda *a:(_ for _ in ()).throw(PermissionError(13,'PRIVATE_SENTINEL')))
    result=D.diagnose_backend();assert result['status']=='UNVERIFIED' and result['cause_codes']
    assert R.validate_report(result,'diagnose-backend',0)==result
    assert not result['historical_failure_proven'] and 'PRIVATE_SENTINEL' not in json.dumps(result)
    assert not D.CHANGED


def test_diagnostic_report_rejects_unbounded_or_private_output(diagnostic):
    result=D.diagnose_backend()
    for report in [dict(result,raw_stderr='PRIVATE_SENTINEL'),dict(result,historical_failure_proven=True),
        dict(result,cause_codes=['PRIVATE_SENTINEL']),dict(result,facts=dict(result['facts'],last_unit_result='PRIVATE_SENTINEL')),
        dict(result,facts=dict(result['facts'],exec_main_status=True)),dict(result,facts=dict(result['facts'],candidate_active='yes'))]:
        with pytest.raises(ValueError):R.validate_report(report,'diagnose-backend',0)


def test_diagnostic_and_backend_code_allowlists_match():
    for key in ('BACKEND_STEPS','ERROR_CAUSES','DIAGNOSTIC_STEPS','DIAGNOSTIC_BOOLS','DIAGNOSTIC_INTS','UNIT_RESULTS'):
        assert getattr(D,key)==getattr(R,key)
    source=ast.parse((DIR/'deploy.py').read_text())
    function=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='diagnose_backend')
    calls={n.func.id for n in ast.walk(function) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
    assert not calls & {'create','atomic_file','pointer','state_save','run','runtime','request_api','probe','production','idle_capacity','apply','reactivate','rollback'}


def test_diagnostic_supervisor_uses_one_fixed_bounded_command(tmp_path,monkeypatch,diagnostic,capsys):
    import sys
    report=D.diagnose_backend();(tmp_path/'preflight').mkdir();calls=[]
    def bounded(argv,**kwargs):
        calls.append((argv,kwargs))
        assert argv==['/verified/ssh','sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 30s /usr/bin/python3 -I -S -B -']
        assert kwargs=={'input':b'verified-diagnostic','timeout':90,'limit':131072,'grace':5}
        return {'returncode':0,'failure':None,'stdout':json.dumps(report).encode(),'stderr':b''}
    wrapper={'profile':lambda:{},'ssh_argv':lambda p:['/verified/ssh','fixed-placeholder'],'PRIVATE':tmp_path}
    monkeypatch.setattr(R,'verify',lambda digest,action:(b'verified-diagnostic',wrapper,{'bounded_run':bounded}))
    monkeypatch.setattr(sys,'argv',['run.py','diagnose-backend','--manifest-sha256','a'*64])
    assert R.main()==0 and len(calls)==1
    output=json.loads(capsys.readouterr().out);assert output['report']==report
    assert len(list((tmp_path/'preflight').iterdir()))==1


def test_operations_timeout_reproduces_recorded_latency_and_preserves_contract(monkeypatch):
    """No sleep/network: simulate the measured4.66s header latency deterministically."""
    import http.client
    calls=[]
    class LegacySocketTimeout(OSError):pass
    assert not isinstance(LegacySocketTimeout(),TimeoutError)
    monkeypatch.setattr(D.socket,'timeout',LegacySocketTimeout)
    class Response:
        def __init__(self,path):self.path=path;self.status=503 if path=='/forecast/next24' else 401 if path.startswith('/admin/') else 200
        def getheaders(self):return [('cache-control','no-store')]
        def read(self,limit):
            assert limit==1000001
            if self.path=='/forecast/next24':return b'{"detail":{"code":"FORECAST_WITHHELD"}}'
            if self.path=='/operations/summary':return b'{"forecast_status":"MISSING_PUBLICATION","health":"Historical snapshot","completeness_note":"Historical evidence only"}'
            if self.path=='/forecast/one-hour?limit=24&offset=0':return b'{"row_count":1,"total_rows":1,"limit":24,"offset":0,"has_more":false,"forecasts":[{}]}'
            return b'{}'
    class Connection:
        def __init__(self,host,port,timeout):assert (host,port)==('127.0.0.1',8010);self.timeout=timeout
        def request(self,method,path):assert method=='GET';self.path=path;calls.append((path,self.timeout))
        def getresponse(self):
            if self.path=='/operations/summary' and self.timeout<4.66:raise LegacySocketTimeout('PRIVATE_SENTINEL')
            return Response(self.path)
        def close(self):pass
    old=Connection('127.0.0.1',8010,3);old.request('GET','/operations/summary')
    with pytest.raises(LegacySocketTimeout):old.getresponse()
    assert D.exception_cause(LegacySocketTimeout())=='TIMEOUT'
    monkeypatch.setattr(http.client,'HTTPConnection',Connection)
    monkeypatch.setattr(D,'OVERLAY',Path('/synthetic-definitely-absent'))
    calls.clear();D.missing_acceptance()
    assert len(calls)==7 and ('/operations/summary',10) in calls
    assert all(timeout==(10 if path=='/operations/summary' else 3) for path,timeout in calls)


@pytest.mark.parametrize('error,cause',[
    (ConnectionRefusedError(errno.ECONNREFUSED,'PRIVATE_SENTINEL'),'CONNECTION_REFUSED'),
    (OSError(errno.ENETUNREACH,'PRIVATE_SENTINEL'),'UNREACHABLE'),
    (PermissionError(13,'PRIVATE_SENTINEL'),'PERMISSION_DENIED'),
    (ConnectionResetError(errno.ECONNRESET,'PRIVATE_SENTINEL'),'CONNECTION_RESET'),
    (TimeoutError('PRIVATE_SENTINEL'),'TIMEOUT'),
])
@pytest.mark.parametrize('stage',['REQUEST','HEADERS','BODY'])
def test_api_transport_failures_are_not_application_503(monkeypatch,error,cause,stage):
    import http.client
    closed=[]
    class Response:
        status=503
        def read(self,limit):raise error
    class Connection:
        def __init__(self,*a,**k):pass
        def request(self,*a):
            if stage=='REQUEST':raise error
        def getresponse(self):
            if stage=='HEADERS':raise error
            return Response()
        def close(self):closed.append(True)
    monkeypatch.setattr(http.client,'HTTPConnection',Connection)
    with pytest.raises(D.Stop) as caught:D.request_api('/forecast/next24')
    expected='API_FORECAST_'+stage+'_'+cause
    assert str(caught.value)==expected and closed==[True]
    assert 'PRIVATE_SENTINEL' not in str(caught.value)
    assert R.validate_report({'status':'PARTIAL','phase':'BACKEND_ACTIVATION','reason':expected,'automatic_rollback':False},'reactivate',1)


def test_legacy_python39_socket_timeout_reports_endpoint_and_phase(monkeypatch):
    import http.client
    class LegacySocketTimeout(OSError):pass
    monkeypatch.setattr(D.socket,'timeout',LegacySocketTimeout)
    class Connection:
        def __init__(self,*a,**k):pass
        def request(self,*a):pass
        def getresponse(self):raise LegacySocketTimeout('PRIVATE_SENTINEL')
        def close(self):pass
    monkeypatch.setattr(http.client,'HTTPConnection',Connection)
    with pytest.raises(D.Stop,match='API_OPERATIONS_HEADERS_TIMEOUT'):D.request_api('/operations/summary')


def test_malformed_http_and_oversized_response_fail_closed(monkeypatch):
    import http.client
    class Connection:
        def __init__(self,*a,**k):pass
        def request(self,*a):pass
        def getresponse(self):raise http.client.BadStatusLine('PRIVATE_SENTINEL')
        def close(self):pass
    monkeypatch.setattr(http.client,'HTTPConnection',Connection)
    with pytest.raises(D.Stop,match='API_FORECAST_HEADERS_HTTP_PROTOCOL'):D.request_api('/forecast/next24')
    class Response:
        status=503
        def read(self,limit):return b'x'*limit
    monkeypatch.setattr(Connection,'getresponse',lambda self:Response())
    with pytest.raises(D.Stop,match='API_BODY_BOUND'):D.request_api('/forecast/next24')


def test_paginated_historical_acceptance_rejects_ignored_or_false_limits():
    valid={'row_count':24,'total_rows':15000,'limit':24,'offset':0,'has_more':True,'forecasts':[{}]*24}
    D.validate_one_hour_page(valid)
    for change in ({'forecasts':[{}]*25,'row_count':25}, {'limit':500}, {'offset':1}, {'has_more':False}, {'row_count':True}, {'total_rows':12}, {'forecasts':None}):
        with pytest.raises(D.Stop,match='API_PAGINATION_CONTRACT'):D.validate_one_hour_page(dict(valid,**change))
    with pytest.raises(D.Stop,match='API_PAGINATION_CONTRACT'):D.validate_one_hour_page({'row_count':24,'forecasts':[{}]*24})


def test_body_bound_reports_only_allowlisted_metadata(monkeypatch):
    import http.client
    class Response:
        status=200
        def read(self,limit):assert limit==1_000_001;return b'x'*limit
        def getheader(self,key,default=None):return {'Content-Length':'1694070','Content-Type':'application/json'}.get(key,default)
    class Connection:
        def __init__(self,*a,**kw):pass
        def request(self,method,path):assert path=='/forecast/one-hour?limit=24&offset=0'
        def getresponse(self):return Response()
        def close(self):pass
    monkeypatch.setattr(http.client,'HTTPConnection',Connection)
    with pytest.raises(D.Stop,match='API_BODY_BOUND') as caught:D.request_api('/forecast/one-hour?limit=24&offset=0')
    evidence=caught.value.api_body_bound
    R.validate_body_bound(evidence)
    assert evidence['endpoint']=='/forecast/one-hour' and evidence['query_scope']=='LATEST_24'
    assert evidence['measured_bytes']==1_000_001 and evidence['content_length']==1694070
    report={'status':'PARTIAL','phase':'BACKEND_ACTIVATION','reason':'API_BODY_BOUND','automatic_rollback':False,'api_body_bound':evidence}
    assert R.validate_report(report,'apply',1)==report
    for change in ({'endpoint':'/private'}, {'query_scope':'PRIVATE_SENTINEL'}, {'content_type':'PRIVATE_SENTINEL'}, {'measured_bytes':1}, {'content_length':-1}):
        with pytest.raises(ValueError):R.validate_body_bound(dict(evidence,**change))


def test_correct_page_remains_under_body_bound(monkeypatch):
    import http.client
    page={'row_count':24,'total_rows':15000,'limit':24,'offset':0,'has_more':True,'forecasts':[{}]*24}
    raw=json.dumps(page).encode()
    class Response:
        status=200
        def read(self,limit):return raw[:limit]
        def getheaders(self):return [('Content-Type','application/json')]
    class Connection:
        def __init__(self,*a,**kw):pass
        def request(self,*a):pass
        def getresponse(self):return Response()
        def close(self):pass
    monkeypatch.setattr(http.client,'HTTPConnection',Connection)
    code,_,body=D.request_api('/forecast/one-hour?limit=24&offset=0')
    assert code==200;D.validate_one_hour_page(json.loads(body))


def test_production_preservation_requires_exact_deployed_a03_parser(monkeypatch):
    monkeypatch.setattr(D,'BASE',{'services':lambda:{'production':{'ActiveState':'active','SubState':'running'}},'fingerprints':lambda units:'stable'},raising=False)
    expected='8800f34a2d0e3db4056e921a7b6629847402f37c20ff9b3e81d50f3c1d77865f'
    monkeypatch.setattr(D,'digest',lambda p:expected)
    assert len(D.production())==64
    monkeypatch.setattr(D,'digest',lambda p:'0'*64)
    with pytest.raises(D.Stop,match='APPROVED_PARSER_DRIFT'):D.production()


def test_new_release_apply_uses_fresh_transaction_and_independent_rollback(retained,monkeypatch):
    # Install a NEW release; never edit the consumed retained release or record.
    old_retained_api=D.API;old_retained_static=D.STATIC
    before_api={str(p.relative_to(D.API)):p.read_bytes() for p in D.API.rglob('*') if p.is_file()}
    monkeypatch.setattr(D,'API',D.API.parent/'new-paginated-release')
    monkeypatch.setattr(D,'STATIC',D.STATIC.parent/'new-paginated-release')
    D.apply()
    assert D.CONTROL.name=='1'*32 and D.CONTROL!=retained.legacy
    record=json.loads((D.CONTROL/'state.json').read_bytes())
    assert record['transaction_id']=='1'*32 and record['legacy_record_sha256']==D.digest(retained.legacy/'state.json')
    assert D.digest(D.CONTROL/'previous-api.env')==D.ENV_BASELINE
    D.rollback()
    assert D.BACKEND_LINK.resolve()==retained.host.old_api and D.STATIC_LINK.resolve()==retained.host.old_static
    assert D.ENV.read_bytes()==retained.host.env
    assert old_retained_static.exists() and before_api=={str(p.relative_to(old_retained_api)):p.read_bytes() for p in old_retained_api.rglob('*') if p.is_file()}
    assert_legacy_unchanged(retained)


def test_new_release_apply_rejects_existing_transaction_without_mutation(retained,monkeypatch):
    monkeypatch.setattr(D,'API',D.API.parent/'new-paginated-release')
    monkeypatch.setattr(D,'STATIC',D.STATIC.parent/'new-paginated-release')
    D.TRANSACTION_PARENT.mkdir(mode=0o700)
    (D.TRANSACTION_PARENT/('1'*32)).mkdir(mode=0o700)
    with pytest.raises(D.Stop,match='DESTINATION_CONFLICT'):D.apply()
    assert D.BACKEND_LINK.resolve()==retained.host.old_api and D.ENV.read_bytes()==retained.host.env
    assert not D.API.exists();assert_legacy_unchanged(retained)


@pytest.mark.parametrize('failure',['legacy_backup','legacy_state','transaction_mode'])
def test_new_apply_drift_stops_before_any_new_write(retained,monkeypatch,failure):
    monkeypatch.setattr(D,'API',D.API.parent/'new-paginated-release')
    monkeypatch.setattr(D,'STATIC',D.STATIC.parent/'new-paginated-release')
    if failure=='legacy_backup':(retained.legacy/'previous-api.env').write_bytes(b'drift')
    elif failure=='legacy_state':
        p=retained.legacy/'state.json';r=json.loads(p.read_bytes());r['phase']='COMPLETE';p.write_text(json.dumps(r))
    else:D.TRANSACTION_PARENT.mkdir(mode=0o755)
    with pytest.raises(D.Stop):D.apply()
    assert not D.CHANGED and not D.API.exists() and not D.STATIC.exists()
    assert not (D.TRANSACTION_PARENT/('1'*32)).exists()
    assert D.ENV.read_bytes()==retained.host.env and D.BACKEND_LINK.resolve()==retained.host.old_api
