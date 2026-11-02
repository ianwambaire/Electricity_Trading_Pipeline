"""Local-only preflight tests: all transport, Linux and service probes mocked."""
import ast
import importlib.util
import json
import io
from pathlib import Path
import signal
import subprocess
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/'deploy/staging/forecast-consistency-release'
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
P=load(DIR/'preflight_readonly.py','pf_readonly')
W=load(DIR/'run_preflight.py','pf_wrapper')
S=load(ROOT/'deploy/remediation/a3-bounded-local.py','pf_supervisor')

def adapter(fake):
    def run(command,**kw):
        out=io.BytesIO();err=io.BytesIO()
        result=fake(command,input=kw['input'],stdout=out,stderr=err,timeout=kw['timeout'],check=False)
        return {'returncode':result.returncode,'stdout':out.getvalue(),'stderr':err.getvalue(),'failure':None}
    return run

def report(state='UNVERIFIED'):
    return {'schema_version':1,'status':'BLOCKED','checks':{k:{'status':state,'facts':{}} for k in P.FIELDS}}

@pytest.mark.parametrize('path',[DIR/'preflight_readonly.py',DIR/'run_preflight.py'])
def test_python39_syntax(path):ast.parse(path.read_text(),feature_version=(3,9))

def test_payload_has_no_mutation_calls():
    tree=ast.parse((DIR/'preflight_readonly.py').read_text())
    forbidden={'write_text','write_bytes','mkdir','unlink','remove','rename','replace','chmod','chown','system','popen','exec','eval'}
    for n in ast.walk(tree):
        if isinstance(n,ast.Call):
            name=n.func.attr if isinstance(n.func,ast.Attribute) else n.func.id if isinstance(n.func,ast.Name) else ''
            # String replacements only are permitted.
            assert name not in forbidden-{'replace'} or (name=='system' and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='platform')
        if isinstance(n,ast.Attribute) and n.attr.startswith('O_'):assert n.attr not in {'O_WRONLY','O_RDWR','O_CREAT','O_TRUNC','O_APPEND'}
    assert 'nginx -t' not in (DIR/'preflight_readonly.py').read_text()
    assert 'load_model' not in (DIR/'preflight_readonly.py').read_text()

@pytest.mark.parametrize('argv',[
    ['/usr/bin/systemctl','restart','powerflow-candidate-api.service'],
    ['/bin/sh','-c','anything'],['/usr/sbin/nginx','-t'],['pip','install','x'],
    ['/usr/bin/systemctl','show','unrelated.service'],['/usr/bin/touch','x'],
])
def test_dispatch_rejects_mutation_and_expansion(argv,monkeypatch):
    monkeypatch.setattr(P.subprocess,'run',lambda *a,**k:pytest.fail('subprocess launched'))
    with pytest.raises(ValueError,match='unapproved_command'):P.command(argv)

def test_exact_service_query(monkeypatch):
    calls=[]
    def fake(argv,**kw):calls.append((argv,kw));return {'stdout':b'','returncode':0,'failure':None}
    monkeypatch.setattr(P,'bounded_run',fake)
    assert P.command(['/usr/bin/systemctl','show',*P.UNITS,'--property='+P.PROPERTIES])==''
    assert len(calls)==1 and calls[0][1]['timeout']==8

@pytest.mark.parametrize('port,path,body',[(443,'https://evil',None),(8010,'/admin/operations',None),(4200,'/api/flow_runs/x/set_state',{}),(8010,'/health',{})])
def test_http_allowlist(port,path,body):
    with pytest.raises(ValueError):P.request(port,path,body)

@pytest.mark.parametrize('change',[
    lambda r:r.update(secret='secret-sentinel'),
    lambda r:r['checks']['health']['facts'].update(token='secret-sentinel'),
    lambda r:r['checks']['health']['facts'].update(api='secret-sentinel'),
    lambda r:r['checks']['health'].update(traceback='secret-sentinel'),
    lambda r:r.update(status='PASS'),
])
def test_output_schema_rejects_secrets_and_false_pass(change):
    r=report();change(r)
    with pytest.raises(ValueError):P.validate_report(r)

def test_unverified_is_blocked(capsys):
    assert P.finish(report()['checks'])==1
    assert json.loads(capsys.readouterr().out)['status']=='BLOCKED'

def test_readonly_file_bound_and_no_changes(tmp_path,monkeypatch):
    # Linux NOATIME has no macOS equivalent; emulate its zero-valued flag locally.
    monkeypatch.setattr(P.os,"O_NOATIME",getattr(P.os,"O_NOATIME",0),raising=False)
    f=tmp_path/'x';f.write_bytes(b'1234');before=f.stat()
    assert P.read(f,4)==b'1234'
    with pytest.raises(ValueError):P.read(f,3)
    link=tmp_path/'link';link.symlink_to(f)
    with pytest.raises(OSError):P.read(link)
    assert f.read_bytes()==b'1234' and f.stat().st_mtime_ns==before.st_mtime_ns

def test_hash_failure_before_transport(tmp_path,monkeypatch):
    f=tmp_path/'payload';f.write_bytes(b'changed')
    monkeypatch.setattr(W.subprocess,'run',lambda *a,**k:pytest.fail('transport'))
    with pytest.raises(ValueError,match='hash_mismatch'):W.verify_hash(f,'0'*64)

def test_no_arbitrary_host_or_command_interface():
    source=(DIR/'run_preflight.py').read_text()
    assert '--host' not in source and '--command' not in source and '--payload' not in source
    argv=W.ssh_argv({'identity_file':'PRIVATE','known_hosts':'PINNED','target':'APPROVED'})
    for setting in ['StrictHostKeyChecking=yes','ConnectTimeout=10','ConnectionAttempts=1','ForwardAgent=no','ControlMaster=no','UpdateHostKeys=no']:
        assert setting in argv
    assert argv[-1]==W.REMOTE and '120s' in argv[-1] and '--kill-after=5s' in argv[-1] and 'sudo -n' in argv[-1]

@pytest.mark.parametrize('code,error,category',[(255,b'Host key verification failed secret-sentinel','HOST_KEY_FAILURE'),(255,b'connect timeout secret-sentinel','SSH_FAILURE'),(1,b'sudo: password required secret-sentinel','SUDO_FAILURE'),(124,b'','TIMEOUT')])
def test_transport_failures_no_retry_or_leak(tmp_path,code,error,category):
    calls=[]
    def run(argv,**kw):
        calls.append((argv,kw));kw['stderr'].write(error);return SimpleNamespace(returncode=code)
    result=W.execute((DIR/'preflight_readonly.py').read_bytes(),b'# verified supervisor fixture',{'identity_file':'PRIVATE','known_hosts':'PINNED','target':'APPROVED'},tmp_path,adapter(run))
    assert result['failure_category']==category and result['exit_status']==code and not result['report_produced']
    assert len(calls)==1 and calls[0][1]['input']==(DIR/'preflight_readonly.py').read_bytes() and calls[0][1]['timeout']==180
    assert 'secret-sentinel' not in json.dumps(result)
    assert (tmp_path/'stderr.private').stat().st_mode&0o777==0o600

@pytest.mark.parametrize('raw',[b'{bad json',b'{"secret":"secret-sentinel"}',b'[]',b'{}\nsecret-sentinel'])
def test_unexpected_stdout_not_exposed(tmp_path,raw):
    def run(argv,**kw):kw['stdout'].write(raw);return SimpleNamespace(returncode=0)
    result=W.execute((DIR/'preflight_readonly.py').read_bytes(),b'# verified supervisor fixture',{'identity_file':'P','known_hosts':'K','target':'T'},tmp_path,adapter(run))
    assert result['failure_category']=='UNEXPECTED_OUTPUT' and not result['report_produced']
    assert 'secret-sentinel' not in json.dumps(result)

def test_mocked_end_to_end_blocked_report(tmp_path):
    r=report()
    def run(argv,**kw):kw['stdout'].write(json.dumps(r).encode());return SimpleNamespace(returncode=1)
    result=W.execute((DIR/'preflight_readonly.py').read_bytes(),b'# verified supervisor fixture',{'identity_file':'P','known_hosts':'K','target':'T'},tmp_path,adapter(run))
    assert result['report_produced'] and result['failure_category']=='CHECKS_BLOCKED' and result['report']==r

def test_missing_dependency_is_unverified(monkeypatch,capsys):
    monkeypatch.setattr(P.os,'geteuid',lambda:0);monkeypatch.setattr(P.sys,'platform','linux')
    monkeypatch.setattr(P,'services',lambda:(_ for _ in ()).throw(FileNotFoundError('private-path-sentinel')))
    assert P.main()==1
    raw=capsys.readouterr().out
    assert 'private-path-sentinel' not in raw and json.loads(raw)['checks']['preservation']['status']=='UNVERIFIED'


def test_supervisor_bounds_and_kill_escalation(monkeypatch):
    calls=[]
    class Process:
        pid=123
        def wait(self,timeout=None):
            calls.append(('wait',timeout))
            if timeout is not None:raise subprocess.TimeoutExpired('fake',timeout)
            return 0
    monkeypatch.setattr(S.subprocess,'Popen',lambda command,**kw:Process())
    monkeypatch.setattr(S.os,'killpg',lambda pid,sig:calls.append(('signal',sig)))
    monkeypatch.setattr(S.time,'monotonic',lambda:0)
    monkeypatch.setattr(S.time,'sleep',lambda seconds:calls.append(('sleep',seconds)))
    assert S.run(['FAKE'])==124
    assert ('wait',180) in calls and ('wait',5) in calls
    assert ('signal',signal.SIGTERM) in calls and ('signal',signal.SIGKILL) in calls


def test_bpf_only_queries_existing_programs():
    source=(DIR/'preflight_readonly.py').read_text()
    assert 'invoke(321,16,' in source
    assert 'query_flags=1' in source and 'prog_cnt=64' in source


def test_no_candidate_runtime_execution_or_package_imports():
    source=(DIR/'preflight_readonly.py').read_text()
    assert 'RUNTIME_CHILD' not in source and 'nsenter' not in source
    tree=ast.parse(source)
    forbidden={'numpy','pandas','pydantic_core','cryptography','_cffi_backend','site'}
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):assert not any(x.name.split('.')[0] in forbidden for x in node.names)
        if isinstance(node,ast.ImportFrom):assert node.module.split('.')[0] not in forbidden
    assert "checks['runtime']={'status':'UNVERIFIED','facts':{}}" in source
    assert "checks['publication']={'status':'UNVERIFIED','facts':{}}" in source


def test_current_review_hash_integrity():
    review=json.loads((DIR/'PREFLIGHT-REVIEW.json').read_bytes())
    for rel,meta in review['artifacts'].items():
        raw=(ROOT/rel).read_bytes();assert len(raw)==meta['bytes'] and W.sha(raw)==meta['sha256']


def test_verify_preserved_mapping_manifest_with_clean_fixture(tmp_path,monkeypatch):
    # Portable fixture: no private package or credential is required by the tests.
    root=tmp_path/'repo';here=root/'deploy/staging/forecast-consistency-release';here.mkdir(parents=True)
    private=root/'private';release=private/'release';release.mkdir(parents=True)
    (release/'api').mkdir();(release/'api/x').write_bytes(b'payload')
    r={'files':{'api/x':{'bytes':7,'sha256':W.sha(b'payload')}}}
    release_raw=json.dumps(r).encode();(release/'release-manifest.json').write_bytes(release_raw)
    tools_raw=json.dumps({'artifacts':[]}).encode();(private/'TOOLS-MANIFEST.json').write_bytes(tools_raw)
    artifacts={}
    for name in W.ARTIFACTS:
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'source')
        artifacts[name]={'bytes':6,'sha256':W.sha(b'source')}
    review=json.dumps({'schema_version':1,'artifacts':artifacts}).encode();(here/'PREFLIGHT-REVIEW.json').write_bytes(review)
    monkeypatch.setattr(W,'ROOT',root);monkeypatch.setattr(W,'HERE',here);monkeypatch.setattr(W,'PRIVATE',private)
    monkeypatch.setattr(W,'RELEASE_SHA',W.sha(release_raw));monkeypatch.setattr(W,'TOOLS_SHA',W.sha(tools_raw));monkeypatch.setattr(W,'SUPERVISOR_SHA',W.sha(b'source'))
    assert W.verify_package(W.sha(review))[0]==b'source'
    (release/'api/x').write_bytes(b'drifted')
    with pytest.raises(ValueError,match='hash_mismatch'):W.verify_package(W.sha(review))

@pytest.mark.parametrize('failure',[FileNotFoundError,PermissionError,subprocess.TimeoutExpired])
def test_missing_tools_permissions_and_timeouts_fail_closed(monkeypatch,capsys,failure):
    monkeypatch.setattr(P.os,'geteuid',lambda:0);monkeypatch.setattr(P.sys,'platform','linux')
    def fail():
        if failure is subprocess.TimeoutExpired:raise failure('PRIVATE',8)
        raise failure('PRIVATE')
    monkeypatch.setattr(P,'services',fail)
    assert P.main()==1
    raw=capsys.readouterr().out;assert 'PRIVATE' not in raw
    r=json.loads(raw);assert r['checks']['preservation']['status']=='UNVERIFIED'
    assert all(x['status']!='PASS' for name,x in r['checks'].items() if name!='identity')


def test_unrelated_unit_and_invalid_service_output_rejected(monkeypatch):
    monkeypatch.setattr(P,'command',lambda a:'Id=unrelated.service\nMainPID=123\n')
    with pytest.raises(ValueError,match='unexpected_unit'):P.services()


def test_report_cannot_claim_pass_with_empty_evidence():
    r=report('PASS');r['status']='PASS'
    with pytest.raises(ValueError,match='report_fields'):P.validate_report(r)


def test_payload_has_only_fixed_subprocess_sites():
    tree=ast.parse((DIR/'preflight_readonly.py').read_text())
    sites=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='subprocess']
    assert len(sites)==1 and all(n.func.attr=='Popen' for n in sites)
    source=(DIR/'preflight_readonly.py').read_text()
    assert 'shell=True' not in source and 'setns' not in source
    assert 'nsenter' not in source and 'preexec_fn' not in source


def test_environment_text_and_process_argv_cannot_be_emitted():
    assert all(not ({'environment','argv','ExecStart','credentials','token'} & fields) for fields in P.FIELDS.values())
    r=report();r['checks']['environment']['facts']['sha256']='not-a-hash secret-sentinel'
    with pytest.raises(ValueError):P.validate_report(r)


def test_executable_artifacts_read_once_and_retained(monkeypatch):
    original=W.file_bytes
    paths={W.HERE/'preflight_readonly.py',W.ROOT/'deploy/remediation/a3-bounded-local.py'}
    counts={p:0 for p in paths}
    def once(path,*args,**kwargs):
        if path in paths:
            counts[path]+=1
            if counts[path]>1:raise AssertionError('Executable reopened after verification')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(W,'file_bytes',once)
    # Stub preserved-package reads so this regression is clean-clone portable.
    review=json.loads(original(DIR/'PREFLIGHT-REVIEW.json'))
    release_raw=json.dumps({'files':{}}).encode();tools_raw=json.dumps({'artifacts':[]}).encode()
    def fixture(path,*a,**kw):
        if path==W.PRIVATE/'release/release-manifest.json':return release_raw
        if path==W.PRIVATE/'TOOLS-MANIFEST.json':return tools_raw
        return once(path,*a,**kw)
    monkeypatch.setattr(W,'file_bytes',fixture)
    monkeypatch.setattr(W,'RELEASE_SHA',W.sha(release_raw));monkeypatch.setattr(W,'TOOLS_SHA',W.sha(tools_raw))
    payload,supervisor=W.verify_package(W.sha(original(DIR/'PREFLIGHT-REVIEW.json')))
    assert payload==original(DIR/'preflight_readonly.py')
    assert supervisor==original(ROOT/'deploy/remediation/a3-bounded-local.py')
    assert all(n==1 for n in counts.values())


def test_execution_and_validator_use_retained_bytes_after_substitution(tmp_path,monkeypatch):
    payload=(DIR/'preflight_readonly.py').read_bytes()
    supervisor=b"print('ORIGINAL_SUPERVISOR')\n"
    old_payload=tmp_path/'payload.py';old_supervisor=tmp_path/'supervisor.py'
    old_payload.write_bytes(payload);old_supervisor.write_bytes(supervisor)
    # Simulate files changing after a successful verification snapshot.
    old_payload.write_bytes(b"raise RuntimeError('SUBSTITUTED_VALIDATOR')")
    old_supervisor.write_bytes(b"raise RuntimeError('SUBSTITUTED_SUPERVISOR')")
    reads=W.file_bytes
    def no_source_reopens(path,*a,**kw):
        assert path not in {DIR/'preflight_readonly.py',old_payload,old_supervisor}
        return reads(path,*a,**kw)
    monkeypatch.setattr(W,'file_bytes',no_source_reopens)
    calls=[]
    def fake(command,**kwargs):
        calls.append(command)
        assert command[0]=='/usr/bin/ssh'
        assert str(old_supervisor) not in command
        assert kwargs['input']==payload
        assert 'SUBSTITUTED' not in repr(command)
        kwargs['stdout'].write(json.dumps(report()).encode())
        return SimpleNamespace(returncode=1)
    result=W.execute(payload,supervisor,{'identity_file':'P','known_hosts':'K','target':'T'},tmp_path,adapter(fake))
    assert len(calls)==1 and result['report_produced'] and result['failure_category']=='CHECKS_BLOCKED'


@pytest.mark.parametrize('reason',['hash_mismatch','artifact_size','review_scope','supervisor_hash'])
def test_package_rejection_prevents_transport(reason,monkeypatch,capsys):
    monkeypatch.setattr(W.sys,'argv',['run_preflight.py','--review-sha256','0'*64])
    def fail(expected):raise ValueError(reason)
    monkeypatch.setattr(W,'verify_package',fail)
    monkeypatch.setattr(W,'execute',lambda *a,**k:pytest.fail('SSH must not begin'))
    monkeypatch.setattr(W,'profile',lambda:pytest.fail('profile not needed on rejected package'))
    assert W.main()==1
    assert json.loads(capsys.readouterr().out)['failure_category']=='LOCAL_VERIFICATION_FAILURE'


def test_retained_bounded_supervisor_preserves_stdin():
    child="import sys; print(len(sys.stdin.buffer.read()))"
    result=P.bounded_run([W.sys.executable,'-I','-B','-c',child],input=b'fixture',timeout=5)
    assert result['returncode']==0 and result['stdout']==b'7\n' and result['failure'] is None


@pytest.mark.parametrize('mutation,expected_error',[
    ('payload_hash','hash_mismatch'),('payload_size','artifact_size'),
    ('unexpected_dependency','review_scope'),
])
def test_real_package_verifier_rejects_changed_artifacts_before_transport(mutation,expected_error,monkeypatch):
    original=W.file_bytes
    review_path=DIR/'PREFLIGHT-REVIEW.json'
    review=json.loads(original(review_path))
    payload_rel='deploy/staging/forecast-consistency-release/preflight_readonly.py'
    if mutation=='payload_size':review['artifacts'][payload_rel]['bytes']+=1
    if mutation=='unexpected_dependency':
        review['artifacts']['unapproved/helper.py']={'bytes':0,'sha256':W.sha(b'')}
    raw=json.dumps(review).encode()
    def substituted(path,*args,**kwargs):
        if path==W.HERE/'PREFLIGHT-REVIEW.json':return raw
        if mutation=='payload_hash' and path==W.ROOT/payload_rel:
            return original(path)+b'\n# substituted after review\n'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(W,'file_bytes',substituted)
    monkeypatch.setattr(W.subprocess,'run',lambda *a,**kw:pytest.fail('No transport allowed'))
    with pytest.raises(ValueError,match=expected_error):W.verify_package(W.sha(raw))


@pytest.mark.parametrize('problem',[None,'missing_metadata','malformed_metadata','version_mismatch'])
def test_passive_installation_never_executes_startup_hooks(tmp_path,monkeypatch,problem):
    venv=tmp_path/'release/.venv-api';site=venv/'lib/python3.14/site-packages';site.mkdir(parents=True)
    interpreter=tmp_path/'interpreter';interpreter.write_bytes(b'NON_EXECUTABLE_BINARY_FIXTURE')
    (venv/'bin').mkdir();(venv/'bin/python').symlink_to(interpreter)
    (venv/'pyvenv.cfg').write_text('version = 3.14.7\n')
    marker=tmp_path/'MUST_NOT_EXIST'
    hook="import pathlib; pathlib.Path("+repr(str(marker))+").write_text('UNSAFE')"
    (site/'unsafe.pth').write_text(hook);(site/'sitecustomize.py').write_text(hook)
    for i,(name,version) in enumerate(P.LOCKED_VERSIONS.items()):
        folder=site/(name+'.dist-info');folder.mkdir()
        if problem=='missing_metadata' and i==0:continue
        (folder/'METADATA').write_text('Name: '+name+'\nVersion: '+('0.0' if problem=='version_mismatch' and i==0 else version)+'\n\n'+hook)
        if problem=='malformed_metadata' and i==0:(folder/'METADATA').write_text('NOT_METADATA\n')
    path_class=Path;original_lstat=Path.lstat
    def root_stat(self,*a,**kw):
        value=original_lstat(self,*a,**kw);parts=list(value);parts[4]=0
        return P.os.stat_result(parts)
    monkeypatch.setattr(Path,'lstat',root_stat)
    monkeypatch.setattr(P,'Path',lambda x:path_class(interpreter) if x=='/usr/bin/python3.14' else path_class(x))
    monkeypatch.setattr(P,'canonical',lambda path,root:venv.parent if path==P.BACKEND else path.resolve(strict=True))
    monkeypatch.setattr(P,'digest',lambda path:'0'*64)
    monkeypatch.setattr(P,'INSTALLED_HASHES',{})
    monkeypatch.setattr(P.os,'O_NOATIME',getattr(P.os,'O_NOATIME',0),raising=False)
    monkeypatch.setattr(P.subprocess,'run',lambda *a,**kw:pytest.fail('Unsafe execution'))
    if problem in ('missing_metadata','malformed_metadata'):
        with pytest.raises((FileNotFoundError,KeyError,ValueError)):P.passive_installation()
    else:
        facts,ok=P.passive_installation()
        assert facts['startup_hooks_present'] is True
        assert ok==(problem is None)
        assert not {'imports','namespace_access','python_match'}&set(facts)
    assert not marker.exists()


@pytest.mark.parametrize('stream',['stdout','stderr'])
def test_streaming_limit_noisy_local_process(stream):
    code="import os; os.write("+('1' if stream=='stdout' else '2')+",b'x'*65536)"
    result=P.bounded_run([W.sys.executable,'-I','-B','-c',code],timeout=3,limit=512,grace=0.05)
    assert result['failure']=='OUTPUT_LIMIT' and len(result[stream])==512
    assert len(result['stdout'])<=512 and len(result['stderr'])<=512
    assert type(result['returncode'])is int


def test_streaming_timeout_kills_signal_ignoring_child():
    code="import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(20)"
    result=P.bounded_run([W.sys.executable,'-I','-B','-c',code],timeout=0.2,grace=0.1)
    assert result['failure']=='TIMEOUT' and result['returncode']<0


def test_wrapper_capture_disk_failure_preserves_actual_status(tmp_path,monkeypatch):
    payload=(DIR/'preflight_readonly.py').read_bytes()
    def result(*a,**kw):return {'returncode':255,'stdout':b'','stderr':b'PRIVATE_SENTINEL','failure':None}
    original=W.os.open
    def fail(path,*a,**kw):
        if str(path).endswith('.private'):raise OSError(28,'PRIVATE_SENTINEL')
        return original(path,*a,**kw)
    monkeypatch.setattr(W.os,'open',fail)
    summary=W.execute(payload,b'legacy',{'identity_file':'P','known_hosts':'K','target':'T'},tmp_path,result)
    assert summary['exit_status']==255 and summary['failure_category']=='CAPTURE_FAILURE'
    assert 'PRIVATE_SENTINEL' not in json.dumps(summary)


@pytest.mark.parametrize('number',[13,28])
def test_report_write_failure_sanitized(tmp_path,monkeypatch,capsys,number):
    monkeypatch.setattr(W.sys,'argv',['run_preflight.py','--review-sha256','0'*64])
    monkeypatch.setattr(W,'verify_package',lambda h:(b'payload',b'supervisor'))
    monkeypatch.setattr(W,'profile',lambda:{})
    monkeypatch.setattr(W.tempfile,'mkdtemp',lambda **kw:str(tmp_path))
    monkeypatch.setattr(W,'execute',lambda *a:{'exit_status':255,'failure_category':'SSH_FAILURE','report_produced':False,'report':None})
    original=W.os.open
    def fail(path,*a,**kw):
        if str(path).endswith('sanitized.json'):raise OSError(number,'PRIVATE_SENTINEL')
        return original(path,*a,**kw)
    monkeypatch.setattr(W.os,'open',fail)
    assert W.main()==1
    raw=capsys.readouterr().out;result=json.loads(raw)
    assert result['exit_status']==255 and result['failure_category']=='REPORT_WRITE_FAILURE'
    assert 'PRIVATE_SENTINEL' not in raw


@pytest.mark.parametrize('name,facts',[
 ('identity',{'root':False,'linux':True}),
 ('cgroup',{'memory_high':384*1024**2,'memory_max':1024,'swap_max':0}),
 ('health',{key:200 for key in P.FIELDS['health']}),
 ('preservation',{'unchanged':True,'before_sha256':'0'*64,'after_sha256':'1'*64}),
 ('runtime',{key:True for key in P.FIELDS['runtime']}),
 ('pipeline',{'schedule_match':True,'concurrency_match':True,'active_runs':1,'scheduled_runs':0,'ingestion_processes':0,'safe_window':True}),
])
def test_contradictory_pass_rejected(name,facts):
    r=report();r['checks'][name]={'status':'PASS','facts':facts}
    with pytest.raises(ValueError):P.validate_report(r)


@pytest.mark.parametrize('problem',[None,'missing','unreadable','malformed','escape','symlink','wrong_hash'])
def test_publication_chain_passive_only(tmp_path,monkeypatch,problem):
    root=tmp_path/'publication';(root/'releases').mkdir(parents=True)
    raw=b'{"version":1}';digest=P.sha(raw)
    release=root/'releases'/digest;release.mkdir()
    bundle=release/'bundle.json';bundle.write_bytes(raw);bundle.chmod(0o640)
    for d in (root,root/'releases',release):d.chmod(0o750)
    (root/'current').symlink_to('releases/'+digest)
    if problem=='missing':bundle.unlink()
    if problem=='unreadable':bundle.chmod(0)
    if problem in ('malformed','wrong_hash'):bundle.write_bytes(b'not-json' if problem=='malformed' else b'{}')
    if problem=='escape':(root/'current').unlink();(root/'current').symlink_to('../escape')
    if problem=='symlink':bundle.unlink();bundle.symlink_to(tmp_path/'outside')
    original=Path.lstat
    def root_stat(path,*a,**kw):
        st=original(path,*a,**kw);parts=list(st);parts[4]=0;parts[5]=992
        if path not in {root,root/'releases',release,bundle,root/'current'}:parts[0]&=~0o022
        return P.os.stat_result(parts)
    monkeypatch.setattr(Path,'lstat',root_stat)
    monkeypatch.setattr(P,'PUBLICATION',root)
    monkeypatch.setattr(P.os,'O_NOATIME',getattr(P.os,'O_NOATIME',0),raising=False)
    if problem is None:
        facts,ok=P.publication_metadata();assert ok and all(facts.values())
        assert 'candidate_readable' not in facts
    else:
        with pytest.raises((OSError,ValueError)):P.publication_metadata()


def test_thirteen_preservation_files_include_historical_snapshot():
    tree=ast.parse((DIR/'preflight_readonly.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='fingerprints')
    paths=next(ast.literal_eval(n.iter) for n in function.body if isinstance(n,ast.For) and isinstance(n.iter,ast.List))
    assert len(paths)==13 and 'database/electricity_trading.db' in paths


def test_wrapper_uses_exact_bounded_supervisor_parameters(tmp_path):
    payload=(DIR/'preflight_readonly.py').read_bytes();calls=[]
    def run(command,**kwargs):
        calls.append(command)
        assert kwargs=={'input':payload,'timeout':180,'limit':131072,'grace':5}
        return {'returncode':-9,'stdout':b'','stderr':b'','failure':'TIMEOUT'}
    result=W.execute(payload,b'legacy',{'identity_file':'P','known_hosts':'K','target':'T'},tmp_path,run)
    assert len(calls)==1 and calls[0][0]=='/usr/bin/ssh'
    assert result['exit_status']==-9 and result['failure_category']=='TIMEOUT' and not result['report_produced']


def test_output_limit_blocks_even_successful_exit(tmp_path):
    payload=(DIR/'preflight_readonly.py').read_bytes()
    def run(*args,**kwargs):return {'returncode':0,'stdout':b'x'*131072,'stderr':b'','failure':'OUTPUT_LIMIT'}
    result=W.execute(payload,b'legacy',{'identity_file':'P','known_hosts':'K','target':'T'},tmp_path,run)
    assert result['exit_status']==0 and result['failure_category']=='OUTPUT_LIMIT' and not result['report_produced']
    assert (tmp_path/'stdout.private').stat().st_size==131072


@pytest.mark.parametrize('error,cause',[(FileNotFoundError,'MISSING_PATH'),(PermissionError,'PERMISSION_DENIED'),(OSError,'IO_ERROR')])
def test_publication_failure_reports_fixed_phase_without_private_paths(monkeypatch,error,cause):
    root=Path('/synthetic-publication-root')
    monkeypatch.setattr(P,'PUBLICATION',root)
    def probe(path,*a,**kw):
        if path==root:raise error('PRIVATE_PATH_SECRET_SENTINEL')
        return SimpleNamespace(st_mode=P.stat.S_IFDIR|0o755,st_uid=0)
    monkeypatch.setattr(Path,'lstat',probe)
    result=P.inspect_check(P.publication_metadata)
    assert result=={'status':'UNVERIFIED','facts':{},'diagnostic':{'phase':'ROOT','cause':cause}}
    assert 'PRIVATE_PATH_SECRET_SENTINEL' not in json.dumps(result)
    r=report();r['checks']['publication_metadata']=result;P.validate_report(r)


@pytest.mark.parametrize('change',[
    lambda r:r['checks']['publication_metadata']['diagnostic'].update(cause='PRIVATE_PATH_SECRET_SENTINEL'),
    lambda r:r['checks']['publication_metadata']['diagnostic'].update(path='PRIVATE_PATH_SECRET_SENTINEL'),
    lambda r:r['checks']['identity'].update(diagnostic={'phase':'ROOT','cause':'MISSING_PATH'}),
    lambda r:r['checks']['publication_metadata'].update(status='PASS'),
])
def test_publication_diagnostic_rejects_unknown_or_misplaced_fields(change):
    r=report();r['checks']['publication_metadata']['diagnostic']={'phase':'ROOT','cause':'MISSING_PATH'}
    change(r)
    with pytest.raises(ValueError):P.validate_report(r)
