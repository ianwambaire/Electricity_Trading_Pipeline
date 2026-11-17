"""Synthetic regression for the observed Nov1 A03/rolling-window failure.

These in-memory prices are tests, never operational inputs or live forecasts.
The existing parser and HGB feature rules are exercised without changing either.
"""
import io
import xml.etree.ElementTree as ET

import pandas as pd

from ingestion.fetch_entsoe_data import parse_price_observations
from models.next24h_production import _historical_market_features
from processing.build_silver_dataset import clean_prices


def price_xml():
    root=ET.Element('Publication_MarketDocument')
    series=ET.SubElement(root,'TimeSeries');ET.SubElement(series,'curveType').text='A03'
    period=ET.SubElement(series,'Period');interval=ET.SubElement(period,'timeInterval')
    ET.SubElement(interval,'start').text='2026-10-31T23:00Z'
    ET.SubElement(interval,'end').text='2026-11-01T23:00Z'
    ET.SubElement(period,'resolution').text='PT15M'
    for position in range(1,97):
        if position==74:continue # 17:15 is covered by the 17:00..17:30 A03 block.
        point=ET.SubElement(period,'Point');ET.SubElement(point,'position').text=str(position)
        ET.SubElement(point,'price.amount').text=str({73:300.44,75:300,76:299.28}.get(position,100))
    return ET.tostring(root).decode()


def cleaned(frame):
    return clean_prices(io.StringIO(frame.to_csv(index=True)))


def test_a03_duration_recovers_hour_required_by_current_rolling_window():
    decoded=parse_price_observations(price_xml())
    gap=pd.Timestamp('2026-11-01T17:15Z');hour=gap.floor('h')
    assert len(decoded)==96
    assert decoded.loc[gap,'price_eur_mwh']==decoded.loc[gap-pd.Timedelta(minutes=15),'price_eur_mwh']==300.44
    complete=cleaned(decoded)
    explicit_only=cleaned(decoded.drop(index=gap))
    assert hour in complete.index and hour not in explicit_only.index
    assert complete.loc[hour,'price_eur_mwh']==(300.44+300.44+300+299.28)/4
    issue=pd.Timestamp('2026-11-02T07:00Z')
    history=pd.DataFrame({'price_eur_mwh':100.},index=pd.date_range('2026-10-24T00:00Z',issue,freq='h'))
    history.update(complete[['price_eur_mwh']])
    fixed=_historical_market_features(history,'price')
    broken=_historical_market_features(history.drop(index=hour),'price')
    assert issue in fixed.index and issue not in broken.index
    assert issue-pd.Timedelta(hours=168) in history.index # This failure is rolling24, not lag168.
    assert fixed.loc[issue,'price_lag_168h']==100
    window=history.loc[issue-pd.Timedelta(hours=23):issue,'price_eur_mwh']
    assert fixed.loc[issue,'price_rolling_mean_24h']==window.mean()


def test_newest_price_hour_does_not_prove_rolling_feature_completeness():
    issue=pd.Timestamp('2026-11-02T07:00Z')
    history=pd.DataFrame({'price_eur_mwh':100.},index=pd.date_range('2026-10-24T00:00Z',issue,freq='h'))
    history=history.drop(index=pd.Timestamp('2026-11-01T17:00Z'))
    assert history.index.max()==issue
    assert issue not in _historical_market_features(history,'price').index
