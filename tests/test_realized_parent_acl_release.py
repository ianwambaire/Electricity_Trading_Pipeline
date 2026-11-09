"""Offline only: fake kernel/libacl/transport; never SSH or privilege changes."""
import ast
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import types
from unittest.mock import Mock

import pytest

ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'deploy/staging/realized-parent-acl-release-v1'
MINIMAL='user::rwx\ngroup::r-x\nother::---\n'
EXTENDED='user::rwx\nuser:42:rwx\ngroup::r-x\ngroup:77:rwx\nmask::r-x\nother::---\n'

def load(name):
    s=importlib.util.spec_from_file_location('acl_test_'+name,HERE/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def ns(*files):
    d={'__name__':'offline_acl','C':{'release':'fixed','transaction':'fixed','binding':'a'*64,'control':'/offline-not-created/acl-transaction'}}
    for name in ['policy.py',*files]:exec(compile((HERE/name).read_bytes(),name,'exec'),d)
    return d

def state(text=MINIMAL):
    m={'device':1,'inode':2,'uid':0,'gid':992,'mode':0o750}
    return {'parent':{'metadata':m,'access_raw':None,'default_raw':None,'access_text':text,'default_text':None},'children':{name:{'id':i}for i,name in enumerate(['published','forecast-publications','operational-publications'])},'worker_groups':[1000],'library':{'device':1,'inode':3,'sha256':'a'*64}}

@pytest.mark.parametrize('text',[MINIMAL,EXTENDED,MINIMAL.replace('group::r-x','user:1000:---\ngroup::r-x\nmask::r-x')])
def test_exact_search_only_plan_and_preservation(text):
    d=ns();old=d['parse'](text);new=d['parse'](d['plan'](text,[1000]))
    assert new[('user','1000')]==1 and d['mode_of'](new)==0o750
    assert new[('mask','')]==old.get(('mask',''),old[('group','')])
    for uid in [1,42,77,999,1001,65534]:
        for gids in [{0},{992},{77},{77,992},{1000},set()]:
            assert d['effective'](old,uid,gids)==d['effective'](new,uid,gids)
    assert all(d['effective'](new,1000,groups)==1 for groups in [{1000},{1000,77},{992}])

@pytest.mark.parametrize('text,code',[
 ('user::rwx\ngroup::rwx\nother::---','ACL_MODE_MISMATCH'),
 (MINIMAL+'user:1000:r-x\nmask::r-x','PRODUCER_EXISTING_ACCESS_NOT_DENIED'),
 (MINIMAL+'user:1000:-w-\nmask::r-x','ACL_TARGET_ENTRY_UNSUPPORTED'),
 (MINIMAL+'user:1000:--x\nmask::r-x','PRODUCER_EXISTING_ACCESS_NOT_DENIED'),
 (MINIMAL+'group:1000:r--\nmask::r-x','PRODUCER_EXISTING_ACCESS_NOT_DENIED'),
 (MINIMAL+'group:88:r--\nmask::r-x','PRODUCER_EXISTING_ACCESS_NOT_DENIED')])
def test_unsafe_preexisting_access_rejected(text,code):
    d=ns()
    with pytest.raises(d['Stop'],match=code):d['plan'](text,[88])

@pytest.mark.parametrize('text',[
 '',MINIMAL+'other::---',MINIMAL+'user:../:--x',MINIMAL+'user:01000:--x',
 MINIMAL+'user:4294967295:--x',MINIMAL+'user:1000:--x',MINIMAL+'mask:1:r-x',
 MINIMAL.replace('rwx','rwx #secret'),MINIMAL+'\x00','\n'.join(['user::rwx']*129)])
def test_acl_parser_rejects_invalid(text):
    d=ns()
    with pytest.raises(d['Stop']):d['parse'](text)

@pytest.mark.parametrize('text',[EXTENDED+'user:1000:--x\n',EXTENDED.replace('other::---','other::r--')])
def test_protected_or_default_acl_cannot_expose_producer(text):
    d=ns()
    for f in ['deny_boundary','deny_default']:
        with pytest.raises(d['Stop']):d[f](text,[1000])

def test_masked_write_rights_never_activated():
    d=ns();new=d['parse'](d['plan'](EXTENDED))
    assert new[('user','42')]==7 and d['effective'](new,42,{0})==5
    with pytest.raises(d['Stop'],match='ACL_NOT_EXACT'):
        d['verify_plan'](EXTENDED,d['render'](dict(new,**{})).replace('mask::r-x','mask::rwx'))

@pytest.mark.parametrize('errno,code',[(95,'POSIX_ACL_NOT_SUPPORTED'),(38,'POSIX_ACL_NOT_SUPPORTED'),(13,'ACL_XATTR_READ_FAILED')])
def test_xattr_support_fail_closed(errno,code):
    d=ns('acl_read.py');d['os']=types.SimpleNamespace(getxattr=Mock(side_effect=OSError(errno,'PRIVATE-SENSITIVE')))
    with pytest.raises(d['Stop'],match=code):d['attr'](17,d['ACCESS'])

def test_xattr_absence_and_exact_bytes():
    d=ns('acl_read.py');d['os']=types.SimpleNamespace(getxattr=Mock(side_effect=OSError(61,'not retained')))
    assert d['attr'](17,d['ACCESS'])is None
    d['os'].getxattr=Mock(return_value=b'exact-xattr-bytes')
    assert base64.b64decode(d['attr'](17,d['DEFAULT']))==b'exact-xattr-bytes'
    with pytest.raises(d['Stop'],match='XATTR_READ_SCOPE'):d['attr'](17,'user.secret')

def child_response(granted=False,**changes):
    value={'version':1,'status':'PASS','reason':'PROBE_PASS','parent_search':granted,'parent_read':False,'parent_write':False,'boundary':'NONE'};value.update(changes)
    return {'failure':None,'returncode':0,'stdout':json.dumps(value).encode(),'stderr':b''}

@pytest.mark.parametrize('granted',[False,True])
def test_probe_success_exact_cleared_identity_argv(granted):
    d=ns('guards.py');d.update(PROBE_DENIED=b'denied',PROBE_GRANTED=b'granted',process=Mock(return_value=child_response(granted)))
    assert d['probe'](granted)['parent_search']is granted
    argv=d['process'].call_args.args[0]
    assert argv[:5]==['/usr/bin/setpriv','--no-new-privs','--reuid=1000','--regid=1000','--clear-groups']

@pytest.mark.parametrize('change',[{'parent_read':True},{'parent_write':True},{'parent_search':True},{'version':True},{'boundary':'FORECAST'},{'reason':'PRIVATE-SECRET'},{'extra':'secret'}])
def test_probe_malformed_or_excess_access_blocks(change):
    d=ns('guards.py');d.update(PROBE_DENIED=b'd',PROBE_GRANTED=b'g',process=Mock(return_value=child_response(**change)))
    with pytest.raises(d['Stop']):d['probe'](False)

@pytest.mark.parametrize('failure',['TIMEOUT','OUTPUT_LIMIT'])
def test_probe_bounds(failure):
    d=ns('guards.py');r=child_response();r['failure']=failure;d.update(PROBE_DENIED=b'd',PROBE_GRANTED=b'g',process=Mock(return_value=r))
    with pytest.raises(d['Stop'],match='PRODUCER_PROBE_TIMEOUT_OR_BOUND'):d['probe'](False)

@pytest.mark.parametrize('names',[
 ['published','forecast-publications','operational-publications','unexpected'],
 ['published','forecast-publications'],['published','published','operational-publications']])
def test_unknown_parent_inventory_blocks_without_opening_children(names):
    class Scan:
        def __enter__(self):return iter(types.SimpleNamespace(name=n)for n in names)
        def __exit__(self,*_):pass
    d=ns('guards.py');d['os']=types.SimpleNamespace(scandir=lambda _:Scan(),lseek=lambda *_:None,SEEK_SET=0,open=Mock())
    with pytest.raises(d['Stop'],match='PARENT_CHILD_INVENTORY_DRIFT'):d['boundary_states'](types.SimpleNamespace(fd=17),[])
    d['os'].open.assert_not_called()

def transaction():
    d=ns('acl_read.py','guards.py','transaction.py');original=state();current=copy.deepcopy(original);memory={};calls=[]
    class Fn:
        def __call__(self,fd,text):
            calls.append(('acl_set_fd',fd,text));assert fd==17
            current['parent']['access_text']=text;current['parent']['access_raw']=base64.b64encode(b'planned-xattr').decode();return 0
    lib=types.SimpleNamespace(acl_set_fd=Fn(),acl_free=Mock())
    acl=types.SimpleNamespace(prepare=lambda text:text,lib=lib)
    class Context:
        fd=17
        def __enter__(self):self.acl=acl;return self
        def __exit__(self,*_):pass
    def write(fd,name,raw,replace=False):
        assert fd==27 and name in {'snapshot.backup','snapshot.independent','record.json'}
        if not replace:assert name not in memory
        memory[name]=raw
    def restore_xattr(fd,name,raw):
        assert fd==17 and name==d['ACCESS'];calls.append(('restore',fd,raw))
        current['parent']=copy.deepcopy(original['parent'])
    fakeos=types.SimpleNamespace(close=lambda _:None,path=types.SimpleNamespace(lexists=lambda p:Path(p).name in memory),setxattr=restore_xattr,removexattr=lambda fd,name:restore_xattr(fd,name,None))
    d.update(Context=Context,os=fakeos,fcntl=types.SimpleNamespace(LOCK_EX=1,LOCK_NB=4,flock=lambda *_:None),idle=Mock(),observe=lambda _:copy.deepcopy(current),fresh=lambda _:(copy.deepcopy(original),d['plan'](original['parent']['access_text'],[1000])),control_fd=lambda create=False:27,write_private=write,read_private=lambda fd,name:(memory[name],(1,10+list(sorted(memory)).index(name))),metadata=lambda _:copy.deepcopy(current['parent']['metadata']))
    def probe(granted):
        assert d['effective'](d['parse'](current['parent']['access_text']),1000,{1000})==(1 if granted else 0)
        calls.append(('probe',granted))
    d['probe']=probe
    return d,original,current,memory,calls

@pytest.mark.parametrize('raw',[None,base64.b64encode(b'original-extended-acl').decode()])
def test_complete_mocked_apply_independent_backup_and_exact_rollback(raw):
    d,old,current,memory,calls=transaction();old['parent']['access_raw']=raw;current['parent']['access_raw']=raw
    # fresh() captures this same original object through closure.
    assert d['apply']()['status']=='APPLIED'
    assert memory['snapshot.backup']==memory['snapshot.independent']
    assert json.loads(memory['record.json'])['phase']=='APPLIED'
    assert len([c for c in calls if c[0]=='acl_set_fd'])==1
    assert d['rollback']()['status']=='ROLLED_BACK'and current==old
    assert json.loads(memory['record.json'])['phase']=='ROLLED_BACK'
    assert [c for c in calls if c[0]=='restore']==[('restore',17,None if raw is None else base64.b64decode(raw))]

@pytest.mark.parametrize('field',['metadata','default_raw','children','worker_groups','library'])
def test_post_change_preservation_drift_blocks(field):
    d=ns('acl_read.py','guards.py','transaction.py');before=state();after=copy.deepcopy(before)
    if field=='metadata':after['parent']['metadata']['gid']=0
    elif field=='default_raw':after['parent']['default_raw']='bad'
    else:after[field]={}if field!='worker_groups'else[992]
    with pytest.raises(d['Stop']):d['preserve'](before,after)

def test_backup_corruption_and_unknown_acl_stop_rollback():
    d,old,current,memory,calls=transaction();d['apply']();memory['snapshot.independent']+=b'corrupt'
    with pytest.raises(d['Stop'],match='BACKUP_INDEPENDENCE_OR_HASH'):d['rollback']()
    assert not any(c[0]=='restore'for c in calls)

@pytest.mark.parametrize('change',['acl','inode','group','default','child'])
def test_unrelated_drift_prevents_rollback(change):
    d,old,current,memory,calls=transaction();d['apply']()
    if change=='acl':current['parent']['access_text']=current['parent']['access_text'].replace('user:1000:--x','user:1000:r-x')
    elif change=='inode':current['parent']['metadata']['inode']=99
    elif change=='group':current['parent']['metadata']['gid']=0
    elif change=='default':current['parent']['default_raw']='unexpected'
    else:current['children']['realized-performance']={}
    with pytest.raises(d['Stop']):d['rollback']()
    assert not any(c[0]=='restore'for c in calls)

def test_failed_postcheck_never_automatically_rolls_back():
    d,old,current,memory,calls=transaction();d['probe']=Mock(side_effect=d['Stop']('PROTECTED_BOUNDARY_ACCESS'))
    with pytest.raises(d['Stop'],match='PROTECTED_BOUNDARY_ACCESS'):d['apply']()
    assert json.loads(memory['record.json'])['phase']=='CHANGING_ACL'
    assert not any(c[0]=='restore'for c in calls)
    # Explicit separate rollback can recover exactly the planned partial state.
    d['probe']=lambda *_:None
    assert d['rollback']()['status']=='ROLLED_BACK'

def test_fresh_gate_change_blocks_before_backup_or_setter():
    d,old,current,memory,calls=transaction();counter=iter([old,{**old,'worker_groups':[10]}]);d['fresh']=lambda _:(copy.deepcopy(next(counter)),d['plan'](MINIMAL))
    with pytest.raises(d['Stop'],match='FRESH_GATE_DRIFT'):d['apply']()
    assert memory=={}and calls==[]

@pytest.fixture(scope='module')
def assembled():
    b=load('build');return b,{a:b.assemble(a)for a in b.ACTIONS}

def test_preflight_excludes_mutation_module_and_setter(assembled):
    b,items=assembled;text=items['preflight'][0].decode()
    for forbidden in ['acl_set_fd','os.setxattr','os.removexattr','os.mkdir','os.chmod','os.fchmod','os.replace','write_private','def apply(','def rollback(']:assert forbidden not in text
    for required in ['PIPELINE_OR_WINDOW_GATE','WORKER_API_READER_GROUP_FORBIDDEN','PROBE_DENIED']:assert required in text

@pytest.mark.parametrize('action',['preflight','apply','rollback'])
def test_determinism_python39_and_no_application_sdk_imports(assembled,action):
    b,items=assembled;raw,c=items[action];assert b.assemble(action)==(raw,c)
    ast.parse(raw,feature_version=(3,9));compile(raw,'<offline-payload>','exec')
    text=raw.decode()
    for bad in ['import boto3','import botocore','import requests','import api.app','setfacl ','chmod /srv','chown /srv']:assert bad not in text
    assert "--clear-groups"in text and c['action']==action

@pytest.mark.parametrize('action',['preflight','apply','rollback'])
def test_exact_transport_and_stdin_enabled(assembled,action):
    b,items=assembled;r=load('run');p,runner,values=b.references();values=list(values);w=dict(values[1]);w['profile']=lambda:{'target':'approved.invalid','identity_file':'/offline/key','known_hosts':'/offline/known'};values[1]=w
    argv=r.command(p,runner,values,action,b.ACTIONS[action][0])
    for option in ['StdinNull=no','StrictHostKeyChecking=yes','BatchMode=yes','IdentitiesOnly=yes','IdentityAgent=none','ForwardAgent=no','ConnectionAttempts=1']:assert option in argv
    assert argv[-1].endswith('/usr/bin/python3 -I -S -B -')and'-n'not in argv
    assert sum(a=='/usr/bin/ssh'for a in argv)==1

@pytest.mark.parametrize('field',['binding','transaction','release','action','version','duplicate','extra','nonfinite','truncated','exit','read_only_mutation'])
def test_response_source_binding_schema_and_sanitization(assembled,field):
    b,items=assembled;config=items['preflight'][1];p=load('protocol');report={'status':'PREFLIGHT_PASS','phase':'READ_ONLY','changed':False,'reason':'ACL_SEARCH_ONLY_PLAN_VERIFIED','target_uid':1000,'owner_group_mode_preserved':True,'mask_preserved':True,'protected_boundaries_denied':True,'rollback_ready':True}
    envelope={'version':1,**{k:config[k]for k in ['binding','transaction','release','action']},'report':report};code=0
    assert p.decode(json.dumps(envelope).encode(),0,config,set())==report
    if field in ['binding','transaction','release','action']:envelope[field]='UNAPPROVED'
    elif field=='version':envelope['version']=True
    elif field=='extra':report['raw_secret']='must never escape'
    elif field=='exit':code=1
    elif field=='read_only_mutation':report['changed']=True
    raw=json.dumps(envelope).encode()
    if field=='duplicate':raw=raw.replace(b'"version": 1',b'"version":1,"version":1')
    elif field=='nonfinite':raw=raw.replace(b'"version": 1',b'"version":NaN')
    elif field=='truncated':raw=raw[:-3]
    with pytest.raises((ValueError,TypeError)):p.decode(raw,code,config,set())

def test_unknown_error_never_discloses_raw_message(assembled):
    b,items=assembled
    # Execute the real source-bound driver with fake setup that fails before any
    # platform calls. Neither stderr nor exception text belongs in the response.
    raw,config=items['preflight'];tree=ast.parse(raw);tail=next(n for n in tree.body if isinstance(n,ast.Try)and any(isinstance(t,ast.ExceptHandler)for t in n.handlers))
    # It is the final top-level try (earlier functions contain their own try).
    assert isinstance(tail,ast.Try)
    start=tail.lineno-1;driver='\n'.join(raw.decode().splitlines()[start:])
    d=ns();d.update(C=config,REASONS=[],META=types.SimpleNamespace(trusted_commands=Mock(side_effect=RuntimeError('PRIVATE token path username')),Stop=type('MetaStop',(ValueError,),{})))
    lines=[];d['print']=lines.append
    with pytest.raises(SystemExit):exec(driver,d)
    observed=lines[0];assert 'PRIVATE'not in observed and 'username'not in observed
    assert json.loads(observed)['report']['reason']=='UNVERIFIED_OPERATION'

def test_original_packages_preserved():
    for rel,digest in [('realized-performance-release-v1','a3dceba7641ceaa9030709b1b7d4ce59460b54f5123b7e89f15d95bba39b0a83'),('realized-parent-traversal-diagnostic-v3','6fb6cd73259c8c6961cc954cc636603abb90a2fcae7983ade15578d7d166fcbe')]:
        assert hashlib.sha256((HERE.parent/rel/'MANIFEST.json').read_bytes()).hexdigest()==digest


def test_manifest_and_payload_integrity_when_built():
    if not(HERE/'MANIFEST.json').exists():pytest.skip('assembly precedes immutable freeze')
    r=load('run');digest=r.sha(r.read(HERE/'MANIFEST.json'))
    for action in ['preflight','apply','rollback']:r.verify(digest,action)

@pytest.mark.parametrize('category',['support','mask','probe','readback','second_observation','control_exists','idle'])
def test_complete_fresh_preflight_failure_gates(category):
    d=ns('acl_read.py','guards.py');before=state();events=[]
    class Context:
        fd=17
        acl=types.SimpleNamespace(validate_plan=lambda _:events.append('plan'),get=lambda _:MINIMAL)
        def __enter__(self):return self
        def __exit__(self,*_):pass
    d.update(Context=Context,idle=lambda:events.append('idle'),safe_parent=lambda _:events.append('parent'),observe=lambda _:copy.deepcopy(before),probe=lambda _:events.append('probe'))
    d['os']=types.SimpleNamespace(path=types.SimpleNamespace(lexists=lambda _:False),statvfs=lambda _:types.SimpleNamespace(f_bavail=10000,f_frsize=4096,f_favail=1000))
    def reject(code):raise d['Stop'](code)
    expected={'support':'POSIX_ACL_NOT_SUPPORTED','mask':'ACL_MODE_MISMATCH','probe':'PRODUCER_SECURITY_CONTEXT_UNVERIFIED','readback':'ACL_SUPPORT_READBACK_CHANGED','second_observation':'FRESH_ACL_OR_ISOLATION_DRIFT','control_exists':'TRANSACTION_ALREADY_EXISTS','idle':'PIPELINE_OR_WINDOW_GATE'}[category]
    if category=='support':Context.acl.validate_plan=lambda _:reject(expected)
    elif category=='mask':before['parent']['access_text']=MINIMAL.replace('group::r-x','group::rwx')
    elif category=='probe':d['probe']=lambda _:reject(expected)
    elif category=='readback':Context.acl.get=lambda _:MINIMAL.replace('group::r-x','group::rwx')
    elif category=='second_observation':
        seq=iter([before,{**before,'worker_groups':[1]}]);d['observe']=lambda _:copy.deepcopy(next(seq))
    elif category=='control_exists':d['os'].path.lexists=lambda _:True
    else:d['idle']=lambda:reject(expected)
    with pytest.raises(d['Stop'],match=expected):d['preflight']()
    assert d['CHANGED']is False

def test_complete_fresh_readonly_preflight_success():
    d=ns('acl_read.py','guards.py');before=state()
    class Context:
        fd=17;acl=types.SimpleNamespace(validate_plan=Mock(),get=lambda _:MINIMAL)
        def __enter__(self):return self
        def __exit__(self,*_):pass
    d.update(Context=Context,idle=Mock(),safe_parent=Mock(),observe=Mock(side_effect=[copy.deepcopy(before),copy.deepcopy(before)]),probe=Mock(),os=types.SimpleNamespace(path=types.SimpleNamespace(lexists=lambda _:False),statvfs=lambda _:types.SimpleNamespace(f_bavail=10000,f_frsize=4096,f_favail=1000)))
    result=d['preflight']();assert result['status']=='PREFLIGHT_PASS'and result['changed']is False
    d['probe'].assert_called_once_with(False)
    assert d['observe'].call_count==2

@pytest.mark.parametrize('errno',[38,95])
def test_libacl_fd_support_errors_are_specific(errno):
    d=ns('acl_read.py');obj=object.__new__(d['ACL']);obj.lib=types.SimpleNamespace(acl_get_fd=lambda _:0)
    old=d['ctypes'].get_errno
    try:
        d['ctypes'].get_errno=lambda:errno
        with pytest.raises(d['Stop'],match='POSIX_ACL_NOT_SUPPORTED'):obj.get(17)
    finally:d['ctypes'].get_errno=old

def test_libacl_memory_plan_never_changes_acl():
    d=ns('acl_read.py');obj=object.__new__(d['ACL']);obj.lib=types.SimpleNamespace(acl_from_text=Mock(return_value=77),acl_valid=Mock(return_value=0),acl_free=Mock())
    obj.validate_plan(d['plan'](MINIMAL));obj.lib.acl_free.assert_called_once_with(77)
    assert not hasattr(obj.lib,'acl_set_fd')

@pytest.mark.parametrize('step',['parse','valid'])
def test_libacl_invalid_plan_never_reaches_setter(step):
    d=ns('acl_read.py');obj=object.__new__(d['ACL']);obj.lib=types.SimpleNamespace(acl_from_text=Mock(return_value=0 if step=='parse'else 77),acl_valid=Mock(return_value=-1),acl_free=Mock())
    with pytest.raises(d['Stop']):obj.validate_plan(d['plan'](MINIMAL))
    if step=='valid':obj.lib.acl_free.assert_called_once_with(77)

def test_failed_acl_setter_has_no_chmod_fallback():
    d,old,current,memory,calls=transaction()
    class Fn:
        def __call__(self,fd,handle):return -1
    # Expose fake context, then replace just its setter.
    context=d['Context']().__enter__();context.acl.lib.acl_set_fd=Fn()
    with pytest.raises(d['Stop'],match='ACL_SET_FD_FAILED'):d['apply']()
    assert current==old and json.loads(memory['record.json'])['phase']=='CHANGING_ACL'
    assert not any(c[0]=='restore'for c in calls)

@pytest.mark.parametrize('field',['uid','gid','mode'])
def test_wrong_existing_parent_metadata_blocks_observation(field):
    d=ns('acl_read.py','guards.py');before=state();before['parent']['metadata'][field]=42
    d.update(root_fd=lambda:18,metadata=lambda _:before['parent']['metadata'],META=types.SimpleNamespace(identities=lambda:[1000]),snapshot=lambda *_:before['parent'])
    d['os']=types.SimpleNamespace(close=lambda _:None)
    with pytest.raises(d['Stop'],match='VERIFIED_PARENT_BASELINE_DRIFT'):d['observe'](types.SimpleNamespace(fd=17,acl=object()))

def test_worker_cannot_be_api_reader_group_member():
    d=ns('acl_read.py','guards.py');d.update(root_fd=lambda:18,metadata=lambda _:state()['parent']['metadata'],META=types.SimpleNamespace(identities=lambda:[992]))
    d['os']=types.SimpleNamespace(close=lambda _:None)
    with pytest.raises(d['Stop'],match='WORKER_API_READER_GROUP_FORBIDDEN'):d['observe'](types.SimpleNamespace(fd=17))

@pytest.mark.parametrize('action',['preflight','apply','rollback'])
def test_real_driver_failure_frame_with_simulated_ssh_and_stdin(assembled,tmp_path,action):
    b,items=assembled;raw,c=items[action];p,runner,values=b.references();supervisor=values[2]
    # Python simulator is not SSH. Execute exact assembled stdin payload with
    # only trusted_commands replaced by an offline blocker immediately before
    # the driver. No platform, identity, network or ACL operation runs.
    text=raw.decode();assert text.count(' META.trusted_commands()')==1
    safe=text.replace(' META.trusted_commands()'," raise Stop('LINUX_RUNTIME_REQUIRED')")
    simulator=tmp_path/'simulator.py';simulator.write_text('import sys\nsource=sys.stdin.buffer.read()\nexec(compile(source,"<simulated-ssh>","exec"))\n')
    result=supervisor([sys.executable,str(simulator)],input=safe.encode(),timeout=5,limit=8192,grace=5)
    assert result['failure']is None and result['returncode']==1 and result['stderr']==b''
    assert load('protocol').decode(result['stdout'],1,c,{'LINUX_RUNTIME_REQUIRED'})['reason']=='LINUX_RUNTIME_REQUIRED'


def test_setter_scope_and_private_write_scope_static():
    source=(HERE/'transaction.py').read_text();tree=ast.parse(source)
    assert source.count('result=setter(context.fd,handle)')==1
    for node in ast.walk(tree):
        if isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)and node.func.attr in {'chmod','chown'}:
            assert node.func.attr=='chmod'and ast.unparse(node.args[0])=='CONTROL'
    assert 'setfacl'not in source and 'os.chown'not in source
    d=ns('acl_read.py','guards.py','transaction.py')
    with pytest.raises(d['Stop'],match='JOURNAL_FILE_SCOPE'):d['read_private'](17,'../private')
    with pytest.raises(d['Stop'],match='JOURNAL_WRITE_SCOPE'):d['write_private'](17,'../private',b'bad')

@pytest.mark.parametrize('fault,expected',[
 ('none','PROBE_PASS'),('uid','PRODUCER_IDENTITY_MISMATCH'),('gid','PRODUCER_IDENTITY_MISMATCH'),
 ('saved_uid','PRODUCER_IDENTITY_MISMATCH'),('group','PRODUCER_IDENTITY_MISMATCH'),
 ('caps','PRODUCER_SECURITY_CONTEXT_UNVERIFIED'),('mode','PARENT_METADATA_MISMATCH'),
 ('read','PARENT_ACCESS_MISMATCH'),('write','PARENT_ACCESS_MISMATCH'),('search','PARENT_ACCESS_MISMATCH'),
 ('listing','PARENT_LISTING_AVAILABLE'),('child_access','PROTECTED_BOUNDARY_ACCESS'),('child_symlink','PROTECTED_BOUNDARY_TYPE')])
def test_actual_unprivileged_probe_with_mock_kernel(fault,expected):
    d={'__name__':'not_main','EXPECT_SEARCH':True};exec((HERE/'probe.py').read_bytes(),d)
    info=types.SimpleNamespace(st_mode=stat.S_IFDIR|0o750,st_uid=0,st_gid=992)
    if fault=='mode':info.st_mode=stat.S_IFDIR|0o755
    def open_(path,flags,**kwargs):
        if flags&getattr(os,'O_PATH',0x200000):return 17
        if fault=='listing'and path=='/srv/powerflow':return 18
        raise PermissionError(13,'private never retained')
    def access(path,mode,**kwargs):
        if path=='.':return mode==os.X_OK and fault!='search'or mode==os.R_OK and fault=='read'or mode==os.W_OK and fault=='write'
        return fault=='child_access'
    fake=types.SimpleNamespace(O_PATH=0x200000,O_DIRECTORY=os.O_DIRECTORY,O_NOFOLLOW=os.O_NOFOLLOW,O_RDONLY=os.O_RDONLY,X_OK=os.X_OK,R_OK=os.R_OK,W_OK=os.W_OK,
      getresuid=lambda:(1001,)*3 if fault=='uid'else(1000,1000,0)if fault=='saved_uid'else(1000,)*3,
      getresgid=lambda:(1001,)*3 if fault=='gid'else(1000,)*3,getgroups=lambda:[992]if fault=='group'else[],open=open_,fstat=lambda _:info,close=lambda _:None,access=access,
      stat=lambda *a,**k:types.SimpleNamespace(st_mode=stat.S_IFLNK|0o750)if fault=='child_symlink'else info)
    d.update(os=fake,sys=types.SimpleNamespace(platform='linux'),security_context=lambda:fault!='caps')
    value=d['check']();assert value['reason']==expected
    assert set(value)=={'version','status','reason','parent_search','parent_read','parent_write','boundary'}


def test_numeric_acl_render_bounds_and_frees_handles():
    d=ns('acl_read.py');obj=object.__new__(d['ACL']);buffer=d['ctypes'].create_string_buffer(MINIMAL.encode())
    obj.lib=types.SimpleNamespace(acl_valid=lambda _:0,acl_entries=lambda _:3,acl_to_any_text=Mock(return_value=d['ctypes'].addressof(buffer)),acl_free=Mock())
    assert obj.text(77)==MINIMAL
    assert obj.lib.acl_to_any_text.call_args.args[1:]==(None,b'\n',8)
    assert obj.lib.acl_free.call_count==2


def test_invalid_library_ownership_blocks_before_loading(monkeypatch):
    d=ns('acl_read.py');calls=[]
    class FakePath:
        def __init__(self,*_):self.parent=self;self.name='libacl.so.1.2'
        def resolve(self,**_):return self
    fakeos=types.SimpleNamespace(environ={},open=lambda *_:17,O_RDONLY=0,O_NOFOLLOW=1,O_NOATIME=2,fstat=lambda _:types.SimpleNamespace(st_mode=stat.S_IFREG|0o666,st_uid=1000,st_size=1),close=lambda _:calls.append('close'))
    fake_ctypes=types.SimpleNamespace(CDLL=Mock())
    d.update(Path=FakePath,safe_parent=lambda _:None,os=fakeos,ctypes=fake_ctypes)
    with pytest.raises(d['Stop'],match='LIBACL_METADATA_UNSAFE'):d['ACL']()
    assert calls==['close'];fake_ctypes.CDLL.assert_not_called()
