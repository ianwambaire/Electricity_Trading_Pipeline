"""Read-only diagnostic gap reporting, without inference or provider requests."""
import runpy
from pathlib import Path
import datetime as D
M=runpy.run_path(str(Path(__file__).parents[1]/'deploy/staging/next24-review/inspect.py'))

def test_identifies_exact_missing_price_lag_and_load_window():
    issue=D.datetime(2026,10,29,4,tzinfo=D.timezone.utc)
    allhours={issue-D.timedelta(hours=i) for i in range(169)}
    hourly={'prices':allhours-{issue-D.timedelta(hours=168)},'load':allhours-{issue-D.timedelta(hours=7)},'generation':{issue}}
    result=M['missing_features'](issue,hourly)
    assert result['prices']['missing_lag_hours']==[(issue-D.timedelta(hours=168)).isoformat()]
    assert result['prices']['missing_rolling24_hours']==[]
    assert result['load']['missing_lag_hours']==[]
    assert result['load']['missing_rolling24_hours']==[(issue-D.timedelta(hours=7)).isoformat()]
    assert 'generation' not in result

def test_complete_history_reports_no_gaps():
    issue=D.datetime(2026,10,29,4,tzinfo=D.timezone.utc)
    hours={issue-D.timedelta(hours=i) for i in range(169)}
    assert M['missing_features'](issue,dict(prices=hours,load=hours,generation=hours))=={}

def test_nonfinite_values_are_not_accepted():
    for value in [None,'','NaN','inf','-inf','broken']:assert not M['finite'](value)
    assert M['finite']('0')


def test_actual_partial_load_pattern_remains_withheld_until_real_quarters_arrive(tmp_path):
    import pandas as pd
    import pytest
    from test_next24h_production import operational_inputs
    from models.next24h_production import assemble_operational_issue_features, ForecastUnavailableError
    paths,weather,last=operational_inputs(tmp_path)
    prices,load,generation=paths
    original=pd.read_csv(load)
    times=pd.to_datetime(original['timestamp'],utc=True)
    partial=original.loc[times < last+pd.Timedelta(minutes=30)]
    partial.to_csv(load,index=False)
    now=last+pd.Timedelta(hours=2,minutes=2)
    before=load.read_bytes()
    with pytest.raises(ForecastUnavailableError,match='load.*3-hour freshness threshold'):
        assemble_operational_issue_features(prices_path=prices,load_path=load,generation_path=generation,now=now,weather_session=weather)
    assert load.read_bytes()==before
    assert weather.params is None  # market gate precedes any weather request
    # Fixture-only legitimate missing quarters restored; no model inference.
    original.to_csv(load,index=False)
    issue,_=assemble_operational_issue_features(prices_path=prices,load_path=load,generation_path=generation,now=now,weather_session=weather)
    assert issue['forecast_issue_time'].iloc[0]==last
    assert len(issue)==1
