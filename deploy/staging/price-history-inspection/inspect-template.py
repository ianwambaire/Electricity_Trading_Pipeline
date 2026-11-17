"""One read-only inspection: source evidence, recent outcomes, bounded upstream price GETs."""
import base64,datetime as dt,hashlib,json,os
from pathlib import Path
import re,sqlite3,stat,subprocess
BINDINGS=__BINDINGS__
exec(compile(base64.b64decode(BINDINGS['helpers']),'<reviewed_readonly_helpers>','exec'),globals())
exec(compile(base64.b64decode(BINDINGS['reason_helper']),'<safe_reason_helpers>','exec'),globals())
NOW=dt.datetime.now(dt.timezone.utc)
OUT={'stage':'source_guards','read_only':True,'retry':False,'observed_utc':NOW.isoformat()}


def recent_outcomes(flows):
    path=ROOT/'database/electricity_trading.db';before=path.stat()
    require(not path.is_symlink() and stat.S_ISREG(before.st_mode),'database_identity')
    def journal():return any(Path(str(path)+suffix).exists() and Path(str(path)+suffix).stat().st_size>0 for suffix in ['-wal','-journal'])
    require(not journal(),'database_journal_active')
    since=(NOW-dt.timedelta(hours=12)).isoformat()
    connection=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True,timeout=2);connection.row_factory=sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        tables={'pipeline_runs','pipeline_stage_timings','operational_incidents'}
        connection.set_authorizer(lambda action,a,b,c,d:sqlite3.SQLITE_OK if action==sqlite3.SQLITE_SELECT or action==sqlite3.SQLITE_READ and a in tables else sqlite3.SQLITE_DENY)
        stages=[dict(r) for r in connection.execute('SELECT run_id,start_timestamp_utc,end_timestamp_utc,status FROM pipeline_stage_timings WHERE stage_name=? AND start_timestamp_utc>=? ORDER BY id DESC LIMIT 12',('Total pipeline',since))]
        totals={r['run_id']:r for r in stages}
        incidents={}
        for r in connection.execute('SELECT timestamp_utc,details_json FROM operational_incidents WHERE component=? AND event_type=? AND timestamp_utc>=? ORDER BY id DESC LIMIT 12',('next24h forecast','forecast_withheld',since)):
            details=json.loads(r['details_json'] or '{}');internal=details.get('run_id')
            if internal and internal not in incidents:incidents[internal]={'time':r['timestamp_utc'],'reason':safe_reason(details.get('reason'))}
        rows=[]
        for r in connection.execute('SELECT run_time,status,message FROM pipeline_runs WHERE run_time>=? ORDER BY id DESC LIMIT 8',(since,)):
            data=json.loads(r['message'] or '{}');internal=data.get('run_id');total=totals.get(internal)
            associated=[]
            if total:
                associated=[f for f in flows if f.get('auto_scheduled') is True and stamp(f['expected_start_time']).minute==45
                    and stamp(f['start_time'])-dt.timedelta(seconds=2)<=stamp(total['start_timestamp_utc'])<=stamp(total['end_timestamp_utc'])<=stamp(f['end_time'])+dt.timedelta(seconds=2)]
            rows.append({'run_time':r['run_time'],'pipeline_status':r['status'],'internal_run_uuid':internal,
                'forecast_status':data.get('next24h_forecast_status'),'forecast_issue_time':data.get('next24h_forecast_issue_time'),
                'withheld_at_utc':data.get('next24h_forecast_withheld_at_utc'),
                'recorded_latest_complete_hours':data.get('next24h_latest_complete_market_hours'),
                'withholding_incident':incidents.get(internal),'scheduled_association_verified':len(associated)==1,
                'prefect_flow_id':associated[0]['id'] if len(associated)==1 else None,
                'scheduled_time':associated[0]['expected_start_time'] if len(associated)==1 else None})
    finally:connection.close()
    after=path.stat();require(not journal() and (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'database_changed_during_query')
    return rows


def main():
    require(ROOT.resolve(strict=True)==ROOT,'repository_identity')
    OUT['source_hashes']={name:digest(read(ROOT/name)) for name in BINDINGS['source_hashes']}
    require(OUT['source_hashes']==BINDINGS['source_hashes'],'source_code_drift')
    OUT['stage']='recent_runs'
    flows=api('/flow_runs/filter',{'deployments':{'id':{'any_':[DEP]}},'flow_runs':{'state':{'type':{'any_':['COMPLETED']}}},'sort':'EXPECTED_START_TIME_DESC','limit':12})
    try:OUT['recent_pipeline_outcomes']=recent_outcomes(flows)
    except Exception as error:OUT['recent_outcomes_unverified']={'error_type':type(error).__name__}
    OUT['stage']='read_only_price_and_upstream_child'
    source=base64.b64decode(BINDINGS['price_child'])
    require(digest(source)==BINDINGS['child_sha256'],'price_child_hash')
    def drop():os.setgroups([1000]);os.setgid(1000);os.setuid(1000)
    child=subprocess.run([str(ROOT/'.venv-prod/bin/python'),'-I','-B','-c',source.decode()],capture_output=True,timeout=75,
        cwd='/',preexec_fn=drop,env={'PATH':'/usr/bin:/bin','HOME':'/home/ec2-user','LANG':'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE':'1','AWS_MAX_ATTEMPTS':'1','AWS_METADATA_SERVICE_TIMEOUT':'3','AWS_METADATA_SERVICE_NUM_ATTEMPTS':'1'})
    OUT['child_exit']=child.returncode
    require(len(child.stdout)<=200000,'child_output_bound')
    if child.stdout:OUT['price_inspection']=json.loads(child.stdout)
    if child.returncode or not child.stdout:OUT['child_error']='raw_stderr_withheld'
    OUT['stage']='complete'


if __name__=='__main__':
    try:main();print(json.dumps(OUT))
    except Exception as error:
        OUT['error']={'type':type(error).__name__,'reason':str(error) if isinstance(error,RuntimeError) else 'details_withheld'}
        if hasattr(error,'code'):OUT['error']['http_status']=error.code
        print(json.dumps(OUT));raise SystemExit(1)
