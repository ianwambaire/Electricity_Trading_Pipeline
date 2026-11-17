"""Synthetic code packet and temporary directories. No SSH, services or forecasts."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/'deploy/staging/forecast-publication'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
J=load('setup_first_test',DIR/'setup_first.py');R=load('setup_runner_test',DIR/'run_first_setup.py')

def packet(files):
    out=io.BytesIO()
    with tarfile.open(fileobj=out,mode='w:gz') as t:
        for name,data in files.items():
            info=tarfile.TarInfo(name);info.size=len(data);t.addfile(info,io.BytesIO(data))
    assert len(out.getvalue())<6470
    return out.getvalue().ljust(6470,b'\0')

@pytest.fixture
def host(tmp_path,monkeypatch):
    hashes={k:hashlib.sha256(b'' if k.endswith('__init__.py') else b'# synthetic code\n').hexdigest() for k in J.HASHES}
    files={k:(b'' if k.endswith('__init__.py') else b'# synthetic code\n') for k in hashes}
    files['tools-manifest.json']=json.dumps(hashes).encode();raw=packet(files)
    parent=tmp_path/'srv';parent.mkdir();opt=tmp_path/'opt';opt.mkdir()
    values={'ROOT':parent/'publication','TOOLS_PARENT':opt/'tools','TOOLS':opt/'tools'/'approved','HASHES':hashes,
      'PACKET_SHA':hashlib.sha256(raw).hexdigest(),'CONFIG':{'packet':base64.b64encode(raw).decode()},'CHANGED':False,'PHASE':'PREFLIGHT'}
    for key,value in values.items():monkeypatch.setattr(J,key,value,raising=False)
    monkeypatch.setattr(J.os,'getuid',lambda:0);monkeypatch.setattr(J.os,'geteuid',lambda:0);monkeypatch.setattr(J.os,'getgid',lambda:0);monkeypatch.setattr(J.os,'getegid',lambda:0);monkeypatch.setattr(J.os,'chown',lambda *a,**kw:None)
    monkeypatch.setattr(J,'system_executables',lambda:None);monkeypatch.setattr(J,'candidate',lambda:42)
    access=[];monkeypatch.setattr(J,'access',lambda pid,phase:access.append((pid,phase)))
    original=Path.lstat
    def rootstat(path,*a,**kw):
        s=list(original(path,*a,**kw));s[4]=0;s[5]=992 if path in (J.ROOT,J.ROOT/'releases') else 0
        if path!=tmp_path and tmp_path not in path.parents:s[0]&=~0o022
        return os.stat_result(s)
    monkeypatch.setattr(Path,'lstat',rootstat)
    return {'raw':raw,'files':files,'access':access,'tmp':tmp_path}

def test_first_setup_exact_scope_and_idempotent_reuse(host):
    result=J.setup();assert result['status']=='SETUP_READY' and result['tools']=='INSTALLED'
    assert result['candidate_bundle_access']=='UNVERIFIED_NO_BUNDLE' and result['publication_performed'] is False
    assert host['access']==[(42,'parent'),(42,'directories')]
    assert stat.S_IMODE(J.ROOT.stat().st_mode)==stat.S_IMODE((J.ROOT/'releases').stat().st_mode)==0o750
    assert {str(p.relative_to(J.TOOLS)) for p in J.TOOLS.rglob('*') if p.is_file()}==set(host['files'])
    assert not (J.ROOT/'current').exists() and not any((J.ROOT/'releases').iterdir())
    before={str(p):p.read_bytes() for p in J.TOOLS.rglob('*') if p.is_file()}
    J.CHANGED=False;assert J.setup()['tools']=='REUSED' and not J.CHANGED
    assert before=={str(p):p.read_bytes() for p in J.TOOLS.rglob('*') if p.is_file()}

@pytest.mark.parametrize('kind',['hash','candidate','permission','config','manifest'])
def test_preflight_failures_create_nothing(host,monkeypatch,kind):
    if kind=='hash':J.CONFIG['packet']=base64.b64encode(b'bad').decode()
    if kind=='candidate':monkeypatch.setattr(J,'candidate',lambda:(_ for _ in ()).throw(J.Stop('CANDIDATE_IDENTITY')))
    if kind=='permission':monkeypatch.setattr(J,'access',lambda *a:(_ for _ in ()).throw(J.Stop('CANDIDATE_DIRECTORY_ACCESS')))
    if kind=='config':J.CONFIG['forecast']=b'unapproved'
    if kind=='manifest':
        files=dict(host['files']);files['tools-manifest.json']=b'{}';raw=packet(files);J.PACKET_SHA=J.sha(raw);J.CONFIG={'packet':base64.b64encode(raw).decode()}
    with pytest.raises(J.Stop):J.setup()
    assert not J.CHANGED and not J.ROOT.exists() and not J.TOOLS_PARENT.exists()

@pytest.mark.parametrize('kind',['current','release','symlink','mode','tools_drift','tools_extra'])
def test_conflicts_fail_without_repair_or_overwrite(host,kind):
    J.setup();J.CHANGED=False
    if kind=='current':(J.ROOT/'current').symlink_to('releases/'+'a'*64)
    if kind=='release':(J.ROOT/'releases'/'unexpected').mkdir()
    if kind=='symlink':
        (J.ROOT/'releases').rmdir();(J.ROOT/'releases').symlink_to(host['tmp'])
    if kind=='mode':J.ROOT.chmod(0o777)
    if kind=='tools_drift':(J.TOOLS/'publish.py').write_bytes(b'drift')
    if kind=='tools_extra':(J.TOOLS/'unapproved.py').write_bytes(b'extra')
    before={str(p):p.read_bytes() for p in J.TOOLS.rglob('*') if p.is_file()}
    with pytest.raises(J.Stop):J.setup()
    assert not J.CHANGED and before=={str(p):p.read_bytes() for p in J.TOOLS.rglob('*') if p.is_file()}

@pytest.mark.parametrize('name',['../escape','/etc/escape','extra.py'])
def test_unapproved_archive_members_rejected(host,name):
    files=dict(host['files']);files[name]=b'not allowed';raw=packet(files);J.PACKET_SHA=J.sha(raw)
    with pytest.raises(J.Stop,match='PACKET_INVENTORY'):J.packet(raw)
    assert not J.ROOT.exists()

def test_post_setup_access_failure_retains_partial_without_publishing(host,monkeypatch):
    def access(pid,phase):
        if phase=='directories':raise J.Stop('CANDIDATE_DIRECTORY_ACCESS')
    monkeypatch.setattr(J,'access',access)
    with pytest.raises(J.Stop,match='CANDIDATE_DIRECTORY_ACCESS'):J.setup()
    assert J.CHANGED and J.PHASE=='ACCESS' and J.TOOLS.exists() and J.ROOT.exists()
    assert not (J.ROOT/'current').exists() and not any((J.ROOT/'releases').iterdir())

def test_write_helper_cannot_create_unapproved_path(host):
    with pytest.raises(J.Stop,match='WRITE_SCOPE'):J.create_directory(host['tmp']/'forbidden',0o700,0)
    assert not (host['tmp']/'forbidden').exists()

def test_access_uses_only_trusted_isolated_python_in_service_mount_namespace(monkeypatch):
    calls=[]
    def cmd(argv):calls.append(argv);return b'{"read_traverse":true,"write":false}'
    monkeypatch.setattr(J,'command',cmd);monkeypatch.setattr(J,'candidate',lambda:123)
    J.access(123,'directories');argv=calls[0]
    assert argv[:5]==['/usr/bin/nsenter','--target','123','--mount','--']
    assert argv[5:13]==['/usr/bin/setpriv','--reuid=992','--regid=992','--clear-groups','--no-new-privs','/usr/bin/python3','-I','-S']
    assert argv[13:15]==['-B','-c'] and argv[-1]=='directories'
    assert 'os.getgroups()==[]' in argv[-2] and 'import site' not in argv[-2]
    monkeypatch.setattr(J,'command',lambda a:b'{"read_traverse":true,"write":true}')
    with pytest.raises(J.Stop,match='CANDIDATE_DIRECTORY_ACCESS'):J.access(123,'directories')

def test_subprocess_bounds_and_failure_sanitization(monkeypatch):
    calls=[]
    def bounded(argv,**kw):
        calls.append(kw);return {'returncode':1,'failure':None,'stdout':b'PRIVATE_SENTINEL'}
    monkeypatch.setattr(J,'BASE',{'bounded_run':bounded},raising=False)
    with pytest.raises(J.Stop,match='INSPECTION_COMMAND_FAILED') as e:J.command(['/usr/bin/systemctl'])
    assert 'PRIVATE_SENTINEL' not in str(e.value) and calls==[{'timeout':8,'limit':16384,'grace':5}]

def test_bad_manifest_stops_before_profile_or_ssh(monkeypatch):
    monkeypatch.setattr(R,'namespace',lambda *a:pytest.fail('Unverified source executed'))
    with pytest.raises(ValueError):R.verify('0'*64)

def test_verified_bytes_not_reopened_when_assembling():
    blobs={R.CORE:b'# verified core',R.JOB:b'# verified setup'}
    raw=R.assemble(blobs,b'verified packet');blobs[R.JOB]=b'CHANGED_PRIVATE_SENTINEL'
    assert b'CHANGED_PRIVATE_SENTINEL' not in raw and b'verified setup' in raw

def test_remote_failure_runs_once_and_preserves_sanitized_capture(tmp_path,monkeypatch,capsys):
    (tmp_path/'preflight').mkdir();calls=[]
    def bounded(argv,**kw):
        calls.append((argv,kw));return {'returncode':255,'failure':None,'stdout':b'','stderr':b'PRIVATE_SENTINEL'}
    wrapper={'ssh_argv':lambda p:['/usr/bin/ssh','fixed'],'profile':lambda:{},'PRIVATE':tmp_path,'failure_category':lambda *a:'SSH_FAILURE'}
    monkeypatch.setattr(R,'verify',lambda e:(b'verified',wrapper,{'bounded_run':bounded}))
    monkeypatch.setattr(sys,'argv',['run_first_setup.py','--manifest-sha256','a'*64])
    assert R.main()==1 and len(calls)==1
    argv,kw=calls[0];assert argv[-1]=='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -'
    assert kw=={'input':b'verified','timeout':120,'limit':131072,'grace':5}
    assert 'PRIVATE_SENTINEL' not in capsys.readouterr().out

def test_setup_report_cannot_claim_bundle_access_or_publication():
    report={'status':'SETUP_READY','phase':'COMPLETE','changed':True,'tools':'INSTALLED','candidate_directory_access':'PASS','candidate_bundle_access':'UNVERIFIED_NO_BUNDLE','publisher_directory_access':'PASS','active_pointer_absent':True,'publication_performed':False}
    assert R.validate(report,0)==report
    for change in ({'publication_performed':True},{'candidate_bundle_access':'PASS'},{'candidate_directory_access':'UNVERIFIED'},{'changed':1}):
        with pytest.raises(ValueError):R.validate(dict(report,**change),0)

def test_manifest_binds_exact_dependency_closure():
    p=DIR/'FIRST-SETUP-MANIFEST.json'
    manifest=json.loads(p.read_bytes());assert set(manifest['artifacts'])==R.ARTIFACTS
    for name,item in manifest['artifacts'].items():
        raw=(ROOT/name).read_bytes();assert len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256']

@pytest.mark.parametrize('kind',['uid','gid','state','pid'])
def test_candidate_identity_missing_or_drift_fails_closed(monkeypatch,kind):
    values={'User':'powerflow-api','Group':'powerflow-api','ActiveState':'active','SubState':'running','MainPID':'42'}
    status=b'Uid:\t992\t992\t992\t992\nGid:\t992\t992\t992\t992\n'
    if kind=='uid':status=status.replace(b'Uid:\t992',b'Uid:\t0',1)
    if kind=='gid':values['Group']='other'
    if kind=='state':values['ActiveState']='failed'
    if kind=='pid':values['MainPID']='not-a-number'
    monkeypatch.setattr(J,'command',lambda args:'\n'.join(k+'='+v for k,v in values.items()).encode())
    monkeypatch.setattr(J,'read',lambda *a:status)
    with pytest.raises(J.Stop,match='CANDIDATE_IDENTITY'):J.candidate()


def test_changed_executable_dependency_rejected_before_namespace_or_packet(monkeypatch):
    data=b'# approved';artifacts={n:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for n in R.ARTIFACTS}
    manifest={'version':1,'packet_sha256':R.PACKET_SHA,'packet_bytes':6470,'artifacts':artifacts,'payload_sha256':'a'*64}
    raw=json.dumps(manifest).encode()
    def read(path,*args):return raw if path.name=='FIRST-SETUP-MANIFEST.json' else b'# substituted'
    monkeypatch.setattr(R,'read',read);monkeypatch.setattr(R,'namespace',lambda *a:pytest.fail('Changed source executed'))
    with pytest.raises(ValueError,match='artifact_hash'):R.verify(hashlib.sha256(raw).hexdigest())


def test_unexpected_root_group_stops_before_creation(host,monkeypatch):
    monkeypatch.setattr(J.os,'getegid',lambda:992)
    with pytest.raises(J.Stop,match='ROOT_REQUIRED'):J.setup()
    assert not J.CHANGED and not J.ROOT.exists() and not J.TOOLS_PARENT.exists()


def test_access_rejects_numeric_booleans_and_missing_evidence(monkeypatch):
    monkeypatch.setattr(J,'candidate',lambda:123)
    for raw in (b'{"read_traverse":1,"write":0}',b'{"read_traverse":true}',b'{"read_traverse":false,"write":false}'):
        monkeypatch.setattr(J,'command',lambda args,raw=raw:raw)
        with pytest.raises(J.Stop,match='CANDIDATE_DIRECTORY_ACCESS'):J.access(123,'directories')


def test_report_write_failure_is_sanitized(tmp_path,monkeypatch,capsys):
    (tmp_path/'preflight').mkdir()
    report={'status':'SETUP_READY','phase':'COMPLETE','changed':True,'tools':'INSTALLED','candidate_directory_access':'PASS','candidate_bundle_access':'UNVERIFIED_NO_BUNDLE','publisher_directory_access':'PASS','active_pointer_absent':True,'publication_performed':False}
    w={'profile':lambda:{},'ssh_argv':lambda p:['/usr/bin/ssh','fixed'],'PRIVATE':tmp_path}
    b={'bounded_run':lambda *a,**kw:{'returncode':0,'failure':None,'stdout':json.dumps(report).encode(),'stderr':b''}}
    monkeypatch.setattr(R,'verify',lambda e:(b'verified',w,b))
    original=R.os.open
    def no_report(path,*args,**kw):
        if Path(path).name=='sanitized.json':raise PermissionError('PRIVATE_SENTINEL')
        return original(path,*args,**kw)
    monkeypatch.setattr(R.os,'open',no_report);monkeypatch.setattr(sys,'argv',['run_first_setup.py','--manifest-sha256','a'*64])
    assert R.main()==1
    text=capsys.readouterr().out;assert 'PRIVATE_SENTINEL' not in text and 'REPORT_WRITE_FAILURE' in text
