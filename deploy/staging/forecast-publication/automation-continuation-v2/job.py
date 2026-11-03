"""Guarded automation install/config activation; no inference or service restart.
BASE, GUARD, CONFIG, ACTION are compiled from retained manifest-bound bytes.
"""
import base64
import copy
import hashlib
import json
import os
import pwd
from pathlib import Path
import re
import stat
import urllib.request

PRODUCTION=Path('/home/ec2-user/Electricity_Trading_Pipeline')
TOOLS=Path('/opt/powerflow/forecast-publication-automation')
LAUNCHER=Path('/usr/local/sbin/powerflow-publish-next24')
RULE=Path('/etc/sudoers.d/powerflow-publish-next24')
CONTROL=Path('/var/lib/powerflow-staging')/('publication-automation-'+CONFIG['transaction'])
FLAG='POWERFLOW_AUTO_PUBLICATION_ENABLED'
DEP='47e5ef51-26d0-44b6-b119-2c40d0e77397'
CHANGED=False
PHASE='PREFLIGHT'
class Stop(ValueError):pass
def need(x,code):
    if not x:raise Stop(code)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(p):return BASE['read'](p,200000)
def safe(p,owners=(0,)):
    for n in (p,)+tuple(p.parents):
        s=n.lstat();need(not stat.S_ISLNK(s.st_mode) and s.st_uid in owners and not s.st_mode&0o022,'UNSAFE_PATH')
def fsync(p):
    fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
def write(p,raw,mode=0o600,owner=0,group=0,exclusive=False):
    safe(p.parent,(0,1000) if str(p).startswith(str(PRODUCTION)+'/') else (0,))
    fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    temp='.automation-'+CONFIG['transaction']+'-'+p.name
    try:
        if exclusive:need(not os.path.lexists(p),'PATH_CONFLICT')
        with os.fdopen(os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode,dir_fd=fd),'wb') as f:
            os.fchmod(f.fileno(),mode);os.fchown(f.fileno(),owner,group);f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temp,p.name,src_dir_fd=fd,dst_dir_fd=fd);os.fsync(fd)
    finally:os.close(fd)
    need(read(p)==raw,'WRITE_VERIFY')
def create_dir(p):
    global CHANGED
    safe(p.parent);p.mkdir(mode=0o700);CHANGED=True;os.chmod(p,0o700);fsync(p.parent)
def process(argv,input=b'',code='COMMAND_FAILED'):
    r=BASE['bounded_run'](argv,input=input,timeout=8,limit=16384,grace=5)
    need(r['returncode']==0 and r['failure'] is None,code);return r['stdout']
def deployment():return BASE['api']('/deployments/'+DEP)
def pool_metadata():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*a,**kw):raise Stop('REDIRECT')
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with op.open('http://127.0.0.1:4200/api/work_pools/electricity-pool',timeout=5) as response:
        raw=response.read(100001);need(len(raw)<=100000,'POOL_RESPONSE_BOUND');return json.loads(raw)

def project(d):
    return {**{k:d.get(k) for k in ['id','name','entrypoint','path','paused','parameters','work_pool_name','work_queue_name','concurrency_options','tags','description','version','version_info','storage_document_id','infrastructure_document_id','enforce_parameter_schema','pull_steps']},'schedules':[{k:s.get(k) for k in ['id','active','schedule']} for s in d.get('schedules',[])],'concurrency':{k:(d.get('global_concurrency_limit') or {}).get(k) for k in ['limit','active']}}
def variables(d):
    old=copy.deepcopy(d.get('job_variables') or {});need(type(old)is dict,'JOB_VARIABLES_SHAPE')
    env=old.get('env',{});need(type(env)is dict and all(type(k)is str and type(v)is str for k,v in env.items()),'ENV_SHAPE')
    need(FLAG not in env,'ACTIVATION_DRIFT')
    new=copy.deepcopy(old);new.setdefault('env',{})[FLAG]='true';return old,new

def patch(value):
    # Only this field on this exact existing deployment; no retry/redirect/proxy.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*a,**kw):raise Stop('REDIRECT')
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    req=urllib.request.Request('http://127.0.0.1:4200/api/deployments/'+DEP,data=json.dumps({'job_variables':value}).encode(),headers={'Content-Type':'application/json'},method='PATCH')
    with op.open(req,timeout=5) as response:need(response.status in (200,204) and len(response.read(1001))<=1000,'PATCH_RESPONSE')

def snapshot(p):
    if not os.path.lexists(p):return None
    safe(p,(0,1000));s=p.lstat();need(stat.S_ISREG(s.st_mode),'FILE_TYPE')
    raw=read(p);return {'raw':base64.b64encode(raw).decode(),'sha256':sha(raw),'uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode)}
def payloads():
    result={}
    for name,item in CONFIG['files'].items():
        raw=base64.b64decode(item['base64'],validate=True);need(len(raw)==item['bytes'] and sha(raw)==item['sha256'],'INPUT_HASH');result[name]=raw
    return result

def frozen():
    for name,expected in [('next24h_model.joblib','69a3fa10f45c18c4733b3f8e12792e36ec9b209b7afd5e94a9932315e4dde0ed'),('next24h_feature_contract.joblib','1d6554e469a869613dd91d820b0537b4562321ea69e8827ecb83137950078a88')]:
        p=PRODUCTION/'artifacts/models/releases/next24h'/name;safe(p,(0,1000))
        need(sha(BASE['read'](p,64000000))==expected,'FROZEN_RELEASE_DRIFT')

def fresh():
    resources=step('CHECK_CAPACITY_AND_WINDOW','HOST_CAPACITY',GUARD['idle_capacity'],1000000)
    step('CHECK_FROZEN_FILES','FROZEN_RELEASE',frozen)
    need(os.getuid()==os.geteuid()==0,'ROOT_REQUIRED')
    backend=step('RESOLVE_BACKEND','BACKEND_POINTER',Path('/opt/powerflow/react-current').resolve,strict=True)
    need(backend==Path('/opt/powerflow/releases/phase-api-body-bound-20261102-v2'),'STAGING_POINTER_DRIFT')
    need(step('RESOLVE_STATIC','STATIC_POINTER',Path('/var/www/powerflow-staging/current').resolve,strict=True)==Path('/var/www/powerflow-staging/releases/phase-api-body-bound-20261102-v2'),'STATIC_POINTER_DRIFT')
    step('CHECK_CANDIDATE_RUNTIME','CANDIDATE_RUNTIME',GUARD['runtime'],backend)
    global OPERATION,PATH_ID
    OPERATION='CHECK_HTTP_HEALTH';PATH_ID='HTTP_HEALTH'
    need(BASE['request'](8010,'/health')[0]==200 and BASE['request'](8010,'/ready')[0]==200,'CANDIDATE_HEALTH')
    need(BASE['request'](443,'/',tls=True)[0]==200 and BASE['request'](8000,'/health')[0]==200 and BASE['request'](8501,'/_stcore/health')[0]==200,'SITE_HEALTH')
    return step('CHECK_PRODUCTION_PRESERVATION','PRODUCTION_BASELINE',GUARD['production']),resources

def system_binaries():
    for binary in ['/usr/bin/sudo','/usr/sbin/visudo','/usr/bin/env','/usr/bin/timeout','/usr/bin/python3','/bin/sh']:
        p=Path(binary).resolve(strict=True);safe(p);need(stat.S_ISREG(p.stat().st_mode),'SYSTEM_BINARY')

def original_tools():
    expected={'prepare.py','publish.py','shared/__init__.py','shared/forecast_publication.py','tools-manifest.json'}
    need(type(CONFIG.get('original_tools'))is dict and set(CONFIG['original_tools'])==expected and all(type(v)is str and re.fullmatch('[0-9a-f]{64}',v) for v in CONFIG['original_tools'].values()),'ORIGINAL_TOOLS_CONFIG_SCOPE')
    root=Path('/opt/powerflow/forecast-publication-tools')/CONFIG['original_packet']
    for folder in [root.parent,root,root/'shared']:
        safe(folder);s=folder.stat();need(s.st_uid==s.st_gid==0 and stat.S_IMODE(s.st_mode)==0o700,'ORIGINAL_TOOLS_DIRECTORY')
    for rel,hash_ in CONFIG['original_tools'].items():
        p=root/rel;safe(p);s=p.stat();need(s.st_uid==s.st_gid==0 and stat.S_IMODE(s.st_mode)==0o600 and sha(read(p))==hash_,'ORIGINAL_TOOLS_DRIFT')
    for p in [Path('/srv/powerflow/forecast-publications'),Path('/srv/powerflow/forecast-publications/releases')]:
        safe(p);s=p.stat();need(s.st_gid==992 and stat.S_IMODE(s.st_mode)==0o750,'PUBLICATION_PERMISSIONS')

# New continuation-only directory and diagnostic helpers.
ROOT_UID=ROOT_GID=0
PRODUCER_UID=PRODUCER_GID=1000
OPERATION='PREFLIGHT'
PATH_ID='NONE'

def step(operation,path_id,function,*args,**kwargs):
    global OPERATION,PATH_ID
    OPERATION=operation;PATH_ID=path_id
    return function(*args,**kwargs)

def directory_info(path):
    if not os.path.lexists(path):return None
    safe(path,(0,1000));s=path.lstat();need(stat.S_ISDIR(s.st_mode),'DIRECTORY_TYPE')
    return {'dev':s.st_dev,'ino':s.st_ino,'uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode)}

def check_shared():
    src=directory_info(PRODUCTION/'src')
    need(src is not None and (src['uid'],src['gid'],src['mode'])==(PRODUCER_UID,PRODUCER_GID,0o755),'SRC_DIRECTORY_METADATA')
    shared=directory_info(PRODUCTION/'src/shared')
    if shared is not None:need((shared['uid'],shared['gid'],shared['mode'])==(PRODUCER_UID,PRODUCER_GID,0o755),'SHARED_DIRECTORY_METADATA')
    return src,shared

def save(record):
    step('SAVE_RECORD','TRANSACTION_RECORD',write,CONTROL/'record.json',json.dumps(record,sort_keys=True).encode())
    need(json.loads(read(CONTROL/'record.json'))==record,'RECORD_VERIFY')

def create_shared(record):
    global OPERATION,PATH_ID
    src,shared=check_shared();need(src==record['src_directory'] and shared==record['shared_before'],'DIRECTORY_DRIFT')
    if shared is not None:return
    record['shared_intent']='CREATE';save(record)
    OPERATION='CREATE_SHARED';PATH_ID='PRODUCTION_SHARED'
    fd=os.open(PRODUCTION/'src',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    child=None
    try:
        info=os.fstat(fd);need((info.st_dev,info.st_ino)==(src['dev'],src['ino']),'SRC_DIRECTORY_DRIFT')
        os.mkdir('shared',0o700,dir_fd=fd)
        child=os.open('shared',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
        info=os.fstat(child)
        initial={'dev':info.st_dev,'ino':info.st_ino,'uid':info.st_uid,'gid':info.st_gid,'mode':stat.S_IMODE(info.st_mode)}
        record['shared_created']={'identity':{'dev':info.st_dev,'ino':info.st_ino},'allowed_metadata':[[initial['uid'],initial['gid'],initial['mode']],[PRODUCER_UID,PRODUCER_GID,initial['mode']],[PRODUCER_UID,PRODUCER_GID,0o755]]}
        os.fsync(child);os.fsync(fd);save(record)
        OPERATION='SET_SHARED_METADATA';PATH_ID='PRODUCTION_SHARED'
        os.fchown(child,PRODUCER_UID,PRODUCER_GID);os.fchmod(child,0o755);os.fsync(child);os.fsync(fd)
        current=directory_info(PRODUCTION/'src/shared')
        need(current==dict(record['shared_created']['identity'],uid=PRODUCER_UID,gid=PRODUCER_GID,mode=0o755),'SHARED_CREATION_VERIFY')
        record['shared_creation_complete']=True;save(record)
    finally:
        if child is not None:os.close(child)
        os.close(fd)

def retained_tools():
    expected={name:hash_ for name,hash_ in CONFIG['installed_tools'].items()}
    expected['automation-manifest.json']=sha(json.dumps(CONFIG['installed_tools'],sort_keys=True).encode())
    found=set();count=0
    for relative,p in [('',TOOLS),('shared/',TOOLS/'shared')]:
        safe(p);s=p.lstat()
        need(stat.S_ISDIR(s.st_mode) and s.st_uid==ROOT_UID and s.st_gid==ROOT_GID and stat.S_IMODE(s.st_mode)==0o700,'RETAINED_DIRECTORY_METADATA')
        with os.scandir(p) as entries:
            for entry in entries:
                count+=1;need(count<=8,'RETAINED_INVENTORY_BOUND')
                rel=relative+entry.name;info=entry.stat(follow_symlinks=False)
                if rel=='shared':
                    need(stat.S_ISDIR(info.st_mode),'RETAINED_DIRECTORY_TYPE');continue
                need(rel in expected,'RETAINED_INVENTORY')
                need(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==ROOT_UID and info.st_gid==ROOT_GID and stat.S_IMODE(info.st_mode)==0o600,'RETAINED_FILE_METADATA')
                need(sha(read(p/entry.name))==expected[rel],'RETAINED_FILE_HASH');found.add(rel)
    need(found==set(expected),'RETAINED_INVENTORY')


def original_transaction(deployment_value):
    old_control=Path('/var/lib/powerflow-staging')/('publication-automation-'+CONFIG['original_transaction'])
    safe(old_control);info=old_control.lstat();need(stat.S_ISDIR(info.st_mode) and info.st_uid==info.st_gid==0 and stat.S_IMODE(info.st_mode)==0o700,'ORIGINAL_TRANSACTION_METADATA')
    p=old_control/'record.json';safe(p);info=p.lstat();need(stat.S_ISREG(info.st_mode) and info.st_uid==info.st_gid==0 and stat.S_IMODE(info.st_mode)==0o600,'ORIGINAL_RECORD_METADATA')
    old=json.loads(read(p));need(old.get('version')==1 and old.get('transaction')==CONFIG['original_transaction'] and old.get('status')=='ROLLED_BACK','ORIGINAL_TRANSACTION_STATE')
    need(old['pipeline']['sha256']==CONFIG['pipeline_before'] and sha(base64.b64decode(old['pipeline']['raw'],validate=True))==CONFIG['pipeline_before'],'ORIGINAL_BACKUP_HASH')
    need((deployment_value.get('job_variables') or {})==old['old_variables'],'ORIGINAL_ENV_DRIFT')

def check_rollback_directory(record):
    need(directory_info(PRODUCTION/'src')==record['src_directory'],'SRC_DIRECTORY_DRIFT')
    current=directory_info(PRODUCTION/'src/shared');before=record['shared_before'];created=record.get('shared_created')
    if before is not None:need(current==before,'SHARED_DIRECTORY_DRIFT')
    elif created is not None:
        allowed=[[PRODUCER_UID,PRODUCER_GID,0o755]] if record.get('shared_creation_complete') else created['allowed_metadata']
        need(current is not None and {k:current[k] for k in ['dev','ino']}==created['identity'] and [current['uid'],current['gid'],current['mode']] in allowed,'SHARED_DIRECTORY_DRIFT')
    else:need(current is None,'UNRECORDED_SHARED_DIRECTORY')

def remove_file(path):
    path.unlink();fsync(path.parent)

def remove_shared(record):
    check_rollback_directory(record)
    if record['shared_before'] is not None:return 'PRESERVED_PREEXISTING'
    if record.get('shared_created') is None:return 'NOT_CREATED'
    path=PRODUCTION/'src/shared'
    if any(path.iterdir()):return 'RETAINED_NONEMPTY'
    check_rollback_directory(record)
    fd=os.open(PRODUCTION/'src',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd);need((info.st_dev,info.st_ino)==(record['src_directory']['dev'],record['src_directory']['ino']),'SRC_DIRECTORY_DRIFT')
        os.rmdir('shared',dir_fd=fd);os.fsync(fd)
    finally:os.close(fd)
    need(not os.path.lexists(path),'DIRECTORY_REMOVE_VERIFY');return 'REMOVED_EMPTY_CREATED'

def approved_paths():
    table={
        '/proc/self/mountinfo':'PROC_MOUNTINFO','/proc/meminfo':'PROC_MEMORY',
        '/proc/net/tcp':'PROC_TCP','/proc/net/tcp6':'PROC_TCP6',
        '/opt/powerflow':'CAPACITY_OPT','/var/www/powerflow-staging':'CAPACITY_WEB','/var/lib':'CAPACITY_STATE',
        '/opt/powerflow/react-current':'BACKEND_POINTER','/var/www/powerflow-staging/current':'STATIC_POINTER',
        '/opt/powerflow/releases/phase-api-body-bound-20261102-v2':'BACKEND_RELEASE',
        '/var/www/powerflow-staging/releases/phase-api-body-bound-20261102-v2':'STATIC_RELEASE',
        '/etc/nginx/conf.d/powerflow.conf':'PRODUCTION_ROUTING',
        '/etc/nginx/conf.d/powerflow-staging-https.conf':'STAGING_ROUTING',
        '/etc/nginx/conf.d/powerflow-staging-acme.conf':'STAGING_ACME_CONFIG',
        '/etc/systemd/system/powerflow-candidate-api.service':'CANDIDATE_UNIT',
        '/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem':'PRODUCTION_PUBLIC_CHAIN',
        '/etc/ssl/certs/ca-certificates.crt':'SYSTEM_CA_BUNDLE',
        '/etc/pki/tls/certs/ca-bundle.crt':'SYSTEM_CA_BUNDLE_RHEL',
        '/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem':'SYSTEM_CA_EXTRACTED',
    }
    for name,label in [('next24h_model.joblib','FROZEN_MODEL'),('next24h_feature_contract.joblib','FROZEN_CONTRACT')]:table[str(PRODUCTION/'artifacts/models/releases/next24h'/name)]=label
    for name,label in [('src/ingestion/fetch_entsoe_data.py','PRODUCTION_PARSER'),('src/scheduled_pipeline.py','PIPELINE_SOURCE'),('.venv-prod/lib/python3.14/site-packages/prefect/workers/base.py','PREFECT_WORKER_SOURCE'),('data/reports/next24h_forecast.csv','PRODUCTION_FORECAST'),('data/reports/next24h_forecast_provenance.json','PRODUCTION_PROVENANCE'),('artifacts/models/releases/next24h/next24h_release_manifest.json','PRODUCTION_MODEL_MANIFEST')]:table[str(PRODUCTION/name)]=label
    published=['data/processed/silver_electricity_market_data.csv','data/features/gold_model_features.csv','data/raw/entsoe/prices.csv','data/raw/entsoe/load.csv','data/raw/entsoe/generation.csv','data/raw/weather/open_meteo_weather.csv','data/reports/actual_vs_predicted.csv','data/reports/detected_anomalies.csv','data/reports/final_holdout_metrics.csv','data/reports/feature_importance.csv','artifacts/models/final_model_release_manifest.json','artifacts/models/releases/next24h/next24h_release_manifest.json','database/electricity_trading.db']
    for i,name in enumerate(published):table[str(Path('/srv/powerflow/published')/name)]='PUBLISHED_SNAPSHOT_%02d'%i
    old=Path('/opt/powerflow/forecast-publication-tools')/CONFIG['original_packet']
    table[str(old)]='ORIGINAL_TOOLS_DIRECTORY'
    for name,label in [('prepare.py','ORIGINAL_TOOL_PREPARE'),('publish.py','ORIGINAL_TOOL_PUBLISH'),('shared/__init__.py','ORIGINAL_TOOL_INIT'),('shared/forecast_publication.py','ORIGINAL_TOOL_CONTRACT'),('tools-manifest.json','ORIGINAL_TOOL_MANIFEST')]:table[str(old/name)]=label
    for path,label in [(PRODUCTION/'src','PRODUCTION_SRC'),(PRODUCTION/'src/shared','PRODUCTION_SHARED'),(TOOLS,'RETAINED_TOOLS'),(CONTROL,'TRANSACTION'),(LAUNCHER,'LAUNCHER'),(RULE,'SUDOERS_RULE'),(Path('/srv/powerflow/forecast-publications'),'PUBLICATION_ROOT'),(Path('/srv/powerflow/forecast-publications/releases'),'PUBLICATION_RELEASES')]:table[str(path)]=label
    old_control=Path('/var/lib/powerflow-staging')/('publication-automation-'+CONFIG['original_transaction'])
    table[str(old_control)]='ORIGINAL_TRANSACTION';table[str(old_control/'record.json')]='ORIGINAL_TRANSACTION_RECORD'
    table[str(CONTROL/'record.json')]='TRANSACTION_RECORD';table[str(PRODUCTION/'src/shared/forecast_delivery.py')]='DELIVERY_MODULE'
    for name in ['systemctl','sudo','env','timeout','python3']:table['/usr/bin/'+name]='SYSTEM_'+name.upper()
    table['/usr/sbin/visudo']='SYSTEM_VISUDO';table['/bin/sh']='SYSTEM_SHELL'
    cg='/sys/fs/cgroup/system.slice/powerflow-candidate-api.service'
    table[cg]='CANDIDATE_CGROUP'
    for name in ['memory.high','memory.max','memory.swap.max','memory.swap.current']:table[cg+'/'+name]='CGROUP_'+name.upper().replace('.','_')
    # All derived ancestors are from this fixed approved table, never from an error.
    for target,label in list(table.items()):
        for depth,parent in enumerate(Path(target).parents,1):table.setdefault(str(parent),'PARENT_'+label+'_%d'%depth)
    return table

def missing_path_id(error):
    value=getattr(error,'filename',None)
    if not isinstance(value,str) or not value.startswith('/') or any(p in ('.','..') for p in value.split('/')):return 'UNMAPPED_REQUIRED_PATH'
    exact=approved_paths().get(value)
    if exact:return exact
    match=re.fullmatch(r'/proc/[0-9]+/(status|cmdline|cwd|fd)(?:/[0-9]+)?',value)
    if match:return 'CANDIDATE_PROC_'+match.group(1).upper()
    if re.fullmatch(r'/etc/letsencrypt/archive/powerflowenergy\.dev/fullchain[0-9]+\.pem',value):return 'PRODUCTION_PUBLIC_CHAIN_ARCHIVE'
    if re.fullmatch(r'/usr/bin/python3(?:\.[0-9]+)+',value):return 'SYSTEM_PYTHON_TARGET'
    return 'UNMAPPED_REQUIRED_PATH'

def failure(error):
    import traceback
    category='GUARD_FAILED' if type(error) in (Stop,GUARD.get('Stop',Stop)) else 'MISSING_PATH' if isinstance(error,FileNotFoundError) else 'PERMISSION_DENIED' if isinstance(error,PermissionError) else 'PATH_CONFLICT' if isinstance(error,FileExistsError) else 'OS_ERROR' if isinstance(error,OSError) else 'VALIDATION_ERROR'
    info={'error_category':category,'operation':OPERATION,'path_id':missing_path_id(error) if isinstance(error,FileNotFoundError) else PATH_ID,'errno':getattr(error,'errno',None)}
    try:
        if CHANGED and CONTROL.is_dir() and not CONTROL.is_symlink():
            private={'phase':PHASE,**info,'exception_type':type(error).__name__,'traceback':''.join(traceback.format_exception(type(error),error,error.__traceback__))[-16000:]}
            action='rollback' if globals().get('ACTION')=='rollback' else 'apply'
            name='failure-'+action+'-'+os.urandom(8).hex()+'.private.json'
            write(CONTROL/name,json.dumps(private,sort_keys=True).encode(),exclusive=True)
    except Exception:pass
    return info


def apply():
    global CHANGED,PHASE
    files=payloads();before,resources=step('CHECK_HOST','HOST',fresh);step('VERIFY_ORIGINAL_TOOLS','ORIGINAL_TOOLS',original_tools)
    step('VERIFY_RETAINED_TOOLS','RETAINED_TOOLS',retained_tools)
    src_directory,shared_before=step('CHECK_SHARED_DIRECTORY','PRODUCTION_SHARED',check_shared)
    step('CHECK_SYSTEM_BINARIES','SYSTEM_BINARIES',system_binaries)
    need(pwd.getpwnam('ec2-user').pw_uid==pwd.getpwnam('ec2-user').pw_gid==1000,'PUBLISHER_IDENTITY')
    worker=BASE['services']()['powerflow-prefect-worker.service']
    need(worker.get('User')==worker.get('Group')=='ec2-user' and worker.get('NoNewPrivileges')=='no' and worker.get('WorkingDirectory')==str(PRODUCTION),'WORKER_PRIVILEGE_OR_DIRECTORY')
    need(sha(step('READ_PREFECT_WORKER','PREFECT_WORKER_SOURCE',read,PRODUCTION/'.venv-prod/lib/python3.14/site-packages/prefect/workers/base.py'))==CONFIG['worker_base_sha256'],'WORKER_ENV_MERGE_UNVERIFIED')
    need(not os.path.lexists(CONTROL),'TRANSACTION_CONFLICT')
    for p in [LAUNCHER,RULE]:safe(p.parent);need(not os.path.lexists(p),'PATH_CONFLICT')
    pipeline=PRODUCTION/'src/scheduled_pipeline.py';delivery=PRODUCTION/'src/shared/forecast_delivery.py'
    old=step('READ_PIPELINE_SOURCE','PIPELINE_SOURCE',snapshot,pipeline);need(old and old['sha256']==CONFIG['pipeline_before'] and old['uid']==old['gid']==1000 and old['mode']==0o644,'PIPELINE_SOURCE_DRIFT')
    need(not os.path.lexists(delivery),'DELIVERY_SOURCE_CONFLICT')
    d=deployment();need(d.get('entrypoint')=='src/scheduled_pipeline.py:powerflow_entsoe_pipeline' and d.get('work_pool_name')=='electricity-pool','DEPLOYMENT_IDENTITY')
    pool=pool_metadata()
    need(pool.get('type')=='process' and pool.get('is_paused') is False,'WORK_POOL_COMPATIBILITY')
    template=pool.get('base_job_template') or {};need('env' in (template.get('variables') or {}).get('properties',{}) and '{{ env }}' in json.dumps(template.get('job_configuration',{})),'ENV_TEMPLATE_UNVERIFIED')
    step('VERIFY_ORIGINAL_TRANSACTION','ORIGINAL_TRANSACTION',original_transaction,d)
    old_vars,new_vars=variables(d)
    need(old_vars.get('command') in (None,'') and old_vars.get('working_dir',str(PRODUCTION))==str(PRODUCTION),'PROCESS_COMMAND_OR_DIRECTORY')
    queued=BASE['api']('/flow_runs/filter',{'deployments':{'id':{'any_':[DEP]}},'flow_runs':{'state':{'type':{'any_':['SCHEDULED']}}},'limit':100})
    need(len(queued)<100 and all(FLAG not in ((r.get('job_variables') or {}).get('env') or {}) for r in queued),'QUEUED_ENV_OVERRIDE')
    # All safety evidence precedes the first (private transaction) write.
    fresh();need(project(deployment())==project(d) and deployment().get('job_variables',{})==old_vars,'DEPLOYMENT_DRIFT')
    process(['/usr/sbin/visudo','-cf','-'],input=files['sudoers'],code='SUDOERS_SYNTAX')
    process(['/usr/sbin/visudo','-c'],code='EXISTING_SUDOERS_INVALID')
    need(check_shared()==(src_directory,shared_before),'DIRECTORY_DRIFT')
    step('VERIFY_RETAINED_TOOLS','RETAINED_TOOLS',retained_tools)
    step('CREATE_TRANSACTION','TRANSACTION',create_dir,CONTROL);CHANGED=True;PHASE='BACKUP'
    record={'version':1,'transaction':CONFIG['transaction'],'pipeline':old,'old_variables':old_vars,'new_variables':new_vars,'projection':project(d),'preservation':before,'status':'PREPARED','src_directory':src_directory,'shared_before':shared_before,'shared_created':None,'shared_intent':'NONE'}
    save(record)
    # Validate the digest-bound regex rule before installation; old grants untouched.
    write(CONTROL/'sudoers.new',files['sudoers']);process(['/usr/sbin/visudo','-cf',str(CONTROL/'sudoers.new')])
    PHASE='INSTALL'
    step('CREATE_OR_VERIFY_SHARED','PRODUCTION_SHARED',create_shared,record)
    step('INSTALL_LAUNCHER','LAUNCHER',write,LAUNCHER,files['launcher'],0o755,exclusive=True)
    step('INSTALL_DELIVERY','DELIVERY_MODULE',write,delivery,files['delivery'],0o644,1000,1000,exclusive=True)
    step('RECHECK_PIPELINE','PIPELINE',lambda:need(sha(read(pipeline))==old['sha256'],'PIPELINE_SOURCE_DRIFT'))
    step('INSTALL_PIPELINE','PIPELINE',write,pipeline,files['pipeline'],0o644,1000,1000)
    step('INSTALL_SUDOERS','SUDOERS_RULE',write,RULE,files['sudoers'],0o440,exclusive=True)
    step('VERIFY_SUDOERS','SUDOERS_RULE',process,['/usr/sbin/visudo','-c'])
    step('VERIFY_INSTALLED','INSTALLED_FILES',verify_installed,files)
    step('VERIFY_RETAINED_TOOLS','RETAINED_TOOLS',retained_tools)
    PHASE='ACTIVATION';step('ACTIVATION_GATES','HOST',fresh);need(deployment().get('job_variables',{})==old_vars,'DEPLOYMENT_DRIFT');step('ENABLE_AUTOMATION','PREFECT_ENV',patch,new_vars)
    after=deployment();need(after.get('job_variables')==new_vars and project(after)==record['projection'],'ACTIVATION_VERIFY')
    need(GUARD['production']()==before,'PRODUCTION_PRESERVATION');fresh();original_tools()
    record['status']='APPLIED';save(record);PHASE='COMPLETE'
    return {'status':'APPLIED','transaction':CONFIG['transaction'],'phase':PHASE,'changed':True,'resources':resources,'automatic_publication':'ENABLED_FOR_NATURAL_RUNS','publication_executed':False,'service_restart':False,'preservation':'PASS','retained_tools':'VERIFIED_REUSED','shared_directory':'CREATED' if record['shared_created'] else 'VERIFIED_PREEXISTING'}

def verify_installed(files):
    for folder in [TOOLS,TOOLS/'shared']:
        safe(folder);s=folder.stat();need(s.st_uid==s.st_gid==0 and stat.S_IMODE(s.st_mode)==0o700,'TOOLS_DIRECTORY')
    need(json.loads(read(TOOLS/'automation-manifest.json'))==CONFIG['installed_tools'],'INSTALLED_MANIFEST')
    for name,hash_ in CONFIG['installed_tools'].items():
        p=TOOLS/name;safe(p);s=p.stat();need(s.st_uid==s.st_gid==0 and stat.S_IMODE(s.st_mode)==0o600 and sha(read(p))==hash_,'INSTALLED_TOOL_HASH')
    for p,key,mode,uid in [(LAUNCHER,'launcher',0o755,0),(RULE,'sudoers',0o440,0),(PRODUCTION/'src/scheduled_pipeline.py','pipeline',0o644,1000),(PRODUCTION/'src/shared/forecast_delivery.py','delivery',0o644,1000)]:
        safe(p,(0,1000));s=p.stat();need(s.st_uid==s.st_gid==uid and stat.S_IMODE(s.st_mode)==mode and read(p)==files[key],'INSTALLED_FILE_HASH')

def rollback():
    global CHANGED,PHASE
    files=payloads();before,_=step('ROLLBACK_GATES','HOST',fresh);safe(CONTROL);record=json.loads(step('READ_RECORD','TRANSACTION_RECORD',read,CONTROL/'record.json'))
    need(record.get('version')==1 and record.get('transaction')==CONFIG['transaction'] and record.get('status') in ['PREPARED','APPLIED'],'ROLLBACK_RECORD')
    old=record['pipeline'];need(old['sha256']==CONFIG['pipeline_before'] and sha(base64.b64decode(old['raw']))==old['sha256'],'BACKUP_HASH')
    current=deployment();need(project(current)==record['projection'],'DEPLOYMENT_DRIFT')
    need(current.get('job_variables',{}) in [record['old_variables'],record['new_variables']],'ACTIVATION_DRIFT')
    step('VERIFY_ROLLBACK_DIRECTORY','PRODUCTION_SHARED',check_rollback_directory,record)
    # Reject drift everywhere before the first rollback mutation.
    for p,key in [(PRODUCTION/'src/scheduled_pipeline.py','pipeline'),(PRODUCTION/'src/shared/forecast_delivery.py','delivery'),(LAUNCHER,'launcher'),(RULE,'sudoers')]:
        if os.path.lexists(p):
            snap=snapshot(p);need(snap['sha256']==sha(files[key]) or (key=='pipeline' and snap==old),'ROLLBACK_FILE_DRIFT')
    CHANGED=True;PHASE='DISABLE';step('DISABLE_AUTOMATION','PREFECT_ENV',patch,record['old_variables'])
    need(deployment().get('job_variables',{})==record['old_variables'],'DISABLE_VERIFY')
    PHASE='RESTORE';step('RESTORE_PIPELINE','PIPELINE',write,PRODUCTION/'src/scheduled_pipeline.py',base64.b64decode(old['raw']),old['mode'],old['uid'],old['gid'])
    for p,label in [(PRODUCTION/'src/shared/forecast_delivery.py','DELIVERY_MODULE'),(RULE,'SUDOERS_RULE'),(LAUNCHER,'LAUNCHER')]:
        if os.path.lexists(p):step('REMOVE_INSTALLED_FILE',label,remove_file,p)
    directory_result=step('REMOVE_EMPTY_CREATED_SHARED','PRODUCTION_SHARED',remove_shared,record)
    process(['/usr/sbin/visudo','-c']);need(snapshot(PRODUCTION/'src/scheduled_pipeline.py')==old,'RESTORE_HASH')
    need(GUARD['production']()==before,'PRODUCTION_PRESERVATION');fresh()
    record['status']='ROLLED_BACK';save(record);PHASE='COMPLETE'
    return {'status':'ROLLED_BACK','transaction':CONFIG['transaction'],'phase':PHASE,'changed':True,'retained_private_tools':True,'shared_directory':directory_result,'publication_executed':False,'preservation':'PASS'}

def cause(error):
    if type(error) in (Stop,GUARD.get('Stop',Stop)) and re.fullmatch('[A-Z0-9_]{1,80}',str(error)):
        return str(error)
    return 'DEPLOYMENT_CHECK_FAILED'

def preflight_report():
    _,resources=step('CHECK_HOST','HOST',fresh)
    step('VERIFY_ORIGINAL_TOOLS','ORIGINAL_TOOLS',original_tools)
    return {'status':'INITIAL_PREFLIGHT_PASS','transaction':CONFIG['transaction'],'phase':'PREFLIGHT','changed':False,'resources':resources,'publication_executed':False,'service_restart':False,'check_scope':'INITIAL_HOST_AND_ORIGINAL_TOOLS'}

if __name__=='__main__':
    try:print(json.dumps(preflight_report() if ACTION=='preflight' else apply() if ACTION=='apply' else rollback(),sort_keys=True))
    except Exception as error:
        print(json.dumps({'status':'PARTIAL' if CHANGED else 'BLOCKED','phase':PHASE,'changed':CHANGED,'transaction':CONFIG['transaction'],'cause':cause(error),'publication_executed':False,**failure(error)}));raise SystemExit(1)
