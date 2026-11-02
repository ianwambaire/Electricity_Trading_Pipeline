"""One-file parser hotfix; BASE/CONFIG/ACTION are injected from verified bytes."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat

ROOT=Path('/home/ec2-user/Electricity_Trading_Pipeline')
TARGET=ROOT/'src/ingestion/fetch_entsoe_data.py'
PARENT=Path('/var/lib/powerflow-staging/a03-parser-hotfix')
OLD='ee1d225895fbf929127a577ca4f85a6855643186a7590cda5eaa27ac6aa21a2a'
NEW='8800f34a2d0e3db4056e921a7b6629847402f37c20ff9b3e81d50f3c1d77865f'
PHASE='PREFLIGHT'
CHANGED=False
MUTATION=False
class Stop(ValueError):pass

def need(value,code):
    if not value:raise Stop(code)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path,limit=64000000):return BASE['read'](path,limit)
def digest(path):return sha(read(path))
def info(path):
    s=path.lstat()
    return {'uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode),'regular':stat.S_ISREG(s.st_mode)}
def safe(path,owners=(0,)):
    for p in (path,)+tuple(path.parents):
        s=p.lstat();need(not stat.S_ISLNK(s.st_mode) and s.st_uid in owners and not s.st_mode&0o022,'UNSAFE_PATH')
def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
def create(path,raw,mode=0o600,uid=0,gid=0):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode),'wb') as f:
        os.fchmod(f.fileno(),mode);os.fchown(f.fileno(),uid,gid);f.write(raw);f.flush();os.fsync(f.fileno())
    sync(path.parent);need(digest(path)==sha(raw),'WRITE_VERIFICATION')
def record_write(control,record):
    temporary=control/'.state-next'
    create(temporary,json.dumps(record,sort_keys=True).encode());os.replace(temporary,control/'state.json');sync(control)
def preserve():
    units=BASE['services']()
    need(all(u.get('ActiveState')=='active' and u.get('SubState')=='running' for u in units.values()),'SERVICE_STATE')
    result={'existing':BASE['fingerprints'](units)}
    paths=['database/electricity_trading.db','data/raw/entsoe/prices.csv','data/raw/entsoe/load.csv','data/raw/entsoe/generation.csv',
      'data/raw/weather/open_meteo_weather.csv','data/processed/silver_electricity_market_data.csv','data/features/gold_model_features.csv',
      'data/reports/next24h_forecast.csv','data/reports/next24h_forecast_history.csv','data/reports/next24h_forecast_provenance.json',
      'artifacts/models/releases/next24h/next24h_model.joblib','artifacts/models/releases/next24h/next24h_feature_contract.joblib']
    for path in paths:result[path]=digest(ROOT/path)
    need(result['artifacts/models/releases/next24h/next24h_model.joblib']=='69a3fa10f45c18c4733b3f8e12792e36ec9b209b7afd5e94a9932315e4dde0ed','MODEL_HASH')
    need(result['artifacts/models/releases/next24h/next24h_feature_contract.joblib']=='1d6554e469a869613dd91d820b0537b4562321ea69e8827ecb83137950078a88','MODEL_HASH')
    return sha(json.dumps(result,sort_keys=True).encode())
def resources():
    values={line.split(':')[0]:int(line.split()[1])*1024 for line in read('/proc/meminfo').decode().splitlines() if line.startswith(('MemAvailable:','SwapTotal:','SwapFree:'))}
    need(values['MemAvailable']>=768*1024**2,'RAM_GATE')
    free=min(os.statvfs(p).f_bavail*os.statvfs(p).f_frsize for p in (ROOT,PARENT.parent))
    need(free>=2*1024**3+2*len(CONFIG['source']),'DISK_GATE')
    return {'available_bytes':values['MemAvailable'],'swap_used_bytes':values['SwapTotal']-values['SwapFree'],'disk_available_bytes':free}
def idle():
    _,ok=BASE['pipeline']();need(ok,'PIPELINE_OR_WINDOW_GATE')
def identity():
    need(os.geteuid()==0,'ROOT_REQUIRED')
    tx=CONFIG['transaction_id'];need(type(tx)is str and re.fullmatch('[0-9a-f]{32}',tx) is not None,'TRANSACTION_ID')
    need(type(CONFIG['source'])is bytes and sha(CONFIG['source'])==NEW,'SOURCE_HASH')
    ast.parse(CONFIG['source'],feature_version=(3,9));compile(CONFIG['source'],'<verified-parser>','exec')
    safe(TARGET,owners=(0,1000));need(info(TARGET)=={'uid':1000,'gid':1000,'mode':0o644,'regular':True},'SOURCE_METADATA')
    return PARENT/tx
def baseline():
    # No source install while a flow/importing engine is active; never pause a producer.
    idle();value=resources();return value,preserve()
def replace_source(raw,expected_current):
    global MUTATION
    temporary=TARGET.parent/('.powerflow-a03-parser-'+CONFIG['transaction_id'])
    create(temporary,raw,0o644,1000,1000)
    need(digest(TARGET)==expected_current and info(TARGET)=={'uid':1000,'gid':1000,'mode':0o644,'regular':True},'SOURCE_DRIFT_AT_REPLACE')
    MUTATION=True # After this point failure/timeout cannot assert original source is intact.
    os.replace(temporary,TARGET);sync(TARGET.parent)
    need(digest(TARGET)==sha(raw) and info(TARGET)=={'uid':1000,'gid':1000,'mode':0o644,'regular':True},'INSTALLED_VERIFY')
def apply():
    global PHASE,CHANGED
    control=identity();need(digest(TARGET)==OLD,'PRODUCTION_BASELINE_DRIFT')
    need(not os.path.lexists(control),'TRANSACTION_COLLISION')
    if os.path.lexists(PARENT):safe(PARENT);need(info(PARENT)['gid']==0 and info(PARENT)['mode']==0o700,'BACKUP_PARENT_MODE')
    else:safe(PARENT.parent)
    before_resources,before=baseline();original=read(TARGET);need(sha(original)==OLD,'PRODUCTION_BASELINE_DRIFT')
    record={'version':1,'transaction_id':CONFIG['transaction_id'],'old_sha256':OLD,'new_sha256':NEW,'production_fingerprint':before,'phase':'BACKUP_VERIFIED'}
    CHANGED=True;PHASE='BACKUPS'
    if not PARENT.exists():PARENT.mkdir(mode=0o700);os.chmod(PARENT,0o700);os.chown(PARENT,0,0);sync(PARENT.parent)
    control.mkdir(mode=0o700);os.chmod(control,0o700);os.chown(control,0,0);sync(PARENT)
    create(control/'original.py',original);record_write(control,record)
    need(digest(control/'original.py')==OLD and json.loads(read(control/'state.json'))==record,'BACKUP_VERIFY')
    for name in ('original.py','state.json'):need(info(control/name)=={'uid':0,'gid':0,'mode':0o600,'regular':True},'BACKUP_METADATA')
    need(info(control)['mode']==0o700 and info(control)['uid']==info(control)['gid']==0,'BACKUP_METADATA')
    # Recheck every guard immediately before the atomic install, after backup I/O.
    need(digest(TARGET)==OLD,'PRODUCTION_BASELINE_DRIFT');identity();baseline_now,current=baseline();need(current==before,'PRODUCTION_DRIFT')
    PHASE='INSTALL';record['phase']='INSTALLING';record_write(control,record)
    idle();need(preserve()==before,'PRODUCTION_DRIFT');resources();need(digest(TARGET)==OLD,'PRODUCTION_BASELINE_DRIFT')
    replace_source(CONFIG['source'],OLD)
    PHASE='VERIFY';ast.parse(read(TARGET),feature_version=(3,9));compile(read(TARGET),'<installed-parser>','exec')
    need(digest(control/'original.py')==OLD,'BACKUP_VERIFY');need(preserve()==before,'PRODUCTION_DRIFT');idle();after=resources()
    record['phase']='APPLIED';record_write(control,record);PHASE='COMPLETE'
    return {'status':'APPLIED','phase':PHASE,'parser_hash_verified':True,'backup_verified':True,'production_preserved':True,'no_services_restarted':True,'resources':after}
def rollback():
    global PHASE,CHANGED
    control=identity();safe(control);need(info(control)['mode']==0o700,'BACKUP_PARENT_MODE')
    for name in ('state.json','original.py'):
        need(info(control/name)=={'uid':0,'gid':0,'mode':0o600,'regular':True},'BACKUP_METADATA')
    record=json.loads(read(control/'state.json',4096))
    need(set(record)=={'version','transaction_id','old_sha256','new_sha256','production_fingerprint','phase'} and record['version']==1 and record['transaction_id']==CONFIG['transaction_id'] and record['old_sha256']==OLD and record['new_sha256']==NEW and record['phase'] in ('INSTALLING','APPLIED'),'ROLLBACK_RECORD')
    original=read(control/'original.py');need(sha(original)==OLD,'BACKUP_VERIFY');need(digest(TARGET)==NEW,'ROLLBACK_SOURCE_DRIFT')
    _,current=baseline();need(current==record['production_fingerprint'],'PRODUCTION_DRIFT')
    PHASE='ROLLBACK';CHANGED=True;replace_source(original,NEW)
    need(preserve()==record['production_fingerprint'],'PRODUCTION_DRIFT');need(digest(TARGET)==OLD,'ROLLBACK_VERIFY');after=resources()
    record['phase']='ROLLED_BACK';record_write(control,record);PHASE='ROLLED_BACK'
    return {'status':'ROLLED_BACK','phase':PHASE,'parser_hash_verified':True,'backup_verified':True,'production_preserved':True,'no_services_restarted':True,'resources':after}
if __name__=='__main__':
    try:
        need(ACTION in ('apply','rollback'),'ACTION_SCOPE');print(json.dumps(apply() if ACTION=='apply' else rollback(),sort_keys=True))
    except Exception as error:
        reason=str(error) if type(error)is Stop else 'PERMISSION_DENIED' if isinstance(error,PermissionError) else 'MISSING_FILE' if isinstance(error,FileNotFoundError) else 'UNEXPECTED_EXCEPTION'
        print(json.dumps({'status':'PARTIAL' if CHANGED else 'BLOCKED','phase':PHASE,'reason':reason,'source_may_have_changed':MUTATION,'automatic_rollback':False},sort_keys=True));raise SystemExit(1)
