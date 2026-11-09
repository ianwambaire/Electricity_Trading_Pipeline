"""Local Git-backed predecessor comparison. No host access or baseline changes."""
import ast
import copy
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import types

import numpy as np
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[1]
RELEASE=ROOT/'deploy/staging/realized-performance-release-v1'
PATH='src/models/next24h_monitoring.py'
INSTALLED_COMMIT='436d7364fa07dae8d01d60bddfc78ef9d12022cd'
EXPECTED_COMMIT='221693a96525afa4b96a2289297aa84cb00c6418'
INSTALLED_SHA='fb9fc1004c79e7888a9b762bfae73cdeec7038c025718dffb5cd21dfa8397bfd'
EXPECTED_SHA='077e2ccfb388be623b01a655071d75f6de87aa093a71a27e52a4ceafd42ffe0a'


def git_source(commit,path):
    return subprocess.run(['git','show',commit+':'+path],cwd=ROOT,capture_output=True,check=True,timeout=5).stdout


@pytest.fixture(scope='module')
def revisions():
    old=git_source(INSTALLED_COMMIT,PATH);expected=git_source(EXPECTED_COMMIT,PATH)
    assert hashlib.sha256(old).hexdigest()==INSTALLED_SHA
    assert hashlib.sha256(expected).hexdigest()==EXPECTED_SHA
    return old,expected,git_source(EXPECTED_COMMIT,'src/shared/forecast_evaluation.py')


def functions(raw):
    return {n.name:n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)}


def pure_module(raw,shared=None):
    # Execute exact committed pure function/constant nodes. Do not import the
    # historical model implementation, execute ingestion or load a model.
    m=types.ModuleType('committed_monitoring_fixture');m.__dict__.update(np=np,pd=pd,Path=Path,HISTORY_PATH=Path('/offline-unused/history.csv'))
    if shared is not None:m.__dict__.update(pure_module(shared).__dict__)
    tree=ast.parse(raw);tree.body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.Assign))]
    exec(compile(tree,'<verified-committed-monitoring>','exec'),m.__dict__)
    return m


def test_expected_baseline_is_independently_reproducible(revisions):
    _,expected,_=revisions;m=json.loads((RELEASE/'MANIFEST.json').read_bytes())
    assert hashlib.sha256((RELEASE/'MANIFEST.json').read_bytes()).hexdigest()=='a3dceba7641ceaa9030709b1b7d4ce59460b54f5123b7e89f15d95bba39b0a83'
    assert (RELEASE/'baseline/next24h_monitoring.py').read_bytes()==expected
    assert m['config']['worker_before'][PATH]==EXPECTED_SHA
    # Establish source ancestry, not deployment authorization.
    assert subprocess.run(['git','merge-base','--is-ancestor',INSTALLED_COMMIT,EXPECTED_COMMIT],cwd=ROOT,capture_output=True,timeout=5).returncode==0


@pytest.mark.parametrize('name',['load_observed_prices','match_realized_forecasts','performance_metrics','update_next24h_monitoring'])
def test_runtime_functions_are_identical_across_commits(revisions,name):
    old,expected,_=revisions
    assert ast.dump(functions(old)[name],include_attributes=False)==ast.dump(functions(expected)[name],include_attributes=False)


def test_only_summary_and_constants_were_relocated(revisions):
    old,expected,shared=revisions
    assert set(functions(old))-set(functions(expected))=={'summarize_realized_performance'}
    assert ast.dump(functions(old)['summarize_realized_performance'],include_attributes=False)==ast.dump(functions(shared)['summarize_realized_performance'],include_attributes=False)
    a=pure_module(old);b=pure_module(expected,shared)
    for name in ['MONITORING_MIN_PAIRS','HORIZON_MIN_PAIRS','REALIZED_COLUMNS','PERFORMANCE_COLUMNS','RAW_PRICE_PATH','REALIZED_PATH','PERFORMANCE_PATH']:
        assert getattr(a,name)==getattr(b,name)


def inputs():
    issue=pd.Timestamp('2026-01-01T00:00:00Z')
    history=pd.DataFrame([dict(forecast_issue_time=issue,target_timestamp=issue+pd.Timedelta(hours=h),issued_at_utc=issue+pd.Timedelta(minutes=5),horizon_hours=h,predicted_price_eur_mwh=float(h-10),model_release='synthetic-test')for h in range(1,25)])
    prices=pd.DataFrame({'target_timestamp':history.target_timestamp,'price_eur_mwh':history.predicted_price_eur_mwh-2.0})
    return history,prices


@pytest.mark.parametrize('kind',['normal','late_issue','missing_issuance','empty','duplicate_actual'])
def test_actual_matching_parity_and_safe_exclusions(revisions,kind):
    old,expected,shared=revisions;a=pure_module(old);b=pure_module(expected,shared);history,prices=inputs()
    if kind=='late_issue':history['issued_at_utc']=history.target_timestamp
    elif kind=='missing_issuance':history=history.drop(columns='issued_at_utc')
    elif kind=='empty':history=history.iloc[:0]
    elif kind=='duplicate_actual':prices=pd.concat([prices,prices.iloc[:1]])
    if kind=='duplicate_actual':
        for m in [a,b]:
            with pytest.raises(ValueError,match='unique'):m.match_realized_forecasts(history,prices)
        return
    first=a.match_realized_forecasts(history,prices);second=b.match_realized_forecasts(history,prices)
    pd.testing.assert_frame_equal(first,second)
    assert len(first)==(24 if kind=='normal'else 0)
    if kind=='normal':assert (first.absolute_error==2).all()and(first.squared_error==4).all()and(first.signed_error==2).all()


@pytest.mark.parametrize('count',[0,4,5,19,20,24])
def test_metrics_and_summary_threshold_parity(revisions,count):
    old,expected,shared=revisions;a=pure_module(old);b=pure_module(expected,shared);history,prices=inputs()
    pairs=a.match_realized_forecasts(history,prices).iloc[:count]
    x=a.performance_metrics(pairs);y=b.performance_metrics(pairs);pd.testing.assert_frame_equal(x,y)
    if count>=5:
        overall=x.loc[x.scope=='overall'].iloc[0];assert overall.mae==overall.rmse==overall.bias==2
    else:assert x.empty
    now=pd.Timestamp('2026-01-03T00:00:00Z')
    first=a.summarize_realized_performance(pairs,now=now);second=b.summarize_realized_performance(pairs,now=now)
    for key in ['overall','windows','target_dates']:assert first[key]==second[key]
    pd.testing.assert_frame_equal(first['horizons'],second['horizons'])
    assert first['overall']['status']==('Available'if count>=20 else'Insufficient data')


def test_both_predecessors_need_the_planned_reporting_upgrade(revisions):
    from models.next24h_monitoring import match_realized_forecasts as candidate
    old,expected,shared=revisions
    for m in [pure_module(old),pure_module(expected,shared)]:
        assert 'now'not in inspect.signature(m.match_realized_forecasts).parameters
    assert 'now'in inspect.signature(candidate).parameters
    history,prices=inputs()
    # Candidate deliberately waits for the complete target hour, unlike both
    # historical predecessors. Keep this safeguard; do not deploy producer alone.
    pairs=candidate(history,prices,now=pd.Timestamp('2026-01-01T03:30:00Z'))
    assert list(pairs.horizon_hours)==[1,2]


def test_strict_preflight_accepts_only_explicitly_selected_predecessor(tmp_path):
    c=copy.deepcopy(json.loads((RELEASE/'MANIFEST.json').read_bytes())['config']);c['worker_before']={PATH:EXPECTED_SHA};c['worker_dependencies']={}
    worker=tmp_path/'worker';file=worker/PATH;file.parent.mkdir(parents=True);file.write_bytes(b'fixture: hash supplied by mock')
    def need(ok,reason):
        if not ok:raise ValueError(reason)
    observed={'sha256':INSTALLED_SHA,'bytes':8434}
    p=types.SimpleNamespace(PRODUCTION=worker,ENV=tmp_path/'env',safe=lambda *a:None,snap=lambda *a:(dict(observed),b''))
    d={'__name__':'offline_guard','C':c,'P':p,'need':need};exec((RELEASE/'guards.py').read_bytes(),d)
    with pytest.raises(ValueError,match='WORKER_BASELINE_DRIFT_NEXT24H_MONITORING'):d['worker_state']()
    # Offline proposal only: never write this into V1 or accept observed hashes.
    # Independently committed source identity was verified by revisions fixture.
    c['worker_before'][PATH]=INSTALLED_SHA
    assert d['worker_state']()[PATH]['sha256']==INSTALLED_SHA
    observed['sha256']='0'*64
    with pytest.raises(ValueError,match='WORKER_BASELINE_DRIFT_NEXT24H_MONITORING'):d['worker_state']()
    assert json.loads((RELEASE/'MANIFEST.json').read_bytes())['config']['worker_before'][PATH]==EXPECTED_SHA
