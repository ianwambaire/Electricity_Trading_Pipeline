"""Guarded apply/independent rollback. No auto retry, rollback, inference or publish.
Only CONFIG inventory, fixed pointers/env/deployment flag and private journal mutate.
"""
import base64
import copy
import json
import os
from pathlib import Path
import stat
import time
import uuid

P=PREFLIGHT
PHASE='PREFLIGHT'
CHANGED=False


def need(ok,code):PLAN.need(ok,code)
def raw_file(key):
    item=CONFIG['files'][key]
    if 'copy_from' in item:
        source=Path(item['copy_from']);need(source.is_relative_to(P.OLD_STATIC),'REUSE_SOURCE_SCOPE')
        _,raw=P.snap(source)
    else:raw=base64.b64decode(item['base64'],validate=True)
    need(len(raw)==item['bytes'] and PLAN.sha(raw)==item['sha256'],'PAYLOAD_HASH')
    return raw


def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def destinations():
    result={P.ENV,P.LAUNCHER,P.RULE,P.STORE/'contract',P.CONTROL/'record.json'}
    for key in CONFIG['files']:
        for prefix,root in [('worker/',P.PRODUCTION),('api/',P.API),('static/',P.STATIC),('helper/',P.TOOLS)]:
            if key.startswith(prefix):result.add(root/key[len(prefix):])
    for key in ['api_env',*CONFIG['worker']]:
        for suffix in ['.backup','.independent']:result.add(P.CONTROL/(key.replace('/','__')+suffix))
    return result


def write(path,raw,uid=0,gid=0,mode=0o600,exclusive=False):
    need(path in destinations(),'WRITE_SCOPE')
    P.safe(path.parent,(0,1000) if str(path).startswith(str(P.PRODUCTION)+'/') else (0,))
    if exclusive:need(not os.path.lexists(path),'WRITE_COLLISION')
    pending=path.parent/('.op-release-'+PLAN.TRANSACTION+'-'+uuid.uuid4().hex)
    with os.fdopen(os.open(pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode),'wb') as f:
        os.fchown(f.fileno(),uid,gid);os.fchmod(f.fileno(),mode);f.write(raw);f.flush();os.fsync(f.fileno())
    os.replace(pending,path);sync(path.parent)
    snap,actual=P.snap(path,uid,gid,mode);need(actual==raw,'WRITE_VERIFY')


def mkdir(path,uid=0,gid=0,mode=0o755):
    allowed={P.CONTROL,P.STORE,P.STORE/'releases',P.API,P.STATIC,P.TOOLS}
    for p in destinations():
        for root in [P.API,P.STATIC,P.TOOLS]:
            if p.is_relative_to(root):allowed.update(q for q in p.parents if q==root or q.is_relative_to(root))
    need(path in allowed,'DIRECTORY_SCOPE')
    P.safe(path.parent);need(not os.path.lexists(path),'DIRECTORY_COLLISION')
    path.mkdir(mode=0o700);os.chown(path,uid,gid);os.chmod(path,mode);sync(path);sync(path.parent)


def save(record):
    PLAN.record_valid(record,CONFIG);write(P.CONTROL/'record.json',json.dumps(record,sort_keys=True).encode())


def checkpoint(record,phase):
    global PHASE
    PHASE=phase;record['phase']=phase;save(record)


def patch(value):
    # The sole remote configuration mutation: this exact deployment's job_variables.
    import http.client
    c=http.client.HTTPConnection('127.0.0.1',4200,timeout=5)
    try:
        c.request('PATCH','/api/deployments/'+PLAN.DEPLOYMENT,body=json.dumps({'job_variables':value}),headers={'Content-Type':'application/json'})
        r=c.getresponse();need(r.status in (200,204) and len(r.read(1001))<=1000,'DEPLOYMENT_PATCH')
    finally:c.close()


def pointer(path,target):
    need(path==P.BACKEND_LINK and target in [P.OLD_API,P.API] or path==P.STATIC_LINK and target in [P.OLD_STATIC,P.STATIC],'POINTER_SCOPE')
    P.safe(path.parent);pending=path.parent/('.op-pointer-'+uuid.uuid4().hex)
    os.symlink(str(target),pending);os.replace(pending,path);sync(path.parent)
    need(path.resolve(strict=True)==target,'POINTER_VERIFY')


def restart():
    r=BASE['bounded_run'](['/usr/bin/systemctl','restart',PLAN.UNIT],timeout=45,limit=16384,grace=5)
    need(r['returncode']==0 and r['failure'] is None,'CANDIDATE_RESTART')
    deadline=time.monotonic()+15
    for _ in range(10):
        try:
            if BASE['request'](8010,'/health')[0]==BASE['request'](8010,'/ready')[0]==200:return
        except Exception:pass
        if time.monotonic()>=deadline:break
        time.sleep(.5)
    need(False,'STARTUP_READINESS')


def install(root,prefix,mode=0o644):
    need((prefix,root) in [('api/',P.API),('static/',P.STATIC),('helper/',P.TOOLS)],'INSTALL_SCOPE')
    mkdir(root,mode=0o700 if root==P.TOOLS else 0o755)
    for key,item in sorted(CONFIG['files'].items()):
        if not key.startswith(prefix):continue
        relative=key[len(prefix):];path=root/relative
        for ancestor in reversed(path.parent.relative_to(root).parents):
            q=root/ancestor
            if not q.exists():mkdir(q,mode=0o700 if root==P.TOOLS else 0o755)
        if not path.parent.exists():mkdir(path.parent,mode=0o700 if root==P.TOOLS else 0o755)
        write(path,raw_file(key),mode=mode,exclusive=True)


def installed(record):
    for rel,spec in CONFIG['worker'].items():
        value,_=P.snap(P.PRODUCTION/rel,1000,1000,0o644);need(value['sha256']==CONFIG['files']['worker/'+rel]['sha256'],'INSTALLED_WORKER')
    for root,prefix in [(P.API,'api/'),(P.STATIC,'static/')]:
        P.assert_files(root,{k[len(prefix):]:v['sha256'] for k,v in CONFIG['files'].items() if k.startswith(prefix)})
    need((P.API/'.venv-api').resolve(strict=True)==Path(record['venv']),'INSTALLED_VENV')
    for key in CONFIG['files']:
        if key.startswith('helper/'):
            value,_=P.snap(P.TOOLS/key[7:],0,0,0o600);need(value['sha256']==CONFIG['files'][key]['sha256'],'INSTALLED_HELPER')
    for path,key,mode in [(P.LAUNCHER,'launcher',0o755),(P.RULE,'sudoers',0o440)]:
        value,_=P.snap(path,0,0,mode);need(value['sha256']==CONFIG['files'][key]['sha256'],'INSTALLED_PRIVILEGE')
    for directory in (P.STORE,P.STORE/'releases'):
        P.safe(directory);s=directory.lstat();need((s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,992,0o750),'STORE_PERMISSIONS')
    value,raw=P.snap(P.STORE/'contract',0,992,0o640);need(raw==b'powerflow-operational-evidence-v1\n','STORE_NAMESPACE')
    P.process(['/usr/sbin/visudo','-c'])


def effective_access():
    # Read/traverse/non-write in the candidate mount namespace as its real UID/GID.
    pid=int(BASE['services']()[PLAN.UNIT]['MainPID']);need(pid>1,'CANDIDATE_PID')
    script="import os,pathlib; r=pathlib.Path('/srv/powerflow/operational-publications'); assert all(os.access(p,os.R_OK|os.X_OK) and not os.access(p,os.W_OK) for p in (r,r/'releases')); assert (r/'contract').read_bytes()==b'powerflow-operational-evidence-v1\\n'"
    argv=['/usr/bin/nsenter','--mount=/proc/'+str(pid)+'/ns/mnt','--','/usr/bin/setpriv','--reuid=992','--regid=992','--clear-groups','/usr/bin/python3','-I','-S','-B','-c',script]
    r=BASE['bounded_run'](argv,timeout=10,limit=4096,grace=5);need(r['returncode']==0 and not r['failure'],'CANDIDATE_STORE_ACCESS')


def acceptance(record):
    GUARD['runtime'](P.API);need(BASE['request'](8010,'/health')[0]==BASE['request'](8010,'/ready')[0]==200,'ACTIVATED_HEALTH')
    effective_access();P.candidate_environment(True)
    pub=P.http('/api/operations/current');pipeline=P.http('/api/pipeline/current')
    for code,headers,body in (pub,pipeline):
        need(code==200 and headers['cache-control']=='no-store' and body.get('status')=='MISSING' and body.get('current_execution')is None and 'admin' not in body,'CURRENT_EMPTY_CONTRACT')
    need(BASE['request'](443,'/',tls=True)[0]==200 and PLAN.sha(BASE['request'](443,'/',tls=True)[1])==CONFIG['files']['static/index.html']['sha256'],'STATIC_ROUTING')
    need(pub[2]==pipeline[2] and P.http('/api/admin/operations/current')[0]==401,'ROLE_OR_CROSS_ENDPOINT')
    # Existing forecast pointer/files must remain byte-identical; validity may
    # legitimately expire during the release. Never publish to manufacture200.
    code,headers,body=P.http('/api/forecast/next24');need(headers['cache-control']=='no-store','FORECAST_CACHE')
    if code==200:need(body.get('row_count')==24 and len(body.get('forecasts',[]))==24 and body.get('publication',{}).get('status')=='VALID','FORECAST_200')
    else:need(code==503 and body=={'detail':{'code':'FORECAST_WITHHELD'}},'FORECAST_WITHHELD')
    need(GUARD['production']()==record['production'] and P.forecast_fingerprint()==record['forecast'],'PRESERVATION')


def apply():
    global CHANGED,PHASE
    baseline=P.initial();again=P.initial();need(baseline==again,'PREFLIGHT_DRIFT')
    # First mutation: private transaction journal. No overwrite/reuse.
    PHASE='BACKUP';CHANGED=True;mkdir(P.CONTROL,mode=0o700)
    record=dict(baseline,transaction=PLAN.TRANSACTION,release=PLAN.RELEASE,phase='BACKED_UP',old_backend=str(P.OLD_API),old_static=str(P.OLD_STATIC))
    for key,before in baseline['backups'].items():
        if before is None:continue
        path=P.ENV if key=='api_env' else P.PRODUCTION/key
        value,raw=P.snap(path,before['uid'],before['gid'],before['mode']);need(value==before,'BACKUP_DRIFT')
        name=key.replace('/','__')
        write(P.CONTROL/(name+'.backup'),raw,exclusive=True);write(P.CONTROL/(name+'.independent'),raw,exclusive=True)
        a=P.CONTROL/(name+'.backup');b=P.CONTROL/(name+'.independent')
        need(a.stat().st_ino!=b.stat().st_ino and PLAN.sha(P.read(a))==PLAN.sha(P.read(b))==before['sha256'],'INDEPENDENT_BACKUP')
    save(record);checkpoint(record,'INSTALL')
    install(P.API,'api/');os.symlink(record['venv'],P.API/'.venv-api');sync(P.API)
    install(P.STATIC,'static/');install(P.TOOLS,'helper/',mode=0o600)
    mkdir(P.STORE,gid=992,mode=0o750);mkdir(P.STORE/'releases',gid=992,mode=0o750)
    write(P.STORE/'contract',b'powerflow-operational-evidence-v1\n',gid=992,mode=0o640,exclusive=True)
    for rel in CONFIG['worker']:write(P.PRODUCTION/rel,raw_file('worker/'+rel),uid=1000,gid=1000,mode=0o644)
    write(P.LAUNCHER,raw_file('launcher'),mode=0o755,exclusive=True);write(P.RULE,raw_file('sudoers'),mode=0o440,exclusive=True)
    installed(record);P.idle(0)
    need(P.deployment().get('job_variables',{})==record['old_variables'] and PLAN.stable_projection(P.deployment())==record['projection'],'PRE_ACTIVATION_DRIFT')
    need(P.BACKEND_LINK.resolve(strict=True)==P.OLD_API and P.STATIC_LINK.resolve(strict=True)==P.OLD_STATIC,'POINTER_DRIFT')
    checkpoint(record,'POINTERS')
    old_env=P.read(P.CONTROL/'api_env.backup');need(PLAN.sha(P.read(P.ENV))==CONFIG['env_before'],'ENV_DRIFT')
    write(P.ENV,PLAN.environment(old_env,CONFIG['env_before']))
    pointer(P.BACKEND_LINK,P.API);restart()
    pointer(P.STATIC_LINK,P.STATIC)
    acceptance(record);P.idle(0)
    need(PLAN.stable_projection(P.deployment())==record['projection'] and P.deployment().get('job_variables',{})==record['old_variables'],'ACTIVATION_BASELINE')
    # Explicit feature flag is the final activation; schedule untouched.
    import datetime
    checkpoint(record,'ACTIVATE');activation_start=datetime.datetime.now(datetime.timezone.utc).isoformat();patch(record['new_variables'])
    need(P.deployment().get('job_variables',{})==record['new_variables'] and PLAN.stable_projection(P.deployment())==record['projection'] and P.pool()==record['pool_sha256'],'ACTIVATION_VERIFY')
    record['activation_bounds']=[activation_start,datetime.datetime.now(datetime.timezone.utc).isoformat()]
    acceptance(record);checkpoint(record,'APPLIED')
    return {'status':'APPLIED','phase':'APPLIED','changed':True,'operational_enabled':True,'forecast_preserved':True,'authenticated_admin':'PENDING_OWNER','natural_run_acceptance':'PENDING'}


def rollback():
    global CHANGED
    # Entire drift/backup/metadata validation before any rollback mutation.
    P.safe(P.CONTROL);_,record_raw=P.snap(P.CONTROL/'record.json',0,0,0o600);record=json.loads(record_raw);PLAN.record_valid(record,CONFIG)
    P.assert_files(P.OLD_API,CONFIG['old_api']);need(GUARD['inventory'](P.OLD_STATIC)==CONFIG['old_static_inventory'],'ROLLBACK_OLD_STATIC')
    need(str(BASE['canonical'](P.OLD_API/'.venv-api',Path('/opt/powerflow/releases')))==record['venv'] and P.baseline_installation()==record['runtime'],'ROLLBACK_RUNTIME_DRIFT')
    need(P.pool()==record['pool_sha256'],'ROLLBACK_POOL_DRIFT')
    need(record['phase']!='ROLLED_BACK','ROLLBACK_CONSUMED');P.idle(0)
    d=P.deployment();need(d.get('job_variables',{}) in [record['old_variables'],record['new_variables']] and PLAN.stable_projection(d)==record['projection'],'ROLLBACK_DEPLOYMENT_DRIFT')
    for key,before in record['backups'].items():
        if before is not None:
            name=key.replace('/','__')
            for suffix in ('.backup','.independent'):
                value,raw=P.snap(P.CONTROL/(name+suffix),0,0,0o600);need(value['sha256']==before['sha256'],'ROLLBACK_BACKUP')
        path=P.ENV if key=='api_env' else P.PRODUCTION/key
        if not os.path.lexists(path):need(before is None,'ROLLBACK_MISSING_FILE');continue
        target=CONFIG['env_after'] if key=='api_env' else CONFIG['files']['worker/'+key]['sha256']
        uid=0 if key=='api_env' else 1000;mode=0o600 if key=='api_env' else 0o644
        value,_=P.snap(path,uid,uid,mode)
        need(value['sha256'] in [target,before['sha256'] if before else None],'ROLLBACK_FILE_DRIFT')
    for path,key,mode in [(P.LAUNCHER,'launcher',0o755),(P.RULE,'sudoers',0o440)]:
        if os.path.lexists(path):
            value,_=P.snap(path,0,0,mode);need(value['sha256']==CONFIG['files'][key]['sha256'],'ROLLBACK_PRIVILEGE_DRIFT')
    for link,old,new in [(P.BACKEND_LINK,P.OLD_API,P.API),(P.STATIC_LINK,P.OLD_STATIC,P.STATIC)]:need(link.resolve(strict=True) in [old,new],'ROLLBACK_POINTER_DRIFT')
    for root,prefix in [(P.API,'api/'),(P.STATIC,'static/'),(P.TOOLS,'helper/')]:P.partial_tree(root,prefix)
    P.forecast_configuration()
    rollback_production=GUARD['production']();rollback_forecast=P.forecast_fingerprint()
    CHANGED=True;checkpoint(record,'ROLLBACK');patch(record['old_variables'])
    need(P.deployment().get('job_variables',{})==record['old_variables'],'DISABLE_VERIFY')
    for key,before in record['backups'].items():
        path=P.ENV if key=='api_env' else P.PRODUCTION/key
        if before is None:
            if os.path.lexists(path):path.unlink();sync(path.parent)
        else:write(path,P.read(P.CONTROL/(key.replace('/','__')+'.backup')),before['uid'],before['gid'],before['mode'])
    pointer(P.BACKEND_LINK,P.OLD_API);restart();pointer(P.STATIC_LINK,P.OLD_STATIC)
    for path in [P.RULE,P.LAUNCHER]:
        if os.path.lexists(path):path.unlink();sync(path.parent)
    for key,before in record['backups'].items():
        path=P.ENV if key=='api_env' else P.PRODUCTION/key
        if before is None:need(not os.path.lexists(path),'RESTORE_ABSENCE')
        else:need(P.snap(path,before['uid'],before['gid'],before['mode'])[0]==before,'RESTORE_BYTES_METADATA')
    P.process(['/usr/sbin/visudo','-c']);GUARD['runtime'](P.OLD_API);P.candidate_environment(False)
    need(BASE['request'](8010,'/health')[0]==BASE['request'](8010,'/ready')[0]==200,'RESTORED_HEALTH')
    need(GUARD['production']()==rollback_production and P.forecast_fingerprint()==rollback_forecast and PLAN.stable_projection(P.deployment())==record['projection'],'RESTORED_PRESERVATION')
    checkpoint(record,'ROLLED_BACK')
    return {'status':'ROLLED_BACK','changed':True,'operational_enabled':False,'forecast_preserved':True,'retained_immutable_releases_and_store':True}
