"""Synthetic filesystem and mock services only. No SSH or actual service action."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import ast
import pytest

ROOT=Path(__file__).resolve().parents[1];DIR=ROOT/'deploy/staging/forecast-consistency-deployment'
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
D=load('deploy_job',DIR/'deploy.py');R=load('deploy_runner',DIR/'run.py')


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
    monkeypatch.setattr(D,'missing_acceptance',lambda:(_ for _ in ()).throw(D.Stop('MISSING_FORECAST_CONTRACT')))
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
