"""Continuation regressions: temporary files only; no SSH/Prefect/root writes."""
import ast
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
import test_automatic_publication_deployment as previous
ROOT=Path(__file__).parents[1]
FOLDER=ROOT/'deploy/staging/forecast-publication/automation-continuation'
def load():
    ns={'__name__':'local_continuation','CONFIG':{'transaction':'b'*32},'BASE':{},'GUARD':{}}
    exec(compile((FOLDER/'job.py').read_bytes(),'<local-continuation>','exec'),ns);return ns

@pytest.fixture
def continuation(tmp_path,monkeypatch):
    monkeypatch.setattr(previous,'load',load)
    j,d,calls,prod,data=previous.deployment.__wrapped__(tmp_path,monkeypatch)
    # Only privileged identity is remapped: mkdir/open/fstat/fchown/chmod/fsync/
    # rmdir below use real native OS calls as the local fixture owner.
    j['PRODUCER_UID']=os.getuid();j['PRODUCER_GID']=os.getgid();j['ROOT_UID']=os.getuid();j['ROOT_GID']=os.getgid()
    j['CONFIG'].update(original_transaction='73080d9ca8fd4c3f9f143fd4ae84a123',original_manifest_sha256='48a17404aa82c2fc16ab961311a7007224e1ee7016ecbc6ca5de04bed8aed389')
    j['original_transaction']=lambda dep:None
    tools=j['TOOLS'];(tools/'shared').mkdir(parents=True);tools.chmod(0o700);(tools/'shared').chmod(0o700)
    # Six retained files, distinct from the original reviewed manual tools.
    for name in ['automatic.py','prepare.py','publish.py','shared/__init__.py','shared/forecast_publication.py']:
        raw=('retained-'+name).encode();(tools/name).write_bytes(raw);(tools/name).chmod(0o600)
        j['CONFIG']['installed_tools'][name]=hashlib.sha256(raw).hexdigest();data['tools/'+name]=raw
    j['CONFIG']['installed_tools'].pop('automatic.py');j['CONFIG']['installed_tools']['automatic.py']=hashlib.sha256(data['tools/automatic.py']).hexdigest()
    (tools/'automation-manifest.json').write_bytes(json.dumps(j['CONFIG']['installed_tools'],sort_keys=True).encode());(tools/'automation-manifest.json').chmod(0o600)
    # The synthetic payloads mirror the retained bytes; nothing executable is run.
    j['CONFIG']['files']={k:{'base64':base64.b64encode(v).decode(),'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()} for k,v in data.items()}
    return j,d,calls,prod,data

def test_missing_shared_created_journalled_and_empty_directory_removed(continuation):
    j,d,calls,prod,data=continuation;(prod/'src/shared').rmdir()
    before={str(p):p.read_bytes() for p in j['TOOLS'].rglob('*') if p.is_file()}
    out=j['apply']();assert out['shared_directory']=='CREATED' and out['retained_tools']=='VERIFIED_REUSED'
    st=(prod/'src/shared').stat();assert st.st_uid==os.getuid() and st.st_gid==os.getgid() and st.st_mode&0o777==0o755
    record=json.loads((j['CONTROL']/'record.json').read_bytes());assert record['shared_before'] is None and record['shared_created']['identity']=={'dev':st.st_dev,'ino':st.st_ino}
    assert j['rollback']()['shared_directory']=='REMOVED_EMPTY_CREATED' and not (prod/'src/shared').exists()
    assert before=={str(p):p.read_bytes() for p in j['TOOLS'].rglob('*') if p.is_file()}
    assert (prod/'src/scheduled_pipeline.py').read_bytes()==b'original' and d['job_variables']=={}


def test_preexisting_shared_directory_is_never_removed(continuation):
    j,d,calls,prod,data=continuation;shared=prod/'src/shared';original=shared.stat().st_ino;(shared/'unrelated.py').write_bytes(b'keep')
    assert j['apply']()['shared_directory']=='VERIFIED_PREEXISTING'
    assert j['rollback']()['shared_directory']=='PRESERVED_PREEXISTING'
    assert shared.stat().st_ino==original and (shared/'unrelated.py').read_bytes()==b'keep'

@pytest.mark.parametrize('kind',['shared_symlink','shared_file','src_symlink','src_mode','shared_mode','owner'])
def test_invalid_directory_state_aborts_before_any_mutation(continuation,tmp_path,kind):
    j,d,calls,prod,data=continuation;shared=prod/'src/shared'
    if kind in ['shared_symlink','shared_file']:shared.rmdir()
    if kind=='shared_symlink':shared.symlink_to(tmp_path)
    if kind=='shared_file':shared.write_bytes(b'keep')
    if kind=='src_symlink':shared.rmdir();(prod/'src/scheduled_pipeline.py').unlink();(prod/'src').rmdir();(prod/'src').symlink_to(tmp_path)
    if kind=='src_mode':(prod/'src').chmod(0o750)
    if kind=='shared_mode':shared.chmod(0o750)
    if kind=='owner':j['PRODUCER_UID']=999999
    with pytest.raises(j['Stop']):j['apply']()
    assert not j['CONTROL'].exists() and j['CHANGED'] is False and d['job_variables']=={}

@pytest.mark.parametrize('kind',['hash','extra','missing','symlink','mode','owner'])
def test_retained_tools_drift_aborts_before_writes(continuation,tmp_path,kind):
    j,d,calls,prod,data=continuation;tools=j['TOOLS'];p=tools/'prepare.py'
    if kind=='hash':p.write_bytes(b'drift')
    if kind=='extra':(tools/'unexpected').write_bytes(b'drift')
    if kind=='missing':p.unlink()
    if kind=='symlink':p.unlink();p.symlink_to(tmp_path/'outside')
    if kind=='mode':p.chmod(0o644)
    if kind=='owner':j['ROOT_UID']=999999
    with pytest.raises(j['Stop']):j['apply']()
    assert not j['CONTROL'].exists() and not j['LAUNCHER'].exists() and d['job_variables']=={} and not j['CHANGED']

@pytest.mark.parametrize('target',['launcher','delivery','pipeline','sudoers'])
def test_install_failure_is_specific_and_rollback_independent(continuation,target):
    j,d,calls,prod,data=continuation;(prod/'src/shared').rmdir();original=j['write']
    path={'launcher':j['LAUNCHER'],'delivery':prod/'src/shared/forecast_delivery.py','pipeline':prod/'src/scheduled_pipeline.py','sudoers':j['RULE']}[target]
    def fail(p,*args,**kwargs):
        if p==path:raise PermissionError(13,'PRIVATE_SENTINEL')
        return original(p,*args,**kwargs)
    j['write']=fail
    with pytest.raises(PermissionError) as caught:j['apply']()
    result=j['failure'](caught.value)
    assert result['operation']=='INSTALL_'+{'launcher':'LAUNCHER','delivery':'DELIVERY','pipeline':'PIPELINE','sudoers':'SUDOERS'}[target]
    assert result['error_category']=='PERMISSION_DENIED' and result['errno']==13 and 'PRIVATE_SENTINEL' not in json.dumps(result)
    assert 'PRIVATE_SENTINEL' in next(j['CONTROL'].glob('failure-*.private.json')).read_text()
    assert d['job_variables']=={} and json.loads((j['CONTROL']/'record.json').read_text())['status']=='PREPARED'
    j['write']=original
    assert j['rollback']()['shared_directory']=='REMOVED_EMPTY_CREATED'


def test_nonempty_created_directory_is_retained(continuation):
    j,d,calls,prod,data=continuation;(prod/'src/shared').rmdir();j['apply']();(prod/'src/shared/keep.py').write_bytes(b'keep')
    out=j['rollback']();assert out['shared_directory']=='RETAINED_NONEMPTY' and (prod/'src/shared/keep.py').read_bytes()==b'keep'
    assert not (prod/'src/shared/forecast_delivery.py').exists() and d['job_variables']=={}


def test_directory_drift_blocks_rollback_before_disabling(continuation):
    j,d,calls,prod,data=continuation;(prod/'src/shared').rmdir();j['apply']();(prod/'src/shared').chmod(0o750);calls.clear()
    with pytest.raises(j['Stop'],match='SHARED_DIRECTORY_DRIFT'):j['rollback']()
    assert not calls and d['job_variables']['env'][j['FLAG']]=='true'


def test_failed_creation_after_mkdir_keeps_inode_record_for_rollback(continuation,monkeypatch):
    j,d,calls,prod,data=continuation;(prod/'src/shared').rmdir();real=j['os'].fchown
    # Only creation invokes the native fchown; installation writer is a fixture.
    def fail(*a):raise PermissionError(13,'synthetic metadata failure')
    monkeypatch.setattr(j['os'],'fchown',fail)
    with pytest.raises(PermissionError):j['apply']()
    record=json.loads((j['CONTROL']/'record.json').read_text());assert record['shared_created']['identity']['ino']==(prod/'src/shared').stat().st_ino
    monkeypatch.setattr(j['os'],'fchown',real)
    assert j['rollback']()['shared_directory']=='REMOVED_EMPTY_CREATED'


def test_unrecorded_directory_cannot_be_claimed_for_cleanup(continuation):
    j,d,calls,prod,data=continuation;record={'src_directory':j['directory_info'](prod/'src'),'shared_before':None,'shared_created':None}
    with pytest.raises(j['Stop'],match='UNRECORDED_SHARED_DIRECTORY'):j['remove_shared'](record)
    assert (prod/'src/shared').exists()


def test_retained_root_symlink_is_not_followed(continuation,tmp_path):
    j,d,calls,prod,data=continuation
    original=j['TOOLS'];moved=tmp_path/'moved';original.rename(moved);original.symlink_to(moved)
    # The real no-follow safety guard, narrowed to the fixture subtree.
    def safe(p,*a):
        while p!=tmp_path:
            assert tmp_path in p.parents
            j['need'](not p.is_symlink(),'UNSAFE_PATH');p=p.parent
    j['safe']=safe
    with pytest.raises(j['Stop'],match='UNSAFE_PATH'):j['apply']()
    assert not j['CONTROL'].exists()


def test_installed_delivery_imports_as_namespace_package_without_init(tmp_path):
    # Reproduce the production src/shared layout; importing this stdlib-only
    # module in an isolated local interpreter does not invoke sudo or publish.
    shared=tmp_path/'src/shared';shared.mkdir(parents=True)
    (shared/'forecast_delivery.py').write_bytes((ROOT/'src/shared/forecast_delivery.py').read_bytes())
    r=subprocess.run([sys.executable,'-I','-S','-B','-c',"import sys;sys.path.insert(0,sys.argv[1]);import shared.forecast_delivery as m;assert m.HELPER=='/usr/local/sbin/powerflow-publish-next24';print('NAMESPACE_IMPORT_OK')",str(tmp_path/'src')],capture_output=True,timeout=8)
    assert r.returncode==0 and r.stdout==b'NAMESPACE_IMPORT_OK\n'


def test_new_manifest_payloads_and_original_preservation(monkeypatch):
    spec=importlib.util.spec_from_file_location('continuation_runner',FOLDER/'run.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
    real=r.namespace
    monkeypatch.setattr(r,'namespace',lambda raw,name,path=None,extra=None:{'profile':lambda:{}} if name=='wrapper' else real(raw,name,path,extra))
    raw=(FOLDER/'MANIFEST.json').read_bytes();digest=hashlib.sha256(raw).hexdigest();m=json.loads(raw)
    assert m['config']['transaction']!=r.ORIGINAL_TRANSACTION
    for action in ['apply','rollback']:
        payload,_,_,transaction=r.verify(digest,action)
        assert hashlib.sha256(payload).hexdigest()==m['payload_sha256'][action] and transaction==m['config']['transaction']
    assert hashlib.sha256((ROOT/r.ORIGINAL_MANIFEST).read_bytes()).hexdigest()==r.ORIGINAL_SHA
    realread=r.read
    monkeypatch.setattr(r,'read',lambda p,*a:realread(p,*a)+b'changed' if p==ROOT/r.JOB else realread(p,*a))
    with pytest.raises(ValueError,match='artifact_hash'):r.verify(digest,'apply')


def test_continuation_never_installs_retained_tool_bytes():
    tree=ast.parse((FOLDER/'job.py').read_bytes());apply=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='apply')
    text=ast.unparse(apply)
    assert 'create_dir(TOOLS)' not in text and "files['tools/'" not in text
    assert 'retained_tools' in text and 'create_shared' in text


def test_completed_creation_does_not_accept_earlier_intermediate_mode(continuation):
    j,d,calls,prod,data=continuation;(prod/'src/shared').rmdir();j['apply']();(prod/'src/shared').chmod(0o700);calls.clear()
    with pytest.raises(j['Stop'],match='SHARED_DIRECTORY_DRIFT'):j['rollback']()
    assert not calls and d['job_variables']['env'][j['FLAG']]=='true'


def test_replacement_directory_inode_cannot_be_removed(continuation,tmp_path):
    j,d,calls,prod,data=continuation;(prod/'src/shared').rmdir();j['apply']()
    (prod/'src/shared').rename(tmp_path/'original-created-directory');(prod/'src/shared').mkdir(mode=0o755);calls.clear()
    with pytest.raises(j['Stop'],match='SHARED_DIRECTORY_DRIFT'):j['rollback']()
    assert not calls and (prod/'src/shared').exists() and (tmp_path/'original-created-directory/forecast_delivery.py').exists()


def test_failure_evidence_is_never_overwritten(continuation):
    j,d,calls,prod,data=continuation;j['apply']()
    j['ACTION']='apply';j['failure'](PermissionError(13,'first private error'))
    first=next(j['CONTROL'].glob('failure-apply-*.private.json'));raw=first.read_bytes()
    j['ACTION']='rollback';j['failure'](OSError(5,'second private error'))
    assert first.read_bytes()==raw and len(list(j['CONTROL'].glob('failure-*.private.json')))==2
