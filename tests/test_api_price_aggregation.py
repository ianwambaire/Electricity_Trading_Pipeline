"""Standalone API aggregation must preserve pipeline completeness semantics."""
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from processing.build_silver_dataset import aggregate_hourly_prices as pipeline
from shared.price_aggregation import aggregate_hourly_prices as api

@pytest.mark.parametrize('kind', ['complete', 'missing_quarter', 'missing_value', 'legacy', 'hourly', 'duplicate', 'mixed', 'unsupported'])
def test_api_matches_pipeline_completeness_rules(kind):
    times = pd.date_range('2026-10-25', periods=8, freq='15min', tz='UTC')
    frame = pd.DataFrame({'price_eur_mwh':range(8), 'source_resolution':'PT15M'}, index=times)
    if kind == 'missing_quarter': frame = frame.drop(times[2])
    elif kind == 'missing_value': frame.loc[times[2], 'price_eur_mwh'] = float('nan')
    elif kind == 'legacy': frame = frame.drop(columns='source_resolution')
    elif kind == 'hourly': frame = frame.iloc[::4].assign(source_resolution='PT60M')
    elif kind == 'duplicate': frame = pd.concat([frame,frame.iloc[:1]])
    elif kind == 'mixed': frame.loc[times[1], 'source_resolution'] = 'PT60M'
    elif kind == 'unsupported': frame['source_resolution'] = 'PT30M'
    original = frame.copy(deep=True)
    if kind in ['duplicate','mixed','unsupported']:
        with pytest.raises(ValueError) as expected: pipeline(frame)
        with pytest.raises(ValueError, match=str(expected.value)): api(frame)
    else:
        assert_frame_equal(api(frame), pipeline(frame))
        if kind in ['missing_quarter','missing_value']: assert times[0] not in api(frame).index
    assert_frame_equal(frame,original)
