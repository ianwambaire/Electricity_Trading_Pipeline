"""Offline protocol/serialization/runner regressions. Never invokes SSH or setpriv."""
import ast
import copy
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import stat
import sys
import types
import pytest

ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'deploy/staging/realized-parent-traversal-diagnostic-v2';PARENT=HERE.parent/'realized-parent-traversal-diagnostic-v1'
ID='a'*64

def load(name,parent=False):
    folder=PARENT if parent else HERE;s=importlib.util.spec_from_file_location('protocol_test_'+name+('_parent'if parent else''),folder/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def success():
    schema=load('inspect',True)
    return {'status':'PASS','changed':False,'reason':'TRAVERSAL_PASS','producer_probe':'TRAVERSAL_PASS','failed_path_id':'NONE','errno':None,'worker_primary_identity':'MATCH','worker_groups_match_cleared_probe':True,'worker_api_reader_group_present':False,'directories':[{'path_id':label,'owner':'ROOT','group':'API_READER_GROUP','mode':'0755','cleared_producer_mode_allows_search':True}for label in schema.LABELS],'stage':'COMPLETE'}

def frame(value=None,**changes):
    return json.dumps({'protocol_version':2,'diagnostic_id':ID,'report':success()if value is None else value,**changes},sort_keys=True).encode()+b'\n'

def outcome(m,reason,stderr=b''):
    return {'returncode':1,'stdout':b'','stderr':stderr,'failure':'TIMEOUT'if reason=='PRODUCER_PROBE_TIMEOUT'else'OUTPUT_LIMIT'if reason=='PRODUCER_PROBE_OUTPUT_LIMIT'else None}

def coordinator(reason,stderr=b''):
    m=load('inspect',True);m.sys=types.SimpleNamespace(platform='linux',version_info=(3,9,6));m.os=types.SimpleNamespace(O_PATH=1,O_NOFOLLOW=2,getuid=lambda:0,geteuid=lambda:0,getgid=lambda:0,getegid=lambda:0)
    m.trusted_commands=lambda:None;m.identities=lambda:[]
    m.metadata=lambda:[{'id':label,'uid':0,'gid':992,'mode':0o755,'identity':(1,2,3)}for label in m.LABELS]
    m.PRODUCER=b'fixed-producer';m.bounded_run=lambda *a,**kw:outcome(m,reason,stderr)
    return m

@pytest.mark.parametrize('reason,stderr',[
 ('PRODUCER_PROBE_TIMEOUT',b''),('PRODUCER_PROBE_OUTPUT_LIMIT',b''),
 ('PRODUCER_INTERPRETER_EXECUTION_FAILED',b'setpriv: failed to execute SECRET_PATH'),
 ('PRODUCER_PRIVILEGE_DROP_FAILED',b'setpriv: setgroups SECRET'),
 ('PRODUCER_PYTHON_STARTUP_FAILED',b'Fatal Python error: SECRET'),
 ('PRODUCER_PROBE_OUTPUT_UNVERIFIED',b'SECRET'),
])
def test_exact_v1_enum_mismatch_reproduced_and_failure_stays_blocked(reason,stderr):
    schema=coordinator(reason,stderr);report=schema.inspect()
    assert report['reason']==report['producer_probe']==reason and report['status']=='BLOCKED'
    with pytest.raises(ValueError):load('run',True).validate_report(json.loads(json.dumps(report)),schema)
    # Legitimate emitted failure is now reportable; never a successful access test.
    parsed=load('protocol').decode(frame(report),1,schema,ID)
    assert parsed==report and parsed['status']=='BLOCKED'and 'SECRET'not in json.dumps(parsed)


def test_success_round_trip_does_not_reproduce_lost_historical_mismatch():
    old=load('run',True);schema=load('inspect',True);wire=load('protocol');count=0
    for group,mode,reader in itertools.product(['ROOT_GROUP','PRODUCER_GROUP','API_READER_GROUP','OTHER'],['0700','0711','0750','0755','2750'],[False,True]):
        value=success();value.update(worker_groups_match_cleared_probe=False,worker_api_reader_group_present=reader)
        for row in value['directories']:
            row.update(group=group,mode=mode,cleared_producer_mode_allows_search=bool(int(mode,8)&(0o010 if group=='PRODUCER_GROUP'else 0o001)))
        assert old.validate_report(json.loads(json.dumps(value)),schema)==value
        assert wire.decode(frame(value),0,schema,ID)==value;count+=1
    assert count==40


@pytest.mark.parametrize('raw,stage,code',[
 (b'','BYTES','EMPTY_STDOUT'),(b'x'*8193,'BYTES','OUTPUT_BOUND'),(b'\xff','UTF8','INVALID_UTF8'),
 (b'BANNER\n{}','JSON','INVALID_JSON'),(b'{}\n{}','JSON','INVALID_JSON'),
 (b'{"a":1,"a":2}','JSON','DUPLICATE_JSON_KEY'),(b'{"a":NaN}','JSON','NONFINITE_JSON'),
 (b'{"a":Infinity}','JSON','NONFINITE_JSON'),(b'{}','FRAME','FRAME_FIELDS'),
])
def test_invalid_framing_fails_closed_without_raw_values(raw,stage,code):
    wire=load('protocol')
    with pytest.raises(wire.Rejected)as e:wire.decode(raw,0,load('inspect',True),ID)
    assert e.value.safe()=={'stage':stage,'code':code,'field':'FRAME'}

@pytest.mark.parametrize('changes,code',[
 ({'protocol_version':True},'FRAME_VERSION'),({'protocol_version':1},'FRAME_VERSION'),
 ({'diagnostic_id':'b'*64},'FRAME_BINDING'),({'diagnostic_id':'SECRET'},'FRAME_BINDING'),
 ({'private':'SECRET'},'FRAME_FIELDS'),
])
def test_binding_and_version_cannot_be_bypassed(changes,code):
    wire=load('protocol')
    with pytest.raises(wire.Rejected)as e:wire.decode(frame(**changes),0,load('inspect',True),ID)
    assert e.value.code==code and 'SECRET'not in json.dumps(e.value.safe())

@pytest.mark.parametrize('changes,stage,code',[
 ({'status':'OTHER'},'REPORT','STATUS'),({'changed':0},'REPORT','CHANGED'),
 ({'changed':True},'REPORT','CHANGED'),({'reason':'SECRET'},'REPORT','REASON'),
 ({'reason':[]},'REPORT','REASON'),({'stage':[]},'REPORT','STAGE'),
 ({'errno':True},'REPORT','ERRNO'),({'worker_primary_identity':'Admin'},'REPORT','PRIMARY_IDENTITY'),
 ({'worker_groups_match_cleared_probe':1},'REPORT','GROUP_FLAGS'),
 ({'worker_api_reader_group_present':True},'CONSISTENCY','GROUP_CONSISTENCY'),
 ({'producer_probe':'SECRET'},'REPORT','PRODUCER_RESULT'),
 ({'failed_path_id':'/private/SECRET'},'REPORT','PATH_ID'),
 ({'directories':[]},'DIRECTORY','DIRECTORY_COUNT'),
 ({'private':'SECRET'},'REPORT','REPORT_FIELDS'),
 ({'status':'BLOCKED'},'CONSISTENCY','STATUS_CONSISTENCY'),
])
def test_report_validation_is_specific_and_does_not_echo_values(changes,stage,code):
    value=success();value.update(changes);wire=load('protocol')
    with pytest.raises(wire.Rejected)as e:wire.decode(frame(value),0,load('inspect',True),ID)
    assert e.value.stage==stage and e.value.code==code and 'SECRET'not in json.dumps(e.value.safe())

@pytest.mark.parametrize('key',list(success()))
def test_every_missing_report_field_is_rejected(key):
    value=success();del value[key];wire=load('protocol')
    with pytest.raises(wire.Rejected)as e:wire.decode(frame(value),0,load('inspect',True),ID)
    assert e.value.code=='REPORT_FIELDS'

@pytest.mark.parametrize('changes,code',[
 ({'mode':'SECRET'},'DIRECTORY_MODE'),({'mode':'0777'},'DIRECTORY_MODE'),
 ({'owner':'OTHER'},'DIRECTORY_OWNER'),({'group':[]},'DIRECTORY_GROUP'),
 ({'path_id':'SECRET'},'DIRECTORY_ORDER'),({'private':'SECRET'},'DIRECTORY_FIELDS'),
 ({'cleared_producer_mode_allows_search':1},'DIRECTORY_SEARCH_FLAG'),
 ({'cleared_producer_mode_allows_search':False},'DIRECTORY_SEARCH_FLAG'),
])
def test_directory_fields_are_minimal_typed_and_consistent(changes,code):
    value=success();value['directories'][2].update(changes);wire=load('protocol')
    with pytest.raises(wire.Rejected)as e:wire.decode(frame(value),0,load('inspect',True),ID)
    assert e.value.code==code and 'SECRET'not in json.dumps(e.value.safe())
    assert e.value.field.startswith('REPORT_STORE_PARENT.')


def test_exit_mismatch_fails_but_saves_only_structurally_valid_candidate():
    value=success();wire=load('protocol')
    with pytest.raises(wire.Rejected)as e:wire.decode(frame(value),1,load('inspect',True),ID)
    assert e.value.safe()=={'stage':'EXIT_STATUS','code':'EXIT_STATUS_MISMATCH','field':'EXIT_STATUS'}
    assert e.value.candidate==value


def test_base_error_can_never_claim_success():
    wire=load('protocol');schema=load('inspect',True)
    value={'status':'BLOCKED','changed':False,'reason':'PARENT_METADATA_UNSAFE','stage':'PARENT_METADATA','errno':None}
    assert wire.decode(frame(value),1,schema,ID)==value
    value['status']='PASS'
    with pytest.raises(wire.Rejected):wire.decode(frame(value),0,schema,ID)


def test_legacy_unframed_success_is_not_accepted_as_v2():
    wire=load('protocol')
    with pytest.raises(wire.Rejected)as e:wire.decode(json.dumps(success()).encode(),0,load('inspect',True),ID)
    assert e.value.code=='FRAME_FIELDS'


def test_only_output_serialization_changes_in_remote_payload():
    b=load('build');*_,framed,schema,frame_id=b.assemble();*_,original,_=b.parent()
    marker=b"print(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']=='PASS'else 1)\n"
    oldprefix=original.split(marker)[0];assert framed.startswith(oldprefix)
    old={n.name:ast.dump(n,include_attributes=False)for n in ast.walk(ast.parse(original))if isinstance(n,ast.FunctionDef)}
    new={n.name:ast.dump(n,include_attributes=False)for n in ast.walk(ast.parse(framed))if isinstance(n,ast.FunctionDef)}
    assert old==new;ast.parse(framed,feature_version=(3,9));assert frame_id.encode()in framed
    assert schema.CHILD_ARGV==['/usr/bin/setpriv','--no-new-privs','--reuid=1000','--regid=1000','--clear-groups','/usr/bin/python3','-I','-S','-B','-']

@pytest.mark.parametrize('code,body,expected_exit,expected_validation',[(0,'valid',0,None),(0,'empty',1,'EMPTY_STDOUT'),(0,'blocked',1,'EXIT_STATUS_MISMATCH')])
def test_runner_serialization_transport_and_validation_end_to_end(tmp_path,monkeypatch,capsys,code,body,expected_exit,expected_validation):
    r=load('run');wire=load('protocol');schema=load('inspect',True);value=success()
    if body=='blocked':value={'status':'BLOCKED','changed':False,'reason':'PARENT_METADATA_UNSAFE','stage':'PARENT_METADATA','errno':None}
    raw=b''if body=='empty'else frame(value)
    private=tmp_path/'private';(private/'preflight').mkdir(parents=True);calls=[]
    wrapper={'PRIVATE':private};supervisor=lambda argv,**kw:calls.append((argv,kw))or {'returncode':code,'failure':None,'stdout':raw,'stderr':b'SECRET /private/path'}
    monkeypatch.setattr(r,'verify',lambda *a:(None,wrapper,supervisor,b'framed-reviewed-payload',schema,wire,ID));monkeypatch.setattr(r,'command',lambda *a:['one-approved-command'])
    monkeypatch.setattr(sys,'argv',['run.py','--manifest-sha256','a'*64])
    assert r.main()==expected_exit and len(calls)==1
    output=json.loads(capsys.readouterr().out);assert 'SECRET'not in json.dumps(output)
    files=[p for p in private.rglob('*')if p.is_file()];assert len(files)==1 and stat.S_IMODE(files[0].stat().st_mode)==0o600
    retained=json.loads(files[0].read_bytes());assert 'SECRET'not in json.dumps(retained)and '/private/path'not in files[0].read_text()
    if expected_validation:
        assert output['report']is None and retained['validation']['code']==expected_validation
        assert retained['unaccepted_sanitized_candidate']==(value if body=='blocked'else None)
    else:assert output['report']==value and output['failure']is None
    assert calls[0][1]==dict(input=b'framed-reviewed-payload',timeout=40,limit=8192,grace=5)


def test_schema_exception_does_not_persist_unknown_field_names_or_values():
    r=load('run');wire=load('protocol');value=success();value['SECRET_FIELD']='SECRET_VALUE'
    summary,candidate=r.assess({'returncode':0,'failure':None,'stdout':frame(value),'stderr':b'SECRET_STDERR'},load('inspect',True),wire,ID,{})
    assert summary['validation']=={'stage':'REPORT','code':'REPORT_FIELDS','field':'REPORT'}
    assert summary['report']is None and candidate is None and 'SECRET'not in json.dumps(summary)


def test_previous_packages_and_evidence_binding_unchanged():
    assert hashlib.sha256((PARENT/'MANIFEST.json').read_bytes()).hexdigest()=='41ebe0af3a0f9533af40e618c77be0238caa4d194366178ac1c7fd613a8ed4d6'
    reporting=HERE.parent/'realized-performance-release-v1/MANIFEST.json'
    assert hashlib.sha256(reporting.read_bytes()).hexdigest()=='a3dceba7641ceaa9030709b1b7d4ce59460b54f5123b7e89f15d95bba39b0a83'


def test_actual_payload_serializer_and_strict_decoder_end_to_end(capsys):
    b=load('build');_,_,_,payload,schema,frame_id=b.assemble()
    prefix,tail=payload.split(b'try:\n report=inspect()',1);ns={}
    exec(compile(prefix,'<offline-serialization-prefix>','exec'),ns)
    m=coordinator('TRAVERSAL_PASS')
    m.bounded_run=lambda *a,**kw:{'returncode':0,'failure':None,'stderr':b'','stdout':b'{"version":1,"reason":"TRAVERSAL_PASS","path_id":"NONE","errno":null}'}
    produced=m.inspect();ns['inspect']=lambda:produced
    with pytest.raises(SystemExit)as exit:exec(compile(b'try:\n report=inspect()'+tail,'<offline-serialization>','exec'),ns)
    assert exit.value.code==0
    wire=load('protocol');assert wire.decode(capsys.readouterr().out.encode(),0,schema,frame_id)==produced


def test_immutable_v2_bindings_and_executable_closure():
    r=load('run');digest=r.sha((HERE/'MANIFEST.json').read_bytes())
    transport,wrapper,supervisor,payload,schema,protocol,frame_id=r.verify(digest)
    m=json.loads((HERE/'MANIFEST.json').read_bytes());assert m['frame_id']==frame_id and m['payload']['sha256']==r.sha(payload)
    assert m['parent_manifest']=='41ebe0af3a0f9533af40e618c77be0238caa4d194366178ac1c7fd613a8ed4d6'
    argv=r.command(transport,wrapper)
    assert argv[-1]=='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 20s /usr/bin/python3 -I -S -B -'
    assert all(option in argv for option in ['StrictHostKeyChecking=yes','PreferredAuthentications=publickey','IdentityAgent=none','ConnectionAttempts=1','ProxyCommand=none'])
    for path in HERE.glob('*.py'):ast.parse(path.read_bytes(),feature_version=(3,9))


def test_bad_manifest_or_modified_protocol_rejected_before_transport(monkeypatch):
    r=load('run');digest=r.sha((HERE/'MANIFEST.json').read_bytes())
    with pytest.raises(AssertionError):r.verify('0'*64)
    original=r.read;monkeypatch.setattr(r,'read',lambda p:b'modified'if Path(p)==HERE/'protocol.py'else original(p))
    with pytest.raises(AssertionError):r.verify(digest)


def test_local_verification_cannot_invoke_ssh(monkeypatch):
    r=load('run');monkeypatch.setattr(r,'verify',lambda *a:(None,None,lambda *a,**kw:pytest.fail('SSH invoked'),b'payload',None,None,ID))
    monkeypatch.setattr(r,'command',lambda *a:['fixed-reviewed-command']);monkeypatch.setattr(sys,'argv',['run.py','--manifest-sha256','a'*64,'--local-check'])
    assert r.main()==0
