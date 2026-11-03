"""Local fixtures only. No SSH, root writes, service or cloud requests."""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).parents[1]
FOLDER=ROOT/'deploy/staging/forecast-publication/automation-install-diagnostic'
def load(name):
    spec=importlib.util.spec_from_file_location('install_diagnostic_'+name,FOLDER/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

@pytest.fixture(autouse=True)
def restore_process_umask():
    original=os.umask(0o077);os.umask(original)
    try:yield
    finally:os.umask(original)

@pytest.fixture
def fixture(tmp_path,monkeypatch):
    payload=load('inspect');runner=load('run');monkeypatch.setattr(payload,'OWNER',os.getuid());monkeypatch.setattr(payload,'GROUP',os.getgid())
    prod=tmp_path/'production';(prod/'src/shared').mkdir(parents=True)
    tools=tmp_path/'tools';(tools/'shared').mkdir(parents=True)
    tools.chmod(0o700);(tools/'shared').chmod(0o700)
    names=['automatic.py','prepare.py','publish.py','shared/__init__.py','shared/forecast_publication.py','automation-manifest.json'];expected={}
    for name in names:
        raw=('synthetic-code-'+name).encode();p=tools/name;p.write_bytes(raw);p.chmod(0o600);expected[name]=hashlib.sha256(raw).hexdigest()
    config={'transaction':runner.TRANSACTION,'original_manifest_sha256':runner.ORIGINAL_SHA,'production_parent':str(prod/'src'),'tools_root':str(tools),'expected_files':expected,'pipeline_uid':os.getuid(),'pipeline_gid':os.getgid()}
    return payload,runner,config,prod,tools

def test_complete_metadata_and_code_inventory(fixture):
    p,r,c,prod,tools=fixture;out=p.inspect(c)
    assert out['status']=='OBSERVED' and out['tools']['state']=='MATCH'
    assert out['production_shared']['primary_group_posix_read_traverse'] is True
    assert out['production_shared']['effective_pipeline_access']=='UNVERIFIED'
    assert set(out['tools']['files'])==set(c['expected_files'])|{'shared/'}
    assert r.validate(out,c,0)==out
    assert out['historical_cause']=='UNVERIFIED' and out['remote_mutations'] is False

def test_missing_shared_reports_only_current_support(fixture):
    p,r,c,prod,tools=fixture;(prod/'src/shared').rmdir();out=p.inspect(c)
    assert out['production_shared']=={'exists':False}
    assert out['interpretation']=='CONSISTENT_WITH_REPRODUCED_MISSING_PARENT' and out['historical_cause']=='UNVERIFIED'
    r.validate(out,c,0)

@pytest.mark.parametrize('which',['shared','parent','ancestor','tool_file','tool_directory'])
def test_symlinks_never_followed(fixture,tmp_path,which):
    p,r,c,prod,tools=fixture;target=tmp_path/'unrelated';target.mkdir();(target/'secret').write_text('never disclose')
    path={'shared':prod/'src/shared','parent':prod/'src','ancestor':prod,'tool_file':tools/'prepare.py','tool_directory':tools/'shared'}[which]
    if path.is_dir():
        if which=='parent':(path/'shared').rmdir()
        elif which=='ancestor':(path/'src/shared').rmdir();(path/'src').rmdir()
        elif which=='tool_directory':
            for f in path.iterdir():f.unlink()
        path.rmdir()
    else:path.unlink()
    path.symlink_to(target);out=p.inspect(c)
    assert out['status']=='UNVERIFIED' and out['cause'] in {'UNSAFE_ANCESTOR','SYMLINK_REJECTED'}
    assert 'never disclose' not in json.dumps(out);r.validate(out,c,1)

@pytest.mark.parametrize('suffix',['/../outside','/./shared'])
def test_traversal_rejected_before_unapproved_access(fixture,suffix):
    p,r,c,prod,tools=fixture;c['production_parent']+=suffix;out=p.inspect(c)
    assert out['status']=='UNVERIFIED' and out['cause']=='PATH_SCOPE'

@pytest.mark.parametrize('kind',['missing_root','missing_file','hash','mode','owner','hard_link','unexpected','oversized','too_many'])
def test_incomplete_or_untrusted_tools_fail_closed(fixture,monkeypatch,tmp_path,kind):
    p,r,c,prod,tools=fixture
    if kind=='missing_root':c['tools_root']=str(tmp_path/'absent')
    if kind=='missing_file':(tools/'prepare.py').unlink()
    if kind=='hash':(tools/'prepare.py').write_bytes(b'wrong bytes')
    if kind=='mode':(tools/'prepare.py').chmod(0o644)
    if kind=='owner':monkeypatch.setattr(p,'OWNER',999999)
    if kind=='hard_link':os.link(tools/'prepare.py',tmp_path/'hardlink')
    if kind=='unexpected':(tools/'secret-name').write_text('private-data')
    if kind=='oversized':(tools/'prepare.py').write_bytes(b'a'*200001)
    if kind=='too_many':
        for i in range(25):(tools/str(i)).write_bytes(b'')
    out=p.inspect(c)
    if kind in ['missing_root','missing_file']:
        assert out['tools']['state'] in {'MISSING','INCOMPLETE'} and out['status']=='OBSERVED'
    else:assert out['status'] in {'FINDINGS','UNVERIFIED'}
    if kind in ['mode','owner','hard_link']:
        record=out['tools']['files']['prepare.py'];assert 'sha256' not in record and record['hash_match'] is None
    assert 'private-data' not in json.dumps(out) and 'secret-name' not in json.dumps(out)
    r.validate(out,c,0 if out['status']=='OBSERVED' else 1)

def test_read_permission_failure_is_sanitized(fixture,monkeypatch):
    p,r,c,prod,tools=fixture
    def blocked(*a):raise PermissionError('private path and credential')
    monkeypatch.setattr(p,'anchor',blocked);out=p.inspect(c)
    assert out['cause']=='PERMISSION_DENIED' and 'credential' not in json.dumps(out)
    r.validate(out,c,1)

@pytest.mark.parametrize('bad',['oversized','extra','fake_success','secret_cause','wrong_transaction'])
def test_output_contract_rejects_unexpected_or_sensitive_fields(fixture,bad):
    p,r,c,prod,tools=fixture;out=p.inspect(c)
    if bad=='oversized':out['private']='x'*17000
    if bad=='extra':out['secret']='never print'
    if bad=='fake_success':out['tools']['files'].pop('prepare.py')
    if bad=='secret_cause':out['cause']='private error detail'
    if bad=='wrong_transaction':out['transaction']='b'*32
    with pytest.raises(ValueError):r.validate(out,c,0)

def test_original_bindings_and_payload_retention(monkeypatch):
    r=load('run');real=r.namespace
    monkeypatch.setattr(r,'namespace',lambda raw,name,path=None:{'profile':lambda:{}} if name=='wrapper' else real(raw,name,path))
    raw=(FOLDER/'MANIFEST.json').read_bytes();digest=hashlib.sha256(raw).hexdigest()
    payload,_,_,config=r.verify(digest);m=json.loads(raw)
    assert hashlib.sha256(payload).hexdigest()==m['remote_payload_sha256']
    assert config['transaction']=='73080d9ca8fd4c3f9f143fd4ae84a123' and config['original_manifest_sha256']==r.ORIGINAL_SHA
    assert set(config['expected_files'])=={'automatic.py','prepare.py','publish.py','shared/__init__.py','shared/forecast_publication.py','automation-manifest.json'}
    saved=bytes(payload);realread=r.read
    def changed(path,*a):return realread(path,*a)+b'changed' if path==ROOT/r.ORIGINAL else realread(path,*a)
    monkeypatch.setattr(r,'read',changed)
    with pytest.raises(ValueError,match='original_manifest_hash'):r.verify(digest)
    assert payload==saved
    with pytest.raises(ValueError,match='diagnostic_manifest_hash'):r.verify('0'*64)


def test_remote_code_has_no_mutation_network_or_application_paths():
    tree=ast.parse((FOLDER/'inspect.py').read_bytes())
    imports={n.names[0].name for n in ast.walk(tree) if isinstance(n,ast.Import)}
    assert imports<={'datetime','hashlib','json','os','stat','sys'}
    forbidden={'write','write_bytes','write_text','mkdir','unlink','rename','replace','chmod','chown','fchmod','fchown','symlink','link','remove','rmdir','system','popen','exec','eval','compile','__import__'}
    for n in ast.walk(tree):
        if isinstance(n,ast.Call):
            name=n.func.id if isinstance(n.func,ast.Name) else n.func.attr if isinstance(n.func,ast.Attribute) else ''
            assert name not in forbidden
        if isinstance(n,ast.Attribute):assert n.attr not in {'O_WRONLY','O_RDWR','O_CREAT','O_TRUNC','O_APPEND'}
    r=load('run');config,_=r.original();payload=r.assemble((FOLDER/'inspect.py').read_bytes(),config)
    assert b'def apply(' not in payload and b'def rollback(' not in payload and b'def publish(' not in payload


@pytest.mark.parametrize('failure,code',[ (None,255),('TIMEOUT',124),('OUTPUT_LIMIT',-15)])
def test_one_attempt_timeout_and_ssh_failure_are_private(fixture,monkeypatch,tmp_path,capsys,failure,code):
    p,r,c,prod,tools=fixture;calls=[];private=tmp_path/'private';(private/'preflight').mkdir(parents=True)
    def bounded(argv,**kwargs):
        calls.append((argv,kwargs));return {'returncode':code,'failure':failure,'stdout':b'','stderr':b'private connection identity'}
    w={'PRIVATE':private,'profile':lambda:{},'ssh_argv':lambda profile:['fixed-ssh','fixed-command'],'failure_category':lambda code,err:'SSH_FAILURE'}
    monkeypatch.setattr(r,'verify',lambda expected:(b'verified-payload',w,{'bounded_run':bounded},c))
    monkeypatch.setattr(sys,'argv',['run','inspect-install-state','--manifest-sha256','a'*64])
    assert r.main()==1;assert len(calls)==1
    argv,kwargs=calls[0];assert argv[-1]=='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 30s /usr/bin/python3 -I -S -B -'
    assert kwargs=={'input':b'verified-payload','timeout':90,'limit':32768,'grace':5}
    out=capsys.readouterr().out;assert 'private connection identity' not in out and (failure or 'SSH_FAILURE') in out
    assert len(list((private/'preflight').glob('*/stderr.private')))==1


def test_hash_failure_never_reaches_transport(monkeypatch,capsys):
    r=load('run')
    def fail(*a):raise ValueError('private details')
    monkeypatch.setattr(r,'verify',fail);monkeypatch.setattr(sys,'argv',['run','inspect-install-state','--manifest-sha256','0'*64])
    assert r.main()==1
    out=capsys.readouterr().out;assert 'LOCAL_VERIFICATION_FAILURE' in out and 'private details' not in out


def test_regular_file_instead_of_shared_is_reported_without_reading_it(fixture):
    p,r,c,prod,tools=fixture;(prod/'src/shared').rmdir();(prod/'src/shared').write_text('unrelated application secret')
    out=p.inspect(c)
    assert out['production_shared']['type']=='REGULAR_FILE' and out['interpretation']=='CURRENT_DESTINATION_TYPE_DEFECT'
    assert out['status']=='FINDINGS' and 'unrelated application secret' not in json.dumps(out)
    r.validate(out,c,1)


def test_primary_owner_permission_denial_does_not_claim_effective_access(fixture):
    p,r,c,prod,tools=fixture;(prod/'src/shared').chmod(0o600);out=p.inspect(c)
    assert out['production_shared']['primary_group_posix_read_traverse'] is False
    assert out['production_shared']['effective_pipeline_access']=='UNVERIFIED'


def test_diagnostic_modified_payload_rejected_before_connection(monkeypatch):
    r=load('run');raw=(FOLDER/'MANIFEST.json').read_bytes();digest=hashlib.sha256(raw).hexdigest();real=r.read
    def changed(path,*args):return real(path,*args)+b'altered' if path==FOLDER/'inspect.py' else real(path,*args)
    monkeypatch.setattr(r,'read',changed)
    with pytest.raises(ValueError,match='diagnostic_artifact_hash'):r.verify(digest)


def test_original_transaction_is_checked_independently(monkeypatch):
    r=load('run');raw=(ROOT/r.ORIGINAL).read_bytes();m=json.loads(raw);m['config']['transaction']='b'*32
    changed=json.dumps(m).encode();real=r.read
    monkeypatch.setattr(r,'ORIGINAL_SHA',hashlib.sha256(changed).hexdigest())
    monkeypatch.setattr(r,'read',lambda path,*args:changed if path==ROOT/r.ORIGINAL else real(path,*args))
    with pytest.raises(ValueError,match='original_transaction'):r.original()


def test_host_key_verification_failure_stops_before_transport(monkeypatch,capsys):
    r=load('run');real=r.namespace;calls=[]
    def namespace(raw,name,path=None):
        if name=='wrapper':
            def profile():calls.append('profile');raise ValueError('host key binding')
            return {'profile':profile}
        return real(raw,name,path)
    monkeypatch.setattr(r,'namespace',namespace)
    digest=hashlib.sha256((FOLDER/'MANIFEST.json').read_bytes()).hexdigest()
    monkeypatch.setattr(sys,'argv',['run','inspect-install-state','--manifest-sha256',digest])
    assert r.main()==1 and calls==['profile']
    assert 'LOCAL_VERIFICATION_FAILURE' in capsys.readouterr().out
