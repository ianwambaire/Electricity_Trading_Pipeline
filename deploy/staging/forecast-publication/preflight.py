"""Read-only publication gate. Stale forecasts stop preparation; no inference/writes."""
import csv,datetime as D,hashlib,io,json,math,os,pathlib,urllib.request
ROOT=pathlib.Path('/home/ec2-user/Electricity_Trading_Pipeline')
DEP='47e5ef51-26d0-44b6-b119-2c40d0e77397'
UTC=D.timezone.utc

def timestamp(value):
 t=D.datetime.fromisoformat(value.replace('Z','+00:00'))
 if t.tzinfo is None:raise ValueError('timezone_required')
 return t.astimezone(UTC)

def main():
 now=D.datetime.now(UTC)
 req=urllib.request.Request('http://127.0.0.1:4200/api/flow_runs/filter',data=json.dumps({'deployments':{'id':{'any_':[DEP]}},'flow_runs':{'state':{'type':{'any_':['COMPLETED']}}},'sort':'START_TIME_DESC','limit':1}).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=10) as response:runs=json.loads(response.read(100001))
 if len(runs)!=1:raise ValueError('completed_run_not_found')
 run=runs[0];report={'as_of':now.isoformat(),'latest_completed_run':{k:run.get(k) for k in ['id','expected_start_time','start_time','end_time']},'preparation_allowed':False}
 path=ROOT/'data/reports/next24h_forecast.csv';before=path.stat()
 if before.st_size>100000:raise ValueError('artifact_size')
 with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NOATIME),'rb') as f:raw=f.read(100001)
 rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8'))))
 issue=timestamp(rows[0]['forecast_issue_time']) if rows else None
 valid=len(rows)==24 and [int(r['horizon_hours']) for r in rows]==list(range(1,25)) and all(timestamp(r['forecast_issue_time'])==issue and timestamp(r['target_timestamp'])==issue+D.timedelta(hours=int(r['horizon_hours'])) and math.isfinite(float(r['predicted_price_eur_mwh'])) for r in rows) and len({r['model_release'] for r in rows})==1
 report.update(artifact=str(path),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),issue=issue.isoformat() if issue else None,freshness_cutoff=(issue+D.timedelta(hours=3)).isoformat() if issue else None,contract_valid=valid,remaining_future_targets=sum(timestamp(r['target_timestamp'])>now for r in rows),model_release=rows[0]['model_release'] if rows else None)
 after=path.stat();stable=(before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns)
 report['stable']=stable
 if not valid or not stable:report['blocker']='invalid_or_changing_artifact'
 elif not D.timedelta(0)<=now-issue<=D.timedelta(hours=3):report['blocker']='latest_forecast_stale'
 else:report['preparation_allowed']=True;report['blocker']=None
 print(json.dumps(report,indent=2));return 0 if report['preparation_allowed'] else 1
if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as e:print(json.dumps({'preparation_allowed':False,'error_type':type(e).__name__}));raise SystemExit(1)
