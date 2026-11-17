"""Disposable local fixtures/mocked OS services only. Never SSH/AWS/systemd/Docker."""
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tarfile
import pytest

ROOT=Path(__file__).parents[1];PACKAGE=ROOT/'deploy/staging/install-package'
def load(name):
    spec=importlib.util.spec_from_file_location('staging_'+name,PACKAGE/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
pub=load('publisher');installer=load('install');bpf=load('cgroup_bpf');cognito=load('prepare-cognito')

@pytest.fixture
def source_plan(tmp_path,monkeypatch):
    root=tmp_path/'source';root.mkdir();db=root/'snapshot.db'
    with sqlite3.connect(db) as c:
        for name in pub.COUNTS:c.execute('CREATE TABLE '+name+'(id INTEGER)')
    monkeypatch.setattr(pub,'COUNTS',{name:0 for name in pub.COUNTS})
    text=root/'market.csv';text.write_text('timestamp,value\n2026-10-01T00:00:00Z,1\n')
    plan=[{'source':str(p),'relative_path':rel,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'freshness':{'classification':'HISTORICAL'}} for p,rel in ((text,'data/market.csv'),(db,'database/electricity_trading.db'))]
    monkeypatch.setattr(pub.os,'chown',lambda *a:None)
    return plan


def test_source_drift_aborts_before_any_publication_write(tmp_path,source_plan):
    Path(source_plan[0]['source']).write_text('drift')
    with pytest.raises(RuntimeError,match='approved_source_drift'):
        pub.publish(source_plan,tmp_path/'published',tmp_path/'.partial',os.getgid(),{},rename=os.rename)
    assert not (tmp_path/'.partial').exists() and not (tmp_path/'published').exists()


def test_atomic_publish_hashes_modes_historical_label_and_originals_unchanged(tmp_path,source_plan):
    originals={x['source']:Path(x['source']).read_bytes() for x in source_plan}
    destination=tmp_path/'published';temporary=tmp_path/'.partial';calls=[]
    def rename(src,dst):
        assert not dst.exists()
        assert stat.S_IMODE(src.stat().st_mode)==0o750
        assert len(list(src.rglob('*.db')))==1
        calls.append(True);os.rename(src,dst)
    r=pub.publish(source_plan,destination,temporary,os.getgid(),{'test':True},rename=rename)
    assert calls==[True] and not temporary.exists() and r['historical_A1']
    manifest=json.loads((destination/'_publication.json').read_bytes())
    assert manifest['operational_data_classification']=='HISTORICAL' and manifest['not_current_operational_state']
    for x in source_plan:
        target=destination/x['relative_path'];assert hashlib.sha256(target.read_bytes()).hexdigest()==x['sha256']
        assert stat.S_IMODE(target.stat().st_mode)==0o640
        assert Path(x['source']).read_bytes()==originals[x['source']]
    assert not list(destination.rglob('*-wal')) and not list(destination.rglob('*-shm'))


def test_destination_conflict_never_overwrites(tmp_path,source_plan):
    target=tmp_path/'published';target.mkdir();(target/'keep').write_text('preserve')
    with pytest.raises(RuntimeError,match='publication_destination_exists'):
        pub.publish(source_plan,target,tmp_path/'.partial',os.getgid(),{},rename=os.rename)
    assert (target/'keep').read_text()=='preserve'


def test_copy_failure_remains_private_and_not_visible(tmp_path,source_plan,monkeypatch):
    original=pub.digest_file;calls=[]
    def hash_file(path):
        calls.append(path)
        if len(calls)==3:raise RuntimeError('injected_copy_failure')
        return original(path)
    monkeypatch.setattr(pub,'digest_file',hash_file)
    with pytest.raises(RuntimeError,match='injected_copy_failure'):
        pub.publish(source_plan,tmp_path/'published',tmp_path/'.partial',os.getgid(),{},rename=os.rename)
    assert not (tmp_path/'published').exists()
    assert stat.S_IMODE((tmp_path/'.partial').stat().st_mode)==0o700


def test_sources_cannot_escape_via_symlink(tmp_path,source_plan):
    p=Path(source_plan[0]['source']);link=tmp_path/'link';link.symlink_to(p);source_plan[0]['source']=str(link)
    with pytest.raises(RuntimeError,match='symlink_path'):pub.validate_sources(source_plan)


def test_source_permission_drift_is_rejected(source_plan):
    source_plan[0]['mode']=0o777
    with pytest.raises(RuntimeError,match='permission_drift'):pub.validate_sources(source_plan)


def test_archive_rejects_symlinks_extra_members_and_bad_hash(tmp_path):
    p=tmp_path/'bad.tar.gz'
    with tarfile.open(p,'w:gz') as t:
        member=tarfile.TarInfo('allowed');member.type=tarfile.SYMTYPE;member.linkname='/etc/passwd';t.addfile(member)
    with pytest.raises(RuntimeError,match='archive_member'):installer.archive_inventory(p,{'allowed':{'bytes':0,'sha256':'0'*64}})


def test_bpf_query_is_read_only_and_checks_both_directions(tmp_path,monkeypatch):
    monkeypatch.setattr(bpf.platform,'system',lambda:'Linux');monkeypatch.setattr(bpf.platform,'machine',lambda:'x86_64')
    seen=[]
    def query(number,command,pointer,size):
        assert (number,command,size)==(321,16,40)
        q=ctypes.cast(pointer,ctypes.POINTER(bpf.Query)).contents
        assert q.query_flags==1
        ids=ctypes.cast(q.prog_ids,ctypes.POINTER(ctypes.c_uint32));ids[0]=123;q.prog_cnt=1;seen.append(q.attach_type);return 0
    assert bpf.attachments(tmp_path,call=query)=={'ingress':[123],'egress':[123]}
    assert seen==[0,1]
    def denied(*args):ctypes.set_errno(1);return -1
    with pytest.raises(RuntimeError,match='errno_1'):bpf.attachments(tmp_path,call=denied)


def test_cognito_transform_is_only_additive_and_preserves_security_settings():
    before={'UserPoolId':'us-east-1_NLoYFRvex','ClientId':'4t8s6a673a18qhbauqac8rhdcf','CallbackURLs':['http://localhost:5175/auth/callback'],'LogoutURLs':['http://localhost:5175/'],'SupportedIdentityProviders':['COGNITO','Google'],'AllowedOAuthScopes':['openid','email','profile','aws.cognito.signin.user.admin'],'WriteAttributes':['name','email','preferred_username'],'EnableTokenRevocation':True}
    result=cognito.prepare({'UserPoolClient':before})
    assert result['CallbackURLs']==before['CallbackURLs']+['https://staging.powerflowenergy.dev/auth/callback']
    for key in set(before)-{'CallbackURLs','LogoutURLs'}:assert result[key]==before[key]
    assert len(before['CallbackURLs'])==1
    with pytest.raises(AssertionError):cognito.prepare({'UserPoolClient':{**before,'UnexpectedNewField':True}})
    with pytest.raises(AssertionError):cognito.prepare({'UserPoolClient':{**before,'ClientSecret':'never-output'}})


def test_package_never_replaces_old_services_or_runs_training():
    source=(PACKAGE/'install.py').read_text()
    assert "'--no-index'" in source and "'--only-binary=:all:'" in source
    assert 'standalone_delete_journal_required' in (PACKAGE/'publisher.py').read_text()
    assert "MemoryMax')==str(512*1024**2)" in source
    assert "MemorySwapMax')=='0'" in source
    assert "'daemon-reload'" in source
    assert "['/usr/bin/systemctl','start',SERVICE]" in source
    assert "['/usr/bin/systemctl','stop',SERVICE]" in source
    assert 'git pull' not in source and "'certbot'" not in source
    for p in PACKAGE.glob('*.py'):compile(p.read_bytes(),str(p),'exec')


def test_snapshot_sidecar_aborts_without_writes(tmp_path,source_plan):
    db=next(Path(x['source']) for x in source_plan if x['source'].endswith('.db'))
    Path(str(db)+'-wal').write_bytes(b'unapproved')
    with pytest.raises(RuntimeError,match='snapshot_sidecar_present'):
        pub.publish(source_plan,tmp_path/'published',tmp_path/'.partial',os.getgid(),{},rename=os.rename)
    assert not (tmp_path/'.partial').exists()


def test_wal_header_image_is_not_silently_repaired(tmp_path,source_plan):
    item=next(x for x in source_plan if x['source'].endswith('.db'));p=Path(item['source'])
    body=bytearray(p.read_bytes());body[18:20]=b'\x02\x02';p.write_bytes(body);item['sha256']=hashlib.sha256(body).hexdigest()
    with pytest.raises(RuntimeError,match='standalone_delete_journal_required'):
        pub.publish(source_plan,tmp_path/'published',tmp_path/'.partial',os.getgid(),{},rename=os.rename)
    assert not (tmp_path/'published').exists() and p.read_bytes()==body


def test_runtime_resource_guards_fail_closed(tmp_path,monkeypatch):
    root=tmp_path/'cg';root.mkdir()
    monkeypatch.setattr(installer,'read',lambda p:{'memory.high':str(384*1024**2),'memory.max':str(512*1024**2),'memory.swap.max':'0'}[p.name].encode())
    props={'ActiveState':'active','NRestarts':'0','User':'powerflow-api','Group':'powerflow-api','MainPID':'123',
           'MemoryHigh':str(384*1024**2),'MemoryMax':str(512*1024**2),'MemorySwapMax':'0','ProtectHome':'yes','ProtectSystem':'strict',
           'NoNewPrivileges':'yes','PrivateTmp':'yes','PrivateDevices':'yes','CapabilityBoundingSet':'',
           'IPAddressDeny':'169.254.169.254/32 fd00:ec2::254/128','ControlGroup':'/system.slice/'+installer.SERVICE}
    def run(label,*a,**k):
        return ('\n'.join(k+'='+v for k,v in props.items()).encode() if label=='effective-unit-properties' else b'LISTEN 0 32 127.0.0.1:8010 0.0.0.0:* users:(("python",pid=123,fd=1))')
    monkeypatch.setattr(installer,'run',run);monkeypatch.setattr(installer.os,'access',lambda *a:True)
    monkeypatch.setattr(installer,'attachments',lambda *a:{'ingress':[],'egress':[]})
    with pytest.raises(RuntimeError,match='bpf_attachment_missing'):installer.limits_and_bpf()
    props['MemorySwapMax']='512'
    with pytest.raises(RuntimeError,match='unit_resource_limits'):installer.limits_and_bpf()
    props['MemorySwapMax']='0';props['ProtectSystem']='full'
    with pytest.raises(RuntimeError,match='effective_sandbox_mismatch'):installer.limits_and_bpf()


def test_execution_wrapper_rejects_bundle_drift_without_transport(tmp_path):
    runner=load('execute-approved');(tmp_path/'bundle.json').write_text('{}')
    with pytest.raises(RuntimeError,match='bundle_hash'):runner.verify(tmp_path,'0'*64)
