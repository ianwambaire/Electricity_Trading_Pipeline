"""Synthetic receipts/markets only; no SSH, sudo, API request or production write."""
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_forecast_publication import publisher, fixture, encoded, storage, ISSUE, NOW
from test_inference_evidence import captured, builder
import shared.forecast_publication as contract
from shared.forecast_delivery import deliver, HELPER

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('automatic_receipt_delivery',ROOT/'deploy/staging/forecast-publication/automatic.py')
auto=importlib.util.module_from_spec(spec);spec.loader.exec_module(auto)
FLOW='22222222-2222-4222-8222-222222222222'


def test_automatic_publish_duplicate_older_and_newer(tmp_path):
    root=storage(tmp_path);raw,sha=encoded(fixture())
    assert publisher.publish_automatic(root,raw,sha,lambda:NOW)['status']=='PUBLISHED'
    assert publisher.publish_automatic(root,raw,sha,lambda:NOW)['status']=='SKIPPED_DUPLICATE'
    newer,digest=encoded(fixture(ISSUE+dt.timedelta(hours=1)))
    assert publisher.publish_automatic(root,newer,digest,lambda:NOW+dt.timedelta(hours=1))['status']=='PUBLISHED'
    assert publisher.publish_automatic(root,raw,sha,lambda:NOW+dt.timedelta(hours=1))['status']=='REJECTED_OLDER_ISSUE'
    same=fixture(ISSUE+dt.timedelta(hours=1));same['forecasts'][0]['predicted_price_eur_mwh']+=1
    data,key=encoded(same)
    assert publisher.publish_automatic(root,data,key,lambda:NOW+dt.timedelta(hours=1))['status']=='SKIPPED_DUPLICATE'
    assert publisher.pointer(root)==digest


def test_expiry_and_missing_root_never_activate(tmp_path):
    root=storage(tmp_path);raw,sha=encoded(fixture())
    assert publisher.publish_automatic(root,raw,sha,lambda:ISSUE+dt.timedelta(hours=4))['status']=='SKIPPED_EXPIRED'
    assert publisher.pointer(root) is None
    with pytest.raises(Exception):publisher.publish_automatic(tmp_path/'missing',raw,sha,lambda:NOW)
    assert not (tmp_path/'missing').exists()


def test_older_check_is_inside_lock_and_concurrent_writer_is_rejected(tmp_path):
    root=storage(tmp_path);raw,sha=encoded(fixture())
    with publisher.locked(root):
        with pytest.raises(BlockingIOError):publisher.publish_automatic(root,raw,sha,lambda:NOW)
    assert publisher.pointer(root) is None


def test_interrupted_pointer_reuses_verified_immutable_release(tmp_path,monkeypatch):
    root=storage(tmp_path);raw,sha=encoded(fixture());original=publisher.switch
    monkeypatch.setattr(publisher,'switch',lambda *a:(_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError):publisher.publish_automatic(root,raw,sha,lambda:NOW)
    before=(root/'releases'/sha/'bundle.json').read_bytes();assert publisher.pointer(root) is None
    monkeypatch.setattr(publisher,'switch',original)
    assert publisher.publish_automatic(root,raw,sha,lambda:NOW)['status']=='PUBLISHED'
    assert (root/'releases'/sha/'bundle.json').read_bytes()==before


@pytest.mark.parametrize('kind',['hash','missing','nan'])
def test_bad_output_never_replaces_current(tmp_path,kind):
    root=storage(tmp_path);bundle=fixture();raw,sha=encoded(bundle)
    if kind=='hash':sha='0'*64
    if kind=='missing':bundle['forecasts'].pop();raw,sha=encoded(bundle)
    if kind=='nan':bundle['forecasts'][0]['predicted_price_eur_mwh']=None;raw,sha=encoded(bundle)
    with pytest.raises(contract.Withheld):publisher.publish_automatic(root,raw,sha,lambda:NOW)
    assert publisher.pointer(root) is None


def fake_api(proof,now):
    e=proof['execution'];scheduled=auto.stamp(e['started_at']).replace(minute=45,second=0,microsecond=0)
    if scheduled>auto.stamp(e['started_at']):scheduled-=dt.timedelta(hours=1)
    def api(path,body=None):
        if path.startswith('/flow_runs/'):
            return {'id':FLOW,'deployment_id':auto.DEPLOYMENT,'auto_scheduled':True,'expected_start_time':scheduled.isoformat(),'start_time':e['started_at'],'state':{'type':'RUNNING'}}
        return [{'flow_run_id':FLOW,'name':'Generate next24h production forecast','state':{'type':'COMPLETED'},'start_time':e['started_at'],'end_time':e['completed_at']}]
    return api


def test_authentic_synthetic_receipt_is_built_and_bound_to_persistence(captured,tmp_path,monkeypatch):
    directory,forecast,matrix,paths,now=captured
    proof=json.loads((directory/'evidence.json').read_bytes());root=storage(tmp_path)
    monkeypatch.setattr(auto,'RECEIPTS',directory.parent);monkeypatch.setattr(auto,'HISTORY',tmp_path/'history.csv');monkeypatch.setattr(auto,'PUBLICATION',root)
    class Publisher:
        def publish_automatic(self,r,raw,sha):return publisher.publish_automatic(r,raw,sha,lambda:now.to_pydatetime())
    report=auto.deliver(directory.name,FLOW,contract,builder,Publisher(),owner=os.getuid(),api=fake_api(proof,now.to_pydatetime()),now=now.to_pydatetime())
    assert report['status']=='PUBLISHED'
    assert len(contract.read_active(root,now.to_pydatetime())['forecasts'])==24
    assert auto.deliver(directory.name,FLOW,contract,builder,Publisher(),owner=os.getuid(),api=fake_api(proof,now.to_pydatetime()),now=now.to_pydatetime())['status']=='SKIPPED_DUPLICATE'


@pytest.mark.parametrize('kind',['missing','hash','persistence','association','privilege'])
def test_receipt_failures_do_not_publish(captured,tmp_path,monkeypatch,kind):
    directory,forecast,matrix,paths,now=captured;proof=json.loads((directory/'evidence.json').read_bytes())
    monkeypatch.setattr(auto,'RECEIPTS',directory.parent);monkeypatch.setattr(auto,'HISTORY',tmp_path/'history.csv')
    p=SimpleNamespace(publish_automatic=lambda *a:pytest.fail('Rejected evidence was published'))
    api=fake_api(proof,now.to_pydatetime());owner=os.getuid()
    if kind=='missing':(directory/'model.json').unlink()
    if kind=='hash':(directory/'forecast.csv').write_bytes(b'tampered')
    if kind=='persistence':(tmp_path/'history.csv').write_text('forecast_issue_time,model_release\n')
    if kind=='association':api=lambda *a,**kw:{}
    if kind=='privilege':owner=99999
    with pytest.raises(Exception):auto.deliver(directory.name,FLOW,contract,builder,p,owner=owner,api=api,now=now.to_pydatetime())


def test_worker_disabled_withheld_and_failures_are_separate():
    result={'status':'GENERATED','generated':True,'inference_receipt_id':'11111111-1111-4111-8111-111111111111'}
    never=lambda *a:pytest.fail('Helper called')
    assert deliver(result,FLOW,runner=never)=={'status':'DISABLED'}
    for invalid in ({'status':'WITHHELD'},dict(result,inference_receipt_id='../bad'),dict(result,generated=False)):
        assert deliver(invalid,FLOW,enabled=True,runner=never)['status']=='REJECTED_INFERENCE'
    before=dict(result)
    assert deliver(result,FLOW,enabled=True,runner=lambda *a:(_ for _ in ()).throw(PermissionError('PRIVATE')))['status']=='FAILED'
    assert result==before
    assert deliver(result,FLOW,enabled=True,runner=lambda *a:{'status':'PUBLISHED'})=={'status':'PUBLISHED'}
    assert HELPER=='/usr/local/sbin/powerflow-publish-next24'


def test_two_concurrent_publishers_cannot_regress_issue(tmp_path,monkeypatch):
    import threading
    root=storage(tmp_path);raw,sha=encoded(fixture())
    entered=threading.Event();release=threading.Event();errors=[];original=publisher.switch
    def pause(*args):
        entered.set();assert release.wait(5);return original(*args)
    monkeypatch.setattr(publisher,'switch',pause)
    def first():
        try:publisher.publish_automatic(root,raw,sha,lambda:NOW)
        except Exception as error:errors.append(error)
    thread=threading.Thread(target=first);thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(BlockingIOError):publisher.publish_automatic(root,raw,sha,lambda:NOW)
    finally:release.set();thread.join(5)
    assert not thread.is_alive() and not errors and publisher.pointer(root)==sha


def test_expiry_is_rechecked_immediately_before_switch(tmp_path):
    root=storage(tmp_path);raw,sha=encoded(fixture());times=iter([NOW,NOW,NOW,ISSUE+dt.timedelta(hours=4)])
    with pytest.raises(contract.ExpiredPublication):publisher.publish_automatic(root,raw,sha,lambda:next(times))
    assert publisher.pointer(root) is None


def test_receipt_expiry_skips_without_publishing(captured,tmp_path,monkeypatch):
    directory,_,_,_,now=captured;proof=json.loads((directory/'evidence.json').read_bytes())
    monkeypatch.setattr(auto,'RECEIPTS',directory.parent)
    p=SimpleNamespace(publish_automatic=lambda *a:pytest.fail('Expired receipt published'))
    later=(now+dt.timedelta(hours=4)).to_pydatetime()
    assert auto.deliver(directory.name,FLOW,contract,builder,p,owner=os.getuid(),api=fake_api(proof,later),now=later)=={'status':'SKIPPED_EXPIRED'}


def test_capture_rejects_symlinks_writable_sources_and_unbounded_files(tmp_path):
    directory=tmp_path/'private';directory.mkdir(mode=0o700);path=directory/'evidence.json';path.write_bytes(b'{}');path.chmod(0o600)
    assert auto.capture(directory,path.name,os.getuid())==b'{}'
    with pytest.raises(Exception):auto.capture(directory,path.name,os.getuid(),1)
    path.chmod(0o640)
    with pytest.raises(Exception):auto.capture(directory,path.name,os.getuid())
    path.chmod(0o600);link=tmp_path/'link';link.symlink_to(directory)
    with pytest.raises(OSError):auto.capture(link,path.name,os.getuid())


@pytest.mark.parametrize('kind',['manual','other_deployment','not_completed','future','ambiguous'])
def test_wrong_or_unfinished_prefect_association_is_rejected(captured,kind):
    directory,_,_,_,now=captured;proof=json.loads((directory/'evidence.json').read_bytes());base=fake_api(proof,now)
    def api(path,body=None):
        value=base(path,body)
        if isinstance(value,dict):
            if kind=='manual':value['auto_scheduled']=False
            if kind=='other_deployment':value['deployment_id']='wrong'
            if kind=='future':value['expected_start_time']=(now+dt.timedelta(hours=1)).isoformat()
        else:
            if kind=='not_completed':value[0]['state']['type']='RUNNING'
            if kind=='ambiguous':value*=2
        return value
    with pytest.raises(Exception):auto.association(FLOW,proof,now.to_pydatetime(),api)


@pytest.mark.parametrize('body,code',[('{"status":"PUBLISHED"}',0),('PRIVATE',0),('{"status":"PUBLISHED","secret":"PRIVATE"}',0),('{"status":"PUBLISHED"}',1),('x'*17000,0)])
def test_worker_uses_only_fixed_privileged_command_and_bounds_output(monkeypatch,body,code):
    import subprocess,sys
    import shared.forecast_delivery as worker
    original=subprocess.Popen;seen=[]
    def local(argv,**kwargs):
        seen.append((argv,kwargs))
        return original([sys.executable,'-I','-S','-B','-c','import sys;sys.stdout.write(sys.argv[1]);sys.exit(int(sys.argv[2]))',body,str(code)],**kwargs)
    monkeypatch.setattr(worker.subprocess,'Popen',local)
    if body=='{"status":"PUBLISHED"}' and code==0:assert worker.invoke(FLOW,FLOW)=={'status':'PUBLISHED'}
    else:
        with pytest.raises((ValueError,json.JSONDecodeError)):worker.invoke(FLOW,FLOW)
    argv,kwargs=seen[0]
    assert argv==['/usr/bin/sudo','-n',HELPER,'--receipt',FLOW,'--flow-run',FLOW]
    assert kwargs['env']=={'PATH':'/usr/bin:/bin'} and kwargs['stdin']==subprocess.DEVNULL and kwargs['start_new_session'] is True
    assert 'shell' not in kwargs


def test_inference_task_passes_explicit_receipt_uuid(captured,monkeypatch):
    import scheduled_pipeline as pipeline
    directory,forecast,_,_,_=captured
    monkeypatch.setattr(pipeline,'run_next24h_forecast',lambda:(forecast,True))
    result=pipeline.next24h_forecast_task.fn()
    assert result['inference_receipt_id']==directory.name and result['status']=='GENERATED'


@pytest.mark.parametrize('status',['PUBLISHED','FAILED','SKIPPED_EXPIRED'])
def test_pipeline_keeps_publication_outcome_separate_from_inference(monkeypatch,tmp_path,status):
    import scheduled_pipeline as pipeline
    monkeypatch.setenv('POWERFLOW_AUTO_PUBLICATION_ENABLED','true')
    monkeypatch.setattr(pipeline,'PROJECT_ROOT',tmp_path)
    monkeypatch.setattr(pipeline,'_timed_stage',lambda _id,_name,operation,*a:operation(*a))
    monkeypatch.setattr(pipeline,'verify_next24h_release_task',lambda:'frozen-release')
    result={'status':'GENERATED','generated':True,'changed':True,'issue_time':ISSUE,'inference_receipt_id':FLOW,'provenance':{'weather_source':'source','weather_acquired_at_utc':NOW.isoformat()}}
    monkeypatch.setattr(pipeline,'next24h_forecast_task',lambda:result)
    seen=[];incidents=[]
    monkeypatch.setattr(pipeline,'next24h_publication_task',lambda r:seen.append(r) or {'status':status})
    monkeypatch.setattr(pipeline,'next24h_monitoring_task',lambda:(0,0))
    monkeypatch.setattr(pipeline,'_sync_storage_group',lambda *a:None)
    monkeypatch.setattr(pipeline,'incident_is_active',lambda *a:False)
    monkeypatch.setattr(pipeline,'_record_incident',lambda *a:incidents.append(a))
    state={};pipeline._run_next24h_stages(None,state)
    assert seen==[result] and state['next24h_forecast_status']=='GENERATED' and state['next24h_forecast_generated'] is True
    assert state['next24h_publication_status']==status
    assert bool(incidents)==(status=='FAILED')


def test_expected_withholding_does_not_invoke_root_helper():
    assert deliver({'status':'WITHHELD','generated':False},FLOW,enabled=True,runner=lambda *a:pytest.fail('Withheld forecast published'))=={'status':'SKIPPED_WITHHELD'}


def test_worker_timeout_terminates_local_child_without_retry(monkeypatch):
    import subprocess,sys
    import shared.forecast_delivery as worker
    original=subprocess.Popen;children=[];ticks=iter([0,100])
    def local(*args,**kwargs):
        child=original([sys.executable,'-I','-S','-B','-c','import time;time.sleep(60)'],**kwargs);children.append(child);return child
    monkeypatch.setattr(worker.subprocess,'Popen',local)
    monkeypatch.setattr(worker.time,'monotonic',lambda:next(ticks))
    with pytest.raises(TimeoutError):worker.invoke(FLOW,FLOW)
    assert len(children)==1 and children[0].poll() is not None


@pytest.mark.parametrize('kind',['valid','hash_mismatch','unexpected_dependency'])
def test_root_tools_execute_only_retained_manifest_bound_code(monkeypatch,kind):
    import hashlib,stat,sys
    folder=ROOT/'deploy/staging/forecast-publication'
    source={n:(ROOT/'src'/n if n.startswith('shared/') else folder/n).read_bytes() for n in ['automatic.py','publish.py','prepare.py','shared/__init__.py','shared/forecast_publication.py']}
    meta={n:hashlib.sha256(raw).hexdigest() for n,raw in source.items()}
    if kind=='hash_mismatch':source['prepare.py']=b'raise RuntimeError("UNVERIFIED CODE EXECUTED")'
    if kind=='unexpected_dependency':meta['unexpected.py']='0'*64
    monkeypatch.setattr(auto,'capture',lambda _path,name,_owner:json.dumps(meta).encode() if name=='automation-manifest.json' else source['shared/'+name] if str(_path).endswith('/shared') else source[name])
    monkeypatch.setattr(Path,'lstat',lambda _path:SimpleNamespace(st_uid=0,st_mode=stat.S_IFDIR|0o700))
    for name in ['shared','shared.forecast_publication','verified_builder','verified_publisher']:
        # Register restoration before tools() replaces these module entries.
        monkeypatch.setitem(sys.modules,name,sys.modules.get(name))
    if kind!='valid':
        with pytest.raises(ValueError,match='publication_evidence_rejected'):auto.tools()
    else:
        result=auto.tools()
        raw,sha=encoded(fixture())
        assert result['contract'].validate(raw,sha,NOW)['model']['release']==contract.RELEASE
        assert result['builder'].validate is result['contract'].validate
        assert result['publisher'].validate is result['contract'].validate


def test_automation_source_manifest_and_installed_closure_are_exact():
    import hashlib
    meta=json.loads((ROOT/'deploy/staging/forecast-publication/AUTOMATION-SOURCE-MANIFEST.json').read_bytes())
    assert meta['version']==1 and meta['execution_authorized'] is False
    expected={'automatic.py','publish.py','prepare.py','shared/__init__.py','shared/forecast_publication.py'}
    assert set(meta['installed_tools'])==expected
    for name,digest in meta['installed_tools'].items():
        path=ROOT/'src'/name if name.startswith('shared/') else ROOT/'deploy/staging/forecast-publication'/name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    for name,record in meta['sources'].items():
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        raw=(ROOT/name).read_bytes()
        assert {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}==record
    assert hashlib.sha256((ROOT/'deploy/staging/forecast-publication/FIRST-SETUP-MANIFEST.json').read_bytes()).hexdigest()==meta['unchanged_first_setup_manifest_sha256']


def test_valid_delivery_resolves_only_its_prior_publication_incident(monkeypatch,tmp_path):
    import scheduled_pipeline as pipeline
    monkeypatch.setenv('POWERFLOW_AUTO_PUBLICATION_ENABLED','true')
    monkeypatch.setattr(pipeline,'PROJECT_ROOT',tmp_path)
    monkeypatch.setattr(pipeline,'_timed_stage',lambda _id,_name,operation,*a:operation(*a))
    monkeypatch.setattr(pipeline,'verify_next24h_release_task',lambda:'frozen-release')
    monkeypatch.setattr(pipeline,'next24h_forecast_task',lambda:{'status':'GENERATED','changed':True,'issue_time':ISSUE,'provenance':{'weather_source':'source','weather_acquired_at_utc':NOW.isoformat()}})
    monkeypatch.setattr(pipeline,'next24h_publication_task',lambda r:{'status':'PUBLISHED'})
    monkeypatch.setattr(pipeline,'next24h_monitoring_task',lambda:(0,0))
    monkeypatch.setattr(pipeline,'_sync_storage_group',lambda *a:None)
    monkeypatch.setattr(pipeline,'incident_is_active',lambda component,*a:component=='staging forecast publication')
    incidents=[];monkeypatch.setattr(pipeline,'_record_incident',lambda *a:incidents.append(a))
    state={};pipeline._run_next24h_stages(None,state)
    assert len(incidents)==1 and incidents[0][1:4]==('staging forecast publication','publication_failed','RESOLVED')
    assert state['next24h_forecast_status']=='GENERATED'
