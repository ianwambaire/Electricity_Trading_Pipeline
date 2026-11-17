"""Local CSV coverage audit; absence alone cannot prove A03 causation."""
import argparse
import json
import pandas as pd


def audit(path):
    data = pd.read_csv(path)
    index = pd.to_datetime(data['timestamp'], utc=True, errors='raise')
    if index.duplicated().any():
        raise ValueError('duplicate_source_timestamps')
    data['timestamp'] = index
    if 'source_resolution' not in data or data.source_resolution.isna().any():
        return {'scope':'local source only; not current production', 'rows':len(data), 'status':'UNVERIFIED', 'reason':'resolution_metadata_unavailable', 'causation':'Cannot attribute gaps to A03 without resolution metadata and original XML'}
    quarter = data.loc[data.source_resolution.eq('PT15M')].set_index('timestamp')
    defects = []
    if not quarter.empty:
        hours = pd.date_range(quarter.index.min().floor('h'), quarter.index.max().floor('h'), freq='h')
        for hour in hours:
            wanted = pd.date_range(hour, periods=4, freq='15min')
            missing = wanted.difference(quarter.index)
            nulls = quarter.reindex(wanted).price_eur_mwh.isna()
            if len(missing) or nulls.any():
                defects.append({'hour':hour.isoformat(), 'missing':[x.isoformat() for x in missing], 'invalid_or_absent':int(nulls.sum())})
    return {'scope':'local source only; not current production', 'rows':len(data), 'incomplete_pt15m_hours':len(defects), 'sample':defects[:100], 'truncated':len(defects)>100, 'causation':'Requires original XML curveType; CSV gaps alone do not prove A03'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('csv')
    print(json.dumps(audit(parser.parse_args().csv), indent=2))
