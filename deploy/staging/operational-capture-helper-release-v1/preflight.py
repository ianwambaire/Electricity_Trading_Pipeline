"""Read-only fresh guards and import probe. No installation/activation functions."""
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys
import types

NEW=Path(C['new_root']);CONTROL=Path(C['control'])
PHASE='READ_ONLY';CHANGED=False

def need(ok,code):OLD_PLAN.need(ok,code)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def artifact(key):
    need(key in C['files'],'ARTIFACT_SCOPE');item=C['files'][key]
    raw=base64.b64decode(item['base64'],validate=True)
    need(len(raw)==item['bytes'] and sha(raw)==item['sha256'],'ARTIFACT_HASH');return raw

def target(key):
    need(key in C['files'],'DESTINATION_SCOPE')
    if key=='launcher':return P.LAUNCHER
    if key=='sudoers':return P.RULE
    rel=key[7:];need(key.startswith('helper/') and not Path(rel).is_absolute() and '..'not in Path(rel).parts,'DESTINATION_SCOPE')
    return NEW/rel

def tree(root,expected,partial=False):
    P.safe(root);s=root.lstat();need(stat.S_ISDIR(s.st_mode) and (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o700),'HELPER_ROOT_METADATA')
    seen={};directories={'.'}
    for parent,dirs,files in os.walk(root,followlinks=False):
        need(len(dirs)+len(files)<=16 and len(seen)<=8,'HELPER_INVENTORY_BOUND')
        for name in dirs:
            path=Path(parent)/name;need(path==root/'shared','HELPER_DIRECTORY_SCOPE');P.safe(path);s=path.lstat()
            need(stat.S_ISDIR(s.st_mode) and (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o700),'HELPER_DIRECTORY_METADATA');directories.add('shared')
        for name in files:
            path=Path(parent)/name;rel=path.relative_to(root).as_posix();need(rel in expected,'HELPER_INVENTORY')
            need(path.lstat().st_nlink==1,'HELPER_HARDLINK');meta,_=P.snap(path,0,0,0o600);need(meta['sha256']==expected[rel],'HELPER_FILE_HASH');seen[rel]=meta['sha256']
    need(partial or seen==expected and directories=={'.','shared'},'HELPER_INCOMPLETE');return seen

def expected_new():return {k[7:]:v['sha256'] for k,v in C['files'].items() if k.startswith('helper/')}
def expected_old():return {k[7:]:v['sha256'] for k,v in OLD_CONFIG['files'].items() if k.startswith('helper/')}

def memory_probe():
    name='operational_helper_probe';need(name not in sys.modules,'IMPORT_NAMESPACE_CONFLICT')
    package=types.ModuleType(name);package.__path__=[];sys.modules[name]=package
    try:
        exec(compile(artifact('helper/shared/__init__.py'),'<verified-helper-package>','exec'),package.__dict__)
        for leaf in ['forecast_publication','operational_evidence','operational_evidence_store','operational_evidence_producer','operational_capture']:
            key='helper/shared/'+leaf+'.py';m=types.ModuleType(name+'.'+leaf);m.__package__=name;sys.modules[m.__name__]=m
            exec(compile(artifact(key),'<verified-helper-'+leaf+'>','exec'),m.__dict__)
        producer=sys.modules[name+'.operational_evidence_producer'];contract=sys.modules[name+'.operational_evidence']
        need(producer.persisted_issue_timestamp('2026-11-07 06:00:00+00:00').isoformat()=='2026-11-07T06:00:00+00:00','CORRECTION_IMPORT')
        try:contract.timestamp('2026-11-07 06:00:00+00:00')
        except contract.InvalidEvidence:pass
        else:need(False,'CONTRACT_WEAKENED')
    finally:
        for key in list(sys.modules):
            if key==name or key.startswith(name+'.'):del sys.modules[key]

def installed_probe():
    # Isolated load() only. Never call the returned main/capture/publisher.
    script="import runpy,sys; b=runpy.run_path("+repr(str(NEW/'bootstrap.py'))+",run_name='verified_import_probe'); b['load'](); p=sys.modules['shared.operational_evidence_producer']; assert p.persisted_issue_timestamp('2026-11-07 06:00:00+00:00').isoformat()=='2026-11-07T06:00:00+00:00'; print('HELPER_IMPORT_PASS')"
    r=BASE['bounded_run'](['/usr/bin/python3','-I','-S','-B','-'],input=script.encode(),timeout=10,limit=4096,grace=5)
    need(r['returncode']==0 and not r['failure'] and r['stdout']==b'HELPER_IMPORT_PASS\n','INSTALLED_IMPORT_COMPATIBILITY')

def entries(path,limit):
    result=[]
    with os.scandir(path) as iterator:
        for entry in iterator:
            need(len(result)<limit,'DIRECTORY_BOUND');result.append(Path(path)/entry.name)
    return result

def store_snapshot():
    for path in [P.STORE,P.STORE/'releases']:
        P.safe(path);s=path.lstat();need(stat.S_ISDIR(s.st_mode) and (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,992,0o750),'STORE_METADATA')
    marker,raw=P.snap(P.STORE/'contract',0,992,0o640);need(raw==b'powerflow-operational-evidence-v1\n','STORE_NAMESPACE')
    names={p.name for p in entries(P.STORE,4)};need(names<={'contract','releases','current','.publication.lock'},'STORE_ENTRY_SCOPE')
    result={'contract':marker['sha256'],'current':None,'releases':{}}
    for path in sorted(entries(P.STORE/'releases',256)):
        need(len(result['releases'])<256 and re.fullmatch('[0-9a-f]{64}',path.name)is not None,'STORE_INVENTORY_BOUND')
        P.safe(path);s=path.lstat();need(stat.S_ISDIR(s.st_mode) and (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,992,0o750),'STORE_RELEASE_METADATA')
        need({p.name for p in entries(path,1)}=={'evidence.json'},'STORE_RELEASE_INVENTORY')
        need((path/'evidence.json').lstat().st_size<=16384,'STORE_EVIDENCE_BOUND')
        meta,raw=P.snap(path/'evidence.json',0,992,0o640);need(meta['sha256']==path.name,'STORE_RELEASE_HASH');OP.validate(raw,path.name,dt.datetime.now(dt.timezone.utc))
        result['releases'][path.name]=meta['sha256']
    if 'current'in names:
        _,raw=P.snap(P.STORE/'current',0,992,0o640);need(re.fullmatch(b'[0-9a-f]{64}\n',raw)is not None,'STORE_POINTER')
        result['current']=raw.decode().strip();need(result['current']in result['releases'],'STORE_POINTER_TARGET')
    if '.publication.lock'in names:
        P.safe(P.STORE/'.publication.lock');s=(P.STORE/'.publication.lock').lstat()
        need(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_uid==0 and s.st_gid in {0,992} and stat.S_IMODE(s.st_mode)==0o600,'STORE_LOCK_METADATA')
    return sha(json.dumps(result,sort_keys=True).encode())

def health():
    need(BASE['request'](8010,'/health')[0]==BASE['request'](8010,'/ready')[0]==200,'CANDIDATE_HEALTH')
    need(BASE['request'](8000,'/health')[0]==BASE['request'](8501,'/_stcore/health')[0]==200,'PRODUCTION_HEALTH')
    code,raw=BASE['request'](443,'/',tls=True);need(code==200 and sha(raw)==OLD_CONFIG['files']['static/index.html']['sha256'],'STAGING_STATIC_HEALTH')
    need(P.http('/api/health')[0]==200,'STAGING_API_HEALTH')
    public=P.http('/api/operations/current');pipeline=P.http('/api/pipeline/current')
    need(public[0]==pipeline[0]==200 and public[1]['cache-control']==pipeline[1]['cache-control']=='no-store' and public[2]==pipeline[2] and 'admin'not in public[2],'CURRENT_ROUTING')
    need(P.http('/api/admin/operations/current')[0]==401,'ADMIN_BOUNDARY')
    code,headers,body=P.http('/api/forecast/next24');need(headers['cache-control']=='no-store','FORECAST_CACHE')
    need(code==200 and body.get('row_count')==24 and len(body.get('forecasts',[]))==24 and body.get('publication',{}).get('status')=='VALID' or code==503 and body=={'detail':{'code':'FORECAST_WITHHELD'}},'FORECAST_READBACK')

def idle():
    P.idle(sum(v['bytes'] for v in C['files'].values())*3)
    for path in entries(Path('/proc'),32768):
        if not path.name.isdigit() or int(path.name)==os.getpid():continue
        try:raw=P.read(path/'cmdline',65536)
        except FileNotFoundError:continue
        need(str(NEW/'bootstrap.py').encode()not in raw,'ACTIVE_NEW_HELPER')

def common(privilege='old'):
    need(os.getuid()==os.geteuid()==0 and sys.platform=='linux' and sys.version_info>=(3,9) and os.uname().machine=='x86_64','HOST_RUNTIME')
    need(hasattr(os,'O_NOATIME') and Path('/proc/self/fd').is_dir(),'PROCFS')
    for name,expected in [('ec2-user',(1000,1000)),('powerflow-api',(992,992))]:
        user=pwd.getpwnam(name);need((user.pw_uid,user.pw_gid)==expected,'SERVICE_IDENTITY')
    idle()
    old_meta,raw=P.snap(P.CONTROL/'record.json',0,0,0o600);record=json.loads(raw);OLD_PLAN.record_valid(record,OLD_CONFIG)
    need(record['phase']=='APPLIED' and record.get('activation_bounds'),'V5_NOT_APPLIED')
    d=P.deployment();need(d.get('job_variables',{})==record['new_variables'] and OLD_PLAN.stable_projection(d)==record['projection'],'DEPLOYMENT_DRIFT')
    env=d.get('job_variables',{}).get('env',{});need(env.get(OLD_PLAN.FLAG)==env.get(OLD_PLAN.FORECAST_FLAG)=='true','DELIVERY_FLAGS')
    queued=BASE['api']('/flow_runs/filter',{'deployments':{'id':{'any_':[OLD_PLAN.DEPLOYMENT]}},'flow_runs':{'state':{'type':{'any_':['SCHEDULED']}}},'limit':100})
    need(type(queued)is list and len(queued)<100 and all(all(((r.get('job_variables')or{}).get('env')or{}).get(k,'true')=='true' for k in [OLD_PLAN.FLAG,OLD_PLAN.FORECAST_FLAG]) for r in queued),'QUEUED_OVERRIDE')
    for rel,digest in OLD_CONFIG['worker_sdk'].items():
        path=P.PRODUCTION/'.venv-prod/lib/python3.14/site-packages/prefect'/rel;P.safe(path,(0,1000));need(sha(P.read(path))==digest,'PREFECT_IMPLEMENTATION_DRIFT')
    path=P.PRODUCTION/'.venv-prod/lib/python3.14/site-packages/prefect-3.7.5.dist-info/METADATA';P.safe(path,(0,1000));need(sha(P.read(path,262144))==OLD_CONFIG['prefect_metadata_sha256'],'PREFECT_VERSION_DRIFT')
    for rel in OLD_CONFIG['worker']:
        meta,_=P.snap(P.PRODUCTION/rel,1000,1000,0o644);need(meta['sha256']==OLD_CONFIG['files']['worker/'+rel]['sha256'],'WORKER_SOURCE_DRIFT')
    worker=BASE['services']()['powerflow-prefect-worker.service'];need(worker.get('User')==worker.get('Group')=='ec2-user' and worker.get('NoNewPrivileges')=='no' and worker.get('WorkingDirectory')==str(P.PRODUCTION),'WORKER_IDENTITY')
    for path in ['/usr/bin/python3','/usr/bin/sudo','/usr/sbin/visudo','/usr/bin/timeout','/usr/bin/env','/bin/sh']:
        actual=Path(path).resolve(strict=True);P.safe(actual);need(stat.S_ISREG(actual.stat().st_mode),'SYSTEM_RUNTIME')
    for link,expected in [(P.BACKEND_LINK,P.API),(P.STATIC_LINK,P.STATIC)]:
        need(link.is_symlink() and link.lstat().st_uid==0 and link.resolve(strict=True)==expected,'V5_POINTER_DRIFT')
    P.assert_files(P.API,{k[4:]:v['sha256'] for k,v in OLD_CONFIG['files'].items() if k.startswith('api/')})
    need(GUARD['inventory'](P.STATIC)=={k[7:]:v['sha256'] for k,v in OLD_CONFIG['files'].items() if k.startswith('static/')},'STATIC_DRIFT')
    need(P.snap(P.NGINX,0,0,0o644)[0]['sha256']==OLD_CONFIG['nginx_after'],'NGINX_DRIFT')
    need(P.snap(P.ENV,0,0,0o600)[0]['sha256']==OLD_CONFIG['env_after'],'API_ENV_DRIFT')
    tree(Path(C['old_root']),expected_old())
    privileges={}
    for key in ['launcher','sudoers']:
        item=C['old_files'][key];meta,_=P.snap(target(key),0,0,item['mode'])
        allowed={item['sha256']} if privilege=='old' else {C['files'][key]['sha256']} if privilege=='new' else {item['sha256'],C['files'][key]['sha256']}
        need(meta['sha256']in allowed,'PRIVILEGE_DRIFT');privileges[key]=meta
    P.process(['/usr/sbin/visudo','-cf','-'],input=artifact('sudoers'));P.process(['/usr/sbin/visudo','-c'])
    P.forecast_configuration();GUARD['runtime'](P.API);P.candidate_environment(True);pool=P.pool();need(pool==record['pool_sha256'],'WORK_POOL_DRIFT');memory_probe();health()
    return {'production':P.production(),'forecast':P.forecast_fingerprint(),'store':store_snapshot(),'policy':sha(json.dumps({'variables':d.get('job_variables',{}),'projection':OLD_PLAN.stable_projection(d),'pool':pool},sort_keys=True).encode()),'v5_record':old_meta['sha256'],'privileges':privileges}

def fresh():
    need(not os.path.lexists(NEW) and not os.path.lexists(CONTROL),'TRANSACTION_OR_DESTINATION_EXISTS')
    P.safe(NEW.parent);P.safe(CONTROL.parent)
    return common('old')

def preflight_report():
    fresh()
    return {'status':'PREFLIGHT_PASS','phase':'READ_ONLY','changed':False,'release':C['release'],'transaction':C['transaction'],'operational_enabled':True,'forecast_enabled':True,'activation':'DEFERRED_TO_AUTHORIZED_APPLY','rollback':'INDEPENDENT_BACKUPS_REQUIRED_AT_APPLY'}
