"""Read-only prices + bounded authenticated upstream queries; never ingestion."""
import ast,datetime as D,hashlib,io,json,logging,math,os,sys
from pathlib import Path
import xml.etree.ElementTree as E
logging.disable(logging.CRITICAL)
ROOT=Path('/home/ec2-user/Electricity_Trading_Pipeline');sys.path.insert(0,str(ROOT/'src'))
import pandas as pd
import numpy as np
from processing.build_silver_dataset import clean_prices,QUARTER_HOURLY_PRICE_START_UTC
from ingestion.fetch_entsoe_data import parse_price_observations,PRICE_REQUERY_OVERLAP
CANDIDATES=[pd.Timestamp('2026-10-31T11:00:00Z'),pd.Timestamp('2026-10-31T12:00:00Z')]
WITHHELD_AT=pd.Timestamp('2026-10-31T13:47:13.620589Z')
OUT={'read_only':True,'upstream_requests':[]}


def need(ok,reason):
    if not ok:raise RuntimeError(reason)


def original_history(hourly):
    raw=(ROOT/'src/models/next24h_production.py').read_text()
    tree=ast.parse(raw);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_historical_market_features')
    space={'pd':pd,'np':np};exec(compile(ast.Module(body=[node],type_ignores=[]),'<existing_price_features>','exec'),space)
    return space['_historical_market_features'](hourly,'price')


def source_read():
    path=ROOT/'data/raw/entsoe/prices.csv';before=path.stat();need(before.st_size<20_000_000,'price_source_size')
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NOATIME),'rb') as stream:raw=stream.read(20_000_001)
    after=path.stat();need((before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'price_source_read_drift')
    return raw,{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                'mtime_utc':D.datetime.fromtimestamp(after.st_mtime,D.timezone.utc).isoformat()}


def analyze(raw):
    source=pd.read_csv(io.BytesIO(raw));need(len(source)<300000,'price_row_bound')
    source['timestamp']=pd.to_datetime(source['timestamp'],utc=True,errors='raise')
    need(not source['timestamp'].duplicated().any(),'duplicate_source_timestamps')
    source['price_eur_mwh']=pd.to_numeric(source['price_eur_mwh'],errors='coerce')
    cleaned=clean_prices(io.BytesIO(raw));history=original_history(cleaned)
    manifest=json.loads((ROOT/'artifacts/models/releases/next24h/next24h_release_manifest.json').read_bytes())
    need(manifest['feature_count']==31 and manifest['horizons_hours']==list(range(1,25)),'model_feature_contract')
    OUT['model_release']=manifest['release_id']
    OUT['ordered_model_price_features']=[name for name in manifest['features'] if name.startswith('price_')]
    full=cleaned[['price_eur_mwh']].reindex(pd.date_range(cleaned.index.min(),cleaned.index.max(),freq='h',tz='UTC'))
    # These reproduce the original unmodified helper; never pass any row to a model.
    full['price_lag_1h']=full['price_eur_mwh'].shift(1)
    full['price_lag_24h']=full['price_eur_mwh'].shift(24)
    full['price_lag_168h']=full['price_eur_mwh'].shift(168)
    full['price_rolling_mean_24h']=full['price_eur_mwh'].rolling(24).mean()
    full['price_rolling_std_24h']=full['price_eur_mwh'].rolling(24).std()
    rows=[];missing_wanted=set();bad_hours=set()
    for issue in CANDIDATES:
        required=sorted({issue-pd.Timedelta(hours=i) for i in [*range(24),24,168]})
        defects=[]
        for hour in required:
            if hour in cleaned.index:continue
            bad_hours.add(hour)
            points=source.loc[source['timestamp'].dt.floor('h')==hour].sort_values('timestamp')
            resolutions=points.get('source_resolution',pd.Series(index=points.index,dtype=object)).fillna('PT15M' if hour>=QUARTER_HOURLY_PRICE_START_UTC else 'PT60M')
            resolution=next(iter(resolutions.unique()),'PT15M' if hour>=QUARTER_HOURLY_PRICE_START_UTC else 'PT60M')
            expected=[hour+pd.Timedelta(minutes=15*i) for i in range(4 if resolution=='PT15M' else 1)]
            actual=set(points['timestamp']);missing=set(expected)-actual
            invalid=points.loc[~np.isfinite(points['price_eur_mwh']),'timestamp'].tolist()
            missing_wanted.update(missing);missing_wanted.update(invalid)
            defects.append({'hour':hour.isoformat(),'source_resolution':str(resolution),'observed_rows':len(points),
                'expected_rows':len(expected),'missing_timestamps':[t.isoformat() for t in sorted(missing)],
                'null_or_nonfinite_timestamps':[t.isoformat() for t in invalid],
                'off_grid_timestamps':[t.isoformat() for t in sorted(actual-set(expected))]})
        features={name:float(value) if math.isfinite(value) else None for name,value in full.loc[issue].items()}
        dependency_hours={'price_eur_mwh':[issue], 'price_lag_1h':[issue-pd.Timedelta(hours=1)],
            'price_lag_24h':[issue-pd.Timedelta(hours=24)],'price_lag_168h':[issue-pd.Timedelta(hours=168)],
            'price_rolling_mean_24h':[issue-pd.Timedelta(hours=i) for i in range(24)],
            'price_rolling_std_24h':[issue-pd.Timedelta(hours=i) for i in range(24)]}
        failures={name:[t.isoformat() for t in times if t not in cleaned.index] for name,times in dependency_hours.items() if features[name] is None}
        eligible=issue in history.index
        need(eligible==all(v is not None for v in features.values()),'feature_helper_disagreement')
        if eligible:need(all(math.isclose(float(history.loc[issue,name]),value,rel_tol=1e-12,abs_tol=1e-12) for name,value in features.items()),'native_feature_value_disagreement')
        rows.append({'issue_hour':issue.isoformat(),'price_features_eligible':eligible,
            'freshness_at_recorded_withholding':bool(pd.Timedelta(0)<=WITHHELD_AT-issue<=pd.Timedelta(hours=3)),
            'rolling_start':(issue-pd.Timedelta(hours=23)).isoformat(),'rolling_end':issue.isoformat(),
            'required_hour_count':len(required),'feature_values':features,'failed_features_and_missing_hours':failures,
            'observation_defects':defects,'feature_logic_matches_native_helper':True})
    latest=source['timestamp'].max();query_start=latest.floor('h')-PRICE_REQUERY_OVERLAP
    OUT.update(source_rows=len(source),latest_stored_price_timestamp=latest.isoformat(),latest_complete_price_hour=cleaned.index.max().isoformat(),
        candidates=rows,normal_price_overlap_hours=PRICE_REQUERY_OVERLAP.total_seconds()/3600,
        next_normal_price_query_start=query_start.isoformat(),
        missing_before_normal_overlap=[t.isoformat() for t in sorted(missing_wanted) if t<query_start],
        missing_within_normal_overlap=[t.isoformat() for t in sorted(missing_wanted) if t>=query_start])
    return sorted(missing_wanted),bad_hours


def upstream(wanted,bad_hours):
    if not wanted:
        OUT['upstream_status']='NOT_NEEDED_no_current_missing_observations';return
    # Two disjoint, bounded windows cover the 168h lags and all current rolling/24h dependencies.
    windows=[]
    for first,last in [(CANDIDATES[0]-pd.Timedelta(hours=168),CANDIDATES[1]-pd.Timedelta(hours=167)),
                       (CANDIDATES[0]-pd.Timedelta(hours=24),CANDIDATES[1]+pd.Timedelta(hours=1))]:
        subset=[t for t in wanted if first<=t<last]
        if subset:windows.append((first,last,subset))
    need(1<=len(windows)<=2 and all(last-first<=pd.Timedelta(hours=26) for first,last,_ in windows),'provider_window_bound')
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env',override=False)
    from powerflow_secrets import get_secret
    import requests
    endpoint=os.environ.get('ENTSOE_ENDPOINT_URL') or 'https://web-api.tp.entsoe.eu/api'
    need(endpoint=='https://web-api.tp.entsoe.eu/api','unapproved_provider_endpoint')
    key=get_secret('ENTSOE_API_KEY')
    session=requests.Session();session.trust_env=False
    session.mount('https://',requests.adapters.HTTPAdapter(max_retries=0))
    try:
        for first,last,subset in windows:
            result={'start_utc':first.isoformat(),'end_exclusive_utc':last.isoformat(),'attempts':1}
            OUT['upstream_requests'].append(result)
            params={'securityToken':key,'documentType':'A44','in_Domain':'10Y1001A1001A82H',
                'out_Domain':'10Y1001A1001A82H','contract_MarketAgreement.type':'A01','offset':0,
                'classificationSequence_AttributeInstanceComponent.position':1,
                'periodStart':first.strftime('%Y%m%d%H%M'),'periodEnd':last.strftime('%Y%m%d%H%M')}
            response=session.get(endpoint,params=params,timeout=(5,20),allow_redirects=False,stream=True)
            result['http']=response.status_code
            need(response.status_code==200,'provider_non_200')
            parts=[];total=0
            for part in response.iter_content(16384):
                total+=len(part);need(total<=2_000_000,'provider_response_bound');parts.append(part)
            response.close();text=b''.join(parts).decode('utf-8');del params
            xml=E.fromstring(text);raw_points={};curves=set();periods=[]
            for series in xml.findall('.//{*}TimeSeries'):
                curve=series.findtext('{*}curveType');curves.add(curve)
                for period in series.findall('{*}Period'):
                    start=pd.Timestamp(period.findtext('{*}timeInterval/{*}start'))
                    end=pd.Timestamp(period.findtext('{*}timeInterval/{*}end'))
                    resolution=period.findtext('{*}resolution');step={'PT15M':15,'PT60M':60}.get(resolution)
                    need(step is not None,'provider_resolution')
                    points=period.findall('{*}Point');positions=[]
                    for point in points:
                        position=int(point.findtext('{*}position'));value=float(point.findtext('{*}price.amount'))
                        timestamp=start+pd.Timedelta(minutes=(position-1)*step);positions.append(position)
                        if math.isfinite(value):raw_points.setdefault(timestamp,[]).append({'resolution':resolution,'value':value})
                    expected=int((end-start).total_seconds()/(60*step))
                    periods.append({'start':start.isoformat(),'end':end.isoformat(),'resolution':resolution,
                        'curve_type':curve,'explicit_point_count':len(points),'nominal_slots':expected,
                        'missing_position_count':len(set(range(1,expected+1))-set(positions))})
            parsed=parse_price_observations(text)
            finite=parsed.loc[np.isfinite(pd.to_numeric(parsed['price_eur_mwh'],errors='coerce'))]
            result.update(tls_verified=True,curve_types=sorted(c for c in curves if c),periods=periods,
                explicit_finite_points=len(raw_points),production_parser_points=len(finite),
                wanted=[{'timestamp':t.isoformat(),'upstream_explicit_present':t in raw_points,
                         'production_parser_present':t in finite.index,
                         'raw_resolutions':sorted({p['resolution'] for p in raw_points.get(t,[])})} for t in subset],
                raw_and_parser_finite_timestamps_equal=set(raw_points)==set(finite.index))
    finally:session.close();del key


def main():
    raw,metadata=source_read();OUT['source_snapshot']=metadata
    wanted,bad=analyze(raw);upstream(wanted,bad)
    OUT['stage']='complete'


try:main()
except Exception as error:OUT['error_type']=type(error).__name__;OUT['stage']='STOPPED_error_details_withheld'
print(json.dumps(OUT,allow_nan=False))
