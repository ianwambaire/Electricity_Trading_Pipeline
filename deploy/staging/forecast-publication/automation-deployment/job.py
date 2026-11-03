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
    resources=GUARD['idle_capacity'](1000000)
    frozen()
    need(os.getuid()==os.geteuid()==0,'ROOT_REQUIRED')
    backend=Path('/opt/powerflow/react-current').resolve(strict=True)
    need(backend==Path('/opt/powerflow/releases/phase-api-body-bound-20261102-v2'),'STAGING_POINTER_DRIFT')
    need(Path('/var/www/powerflow-staging/current').resolve(strict=True)==Path('/var/www/powerflow-staging/releases/phase-api-body-bound-20261102-v2'),'STATIC_POINTER_DRIFT')
    GUARD['runtime'](backend)
    need(BASE['request'](8010,'/health')[0]==200 and BASE['request'](8010,'/ready')[0]==200,'CANDIDATE_HEALTH')
    need(BASE['request'](443,'/',tls=True)[0]==200 and BASE['request'](8000,'/health')[0]==200 and BASE['request'](8501,'/_stcore/health')[0]==200,'SITE_HEALTH')
    return GUARD['production'](),resources

def system_binaries():
    for binary in ['/usr/bin/sudo','/usr/sbin/visudo','/usr/bin/env','/usr/bin/timeout','/usr/bin/python3','/bin/sh']:
        p=Path(binary).resolve(strict=True);safe(p);need(stat.S_ISREG(p.stat().st_mode),'SYSTEM_BINARY')

def original_tools():
    root=Path('/opt/powerflow/forecast-publication-tools')/CONFIG['original_packet']
    for folder in [root.parent,root,root/'shared']:
        safe(folder);s=folder.stat();need(s.st_uid==s.st_gid==0 and stat.S_IMODE(s.st_mode)==0o700,'ORIGINAL_TOOLS_DIRECTORY')
    for rel,hash_ in CONFIG['original_tools'].items():
        p=root/rel;safe(p);s=p.stat();need(s.st_uid==s.st_gid==0 and stat.S_IMODE(s.st_mode)==0o600 and sha(read(p))==hash_,'ORIGINAL_TOOLS_DRIFT')
    for p in [Path('/srv/powerflow/forecast-publications'),Path('/srv/powerflow/forecast-publications/releases')]:
        safe(p);s=p.stat();need(s.st_gid==992 and stat.S_IMODE(s.st_mode)==0o750,'PUBLICATION_PERMISSIONS')

def apply():
    global CHANGED,PHASE
    files=payloads();before,resources=fresh();original_tools()
    system_binaries()
    need(pwd.getpwnam('ec2-user').pw_uid==pwd.getpwnam('ec2-user').pw_gid==1000,'PUBLISHER_IDENTITY')
    worker=BASE['services']()['powerflow-prefect-worker.service']
    need(worker.get('User')==worker.get('Group')=='ec2-user' and worker.get('NoNewPrivileges')=='no' and worker.get('WorkingDirectory')==str(PRODUCTION),'WORKER_PRIVILEGE_OR_DIRECTORY')
    need(sha(read(PRODUCTION/'.venv-prod/lib/python3.14/site-packages/prefect/workers/base.py'))==CONFIG['worker_base_sha256'],'WORKER_ENV_MERGE_UNVERIFIED')
    need(not os.path.lexists(CONTROL),'TRANSACTION_CONFLICT')
    for p in [TOOLS,LAUNCHER,RULE]:safe(p.parent);need(not os.path.lexists(p),'PATH_CONFLICT')
    pipeline=PRODUCTION/'src/scheduled_pipeline.py';delivery=PRODUCTION/'src/shared/forecast_delivery.py'
    old=snapshot(pipeline);need(old and old['sha256']==CONFIG['pipeline_before'] and old['uid']==old['gid']==1000 and old['mode']==0o644,'PIPELINE_SOURCE_DRIFT')
    need(not os.path.lexists(delivery),'DELIVERY_SOURCE_CONFLICT')
    d=deployment();need(d.get('entrypoint')=='src/scheduled_pipeline.py:powerflow_entsoe_pipeline' and d.get('work_pool_name')=='electricity-pool','DEPLOYMENT_IDENTITY')
    pool=pool_metadata()
    need(pool.get('type')=='process' and pool.get('is_paused') is False,'WORK_POOL_COMPATIBILITY')
    template=pool.get('base_job_template') or {};need('env' in (template.get('variables') or {}).get('properties',{}) and '{{ env }}' in json.dumps(template.get('job_configuration',{})),'ENV_TEMPLATE_UNVERIFIED')
    old_vars,new_vars=variables(d)
    need(old_vars.get('command') in (None,'') and old_vars.get('working_dir',str(PRODUCTION))==str(PRODUCTION),'PROCESS_COMMAND_OR_DIRECTORY')
    queued=BASE['api']('/flow_runs/filter',{'deployments':{'id':{'any_':[DEP]}},'flow_runs':{'state':{'type':{'any_':['SCHEDULED']}}},'limit':100})
    need(len(queued)<100 and all(FLAG not in ((r.get('job_variables') or {}).get('env') or {}) for r in queued),'QUEUED_ENV_OVERRIDE')
    # All safety evidence precedes the first (private transaction) write.
    fresh();need(project(deployment())==project(d) and deployment().get('job_variables',{})==old_vars,'DEPLOYMENT_DRIFT')
    process(['/usr/sbin/visudo','-cf','-'],input=files['sudoers'],code='SUDOERS_SYNTAX')
    process(['/usr/sbin/visudo','-c'],code='EXISTING_SUDOERS_INVALID')
    create_dir(CONTROL);CHANGED=True;PHASE='BACKUP'
    record={'version':1,'transaction':CONFIG['transaction'],'pipeline':old,'old_variables':old_vars,'new_variables':new_vars,'projection':project(d),'preservation':before,'status':'PREPARED'}
    write(CONTROL/'record.json',json.dumps(record,sort_keys=True).encode());need(json.loads(read(CONTROL/'record.json'))==record,'BACKUP_VERIFY')
    # Validate the digest-bound regex rule before installation; old grants untouched.
    write(CONTROL/'sudoers.new',files['sudoers']);process(['/usr/sbin/visudo','-cf',str(CONTROL/'sudoers.new')])
    PHASE='INSTALL';create_dir(TOOLS);create_dir(TOOLS/'shared')
    for name in CONFIG['installed_tools']:write(TOOLS/name,files['tools/'+name],exclusive=True)
    write(TOOLS/'automation-manifest.json',json.dumps(CONFIG['installed_tools'],sort_keys=True).encode(),exclusive=True)
    write(LAUNCHER,files['launcher'],0o755,exclusive=True)
    write(delivery,files['delivery'],0o644,1000,1000,exclusive=True)
    need(sha(read(pipeline))==old['sha256'],'PIPELINE_SOURCE_DRIFT');write(pipeline,files['pipeline'],0o644,1000,1000)
    write(RULE,files['sudoers'],0o440,exclusive=True);process(['/usr/sbin/visudo','-c'])
    verify_installed(files)
    PHASE='ACTIVATION';fresh();need(deployment().get('job_variables',{})==old_vars,'DEPLOYMENT_DRIFT');patch(new_vars)
    after=deployment();need(after.get('job_variables')==new_vars and project(after)==record['projection'],'ACTIVATION_VERIFY')
    need(GUARD['production']()==before,'PRODUCTION_PRESERVATION');fresh();original_tools()
    record['status']='APPLIED';write(CONTROL/'record.json',json.dumps(record,sort_keys=True).encode());PHASE='COMPLETE'
    return {'status':'APPLIED','transaction':CONFIG['transaction'],'phase':PHASE,'changed':True,'resources':resources,'automatic_publication':'ENABLED_FOR_NATURAL_RUNS','publication_executed':False,'service_restart':False,'preservation':'PASS'}

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
    files=payloads();before,_=fresh();safe(CONTROL);record=json.loads(read(CONTROL/'record.json'))
    need(record.get('version')==1 and record.get('transaction')==CONFIG['transaction'] and record.get('status') in ['PREPARED','APPLIED'],'ROLLBACK_RECORD')
    old=record['pipeline'];need(old['sha256']==CONFIG['pipeline_before'] and sha(base64.b64decode(old['raw']))==old['sha256'],'BACKUP_HASH')
    current=deployment();need(project(current)==record['projection'],'DEPLOYMENT_DRIFT')
    need(current.get('job_variables',{}) in [record['old_variables'],record['new_variables']],'ACTIVATION_DRIFT')
    # Reject drift everywhere before the first rollback mutation.
    for p,key in [(PRODUCTION/'src/scheduled_pipeline.py','pipeline'),(PRODUCTION/'src/shared/forecast_delivery.py','delivery'),(LAUNCHER,'launcher'),(RULE,'sudoers')]:
        if os.path.lexists(p):
            snap=snapshot(p);need(snap['sha256']==sha(files[key]) or (key=='pipeline' and snap==old),'ROLLBACK_FILE_DRIFT')
    CHANGED=True;PHASE='DISABLE';patch(record['old_variables'])
    need(deployment().get('job_variables',{})==record['old_variables'],'DISABLE_VERIFY')
    PHASE='RESTORE';write(PRODUCTION/'src/scheduled_pipeline.py',base64.b64decode(old['raw']),old['mode'],old['uid'],old['gid'])
    for p in [PRODUCTION/'src/shared/forecast_delivery.py',RULE,LAUNCHER]:
        if os.path.lexists(p):p.unlink();fsync(p.parent)
    process(['/usr/sbin/visudo','-c']);need(snapshot(PRODUCTION/'src/scheduled_pipeline.py')==old,'RESTORE_HASH')
    need(GUARD['production']()==before,'PRODUCTION_PRESERVATION');fresh()
    record['status']='ROLLED_BACK';write(CONTROL/'record.json',json.dumps(record,sort_keys=True).encode());PHASE='COMPLETE'
    return {'status':'ROLLED_BACK','transaction':CONFIG['transaction'],'phase':PHASE,'changed':True,'retained_private_tools':True,'publication_executed':False,'preservation':'PASS'}

def cause(error):
    if type(error) in (Stop,GUARD.get('Stop',Stop)) and re.fullmatch('[A-Z0-9_]{1,80}',str(error)):
        return str(error)
    return 'DEPLOYMENT_CHECK_FAILED'

if __name__=='__main__':
    try:print(json.dumps(apply() if ACTION=='apply' else rollback(),sort_keys=True))
    except Exception as error:
        print(json.dumps({'status':'PARTIAL' if CHANGED else 'BLOCKED','phase':PHASE,'changed':CHANGED,'transaction':CONFIG['transaction'],'cause':cause(error),'publication_executed':False}));raise SystemExit(1)
