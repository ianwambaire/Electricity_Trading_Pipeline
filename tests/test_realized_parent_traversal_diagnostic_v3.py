"""Real argv/supervisor, simulated SSH only. No network or privileged execution."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
import types
import pytest

ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'deploy/staging/realized-parent-traversal-diagnostic-v3'
PARENT=HERE.parent/'realized-parent-traversal-diagnostic-v2'

def load(name,folder=HERE):
    s=importlib.util.spec_from_file_location('stdin_test_'+name+('_old'if folder==PARENT else''),folder/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

@pytest.fixture(scope='module')
def package():
    b=load('build');parent,values=b.parent();transport,wrapper,supervisor,payload,schema,protocol,frame_id=values
    synthetic=copy.copy(wrapper)
    synthetic['profile']=lambda:{'target':'approved.invalid','identity_file':'/offline-do-not-open/identity','known_hosts':'/offline-do-not-open/known_hosts'}
    return parent,(transport,synthetic,supervisor,payload,schema,protocol,frame_id)

# This program never opens keys, connects sockets, runs SSH, sudo or setpriv.
# Its Python-only child reads stdin and executes the exact supplied bytes while
# deliberately forcing the payload's HOST gate to fail before any OS inspection.
SIMULATOR=r'''
import os,sys,subprocess
args=sys.argv[1:];i=0;stdin_null=None
while i<len(args):
 arg=args[i]
 if arg in {'-F','-i'}:i+=2;continue
 if arg=='-T':i+=1;continue
 if arg in {'-n','-f'}:stdin_null=True;i+=1;continue
 if arg=='-o':
  key,sep,value=args[i+1].partition('=')
  if key.lower()=='stdinnull'and stdin_null is None:
   assert value.lower()in {'yes','no'};stdin_null=value.lower()=='yes'
  i+=2;continue
 assert not arg.startswith('-')
 assert arg=='approved.invalid'and len(args[i:])==2
 assert args[i+1]=='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 20s /usr/bin/python3 -I -S -B -'
 break
assert stdin_null is not None

def audit(event,values):
 if event in {'socket.connect','socket.bind'}:raise RuntimeError('SIMULATOR_NETWORK_FORBIDDEN')
 if event=='subprocess.Popen'and values[0]!=sys.executable:raise RuntimeError('SIMULATOR_COMMAND_FORBIDDEN')
sys.addaudithook(audit)
shim="import sys,os,json,subprocess,selectors,signal,time,pwd,re,stat; source=sys.stdin.buffer.read(65537); assert len(source)<=65536; sys.platform='offline-identity-denied'; exec(compile(source,'<immutable-simulated-remote>','exec'),{'__name__':'__main__'})"
child=subprocess.run([sys.executable,'-I','-S','-B','-c',shim],stdin=subprocess.DEVNULL if stdin_null else None,check=False)
raise SystemExit(child.returncode)
'''


def simulate(tmp_path,argv,payload,supervisor):
    assert argv[0]=='/usr/bin/ssh'
    script=tmp_path/'simulated_ssh.py';script.write_text(SIMULATOR)
    # Only Python is launched, using the actual SSH argv after its executable.
    local=[sys.executable,'-I','-B',str(script),*argv[1:]]
    return supervisor(local,input=payload,timeout=10,limit=8192,grace=5)


def test_v2_actual_command_reproduces_observed_empty_stdout(tmp_path,package):
    parent,(transport,wrapper,supervisor,payload,schema,protocol,frame_id)=package
    command=parent.command(transport,wrapper);assert 'StdinNull=yes'in command
    result=simulate(tmp_path,command,payload,supervisor)
    assert result=={'returncode':0,'stdout':b'','stderr':b'','failure':None}
    assessment,candidate=parent.assess(result,schema,protocol,frame_id,wrapper)
    assert assessment['validation']=={'stage':'BYTES','code':'EMPTY_STDOUT','field':'FRAME'}
    assert assessment['report']is None and candidate is None


def test_correction_changes_only_the_one_stdin_setting(package):
    parent,(transport,wrapper,_,_,_,_,_)=package;r=load('run')
    before=parent.command(transport,wrapper);after=r.command(parent,transport,wrapper)
    assert len(before)==len(after)
    assert [(a,b)for a,b in zip(before,after)if a!=b]==[('StdinNull=yes','StdinNull=no')]
    assert 'StdinNull=yes'in transport.EXTRA_OPTIONS # original connectivity tool untouched
    assert after[-1]==before[-1]and 'sudo -n'in after[-1]
    assert all(option in after for option in ['StrictHostKeyChecking=yes','BatchMode=yes','PreferredAuthentications=publickey','NumberOfPasswordPrompts=0','RequestTTY=no','IdentityAgent=none','ProxyCommand=none','ConnectionAttempts=1'])


def test_v3_delivers_exact_immutable_payload_and_retains_strict_validation(tmp_path,package):
    parent,(transport,wrapper,supervisor,payload,schema,protocol,frame_id)=package;r=load('run')
    before=hashlib.sha256(payload).hexdigest()
    result=simulate(tmp_path,r.command(parent,transport,wrapper),payload,supervisor)
    assert result['returncode']==1 and result['stderr']==b''and result['failure']is None
    assessment,candidate=parent.assess(result,schema,protocol,frame_id,wrapper)
    assert assessment['failure']is None and assessment['validation']is None
    assert assessment['report']=={'status':'BLOCKED','changed':False,'stage':'HOST','reason':'LINUX_COORDINATOR_IDENTITY_REQUIRED','errno':None}
    assert candidate is None and before==hashlib.sha256(payload).hexdigest()
    assert json.loads(result['stdout'])['diagnostic_id']==frame_id


def test_appending_stdin_no_is_not_a_valid_correction(tmp_path,package):
    parent,(transport,wrapper,supervisor,payload,*_)=package
    argv=parent.command(transport,wrapper);argv=argv[:-2]+['-o','StdinNull=no']+argv[-2:]
    result=simulate(tmp_path,argv,payload,supervisor)
    assert result=={'returncode':0,'stdout':b'','stderr':b'','failure':None}

@pytest.mark.parametrize('kind',['missing','duplicate','case-variant','ssh-n','ssh-f','wrong-command'])
def test_stdin_policy_or_command_drift_stops_before_connection(package,kind):
    parent,(transport,wrapper,*_)=package;r=load('run');argv=parent.command(transport,wrapper)
    if kind=='missing':index=argv.index('StdinNull=yes');del argv[index-1:index+1]
    elif kind=='duplicate':argv=argv[:-2]+['-o','StdinNull=yes']+argv[-2:]
    elif kind=='case-variant':argv[argv.index('StdinNull=yes')]='stdinnull=YES'
    elif kind=='ssh-n':argv=argv[:-2]+['-n']+argv[-2:]
    elif kind=='ssh-f':argv=argv[:-2]+['-f']+argv[-2:]
    else:argv[-1]='/usr/bin/true'
    with pytest.raises(AssertionError):r.command(types.SimpleNamespace(command=lambda *a:argv),transport,wrapper)


def test_unmodified_v2_protocol_rejects_forged_or_malformed_reports(package):
    parent,(_,wrapper,_,_,schema,protocol,frame_id)=package
    for raw in [b'',b'{}',b'BANNER\n{}',b'{"private":"SECRET"}',b'\xff']:
        assessment,candidate=parent.assess({'returncode':0,'failure':None,'stdout':raw,'stderr':b'SECRET'},schema,protocol,frame_id,wrapper)
        assert assessment['failure']=='DIAGNOSTIC_OUTPUT_UNVERIFIED'and assessment['report']is None and candidate is None
        assert 'SECRET'not in json.dumps(assessment)


def test_previous_packages_are_preserved_and_payload_has_no_new_operations(package):
    _,(_,_,_,payload,*_)=package
    assert hashlib.sha256((PARENT/'MANIFEST.json').read_bytes()).hexdigest()=='303af3ff285c1628081bec69bd28dd3502e0bc0994765c753a3800b3a3e6ab05'
    assert payload==(PARENT/'inspect.payload.py').read_bytes()
    original=HERE.parent/'realized-performance-release-v1'
    assert hashlib.sha256((original/'MANIFEST.json').read_bytes()).hexdigest()=='a3dceba7641ceaa9030709b1b7d4ce59460b54f5123b7e89f15d95bba39b0a83'
    assert "StdinNull"not in(original/'run.py').read_text()
    for file in ['build.py','run.py']:ast.parse((HERE/file).read_bytes(),feature_version=(3,9))


def test_main_one_shot_pipeline_uses_corrected_transport_and_validates_response(tmp_path,monkeypatch,capsys,package):
    parent,(transport,original_wrapper,real_supervisor,payload,schema,protocol,frame_id)=package;r=load('run')
    private=tmp_path/'private';(private/'preflight').mkdir(parents=True);wrapper=copy.copy(original_wrapper);wrapper['PRIVATE']=private;calls=[]
    def simulated_attempt(argv,**kwargs):
        calls.append((argv,kwargs));return simulate(tmp_path,argv,kwargs['input'],real_supervisor)
    values=(transport,wrapper,simulated_attempt,payload,schema,protocol,frame_id)
    monkeypatch.setattr(r,'verify',lambda *a:(parent,values));monkeypatch.setattr(sys,'argv',['run.py','--manifest-sha256','a'*64])
    assert r.main()==1 # genuine local HOST denial, not a simulated Linux PASS
    report=json.loads(capsys.readouterr().out)
    assert report['failure']is None and report['report']['reason']=='LINUX_COORDINATOR_IDENTITY_REQUIRED'
    assert report['ssh_attempts']==1 and len(calls)==1 and 'StdinNull=no'in calls[0][0]
    assert calls[0][1]==dict(input=payload,timeout=40,limit=8192,grace=5)
    files=[p for p in private.rglob('*')if p.is_file()];assert len(files)==1 and files[0].name=='assessment.json'
    assert stat.S_IMODE(files[0].stat().st_mode)==0o600


def test_local_check_cannot_run_simulator_or_ssh(monkeypatch,package):
    parent,(transport,wrapper,_,payload,schema,protocol,frame_id)=package;r=load('run')
    values=(transport,wrapper,lambda *a,**kw:pytest.fail('process started'),payload,schema,protocol,frame_id)
    monkeypatch.setattr(r,'verify',lambda *a:(parent,values));monkeypatch.setattr(sys,'argv',['run.py','--manifest-sha256','a'*64,'--local-check'])
    assert r.main()==0


def test_final_immutable_binding_and_unchanged_source_bound_payload():
    r=load('run');raw=(HERE/'MANIFEST.json').read_bytes();parent,values=r.verify(r.sha(raw))
    transport,wrapper,_,payload,_,_,frame_id=values;m=json.loads(raw)
    assert payload==(PARENT/'inspect.payload.py').read_bytes()
    assert m['payload']['sha256']=='a01971eb4d9d47fbf1418dacbdcceaae2a98e78e6a09de87861f79b6ca1bfc2c'
    assert m['frame_id']==frame_id=='ad38f060fca7a4f8737598f8591dfb1041ee378ccdd59f53aa678301ace8e8d7'
    assert r.command(parent,transport,wrapper).count('StdinNull=no')==1


def test_manifest_or_stdin_policy_tampering_rejected_before_transport(monkeypatch):
    r=load('run');digest=r.sha((HERE/'MANIFEST.json').read_bytes())
    with pytest.raises(AssertionError):r.verify('0'*64)
    original=r.read;monkeypatch.setattr(r,'read',lambda p:b'changed'if Path(p)==HERE/'REVIEW.md'else original(p))
    with pytest.raises(AssertionError):r.verify(digest)
