"""Offline fixed-scope metadata/access fixtures. No SSH or privilege changes."""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import types
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'deploy/staging/realized-parent-traversal-diagnostic-v1'
def load(name):
    s=importlib.util.spec_from_file_location('traversal_'+name,HERE/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def rows(mode=0o750,gid=992):
    return [{'id':label,'uid':0,'gid':gid if i==2 else 0,'mode':mode if i==2 else 0o755,'identity':(1,i+1,0)}for i,label in enumerate(load('inspect').LABELS)]

def result(reason='TRAVERSAL_PASS',path='NONE',code=None,**change):
    report={'version':1,'reason':reason,'path_id':path,'errno':None}
    return {'returncode':(0 if reason=='TRAVERSAL_PASS'else 1)if code is None else code,'stdout':json.dumps(report).encode(),'stderr':b'','failure':None,**change}

@pytest.fixture
def coordinator(monkeypatch):
    m=load('inspect');m.sys=types.SimpleNamespace(platform='linux',version_info=(3,9,6));m.os=types.SimpleNamespace(getuid=lambda:0,geteuid=lambda:0,getgid=lambda:0,getegid=lambda:0,O_PATH=1,O_NOFOLLOW=2)
    calls=[];m.trusted_commands=lambda:calls.append('trusted-tools');m.identities=lambda:[];m.metadata=lambda:rows();m.PRODUCER=b'fixed-reviewed-child'
    def run(argv,**kw):calls.append((argv,kw));return result('PRODUCER_TRAVERSAL_DENIED','REPORT_STORE_PARENT')
    m.bounded_run=run;return m,calls


def test_original_parent_mode_explains_cleared_identity_but_is_not_host_proof(coordinator):
    m,calls=coordinator;report=m.inspect()
    assert report['status']=='BLOCKED'and report['reason']=='PRODUCER_TRAVERSAL_MODE_DENIED'
    assert report['failed_path_id']=='REPORT_STORE_PARENT'and report['directories'][-1]=={'path_id':'REPORT_STORE_PARENT','owner':'ROOT','group':'API_READER_GROUP','mode':'0750','cleared_producer_mode_allows_search':False}
    command,kw=calls[-1];assert command==m.CHILD_ARGV
    assert kw==dict(input=m.PRODUCER,timeout=5,limit=2048,grace=5)
    assert not any('root'==arg or'--init-groups'==arg for arg in command)


def test_actual_worker_group_difference_does_not_bypass_gate(coordinator):
    m,calls=coordinator;m.identities=lambda:[992]
    report=m.inspect();assert report['reason']=='PROBE_GROUP_CONTEXT_DIFFERENCE'and report['status']=='BLOCKED'
    assert report['worker_api_reader_group_present']is True and report['worker_groups_match_cleared_probe']is False
    assert len([c for c in calls if isinstance(c,tuple)])==1
    assert '--clear-groups'in calls[-1][0]


def test_mode_allowed_but_access_denied_leaves_acl_mac_cause_unestablished(coordinator):
    m,_=coordinator;m.metadata=lambda:rows(mode=0o755)
    assert m.inspect()['reason']=='PRODUCER_TRAVERSAL_OS_POLICY_DENIED'


def test_current_success_does_not_claim_historical_root_cause(coordinator):
    m,_=coordinator;m.metadata=lambda:rows(mode=0o755);m.bounded_run=lambda *a,**kw:result()
    assert m.inspect()['status']=='PASS'

@pytest.mark.parametrize('reason',['PRODUCER_UID_MISMATCH','PRODUCER_GID_MISMATCH','PRODUCER_SAVED_ID_MISMATCH','PRODUCER_SUPPLEMENTARY_GROUPS_PRESENT','PRODUCER_SECURITY_CONTEXT_UNVERIFIED','PATH_MISSING','PATH_LOOKUP_DENIED','PATH_SYMLINK_OR_TYPE_VIOLATION','PROBE_RUNTIME_UNSUPPORTED'])
def test_child_failure_is_specific_not_assumed_parent_permissions(coordinator,reason):
    m,_=coordinator;m.bounded_run=lambda *a,**kw:result(reason)
    assert m.inspect()['reason']==reason

@pytest.mark.parametrize('failure,expected',[('TIMEOUT','PRODUCER_PROBE_TIMEOUT'),('OUTPUT_LIMIT','PRODUCER_PROBE_OUTPUT_LIMIT')])
def test_supervision_is_not_reported_as_traversal_denial(coordinator,failure,expected):
    m,_=coordinator;m.bounded_run=lambda *a,**kw:result(stdout=b'',failure=failure)
    assert m.inspect()['reason']==expected

@pytest.mark.parametrize('stderr,expected',[(b'setpriv: failed to execute /private/secret: Permission denied','PRODUCER_INTERPRETER_EXECUTION_FAILED'),(b'setpriv: setgroups failed: SECRET','PRODUCER_PRIVILEGE_DROP_FAILED'),(b'Fatal Python error: SECRET /private/path','PRODUCER_PYTHON_STARTUP_FAILED'),(b'UNCLASSIFIED_SECRET','PRODUCER_PROBE_OUTPUT_UNVERIFIED')])
def test_startup_classification_never_keeps_raw_error(coordinator,stderr,expected):
    m,_=coordinator;m.bounded_run=lambda *a,**kw:result(stdout=b'',stderr=stderr,code=1)
    report=m.inspect();assert report['reason']==expected
    assert 'SECRET'not in json.dumps(report)and '/private'not in json.dumps(report)

@pytest.mark.parametrize('raw',[b'{}',b'[]',b'{"version":1,"version":2}',b'{"secret":"DO_NOT_RETAIN"}',b'not json',b'x'*2049])
def test_malformed_or_unapproved_child_output_fails_closed(coordinator,raw):
    m,_=coordinator
    try:report=m.child_result(result(stdout=raw))
    except m.Stop as e:report=m.failure_report(e)
    assert report['reason']=='PRODUCER_PROBE_OUTPUT_UNVERIFIED'
    assert 'DO_NOT_RETAIN'not in json.dumps(report)


def test_parent_metadata_change_blocks_instead_of_accepting_new_values(coordinator):
    m,_=coordinator;first=rows();second=copy.deepcopy(first);second[-1]['identity']=(9,9,9)
    values=iter([first,second]);m.metadata=lambda:next(values)
    with pytest.raises(m.Stop,match='PARENT_METADATA_CHANGED'):m.inspect()


def test_root_error_reporting_is_closed_and_sanitized(coordinator):
    m,_=coordinator;m.STAGE='PARENT_METADATA'
    for error in [RuntimeError('SECRET /private/path'),m.Stop('SECRET_TOKEN'),PermissionError(13,'SECRET','/private/path')]:
        report=m.failure_report(error);assert report['status']=='BLOCKED'
        assert 'SECRET'not in json.dumps(report)and '/private'not in json.dumps(report)

@pytest.fixture
def producer():
    m=load('producer');calls=[]
    fake=types.SimpleNamespace(O_PATH=1,O_DIRECTORY=2,O_NOFOLLOW=4,X_OK=1,getuid=lambda:1000,geteuid=lambda:1000,getgid=lambda:1000,getegid=lambda:1000,getresuid=lambda:(1000,1000,1000),getresgid=lambda:(1000,1000,1000),getgroups=lambda:[],close=lambda fd:calls.append(('close',fd)),stat=lambda name,**kw:types.SimpleNamespace(st_mode=stat.S_IFDIR|0o750),access=lambda name,mode,**kw:True)
    def opening(name,flags,**kwargs):calls.append(('open',name,flags,kwargs));return len(calls)
    fake.open=opening;m.os=fake;m.sys=types.SimpleNamespace(platform='linux');m.security_context=lambda:True
    return m,calls


def test_child_exact_paths_identity_and_search_only(producer):
    m,calls=producer;access=[]
    m.os.access=lambda name,mode,**kw:access.append((name,mode,kw))or name!='powerflow'
    assert m.check()['reason']=='PRODUCER_TRAVERSAL_DENIED'
    assert [r[0]for r in access]==['.','srv','powerflow']
    assert all(r[1]==m.os.X_OK and r[2]['follow_symlinks']is False for r in access)
    assert all(c[1]in{'/','srv'}for c in calls if c[0]=='open') # denied parent is never opened

@pytest.mark.parametrize('attr,value,reason',[('getuid',0,'PRODUCER_UID_MISMATCH'),('getgid',0,'PRODUCER_GID_MISMATCH'),('getresuid',(1000,1000,0),'PRODUCER_SAVED_ID_MISMATCH'),('getgroups',[992],'PRODUCER_SUPPLEMENTARY_GROUPS_PRESENT')])
def test_no_root_or_added_group_fallback(producer,attr,value,reason):
    m,calls=producer;setattr(m.os,attr,lambda:value)
    assert m.check()['reason']==reason and not calls


def test_symlink_rejected_without_following_it(producer):
    m,_=producer;m.os.stat=lambda *a,**kw:types.SimpleNamespace(st_mode=stat.S_IFLNK|0o777)
    assert m.check()['reason']=='PATH_SYMLINK_OR_TYPE_VIOLATION'


def test_security_context_failure_stops_before_traversal(producer):
    m,calls=producer;m.security_context=lambda:False
    assert m.check()['reason']=='PRODUCER_SECURITY_CONTEXT_UNVERIFIED'and not calls


def test_exact_service_and_runtime_identity_reads(monkeypatch):
    m=load('inspect');calls=[]
    monkeypatch.setattr(m.pwd,'getpwnam',lambda name:types.SimpleNamespace(pw_uid=1000,pw_gid=1000))
    def query(argv,**kw):
        calls.append((argv,kw));return {'returncode':0,'failure':None,'stdout':b'User=ec2-user\nGroup=ec2-user\nMainPID=123\n','stderr':b''}
    m.bounded_run=query;m.read_proc=lambda path:calls.append(path)or b'Uid:\t1000\t1000\t1000\t1000\nGid:\t1000\t1000\t1000\t1000\nGroups:\t992 1000\n'
    assert m.identities()==[992,1000]
    assert calls[0][0]==m.SERVICE_ARGV and calls[-1]=='/proc/123/status'
    assert 'Environment'not in str(calls[0])and'environ'not in calls[-1]


def test_wrong_worker_identity_stops_without_a_producer_probe(monkeypatch):
    m=load('inspect');monkeypatch.setattr(m.pwd,'getpwnam',lambda name:types.SimpleNamespace(pw_uid=999,pw_gid=999))
    m.bounded_run=lambda *a,**kw:pytest.fail('queried after wrong producer identity')
    with pytest.raises(m.Stop,match='PRODUCER_ACCOUNT_IDENTITY_MISMATCH'):m.identities()


def test_scope_no_filesystem_mutation_sdk_network_or_app_imports():
    for file in ['inspect.py','producer.py']:
        tree=ast.parse((HERE/file).read_bytes(),feature_version=(3,9))
        imports={n.name for node in ast.walk(tree)if isinstance(node,ast.Import)for n in node.names}
        assert imports<={'json','os','pwd','re','stat','sys'}
        attrs={n.func.attr for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)}
        assert not attrs&{'mkdir','chmod','chown','unlink','remove','rename','replace','write','connect','request','publish','run','system'}
        assert 'O_WRONLY'not in (HERE/file).read_text()and 'O_RDWR'not in(HERE/file).read_text()


def test_local_layout_clue_is_not_host_proof_and_release_remains_unchanged():
    text=(ROOT/'deploy/staging/install-package/install.py').read_text()
    assert "mkdir_new_or_safe(Path('/srv/powerflow'),0o750);os.chown('/srv/powerflow',0,g.gr_gid)"in text
    original=ROOT/'deploy/staging/realized-performance-release-v1'
    assert hashlib.sha256((original/'MANIFEST.json').read_bytes()).hexdigest()=='a3dceba7641ceaa9030709b1b7d4ce59460b54f5123b7e89f15d95bba39b0a83'
    assert "--clear-groups"in(original/'guards.py').read_text()

@pytest.mark.parametrize('body,expected',[(b'NoNewPrivs:\t1\nCapEff:\t0\nCapPrm:\t0\nCapAmb:\t0\n',True),(b'NoNewPrivs:\t0\nCapEff:\t0\nCapPrm:\t0\nCapAmb:\t0\n',False),(b'NoNewPrivs:\t1\nCapEff:\t1\nCapPrm:\t0\nCapAmb:\t0\n',False),(b'NoNewPrivs:\t1\nCapEff:\t0\nCapPrm:\t1\nCapAmb:\t0\n',False),(b'NoNewPrivs:\t1\nCapEff:\t0\nCapPrm:\t0\nCapAmb:\t1\n',False),(b'malformed SECRET',False),(b'x'*16385,False)])
def test_child_verifies_no_privilege_material_and_kernel_read_scope(body,expected):
    m=load('producer');calls=[]
    m.os=types.SimpleNamespace(O_RDONLY=0,O_NOFOLLOW=1,getpid=lambda:123,open=lambda path,flags:calls.append((path,flags))or 7,read=lambda fd,limit:body,close=lambda fd:None)
    assert m.security_context()is expected
    assert calls==[('/proc/123/status',1)]


def test_metadata_does_not_enumerate_or_follow_symlinks():
    m=load('inspect');calls=[]
    def statter(name,**kw):
        calls.append((name,kw));return types.SimpleNamespace(st_mode=(stat.S_IFLNK if name=='powerflow'else stat.S_IFDIR)|0o755,st_uid=0,st_gid=0,st_dev=1,st_ino=2,st_ctime_ns=3)
    m.os=types.SimpleNamespace(O_PATH=1,O_DIRECTORY=2,O_NOFOLLOW=4,open=lambda *a,**kw:1,close=lambda fd:None,stat=statter)
    with pytest.raises(m.Stop,match='PATH_SYMLINK_OR_TYPE_VIOLATION'):m.metadata()
    assert [name for name,_ in calls]==['.','srv','powerflow']
    assert all(kw['follow_symlinks']is False for _,kw in calls)


def test_runtime_worker_identity_mismatch_is_not_a_permission_result(monkeypatch):
    m=load('inspect');monkeypatch.setattr(m.pwd,'getpwnam',lambda name:types.SimpleNamespace(pw_uid=1000,pw_gid=1000))
    m.bounded_run=lambda *a,**kw:{'returncode':0,'failure':None,'stdout':b'User=ec2-user\nGroup=ec2-user\nMainPID=123\n','stderr':b''}
    m.read_proc=lambda path:b'Uid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\nGroups:\t0\n'
    with pytest.raises(m.Stop,match='WORKER_RUNTIME_IDENTITY_MISMATCH'):m.identities()


def test_future_payload_has_one_command_each_and_no_application_entrypoints():
    r=load('run');blobs={str((HERE/'producer.py').relative_to(ROOT)):(HERE/'producer.py').read_bytes(),str((HERE/'inspect.py').relative_to(ROOT)):(HERE/'inspect.py').read_bytes()}
    # A stand-in supervisor is inert: no process creation in the test.
    bounded=b"calls=[]\ndef bounded_run(argv,**kw):\n calls.append(argv)\n return {'returncode':0,'failure':None,'stdout':b'','stderr':b''}\n"
    payload=r.assemble(blobs,bounded);ast.parse(payload,feature_version=(3,9))
    prefix=payload.split(b'try:\n report=inspect()')[0];ns={};exec(compile(prefix,'<offline-only>','exec'),ns)
    ns['bounded_run'](ns['SERVICE_ARGV'],timeout=5,limit=4096,grace=5)
    with pytest.raises(ns['Stop'],match='DIAGNOSTIC_EXECUTION_BOUND'):ns['bounded_run'](ns['SERVICE_ARGV'],timeout=5,limit=4096,grace=5)
    with pytest.raises(ns['Stop'],match='DIAGNOSTIC_COMMAND_SCOPE'):ns['bounded_run'](['/usr/bin/true'])
    with pytest.raises(ns['Stop'],match='DIAGNOSTIC_INPUT_SCOPE'):ns['bounded_run'](ns['CHILD_ARGV'],input=b'unreviewed',limit=2048)
    assert len(ns['calls'])==1
    names={n.name for n in ast.walk(ast.parse(payload))if isinstance(n,ast.FunctionDef)}
    assert not names&{'apply','rollback','publish','deliver_terminal','preflight_report'}


def test_report_schema_rejects_sensitive_or_unknown_fields(coordinator):
    m,_=coordinator;r=load('run');report=m.inspect()
    assert r.validate_report(report,m)['reason']=='PRODUCER_TRAVERSAL_MODE_DENIED'
    with pytest.raises(ValueError):r.validate_report({**report,'path':'/private/secret'},m)
    changed=copy.deepcopy(report);changed['directories'][0]['owner']='SECRET_USERNAME'
    with pytest.raises(ValueError):r.validate_report(changed,m)


def test_immutable_package_and_zero_connection_verification():
    r=load('run');raw=(HERE/'MANIFEST.json').read_bytes();digest=r.sha(raw)
    transport,wrapper,supervisor,payload,schema=r.verify(digest)
    assert r.sha(payload)==json.loads(raw)['payload']['sha256']
    command=r.argv(transport,wrapper)
    assert command[-1]==r.REMOTE
    assert all(option in command for option in ['StrictHostKeyChecking=yes','PreferredAuthentications=publickey','IdentityAgent=none','ProxyCommand=none','ConnectTimeout=10','ConnectionAttempts=1'])
    assert b'def apply('not in payload and b'def publish('not in payload
    assert b'fixed PowerFlow staging installation'not in payload
    ast.parse(payload,feature_version=(3,9))


def test_manifest_tampering_is_rejected_before_connection():
    r=load('run')
    with pytest.raises(ValueError,match='DIAGNOSTIC_BINDING_REJECTED'):r.verify('0'*64)


def test_execution_is_one_attempt_with_sanitized_private_capture(tmp_path,monkeypatch,coordinator):
    r=load('run');schema,_=coordinator;report=schema.inspect();calls=[]
    private=tmp_path/'private';(private/'preflight').mkdir(parents=True)
    wrapper={'PRIVATE':private}
    def supervise(argv,**kwargs):
        calls.append((argv,kwargs));return {'returncode':1,'failure':None,'stdout':json.dumps(report).encode(),'stderr':b'SECRET TRANSPORT /private/path'}
    monkeypatch.setattr(r,'verify',lambda *a:(None,wrapper,supervise,b'reviewed-metadata-payload',schema));monkeypatch.setattr(r,'argv',lambda *_:['approved-one-shot-command'])
    monkeypatch.setattr(sys,'argv',['run.py','--manifest-sha256','a'*64])
    assert r.main()==1 and len(calls)==1
    assert calls[0][1]==dict(input=b'reviewed-metadata-payload',timeout=40,limit=8192,grace=5)
    files=[p for p in private.rglob('*')if p.is_file()];assert len(files)==1
    assert 'SECRET'not in files[0].read_text()and '/private/path'not in files[0].read_text()
    assert stat.S_IMODE(files[0].stat().st_mode)==0o600


def test_local_check_cannot_start_ssh(monkeypatch):
    r=load('run');monkeypatch.setattr(r,'verify',lambda *a:(None,None,lambda *a,**kw:pytest.fail('SSH attempted'),b'payload',None));monkeypatch.setattr(r,'argv',lambda *_:['fixed'])
    monkeypatch.setattr(sys,'argv',['run.py','--manifest-sha256','a'*64,'--local-check'])
    assert r.main()==0
