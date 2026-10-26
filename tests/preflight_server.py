"""LOCAL ONLY browser fixture server. Never a deployment entry point.

The main app retains JWT guards and reads a private copy of actual local data.
/__fixtures is explicitly synthetic, with a test-only Admin dependency override.
All writes are blocked. No AWS credentials, provider requests or jobs are used.
"""
import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3

from fastapi.responses import JSONResponse
from api.app import APISettings, create_app
from api.market_data import VALUE_FIELDS, WEATHER_FIELDS
from api.runtime import RuntimeSettings
from api.security import SecuritySettings, CognitoVerifier, JwksCache, CurrentUser, require_admin
from shared.forecast_evaluation import REALIZED_COLUMNS

SECURITY=SecuritySettings('https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OfflineTest',frozenset({'offlineclient'}))

def write_csv(root,relative,fields,rows):
    path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def fixture_data(root,actual):
    root.mkdir(mode=0o700,exist_ok=False)
    issue=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    rows=[]
    for i in range(168):
        row=dict.fromkeys([*VALUE_FIELDS,*WEATHER_FIELDS],1)
        row.update(timestamp=(issue-timedelta(hours=167-i)).isoformat(),price_eur_mwh=i-50,load_mw=100+i,wind_total_mw=6,solar_mw=2,temperature_2m=i/10,wind_speed_10m=4+i/10)
        rows.append(row)
    write_csv(root,'data/processed/silver_electricity_market_data.csv',['timestamp',*VALUE_FIELDS,*WEATHER_FIELDS],rows)
    for relative in ['data/raw/entsoe/prices.csv','data/raw/entsoe/load.csv','data/raw/entsoe/generation.csv','data/raw/weather/open_meteo_weather.csv','data/features/gold_model_features.csv']:
        write_csv(root,relative,['timestamp',*VALUE_FIELDS,*WEATHER_FIELDS],rows)
    write_csv(root,'data/reports/actual_vs_predicted.csv',['timestamp','actual_price','predicted_price'],[{'timestamp':r['timestamp'],'actual_price':r['price_eur_mwh'],'predicted_price':r['price_eur_mwh']+1} for r in rows])
    write_csv(root,'data/reports/detected_anomalies.csv',['timestamp','price_eur_mwh','load_mw','anomaly'],[{**{k:r[k] for k in ['timestamp','price_eur_mwh','load_mw']},'anomaly':-1} for r in rows[-2:]])
    forecasts=[dict(forecast_issue_time=issue.isoformat(),target_timestamp=(issue+timedelta(hours=h)).isoformat(),horizon_hours=h,predicted_price_eur_mwh=h-12,model_release='fixture-not-a-trained-release') for h in range(1,25)]
    write_csv(root,'data/reports/next24h_forecast.csv',list(forecasts[0]),forecasts)
    write_csv(root,'data/reports/next24h_forecast_history.csv',[*forecasts[0],'issued_at_utc'],[{**r,'issued_at_utc':issue.isoformat()} for r in forecasts])
    realized=[]
    for i in range(24):
        stamp=issue-timedelta(hours=i+2)
        realized.append(dict(zip(REALIZED_COLUMNS,[stamp.isoformat(),(stamp+timedelta(hours=1)).isoformat(),1,stamp.isoformat(),2,'fixture-not-a-trained-release',1,1,1,1])))
    write_csv(root,'data/reports/next24h_realized_errors.csv',REALIZED_COLUMNS,realized)
    monitoring=root/'data/reports/monitoring';monitoring.mkdir(parents=True)
    (monitoring/'forecast_vintage_health.json').write_text(json.dumps({'generated_at_utc':issue.isoformat(),'overall_status':'STALE','sources':[{'source':'OPEN_METEO','status':'STALE','expected_target_count':24,'observed_target_count':20,'missing_target_count':4}]}))
    (monitoring/'next24h_exogenous_silver_quality.json').write_text(json.dumps({'generated_at_utc':issue.isoformat(),'dataset_status':'NOT_READY','distinct_issue_cycles':1,'distinct_calendar_days':1,'complete_issue_cycles':0,'horizon_coverage_count':24,'output_rows':24,'leakage_check':{'passed':True}}))
    # Existing genuine model summaries remain identified as copied metadata, not
    # claimed to have generated synthetic forecasts or evaluation errors.
    if (actual/'artifacts').exists():shutil.copytree(actual/'artifacts',root/'artifacts')
    for name in ['final_holdout_metrics.csv','feature_importance.csv']:
        if (actual/'data/reports'/name).is_file():shutil.copyfile(actual/'data/reports'/name,root/'data/reports'/name)
    path=root/'database/electricity_trading.db';path.parent.mkdir()
    with sqlite3.connect(path) as db:
        db.executescript((Path(__file__).parents[1]/'database/schema.sql').read_text())
        db.execute('INSERT INTO pipeline_runs(run_time,status,records_processed,message) VALUES(?,?,?,?)',(issue.isoformat(),'SUCCESS',168,json.dumps({'next24h_forecast_status':'GENERATED','new_rows_ingested':0,'predictions_generated':168})))
        db.execute('INSERT INTO data_quality_results(check_time,check_name,status,message) VALUES(?,?,?,?)',(issue.isoformat(),'silver_dataset_validation','PASSED','Synthetic preflight fixture'))
        db.execute('INSERT INTO operational_incidents(timestamp_utc,severity,component,event_type,status,message) VALUES(?,?,?,?,?,?)',(issue.isoformat(),'WARNING','ENTSO-E','SOURCE_GAP','ACTIVE','Synthetic fixture'))
        for name,duration in [('Total pipeline',2.5),('Next24h forecast generation',0.75)]:
            db.execute('INSERT INTO pipeline_stage_timings(run_id,stage_name,start_timestamp_utc,end_timestamp_utc,duration_seconds,status) VALUES(?,?,?,?,?,?)',('fixture-run',name,issue.isoformat(),(issue+timedelta(seconds=duration)).isoformat(),duration,'SUCCESS'))

def build(actual,fixtures):
    def application(root):
        app=create_app(APISettings.from_root(root),security_settings=SECURITY,runtime_settings=RuntimeSettings('staging',('localhost','127.0.0.1','testserver')))
        # Never request even public provider metadata from this isolated server.
        app.state.account_totp_enabled=False
        app.state.cognito_verifier=CognitoVerifier(SECURITY,JwksCache(SECURITY.jwks_url,fetch=lambda _: {'keys':[]}))
        return app
    actual=Path(actual).resolve();fixtures=Path(fixtures).resolve()
    if not (actual/'preflight-manifest.json').is_file():raise ValueError('Expected private local snapshot manifest')
    if not fixtures.exists():fixture_data(fixtures,actual)
    app=application(actual);fixture=application(fixtures)
    fixture.dependency_overrides[require_admin]=lambda:CurrentUser('01234567-89ab-4def-8123-0123456789ab','Admin')
    app.mount('/__fixtures',fixture)
    @app.middleware('http')
    async def read_only(request,call_next):
        if request.method not in {'GET','HEAD'}:return JSONResponse({'detail':'Local preflight is read-only.'},status_code=405)
        return await call_next(request)
    return app

def factory():
    return build(os.environ['POWERFLOW_PREFLIGHT_ACTUAL_ROOT'],os.environ['POWERFLOW_PREFLIGHT_FIXTURE_ROOT'])
