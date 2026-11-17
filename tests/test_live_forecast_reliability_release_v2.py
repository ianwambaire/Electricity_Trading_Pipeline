"""Offline guards/transaction tests. Linux identities/services are explicitly mocked."""
import ast
import importlib.util
import json
import os
import stat
from pathlib import Path
import subprocess
import sys
import types
import pytest

ROOT=Path(__file__).parents[1]
HERE=ROOT/'deploy/staging/live-forecast-reliability-release-v2'
def load(name):
    s=importlib.util.spec_from_file_location('rel_'+name,HERE/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
class Stop(ValueError):pass
def need(v,code):
    if not v:raise Stop(code)
@pytest.fixture(scope='module')
def package():
    b=load('build');prefix,_,_,v5,h=b.baseline();return b,prefix,v5,h,b.config(v5),{n:b.read(HERE/n) for n in b.FILES}
def test_exact_scope_and_retained_assets(package):
    b,_,v5,_,c,_=package;old=v5['config']['files']
    assert {k[4:] for k,v in c['files'].items() if k.startswith('api/') and (k not in old or v['sha256']!=old[k]['sha256'])}==b.CHANGED
    for k,v in old.items():
        if k.startswith('static/assets/'):assert c['files'][k]['sha256']==v['sha256']
    assert c['files']['static/build-config.json']['sha256']==old['static/build-config.json']['sha256']
    assert c['files']['api/src/shared/forecast_publication.py']['sha256']=='a88906ef45688dbee98171376a53ff64a6b88e68a800a0a422a1a7375e452902'
    assert not any(k.startswith(('worker/','helper/'))or k in {'launcher','sudoers','nginx'} for k in c['files'])
def test_historical_failure_is_existing_v5_pipeline_not_reliability(package):
    b,_,v5,_,_,_=package;name='src/scheduled_pipeline.py';actual=b.sha((ROOT/name).read_bytes())
    old=json.loads((ROOT/'deploy/staging/forecast-publication/AUTOMATION-SOURCE-MANIFEST.json').read_bytes())
    assert actual==v5['config']['files']['worker/'+name]['sha256'] and actual!=old['sources'][name]['sha256']
    for k,h in old['installed_tools'].items():
        p=ROOT/'src'/k if k.startswith('shared/') else ROOT/'deploy/staging/forecast-publication'/k
        assert b.sha(p.read_bytes())==h
@pytest.mark.parametrize('action',['preflight','apply','rollback','accept'])
def test_assembly_deterministic_immutable_and_python39(package,action):
    b,p,_,h,c,blobs=package;raw=b.assemble(action,p,c,blobs,h);assert raw==b.assemble(action,p,c,blobs,h);ast.parse(raw,feature_version=(3,9));assert len(raw)<4*1024*1024
    if (HERE/'MANIFEST.json').exists():
        m=json.loads((HERE/'MANIFEST.json').read_bytes());assert raw==(HERE/(action+'.payload.py')).read_bytes()
        assert m['payloads'][action]=={'sha256':b.sha(raw),'bytes':len(raw)}
@pytest.mark.parametrize('action',['preflight','accept'])
def test_readonly_excludes_mutation_entrypoints(package,action):
    b,p,_,h,c,blobs=package;raw=b.assemble(action,p,c,blobs,h);assert b'<verified-reliability-transaction>'not in raw
    functions=set()
    for n in ast.walk(ast.parse(raw)):
        if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='compile'and n.args and isinstance(n.args[0],ast.Constant)and isinstance(n.args[0].value,(str,bytes)):
            functions.update(t.name for t in ast.walk(ast.parse(n.args[0].value)) if isinstance(t,(ast.FunctionDef,ast.AsyncFunctionDef)))
    assert not {'apply','rollback','write','mkdir','restart','pointer','publish','deliver_terminal'}&functions
def test_immutable_emit_no_partial_refresh(tmp_path):
    b=load('build');p=tmp_path/'old';q=tmp_path/'new';p.write_bytes(b'old')
    with pytest.raises(AssertionError,match='IMMUTABLE_RELEASE_DRIFT'):b.emit({q:b'new',p:b'new'})
    assert p.read_bytes()==b'old' and not q.exists()
@pytest.mark.parametrize('p',['/etc/passwd','../x','a//b','a/./b','a/../b','a\\b',''])
def test_traversal(p):assert not load('build').safe_rel(p)

@pytest.fixture
def job(tmp_path,monkeypatch):
    b=load('build');oldapi=tmp_path/'old-api';oldstatic=tmp_path/'old-static';v5=tmp_path/'v5';venv=tmp_path/'runtime'
    for p in [oldapi,oldstatic,v5,venv]:p.mkdir()
    (oldapi/'old.py').write_bytes(b'old');(oldstatic/'index.html').write_bytes(b'old-index');(oldapi/'.venv-api').symlink_to(venv)
    api_link=tmp_path/'api-current';static_link=tmp_path/'static-current';api_link.symlink_to(oldapi);static_link.symlink_to(oldstatic)
    c={'api':str(tmp_path/'new-api'),'static':str(tmp_path/'new-static'),'control':str(tmp_path/'journal'),'release':b.RELEASE,'transaction':b.TRANSACTION,'binding':'binding','files':{}}
    import base64
    for k,raw in [('api/src/api/test.py',b'new-api'),('static/index.html',b'new-static')]:c['files'][k]={'sha256':b.sha(raw),'bytes':len(raw),'base64':base64.b64encode(raw).decode()}
    closure={'sha256':'runtime','files':1,'bytes':1,'imports':'PASS'};calls=[]
    fingerprint={'production':'p','forecast':{'bundle':'b'},'store':'s','helper':'h','policy':'d','environment':'e','nginx':'n'}
    def snap(p,uid=0,gid=0,mode=0o644):
        raw=json.dumps({'phase':'APPLIED','runtime':{'executable_closure':closure}}).encode()if p==v5/'record.json' else Path(p).read_bytes()
        return {'sha256':b.sha(raw),'bytes':len(raw),'uid':uid,'gid':gid,'mode':mode},raw
    def inventory(root):return {p.relative_to(root).as_posix():b.sha(p.read_bytes()) for p in root.rglob('*')if p.is_file()and not p.is_symlink()}
    P=types.SimpleNamespace(API=oldapi,STATIC=oldstatic,CONTROL=v5,BACKEND_LINK=api_link,STATIC_LINK=static_link,safe=lambda *_:None,snap=snap,read=lambda p,limit=2000000:Path(p).read_bytes(),runtime_closure=lambda _:closure,assert_files=lambda root,want:need(inventory(root)==want,'OLD_API_DRIFT'),idle=lambda _:calls.append('idle'),candidate_environment=lambda _:calls.append('environment'))
    H=types.SimpleNamespace(need=need,sha=b.sha,common=lambda _:calls.append('common'),OLD_PLAN=types.SimpleNamespace(record_valid=lambda *_:None,UNIT='powerflow-candidate-api.service'),OP=types.SimpleNamespace(timestamp=lambda v:__import__('datetime').datetime.fromisoformat(v)),health=lambda:calls.append('old-health'))
    view=types.SimpleNamespace(load_record=lambda:{'phase':'APPLIED'},verified_backups=lambda _:calls.append('helper-backups'),new_tree=lambda *_,**kw:calls.append('helper-tree'))
    B={'canonical':lambda *_:venv,'bounded_run':lambda argv,**kw:(calls.append(tuple(argv))or{'returncode':0,'failure':None}),'request':lambda *_:(200,b'ok')}
    G={'inventory':inventory,'runtime':lambda p:calls.append(('runtime',str(p)))}
    m=types.ModuleType('test_job');m.__dict__.update(C=c,P=P,H=H,HVIEW=view,B=B,G=G,OLD={'files':{'api/old.py':{'sha256':b.sha(b'old')},'static/index.html':{'sha256':b.sha(b'old-index')}}})
    exec(compile((HERE/'guards.py').read_bytes(),'<test-guards>','exec'),m.__dict__)
    m.baseline_preservation=lambda:json.loads(json.dumps(fingerprint));m.import_probe=lambda _:calls.append('imports')
    exec(compile((HERE/'transaction.py').read_bytes(),'<test-transaction>','exec'),m.__dict__)
    m.deployment_checks=lambda r:(m.old_trees(),m.tree_state(r,complete=True),m.same(fingerprint,m.baseline_preservation()))
    # Real local atomic writes/inodes, mocked Linux ownership only.
    monkeypatch.setattr(os,'chown',lambda *_:None);monkeypatch.setattr(os,'fchown',lambda *_:None)
    monkeypatch.setattr(os,'getgid',lambda:0);monkeypatch.setattr(os,'getegid',lambda:0)
    original=Path.lstat
    def metadata(p):
        s=list(original(p));s[4]=s[5]=0
        if stat.S_ISLNK(s[0]):s[0]=stat.S_IFLNK|0o777  # Linux symlink mode; macOS differs.
        return os.stat_result(s)
    monkeypatch.setattr(Path,'lstat',metadata)
    return m,calls,fingerprint
def test_complete_mock_preflight(job):
    m,calls,_=job;assert m.preflight_report()['status']=='PREFLIGHT_PASS'
    assert {'common','imports','helper-backups','helper-tree'}<=set(calls)
    assert not m.CONTROL.exists() and not m.API.exists() and not m.CHANGED
@pytest.mark.parametrize('gate',['PIPELINE_OR_WINDOW_GATE','PREFECT_IMPLEMENTATION_DRIFT','STATIC_DRIFT','CANDIDATE_IMPORT_COMPATIBILITY'])
def test_preflight_original_failure_preserved_no_writes(job,gate):
    m,_,_=job
    def fail(*a,**kw):raise Stop(gate)
    if gate=='CANDIDATE_IMPORT_COMPATIBILITY':m.import_probe=fail
    else:m.H.common=fail
    with pytest.raises(Stop,match=gate):m.preflight_report()
    assert not m.CONTROL.exists() and not m.API.exists() and not m.CHANGED
def test_apply_and_independent_rollback(job):
    m,calls,f=job;assert m.apply()['status']=='APPLIED'
    assert m.P.BACKEND_LINK.resolve()==m.API and m.P.STATIC_LINK.resolve()==m.STATIC
    a=m.CONTROL/'pointers.backup';b=m.CONTROL/'pointers.independent';assert a.read_bytes()==b.read_bytes() and a.stat().st_ino!=b.stat().st_ino
    f['store']='new-natural-record';f['forecast']={'bundle':'new-natural-bundle'}
    assert m.rollback()['status']=='ROLLED_BACK'
    assert m.P.BACKEND_LINK.resolve()==m.P.API and m.P.STATIC_LINK.resolve()==m.P.STATIC
    assert f['store']=='new-natural-record' and f['forecast']=={'bundle':'new-natural-bundle'} and m.API.exists()
    assert calls.count(('/usr/bin/systemctl','restart','powerflow-candidate-api.service'))==2
def test_partial_failure_no_activation_and_guarded_rollback(job):
    m,calls,_=job;original=m.write
    def fail(p,*a,**kw):
        if p==m.STATIC/'index.html':raise Stop('INSTALL_TEST_FAILURE')
        return original(p,*a,**kw)
    m.write=fail
    with pytest.raises(Stop,match='INSTALL_TEST_FAILURE'):m.apply()
    assert m.P.BACKEND_LINK.resolve()==m.P.API and not any(isinstance(c,tuple)and c[:2]==('/usr/bin/systemctl','restart') for c in calls)
    m.write=original;assert m.rollback()['status']=='ROLLED_BACK'
@pytest.mark.parametrize('kind',['backup','new_file','old_file','external_pointer','policy','extra_directory','hardlink'])
def test_rollback_drift_stops_before_mutation(job,kind):
    m,_,f=job;m.apply();before=(m.CONTROL/'record.json').read_bytes()
    if kind=='backup':(m.CONTROL/'pointers.independent').write_bytes(b'changed')
    if kind=='new_file':(m.API/'src/api/test.py').write_bytes(b'changed')
    if kind=='old_file':(m.P.API/'old.py').write_bytes(b'changed')
    if kind=='external_pointer':m.P.BACKEND_LINK.unlink();m.P.BACKEND_LINK.symlink_to(m.CONTROL)
    if kind=='policy':f['policy']='changed'
    if kind=='extra_directory':(m.API/'unexpected').mkdir()
    if kind=='hardlink':os.link(m.API/'src/api/test.py',m.API/'other.py')
    with pytest.raises((Stop,ValueError)):m.rollback()
    assert (m.CONTROL/'record.json').read_bytes()==before
def test_candidate_import_script_actual_runtime_no_network_or_write(package):
    _,_,_,_,c,_=package;m=types.ModuleType('probe');m.__dict__.update(C=c,H=types.SimpleNamespace(need=need,sha=load('build').sha))
    exec(compile((HERE/'guards.py').read_bytes(),'<offline-guards>','exec'),m.__dict__)
    script=m.candidate_probe_script()
    # UID simulation is offline only. The real preflight retains nsenter/setpriv.
    script=script.replace(b'assert sys.version_info',b'os.getuid=os.geteuid=os.getgid=os.getegid=lambda:992\nassert sys.version_info',1)
    r=subprocess.run([sys.executable,'-I','-B','-'],input=script,capture_output=True,cwd='/',env={'PATH':'/usr/bin:/bin','MPLBACKEND':'Agg'},timeout=25)
    assert r.returncode==0,r.stderr.decode()[-2000:]
    assert r.stdout==b'CANDIDATE_IMPORT_PASS\n'

def test_original_failure_is_reproduced_from_supervisor_root_cwd():
    r=subprocess.run([sys.executable,'-I','-B','-'],input=b"from pathlib import Path\ntry:Path('<verified-candidate>').resolve().parents[2]\nexcept IndexError:print('ORIGINAL_INDEX_ERROR')\n",capture_output=True,cwd='/',env={'PATH':'/usr/bin:/bin'},timeout=5)
    assert r.returncode==0 and r.stdout==b'ORIGINAL_INDEX_ERROR\n'

def test_exact_module_package_layout_and_no_application_or_security_guard_change(package):
    b,_,_,_,c,_=package;m=types.ModuleType('probe');m.__dict__.update(C=c,H=types.SimpleNamespace(need=need,sha=b.sha))
    exec(compile((HERE/'guards.py').read_bytes(),'<offline-guards>','exec'),m.__dict__)
    script=ast.parse(m.candidate_probe_script())
    assignments={n.targets[0].id:n.value for n in script.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
    sources=ast.literal_eval(assignments['SOURCES']);locations=ast.literal_eval(assignments['LOCATIONS'])
    assert sources.keys()==locations.keys()
    for name,(raw,package_flag) in sources.items():
        rel=name.replace('.','/')+('/__init__.py' if package_flag else '.py')
        assert locations[name]==c['api']+'/src/'+rel
        assert b.sha(raw.encode())==c['files']['api/src/'+rel]['sha256']
    assert Path(locations['api.app']).parents[2]==Path(c['api'])
    old=json.loads((HERE.parent/'live-forecast-reliability-release-v1/MANIFEST.json').read_bytes())
    assert c['files']==old['config']['files']
    # The exact audit restrictions and all original policy/schema/routes assertions
    # remain in the new generated child; only module layout is corrected.
    previous=types.ModuleType('old_probe')
    previous.__dict__.update(C=c,H=types.SimpleNamespace(need=need,sha=b.sha))
    exec(compile((HERE.parent/'live-forecast-reliability-release-v1/guards.py').read_bytes(),'<old-probe>','exec'),previous.__dict__)
    oldchild=ast.parse(previous.candidate_probe_script())
    audit=lambda t:ast.dump(next(n for n in t.body if isinstance(n,ast.FunctionDef)and n.name=='audit'),include_attributes=False)
    assert audit(script)==audit(oldchild)
    asserts={ast.dump(n,include_attributes=False) for n in script.body if isinstance(n,ast.Assert)}
    assert {ast.dump(n,include_attributes=False)for n in oldchild.body if isinstance(n,ast.Assert)}<=asserts

@pytest.mark.parametrize('gate',['PIPELINE_OR_WINDOW_GATE','PREFECT_IMPLEMENTATION_DRIFT'])
def test_full_payload_failure_dispatch_preserves_original_identifier(package,gate,capsys):
    b,p,_,h,c,blobs=package;tree=ast.parse(b.assemble('preflight',p,c,blobs,h));index=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Try))
    before={k:v for k,v in sys.modules.items() if k=='shared' or k.startswith('shared.')}
    namespace={}
    try:
        exec(compile(ast.Module(body=tree.body[:index],type_ignores=[]),'<offline-init>','exec'),namespace)
        def fail():raise namespace['PLAN'].Stop(gate)
        namespace['JOB'].fresh=fail
        with pytest.raises(SystemExit) as result:exec(compile(ast.Module(body=tree.body[index:],type_ignores=[]),'<offline-dispatch>','exec'),namespace)
        assert result.value.code==1
        report=json.loads(capsys.readouterr().out)
        assert {k:report[k] for k in ['status','phase','changed','reason']}=={'status':'BLOCKED','phase':'READ_ONLY','changed':False,'reason':gate}
        assert report['operation']=='preflight_report' and type(report['line'])is int
    finally:
        for key in list(sys.modules):
            if key=='shared' or key.startswith('shared.'):sys.modules.pop(key)
        sys.modules.update(before)

def test_local_check_has_no_ssh_or_remote_execution(monkeypatch,capsys):
    runner=load('run');calls=[]
    wrapper=types.SimpleNamespace(profile=lambda:(calls.append('identity')or{}),ssh_argv=lambda _:pytest.fail('SSH not allowed'))
    monkeypatch.setattr(runner,'verify',lambda *_:(b'payload',wrapper,types.SimpleNamespace()))
    monkeypatch.setattr(sys,'argv',['run.py','preflight','--manifest-sha256','0'*64,'--local-check'])
    assert runner.main()==0 and calls==['identity']
    assert json.loads(capsys.readouterr().out)=={'status':'LOCAL_PASS','ssh_attempts':0}

@pytest.mark.parametrize('kind',['manifest','guards','candidate_source','payload'])
def test_hash_mismatch_fails_locally_before_any_transport(package,monkeypatch,kind):
    b,p,_,h,c,blobs=package;runner=load('run')
    m={'version':1,'execution_authorized':False,'release':b.RELEASE,'transaction':b.TRANSACTION,'config':c,
       'artifacts':{name:b.sha(b.read(ROOT/name)) for name in b.artifact_paths()},'payloads':{}}
    payloads={}
    for action in ['preflight','apply','rollback','accept']:
        raw=b.assemble(action,p,c,blobs,h);payloads[HERE/(action+'.payload.py')]=raw;m['payloads'][action]={'sha256':b.sha(raw),'bytes':len(raw)}
    encoded=b.encode(m);expected=b.sha(encoded);original=runner.read
    target=HERE/'guards.py' if kind=='guards' else ROOT/'src/shared/forecast_availability.py'
    def read(path):
        if path==HERE/'MANIFEST.json':return encoded+b'x'if kind=='manifest' else encoded
        if path in payloads:return payloads[path]+(b'x'if kind=='payload'else b'')
        raw=original(path)
        return raw+b'x'if kind in {'guards','candidate_source'}and path==target else raw
    monkeypatch.setattr(runner,'read',read)
    with pytest.raises((AssertionError,ValueError)):runner.verify(expected,'preflight')

def test_conflicting_retained_asset_cannot_be_rebaselined(package):
    import copy
    b,_,v5,_,_,_=package;bad=copy.deepcopy(v5)
    bad['config']['files']['static/assets/index-DST_P3xP.css']['sha256']='0'*64
    with pytest.raises(AssertionError,match='HASHED_ASSET_COLLISION'):b.config(bad)

def test_unapproved_static_source_never_enters_public_release(package,tmp_path,monkeypatch):
    import shutil
    b,_,v5,_,_,_=package;copy=tmp_path/'front';shutil.copytree(b.FRONT,copy);(copy/'private.txt').write_bytes(b'not-publishable')
    monkeypatch.setattr(b,'FRONT',copy)
    with pytest.raises(AssertionError,match='STATIC_FILE_SCOPE'):b.config(v5)
