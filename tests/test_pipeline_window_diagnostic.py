"""Synthetic Prefect/proc/time only. No network or service operations."""
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import ast
import pytest

ROOT=Path(__file__).resolve().parents[1];DIR=ROOT/'deploy/staging/pipeline-window-diagnostic'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
D=load('pipeline_diagnostic',DIR/'inspect.py');R=load('pipeline_runner',DIR/'run.py')


def context(case='pass'):
    base={'__name__':'synthetic_guard'}
    exec(compile((ROOT/R.CORE).read_bytes(),'<retained-guard>','exec'),base)
    now=dt.datetime(2026,11,2,10,0,tzinfo=dt.timezone.utc)
    if case=='window':now=now.replace(minute=35)
    if case=='inside_window':now=now.replace(minute=34,second=59)
    if case=='boundary_before':now=now.replace(minute=35)-dt.timedelta(microseconds=1)
    if case=='boundary_after':now=now.replace(minute=35)+dt.timedelta(microseconds=1)
    class Clock(dt.datetime):
        @classmethod
        def now(cls,tz=None):return now
    base['datetime']=SimpleNamespace(datetime=Clock,timezone=dt.timezone,timedelta=dt.timedelta)
    deployment={'id':base['DEPLOYMENT'],'paused':False,'schedules':[{'active':True,'schedule':{'cron':'45 * * * *','timezone':'UTC','day_or':True}}],'global_concurrency_limit':{'limit':1,'active':True,'active_slots':0},'concurrency_options':None}
    if case=='schedule':deployment['schedules'][0]['schedule']['cron']='0 * * * *'
    if case=='concurrency':deployment['global_concurrency_limit']['limit']=2
    if case=='slots':deployment['global_concurrency_limit']['active_slots']=1
    active=[{'state_type':'RUNNING','private':'SECRET_SENTINEL'}] if case=='active' else []
    queued=[{'expected_start_time':(now+dt.timedelta(minutes=5 if case=='queued' else 45)).isoformat()}]
    calls=[]
    def api(path,body=None):
        calls.append((path,body))
        if path.startswith('/deployments/'):return deployment
        return queued if body['flow_runs']['state']['type']['any_']==['SCHEDULED'] else active
    base['api']=api
    entries=[Path('/synthetic/999999999')] if case=='process' else []
    base['Path']=lambda p:SimpleNamespace(iterdir=lambda:iter(entries))
    base['read']=lambda p,*a:b'36 1 0:1 / /proc rw - proc proc rw\n' if str(p).endswith('mountinfo') else b'scheduled_pipeline\x00'
    return base,calls


@pytest.mark.parametrize('case,reason',[
 ('pass',None),('inside_window',None),('boundary_before',None),('boundary_after','HOURLY_WINDOW_TOO_SHORT'),('window','HOURLY_WINDOW_TOO_SHORT'),('queued','QUEUED_RUN_TOO_CLOSE'),('schedule','SCHEDULE_OR_DEPLOYMENT_MISMATCH'),('concurrency','CONCURRENCY_OR_COLLISION_MISMATCH'),('slots','ACTIVE_CONCURRENCY_SLOTS_OR_UNKNOWN'),('active','ACTIVE_FLOW_RUNS'),('process','INGESTION_OR_ENGINE_PROCESSES')])
def test_exact_existing_guard_subconditions(case,reason):
    base,calls=context(case);api=base['api'];clock=base['datetime']
    result=D.validate_report(D.inspect(base))
    assert result['status']==('PASS' if reason is None else 'BLOCKED')
    assert result['failed_conditions']==([] if reason is None else [reason])
    assert result['minimum_window_microseconds']==600_000_000
    assert base['api'] is api and base['datetime'] is clock
    assert len(calls)==3 and all('set_state' not in path for path,body in calls)
    assert 'SECRET_SENTINEL' not in json.dumps(result)
    assert result['historical_apply_failure_cause']=='UNVERIFIED'


def test_missing_evidence_is_unverified_and_redacted():
    base,_=context();base['api']=lambda *a,**k:(_ for _ in ()).throw(PermissionError('SECRET_SENTINEL'))
    assert D.inspect(base)=={'status':'UNVERIFIED','cause':'EVIDENCE_COLLECTION_FAILED'}


@pytest.mark.parametrize('key,value',[('failed_conditions',[]),('status','PASS'),('minimum_window_microseconds',0),('evaluation_utc','SECRET_SENTINEL'),('historical_apply_failure_cause','CONFIRMED')])
def test_contradictory_or_private_output_rejected(key,value):
    base,_=context('active');result=D.inspect(base);result[key]=value
    with pytest.raises((ValueError,TypeError)):D.validate_report(result)


def test_manifest_closure_and_assembly():
    m=json.loads((DIR/'MANIFEST.json').read_bytes());assert set(m['artifacts'])==R.ARTIFACTS
    blobs={}
    for name,meta in m['artifacts'].items():
        raw=(ROOT/name).read_bytes();assert len(raw)==meta['bytes'] and hashlib.sha256(raw).hexdigest()==meta['sha256'];blobs[name]=raw
    assert hashlib.sha256(R.assemble(blobs)).hexdigest()==m['remote_payload_sha256']
    ast.parse(R.assemble(blobs).decode(),feature_version=(3,9))


def test_mismatch_stops_before_loading_executables(monkeypatch):
    monkeypatch.setattr(R,'namespace',lambda *a:pytest.fail('Unverified executable loaded'))
    with pytest.raises(ValueError):R.verify('0'*64)


def test_no_mutation_or_full_preflight_call():
    tree=ast.parse((DIR/'inspect.py').read_text(),feature_version=(3,9))
    for n in ast.walk(tree):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute):assert n.func.attr not in {'write_text','write_bytes','mkdir','unlink','chmod','chown','system','Popen','run'}
    text=(DIR/'inspect.py').read_text();assert "base['main']" not in text and "base['pipeline']()" in text
