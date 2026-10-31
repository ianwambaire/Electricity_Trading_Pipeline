"""One read-only production capture preflight. Standard library; no Git commands."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import urllib.request

ROOT=Path('/home/ec2-user/Electricity_Trading_Pipeline')
DEP='47e5ef51-26d0-44b6-b119-2c40d0e77397'
UNITS=['powerflow-api.service','powerflow-streamlit.service','powerflow-prefect-worker.service','powerflow-prefect-server.service','postgresql.service']
FILES=['src/models/next24h.py','src/models/next24h_production.py','src/models/inference_evidence.py',
       'src/processing/build_silver_dataset.py','src/ingestion/fetch_weather_data.py','src/models/final_evaluation.py',
       'src/scheduled_pipeline.py','artifacts/models/releases/next24h/next24h_release_manifest.json']
BASELINES=['/etc/nginx/conf.d/powerflow.conf','/etc/nginx/conf.d/powerflow-staging-https.conf',
           '/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem']
OUT={'read_only':True,'automatic_retry':False,'stage':'identity','errors':[]}

def read(path,limit=2_000_000):
    fd=os.open(path,os.O_RDONLY|os.O_NOATIME)
    with os.fdopen(fd,'rb') as stream:
        raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('read_bound')
    return raw

def metadata(path,hash_file=False):
    path=Path(path)
    try:s=path.lstat()
    except FileNotFoundError:return {'exists':False}
    result={'exists':True,'symlink':stat.S_ISLNK(s.st_mode),'regular':stat.S_ISREG(s.st_mode),
            'directory':stat.S_ISDIR(s.st_mode),'uid':s.st_uid,'gid':s.st_gid,'mode':oct(stat.S_IMODE(s.st_mode)),
            'bytes':s.st_size,'mtime_utc':dt.datetime.fromtimestamp(s.st_mtime,dt.timezone.utc).isoformat()}
    if hash_file:
        result['sha256']=hashlib.sha256(read(path)).hexdigest()
    return result

def command(args):
    value=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=False)
    if value.returncode:raise RuntimeError('command_failed:'+args[0]+':'+str(value.returncode))
    return value.stdout.decode()

def services():
    raw=command(['/usr/bin/systemctl','show',*UNITS,'--property=Id,User,Group,MainPID,ActiveState,SubState,ActiveEnterTimestampMonotonic,WorkingDirectory,MemoryCurrent'])
    return {entry['Id']:entry for entry in (dict(line.split('=',1) for line in block.splitlines() if '=' in line) for block in raw.strip().split('\n\n')) if 'Id' in entry}

def api(path,body=None):
    data=None if body is None else json.dumps(body).encode()
    request=urllib.request.Request('http://127.0.0.1:4200/api'+path,data=data,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=6) as response:
        raw=response.read(1_000_001)
    if len(raw)>1_000_000:raise ValueError('prefect_response_bound')
    return json.loads(raw)

def safe_run(run):
    return {**{k:run.get(k) for k in ['id','deployment_id','expected_start_time','start_time','end_time','updated']},
            'state':{k:(run.get('state') or {}).get(k) for k in ['type','name','timestamp']}}

def main():
    if ROOT.is_symlink() or not ROOT.is_dir():raise ValueError('repository_identity')
    head=read(ROOT/'.git/HEAD',256).decode().strip()
    if head.startswith('ref: '):
        ref=head[5:]
        if not re.fullmatch(r'refs/heads/[A-Za-z0-9_./-]+',ref) or '..' in ref:raise ValueError('unsafe_revision_ref')
        refpath=ROOT/'.git'/ref
        if refpath.exists():revision=read(refpath,128).decode().strip()
        else:
            matches=[line.split(' ',1)[0] for line in read(ROOT/'.git/packed-refs').decode().splitlines() if line.endswith(' '+ref)]
            if len(matches)!=1:raise ValueError('revision_unresolved')
            revision=matches[0]
    else:revision=head
    if not re.fullmatch('[0-9a-f]{40}',revision):raise ValueError('revision_invalid')
    OUT['revision']={'head':head,'commit':revision,'method':'read_HEAD_ref_only_no_git_command'}
    OUT['stage']='baselines';before=services();config_before={p:metadata(p,True)['sha256'] for p in BASELINES}
    OUT['services']=before
    OUT['stage']='files';OUT['code']={p:metadata(ROOT/p,True) for p in FILES}
    paths=['data','data/reports','data/reports/next24h_inference','src/models']
    OUT['directories']={p:metadata(ROOT/p) for p in paths}
    OUT['forecast_baselines']={p:metadata(ROOT/p,True) for p in ['data/reports/next24h_forecast.csv','data/reports/next24h_forecast_history.csv','data/reports/next24h_forecast_provenance.json']}
    OUT['database_metadata']=metadata(ROOT/'database/electricity_trading.db')
    OUT['source_sizes']={p:metadata(ROOT/('data/raw/entsoe/'+p+'.csv'))['bytes'] for p in ['prices','load','generation']}
    OUT['stage']='capacity';mem={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key,val=line.split(':',1)
        if key in ['MemTotal','MemAvailable','SwapTotal','SwapFree']:mem[key]=int(val.split()[0])*1024
    fs=os.statvfs(ROOT)
    OUT['capacity']={**mem,'swap_used_bytes':mem['SwapTotal']-mem['SwapFree'],'disk_available_bytes':fs.f_bavail*fs.f_frsize,'disk_total_bytes':fs.f_blocks*fs.f_frsize}
    OUT['stage']='python';OUT['python']=json.loads(command([str(ROOT/'.venv-prod/bin/python'),'-I','-B','-c',
        "import sys,json,importlib.metadata as m;print(json.dumps({'version':sys.version.split()[0],'packages':{p:m.version(p) for p in ['pandas','numpy','joblib','scikit-learn']}}))"]))
    OUT['stage']='prefect';dep=api('/deployments/'+DEP)
    if dep.get('id')!=DEP or dep.get('name')!='powerflow-entsoe-pipeline' or dep.get('entrypoint')!='src/scheduled_pipeline.py:powerflow_entsoe_pipeline':raise ValueError('deployment_identity')
    schedules=[{k:s.get(k) for k in ['id','active','schedule']} for s in dep.get('schedules',[])]
    limit=dep.get('global_concurrency_limit') or {}
    OUT['deployment']={'id':DEP,'paused':dep.get('paused'),'status':dep.get('status'),'schedules':schedules,
                       'concurrency':{k:limit.get(k) for k in ['limit','active','active_slots']},'collision_policy':dep.get('concurrency_options')}
    OUT['schedule_verified']=len(schedules)==1 and schedules[0]['active'] is True and schedules[0]['schedule']=={'cron':'45 * * * *','timezone':'UTC','day_or':True} and limit.get('limit')==1 and limit.get('active') is True and dep.get('paused') is False and dep.get('concurrency_options') is None
    base={'deployments':{'id':{'any_':[DEP]}}}
    active=api('/flow_runs/filter',{**base,'flow_runs':{'state':{'type':{'any_':['RUNNING','PENDING','CANCELLING','PAUSED']}}},'limit':20})
    queued=api('/flow_runs/filter',{**base,'flow_runs':{'state':{'type':{'any_':['SCHEDULED']}}},'sort':'EXPECTED_START_TIME_ASC','limit':4})
    recent=api('/flow_runs/filter',{**base,'sort':'EXPECTED_START_TIME_DESC','limit':3})
    if len(active)>=20:raise ValueError('active_run_bound')
    OUT['active_runs']=[safe_run(r) for r in active];OUT['queued_runs']=[safe_run(r) for r in queued];OUT['recent_runs']=[safe_run(r) for r in recent]
    now=dt.datetime.now(dt.timezone.utc);next_run=now.replace(minute=45,second=0,microsecond=0)
    if next_run<=now:next_run+=dt.timedelta(hours=1)
    OUT['observed_at_utc']=now.isoformat();OUT['next_cron_occurrence_utc']=next_run.isoformat()
    OUT['seconds_to_next_cron']=(next_run-now).total_seconds()
    OUT['stage']='preservation';OUT['services_unchanged']=before==services()
    OUT['routing_certificate_hashes_unchanged']=config_before=={p:metadata(p,True)['sha256'] for p in BASELINES}
    OUT['forecast_files_unchanged']={p:metadata(ROOT/p,True) for p in OUT['forecast_baselines']}==OUT['forecast_baselines']
    OUT['stage']='complete'

if __name__=='__main__':
    try:
        main();print(json.dumps(OUT));raise SystemExit(0)
    except Exception as error:
        OUT['errors'].append({'type':type(error).__name__,'stage':OUT['stage']})
        print(json.dumps(OUT));raise SystemExit(1)
