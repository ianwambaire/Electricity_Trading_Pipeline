"""Actual writer serialization, synthetic data, no remote or publisher operations."""
import ast
import copy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import pandas as pd
import pytest
from shared import operational_evidence as contract
from shared import operational_evidence_producer as original
from shared import operational_capture as capture
from shared import forecast_publication as forecast
from models.inference_evidence import receipt
from test_current_operations import association,summary
from test_operational_terminal import stable,fixture_source,source_api,STATE,NOW
ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'deploy/staging/operational-capture-correction-v1/operational_evidence_producer.py'
spec=importlib.util.spec_from_file_location('shared.operational_candidate',PATH);candidate=importlib.util.module_from_spec(spec);spec.loader.exec_module(candidate)

def actual_writer_fixture(a):
 old=a['receipts'][0];proof=json.loads(old['evidence.json']);pr=json.loads(old['provenance.json']);pr.pop('inference_evidence')
 frame=pd.read_csv(io.BytesIO(old['forecast.csv']))
 for name in ['forecast_issue_time','target_timestamp']:frame[name]=pd.to_datetime(frame[name],utc=True)
 matrix=pd.DataFrame([proof['inference']['feature_values']],columns=proof['inference']['feature_names'])
 a['receipts']=[receipt(frame,pr,old['model.json'],matrix,proof['inputs'],proof['inference']['source_sha256'],proof['execution'])]
 summary(a,next24h_forecast_issue_time=str(frame['forecast_issue_time'].iloc[0]))
 return a

def test_real_writer_reproduces_failure_and_candidate_passes(association):
 a=actual_writer_fixture(association)
 persisted=json.loads(a['records'][0]['message'])['next24h_forecast_issue_time'];assert persisted[10]==' '
 assert next(csv.DictReader(io.StringIO(a['receipts'][0]['forecast.csv'].decode())))['forecast_issue_time'][10]==' '
 with pytest.raises(contract.InvalidEvidence,match='^TIMESTAMP$'):original.associate(**a)
 raw,digest=candidate.associate(**a);result=contract.validate(raw,digest,a['observed_at'])
 assert 'T'in result['inference']['issue_time'] and result['delivery']['outcome']=='PUBLISHED'

def test_bundle_hash_and_source_artifacts_unchanged(association,tmp_path):
 a=actual_writer_fixture(association);files=copy.deepcopy(a['receipts'][0])
 # Compare with the unchanged reviewed forecast bundle builder, not a second
 # implementation of its serialization.
 spec=importlib.util.spec_from_file_location('reviewed_builder',ROOT/'deploy/staging/forecast-publication/prepare.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
 names=['forecast.csv','provenance.json','model.json','evidence.json'];paths=[]
 for name in names:p=tmp_path/name;p.write_bytes(files[name]);p.chmod(0o600);paths.append(p)
 bundle,expected=builder.build(*paths,[hashlib.sha256(files[n]).hexdigest() for n in names],now=a['observed_at'])
 raw,digest=candidate.associate(**a);result=contract.validate(raw,digest,a['observed_at'])
 assert result['delivery']['bundle_sha256']==expected
 assert candidate.receipt_bundle(files,a['observed_at'])[1]==expected
 assert a['receipts'][0]==files and all(p.read_bytes()==files[n] for p,n in zip(paths,names))

def test_full_readonly_capture_with_candidate(stable,tmp_path,monkeypatch):
 a=actual_writer_fixture(stable);source,db=fixture_source(a,tmp_path,monkeypatch);api,_=source_api(a);before=db.read_bytes()
 monkeypatch.setattr(capture,'from_snapshot',candidate.from_snapshot)
 raw,digest=capture.capture_terminal(a['flow']['id'],STATE,source=source,api=api,clock=lambda:NOW)
 assert contract.validate(raw,digest,NOW)['inference']['outcome']=='GENERATED';assert db.read_bytes()==before

@pytest.mark.parametrize('value',['2026-01-05T08:00:00Z','2026-01-05 08:00:00Z','2026-01-05 08:00:00+00:00','2026-01-05T08:00:00+00:00'])
def test_supported_utc_spellings(value):assert candidate.persisted_issue_timestamp(value).isoformat()=='2026-01-05T08:00:00+00:00'
@pytest.mark.parametrize('value',[None,123,'2026-01-05 08:00:00','2026-01-05 08:00:00+01:00','2026-01-05 08:00:00-00:00','2026-01-05 08:00:00 UTC','2026-01-05  08:00:00Z','2026-02-30 08:00:00Z','2026-01-05 08:00:60Z','2026-01-05\t08:00:00Z','2026-01-05 08:00:00Z SECRET'])
def test_malformed_naive_non_utc_still_rejected(value):
 with pytest.raises(contract.InvalidEvidence,match='TIMESTAMP'):candidate.persisted_issue_timestamp(value)

def test_public_contract_remains_strict():
 with pytest.raises(contract.InvalidEvidence,match='TIMESTAMP'):contract.timestamp('2026-01-05 08:00:00+00:00')
@pytest.mark.parametrize('kind',['mismatch','hash','feature_order','identity'])
def test_existing_integrity_guards_survive(association,kind):
 a=actual_writer_fixture(association)
 if kind=='mismatch':summary(a,next24h_forecast_issue_time='2026-01-05 09:00:00+00:00')
 elif kind=='hash':a['receipts'][0]['forecast.csv']+=b'changed'
 elif kind=='feature_order':
  m=json.loads(a['receipts'][0]['model.json']);m['features'].reverse();a['receipts'][0]['model.json']=json.dumps(m).encode()
 else:a['tasks'][0]['flow_run_id']='99999999-9999-4999-8999-999999999999'
 with pytest.raises((contract.InvalidEvidence,forecast.Withheld)):candidate.associate(**a)

def test_python39_and_exact_original_preservation():
 ast.parse(PATH.read_text(),feature_version=(3,9))
 assert hashlib.sha256((ROOT/'src/shared/operational_evidence_producer.py').read_bytes()).hexdigest()=='c4969093ad6b8361c11d96b194c00098cb42f87ef78ebba5c0cdeed82dab582c'
 assert hashlib.sha256((ROOT/'deploy/staging/operational-evidence-release-v5/MANIFEST.json').read_bytes()).hexdigest()=='cdd828defc52ea258852b88aa852d1d470ca915d098021d6ff8fd2be9b05223b'

def test_expired_forecast_and_operational_freshness_are_not_extended(association):
 import datetime as dt
 a=actual_writer_fixture(association);a['observed_at']+=dt.timedelta(days=2)
 raw,digest=candidate.associate(**a)
 view=contract.view(raw,digest,now=a['observed_at']);assert view['status']=='STALE' and view['current_execution']is None
 assert contract.timestamp(view['fresh_until'])==contract.timestamp(a['flow']['expected_start_time'])+contract.MAX_AGE
 bundle,bundle_hash=candidate.receipt_bundle(a['receipts'][0],a['observed_at'])
 encoded=json.dumps(bundle,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
 with pytest.raises(forecast.ExpiredPublication):forecast.validate(encoded,bundle_hash,a['observed_at'])

def test_only_issue_boundary_changes():
 old=ast.parse((ROOT/'src/shared/operational_evidence_producer.py').read_text());new=ast.parse(PATH.read_text())
 old_functions={n.name:ast.dump(n,include_attributes=False) for n in old.body if isinstance(n,ast.FunctionDef)}
 new_functions={n.name:ast.dump(n,include_attributes=False) for n in new.body if isinstance(n,ast.FunctionDef)}
 assert set(new_functions)-set(old_functions)=={'persisted_issue_timestamp'}
 assert [n for n in old_functions if old_functions[n]!=new_functions[n]]==['_associate']
