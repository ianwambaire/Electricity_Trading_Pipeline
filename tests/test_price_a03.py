import hashlib
import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from ingestion.fetch_entsoe_data import parse_price_observations
from processing.build_silver_dataset import aggregate_hourly_prices
from models.next24h_production import _historical_market_features


def xml(points, curve='A03', start='2026-10-24T00:00Z', end='2026-10-25T00:00Z', resolution='PT15M'):
    body = ''.join(f'<Point><position>{p}</position><price.amount>{v}</price.amount></Point>' for p, v in points)
    return f'<Publication_MarketDocument xmlns="urn:iec62325"><TimeSeries><curveType>{curve}</curveType><Period><timeInterval><start>{start}</start><end>{end}</end></timeInterval><resolution>{resolution}</resolution>{body}</Period></TimeSeries></Publication_MarketDocument>'


def test_93_blocks_cover_96_quarters():
    points = [(p, p) for p in range(1, 97) if p not in {48, 50, 75}]
    result = parse_price_observations(xml(points))
    assert len(result) == 96
    assert result.iloc[47].price_eur_mwh == 47
    assert result.iloc[49].price_eur_mwh == 49
    assert result.attrs['price_decode_diagnostics'][0]['explicit_points'] == 93
    assert len(aggregate_hourly_prices(result)) == 24


def test_a01_never_expands_gaps():
    result = parse_price_observations(xml([(1, 10), (3, 20)], curve='A01', end='2026-10-24T01:00Z'))
    assert len(result) == 2
    assert aggregate_hourly_prices(result).empty
    assert result.attrs['price_decode_diagnostics'][0]['classification'] == 'upstream_missing_a01_points'


@pytest.mark.parametrize('points', [[], [(2, 1)], [(1, 1), (1, 2)], [(1, 1), (3, 3), (2, 2)], [(1, 1), (97, 2)], [(0, 1)], [(1, float('nan'))], [(1, float('inf'))], [('1.0', 2)]])
def test_invalid_blocks_rejected(points):
    with pytest.raises(ValueError):
        parse_price_observations(xml(points))


@pytest.mark.parametrize('kwargs', [
    {'end':'2026-10-24T00:20Z'}, {'end':'2026-10-23T00:00Z'},
    {'start':'2026-10-24T00:01Z'}, {'start':'2026-10-24T00:00'},
    {'curve':'A02'}, {'resolution':'PT30M'},
])
def test_invalid_periods_rejected(kwargs):
    with pytest.raises(ValueError):
        parse_price_observations(xml([(1, 10)], **kwargs))


@pytest.mark.parametrize('start,end,hours', [
    ('2026-03-28T23:00Z','2026-03-29T22:00Z',23),
    ('2026-10-24T22:00Z','2026-10-25T23:00Z',25),
    ('2026-10-25T00:00+02:00','2026-10-26T00:00+01:00',25),
])
def test_dst_uses_utc_elapsed_time(start,end,hours):
    result = parse_price_observations(xml([(1, -10)], start=start, end=end))
    assert len(result) == hours * 4
    assert result.index.is_unique
    assert result.price_eur_mwh.eq(-10).all()


def test_nested_period_overlap_and_duplicate_metadata_rejected():
    source = xml([(1, 3)])
    period = source[source.index('<Period>'):source.index('</Period>')+9]
    with pytest.raises(ValueError, match='overlapping'):
        parse_price_observations(source.replace('</TimeSeries>',period+'</TimeSeries>'))
    with pytest.raises(ValueError, match='ambiguous'):
        parse_price_observations(source.replace('<curveType>A03</curveType>', '<curveType>A03</curveType><curveType>A01</curveType>'))


def test_recovered_history_restores_168h_contract():
    quarters = pd.date_range('2026-10-24T00:00Z', '2026-10-31T12:45Z', freq='15min')
    values = pd.DataFrame({'price_eur_mwh':100.0, 'source_resolution':'PT15M'}, index=quarters)
    values = values.drop(pd.to_datetime(['2026-10-24T11:45Z','2026-10-24T12:15Z']))
    hours = pd.to_datetime(['2026-10-31T11:00Z','2026-10-31T12:00Z'])
    assert not any(t in _historical_market_features(aggregate_hourly_prices(values), 'price').index for t in hours)
    recovered = parse_price_observations(xml([(1,100)]))
    repaired = pd.concat([values, recovered.loc[recovered.index.difference(values.index)]]).sort_index()
    features = _historical_market_features(aggregate_hourly_prices(repaired), 'price')
    assert features.loc[hours, 'price_lag_168h'].eq(100).all()


def repair_module():
    spec = importlib.util.spec_from_file_location('repair_a03', Path(__file__).resolve().parents[1] / 'deploy/staging/a03-price-recovery/repair.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repair_is_allowlisted_conflict_safe_and_idempotent():
    m = repair_module()
    fresh = parse_price_observations(xml([(1,100)], start='2026-10-24T11:00Z',end='2026-10-24T13:00Z'))
    old = fresh.drop(m.ALLOWED).reset_index().to_csv(index=False).encode()
    source_xml = xml([(1,100)], start='2026-10-24T11:00Z',end='2026-10-24T13:00Z').encode()
    digest = lambda b: hashlib.sha256(b).hexdigest()
    candidate, report = m.prepare(old,source_xml,digest(old),digest(source_xml))
    assert report['added_count'] == 2
    assert m.prepare(candidate,source_xml,digest(candidate),digest(source_xml))[1]['idempotent_noop']
    with pytest.raises(ValueError,match='hash'):
        m.prepare(old,source_xml,'0'*64,digest(source_xml))
    conflict = old.replace(b'100.0',b'101.0')
    with pytest.raises(ValueError,match='conflict'):
        m.prepare(conflict,source_xml,digest(conflict),digest(source_xml))
    missing = fresh.drop([m.ALLOWED[0], fresh.index[0]]).reset_index().to_csv(index=False).encode()
    with pytest.raises(ValueError,match='unapproved'):
        m.prepare(missing,source_xml,digest(missing),digest(source_xml))


def test_repair_rejects_incomplete_a01_and_wrong_resolution():
    m = repair_module()
    old = b'timestamp,price_eur_mwh,source_resolution\n2026-10-24T11:00:00Z,100,PT15M\n'
    for content in [xml([(1,100)], curve='A01',start='2026-10-24T11:00Z',end='2026-10-24T13:00Z'), xml([(1,100)],resolution='PT60M',start='2026-10-24T11:00Z',end='2026-10-24T13:00Z')]:
        raw = content.encode()
        with pytest.raises(ValueError, match='incomplete'):
            m.prepare(old,raw,m.sha(old),m.sha(raw))


def test_repair_cli_private_outputs_and_no_source_write(tmp_path, monkeypatch):
    m = repair_module()
    raw = xml([(1,100)],start='2026-10-24T11:00Z',end='2026-10-24T13:00Z').encode()
    original = parse_price_observations(raw.decode()).drop(m.ALLOWED).reset_index().to_csv(index=False).encode()
    source, upstream = tmp_path/'prices.csv', tmp_path/'response.xml'
    source.write_bytes(original)
    upstream.write_bytes(raw)
    out = tmp_path/'private'
    monkeypatch.setattr('sys.argv', ['repair.py','--source',str(source),'--xml',str(upstream),'--source-sha256',m.sha(original),'--xml-sha256',m.sha(raw),'--output',str(out)])
    m.main()
    assert source.read_bytes() == original
    assert out.stat().st_mode & 0o777 == 0o700
    for path in out.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
    assert (out/'original.csv').read_bytes() == original
    with pytest.raises(ValueError, match='destination_conflict'):
        m.main()


def test_parser_does_not_bridge_separate_period_gap():
    first = xml([(1,10)], end='2026-10-24T01:00Z')
    second = xml([(1,20)],start='2026-10-24T02:00Z',end='2026-10-24T03:00Z')
    series = second[second.index('<TimeSeries>'):second.index('</TimeSeries>')+13]
    result = parse_price_observations(first.replace('</Publication_MarketDocument>',series+'</Publication_MarketDocument>'))
    assert pd.Timestamp('2026-10-24T01:00Z') not in result.index
    assert len(result) == 8


def test_out_of_order_periods_rejected():
    first = xml([(1,10)],start='2026-10-24T02:00Z',end='2026-10-24T03:00Z')
    second = xml([(1,20)],start='2026-10-24T00:00Z',end='2026-10-24T01:00Z')
    series = second[second.index('<TimeSeries>'):second.index('</TimeSeries>')+13]
    with pytest.raises(ValueError,match='out of order'):
        parse_price_observations(first.replace('</Publication_MarketDocument>',series+'</Publication_MarketDocument>'))


def test_null_value_never_becomes_a03_block():
    with pytest.raises(ValueError):
        parse_price_observations(xml([(1,'')]))


def test_dry_run_has_no_output_or_source_mutation(tmp_path, monkeypatch):
    m = repair_module()
    raw = xml([(1,100)],start='2026-10-24T11:00Z',end='2026-10-24T13:00Z').encode()
    original = parse_price_observations(raw.decode()).drop(m.ALLOWED).reset_index().to_csv(index=False).encode()
    source, upstream = tmp_path/'prices.csv', tmp_path/'response.xml'
    source.write_bytes(original)
    upstream.write_bytes(raw)
    monkeypatch.setattr('sys.argv', ['repair.py','--source',str(source),'--xml',str(upstream),'--source-sha256',m.sha(original),'--xml-sha256',m.sha(raw)])
    m.main()
    assert source.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ['prices.csv','response.xml']


def test_candidate_preserves_original_bytes_including_float_formatting():
    m = repair_module()
    raw = xml([(1,100)],start='2026-10-24T11:00Z',end='2026-10-24T13:00Z').encode()
    original = parse_price_observations(raw.decode()).drop(m.ALLOWED).reset_index().to_csv(index=False).encode().replace(b'100.0',b'100.000000000')
    candidate, _ = m.prepare(original,raw,m.sha(original),m.sha(raw))
    assert candidate.startswith(original)
