"""Create a private, allowlisted LOCAL snapshot for browser preflight; never production writes."""
from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

FILES = (
    'data/processed/silver_electricity_market_data.csv', 'data/features/gold_model_features.csv',
    'data/raw/entsoe/prices.csv','data/raw/entsoe/load.csv','data/raw/entsoe/generation.csv',
    'data/raw/weather/open_meteo_weather.csv', 'data/reports/actual_vs_predicted.csv',
    'data/reports/detected_anomalies.csv','data/reports/final_holdout_metrics.csv',
    'data/reports/feature_importance.csv','artifacts/models/final_model_release_manifest.json',
    'artifacts/models/final_gold_model.joblib','artifacts/models/final_gold_model_features.joblib',
    'artifacts/models/releases/next24h/next24h_release_manifest.json',
    'artifacts/models/releases/next24h/next24h_model.joblib',
    'artifacts/models/releases/next24h/next24h_feature_contract.joblib',
    'data/reports/next24h_forecast.csv','data/reports/next24h_realized_errors.csv',
    'data/reports/next24h_forecast_history.csv','data/reports/next24h_forecast_provenance.json',
    'data/reports/monitoring/forecast_vintage_health.json',
    'data/reports/monitoring/next24h_exogenous_silver_quality.json',
)

def prepare(source, destination):
    source, destination = source.resolve(), destination.resolve()
    if destination == source or source in destination.parents:
        raise ValueError('Snapshot destination must be outside the source tree')
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    records, missing = {}, []
    for relative in FILES:
        path = source/relative
        if not path.is_file(): missing.append(relative); continue
        if path.is_symlink() or source not in path.resolve().parents:
            raise ValueError('Symlinked or escaping snapshot input rejected')
        before=path.stat(); digest=hashlib.sha256(path.read_bytes()).hexdigest()
        target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target);target.chmod(0o600)
        after=path.stat()
        if (before.st_mtime_ns,before.st_size)!=(after.st_mtime_ns,after.st_size) or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
            raise ValueError('Local source changed during snapshot; discard this incomplete snapshot')
        records[relative]={'bytes':after.st_size,'sha256':digest}
    db=source/'database/electricity_trading.db'
    if db.is_file():
        if db.is_symlink() or source not in db.resolve().parents:
            raise ValueError('Symlinked or escaping database rejected')
        target=destination/'database/electricity_trading.db';target.parent.mkdir(exist_ok=True)
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as original, closing(sqlite3.connect(target)) as backup:
            original.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Snapshot integrity failed')
        target.chmod(0o600)
        records['database/electricity_trading.db']={'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'method':'SQLite online backup of local source; integrity_check ok'}
    (destination/'preflight-manifest.json').write_text(json.dumps({'scope':'LOCAL preflight only; not production restoration evidence','files':records,'missing':missing},indent=2))
    os.chmod(destination/'preflight-manifest.json',0o600)
    return {'copied_files':len(records),'missing_files':missing,'database_snapshot':db.is_file()}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--destination',type=Path,required=True);args=p.parse_args()
    print(json.dumps(prepare(args.source,args.destination),indent=2))
