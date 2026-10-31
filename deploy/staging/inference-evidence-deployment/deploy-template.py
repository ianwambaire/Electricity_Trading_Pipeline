"""PROPOSED deployment only. Three code files; no forecasts, service changes or Git."""
import base64
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid
import urllib.request

# The generated reviewed script binds these constants and embedded code bytes.
CONFIG = __CONFIG__
ROOT=Path('/home/ec2-user/Electricity_Trading_Pipeline')
BACKUP=Path('/home/ec2-user/powerflow-inference-evidence-backup-20261031-v1')
RECEIPTS=ROOT/'data/reports/next24h_inference'
DEP='47e5ef51-26d0-44b6-b119-2c40d0e77397'
UNITS=['powerflow-api.service','powerflow-streamlit.service','powerflow-prefect-worker.service','powerflow-prefect-server.service','postgresql.service']
BASELINES=['/etc/nginx/conf.d/powerflow.conf','/etc/nginx/conf.d/powerflow-staging-https.conf','/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem']
FORECASTS=['data/reports/next24h_forecast.csv','data/reports/next24h_forecast_history.csv','data/reports/next24h_forecast_provenance.json']
RESULT={'stage':'preflight','installed':[],'automatic_rollback':False,'service_restart':False}

def require(condition,reason):
    if not condition:raise RuntimeError(reason)

def read(path):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NOATIME),'rb') as stream:raw=stream.read(2_000_001)
    require(len(raw)<=2_000_000,'file_read_bound');return raw

def digest(raw):return hashlib.sha256(raw).hexdigest()

def api(path,body=None):
    request=urllib.request.Request('http://127.0.0.1:4200/api'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=5) as response:raw=response.read(1_000_001)
    require(len(raw)<=1_000_000,'prefect_bound');return json.loads(raw)

def idle():
    d=api('/deployments/'+DEP);s=d.get('schedules',[]);g=d.get('global_concurrency_limit') or {}
    require(d.get('id')==DEP and d.get('name')=='powerflow-entsoe-pipeline' and d.get('entrypoint')=='src/scheduled_pipeline.py:powerflow_entsoe_pipeline' and d.get('paused') is False,'deployment_drift')
    require(len(s)==1 and s[0].get('id')=='9319f665-9836-4120-9801-031e23ad2b4a' and s[0].get('active') is True and s[0].get('schedule')=={'cron':'45 * * * *','timezone':'UTC','day_or':True},'schedule_drift')
    require(g.get('limit')==1 and g.get('active') is True and g.get('active_slots')==0 and d.get('concurrency_options') is None,'concurrency_not_idle')
    now=dt.datetime.now(dt.timezone.utc);next_time=now.replace(minute=45,second=0,microsecond=0)
    if next_time<=now:next_time+=dt.timedelta(hours=1)
    require((next_time-now).total_seconds()>=600,'schedule_window_under_ten_minutes')
    runs=api('/flow_runs/filter',{'deployments':{'id':{'any_':[DEP]}},'flow_runs':{'state':{'type':{'any_':['RUNNING','PENDING','CANCELLING','PAUSED']}}},'limit':20})
    require(not runs,'active_prefect_run')
    queued=api('/flow_runs/filter',{'deployments':{'id':{'any_':[DEP]}},'flow_runs':{'state':{'type':{'any_':['SCHEDULED']}},'expected_start_time':{'before_':(now+dt.timedelta(minutes=10)).isoformat()}},'limit':20})
    require(not queued,'imminent_queued_run')

def identities():
    r=subprocess.run(['/usr/bin/systemctl','show',*UNITS,'--property=Id,User,Group,MainPID,ActiveState,SubState,ActiveEnterTimestampMonotonic,WorkingDirectory'],capture_output=True,timeout=8)
    require(r.returncode==0,'service_inspection_failed')
    return r.stdout.decode()

def baselines():
    # Elevation is limited to hashing these exact public certificate/config paths.
    result=subprocess.run(['/usr/bin/sudo','-n','/usr/bin/sha256sum',*BASELINES],capture_output=True,timeout=8)
    require(result.returncode==0,'baseline_hash_read_failed')
    lines=result.stdout.decode().splitlines();require(len(lines)==len(BASELINES),'baseline_count')
    values={}
    for line,name in zip(lines,BASELINES):
        value,path=line.split(None,1);require(path==name and len(value)==64,'baseline_identity');values[name]=value
    return values

def hashes_forecasts():return {name:digest(read(ROOT/name)) for name in FORECASTS}

def private_write(path,raw,mode):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.chmod(path,mode)

def replace_code(name,raw):
    idle()
    temporary=ROOT/'src/models'/('.evidence-'+uuid.uuid4().hex+'.tmp')
    private_write(temporary,raw,0o644)
    require(digest(read(temporary))==digest(raw),'temporary_code_hash')
    os.replace(temporary,ROOT/name);RESULT['installed'].append(name)
    fd=os.open(ROOT/'src/models',os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

def main(action):
    os.umask(0o077)
    require(action in ['apply','rollback'],'action')
    require(os.geteuid()==1000 and ROOT.resolve(strict=True)==ROOT,'identity_or_root')
    require(sys.version_info[:3]==(3,14,7),'python_patch_drift')
    for name,version in CONFIG['packages'].items():require(importlib.metadata.version(name)==version,'package_drift')
    require(read(ROOT/'.git/HEAD').decode().strip()=='ref: refs/heads/main','branch_drift')
    # Production's verified loose ref is required; do not invoke Git or guess alternatives.
    require(read(ROOT/'.git/refs/heads/main').decode().strip()==CONFIG['revision'],'revision_drift')
    for name,h in CONFIG['dependencies'].items():require(digest(read(ROOT/name))==h,'dependency_drift:'+name)
    idle()
    mem={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')}
    fs=os.statvfs(ROOT);require(mem['MemAvailable']>=768*1024**2 and fs.f_bavail*fs.f_frsize>=2*1024**3,'capacity')
    before_services=identities();before_config=baselines();before_forecasts=hashes_forecasts()
    if action=='apply':
        require(not os.path.lexists(BACKUP) and not os.path.lexists(RECEIPTS),'backup_or_receipt_conflict')
        for parent in [ROOT/'src',ROOT/'src/models',ROOT/'data',ROOT/'data/reports']:
            info=parent.lstat();require(stat.S_ISDIR(info.st_mode) and not parent.is_symlink() and info.st_uid==1000 and not info.st_mode&0o022,'parent_permissions')
        payload={name:base64.b64decode(item['base64'],validate=True) for name,item in CONFIG['files'].items()}
        for name,raw in payload.items():
            require(digest(raw)==CONFIG['files'][name]['sha256'],'payload_hash');compile(raw,name,'exec')
            expected=CONFIG['files'][name]['previous_sha256'];path=ROOT/name
            if expected is None:require(not os.path.lexists(path),'new_file_conflict')
            else:
                info=path.lstat();require(stat.S_ISREG(info.st_mode) and info.st_uid==1000 and stat.S_IMODE(info.st_mode)==0o644,'code_permissions')
                require(digest(read(path))==expected,'code_drift:'+name)
        RESULT['stage']='backups';BACKUP.mkdir(mode=0o700)
        for name,item in CONFIG['files'].items():
            if item['previous_sha256'] is not None:
                raw=read(ROOT/name);require(digest(raw)==item['previous_sha256'],'source_changed_before_backup')
                private_write(BACKUP/Path(name).name,raw,0o600)
                require(digest(read(BACKUP/Path(name).name))==item['previous_sha256'],'backup_readback')
        private_write(BACKUP/'deployment.json',json.dumps({'files':{name:{k:v for k,v in item.items() if k!='base64'} for name,item in CONFIG['files'].items()},'services':before_services,'configuration':before_config,'forecasts':before_forecasts},sort_keys=True).encode(),0o600)
        fd=os.open(BACKUP,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        RESULT['stage']='receipt_directory';RECEIPTS.mkdir(mode=0o700)
        fd=os.open(RECEIPTS.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        # Backward-compatible helper first; operational activation file LAST.
        RESULT['stage']='code_install'
        for name in ['src/models/inference_evidence.py','src/models/next24h.py','src/models/next24h_production.py']:replace_code(name,payload[name])
        for name,item in CONFIG['files'].items():require(digest(read(ROOT/name))==item['sha256'],'installed_hash')
    else:
        require(BACKUP.is_dir() and not BACKUP.is_symlink() and stat.S_IMODE(BACKUP.stat().st_mode)==0o700,'rollback_backup')
        for name,item in CONFIG['files'].items():require(digest(read(ROOT/name))==item['sha256'],'rollback_current_drift')
        old={}
        for name,item in CONFIG['files'].items():
            if item['previous_sha256'] is not None:
                raw=read(BACKUP/Path(name).name);require(digest(raw)==item['previous_sha256'],'rollback_hash');old[name]=raw
        RESULT['stage']='rollback'
        for name in ['src/models/next24h_production.py','src/models/next24h.py']:replace_code(name,old[name])
        # Never delete receipts/backups/helper, and never roll back historical output.
    RESULT['stage']='preservation'
    RESULT['services_preserved']=before_services==identities();require(RESULT['services_preserved'],'service_identity_changed')
    RESULT['routing_certificates_preserved']=before_config==baselines();require(RESULT['routing_certificates_preserved'],'routing_certificate_changed')
    RESULT['forecasts_preserved']=before_forecasts==hashes_forecasts();require(RESULT['forecasts_preserved'],'forecast_changed_during_idle_install')
    RESULT['stage']='complete';RESULT['status']='CAPTURE_CODE_INSTALLED' if action=='apply' else 'CODE_ROLLED_BACK'
    RESULT['live_receipt_verification']='pending_normal_scheduled_run'

if __name__=='__main__':
    try:
        require(len(sys.argv)==2,'one_action_required');main(sys.argv[1]);print(json.dumps(RESULT))
    except Exception as error:
        RESULT['status']='STOPPED';RESULT['error_type']=type(error).__name__;RESULT['reason']=str(error) if isinstance(error,RuntimeError) else 'unexpected_error_raw_details_withheld'
        print(json.dumps(RESULT));raise SystemExit(1)
