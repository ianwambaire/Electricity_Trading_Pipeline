"""Read-only predecessor, idle-window, ownership and unprivileged import gates."""
import base64
import datetime as dt
import json
import http.client as http_client
import socket
import ssl
import os
from pathlib import Path
import pwd
import re
import stat
import sys

API=Path(C['api']);STATIC=Path(C['static']);CONTROL=Path(C['control']);REPORT=Path(C['root'])
WORKER=P.PRODUCTION;ENV=P.ENV

def raw_file(key):
    need(key in C['files'],'FILE_SCOPE');item=C['files'][key]
    if 'copy_from'in item:
        need(key.startswith('static/assets/') and item['copy_from']==str(OLD.STATIC/key[7:]),'COPY_SOURCE_SCOPE')
        need(OLD.C['files'][key]['sha256']==item['sha256'],'COPY_BASELINE_HASH')
        raw=P.snap(Path(item['copy_from']))[1]
    else:raw=base64.b64decode(item['base64'],validate=True)
    need(sha(raw)==item['sha256'] and len(raw)<=item.get('max_bytes',2000000) and (item['bytes']is None or len(raw)==item['bytes']),'PAYLOAD_BINDING');return raw

def optional_package_state():
    result={}
    for name,item in C.get('worker_optional_packages',{}).items():
        need(name=='shared'and item['path']=='src/shared'and item['initializer']=='src/shared/__init__.py','WORKER_OPTIONAL_PACKAGE_SCOPE')
        root=WORKER/item['path'];P.safe(root,(0,1000));s=root.lstat()
        need(stat.S_ISDIR(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(1000,1000,0o755),'WORKER_PACKAGE_DIRECTORY_METADATA')
        need(not os.path.lexists(WORKER/'src/shared.py'),'WORKER_PACKAGE_SHADOW')
        info={'directory':[s.st_dev,s.st_ino,s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode)],'initializer':None}
        path=WORKER/item['initializer']
        if os.path.lexists(path):
            meta,raw=P.snap(path,1000,1000,0o644);inode=path.lstat()
            need(inode.st_nlink==1 and meta['sha256']==item['sha256']and meta['bytes']==item['bytes'],'WORKER_OPTIONAL_INITIALIZER_DRIFT')
            info['initializer']={**meta,'identity':[inode.st_dev,inode.st_ino]}
        result[name]=info
    return result

def worker_state(installed=False):
    result={};issues=[]
    try:optional_package_state()
    except (OSError,ValueError)as error:issues.append(dependency_issue('src/shared','PACKAGE',error))
    for rel,before in C['worker_before'].items():
        path=WORKER/rel;stage='PARENT'
        try:
            P.safe(path.parent,(0,1000));stage='FILE'
            if not os.path.lexists(path):
                if not installed and(before is None or isinstance(before,list)and None in before):result[rel]=None
                else:issues.append(dependency_issue(rel,stage,category='MISSING',gate='WORKER_REQUIRED_FILE_MISSING'))
                continue
            meta,_=P.snap(path,1000,1000,0o644)
            if path.lstat().st_nlink!=1:issues.append(dependency_issue(rel,stage,category='HARDLINK',gate='WORKER_HARDLINK'));continue
            allowed=[C['files']['worker/'+rel]['sha256']]if installed else before if isinstance(before,list)else[before]
            if meta['sha256']not in allowed:
                issues.append(dependency_issue(rel,'BASELINE',category='UNEXPECTED_PRESENT'if allowed==[None]else'HASH_OR_SIZE_MISMATCH',gate='WORKER_BASELINE_DRIFT_'+Path(rel).stem.upper()));continue
            result[rel]=meta
        except (OSError,ValueError)as error:issues.append(dependency_issue(rel,stage,error))
    for rel,item in C['worker_dependencies'].items():
        try:
            meta,_=P.snap(WORKER/rel,1000,1000,0o644)
            if meta['sha256']!=item['sha256']or meta['bytes']!=item['bytes']:
                issues.append(dependency_issue(rel,'DEPENDENCY',category='HASH_OR_SIZE_MISMATCH',gate='WORKER_DEPENDENCY_DRIFT_'+Path(rel).stem.upper()))
        except (OSError,ValueError)as error:issues.append(dependency_issue(rel,'DEPENDENCY',error))
    if issues:raise DependencyInventoryFailure(issues)
    return result

def report_environment(active):
    pid=int(B['services']()[H.OLD_PLAN.UNIT]['MainPID']);need(pid>1,'CANDIDATE_PID')
    raw=P.read('/proc/'+str(pid)+'/environ',262144)
    values=[line for line in raw.split(b'\0')if line.startswith((ROOT_KEY+'=').encode())]
    need(values==[(ROOT_KEY+'='+C['root']).encode()]if active else not values,'REPORT_PROCESS_ENV')
    return pid

def sources(kind):
    result={};locations={}
    if kind=='api':
        for key in C['files']:
            if not(key.startswith('api/src/')and key.endswith('.py')):continue
            rel=key[8:];name=rel[:-3].replace('/','.');package=name.endswith('.__init__')
            if package:name=name[:-9]
            result[name]=(raw_file(key).decode(),package);locations[name]=str(API/'src'/rel)
    else:
        packages=optional_package_state()
        for name,item in C['worker_closure'].items():
            if name in packages and packages[name]['initializer']is None:
                result[name]=('',True);locations[name]=str(WORKER/C['worker_optional_packages'][name]['path']);continue
            rel=item['path']
            try:raw=raw_file('worker/'+rel)if 'worker/'+rel in C['files']else P.snap(WORKER/rel,1000,1000,0o644)[1]
            except OSError as error:raise DependencyInventoryFailure([dependency_issue(rel,'IMPORT_SOURCE',error)])from None
            need(sha(raw)==item['sha256'],'WORKER_IMPORT_SOURCE_HASH');package=rel.endswith('/__init__.py')
            result[name]=(raw.decode(),package);locations[name]=str(WORKER/rel)
        for name in ['models','processing','ingestion']:
            result.setdefault(name,('',True));locations.setdefault(name,str(WORKER/'src'/name/'__init__.py'))
    return result,locations

def probe_script(kind):
    code,locations=sources(kind);uid=992 if kind=='api'else 1000
    script="import sys,os,json,importlib.abc,importlib.util,importlib.metadata,importlib.machinery\n"
    identity="assert sys.version_info[:3]==(3,14,7) and os.getuid()==os.geteuid()=="+str(uid)+" and os.getgid()==os.getegid()=="+str(uid)+"\n"
    script+="def audit(event,args):\n if event in {'socket.connect','socket.bind','subprocess.Popen','os.system','os.mkdir','os.remove','os.rename','os.chmod','os.chown','os.symlink','os.link'}:raise RuntimeError('IMPORT_SIDE_EFFECT')\n if event=='open' and args[2]&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):raise RuntimeError('IMPORT_WRITE')\nsys.addaudithook(audit)\n"
    namespaces={name for name,item in C.get('worker_optional_packages',{}).items()if kind=='worker'and locations.get(name)==str(WORKER/item['path'])}
    script+='NAMESPACES='+repr(sorted(namespaces))+'\n'
    script+='SOURCES='+repr(code)+'\nLOCATIONS='+repr(locations)+"\nclass Loader(importlib.abc.MetaPathFinder,importlib.abc.Loader):\n def find_spec(self,name,path=None,target=None):\n  if name not in SOURCES:\n   if name.split('.')[0]in {'api','models','shared','ingestion','processing'}:raise ModuleNotFoundError('UNBOUND_PROJECT_MODULE')\n   return None\n  if name in NAMESPACES:\n   spec=importlib.machinery.ModuleSpec(name,loader=None,is_package=True);spec.submodule_search_locations=[LOCATIONS[name]];return spec\n  spec=importlib.util.spec_from_loader(name,self,origin=LOCATIONS[name],is_package=SOURCES[name][1]);spec.has_location=True\n  if SOURCES[name][1]:spec.submodule_search_locations=[os.path.dirname(LOCATIONS[name])]\n  return spec\n def create_module(self,spec):return None\n def exec_module(self,module):\n  module.__file__=LOCATIONS[module.__name__]\n  if SOURCES[module.__name__][1]:module.__path__=[os.path.dirname(module.__file__)]\n  exec(compile(SOURCES[module.__name__][0],module.__file__,'exec'),module.__dict__)\nsys.meta_path.insert(0,Loader())\n"
    checks=identity
    if kind=='api':
        checks+="import api.app,api.realized_reporting,shared.realized_report_store\nassert str(api.app.PROJECT_ROOT)=="+repr(str(API))+"\nassert '/forecast/realized-evaluation'in {r.path for r in api.app.app.routes}\nassert {'report_status','generated_at','fresh_until','coverage'}<=set(api.realized_reporting.RealizedEvaluation.model_fields)\n"
    else:
        checks+="import models.realized_reporting,models.next24h_monitoring\nassert all(importlib.metadata.version(k)==v for k,v in "+repr(C['worker_versions'])+".items())\n"
    # Fixed categories/module identifiers only; never return child stderr.
    script+="try:\n"+''.join(' '+line+'\n'for line in checks.splitlines())
    script+="except Exception as error:\n cause=type(error).__name__\n if cause not in {'AssertionError','ModuleNotFoundError','ImportError','AttributeError','RuntimeError','PermissionError','FileNotFoundError','TypeError','ValueError'}:cause='OTHER'\n module='UNVERIFIED';trace=error.__traceback__\n while trace:\n  for name,location in LOCATIONS.items():\n   if trace.tb_frame.f_code.co_filename==location:module=name\n  trace=trace.tb_next\n print(json.dumps({'status':'FAILED','cause_class':cause,'approved_module':module},sort_keys=True));raise SystemExit(1)\nprint('REPORT_IMPORT_PASS')\n"
    return script.encode()

def import_probe(kind,venv):
    uid=992 if kind=='api'else 1000
    command=['/usr/bin/setpriv','--no-new-privs','--reuid='+str(uid),'--regid='+str(uid),'--clear-groups',str(venv/'bin/python'),'-I','-B','-']
    if kind=='api':
        pid=report_environment(False)
        command=['/usr/bin/nsenter','--mount=/proc/'+str(pid)+'/ns/mnt','--']+command
    result=B['bounded_run'](command,input=probe_script(kind),timeout=25,limit=8192,grace=5)
    if result['returncode']!=0 or result['failure']or result['stdout']!=b'REPORT_IMPORT_PASS\n':
        detail={}
        try:detail=json.loads(result['stdout'])
        except(ValueError,TypeError):pass
        raise ImportProbeFailure('REPORT_'+kind.upper()+'_IMPORT_COMPATIBILITY',detail.get('approved_module','UNVERIFIED'),detail.get('cause_class','OTHER'))

def queued_gate():
    runs=B['api']('/flow_runs/filter',{'deployments':{'id':{'any_':[H.OLD_PLAN.DEPLOYMENT]}},'flow_runs':{'state':{'type':{'any_':['SCHEDULED']}}},'limit':100})
    need(type(runs)is list and len(runs)<100,'QUEUED_RUN_BOUND')
    for run in runs:
        env=((run.get('job_variables')or{}).get('env')or{})
        need(FLAG not in env and ROOT_KEY not in env,'QUEUED_REPORT_OVERRIDE')

def input_bounds():
    for rel,limit,rows in [('data/reports/next24h_forecast_history.csv',64*1024**2,100000),('data/raw/entsoe/prices.csv',64*1024**2,400000)]:
        try:
            path=WORKER/rel;P.safe(path,(0,1000));s=path.lstat()
            need(stat.S_ISREG(s.st_mode)and s.st_uid==1000 and s.st_size<=limit,'REPORT_INPUT_SIZE')
            raw=P.read(path,limit);need(raw.count(b'\n')<=rows+1,'REPORT_INPUT_ROW_BOUND')
        except OSError as error:raise DependencyInventoryFailure([dependency_issue(rel,'INPUT',error)])from None
    rel='data/reports/next24h_inference'
    try:
        root=WORKER/rel;P.safe(root,(0,1000));need(root.is_dir(),'RECEIPT_ROOT_MISSING')
        with os.scandir(root)as entries:
            for i,entry in enumerate(entries):need(i<10000 and entry.is_dir(follow_symlinks=False),'RECEIPT_DIRECTORY_BOUND')
    except OSError as error:raise DependencyInventoryFailure([dependency_issue(rel,'INPUT',error)])from None

def snapshot():
    return {'production':P.production(),'forecast':P.forecast_fingerprint(),'store':H.store_snapshot(),'helper':OLD.helper_verified(),
            'nginx':P.snap(P.NGINX,0,0,0o644)[0]['sha256'],'pool':P.pool(),'worker_packages':optional_package_state()}

def parent_access():
    script="import os;assert os.getuid()==os.geteuid()==1000;assert os.access("+repr(str(REPORT.parent))+",os.X_OK);print('PARENT_ACCESS_PASS')"
    result=B['bounded_run'](['/usr/bin/setpriv','--no-new-privs','--reuid=1000','--regid=1000','--clear-groups','/usr/bin/python3','-I','-S','-B','-c',script],timeout=5,limit=1024,grace=5)
    need(result['returncode']==0 and not result['failure']and result['stdout']==b'PARENT_ACCESS_PASS\n','REPORT_PARENT_TRAVERSAL')


def report_http():
    c=http_client.HTTPSConnection('staging.powerflowenergy.dev',timeout=10,context=ssl.create_default_context())
    c._create_connection=lambda address,timeout,source_address=None:socket.create_connection(('127.0.0.1',443),timeout)
    try:
        c.request('GET','/api/forecast/realized-evaluation',headers={'Accept':'application/json'});response=c.getresponse();raw=response.read(100001)
        need(len(raw)<=100000 and(response.getheader('Content-Type')or'').split(';')[0]=='application/json','REALIZED_HTTP_CONTENT')
        need(response.getheader('Cache-Control')=='no-store','REALIZED_HTTP_CACHE')
        try:body=json.loads(raw)
        except ValueError:need(False,'REALIZED_HTTP_JSON')
        need(type(body)is dict,'REALIZED_HTTP_SCHEMA')
        return response.status,body
    finally:c.close()

def fresh():
    global PREFLIGHT_STAGE
    PREFLIGHT_STAGE='HOST'
    need(os.getuid()==os.geteuid()==os.getgid()==os.getegid()==0 and sys.platform=='linux','HOST_IDENTITY')
    need(sys.version_info>=(3,9) and os.uname().machine=='x86_64' and hasattr(os,'O_NOATIME')and Path('/proc/self/fd').is_dir(),'HOST_RUNTIME')
    for name,expected in [('ec2-user',(1000,1000)),('powerflow-api',(992,992))]:
        u=pwd.getpwnam(name);need((u.pw_uid,u.pw_gid)==expected,'SERVICE_IDENTITIES')
    for p in [API,STATIC,CONTROL,REPORT]:P.safe(p.parent);need(not os.path.lexists(p),'DESTINATION_OR_TRANSACTION_EXISTS')
    PREFLIGHT_STAGE='PREDECESSOR_AND_SAFETY'
    P.idle(sum(v['bytes']or v.get('max_bytes',2000000)for v in C['files'].values())*4)
    previous=OLD.load_record();need(previous['phase']=='APPLIED' and previous['activated_at'],'RELIABILITY_V2_NOT_APPLIED');OLD.verified_backups(previous)
    OLD.deployment_checks(previous) # accepted component-level preservation policy
    P.forecast_configuration()
    code,_=report_http();need(code in {200,404,503},'REALIZED_ROUTING_BASELINE')
    for link,target in [(P.BACKEND_LINK,OLD.API),(P.STATIC_LINK,OLD.STATIC)]:
        s=link.lstat();need(stat.S_ISLNK(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o777)and os.readlink(link)==str(target),'POINTER_BASELINE')
    d=P.deployment();new=variables(d.get('job_variables',{}));queued_gate()
    # Shared env and worker-service environment must not shadow deployment opt-in.
    shared=P.read(WORKER/'.env',65536)
    need(not any(re.match(rb'\s*(?:export\s+)?(?:POWERFLOW_REALIZED_REPORT_ENABLED|POWERFLOW_REALIZED_REPORT_ROOT)\s*=',line)for line in shared.splitlines()),'SHARED_ENV_OVERRIDE')
    service=B['services']()['powerflow-prefect-worker.service'];need(service['User']==service['Group']=='ec2-user'and service['WorkingDirectory']==str(WORKER),'WORKER_SERVICE')
    worker_pid=int(service['MainPID']);need(worker_pid>1,'WORKER_PID')
    raw=P.read('/proc/'+str(worker_pid)+'/environ',262144)
    need(not any(line.startswith(((FLAG+'=').encode(),(ROOT_KEY+'=').encode()))for line in raw.split(b'\0')),'WORKER_ENV_OVERRIDE')
    # Prefect implementation and installed terminal integration stay exact.
    for rel,digest in H.OLD_CONFIG['worker_sdk'].items():
        path=WORKER/'.venv-prod/lib/python3.14/site-packages/prefect'/rel;P.safe(path,(0,1000));need(sha(P.read(path))==digest,'PREFECT_IMPLEMENTATION_DRIFT')
    meta=WORKER/'.venv-prod/lib/python3.14/site-packages/prefect-3.7.5.dist-info/METADATA';P.safe(meta,(0,1000));need(sha(P.read(meta,262144))==H.OLD_CONFIG['prefect_metadata_sha256'],'PREFECT_VERSION_DRIFT')
    for rel in H.OLD_CONFIG['worker']:
        need(P.snap(WORKER/rel,1000,1000,0o644)[0]['sha256']==H.OLD_CONFIG['files']['worker/'+rel]['sha256'],'TERMINAL_PIPELINE_DRIFT')
    need(service.get('NoNewPrivileges')=='no','WORKER_PRIVILEGE_BASELINE')
    PREFLIGHT_STAGE='TRAVERSAL'
    parent_access();P.process(['/usr/sbin/visudo','-c'])
    PREFLIGHT_STAGE='WORKER_INVENTORY'
    before=worker_state()
    PREFLIGHT_STAGE='INPUT_BOUNDS'
    input_bounds()
    PREFLIGHT_STAGE='ENVIRONMENT_AND_RUNTIME'
    envmeta,env=P.snap(ENV,0,0,0o600);new_env=environment(env)
    venv=Path(previous['baseline']['venv']);worker_venv=WORKER/'.venv-prod'
    actual=(worker_venv/'bin/python').resolve(strict=True);P.safe(actual);need(stat.S_ISREG(actual.stat().st_mode),'WORKER_EXECUTABLE')
    PREFLIGHT_STAGE='CANDIDATE_PAYLOADS'
    for key in C['files']:raw_file(key)
    PREFLIGHT_STAGE='API_IMPORT'
    import_probe('api',venv)
    PREFLIGHT_STAGE='WORKER_IMPORT'
    import_probe('worker',worker_venv)
    PREFLIGHT_STAGE='FINAL_IDLE'
    P.idle(0)
    return {'snapshot':snapshot(),'worker':before,'env':envmeta,'env_after':sha(new_env),'old_variables':d.get('job_variables',{}),'new_variables':new,'projection':H.OLD_PLAN.stable_projection(d),'venv':str(venv),'runtime':previous['baseline']['runtime']}

def preflight_report():
    fresh()
    return {'status':'PREFLIGHT_PASS','phase':'READ_ONLY','changed':False,'release':C['release'],'transaction':C['transaction'],'linux_imports':'PASS','forecast_enabled':True,'operational_enabled':True,'report_delivery_enabled':False,'rollback_ready':True,'deployment_authorized':False}
