"""Synthetic source/weather fixtures only; no production access or retraining."""
import importlib.util
import json
from pathlib import Path
import uuid

import numpy as np
import pandas as pd
import pytest

from models import next24h_production as production
from models.inference_evidence import canonical, digest, persist, snapshot
from models.next24h import create_next24h_forecast
from shared.forecast_publication import Withheld, validate
from test_next24h_production import operational_inputs

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('receipt_builder', ROOT/'deploy/staging/forecast-publication/prepare.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def captured(tmp_path, monkeypatch):
    paths, session, issue = operational_inputs(tmp_path)
    model, features, manifest = production.load_next24h_release()
    seen = []
    class RecordingModel:
        def predict(self, matrix):
            seen.append(matrix.copy(deep=True))
            return np.arange(24, dtype=float).reshape(1,24)
    monkeypatch.setattr(production, 'load_next24h_release', lambda _: (RecordingModel(),features,manifest))
    now = issue+pd.Timedelta(hours=1,minutes=30)
    root = tmp_path/'receipts'
    forecast, changed = production.run_next24h_forecast(
        prices_path=paths[0],load_path=paths[1],generation_path=paths[2],
        latest_path=tmp_path/'latest.csv',history_path=tmp_path/'history.csv',
        provenance_path=tmp_path/'provenance.json',evidence_root=root,now=now,weather_session=session)
    directory = next(p for p in root.iterdir() if not p.name.startswith('.'))
    return directory, forecast, seen[0], paths, now


def build(directory, now):
    files = [directory/n for n in ['forecast.csv','provenance.json','model.json','evidence.json']]
    return builder.build(*files,[digest(f.read_bytes()) for f in files],now)


def test_actual_matrix_receipt_is_accepted_by_publication(captured):
    directory, forecast, matrix, paths, now = captured
    proof = json.loads((directory/'evidence.json').read_bytes())
    assert proof['inference']['feature_names'] == list(matrix.columns)
    assert proof['inference']['feature_values'] == matrix.iloc[0].tolist()
    assert proof['inputs']['features'] == matrix.iloc[0].to_dict()
    assert set(json.loads((directory/'model.json').read_bytes())) == {'release_id','model_sha256','feature_contract_sha256','feature_count','features','horizons_hours'}
    assert forecast.attrs['inference_receipt_id'] == directory.name
    assert forecast['predicted_price_eur_mwh'].tolist() == list(range(24))
    assert proof['inference']['source_sha256'] == {k:digest(p.read_bytes()) for k,p in zip(['price','load','generation'],paths)}
    raw, sha = build(directory,now)
    assert len(validate(raw,sha,now)['forecasts']) == 24
    integrity = json.loads((directory/'integrity.json').read_bytes())
    assert integrity['run_id'] == directory.name == proof['execution']['run_id']
    for name, sha in integrity['sha256'].items():
        assert digest((directory/name).read_bytes()) == sha
        assert (directory/name).stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700
    # Legacy provenance is unchanged; archived provenance has the run/hash binding.
    assert 'inference_evidence' not in forecast.attrs['provenance']
    assert 'inference_evidence' in json.loads((directory/'provenance.json').read_bytes())


@pytest.mark.parametrize('kind',['order','value','run','source','missing','version','target','model','forecast','provenance','manifest'])
def test_cross_run_malformed_and_hash_mismatches_rejected(captured,kind):
    directory, forecast, matrix, paths, now = captured
    proof = json.loads((directory/'evidence.json').read_bytes())
    if kind=='order': proof['inference']['feature_names'].reverse()
    elif kind=='value': proof['inference']['feature_values'][0] += 1
    elif kind=='run': proof['execution']['run_id'] = str(uuid.uuid4())
    elif kind=='source': proof['inference']['source_sha256']['load'] = 'not-a-hash'
    elif kind=='missing': proof.pop('inputs')
    elif kind=='version': proof['version'] = 2
    elif kind=='target': proof['inference']['target_times'].pop()
    elif kind=='model': proof['inference']['model']['model_sha256'] = '0'*64
    elif kind=='forecast':
        data = (directory/'forecast.csv').read_text().replace(',0.0,',',99.0,')
        (directory/'forecast.csv').write_text(data)
    elif kind=='provenance': (directory/'provenance.json').write_bytes(b'{}')
    elif kind=='manifest': (directory/'model.json').write_bytes(b'{}')
    (directory/'evidence.json').write_bytes(canonical(proof))
    with pytest.raises((Withheld,KeyError,ValueError)):
        build(directory,now)


def test_stale_evidence_and_partial_receipts_rejected(captured,tmp_path):
    directory, _, _, _, now = captured
    with pytest.raises(Withheld): build(directory,now+pd.Timedelta(hours=3))
    partial = tmp_path/'.partial-test';partial.mkdir();(partial/'evidence.json').write_bytes((directory/'evidence.json').read_bytes())
    with pytest.raises(FileNotFoundError): build(partial,now)


def test_commit_failure_never_exposes_completed_receipt(tmp_path,monkeypatch):
    root = tmp_path/'receipts';run_id = str(uuid.uuid4())
    monkeypatch.setattr('models.inference_evidence.os.fsync',lambda _: (_ for _ in ()).throw(OSError('injected')))
    with pytest.raises(OSError): persist(root, {'forecast.csv':b'test'}, run_id)
    assert not (root/run_id).exists()
    assert list(root.glob('.partial-*'))


def test_duplicate_commit_never_overwrites(tmp_path):
    root=tmp_path/'receipts';run_id=str(uuid.uuid4())
    persist(root,{'test':b'one'},run_id)
    with pytest.raises(FileExistsError):persist(root,{'test':b'two'},run_id)
    assert (root/run_id/'test').read_bytes()==b'one'


def test_capture_sees_ordered_input_before_predict_mutation():
    from models.final_evaluation import FINAL_FEATURES
    row = pd.DataFrame([{**dict.fromkeys(reversed(FINAL_FEATURES),1.0),'forecast_issue_time':pd.Timestamp('2026-01-01T00:00Z')}])
    captured=[]
    class MutatingModel:
        def predict(self,matrix):
            assert list(matrix.columns)==list(FINAL_FEATURES)
            matrix.iloc[0,0]=999
            return np.zeros((1,24))
    create_next24h_forecast(row,MutatingModel(),model_release='test',capture_input=captured.append)
    assert captured[0].iloc[0,0]==1


def test_source_read_drift_is_rejected(tmp_path,monkeypatch):
    path=tmp_path/'source';path.write_bytes(b'original')
    original=Path.read_bytes
    def changing(p):
        raw=original(p)
        if p==path:p.write_bytes(b'replacement')
        return raw
    monkeypatch.setattr(Path,'read_bytes',changing)
    with pytest.raises(ValueError,match='changed during read'):snapshot(path)
