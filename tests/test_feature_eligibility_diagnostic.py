"""Synthetic price/load CSVs only. Native-helper parity; no network or inference."""
import ast,datetime as dt,hashlib,importlib.util,io,json
from pathlib import Path
import pytest
import pandas as pd
from models.next24h_production import _historical_market_features
from processing.build_silver_dataset import clean_prices,clean_load
ROOT=Path(__file__).parents[1];FOLDER=ROOT/'deploy/staging/forecast-publication/feature-eligibility-diagnostic'
def load(name):
    s=importlib.util.spec_from_file_location('featurediag_'+name,FOLDER/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
@pytest.fixture
def sample():
    m=load('inspect');r=load('run');reader=r.namespace(r.reader_source((ROOT/r.PREFECT_SOURCE).read_bytes()),'reader');m.R=reader
    return m

def data(m,source):
    hours=set().union(*(set(m.hours(m.time(i),source)) for i in m.ISSUES));rows=[]
    field='price_eur_mwh' if source=='price' else 'load_mw'
    for h in sorted(hours):
        for q in range(4):rows.append({'timestamp':(h+dt.timedelta(minutes=15*q)).isoformat(),field:100.0 if source=='price' else 40000.0,**({'source_resolution':'PT15M'} if source=='price' else {})})
    return pd.DataFrame(rows)

def encoded(frame):return frame.to_csv(index=False).encode()

@pytest.mark.parametrize('source',['price','load'])
@pytest.mark.parametrize('kind',['complete','current14','current15','lag24','rolling','lag168','null','duplicate','offgrid','inf'])
def test_exact_hour_and_history_parity(sample,source,kind):
    m=sample;frame=data(m,source);issue=m.time(m.ISSUES[0]);field='price_eur_mwh' if source=='price' else 'load_mw'
    if kind!='complete':
        hour=issue if kind in {'current14','null','duplicate','offgrid','inf'} else issue+dt.timedelta(hours=1) if kind=='current15' else issue-dt.timedelta(hours=24) if kind=='lag24' else issue-dt.timedelta(hours=168) if kind=='lag168' and source=='price' else issue-dt.timedelta(hours=6)
        indices=frame.index[pd.to_datetime(frame.timestamp,utc=True)==hour]
        assert len(indices)==1;idx=indices[0]
        if kind=='null':frame.loc[idx,field]=float('nan')
        elif kind=='inf':frame.loc[idx,field]=float('inf')
        elif kind=='duplicate':frame=pd.concat([frame,frame.loc[[idx]]],ignore_index=True)
        elif kind=='offgrid':frame.loc[idx,'timestamp']=(hour+dt.timedelta(minutes=1)).isoformat()
        else:frame=frame.drop(idx)
    raw=encoded(frame);report=m.analyze(raw,source,'2026-11-03T16:47:04.080982+00:00')
    try:
        clean=(clean_prices if source=='price' else clean_load)(io.BytesIO(raw));native=_historical_market_features(clean,source)
        expected=[pd.Timestamp(i)in native.index for i in m.ISSUES]
    except ValueError:expected=[False,False]
    assert [r['current_snapshot_eligible_at_recorded_clock'] for r in report['candidates']]==expected
    assert all(r['fresh_at_withholding_clock'] and r['hour_finished_at_withholding'] for r in report['candidates'])
    assert '40000' not in json.dumps(report) and '100.0' not in json.dumps(report)


def test_load_required_hours_and_quarter_counts(sample):
    m=sample
    for text in m.ISSUES:
        issue=m.time(text);required=m.hours(issue,'load');assert len(required)==25 and required[0]==issue-dt.timedelta(hours=24) and required[-1]==issue
        assert len(required)*4==100
    raw=encoded(data(m,'load'));out=m.analyze(raw,'load','2026-11-03T18:00:01+00:00')
    assert not any(r['fresh_at_withholding_clock'] for r in out['candidates'])


def test_missing_exact_quarter_provenance(sample):
    m=sample;frame=data(m,'load');missing='2026-11-03T14:15:00+00:00';frame=frame.loc[frame.timestamp!=missing]
    report=m.analyze(encoded(frame),'load','2026-11-03T16:47:04+00:00')
    assert report['candidates'][0]['defects'][0]['missing']==[missing]
    assert report['candidates'][0]['failed_prerequisites']==['CURRENT_HOUR','LAG_OR_ROLLING_HISTORY']


def test_full_comparison_cannot_claim_historical_reconstruction(sample):
    m=sample;raw={s:encoded(data(m,s)) for s in ['price','load']}
    historical={'status':'PASS','internal_run_uuid':'025ef1c9a1da4867a05aecb718028afa','failed_prerequisite':{'gate':'JOINT_PRICE_LOAD_HOUR'},'withheld_at':'2026-11-03T16:47:04+00:00','latest_complete_hours':{'price':m.ISSUES[1],'load':m.ISSUES[0]}}
    m.W={'inspect':lambda:historical,'validate_report':lambda x:x};m.SOURCE_HASHES={}
    m.READ={'capture':lambda parent,name,*a:raw['price' if name=='prices.csv' else 'load']}
    out=m.validate_report(m.inspect());assert out['status']=='PASS' and out['historical_state']=='NOT_RECONSTRUCTIBLE_FROM_CURRENT_CSV'
    assert out['joint_candidates'][1]['recorded_watermark_hour_availability']['load']=='NOT_COMPLETE_AT_WITHHOLDING'
    assert out['joint_candidates'][1]['current_snapshot_joint_eligible_at_recorded_clock']is True
    assert 'UPSTREAM_VS_INGESTION_CAUSE_UNVERIFIED'in out['gaps']
    out['current_sources']['load']['candidates'][0]['defects']=[{'secret':'TOKEN'}]
    with pytest.raises(Exception):m.validate_report(out)


def test_capture_failures_and_source_drift_are_redacted(sample):
    m=sample;m.W={'inspect':lambda:{'status':'PARTIAL'},'validate_report':lambda x:x}
    out=m.validate_report(m.inspect());assert out['gaps']==['TARGET_WITHHOLDING_BINDING']
    m.W['inspect']=lambda:(_ for _ in ()).throw(OSError('TOKEN /private/secret'))
    assert 'TOKEN' not in json.dumps(m.inspect())


def test_dependency_payload_and_readonly_boundary(monkeypatch):
    r=load('run');raw=(FOLDER/'MANIFEST.json').read_bytes();manifest=json.loads(raw);real=r.namespace
    monkeypatch.setattr(r,'namespace',lambda raw,name,file=None:{'profile':lambda:{}} if name=='wrapper' else real(raw,name,file))
    payload,_,_,_=r.verify(hashlib.sha256(raw).hexdigest());assert hashlib.sha256(payload).hexdigest()==manifest['payload_sha256']
    assert b'publish_automatic' not in payload and b'assemble_operational_issue_features' not in payload
    for name in ['inspect.py']:
        tree=ast.parse((FOLDER/name).read_bytes())
        assert not any(isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr in {'write','mkdir','unlink','chmod','chown','publish','rollback'} for n in ast.walk(tree))
