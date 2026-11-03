"""Exact bad-manifest reproduction and diagnostic-only changes; no remote calls."""
import ast
import copy
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
import test_automation_continuation as continuation
ROOT=Path(__file__).parents[1]
FOLDER=ROOT/'deploy/staging/forecast-publication/automation-continuation-v2'
PRIOR=FOLDER.parent/'automation-continuation'
def load():
    ns={'__name__':'local_job','CONFIG':{'transaction':'c'*32},'BASE':{},'GUARD':{}}
    exec(compile((FOLDER/'job.py').read_bytes(),'<v2-local-job>','exec'),ns)
    ns['_real_fresh']=ns['fresh'];ns['_real_original_tools']=ns['original_tools'];return ns
@pytest.fixture
def fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(continuation,'load',load)
    j,d,calls,prod,data=continuation.continuation.__wrapped__(tmp_path,monkeypatch)
    j['CONFIG']['original_packet']=json.loads((PRIOR/'MANIFEST.json').read_bytes())['config']['original_packet']
    return j,d,calls,prod,data

def test_approved_prior_manifest_has_wrong_original_tools_shape():
    raw=(PRIOR/'MANIFEST.json').read_bytes();assert hashlib.sha256(raw).hexdigest()=='62b03da0c79211714777aa0d6f20bf97d12b2b54b6e4ca069fb4ed82ee1778a4'
    m=json.loads(raw);bad=m['config']['original_tools']
    assert next(iter(bad))=='files' and isinstance(bad['files'],dict)
    original=json.loads((FOLDER.parent/'automation-deployment/MANIFEST.json').read_bytes())
    assert bad==original['config']
    assert bad['original_tools']==original['config']['original_tools']


def test_native_reproduction_of_invalid_files_lookup(tmp_path,monkeypatch):
    old=json.loads((PRIOR/'MANIFEST.json').read_bytes());config=old['config']
    ns={'__name__':'old_job','CONFIG':config,'BASE':{},'GUARD':{}}
    exec(compile((PRIOR/'job.py').read_bytes(),'<immutable-prior-job>','exec'),ns)
    manual=tmp_path/'manual';tool=manual/config['original_packet'];(tool/'shared').mkdir(parents=True)
    def mapped(value):return manual if str(value)=='/opt/powerflow/forecast-publication-tools' else Path(value)
    ns['Path']=mapped;ns['safe']=lambda *a:None
    real=Path.stat
    def root_metadata(path,*args,**kwargs):
        if path in [manual,tool,tool/'shared']:return SimpleNamespace(st_mode=0o40700,st_uid=0,st_gid=0)
        return real(path,*args,**kwargs)
    monkeypatch.setattr(Path,'stat',root_metadata)
    with pytest.raises(FileNotFoundError) as caught:ns['original_tools']()
    assert Path(caught.value.filename)==tool/'files' and caught.value.errno==errno.ENOENT
    report=ns['failure'](caught.value)
    assert report=={'error_category':'MISSING_PATH','operation':'PREFLIGHT','path_id':'NONE','errno':2}
    assert list(tool.iterdir())==[tool/'shared']


def test_bad_schema_rejected_before_any_directory_lookup(fixture):
    j,_,_,_,_=fixture;j['CONFIG']['original_tools']=json.loads((PRIOR/'MANIFEST.json').read_bytes())['config']['original_tools']
    with pytest.raises(j['Stop'],match='ORIGINAL_TOOLS_CONFIG_SCOPE'):j['_real_original_tools']()
    assert not j['CHANGED']


def test_correct_tools_use_real_verified_files_and_label_missing_tool(tmp_path,monkeypatch):
    config=json.loads((FOLDER/'MANIFEST.json').read_bytes())['config']
    j={'__name__':'local_job','CONFIG':config,'BASE':{},'GUARD':{}}
    exec(compile((FOLDER/'job.py').read_bytes(),'<v2-native-tools>','exec'),j)
    manual=tmp_path/'manual';root=manual/config['original_packet'];(root/'shared').mkdir(parents=True)
    # Native reads/hashes; only privileged root directory/file metadata is simulated.
    paths={'prepare.py':'deploy/staging/forecast-publication/prepare.py',
           'publish.py':'deploy/staging/forecast-publication/publish.py',
           'shared/__init__.py':'src/shared/__init__.py',
           'shared/forecast_publication.py':'src/shared/forecast_publication.py'}
    # Original installed tools predate the automation contract, so use only local
    # synthetic file bytes with an equally strict per-file hash map here.
    assert set(config['original_tools'])==set(paths)|{'tools-manifest.json'}
    for name in config['original_tools']:
        raw=('synthetic-tool-'+name).encode();(root/name).write_bytes(raw)
        config['original_tools'][name]=hashlib.sha256(raw).hexdigest()
    publication=tmp_path/'publication';(publication/'releases').mkdir(parents=True)
    def mapped(value):
        value=str(value)
        return manual if value=='/opt/powerflow/forecast-publication-tools' else publication if value=='/srv/powerflow/forecast-publications' else publication/'releases' if value=='/srv/powerflow/forecast-publications/releases' else Path(value)
    j['Path']=mapped;j['safe']=lambda *a:None;j['BASE']['read']=lambda p,n:p.read_bytes()
    real=Path.stat
    def metadata(p,*a,**kw):
        st=real(p,*a,**kw)
        if p in [manual,root,root/'shared']:return SimpleNamespace(st_uid=0,st_gid=0,st_mode=0o40700)
        if p in [publication,publication/'releases']:return SimpleNamespace(st_uid=0,st_gid=992,st_mode=0o40750)
        if root in p.parents:return SimpleNamespace(st_uid=0,st_gid=0,st_mode=0o100600)
        return st
    monkeypatch.setattr(Path,'stat',metadata)
    assert j['original_tools']() is None
    (root/'prepare.py').unlink()
    with pytest.raises(FileNotFoundError) as caught:j['step']('VERIFY_ORIGINAL_TOOLS','ORIGINAL_TOOLS',j['original_tools'])
    assert j['failure'](caught.value)['path_id']=='ORIGINAL_TOOL_PREPARE'
    host='/opt/powerflow/forecast-publication-tools/'+config['original_packet']+'/prepare.py'
    # Reset Path only to exercise the source-derived host identifier table.
    j['Path']=Path
    info=j['failure'](FileNotFoundError(2,'private',host))
    assert info['operation']=='VERIFY_ORIGINAL_TOOLS' and info['path_id']=='ORIGINAL_TOOL_PREPARE'
    assert host not in json.dumps(info) and not j['CHANGED']

@pytest.mark.parametrize('candidate,label,stage',[
 ('/proc/meminfo','PROC_MEMORY','capacity'),
 ('/sys/fs/cgroup/system.slice/powerflow-candidate-api.service/memory.max','CGROUP_MEMORY_MAX','runtime'),
 ('/srv/powerflow/published/data/reports/actual_vs_predicted.csv','PUBLISHED_SNAPSHOT_06','production'),
])
def test_initial_host_missing_paths_have_specific_safe_ids(fixture,candidate,label,stage):
    j,d,calls,prod,data=fixture
    def missing(*a):raise FileNotFoundError(2,'private filesystem detail',candidate)
    if stage=='capacity':j['GUARD']['idle_capacity']=missing
    else:
        j['GUARD']['idle_capacity']=lambda *a:{};j['frozen']=lambda:None
        # Exercise the exact nested stage through a minimal verified function.
        j['fresh']=lambda:j['step']('CHECK_CANDIDATE_RUNTIME' if stage=='runtime' else 'CHECK_PRODUCTION_PRESERVATION','HOST',missing)
    target=j['_real_fresh'] if stage=='capacity' else j['fresh']
    with pytest.raises(FileNotFoundError) as caught:target()
    report=j['failure'](caught.value)
    assert report['path_id']==label and report['operation']!='PREFLIGHT' and report['errno']==2
    assert candidate not in json.dumps(report) and 'private filesystem' not in json.dumps(report)
    assert not j['CONTROL'].exists() and not j['CHANGED']


def test_missing_frozen_model_native_fixture_still_fails_closed(fixture):
    j,_,_,prod,_=fixture;j['GUARD']['idle_capacity']=lambda *a:{}
    with pytest.raises(FileNotFoundError) as caught:j['_real_fresh']()
    info=j['failure'](caught.value)
    assert info['path_id']=='FROZEN_MODEL' and info['operation']=='CHECK_FROZEN_FILES'
    assert not (prod/'artifacts/models/releases/next24h/next24h_model.joblib').exists() and not j['CHANGED']


def test_unknown_path_is_not_disclosed(fixture):
    j,_,_,_,_=fixture;info=j['failure'](FileNotFoundError(2,'secret','/unapproved/private/secret'))
    assert info['path_id']=='UNMAPPED_REQUIRED_PATH' and '/unapproved' not in json.dumps(info)


def test_preflight_only_has_no_writes_or_activation(fixture):
    j,d,calls,prod,_=fixture;(prod/'src/shared').rmdir();before=(prod/'src/scheduled_pipeline.py').read_bytes()
    j['CONFIG']['original_tools']={};d['job_variables']={'env':{'PRIVATE':'SENTINEL'}}
    report=j['preflight_report']()
    assert report['status']=='INITIAL_PREFLIGHT_PASS' and report['check_scope']=='INITIAL_HOST_AND_ORIGINAL_TOOLS'
    assert report['changed'] is False and 'SENTINEL' not in json.dumps(report)
    assert not j['CONTROL'].exists() and not (prod/'src/shared').exists() and not calls
    assert (prod/'src/scheduled_pipeline.py').read_bytes()==before and not j['CHANGED']
    tree=ast.parse((FOLDER/'job.py').read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='preflight_report')
    text=ast.unparse(fn);assert 'apply(' not in text and 'rollback(' not in text and 'write(' not in text and 'patch(' not in text


def test_operational_directory_behavior_unchanged(fixture):
    j,d,calls,prod,_=fixture;(prod/'src/shared').rmdir()
    assert j['apply']()['shared_directory']=='CREATED'
    assert j['rollback']()['shared_directory']=='REMOVED_EMPTY_CREATED'
    assert (prod/'src/scheduled_pipeline.py').read_bytes()==b'original'


def test_new_manifest_has_exact_original_tool_hash_map(monkeypatch):
    spec=importlib.util.spec_from_file_location('v2_runner',FOLDER/'run.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
    real=r.namespace
    monkeypatch.setattr(r,'namespace',lambda raw,name,path=None,extra=None:{'profile':lambda:{}} if name=='wrapper' else real(raw,name,path,extra))
    raw=(FOLDER/'MANIFEST.json').read_bytes();m=json.loads(raw);digest=hashlib.sha256(raw).hexdigest()
    old=json.loads((FOLDER.parent/'automation-deployment/MANIFEST.json').read_bytes())
    assert m['config']['original_tools']==old['config']['original_tools']
    for action in ['preflight','apply','rollback']:
        payload,_,_,tx=r.verify(digest,action);assert hashlib.sha256(payload).hexdigest()==m['payload_sha256'][action]
        assert tx not in [r.ORIGINAL_TRANSACTION,r.PRIOR_TRANSACTION]
    # Even a consistently re-hashed test manifest cannot broaden original-tool bindings.
    modified=copy.deepcopy(m);modified['config']['original_tools']=json.loads((PRIOR/'MANIFEST.json').read_bytes())['config']['original_tools']
    changed=json.dumps(modified).encode();read=r.read
    monkeypatch.setattr(r,'read',lambda p,*a:changed if p==FOLDER/'MANIFEST.json' else read(p,*a))
    with pytest.raises(ValueError,match='original_tools_binding'):r.verify(hashlib.sha256(changed).hexdigest(),'preflight')


@pytest.mark.parametrize('result_kind',['pass','missing_path','missing_scope','ssh_failure'])
def test_readonly_wrapper_bounds_output_and_never_retries(tmp_path,monkeypatch,capsys,result_kind):
    spec=importlib.util.spec_from_file_location('v2_wrapper_fixture',FOLDER/'run.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
    (tmp_path/'preflight').mkdir();calls=[];payload=b'held-verified-synthetic-bytes';tx='f'*32
    report={'status':'INITIAL_PREFLIGHT_PASS','transaction':tx,'phase':'PREFLIGHT','changed':False,'publication_executed':False,'check_scope':'INITIAL_HOST_AND_ORIGINAL_TOOLS'}
    if result_kind=='missing_scope':report.pop('check_scope')
    if result_kind=='missing_path':report.update(status='BLOCKED',error_category='MISSING_PATH',operation='VERIFY_ORIGINAL_TOOLS',path_id='ORIGINAL_TOOL_PREPARE',errno=2)
    def bounded(argv,**kwargs):
        calls.append((argv,kwargs))
        return {'returncode':255 if result_kind=='ssh_failure' else 1 if result_kind=='missing_path' else 0,'failure':'SSH_FAILURE' if result_kind=='ssh_failure' else None,'stdout':json.dumps(report).encode(),'stderr':b''}
    w={'PRIVATE':tmp_path,'profile':lambda:{},'ssh_argv':lambda p:['fixed-ssh','fixed-reviewed-remote-command'],'failure_category':lambda *a:'SSH_FAILURE'}
    monkeypatch.setattr(r,'verify',lambda *a:(payload,w,{'bounded_run':bounded},tx))
    monkeypatch.setattr('sys.argv',['run.py','preflight','--manifest-sha256','a'*64])
    previous_mask=os.umask(0o077);os.umask(previous_mask)
    try:assert r.main()==(0 if result_kind=='pass' else 1)
    finally:os.umask(previous_mask)
    assert len(calls)==1
    argv,kw=calls[0]
    assert argv[-1]=='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -'
    assert kw=={'input':payload,'timeout':120,'limit':131072,'grace':5}
    output=json.loads(capsys.readouterr().out)
    if result_kind=='missing_path':assert output['report']['path_id']=='ORIGINAL_TOOL_PREPARE'
    if result_kind=='missing_scope':assert output['failure_category']=='UNEXPECTED_OUTPUT'
