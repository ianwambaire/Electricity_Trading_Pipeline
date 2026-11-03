"""Local synthetic deployment state only; no SSH, sudo, HTTP or root operations."""
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
FOLDER=ROOT/'deploy/staging/forecast-publication/automation-deployment'
def load():
    ns={'__name__':'local_job','CONFIG':{'transaction':'a'*32},'BASE':{},'GUARD':{}}
    exec(compile((FOLDER/'job.py').read_bytes(),'<local-job>','exec'),ns);return ns

def test_activation_changes_only_one_deployment_env_value():
    job=load();old={'env':{'UNCHANGED':'fixture'},'other':123};d={'job_variables':old}
    previous,new=job['variables'](d)
    assert previous==old and new=={'env':{'UNCHANGED':'fixture','POWERFLOW_AUTO_PUBLICATION_ENABLED':'true'},'other':123}
    assert d['job_variables']==old
    with pytest.raises(job['Stop']):job['variables']({'job_variables':{'env':{'POWERFLOW_AUTO_PUBLICATION_ENABLED':'false'}}})
    with pytest.raises(job['Stop']):job['variables']({'job_variables':{'env':[]}})

@pytest.fixture
def deployment(tmp_path,monkeypatch):
    j=load();prod=tmp_path/'production';(prod/'src/shared').mkdir(parents=True);pipeline=prod/'src/scheduled_pipeline.py';pipeline.write_bytes(b'original')
    (tmp_path/'etc').mkdir();(tmp_path/'sbin').mkdir();(tmp_path/'control').mkdir();(prod/'.venv-prod/lib/python3.14/site-packages/prefect/workers').mkdir(parents=True)
    (prod/'.venv-prod/lib/python3.14/site-packages/prefect/workers/base.py').write_bytes(b'worker')
    j.update(PRODUCTION=prod,TOOLS=tmp_path/'tools',LAUNCHER=tmp_path/'sbin/launcher',RULE=tmp_path/'etc/rule',CONTROL=tmp_path/'control/transaction')
    data={'pipeline':b'new-pipeline','delivery':b'delivery','launcher':b'launcher','sudoers':b'rule','tools/automatic.py':b'automatic'}
    j['CONFIG'].update(files={k:{'base64':base64.b64encode(v).decode(),'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()} for k,v in data.items()},installed_tools={'automatic.py':hashlib.sha256(b'automatic').hexdigest()},pipeline_before=hashlib.sha256(b'original').hexdigest(),worker_base_sha256=hashlib.sha256(b'worker').hexdigest())
    d={'entrypoint':'src/scheduled_pipeline.py:powerflow_entsoe_pipeline','work_pool_name':'electricity-pool','job_variables':{},'schedules':[]};calls=[]
    j['fresh']=lambda:('stable-production',{'available_bytes':999999999})
    j['original_tools']=lambda:None;j['system_binaries']=lambda:None;j['safe']=lambda *a:None;j['fsync']=lambda *a:None
    j['BASE']={'read':lambda p,limit:Path(p).read_bytes(),'api':lambda *a:[],'services':lambda:{'powerflow-prefect-worker.service':{'User':'ec2-user','Group':'ec2-user','NoNewPrivileges':'no','WorkingDirectory':str(prod)}}}
    j['GUARD']={'production':lambda:'stable-production'}
    j['deployment']=lambda:copy.deepcopy(d)
    j['pool_metadata']=lambda:{'type':'process','is_paused':False,'base_job_template':{'variables':{'properties':{'env':{}}},'job_configuration':{'env':'{{ env }}'}}}
    def patch(value):calls.append('patch');d['job_variables']=copy.deepcopy(value)
    j['patch']=patch;j['process']=lambda argv,**kw:calls.append('visudo') or b''
    j['pwd']=type('Pwd',(),{'getpwnam':lambda self,n:type('User',(),{'pw_uid':1000,'pw_gid':1000})()})()
    # Model trusted OS metadata locally; the real preflight checks actual UID/GID/mode.
    old_snapshot=j['snapshot']
    def snapshot(p):
        s=old_snapshot(p)
        if s:s.update(uid=1000,gid=1000)
        return s
    j['snapshot']=snapshot
    def mkdir(p):p.mkdir(mode=0o700);j['CHANGED']=True
    j['create_dir']=mkdir
    def write(p,raw,mode=0o600,owner=0,group=0,exclusive=False):
        if exclusive and p.exists():raise j['Stop']('PATH_CONFLICT')
        p.write_bytes(raw);p.chmod(mode)
    j['write']=write
    def installed(files):
        for key,p in [('pipeline',pipeline),('delivery',prod/'src/shared/forecast_delivery.py'),('launcher',j['LAUNCHER']),('sudoers',j['RULE'])]:assert p.read_bytes()==files[key]
    j['verify_installed']=installed
    # No OS binary metadata modification is performed; mask those two checks only.
    real_need=j['need']
    j['need']=lambda v,c:None if c=='SYSTEM_BINARY' else real_need(v,c)
    return j,d,calls,prod,data

def test_apply_and_independent_rollback_restore_exact_source_and_env(deployment):
    j,d,calls,prod,data=deployment
    report=j['apply']();assert report['status']=='APPLIED' and report['publication_executed'] is False
    record=json.loads((j['CONTROL']/'record.json').read_bytes());assert record['status']=='APPLIED'
    assert base64.b64decode(record['pipeline']['raw'])==b'original'
    assert d['job_variables']=={'env':{'POWERFLOW_AUTO_PUBLICATION_ENABLED':'true'}}
    j['rollback']()
    assert (prod/'src/scheduled_pipeline.py').read_bytes()==b'original' and d['job_variables']=={}
    assert not j['RULE'].exists() and not j['LAUNCHER'].exists() and not (prod/'src/shared/forecast_delivery.py').exists()
    assert j['TOOLS'].exists() # inactive root-private evidence retained

@pytest.mark.parametrize('kind',['active','capacity','source','transaction','launcher','config','pool','worker'])
def test_preflight_failure_makes_no_remote_equivalent_mutation(deployment,kind):
    j,d,calls,prod,data=deployment
    if kind in ['active','capacity']:j['fresh']=lambda:(_ for _ in ()).throw(j['Stop'](kind))
    if kind=='source':(prod/'src/scheduled_pipeline.py').write_bytes(b'drift')
    if kind=='transaction':j['CONTROL'].mkdir()
    if kind=='launcher':j['LAUNCHER'].write_bytes(b'existing')
    if kind=='config':d['job_variables']={'env':{'POWERFLOW_AUTO_PUBLICATION_ENABLED':'true'}}
    if kind=='pool':j['pool_metadata']=lambda:{'type':'docker'}
    if kind=='worker':j['CONFIG']['worker_base_sha256']='0'*64
    before={str(p):p.read_bytes() for p in prod.rglob('*') if p.is_file()}
    with pytest.raises(j['Stop']):j['apply']()
    assert before=={str(p):p.read_bytes() for p in prod.rglob('*') if p.is_file()}
    assert j['CHANGED'] is False and not calls and not j['RULE'].exists()

@pytest.mark.parametrize('stage',['tools','source','rule','activation','acceptance'])
def test_partial_install_has_usable_record_and_never_implicitly_rolls_back(deployment,stage):
    j,d,calls,prod,data=deployment;original=j['write'];realpatch=j['patch']
    def write(p,*a,**kw):
        fail=stage=='tools' and p.name=='automatic.py' or stage=='source' and p.name=='scheduled_pipeline.py' or stage=='rule' and p==j['RULE']
        if fail:raise OSError('synthetic')
        return original(p,*a,**kw)
    j['write']=write
    if stage=='activation':j['patch']=lambda v:(_ for _ in ()).throw(OSError())
    if stage=='acceptance':j['GUARD']['production']=lambda:'drift'
    with pytest.raises(Exception):j['apply']()
    record=json.loads((j['CONTROL']/'record.json').read_bytes());assert record['status']=='PREPARED' and j['CHANGED']
    assert base64.b64decode(record['pipeline']['raw'])==b'original'
    assert 'ROLLED_BACK' not in record.values()
    j['write']=original;j['patch']=realpatch;j['GUARD']['production']=lambda:'stable-production'
    assert j['rollback']()['status']=='ROLLED_BACK'


def test_rollback_rejects_drift_before_disabling_or_restoring(deployment):
    j,d,calls,prod,data=deployment;j['apply']();(prod/'src/scheduled_pipeline.py').write_bytes(b'unexpected')
    calls.clear()
    with pytest.raises(j['Stop'],match='ROLLBACK_FILE_DRIFT'):j['rollback']()
    assert not calls and (prod/'src/scheduled_pipeline.py').read_bytes()==b'unexpected'


def test_root_rule_is_digest_bound_uuid_only():
    text=(FOLDER/'sudoers.rule').read_text()
    assert 'sha256:'+hashlib.sha256((FOLDER.parent/'powerflow-publish-next24').read_bytes()).hexdigest() in text
    assert 'NOPASSWD: NOSETENV: sha256:' in text and '^--receipt ' in text and ' --flow-run ' in text and text.rstrip().endswith('$')
    assert '/bin/sh' not in text and '/usr/bin/python' not in text
    regex=text.split('/usr/local/sbin/powerflow-publish-next24 ',1)[1].strip()
    import re
    value='11111111-1111-4111-8111-111111111111'
    assert re.fullmatch(regex,'--receipt '+value+' --flow-run '+value)
    for argument in ['--receipt ../../secret --flow-run '+value,'--receipt '+value+' --flow-run '+value+' --command sh','--receipt '+value+';id --flow-run '+value]:assert not re.fullmatch(regex,argument)


def test_manifest_payload_closure_and_post_verification_retention(monkeypatch):
    spec=importlib.util.spec_from_file_location('automation_runner',FOLDER/'run.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    original=runner.namespace
    def namespace(raw,name,path=None,extra=None):
        if name=='wrapper':return {'profile':lambda:{'verified':True}}
        return original(raw,name,path,extra)
    monkeypatch.setattr(runner,'namespace',namespace)
    manifest=(FOLDER/'MANIFEST.json').read_bytes();digest=hashlib.sha256(manifest).hexdigest()
    for action in ['apply','rollback']:
        payload,_,_,transaction=runner.verify(digest,action)
        m=json.loads(manifest);assert hashlib.sha256(payload).hexdigest()==m['payload_sha256'][action]
        assert transaction==m['config']['transaction']
    real_read=runner.read
    monkeypatch.setattr(runner,'read',lambda path,*a:real_read(path,*a)+b'altered' if path==ROOT/runner.JOB else real_read(path,*a))
    with pytest.raises(ValueError,match='artifact_hash'):runner.verify(digest,'apply')
    # Previously returned payload is immutable and unaffected by subsequent reads.
    assert hashlib.sha256(payload).hexdigest()==m['payload_sha256']['rollback']
    with pytest.raises(ValueError,match='manifest_hash'):runner.verify('0'*64,'apply')


def test_preserved_original_setup_and_archive_bindings():
    assert hashlib.sha256((ROOT/'deploy/staging/forecast-publication/FIRST-SETUP-MANIFEST.json').read_bytes()).hexdigest()=='274bf50c731bc5ff074d8dae28b87126055e70db663081b4ee3d68165d9217b7'
    meta=json.loads((FOLDER/'MANIFEST.json').read_bytes())
    assert meta['config']['original_packet']=='faeec014b4cde838fcffb3c285eef1995f38547d443162e529fa90ec7209a6b3'


def test_sudoers_parse_failure_is_preflight_and_has_no_write(deployment):
    j,d,calls,prod,data=deployment
    def reject(*a,**kw):raise j['Stop']('SUDOERS_SYNTAX')
    j['process']=reject
    with pytest.raises(j['Stop'],match='SUDOERS_SYNTAX'):j['apply']()
    assert not j['CONTROL'].exists() and j['CHANGED'] is False
    assert (prod/'src/scheduled_pipeline.py').read_bytes()==b'original'


def test_custom_process_command_is_not_silently_activated(deployment):
    j,d,calls,prod,data=deployment;d['job_variables']={'command':'unreviewed command'}
    with pytest.raises(j['Stop'],match='PROCESS_COMMAND_OR_DIRECTORY'):j['apply']()
    assert not j['CONTROL'].exists() and j['CHANGED'] is False


def test_rollback_refuses_symlink_before_any_write(deployment,tmp_path):
    j,d,calls,prod,data=deployment;j['apply']()
    other=tmp_path/'unrelated';other.write_bytes(b'keep')
    j['RULE'].unlink();j['RULE'].symlink_to(other);calls.clear()
    with pytest.raises(j['Stop'],match='FILE_TYPE'):j['rollback']()
    assert other.read_bytes()==b'keep' and not calls


def test_tools_path_conflict_is_not_repaired(deployment,tmp_path):
    j,d,calls,prod,data=deployment;target=tmp_path/'unrelated';target.mkdir();j['TOOLS'].symlink_to(target)
    with pytest.raises(j['Stop'],match='PATH_CONFLICT'):j['apply']()
    assert j['CHANGED'] is False and not list(target.iterdir())


def test_existing_guard_failure_codes_remain_specific_and_sanitized():
    j=load()
    class GuardStop(ValueError):pass
    j['GUARD']['Stop']=GuardStop
    assert j['cause'](GuardStop('RAM_GATE'))=='RAM_GATE'
    assert j['cause'](GuardStop('PIPELINE_OR_WINDOW_GATE'))=='PIPELINE_OR_WINDOW_GATE'
    assert j['cause'](GuardStop('private diagnostic /path'))=='DEPLOYMENT_CHECK_FAILED'
    assert j['cause'](OSError('private diagnostic'))=='DEPLOYMENT_CHECK_FAILED'
