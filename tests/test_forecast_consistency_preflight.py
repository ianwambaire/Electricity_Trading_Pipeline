"""Local-only preflight tests: all transport, Linux and service probes mocked."""
import ast
import importlib.util
import json
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
    def fake(argv,**kw):calls.append((argv,kw));return SimpleNamespace(stdout=b'')
    monkeypatch.setattr(P.subprocess,'run',fake)
    assert P.command(['/usr/bin/systemctl','show',*P.UNITS,'--property='+P.PROPERTIES])==''
    assert len(calls)==1 and calls[0][1]['timeout']==8 and calls[0][1]['check'] is True

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
    result=W.execute(b'PAYLOAD',Path('/supervisor'),{'identity_file':'PRIVATE','known_hosts':'PINNED','target':'APPROVED'},tmp_path,run)
    assert result['failure_category']==category and result['exit_status']==code and not result['report_produced']
    assert len(calls)==1 and calls[0][1]['input']==b'PAYLOAD' and calls[0][1]['timeout']==190
    assert 'secret-sentinel' not in json.dumps(result)
    assert (tmp_path/'stderr.private').stat().st_mode&0o777==0o600

@pytest.mark.parametrize('raw',[b'{bad json',b'{"secret":"secret-sentinel"}',b'[]',b'{}\nsecret-sentinel'])
def test_unexpected_stdout_not_exposed(tmp_path,raw):
    def run(argv,**kw):kw['stdout'].write(raw);return SimpleNamespace(returncode=0)
    result=W.execute(b'x',Path('/supervisor'),{'identity_file':'P','known_hosts':'K','target':'T'},tmp_path,run)
    assert result['failure_category']=='UNEXPECTED_OUTPUT' and not result['report_produced']
    assert 'secret-sentinel' not in json.dumps(result)

def test_mocked_end_to_end_blocked_report(tmp_path):
    r=report()
    def run(argv,**kw):kw['stdout'].write(json.dumps(r).encode());return SimpleNamespace(returncode=1)
    result=W.execute(b'x',Path('/supervisor'),{'identity_file':'P','known_hosts':'K','target':'T'},tmp_path,run)
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


def test_runtime_child_no_app_or_provider_imports():
    ast.parse(P.RUNTIME_CHILD,feature_version=(3,9))
    assert 'socket.socket=blocked' in P.RUNTIME_CHILD and 'socket.create_connection=blocked' in P.RUNTIME_CHILD
    assert 'api.app' not in P.RUNTIME_CHILD and 'model.predict' not in P.RUNTIME_CHILD


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
    assert len(sites)==2 and all(n.func.attr=='run' for n in sites)
    source=(DIR/'preflight_readonly.py').read_text()
    assert 'shell=True' not in source and 'setns' not in source
    assert "'/usr/bin/nsenter','--target'" in source and "'--mount','--setgid','992','--setuid','992'" in source


def test_environment_text_and_process_argv_cannot_be_emitted():
    assert all(not ({'environment','argv','ExecStart','credentials','token'} & fields) for fields in P.FIELDS.values())
    r=report();r['checks']['environment']['facts']['sha256']='not-a-hash secret-sentinel'
    with pytest.raises(ValueError):P.validate_report(r)
