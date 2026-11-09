"""Read-only Linux prerequisites. BASE/GUARD/PLAN/CONFIG are verified bytes.
No mkdir, chmod, chown, install, restart, deployment PATCH or publication calls.
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import pwd
import re
import socket
import ssl
import stat
import sys

PRODUCTION=Path('/home/ec2-user/Electricity_Trading_Pipeline')
OLD_API=Path('/opt/powerflow/releases')/PLAN.OLD_RELEASE
OLD_STATIC=Path('/var/www/powerflow-staging/releases')/PLAN.OLD_RELEASE
API=Path('/opt/powerflow/releases')/PLAN.RELEASE
STATIC=Path('/var/www/powerflow-staging/releases')/PLAN.RELEASE
TOOLS=Path('/opt/powerflow/operational-evidence-v1')
STORE=Path(PLAN.ROOT)
LAUNCHER=Path('/usr/local/sbin/powerflow-publish-operations')
RULE=Path('/etc/sudoers.d/powerflow-publish-operations')
BACKEND_LINK=Path('/opt/powerflow/react-current')
STATIC_LINK=Path('/var/www/powerflow-staging/current')
ENV=Path('/etc/powerflow/react-api.env')
CONTROL=Path('/var/lib/powerflow-staging')/('operational-evidence-'+PLAN.TRANSACTION)
KEY_PATHS={'TOOLS':TOOLS,'STORE':STORE,'LAUNCHER':LAUNCHER,'RULE':RULE,'API':API,'STATIC':STATIC,'TRANSACTION':CONTROL}


def path_id(value):
    if not isinstance(value,(str,bytes)):return 'UNIDENTIFIED'
    if isinstance(value,bytes):
        try:value=value.decode('ascii')
        except UnicodeError:return 'UNIDENTIFIED'
    table={str(p):name for name,p in KEY_PATHS.items()}
    table.update({str(ENV):'API_ENV',str(OLD_API):'BASELINE_API',str(OLD_STATIC):'BASELINE_STATIC'})
    for rel in CONFIG['worker']:table[str(PRODUCTION/rel)]='WORKER_'+rel.rsplit('/',1)[-1].replace('.','_').upper()
    for rel in CONFIG['old_api']:table[str(OLD_API/rel)]='BASELINE_API_'+rel.replace('/','_').replace('.','_').upper()
    for rel in CONFIG['worker_sdk']:table[str(PRODUCTION/'.venv-prod/lib/python3.14/site-packages/prefect'/rel)]='PREFECT_'+rel.replace('/','_').replace('.','_').upper()
    for rel in CONFIG.get('existing_forecast_tools',{}):table[str(Path('/opt/powerflow/forecast-publication-automation')/rel)]='FORECAST_TOOL_'+rel.replace('/','_').replace('.','_').upper()
    for path in CONFIG.get('existing_forecast_entrypoints',{}):table[path]='FORECAST_PRIVILEGE_'+Path(path).name.replace('-','_').upper()
    for rel in CONFIG.get('frozen',{}):table[str(PRODUCTION/'artifacts/models/releases/next24h'/rel)]='FROZEN_'+rel.replace('.','_').upper()
    if re.fullmatch(r'/proc/[0-9]+/(status|cmdline|environ)',value):return 'PROCESS_'+value.rsplit('/',1)[-1].upper()
    return table.get(value,'UNIDENTIFIED')


def need(value,code):PLAN.need(value,code)
def sha(raw):return PLAN.sha(raw)
def read(path,limit=2000000):return BASE['read'](path,limit)

def safe(path,owners=(0,)):
    for p in (Path(path),*Path(path).parents):
        s=p.lstat();need(not stat.S_ISLNK(s.st_mode) and s.st_uid in owners and not s.st_mode&0o022,'PATH_METADATA')

def snap(path,uid=0,gid=0,mode=0o644):
    safe(path,(0,1000) if str(path).startswith(str(PRODUCTION)+'/') else (0,))
    s=path.lstat();need(stat.S_ISREG(s.st_mode) and (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(uid,gid,mode),'FILE_METADATA')
    raw=read(path);return {'sha256':sha(raw),'uid':uid,'gid':gid,'mode':mode,'bytes':len(raw)},raw

def process(argv,input=b'',seconds=10):
    allowed=(argv in (['/usr/sbin/visudo','-cf','-'],['/usr/sbin/visudo','-c']))
    need(allowed,'READONLY_COMMAND_SCOPE')
    r=BASE['bounded_run'](argv,input=input,timeout=seconds,limit=16384,grace=5)
    need(r['returncode']==0 and r['failure'] is None,'SUDO_SYNTAX')


def deployment():return BASE['api']('/deployments/'+PLAN.DEPLOYMENT)

def forecast_fingerprint():
    root=Path('/srv/powerflow/forecast-publications');safe(root);safe(root/'releases')
    result={}
    for path in [root,root/'releases']:
        s=path.lstat();result[str(path.name)]=[s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode)]
    if os.path.lexists(root/'current'):
        target=os.readlink(root/'current');need(re.fullmatch(r'releases/[0-9a-f]{64}',target)is not None,'FORECAST_POINTER')
        safe(root/target);result['pointer']=target;result['bundle']=sha(read(root/target/'bundle.json',100001))
        need(result['bundle']==target.split('/')[1],'FORECAST_BUNDLE')
    else:result['pointer']=None
    return result


def http(path):
    need(path in {'/api/health','/api/operations/current','/api/pipeline/current','/api/admin/operations/current','/api/forecast/next24','/api/operations/summary'},'HTTP_SCOPE')
    c=http.client.HTTPSConnection('staging.powerflowenergy.dev',timeout=10,context=ssl.create_default_context())
    c._create_connection=lambda address,timeout,source_address=None:socket.create_connection(('127.0.0.1',443),timeout)
    try:
        c.request('GET',path,headers={'Accept':'application/json'});r=c.getresponse();raw=r.read(1000001)
        need(len(raw)<=1000000 and (r.getheader('Content-Type')or'').split(';')[0]=='application/json','HTTP_BOUND')
        return r.status,{'cache-control':r.getheader('Cache-Control','')},json.loads(raw)
    finally:c.close()


def assert_files(root,expected):
    # Root-only immutable tree, exact inventory; no symlinks except verified venv
    # handled independently by caller, never recursively traversed here.
    result={}
    for parent,dirs,files in os.walk(root,followlinks=False):
        need(len(result)<200 and len(dirs)+len(files)<200,'INVENTORY_BOUND')
        for name in dirs:
            p=Path(parent)/name
            if name=='.venv-api':need(p.parent==root and p.is_symlink(),'VENV_LAYOUT');continue
            safe(p)
        for name in files:
            p=Path(parent)/name;rel=p.relative_to(root).as_posix()
            if rel=='.venv-api':continue
            s,raw=snap(p);result[rel]=s['sha256']
    need(result==expected,'RELEASE_CONTENT_DRIFT')


def runtime_imports(venv):
    pid=int(BASE['services']()[PLAN.UNIT]['MainPID']);need(pid>1,'CANDIDATE_PID')
    script="import sys,pathlib,fastapi,uvicorn,httpx,joserfc,pandas,numpy,fcntl; root=pathlib.Path(sys.prefix); assert sys.version_info[:3]==(3,14,7); assert str(root)==sys.argv[1]; assert all(pathlib.Path(m.__file__).resolve().is_relative_to(root/'lib/python3.14/site-packages') for m in (fastapi,uvicorn,httpx,joserfc,pandas,numpy))"
    argv=['/usr/bin/nsenter','--mount=/proc/'+str(pid)+'/ns/mnt','--','/usr/bin/setpriv','--no-new-privs','--reuid=992','--regid=992','--clear-groups',str(venv/'bin/python'),'-I','-B','-c',script,str(venv)]
    result=BASE['bounded_run'](argv,timeout=15,limit=4096,grace=5)
    need(result['returncode']==0 and not result['failure'],'API_IMPORT_COMPATIBILITY')


def runtime_closure(venv):
    site=venv/'lib/python3.14/site-packages';safe(site);hashes={};total=0
    for parent,dirs,files in os.walk(site,followlinks=False):
        need(len(dirs)+len(files)<=2000,'RUNTIME_DIRECTORY_BOUND')
        for name in dirs:safe(Path(parent)/name)
        for name in files:
            path=Path(parent)/name;safe(path);s=path.lstat()
            need(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=64000000 and len(hashes)<20000,'RUNTIME_FILE_METADATA')
            raw=read(path,64000000);total+=len(raw);need(total<=512*1024**2,'RUNTIME_BYTES_BOUND')
            hashes[path.relative_to(site).as_posix()]=sha(raw)
    runtime_imports(venv)
    return {'sha256':sha(json.dumps(hashes,sort_keys=True).encode()),'files':len(hashes),'bytes':total,'imports':'PASS'}


def candidate_environment(operational=False):
    service=BASE['services']()[PLAN.UNIT]
    need(service.get('EnvironmentFiles')==str(ENV)+' (ignore_errors=no)','CANDIDATE_ENV_FILE')
    pid=int(service['MainPID']);raw=read('/proc/'+str(pid)+'/environ',262144)
    expected={b'POWERFLOW_API_DATA_ROOT':b'/srv/powerflow/published',b'POWERFLOW_FORECAST_PUBLICATION_ROOT':b'/srv/powerflow/forecast-publications'}
    if operational:expected[b'POWERFLOW_OPERATIONAL_PUBLICATION_ROOT']=str(STORE).encode()
    else:need(not any(line.startswith(b'POWERFLOW_OPERATIONAL_PUBLICATION_ROOT=') for line in raw.split(b'\0')),'EXISTING_OPERATIONAL_CONFIG')
    for key,value in expected.items():
        # Match only these public path settings; never report unrelated env data.
        values=[line[len(key)+1:] for line in raw.split(b'\0') if line.startswith(key+b'=')]
        need(values==[value],'CANDIDATE_PROCESS_ENV')


def partial_tree(root,prefix):
    if not os.path.lexists(root):return
    safe(root)
    expected={k[len(prefix):]:v for k,v in CONFIG['files'].items() if k.startswith(prefix)}
    for parent,dirs,files in os.walk(root,followlinks=False):
        need(len(dirs)+len(files)<200,'PARTIAL_TREE_BOUND')
        for name in dirs:
            path=Path(parent)/name
            if path==root/'.venv-api':need(path.is_symlink(),'VENV_LAYOUT');continue
            safe(path)
        for name in files:
            path=Path(parent)/name;relative=path.relative_to(root).as_posix()
            if relative=='.venv-api':need(path.is_symlink(),'VENV_LAYOUT');continue
            need(relative in expected,'PARTIAL_TREE_DRIFT')
            mode=0o600 if prefix=='helper/' else 0o644
            value,_=snap(path,0,0,mode);need(value['sha256']==expected[relative]['sha256'],'PARTIAL_FILE_DRIFT')


def forecast_configuration():
    for rel,digest in CONFIG['existing_forecast_tools'].items():
        value,_=snap(Path('/opt/powerflow/forecast-publication-automation')/rel,0,0,0o600)
        need(value['sha256']==digest,'FORECAST_TOOLS_DRIFT')
    for path,hash_ in CONFIG['existing_forecast_entrypoints'].items():
        value,_=snap(Path(path),0,0,0o440 if '/sudoers.d/' in path else 0o755)
        need(value['sha256']==hash_,'FORECAST_LAUNCHER_DRIFT')
    for name,hash_ in CONFIG['frozen'].items():
        path=PRODUCTION/'artifacts/models/releases/next24h'/name;safe(path,(0,1000));need(sha(read(path,64000000))==hash_,'FROZEN_MODEL_DRIFT')
    for rel,digest in CONFIG['first_tools'].items():
        path=Path('/opt/powerflow/forecast-publication-tools')/CONFIG['first_packet']/rel
        value,_=snap(path,0,0,0o600);need(value['sha256']==digest,'ORIGINAL_PUBLICATION_TOOLS_DRIFT')


def pool():
    c=http.client.HTTPConnection('127.0.0.1',4200,timeout=3)
    try:
        c.request('GET','/api/work_pools/electricity-pool');r=c.getresponse();raw=r.read(100001)
        need(r.status==200 and len(raw)<=100000,'WORK_POOL_READ')
        p=json.loads(raw);template=p.get('base_job_template')or{}
        need(p.get('type')=='process' and p.get('is_paused')is False and 'env' in (template.get('variables')or{}).get('properties',{}) and '{{ env }}' in json.dumps(template.get('job_configuration',{})),'WORK_POOL_ENV')
        return sha(json.dumps({k:p.get(k) for k in ['id','type','is_paused','base_job_template']},sort_keys=True).encode())
    finally:c.close()


def baseline_installation():
    hashes,backend=BASE['INSTALLED_HASHES'],BASE['BACKEND']
    BASE['INSTALLED_HASHES']=CONFIG['old_api'];BASE['BACKEND']=OLD_API
    try:
        facts,ok=BASE['passive_installation']();need(ok and not facts['startup_hooks_present'],'API_RUNTIME_CLOSURE')
        venv=BASE['canonical'](OLD_API/'.venv-api',Path('/opt/powerflow/releases'))
        facts['executable_closure']=runtime_closure(venv)
        return facts
    finally:BASE['INSTALLED_HASHES']=hashes;BASE['BACKEND']=backend


def idle(extra):
    result=GUARD['idle_capacity'](extra)
    entries=list(Path('/proc').iterdir());need(len(entries)<=32768,'PROCESS_BOUND')
    for p in entries:
        if not p.name.isdigit() or int(p.name)==os.getpid():continue
        try:cmd=read(p/'cmdline',65536)
        except FileNotFoundError:continue
        need(b'/opt/powerflow/operational-evidence-v1/bootstrap.py' not in cmd and b'/usr/local/sbin/powerflow-publish-operations' not in cmd,'ACTIVE_OPERATIONAL_HELPER')
    return result


def initial():
    need(os.getuid()==os.geteuid()==0 and sys.platform=='linux' and sys.version_info>=(3,9),'HOST_RUNTIME')
    need(os.uname().machine=='x86_64' and hasattr(os,'O_NOATIME') and Path('/proc/self/fd').is_dir(),'PROCFS')
    identity=pwd.getpwnam('powerflow-api');producer=pwd.getpwnam('ec2-user')
    need((identity.pw_uid,identity.pw_gid)==(992,992) and (producer.pw_uid,producer.pw_gid)==(1000,1000),'SERVICE_IDENTITIES')
    # Collision/existence gates precede writes. Missing operational root is the
    # declared initial condition, NOT a claim of existing effective API access.
    for key,path in KEY_PATHS.items():safe(path.parent);need(not os.path.lexists(path),'DESTINATION_CONFLICT_'+key)
    for path in [PRODUCTION/'src',PRODUCTION/'src/shared']:
        safe(path,(0,1000));s=path.lstat();need(stat.S_ISDIR(s.st_mode) and (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(1000,1000,0o755),'PRODUCTION_DIRECTORY')
    need(Path('/opt/powerflow/react-current').resolve(strict=True)==OLD_API and Path('/var/www/powerflow-staging/current').resolve(strict=True)==OLD_STATIC,'BASELINE_POINTERS')
    for link in ['/opt/powerflow/react-current','/var/www/powerflow-staging/current']:
        s=Path(link).lstat();need(stat.S_ISLNK(s.st_mode) and s.st_uid==0,'POINTER_METADATA')
    assert_files(OLD_API,CONFIG['old_api']);need(GUARD['inventory'](OLD_STATIC)==CONFIG['old_static_inventory'],'STATIC_BASELINE')
    historical=Path('/var/lib/powerflow-staging/forecast-consistency-transactions/f2f195174eda43daa8e5593087fbe1d3/state.json')
    _,historical_raw=snap(historical,0,0,0o600)
    need(sha(historical_raw)==CONFIG['historical_record_sha256'],'HISTORICAL_RECORD_DRIFT')
    env_snap,env=snap(ENV,0,0,0o600);new_env=PLAN.environment(env,CONFIG['env_before'])
    need(sha(new_env)==CONFIG['env_after'],'ENV_TARGET')
    backups={'api_env':env_snap}
    for rel,meta in CONFIG['worker'].items():
        path=PRODUCTION/rel
        if meta['before'] is None:need(not os.path.lexists(path),'WORKER_PATH_CONFLICT');backups[rel]=None
        else:
            before,_=snap(path,1000,1000,0o644);need(before['sha256']==meta['before'],'PIPELINE_DRIFT');backups[rel]=before
    # Existing publisher and frozen parser/model paths are preservation-only.
    forecast_configuration()
    for rel,digest in CONFIG['existing_forecast_tools'].items():
        path=Path('/opt/powerflow/forecast-publication-automation')/rel
        item,_=snap(path,0,0,0o600);need(item['sha256']==digest,'FORECAST_TOOLS_DRIFT')
    for path,hash_ in CONFIG['existing_forecast_entrypoints'].items():
        expected_mode=0o440 if '/sudoers.d/' in path else 0o755
        item,_=snap(Path(path),0,0,expected_mode);need(item['sha256']==hash_,'FORECAST_LAUNCHER_DRIFT')
    for name,hash_ in CONFIG['worker_sdk'].items():
        path=PRODUCTION/'.venv-prod/lib/python3.14/site-packages/prefect'/name
        safe(path,(0,1000));need(sha(read(path))==hash_,'PREFECT_IMPLEMENTATION_DRIFT')
    for path in ['/usr/bin/python3','/usr/bin/python3.14','/usr/bin/sudo','/usr/sbin/visudo','/usr/bin/timeout','/usr/bin/env','/bin/sh','/usr/bin/systemctl','/usr/bin/nsenter','/usr/bin/setpriv']:
        p=Path(path).resolve(strict=True);safe(p);need(stat.S_ISREG(p.stat().st_mode),'SYSTEM_BINARY')
    installation=baseline_installation()
    GUARD['runtime'](OLD_API);candidate_environment(False);idle(CONFIG['total_bytes']*2)
    worker=BASE['services']()['powerflow-prefect-worker.service']
    need(worker.get('User')==worker.get('Group')=='ec2-user' and worker.get('NoNewPrivileges')=='no' and worker.get('WorkingDirectory')==str(PRODUCTION),'WORKER_IDENTITY')
    for name,hash_ in CONFIG['frozen'].items():
        path=PRODUCTION/'artifacts/models/releases/next24h'/name;safe(path,(0,1000));need(sha(read(path,64000000))==hash_,'FROZEN_MODEL_DRIFT')
    manifest,_=snap(Path('/opt/powerflow/forecast-publication-automation/automation-manifest.json'),0,0,0o600)
    need(json.loads(read('/opt/powerflow/forecast-publication-automation/automation-manifest.json'))==CONFIG['existing_forecast_tools'],'FORECAST_MANIFEST_DRIFT')
    pid=int(worker['MainPID']);need(not any(line.startswith(PLAN.FLAG.encode()+b'=') for line in read('/proc/'+str(pid)+'/environ',262144).split(b'\0')),'WORKER_ENV_OVERRIDE')
    pool_hash=pool()
    d=deployment();new_vars=PLAN.variables(d.get('job_variables',{}))
    need(d.get('entrypoint')=='src/scheduled_pipeline.py:powerflow_entsoe_pipeline' and d.get('work_pool_name')=='electricity-pool','DEPLOYMENT_IDENTITY')
    queued=BASE['api']('/flow_runs/filter',{'deployments':{'id':{'any_':[PLAN.DEPLOYMENT]}},'flow_runs':{'state':{'type':{'any_':['SCHEDULED']}}},'limit':100})
    need(type(queued)is list and len(queued)<100 and all(PLAN.FLAG not in ((r.get('job_variables')or{}).get('env')or{}) and ((r.get('job_variables')or{}).get('env')or{}).get(PLAN.FORECAST_FLAG,'true')=='true' for r in queued),'QUEUED_OVERRIDE')
    # Never execute/import code from the worker SDK as root.
    for line in read(PRODUCTION/'.env',65536).splitlines():need(not line.strip().startswith(PLAN.FLAG.encode()+b'='),'SHARED_ENV_OVERRIDE')
    process(['/usr/sbin/visudo','-cf','-'],input=bytes.fromhex(CONFIG['sudoers_hex']));process(['/usr/sbin/visudo','-c'])
    need(BASE['request'](8010,'/health')[0]==BASE['request'](8010,'/ready')[0]==200,'CANDIDATE_HEALTH')
    need(BASE['request'](8000,'/health')[0]==BASE['request'](8501,'/_stcore/health')[0]==BASE['request'](443,'/',tls=True)[0]==200,'PRODUCTION_HEALTH')
    need(http('/api/health')[0]==200,'STAGING_ROUTING')
    venv=BASE['canonical'](OLD_API/'.venv-api',Path('/opt/powerflow/releases'))
    before={'backups':backups,'projection':PLAN.stable_projection(d),'old_variables':d.get('job_variables',{}),'new_variables':new_vars,
            'venv':str(venv),'production':GUARD['production'](),'forecast':forecast_fingerprint(),'runtime':installation,'pool_sha256':pool_hash}
    return before
