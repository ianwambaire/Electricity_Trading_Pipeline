"""Synthetic offline fixtures only: no source acquisition, forecasts or promotion."""
import numpy as np
import pandas as pd
import pytest

from models.next24h import HORIZONS, ISSUE_TIME
from models.next24h_exogenous_evaluation import (
    ENTSOE_PREFIXES, SOURCE_PREFIXES, OBSERVED_AVAILABLE,
    evaluate_future_known_horizons, purged_chronological_splits,
    validate_actual_issuance_rows,
)
from processing.build_next24h_exogenous_silver import EXOGENOUS_FEATURE_COLUMNS, TARGET_COLUMN


@pytest.fixture
def evidence():
    issues = pd.to_datetime(['2026-01-02','2026-01-05','2026-01-31T23:00:00',
                            '2026-02-02','2026-02-05','2026-02-28T23:00:00',
                            '2026-03-02','2026-03-05'], format='mixed', utc=True)
    rows=[]
    for issue in issues:
        for horizon in HORIZONS:
            target=issue+pd.Timedelta(hours=horizon)
            row=dict.fromkeys(EXOGENOUS_FEATURE_COLUMNS, 10.0)
            row.update({ISSUE_TIME:issue,'target_timestamp':target,'horizon_hours':horizon,
                        'issue_observed_timestamp':issue-pd.Timedelta(hours=2),
                        OBSERVED_AVAILABLE:issue-pd.Timedelta(minutes=30),
                        TARGET_COLUMN:float(horizon-12),
                        'target_hour':target.hour,'target_day_of_week':target.dayofweek,
                        'target_month':target.month,'target_is_weekend':int(target.dayofweek>=5)})
            for prefix in SOURCE_PREFIXES:
                row[f'{prefix}_collection_issue_time']=issue-pd.Timedelta(hours=1)
                row[f'{prefix}_acquired_at_utc']=issue-pd.Timedelta(minutes=20)
            for prefix in ENTSOE_PREFIXES:
                row[f'{prefix}_source_created_at_utc']=issue-pd.Timedelta(hours=2)
            rows.append(row)
    return pd.DataFrame(rows)


def split(frame):
    return purged_chronological_splits(frame,validation_start='2026-02-01T00:00Z',test_start='2026-03-01T00:00Z')


def test_strict_evidence_and_full_horizon_purge(evidence):
    before=evidence.copy(deep=True)
    validated=validate_actual_issuance_rows(evidence)
    assert len(validated)==len(evidence)
    partitions=split(evidence)
    assert all(rows[ISSUE_TIME].nunique()==2 for rows in partitions.values())
    assert all(len(rows)==48 for rows in partitions.values())
    assert partitions['train']['target_timestamp'].max()<partitions['validation'][ISSUE_TIME].min()
    assert partitions['validation']['target_timestamp'].max()<partitions['test'][ISSUE_TIME].min()
    # Original caller data is not mutated.
    pd.testing.assert_frame_equal(evidence,before)


@pytest.mark.parametrize('column,value',[
    ('load_forecast_acquired_at_utc','2026-01-02T00:05Z'),
    ('weather_forecast_acquired_at_utc','2026-01-02T00:05Z'),
    ('load_forecast_source_created_at_utc','2026-01-02T00:00Z'),
    ('issue_observed_timestamp','2026-01-02T00:00Z'),
    (OBSERVED_AVAILABLE,'2026-01-02T00:01Z'),
    (ISSUE_TIME,'2026-01-02T00:00'),
    ('target_hour',99),
    ('forecast_load_mw',float('inf')),
])
def test_future_unavailable_invalid_or_unzoned_inputs_fail(evidence,column,value):
    evidence[column]=evidence[column].astype(object)
    evidence.loc[0,column]=value
    with pytest.raises(ValueError): validate_actual_issuance_rows(evidence)


def test_partial_duplicate_and_missing_actual_availability_refused(evidence):
    for bad in (evidence.iloc[1:],pd.concat([evidence,evidence.iloc[[0]]]),evidence.drop(columns=[OBSERVED_AVAILABLE]),
                evidence.drop(columns=[ISSUE_TIME])):
        with pytest.raises(ValueError): validate_actual_issuance_rows(bad)


def test_consistent_issue_snapshot_and_split_readiness(evidence):
    evidence.loc[0,'load_mw']=999
    with pytest.raises(ValueError,match='consistent'): validate_actual_issuance_rows(evidence)
    with pytest.raises(ValueError): split(evidence.iloc[:24])


class OfflineMean:
    def __init__(self,horizon,record): self.horizon=horizon;self.record=record
    def fit(self,x,y):
        assert TARGET_COLUMN not in x.columns
        assert list(x.columns)==list(EXOGENOUS_FEATURE_COLUMNS)
        self.record.append((self.horizon,x.copy(),y.copy()))
        self.mean=float(y.mean());return self
    def predict(self,x): return np.full(len(x),self.mean)


def evaluate(frame,record):
    return evaluate_future_known_horizons(frame,lambda h:OfflineMean(h,record),
        validation_start='2026-02-01T00:00Z',test_start='2026-03-01T00:00Z')


def test_24_independent_train_only_models_and_test_not_used_for_fit(evidence):
    first=[]; metrics,report=evaluate(evidence,first)
    changed=evidence.copy()
    changed.loc[changed[ISSUE_TIME]>=pd.Timestamp('2026-03-01T00:00Z'),TARGET_COLUMN]+=100
    second=[]; altered,_=evaluate(changed,second)
    assert len(first)==24 and len(metrics)==144
    assert report['production_promoted'] is False
    assert report['operational_predictions_validated'] is False
    assert report['split_issue_counts']==dict(train=2,validation=2,test=2)
    for (_,x,y),(_,other_x,other_y) in zip(first,second):
        assert len(x)==2
        pd.testing.assert_frame_equal(x,other_x)
        pd.testing.assert_series_equal(y,other_y)
    pd.testing.assert_frame_equal(metrics.query("split=='validation'"),altered.query("split=='validation'"))
    assert (altered.query("split=='test' and model_name=='Candidate'")['mae']==100).all()


def test_shared_estimator_and_invalid_predictions_refused(evidence):
    shared=OfflineMean(1,[])
    with pytest.raises(ValueError,match='independent'):
        evaluate_future_known_horizons(evidence,lambda _:shared,validation_start='2026-02-01T00:00Z',test_start='2026-03-01T00:00Z')
    class Bad(OfflineMean):
        def predict(self,x):return np.full(len(x),np.nan)
    with pytest.raises(ValueError,match='finite'):
        evaluate_future_known_horizons(evidence,lambda h:Bad(h,[]),validation_start='2026-02-01T00:00Z',test_start='2026-03-01T00:00Z')


def test_weekly_naive_uses_exact_asof_revisions_and_reports_matched_coverage(evidence):
    history=[]
    for _,row in evidence.iterrows():
        timestamp=row['target_timestamp']-pd.Timedelta(hours=168)
        history.append({'timestamp':timestamp,'available_at_utc':timestamp+pd.Timedelta(hours=1),
                        'price_eur_mwh':row[TARGET_COLUMN]})
        # A late revision must not affect the baseline for an earlier issue.
        history.append({'timestamp':timestamp,'available_at_utc':row[ISSUE_TIME]+pd.Timedelta(minutes=1),
                        'price_eur_mwh':100000.0})
    history=pd.DataFrame(history).drop_duplicates(['timestamp','available_at_utc'])
    metrics,report=evaluate_future_known_horizons(evidence,lambda h:OfflineMean(h,[]),
        validation_start='2026-02-01T00:00Z',test_start='2026-03-01T00:00Z',
        observed_price_history=history)
    weekly=metrics.query("model_name=='Weekly seasonal naive'")
    assert report['weekly_baseline_history_supplied'] is True
    assert weekly['observations'].eq(2).all()
    assert weekly['mae'].eq(0).all()
    assert weekly['candidate_mae_on_same_pairs'].eq(0).all()
    assert metrics.query("model_name=='Persistence'")['observations'].eq(2).all()

    # No nearest-hour fallback and no partial-pair comparison pretending complete.
    remove=(history['timestamp']==pd.Timestamp('2026-02-23T01:00Z'))
    partial,_=evaluate_future_known_horizons(evidence,lambda h:OfflineMean(h,[]),
        validation_start='2026-02-01T00:00Z',test_start='2026-03-01T00:00Z',
        observed_price_history=history.loc[~remove])
    row=partial.query("model_name=='Weekly seasonal naive' and split=='test' and horizon_hours==1").iloc[0]
    assert row['observations']==1 and row['eligible_issue_count']==2
    assert row['status']=='Insufficient available evidence' and pd.isna(row['mae'])


def test_baseline_history_availability_is_required(evidence):
    bad=pd.DataFrame({'timestamp':['2026-01-01T00:00Z'],'price_eur_mwh':[1.]})
    with pytest.raises(ValueError,match='availability'):
        evaluate_future_known_horizons(evidence,lambda h:OfflineMean(h,[]),
            validation_start='2026-02-01T00:00Z',test_start='2026-03-01T00:00Z',
            observed_price_history=bad)
    metrics,_=evaluate(evidence,[])
    absent=metrics.query("model_name=='Weekly seasonal naive'")
    assert absent['observations'].eq(0).all() and absent['mae'].isna().all()


@pytest.mark.parametrize('start',['2026-03-29T00:00Z','2026-10-25T00:00Z'])
def test_all_24_utc_horizons_remain_exact_across_dst(evidence,start):
    original=evidence.loc[evidence[ISSUE_TIME]==evidence[ISSUE_TIME].iloc[0]].copy()
    delta=pd.Timestamp(start)-original[ISSUE_TIME].iloc[0]
    time_columns=[name for name in original if name.endswith('_utc') or name.endswith('_time')
                  or name in ('target_timestamp','issue_observed_timestamp')]
    for name in time_columns:
        original[name]=pd.to_datetime(original[name],utc=True)+delta
    target=original['target_timestamp']
    original['target_hour']=target.dt.hour
    original['target_day_of_week']=target.dt.dayofweek
    original['target_month']=target.dt.month
    original['target_is_weekend']=target.dt.dayofweek.ge(5).astype(int)
    validated=validate_actual_issuance_rows(original)
    assert (validated['target_timestamp']-validated[ISSUE_TIME]).dt.total_seconds().tolist()==[h*3600 for h in HORIZONS]
    assert validated['target_timestamp'].diff().iloc[1:].eq(pd.Timedelta(hours=1)).all()
