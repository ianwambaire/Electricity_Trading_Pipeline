"""Synthetic receipts and isolated SQLite only. No network or privileged writes."""
import ast
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace
import pytest
import shared.forecast_publication as contract
from test_inference_evidence import captured,builder

ROOT=Path(__file__).parents[1]
FOLDER=ROOT/'deploy/staging/forecast-publication/automatic-acceptance'
FLOW='22222222-2222-4222-8222-222222222222'
FT='33333333-3333-4333-8333-333333333333'
PT='44444444-4444-4444-8444-444444444444'
INTERNAL='a'*32

def load(name):
    s=importlib.util.spec_from_file_location('acceptance_'+name,FOLDER/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket,'create_connection',lambda *a,**kw:pytest.fail('Unexpected network attempt'))

@pytest.fixture
def sample(captured,monkeypatch):
    directory,forecast,matrix,paths,now=captured
    m=load('inspect');monkeypatch.setattr(m,'CONTRACT',contract,raising=False);monkeypatch.setattr(m,'BUILDER',builder,raising=False)
    proof=json.loads((directory/'evidence.json').read_bytes());e=proof['execution'];start=m.stamp(e['started_at']);end=m.stamp(e['completed_at'])
    scheduled=start.replace(minute=45,second=0,microsecond=0)
    if scheduled>=start:scheduled-=dt.timedelta(hours=1)
    m.ACTIVATED=(scheduled-dt.timedelta(hours=1)).isoformat()
    fs=scheduled+dt.timedelta(seconds=1);ts=start-dt.timedelta(seconds=1);te=end+dt.timedelta(seconds=1);ps=te+dt.timedelta(seconds=1);pe=ps+dt.timedelta(seconds=1);fe=pe+dt.timedelta(seconds=3)
    clock=max(now.to_pydatetime(),fe+dt.timedelta(seconds=1))
    flow={'id':FLOW,'deployment_id':m.DEP,'auto_scheduled':True,'state':{'type':'COMPLETED'},'expected_start_time':scheduled.isoformat(),'start_time':fs.isoformat(),'end_time':fe.isoformat()}
    tasks=[{'id':FT,'flow_run_id':FLOW,'name':'Generate next24h production forecast-test','state':{'type':'COMPLETED'},'start_time':ts.isoformat(),'end_time':te.isoformat()},
           {'id':PT,'flow_run_id':FLOW,'name':'Publish validated staging next24h forecast-test','state':{'type':'COMPLETED'},'start_time':ps.isoformat(),'end_time':pe.isoformat()}]
    files={n:(directory/n).read_bytes() for n in m.NAMES}
    bundle,digest,hashes,expired=m.receipt_bundle(files,directory.name,contract,builder,clock)
    class IO:
        def __init__(self):
            self.flows=[flow];self.task_list=tasks;self.result=(directory.name,files);self.status='PUBLISHED';self.raw=json.dumps(bundle,sort_keys=True,separators=(',',':'),allow_nan=False).encode();self.target='releases/'+digest;self.forecast_code=200;self.operations='VALID';self.cache='no-store';self.now=clock;self.mutation=None;self.calls=[]
        def sources(self):pass
        def clock(self):return self.now
        def runs(self):return self.flows
        def flow(self,identity):assert identity==FLOW;return flow
        def tasks(self,identity):assert identity==FLOW;return self.task_list
        def receipt(self,t):assert t['id']==FT;return self.result
        def outcome(self,f,t):return {'internal_run_id':INTERNAL,'status':self.status,'forecast_status':'GENERATED','generated':True,'issue':bundle['forecasts'][0]['issue_time']}
        def history(self,b):assert b==bundle
        def publication(self):return {'publication_state':'EXPIRED' if self.now>m.stamp(bundle['forecasts'][0]['issue_time'])+contract.MAX_AGE else 'VALID'},self.raw,self.target
        def recheck(self,target):
            if self.target!=target:raise m.Stop('POINTER_DRIFT')
        def http(self,path):
            self.calls.append(path)
            if path.endswith('/forecast/next24'):
                data={'detail':{'code':'FORECAST_WITHHELD'}} if self.forecast_code==503 else {'row_count':24,'forecasts':copy.deepcopy(bundle['forecasts']),'publication':{'status':'VALID','issue_time':bundle['forecasts'][0]['issue_time'],'expires_at':(m.stamp(bundle['forecasts'][0]['issue_time'])+contract.MAX_AGE).isoformat(),'completed_at':bundle['execution']['completed_at']}}
                if self.mutation:self.mutation(data)
                return self.forecast_code,{'cache-control':self.cache},data
            return 200,{}, {'forecast_status':self.operations,'forecast_reason':'issue '+m.stamp(bundle['forecasts'][0]['issue_time']).isoformat()+' cutoff '+(m.stamp(bundle['forecasts'][0]['issue_time'])+contract.MAX_AGE).isoformat()}
    return m,IO(),bundle,flow,tasks,files

def test_published_matching_receipt_bundle_and_api(sample):
    m,io,b,flow,tasks,files=sample;r=m.validate_report(m.inspect(io,io.now))
    assert r['status']=='PASS' and r['delivery_status']=='PUBLISHED' and r['api_predictions']==24,r['gaps']
    assert r['features']==31 and r['pointer_binding']=='PASS' and r['react']=='PENDING_BROWSER'
    t=r['timing'];assert t['publication_time']is None and t['publication_time_evidence']=='NOT_PERSISTED'
    assert t['completion_to_publication_seconds_bounds'][1]<0 and t['remaining_at_publication_seconds_bounds'][0]>0
    assert 'feature_values' not in json.dumps(r) and 'inputs' not in json.dumps(r)

@pytest.mark.parametrize('kind',['none','manual','before_activation','running'])
def test_no_completed_post_activation_natural_run(sample,kind):
    m,io,b,flow,tasks,files=sample
    if kind=='none':io.flows=[]
    elif kind=='manual':flow['auto_scheduled']=False
    elif kind=='before_activation':m.ACTIVATED=io.now.isoformat()
    else:flow['state']['type']='RUNNING'
    r=m.inspect(io,io.now);assert r['status']=='BLOCKED' and r['gaps']==['NO_COMPLETED_POST_ACTIVATION_NATURAL_RUN'] and not io.calls

@pytest.mark.parametrize('kind',['receipt','status','unrecognized'])
def test_missing_receipt_or_delivery_evidence(sample,kind):
    m,io,*_=sample
    if kind=='receipt':io.result=None
    elif kind=='status':io.status=None
    else:io.status='PRIVATE_SECRET'
    r=m.validate_report(m.inspect(io,io.now));assert r['status'] in {'PARTIAL','FAILED'} and not io.calls
    assert 'PRIVATE_SECRET' not in json.dumps(r)

@pytest.mark.parametrize('status',['SKIPPED_DUPLICATE','SKIPPED_WITHHELD','SKIPPED_EXPIRED','REJECTED_OLDER_ISSUE','REJECTED_INFERENCE','FAILED','DISABLED'])
def test_actual_nonpublished_status_never_claims_published(sample,status):
    m,io,*_=sample;io.status=status;r=m.inspect(io,io.now)
    assert r['delivery_status']==status and r['status']=='PARTIAL' and 'DELIVERY_DID_NOT_PUBLISH_THIS_RUN' in r['gaps']

@pytest.mark.parametrize('kind',['pointer','receipt','bytes','switch'])
def test_publication_receipt_or_pointer_mismatch(sample,kind):
    m,io,b,flow,tasks,files=sample
    if kind=='pointer':io.target='releases/'+'0'*64
    elif kind=='receipt':io.result=('55555555-5555-4555-8555-555555555555',files)
    elif kind=='bytes':io.raw=b'{}'
    else:
        def switched(path):io.target='releases/'+'0'*64
        original=io.http
        def changing(path):r=original(path);switched(path);return r
        io.http=changing
    r=m.inspect(io,io.now);assert r['status']=='FAILED'


def test_expiry_structural_checks_and_withheld_api(sample):
    m,io,b,*_=sample;io.now=m.stamp(b['forecasts'][0]['issue_time'])+contract.MAX_AGE+dt.timedelta(seconds=1);io.forecast_code=503;io.operations='EXPIRED'
    r=m.validate_report(m.inspect(io,io.now));assert r['status']=='PARTIAL' and r['receipt_integrity']=='PASS' and r['pointer_binding']=='PASS'
    assert r['api_state']=='WITHHELD' and r['api_predictions']==0 and r['operations_status']=='EXPIRED' and r['timing']['expired_at_inspection']

@pytest.mark.parametrize('kind',['withheld_fresh','operations','provenance_missing','provenance_bad','provenance_malformed','count','values','alignment','nan','cache','fake_cache','historical'])
def test_api_contract_failures(sample,kind):
    m,io,*_=sample
    if kind=='withheld_fresh':io.forecast_code=503
    elif kind=='operations':io.operations='MISSING_PUBLICATION'
    elif kind in ['cache','fake_cache']:io.cache='public' if kind=='cache' else 'x-no-store'
    else:
        def mutate(data):
            if kind=='provenance_missing':data.pop('publication')
            elif kind=='provenance_bad':data['publication']['issue_time']='2020-01-01T00:00Z'
            elif kind=='provenance_malformed':data['publication']='PRIVATE_TOKEN'
            elif kind=='count':data['forecasts'].pop()
            elif kind=='values':data['forecasts'][0]['predicted_price_eur_mwh']+=1
            elif kind=='alignment':data['forecasts'][0]['target_time']=data['forecasts'][1]['target_time']
            elif kind=='nan':data['forecasts'][0]['predicted_price_eur_mwh']=float('nan')
            elif kind=='historical':data.pop('publication');data['row_count']=500
        io.mutation=mutate
    r=m.inspect(io,io.now);assert r['status']=='FAILED'


def test_unexpected_errors_and_output_are_sanitized(sample):
    m,io,*_=sample
    io.receipt=lambda *a:(_ for _ in ()).throw(FileNotFoundError(2,'SECRET','/private/SECRET'))
    r=m.inspect(io,io.now);assert r['gaps']==['EVIDENCE_UNVERIFIED'] and 'SECRET' not in json.dumps(r)
    for extra in [{'secret':'TOKEN'},{'gaps':['/private/path']},{'receipt':'TOKEN'},{'timing':{'secret':'TOKEN'}}]:
        with pytest.raises(Exception):m.validate_report(dict(r,**extra))


def test_fixed_http_scope_bounds_no_redirects(monkeypatch):
    m=load('inspect');calls=[]
    class Response:
        status=200
        def read(self,n):calls.append(('read',n));return b'{}'
        def getheader(self,k):return 'application/json'
        def getheaders(self):return [('Cache-Control','no-store')]
    class Connection:
        def __init__(self,host,timeout):calls.append(('connect',host,timeout))
        def request(self,method,path):calls.append((method,path))
        def getresponse(self):return Response()
        def close(self):calls.append(('close',))
    monkeypatch.setattr(m.http.client,'HTTPSConnection',Connection)
    for path,timeout in [('/api/forecast/next24',5),('/api/operations/summary',10)]:
        m.request(path);assert ('connect','staging.powerflowenergy.dev',timeout)in calls
    assert ('read',262145)in calls
    for path in ['http://evil','/api/admin/operations','/api/forecast/next24?unbounded=true']:
        with pytest.raises(m.Stop):m.request(path)
    class Large(Response):
        def read(self,n):return b'x'*n
    monkeypatch.setattr(Connection,'getresponse',lambda self:Large())
    with pytest.raises(m.Stop,match='HTTP_BODY_BOUND'):m.request('/api/forecast/next24')


def test_no_mutation_entrypoints_or_dynamic_application_imports():
    r=load('run');tree=ast.parse((FOLDER/'inspect.py').read_bytes())
    forbidden={'write','write_bytes','write_text','mkdir','unlink','rmdir','rename','chmod','chown','fchmod','fchown','system','popen','publish','publish_automatic','rollback'}
    assert not {n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}&forbidden
    assert 'os.replace(' not in (FOLDER/'inspect.py').read_text()
    assert not any(isinstance(n,(ast.Import,ast.ImportFrom)) and 'models' in ast.unparse(n) for n in ast.walk(tree))
    auto=r.extract((ROOT/r.AUTO).read_bytes(),['require','stamp','capture','persisted']);builder=r.extract((ROOT/r.BUILDER).read_bytes(),['build'])
    assert {n.name for n in ast.parse(auto).body if isinstance(n,ast.FunctionDef)}=={'require','stamp','capture','persisted'}
    assert {n.name for n in ast.parse(builder).body if isinstance(n,ast.FunctionDef)}=={'build'}
    assert b'publish_automatic' not in auto and b'.open(' not in builder and b'deliver(' not in auto

@pytest.mark.parametrize('kind',['valid','missing_status','journal','symlink','ambiguous','bad_internal','wrong_issue_source'])
def test_readonly_database_association_in_isolated_fixture(sample,tmp_path,monkeypatch,kind):
    m,io,b,flow,tasks,files=sample;prod=tmp_path/'production';(prod/'database').mkdir(parents=True);path=prod/'database/electricity_trading.db'
    c=sqlite3.connect(path);c.executescript('CREATE TABLE pipeline_stage_timings(run_id TEXT,stage_name TEXT,start_timestamp_utc TEXT,end_timestamp_utc TEXT,status TEXT); CREATE TABLE pipeline_runs(id INTEGER PRIMARY KEY,run_time TEXT,status TEXT,message TEXT);')
    t=tasks[0];internal='not-an-id' if kind=='bad_internal' else INTERNAL
    c.execute('INSERT INTO pipeline_stage_timings VALUES (?,?,?,?,?)',(internal,'Next24h forecast generation',t['start_time'],t['end_time'],'SUCCESS'))
    meta={'run_id':INTERNAL,'status':'SUCCESS','next24h_publication_status':None if kind=='missing_status' else 'PUBLISHED','next24h_forecast_status':'GENERATED','next24h_forecast_generated':True,'next24h_forecast_issue_time':b['forecasts'][0]['issue_time'],'private':'SECRET_TOKEN'}
    if kind=='wrong_issue_source':meta['run_id']='b'*32
    c.execute('INSERT INTO pipeline_runs VALUES (1,?,?,?)',(flow['end_time'],'SUCCESS',json.dumps(meta)))
    if kind=='ambiguous':c.execute('INSERT INTO pipeline_stage_timings SELECT * FROM pipeline_stage_timings')
    c.commit();c.close();path.chmod(0o644);original=path.read_bytes();monkeypatch.setattr(m,'ROOT',prod)
    if kind=='journal':Path(str(path)+'-wal').write_bytes(b'active')
    if kind=='symlink':target=prod/'database/real.db';path.rename(target);path.symlink_to(target)
    real_stat=m.os.fstat
    class Metadata:
        def __init__(self,s):self.s=s;self.st_uid=1000
        def __getattr__(self,n):return getattr(self.s,n)
    monkeypatch.setattr(m.os,'fstat',lambda fd:Metadata(real_stat(fd)))
    connect=m.sqlite3.connect;calls=[];statements=[]
    def mapped(database_uri,**kw):
        assert database_uri.startswith('file:/proc/self/fd/') and database_uri.endswith('?mode=ro&immutable=1') and kw=={'uri':True,'timeout':2}
        calls.append(database_uri);connection=connect(path.as_uri()+'?mode=ro&immutable=1',**kw);connection.set_trace_callback(statements.append);return connection
    monkeypatch.setattr(m.sqlite3,'connect',mapped)
    if kind in ['valid','missing_status']:
        result=m.database_outcome(flow,t);assert result['status']==('PUBLISHED' if kind=='valid' else None)
        assert result['internal_run_id']==INTERNAL and 'SECRET_TOKEN' not in json.dumps(result)
        assert all(s.startswith(('PRAGMA query_only=ON','SELECT ')) for s in statements)
        assert path.read_bytes()==original
    else:
        if kind=='symlink':
            with pytest.raises(OSError):m.database_outcome(flow,t)
        else:
            code={'journal':'DATABASE_ACTIVE_JOURNAL','ambiguous':'INTERNAL_RUN_ASSOCIATION','bad_internal':'INTERNAL_RUN_ASSOCIATION','wrong_issue_source':'PIPELINE_RECORD_ASSOCIATION'}[kind]
            with pytest.raises(m.Stop,match=code):m.database_outcome(flow,t)
        if kind in ['journal','symlink']:assert not calls


def test_crossing_expiry_is_partial_not_a_deployment_failure(sample):
    m,io,b,*_=sample;cutoff=m.stamp(b['forecasts'][0]['issue_time'])+contract.MAX_AGE
    io.now=cutoff-dt.timedelta(seconds=1);io.forecast_code=503;io.operations='EXPIRED';original=io.http
    def crossing(path):io.now=cutoff+dt.timedelta(seconds=1);return original(path)
    io.http=crossing;r=m.validate_report(m.inspect(io,cutoff-dt.timedelta(seconds=1)))
    assert r['status']=='PARTIAL' and r['api_state']=='WITHHELD' and 'FRESHNESS_BOUNDARY_DURING_READBACK'in r['gaps']


def test_receipt_directory_and_fixed_helpers_reject_symlinks(tmp_path):
    r=load('run');ns={'__name__':'readonly_helpers','NAMES':{'evidence.json'}}
    exec(compile(r.extract((ROOT/r.AUTO).read_bytes(),['require','stamp','capture','persisted']),'<test-readonly-capture>','exec'),ns)
    directory=tmp_path/'receipt';directory.mkdir(mode=0o700);target=tmp_path/'secret';target.write_bytes(b'PRIVATE');(directory/'evidence.json').symlink_to(target)
    with pytest.raises(OSError):ns['capture'](directory,'evidence.json',os.getuid())
    for name in ['../secret','/private/secret','..']:
        with pytest.raises(ValueError):ns['capture'](directory,name,os.getuid())
    m=load('inspect');link=tmp_path/'link';link.symlink_to(directory)
    with pytest.raises(OSError):m.directory(link)


def test_manifest_dependency_closure_and_verified_bytes(monkeypatch):
    r=load('run');raw=(FOLDER/'MANIFEST.json').read_bytes();manifest=json.loads(raw);expected=hashlib.sha256(raw).hexdigest()
    real_namespace=r.namespace
    monkeypatch.setattr(r,'namespace',lambda raw,name,file=None:{'profile':lambda:{}} if name=='wrapper' else real_namespace(raw,name,file))
    original=r.read;counts={}
    def once(path):
        counts[path]=counts.get(path,0)+1
        if counts[path]>1:raise AssertionError('Executable dependency reopened')
        return original(path)
    monkeypatch.setattr(r,'read',once)
    payload,_,_,_=r.verify(expected)
    assert hashlib.sha256(payload).hexdigest()==manifest['payload_sha256'] and all(n==1 for n in counts.values())
    assert b'publish_automatic' not in payload and b'install(' not in payload
    # Every embedded code body is hashed in the exact artifact inventory.
    blobs={name:(ROOT/name).read_bytes() for name in r.ARTIFACTS}
    blobs[r.CONTRACT]=b'raise RuntimeError("tampered")'
    assert hashlib.sha256(r.assemble(blobs)).hexdigest()!=manifest['payload_sha256']
    monkeypatch.setattr(r,'read',lambda path:b'changed' if path==ROOT/r.CONTRACT else original(path))
    with pytest.raises(ValueError,match='dependency_hash'):r.verify(expected)


@pytest.mark.parametrize('kind',['pass','ssh','bad_output'])
def test_wrapper_one_attempt_limits_and_sanitization(tmp_path,monkeypatch,capsys,kind):
    r=load('run');v=load('inspect');(tmp_path/'preflight').mkdir();calls=[]
    # Transport success with a blocked, correctly sanitized report is still non-PASS.
    report={'status':'BLOCKED','inspected_at':'2026-11-03T16:00:00+00:00','phase':'RUN','run':None,'receipt':None,'delivery_status':None,'publication':'UNVERIFIED','gaps':['NO_COMPLETED_POST_ACTIVATION_NATURAL_RUN'],'react':'PENDING_BROWSER','read_only':True}
    def run(argv,**kwargs):
        calls.append((argv,kwargs));return {'returncode':255 if kind=='ssh' else 1,'failure':'SSH_FAILURE' if kind=='ssh' else None,'stdout':b'{"secret":"TOKEN"}' if kind=='bad_output' else json.dumps(report).encode(),'stderr':b'PRIVATE_TRANSPORT'}
    w={'PRIVATE':tmp_path,'profile':lambda:{},'ssh_argv':lambda p:['reviewed_ssh','fixed_command'],'failure_category':lambda *a:'UNEXPECTED_OUTPUT'}
    monkeypatch.setattr(r,'verify',lambda *a:(b'held-verified-payload',w,{'bounded_run':run},{'validate_report':v.validate_report}))
    monkeypatch.setattr('sys.argv',['run.py','--manifest-sha256','a'*64]);old=os.umask(0o077);os.umask(old)
    try:assert r.main()==1
    finally:os.umask(old)
    assert len(calls)==1;argv,kw=calls[0]
    assert argv[-1]=='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 90s /usr/bin/python3 -I -S -B -'
    assert kw=={'input':b'held-verified-payload','timeout':150,'limit':65536,'grace':5}
    result=capsys.readouterr().out;assert 'TOKEN' not in result and 'PRIVATE_TRANSPORT' not in result
    for file in (tmp_path/'preflight').rglob('*'):
        assert file.stat().st_mode&0o777==(0o700 if file.is_dir() else 0o600)

@pytest.mark.parametrize('kind',['unrelated_change','run_identity','timestamp','task_flow','task_state','source_drift'])
def test_run_and_task_correlations_fail_closed_on_relevant_drift(sample,kind):
    m,io,b,flow,tasks,files=sample;copy_flow=copy.deepcopy(flow)
    if kind=='unrelated_change':copy_flow['updated']='metadata-only-change'
    elif kind=='run_identity':copy_flow['id']='55555555-5555-4555-8555-555555555555'
    elif kind=='timestamp':copy_flow['expected_start_time']=(m.stamp(flow['expected_start_time'])+dt.timedelta(hours=1)).isoformat()
    elif kind=='task_flow':tasks[1]['flow_run_id']='55555555-5555-4555-8555-555555555555'
    elif kind=='task_state':tasks[1]['state']['type']='FAILED'
    else:io.sources=lambda:(_ for _ in ()).throw(m.Stop('DEPLOYED_SOURCE_DRIFT'))
    io.flow=lambda identity:copy_flow
    r=m.validate_report(m.inspect(io,io.now))
    assert r['status']==('PASS' if kind=='unrelated_change' else 'FAILED')


def test_skipped_delivery_with_previous_active_bundle_is_partial(sample):
    m,io,*_=sample;io.status='SKIPPED_DUPLICATE';io.target='releases/'+'0'*64
    r=m.validate_report(m.inspect(io,io.now))
    assert r['status']=='PARTIAL' and r['delivery_status']=='SKIPPED_DUPLICATE'
    assert r['gaps']==['ACTIVE_PUBLICATION_DIFFERENT_RECEIPT'] and not io.calls
