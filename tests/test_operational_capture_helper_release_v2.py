"""Offline helper-only release: immutable assembly and isolated transaction files.
Root UID/GID and Linux runtime checks are mocked, not claimed as live validation.
"""
import ast
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace,ModuleType
import pytest
ROOT=Path(__file__).resolve().parents[1];FOLDER=ROOT/'deploy/staging/operational-capture-helper-release-v2'
def load(name,extra=None):
 m=ModuleType('offline_helper_'+name);m.__file__=str(FOLDER/(name+'.py'))
 if extra:m.__dict__.update(extra)
 exec(compile((FOLDER/(name+'.py')).read_bytes(),'<offline-helper-'+name+'>','exec'),m.__dict__);return m
@pytest.fixture(scope='module')
def package():
 b=load('build');old=json.loads((ROOT/'deploy/staging/operational-evidence-release-v5/MANIFEST.json').read_bytes())
 assert b.sha((ROOT/'deploy/staging/operational-evidence-release-v5/MANIFEST.json').read_bytes())==b.V5
 return b,old,b.config(old)

def test_exact_scope_and_candidate(package):
 b,old,c=package
 assert set(c['files'])=={'helper/'+k for k in ['bootstrap.py','TOOLS.json','shared/__init__.py','shared/forecast_publication.py','shared/operational_evidence.py','shared/operational_evidence_store.py','shared/operational_evidence_producer.py','shared/operational_capture.py']}|{'launcher','sudoers'}
 assert not any(k.startswith(('api/','static/','worker/')) for k in c['files'])
 for key,item in c['files'].items():
  raw=base64.b64decode(item['base64']);assert len(raw)==item['bytes'] and b.sha(raw)==item['sha256']
  if key.startswith('helper/') and key not in {'helper/bootstrap.py','helper/TOOLS.json','helper/shared/operational_evidence_producer.py'}:assert item['sha256']==old['config']['files'][key]['sha256']
 assert c['files']['helper/shared/operational_evidence_producer.py']['sha256']=='f0e94ea827c76cdfbd84ad1eb686d65f490c52babd5bb15379c4d739e4dc7477'

def test_privilege_scope_unchanged(package):
 b,old,c=package
 old_launcher=(ROOT/old['config']['files']['launcher']['source']).read_bytes();new_launcher=base64.b64decode(c['files']['launcher']['base64'])
 assert new_launcher.replace(c['new_root'].encode(),c['old_root'].encode())==old_launcher
 old_rule=(ROOT/old['config']['files']['sudoers']['source']).read_bytes();new_rule=base64.b64decode(c['files']['sudoers']['base64'])
 assert new_rule.replace(c['files']['launcher']['sha256'].encode(),c['old_files']['launcher']['sha256'].encode())==old_rule
 assert b'NOSETENV' in new_rule and b' --state 'in new_rule
 assert json.loads(base64.b64decode(c['files']['helper/TOOLS.json']['base64']))=={k[7:]:v['sha256'] for k,v in c['files'].items() if k.startswith('helper/') and k!='helper/TOOLS.json'}

def test_memory_import_probe_readonly(package,monkeypatch):
 b,old,c=package
 def need(v,code):
  if not v:raise ValueError(code)
 m=load('preflight',{'C':c,'OLD_PLAN':SimpleNamespace(need=need)})
 import socket,subprocess
 monkeypatch.setattr(socket,'create_connection',lambda *a,**kw:pytest.fail('Network'))
 monkeypatch.setattr(subprocess,'Popen',lambda *a,**kw:pytest.fail('Process'))
 m.memory_probe()
 import sys
 assert not any(k.startswith('operational_helper_probe') for k in sys.modules)

@pytest.fixture
def transaction(package,tmp_path,monkeypatch):
 b,old,config=package;c=copy.deepcopy(config);c['new_root']=str(tmp_path/'new');c['control']=str(tmp_path/'control')
 launcher=tmp_path/'launcher';rule=tmp_path/'rule'
 for path,key in [(launcher,'launcher'),(rule,'sudoers')]:path.write_bytes((ROOT/old['config']['files'][key]['source']).read_bytes());path.chmod(c['old_files'][key]['mode'])
 def need(v,code):
  if not v:raise ValueError(code)
 def safe(path,*args):
  assert path==tmp_path or path.is_relative_to(tmp_path)
  assert path.is_dir() and not path.is_symlink() and path.stat().st_uid==os.getuid() and not path.stat().st_mode&0o022
 def snap(path,uid=0,gid=0,mode=0o644):
  assert uid==gid==0
  assert path.is_file() and not path.is_symlink() and path.stat().st_uid==os.getuid() and path.stat().st_nlink==1 and path.stat().st_mode&0o777==mode
  raw=path.read_bytes();return {'sha256':b.sha(raw),'bytes':len(raw),'uid':0,'gid':0,'mode':mode},raw
 commands=[]
 def process(argv,input=b''):
  assert argv in (['/usr/sbin/visudo','-c'],['/usr/sbin/visudo','-cf','-']);commands.append(argv)
 p=SimpleNamespace(safe=safe,snap=snap,read=lambda path,*a:path.read_bytes(),LAUNCHER=launcher,RULE=rule,process=process)
 m=load('preflight',{'C':c,'OLD_PLAN':SimpleNamespace(need=need),'P':p})
 exec(compile((FOLDER/'transaction.py').read_bytes(),'<offline-transaction>','exec'),m.__dict__)
 # Ownership syscalls are simulated; only fixture paths are written.
 def chown(path,uid,gid):assert uid==gid==0 and Path(path).is_relative_to(tmp_path)
 def fchown(fd,uid,gid):assert uid==gid==0
 monkeypatch.setattr(m.os,'chown',chown);monkeypatch.setattr(m.os,'fchown',fchown)
 actual_lstat=Path.lstat
 def root_metadata(path):
  info=actual_lstat(path)
  if path.is_relative_to(tmp_path):
   values=list(info);values[4]=values[5]=0;return os.stat_result(values)
  return info
 monkeypatch.setattr(Path,'lstat',root_metadata)
 def tree(root,expected,partial=False):
  assert root.is_dir() and not root.is_symlink() and root.stat().st_mode&0o777==0o700
  seen={}
  for f in root.rglob('*'):
   assert not f.is_symlink()
   if f.is_dir():assert f==root/'shared' and f.stat().st_mode&0o777==0o700
   else:
    rel=f.relative_to(root).as_posix();assert rel in expected;meta,_=snap(f,0,0,0o600);assert meta['sha256']==expected[rel];seen[rel]=meta['sha256']
  assert partial or seen==expected
 m.tree=tree;m.installed_probe=lambda:tree(m.NEW,m.expected_new());m.idle=lambda:None
 baseline={'production':'stable-prod','forecast':{'pointer':None},'store':'empty-op','policy':'stable-policy','v5_record':'verified-v5'}
 def common(privilege='old'):
  result=copy.deepcopy(baseline);result['privileges']={}
  for key in ['launcher','sudoers']:
   meta,_=snap(m.target(key),0,0,c['old_files'][key]['mode'])
   allowed={c['old_files'][key]['sha256']} if privilege=='old' else {c['files'][key]['sha256']} if privilege=='new' else {c['old_files'][key]['sha256'],c['files'][key]['sha256']}
   need(meta['sha256']in allowed,'PRIVILEGE_DRIFT');result['privileges'][key]=meta
  return result
 m.common=common
 return m,baseline,commands

def test_apply_and_independent_rollback(transaction):
 m,baseline,commands=transaction
 result=m.apply();assert result['status']=='APPLIED' and result['services_restarted']is False
 record=m.load_record();m.verified_backups(record)
 for key in ['launcher','sudoers']:
  assert (m.CONTROL/(key+'.backup')).stat().st_ino!=(m.CONTROL/(key+'.independent')).stat().st_ino
 assert m.P.LAUNCHER.read_bytes()==m.artifact('launcher')
 baseline['store']='new-natural-record';baseline['forecast']={'pointer':'new-natural-forecast'}
 result=m.rollback();assert result['status']=='ROLLED_BACK' and result['retained_versioned_helper']
 assert m.NEW.exists() and baseline['store']=='new-natural-record'
 for key in ['launcher','sudoers']:assert m.sha(m.target(key).read_bytes())==m.C['old_files'][key]['sha256']
 assert all(argv[0]=='/usr/sbin/visudo' for argv in commands)

@pytest.mark.parametrize('phase',['install','rule','activate'])
def test_partial_failure_can_rollback_without_retry(transaction,monkeypatch,phase):
 m,_,_=transaction;original=m.write;writes=[]
 def write(path,*a,**kw):
  writes.append(path)
  if phase=='install' and path.name=='shared':raise OSError('fixture')
  if phase=='install' and path==m.NEW/'bootstrap.py':raise OSError('fixture')
  if phase=='rule' and path==m.P.RULE:raise OSError('fixture')
  if phase=='activate' and path==m.P.LAUNCHER:raise OSError('fixture')
  return original(path,*a,**kw)
 monkeypatch.setattr(m,'write',write)
 with pytest.raises(OSError):m.apply()
 assert m.load_record()['phase']in {'INSTALL','READY','ACTIVATE'}
 monkeypatch.setattr(m,'write',original)
 assert m.rollback()['status']=='ROLLED_BACK'
 assert m.sha(m.P.LAUNCHER.read_bytes())==m.C['old_files']['launcher']['sha256']

@pytest.mark.parametrize('kind',['backup','hardlink','launcher_drift','tree_drift','creation_identity'])
def test_rollback_stops_before_mutation_on_drift(transaction,kind):
 m,_,_=transaction;m.apply();before=m.P.LAUNCHER.read_bytes();record=m.load_record()
 if kind=='backup':(m.CONTROL/'launcher.backup').write_bytes(b'changed')
 elif kind=='hardlink':
  p=m.CONTROL/'launcher.independent';p.unlink();p.hardlink_to(m.CONTROL/'launcher.backup')
 elif kind=='launcher_drift':m.P.LAUNCHER.write_bytes(b'changed');before=b'changed'
 elif kind=='tree_drift':(m.NEW/'bootstrap.py').write_bytes(b'changed')
 else:record['new_root_identity'][1]+=1;m.save(record,'APPLIED')
 with pytest.raises((ValueError,AssertionError)):m.rollback()
 assert m.P.LAUNCHER.read_bytes()==before and m.load_record()['phase']=='APPLIED'

def test_apply_stops_before_first_write(transaction,monkeypatch):
 m,_,_=transaction;original=m.P.LAUNCHER.read_bytes()
 monkeypatch.setattr(m,'fresh',lambda:(_ for _ in ()).throw(ValueError('PIPELINE_OR_WINDOW_GATE')))
 with pytest.raises(ValueError,match='PIPELINE_OR_WINDOW_GATE'):m.apply()
 assert not m.CONTROL.exists() and not m.NEW.exists() and m.P.LAUNCHER.read_bytes()==original

def test_only_approved_mutation_paths(transaction):
 m,_,_=transaction
 assert m.P.LAUNCHER in m.writable() and m.P.RULE in m.writable()
 with pytest.raises(ValueError,match='WRITE_SCOPE'):m.write(m.NEW.parent/'unrelated',b'x',exclusive=True)
 with pytest.raises(ValueError,match='DIRECTORY_SCOPE'):m.mkdir(m.NEW.parent/'unrelated')
 assert not any('forecast-publications' in str(p) or 'operational-publications'in str(p) for p in m.writable())

def test_new_file_collision_not_overwritten(transaction):
 m,_,_=transaction;m.mkdir(m.CONTROL);p=m.CONTROL/'launcher.backup';p.write_bytes(b'keep')
 with pytest.raises(ValueError,match='WRITE_DRIFT'):m.write(p,b'new',exclusive=True)
 assert p.read_bytes()==b'keep'

def test_immutable_payloads_and_python39(package):
 b,old,c=package;raw=(FOLDER/'MANIFEST.json').read_bytes();manifest=json.loads(raw)
 assert manifest['execution_authorized']is False and manifest['config']==c
 for rel,digest in manifest['artifacts'].items():assert b.sha((ROOT/rel).read_bytes())==digest
 prefix=(ROOT/'deploy/staging/operational-evidence-release-v5/accept.payload.py').read_bytes()
 assert b.sha(prefix)==old['payloads']['accept']['sha256']
 blobs={name:(FOLDER/name).read_bytes() for name in b.FILES}
 for action in ['preflight','apply','rollback']:
  payload=(FOLDER/(action+'.payload.py')).read_bytes();ast.parse(payload,feature_version=(3,9))
  assert b.sha(payload)==manifest['payloads'][action]['sha256'] and len(payload)==manifest['payloads'][action]['bytes']
  assert b.assemble(action,prefix,c,blobs)==payload
 for name in b.FILES:
  if name.endswith('.py'):ast.parse((FOLDER/name).read_text(),feature_version=(3,9))
 assert b.assemble('apply',prefix,c,blobs)==b.assemble('apply',prefix,c,blobs)

def test_preflight_cannot_dispatch_mutation(package):
 b,old,c=package;payload=(FOLDER/'preflight.payload.py').read_bytes();tree=ast.parse(payload)
 embedded=[n.args[0].args[0].value for n in tree.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='exec' for n in [n.value] if n.args and isinstance(n.args[0],ast.Call) and isinstance(n.args[0].args[0],ast.Constant)]
 assert not any(b'def apply()'in v or b'def rollback()'in v for v in embedded if isinstance(v,bytes))
 source=(FOLDER/'preflight.py').read_text();parsed=ast.parse(source)
 assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {'mkdir','write_bytes','write_text','replace','chmod','chown','unlink','publish','publish_terminal','capture_terminal'} for n in ast.walk(parsed))
 tokens=[n.value for n in ast.walk(ast.parse((FOLDER/'transaction.py').read_text())) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
 assert not set(tokens)&{'restart','reload','PATCH','trigger_run'}

def test_runner_bad_integrity_never_reaches_transport():
 r=load('run')
 with pytest.raises(AssertionError):r.verify('0'*64,'preflight')

@pytest.mark.parametrize('action',['preflight','apply','rollback'])
def test_local_check_never_connects(action,monkeypatch,capsys):
 r=load('run');r.verify=lambda *a:(b'payload',SimpleNamespace(profile=lambda:pytest.fail('Identity/transport accessed')),None)
 monkeypatch.setattr('sys.argv',['run.py',action,'--manifest-sha256','0'*64,'--local-check'])
 assert r.main()==0 and json.loads(capsys.readouterr().out)['ssh_attempts']==0

@pytest.mark.parametrize('kind',['manifest','module'])
def test_candidate_binding_rejects_local_drift(package,monkeypatch,kind):
 b,old,_=package;actual=b.read
 def read(path,*a,**kw):
  raw=actual(path,*a,**kw)
  if str(path).endswith('operational-capture-correction-v1/'+('MANIFEST.json'if kind=='manifest'else'operational_evidence_producer.py')):return raw+b'changed'
  return raw
 monkeypatch.setattr(b,'read',read)
 with pytest.raises(AssertionError):b.config(old)

def test_activation_is_last_and_import_checked_first(transaction,monkeypatch):
 m,_,_=transaction;events=[];write=m.write;probe=m.installed_probe
 def tracked(path,*args,**kw):events.append(str(path));return write(path,*args,**kw)
 def checked():events.append('IMPORT');return probe()
 monkeypatch.setattr(m,'write',tracked);monkeypatch.setattr(m,'installed_probe',checked)
 m.apply()
 rule=events.index(str(m.P.RULE));launcher=events.index(str(m.P.LAUNCHER))
 assert events.index('IMPORT')<rule<launcher
 assert all(events.index(str(m.target(key)))<rule for key in m.C['files'] if key.startswith('helper/'))
 assert events[-1]==str(m.CONTROL/'record.json')

def test_failed_backup_never_installs_or_activates(transaction,monkeypatch):
 m,_,_=transaction;write=m.write
 def corrupt(path,*a,**kw):
  result=write(path,*a,**kw)
  if path==m.CONTROL/'sudoers.independent':path.write_bytes(b'corrupted')
  return result
 monkeypatch.setattr(m,'write',corrupt)
 with pytest.raises(ValueError,match='BACKUP_HASH'):m.apply()
 assert not m.NEW.exists()
 for key in ['launcher','sudoers']:assert m.sha(m.target(key).read_bytes())==m.C['old_files'][key]['sha256']

def test_failed_post_activation_stops_without_rollback(transaction,monkeypatch):
 m,_,_=transaction;common=m.common
 def check(mode='old'):
  if mode=='new':raise ValueError('HEALTH_FAILED')
  return common(mode)
 monkeypatch.setattr(m,'common',check)
 with pytest.raises(ValueError,match='HEALTH_FAILED'):m.apply()
 assert m.sha(m.P.LAUNCHER.read_bytes())==m.C['files']['launcher']['sha256']
 assert m.load_record()['phase']=='ACTIVATE'
 monkeypatch.setattr(m,'common',common)
 assert m.rollback()['status']=='ROLLED_BACK'

@pytest.mark.parametrize('kind',['empty','valid','partial','symlink'])
def test_store_readonly_snapshot_bounds(package,tmp_path,monkeypatch,kind):
 from test_operational_evidence import fixture,encoded
 from shared import operational_evidence as op
 b,old,c=package;root=tmp_path/'store';root.mkdir(mode=0o750);(root/'releases').mkdir(mode=0o750)
 (root/'contract').write_bytes(b'powerflow-operational-evidence-v1\n');(root/'contract').chmod(0o640)
 if kind in {'valid','symlink'}:
  raw,digest=encoded(fixture());release=root/'releases'/digest;release.mkdir(mode=0o750);(release/'evidence.json').write_bytes(raw);(release/'evidence.json').chmod(0o640)
  pointer=root/'current'
  if kind=='valid':pointer.write_text(digest+'\n');pointer.chmod(0o640)
  else:pointer.symlink_to(release/'evidence.json')
 if kind=='partial':(root/'releases'/('.partial-'+'a'*32)).mkdir(mode=0o750)
 original=Path.lstat
 def metadata(path):
  info=original(path)
  if path.is_relative_to(root):
   values=list(info);values[4]=0;values[5]=992;return os.stat_result(values)
  return info
 monkeypatch.setattr(Path,'lstat',metadata)
 def need(v,code):
  if not v:raise ValueError(code)
 def safe(path,*a):assert not path.is_symlink()
 def snap(path,uid,gid,mode):
  safe(path);assert path.stat().st_mode&0o777==mode;raw=path.read_bytes();return {'sha256':b.sha(raw)},raw
 m=load('preflight',{'C':c,'P':SimpleNamespace(STORE=root,safe=safe,snap=snap),'OLD_PLAN':SimpleNamespace(need=need),'OP':op})
 before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()and not p.is_symlink()}
 if kind in {'empty','valid'}:assert len(m.store_snapshot())==64
 else:
  with pytest.raises((AssertionError,ValueError)):m.store_snapshot()
 assert before=={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()and not p.is_symlink()}

def test_assembler_never_refreshes_an_existing_release(package,tmp_path):
 b,_,_=package;manifest=tmp_path/'MANIFEST.json';payload=tmp_path/'payload.py'
 b.emit({manifest:b'bound',payload:b'code'});before=manifest.stat().st_mtime_ns
 b.emit({manifest:b'bound',payload:b'code'});assert manifest.stat().st_mtime_ns==before
 absent=tmp_path/'new'
 with pytest.raises(AssertionError,match='IMMUTABLE_RELEASE_DRIFT'):b.emit({absent:b'must not write',manifest:b'changed'})
 assert not absent.exists() and manifest.read_bytes()==b'bound' and payload.read_bytes()==b'code'

@pytest.mark.parametrize('scenario',['scheduling_window','active_pipeline'])
@pytest.mark.parametrize('legacy',[False,True])
def test_complete_assembled_preflight_preserves_idle_guard(package,tmp_path,monkeypatch,capsys,scenario,legacy):
 """Execute the real assembled dispatch and guard chain, with host I/O mocked."""
 import sys
 b,old,c=package
 prefix=(ROOT/'deploy/staging/operational-evidence-release-v5/accept.payload.py').read_bytes()
 blobs={name:(FOLDER/name).read_bytes() for name in b.FILES}
 payload=(FOLDER.parent/'operational-capture-helper-release-v1/preflight.payload.py').read_bytes()if legacy else b.assemble('preflight',prefix,c,blobs);tree=ast.parse(payload)
 index=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Try))
 saved={k:v for k,v in sys.modules.items() if k=='shared'or k.startswith('shared.')}
 namespace={}
 try:
  exec(compile(ast.Module(body=tree.body[:index],type_ignores=[]),'<mock-complete-preflight>','exec'),namespace)
  helper=namespace['HELPER'];helper.NEW=tmp_path/'absent-helper';helper.CONTROL=tmp_path/'absent-transaction'
  monkeypatch.setattr(namespace['PREFLIGHT'],'safe',lambda *a,**kw:None)
  monkeypatch.setattr(sys,'platform','linux');monkeypatch.setattr(os,'getuid',lambda:0);monkeypatch.setattr(os,'geteuid',lambda:0)
  monkeypatch.setattr(os,'uname',lambda:os.uname_result(('Linux','fixture','fixture','fixture','x86_64')))
  monkeypatch.setattr(os,'O_NOATIME',getattr(os,'O_NOATIME',0x40000),raising=False)
  monkeypatch.setattr(helper.pwd,'getpwnam',lambda name:SimpleNamespace(pw_uid=1000 if name=='ec2-user'else 992,pw_gid=1000 if name=='ec2-user'else 992))
  original=Path.is_dir
  monkeypatch.setattr(Path,'is_dir',lambda path:True if str(path)=='/proc/self/fd'else original(path))
  calls=[]
  def pipeline():
   calls.append(scenario)
   return {'safe_window':scenario!='scheduling_window','active_runs':1 if scenario=='active_pipeline'else 0},False
  namespace['BASE'].__dict__['pipeline']=pipeline
  namespace['BASE'].__dict__['bounded_run']=lambda *a,**kw:pytest.fail('Unexpected external command')
  namespace['BASE'].__dict__['api']=lambda *a,**kw:pytest.fail('Unexpected API request')
  if legacy:
   with pytest.raises(NameError,match='OP')as masked:exec(compile(ast.Module(body=tree.body[index:],type_ignores=[]),'<mock-complete-preflight>','exec'),namespace)
   assert str(masked.value.__context__)=='PIPELINE_OR_WINDOW_GATE' and calls==[scenario]
   assert capsys.readouterr().out=='' and not helper.NEW.exists() and not helper.CONTROL.exists()
   return
  with pytest.raises(SystemExit)as stopped:exec(compile(ast.Module(body=tree.body[index:],type_ignores=[]),'<mock-complete-preflight>','exec'),namespace)
  result=json.loads(capsys.readouterr().out)
  assert stopped.value.code==1 and result['status']=='BLOCKED' and result['changed']is False
  assert result['reason']=='PIPELINE_OR_WINDOW_GATE' and result['error_class']=='Stop' and result['function']=='idle'
  assert calls==[scenario] and not helper.NEW.exists() and not helper.CONTROL.exists()
  assert load('run').validate_report(result)==result
 finally:
  for key in list(sys.modules):
   if key=='shared'or key.startswith('shared.'):del sys.modules[key]
  sys.modules.update(saved)

@pytest.mark.parametrize('kind,reason,error_class',[('contract','TIMESTAMP','InvalidEvidence'),('unknown','UNVERIFIED_HOST_OPERATION','TypeError')])
def test_complete_dispatch_exception_namespaces_and_redaction(package,monkeypatch,capsys,kind,reason,error_class):
 import sys
 b,old,c=package;prefix=(ROOT/'deploy/staging/operational-evidence-release-v5/accept.payload.py').read_bytes()
 payload=b.assemble('preflight',prefix,c,{n:(FOLDER/n).read_bytes() for n in b.FILES});tree=ast.parse(payload);index=next(i for i,n in enumerate(tree.body)if isinstance(n,ast.Try))
 saved={k:v for k,v in sys.modules.items()if k=='shared'or k.startswith('shared.')};namespace={}
 try:
  exec(compile(ast.Module(body=tree.body[:index],type_ignores=[]),'<mock-preflight-prefix>','exec'),namespace)
  assert 'OP'not in namespace and hasattr(namespace['HELPER'],'OP')
  error=namespace['HELPER'].OP.InvalidEvidence('TIMESTAMP')if kind=='contract'else TypeError('SECRET_TOKEN_AND_PRIVATE_PATH')
  def fail():raise error
  namespace['HELPER'].preflight_report=fail
  with pytest.raises(SystemExit):exec(compile(ast.Module(body=tree.body[index:],type_ignores=[]),'<mock-dispatch>','exec'),namespace)
  result=json.loads(capsys.readouterr().out)
  assert result['reason']==reason and result['error_class']==error_class and result['changed']is False
  assert 'SECRET'not in json.dumps(result) and load('run').validate_report(result)==result
 finally:
  for key in list(sys.modules):
   if key=='shared'or key.startswith('shared.'):del sys.modules[key]
  sys.modules.update(saved)

def test_v1_and_helper_security_contents_unchanged(package):
 b,old,c=package
 v1=FOLDER.parent/'operational-capture-helper-release-v1';manifest=json.loads((v1/'MANIFEST.json').read_bytes())
 assert b.sha((v1/'MANIFEST.json').read_bytes())=='cf1551fd6f7f6004d1a36d101f95057a42fa93e2e939d65d247a70d6a4e8f8ce'
 assert c['files']==manifest['config']['files'] and c['old_files']==manifest['config']['old_files']
 for name in ['preflight.py','transaction.py']:assert (FOLDER/name).read_bytes()==(v1/name).read_bytes()
 for rel,digest in manifest['artifacts'].items():assert b.sha((ROOT/rel).read_bytes())==digest
 for action,item in manifest['payloads'].items():assert b.sha((v1/(action+'.payload.py')).read_bytes())==item['sha256']

@pytest.mark.parametrize('action',['apply','rollback'])
def test_assembled_partial_failure_retains_guard_and_mutation_state(package,capsys,action):
 import sys
 b,_,c=package;prefix=(ROOT/'deploy/staging/operational-evidence-release-v5/accept.payload.py').read_bytes()
 tree=ast.parse(b.assemble(action,prefix,c,{n:(FOLDER/n).read_bytes()for n in b.FILES}));index=next(i for i,n in enumerate(tree.body)if isinstance(n,ast.Try))
 saved={k:v for k,v in sys.modules.items()if k=='shared'or k.startswith('shared.')};ns={}
 try:
  exec(compile(ast.Module(body=tree.body[:index],type_ignores=[]),'<mock-action-prefix>','exec'),ns)
  helper=ns['HELPER'];helper.CHANGED=True;helper.PHASE='ACTIVATE'if action=='apply'else'ROLLBACK'
  def fail():raise ns['PLAN'].Stop('BACKUP_HASH')
  setattr(helper,action,fail)
  with pytest.raises(SystemExit)as stopped:exec(compile(ast.Module(body=tree.body[index:],type_ignores=[]),'<mock-action-dispatch>','exec'),ns)
  result=json.loads(capsys.readouterr().out)
  assert stopped.value.code==1 and result['status']=='FAILED' and result['changed']is True and result['reason']=='BACKUP_HASH' and result['phase']==helper.PHASE
  load('run').validate_report(result)
 finally:
  for key in list(sys.modules):
   if key=='shared'or key.startswith('shared.'):del sys.modules[key]
  sys.modules.update(saved)
