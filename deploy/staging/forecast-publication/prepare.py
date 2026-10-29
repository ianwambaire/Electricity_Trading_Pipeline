"""Offline allowlisted bundle builder. Requires verified input evidence; no network."""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
from shared.forecast_publication import FEATURES, MAX_BYTES, require, safe_file, validate, decode


def build(forecast, provenance, model, evidence, expected, now=None):
    blobs=[safe_file(Path(p)) for p in (forecast,provenance,model,evidence)]
    require(all(hashlib.sha256(raw).hexdigest()==digest for raw,digest in zip(blobs,expected)))
    reader=csv.DictReader(io.StringIO(blobs[0].decode('utf-8')))
    require(reader.fieldnames==['forecast_issue_time','target_timestamp','horizon_hours','predicted_price_eur_mwh','model_release'])
    rows=[]
    for row in reader:
        require(len(rows)<24 and None not in row)
        rows.append({'issue_time':row['forecast_issue_time'],'target_time':row['target_timestamp'],'horizon_hours':int(row['horizon_hours']),'predicted_price_eur_mwh':float(row['predicted_price_eur_mwh']),'model_release':row['model_release']})
    pr,manifest,proof=(decode(raw) for raw in blobs[1:])
    require(manifest.get('feature_count')==31 and manifest.get('features')==list(FEATURES) and manifest.get('horizons_hours')==list(range(1,25)))
    require(set(proof)=={'execution','inputs'})
    bundle={'version':1,'forecasts':rows,'model':{'release':manifest['release_id'],'model_sha256':manifest['model_sha256'],'feature_contract_sha256':manifest['feature_contract_sha256']},'provenance':{'issue_time':pr['forecast_issue_time'],'weather_hour':pr['weather_hour'],'weather_acquired_at':pr['weather_acquired_at_utc'],'weather_source':pr['weather_source']},'execution':proof['execution'],'inputs':proof['inputs']}
    raw=json.dumps(bundle,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    digest=hashlib.sha256(raw).hexdigest();validate(raw,digest,now)
    return raw,digest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['forecast','provenance','model','evidence']:
        p.add_argument('--'+name,type=Path,required=True);p.add_argument('--'+name+'-sha256',required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    raw,digest=build(a.forecast,a.provenance,a.model,a.evidence,[getattr(a,n+'_sha256') for n in ['forecast','provenance','model','evidence']])
    os.umask(0o077)
    with a.out.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    print(json.dumps({'bundle_sha256':digest,'bytes':len(raw),'source_forecast_sha256':a.forecast_sha256}))

if __name__=='__main__':
    try:main()
    except Exception:
        print(json.dumps({'status':'STOPPED','reason':'Verified fresh source evidence is required.'}));raise SystemExit(1)
