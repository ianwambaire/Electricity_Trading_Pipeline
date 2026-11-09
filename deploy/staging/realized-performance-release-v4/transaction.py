"""Guarded API/static/reporting-only transaction. No automatic rollback or retries."""
import copy
import http.client as http_client
import time
import uuid

PHASES={'BACKED_UP','INSTALL','READY','POINTERS','ACTIVATE','APPLIED','ROLLBACK','ROLLED_BACK'}

def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
def destination(key):
    need(key in C['files'],'DESTINATION_SCOPE')
    prefix,rel=key.split('/',1)
    return {'api':API,'static':STATIC,'worker':WORKER}[prefix]/rel

def backup_name(key,suffix):return CONTROL/(key.replace('/','__')+'.'+suffix)
def allowed_files():
    result={ENV,CONTROL/'record.json',REPORT/'contract'}|{destination(k)for k in C['files']}
    for key in ['env','pointers','variables',*C['worker_before']]:
        result.update(backup_name(key,s)for s in ['backup','independent'])
    return result

def write(path,raw,uid=0,gid=0,mode=0o644,replace=False):
    need(path in allowed_files(),'WRITE_SCOPE')
    if path.parent==REPORT:report_metadata(empty=True,partial=True)
    else:P.safe(path.parent,(0,1000)if str(path).startswith(str(WORKER)+'/')else(0,))
    need(replace or not os.path.lexists(path),'WRITE_COLLISION')
    temporary=path.parent/('.realized-'+C['transaction']+'-'+uuid.uuid4().hex)
    try:
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb')as f:
            os.fchown(f.fileno(),uid,gid);os.fchmod(f.fileno(),mode);f.write(raw);f.flush();os.fsync(f.fileno())
        if replace:os.replace(temporary,path)
        else:os.link(temporary,path,follow_symlinks=False);os.unlink(temporary)
        sync(path.parent)
        s=path.lstat();need(stat.S_ISREG(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode),s.st_nlink)==(uid,gid,mode,1)and B['read'](path,max(len(raw),1))==raw,'WRITE_VERIFY')
    finally:
        if os.path.lexists(temporary):os.unlink(temporary)

def allowed_dirs():
    result={CONTROL,API,STATIC,REPORT,REPORT/'releases'}
    for key in C['files']:
        if not key.startswith(('api/','static/')):continue
        path=destination(key);root=API if key.startswith('api/')else STATIC
        result.update(p for p in path.parents if p==root or p.is_relative_to(root))
    return result

def mkdir(path):
    need(path in allowed_dirs(),'DIRECTORY_SCOPE');P.safe(path.parent,(0,1000)if path.parent==REPORT else(0,));need(not os.path.lexists(path),'DIRECTORY_COLLISION')
    uid,gid,mode=(1000,992,0o2750)if path in {REPORT,REPORT/'releases'}else(0,0,0o700 if path==CONTROL else 0o755)
    os.mkdir(path,0o700);os.chown(path,uid,gid);os.chmod(path,mode);sync(path);sync(path.parent)
    s=path.lstat();return [s.st_dev,s.st_ino]

def record_valid(r):
    need(type(r)is dict and set(r)=={'release','transaction','binding','phase','before','roots','created_at','activated_at'},'JOURNAL_SCHEMA')
    need((r['release'],r['transaction'],r['binding'])==(C['release'],C['transaction'],C['binding'])and r['phase']in PHASES,'JOURNAL_IDENTITY')
    b=r['before'];need(set(b)=={'snapshot','worker','env','env_after','old_variables','new_variables','projection','venv','runtime'},'JOURNAL_BASELINE_SCOPE')
    need(variables(b['old_variables'])==b['new_variables']and set(b['worker'])==set(C['worker_before']),'JOURNAL_VARIABLES')
    need(set(r['roots'])<={'api','static','report','report_releases'}and all(type(v)is list and len(v)==2 and all(type(n)is int for n in v)for v in r['roots'].values()),'JOURNAL_ROOTS')
    for rel,meta in b['worker'].items():
        allowed=C['worker_before'][rel];allowed=allowed if isinstance(allowed,list)else[allowed]
        need(meta is None and None in allowed or type(meta)is dict and meta.get('sha256')in allowed and(meta.get('uid'),meta.get('gid'),meta.get('mode'))==(1000,1000,0o644),'JOURNAL_WORKER_BASELINE')
    need(H.OP.timestamp(r['created_at'])<=dt.datetime.now(dt.timezone.utc),'JOURNAL_CREATED_TIME')
    need(r['activated_at']is None or H.OP.timestamp(r['activated_at'])<=dt.datetime.now(dt.timezone.utc),'JOURNAL_TIME')
    return r

def save(r,phase):
    global PHASE
    PHASE=phase;r['phase']=phase;record_valid(r)
    write(CONTROL/'record.json',json.dumps(r,sort_keys=True).encode(),mode=0o600,replace=os.path.lexists(CONTROL/'record.json'))
def load_record():
    P.safe(CONTROL);s=CONTROL.lstat();need((s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o700),'JOURNAL_METADATA')
    return record_valid(json.loads(P.snap(CONTROL/'record.json',0,0,0o600)[1]))

def backup_values(before):
    return {'pointers':json.dumps({'api':str(OLD.API),'static':str(OLD.STATIC)},sort_keys=True).encode(),'variables':json.dumps(before['old_variables'],sort_keys=True).encode()}
def verify_backups(r):
    before=r['before'];fixed=backup_values(before)
    for key in ['env','pointers','variables',*C['worker_before']]:
        meta=before['env']if key=='env'else before['worker'].get(key)
        if key in C['worker_before']and meta is None:
            need(not any(os.path.lexists(backup_name(key,s))for s in ['backup','independent']),'UNEXPECTED_ABSENCE_BACKUP');continue
        seen=[]
        for suffix in ['backup','independent']:
            path=backup_name(key,suffix);info,raw=P.snap(path,0,0,0o600);s=path.lstat();need(s.st_nlink==1,'BACKUP_HARDLINK');seen.append((s.st_dev,s.st_ino))
            need(raw==fixed[key]if key in fixed else info['sha256']==meta['sha256']and info['bytes']==meta['bytes'],'BACKUP_BYTES')
        need(seen[0]!=seen[1],'BACKUP_NOT_INDEPENDENT')
    raw=P.snap(backup_name('env','backup'),0,0,0o600)[1];need(sha(environment(raw))==before['env_after'],'ENV_BACKUP_TARGET')

def new_trees(r,complete=False):
    for label,root,prefix in [('api',API,'api/'),('static',STATIC,'static/')]:
        if not os.path.lexists(root):need(label not in r['roots'],'CREATED_ROOT_MISSING');continue
        s=root.lstat();need(r['roots'].get(label)==[s.st_dev,s.st_ino]and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o755)and stat.S_ISDIR(s.st_mode),'CREATED_ROOT_DRIFT')
        expected={k[len(prefix):]:v['sha256']for k,v in C['files'].items()if k.startswith(prefix)};seen={};dirs={'.'};allowed={'.'}
        for rel in expected:allowed.update(p.as_posix()for p in Path(rel).parents)
        for parent,sub,files in os.walk(root,followlinks=False):
            need(len(sub)+len(files)<200,'RELEASE_TREE_BOUND')
            for name in sub:
                p=Path(parent)/name
                if p==API/'.venv-api':need(p.is_symlink()and p.lstat().st_uid==p.lstat().st_gid==0 and str(p.resolve(strict=True))==r['before']['venv'],'RUNTIME_LINK');continue
                rel=p.relative_to(root).as_posix();need(rel in allowed,'UNEXPECTED_DIRECTORY');P.safe(p);dirs.add(rel)
            for name in files:
                p=Path(parent)/name;rel=p.relative_to(root).as_posix();need(rel in expected and p.lstat().st_nlink==1,'UNEXPECTED_FILE');meta,_=P.snap(p);need(meta['sha256']==expected[rel],'RELEASE_CONTENT_DRIFT');seen[rel]=meta['sha256']
        if complete:need(seen==expected and dirs==allowed and (root!=API or(API/'.venv-api').is_symlink()),'RELEASE_INCOMPLETE')

def pointer(path,target,expected):
    need(path==P.BACKEND_LINK and target in {OLD.API,API}or path==P.STATIC_LINK and target in {OLD.STATIC,STATIC},'POINTER_SCOPE')
    s=path.lstat();need(stat.S_ISLNK(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o777)and os.readlink(path)==str(expected),'POINTER_DRIFT')
    temporary=path.parent/('.realized-pointer-'+C['transaction']+'-'+uuid.uuid4().hex)
    try:os.symlink(str(target),temporary);os.replace(temporary,path);sync(path.parent)
    finally:
        if os.path.lexists(temporary):os.unlink(temporary)
    need(path.resolve(strict=True)==target,'POINTER_VERIFY')

def patch(expected,value):
    need((expected,value)==(RBEFORE['old_variables'],RBEFORE['new_variables'])or(expected,value)==(RBEFORE['new_variables'],RBEFORE['old_variables']),'DEPLOYMENT_WRITE_SCOPE')
    d=P.deployment();need(d.get('job_variables',{})==expected and H.OLD_PLAN.stable_projection(d)==RBEFORE['projection'],'DEPLOYMENT_WRITE_DRIFT')
    c=http_client.HTTPConnection('127.0.0.1',4200,timeout=5)
    try:
        c.request('PATCH','/api/deployments/'+H.OLD_PLAN.DEPLOYMENT,body=json.dumps({'job_variables':value}),headers={'Content-Type':'application/json'})
        response=c.getresponse();need(response.status in {200,204}and len(response.read(1001))<=1000,'DEPLOYMENT_PATCH')
    finally:c.close()
    d=P.deployment();need(d.get('job_variables',{})==value and H.OLD_PLAN.stable_projection(d)==RBEFORE['projection'],'DEPLOYMENT_PATCH_VERIFY')

def restart(target):
    r=B['bounded_run'](['/usr/bin/systemctl','restart',H.OLD_PLAN.UNIT],timeout=45,limit=8192,grace=5)
    need(r['returncode']==0 and not r['failure'],'CANDIDATE_RESTART')
    ready=False
    for _ in range(10):
        try:ready=B['request'](8010,'/health')[0]==B['request'](8010,'/ready')[0]==200
        except Exception:pass
        if ready:break
        time.sleep(.5)
    need(ready,'CANDIDATE_STARTUP');G['runtime'](target);P.candidate_environment(True)

def apply():
    global CHANGED,RBEFORE
    before=fresh();need(before==fresh(),'FRESH_GATE_CHANGED');RBEFORE=before
    CHANGED=True;mkdir(CONTROL)
    r={'release':C['release'],'transaction':C['transaction'],'binding':C['binding'],'phase':'BACKED_UP','before':before,'roots':{},'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'activated_at':None}
    values=backup_values(before);values['env']=P.snap(ENV,0,0,0o600)[1]
    for rel,meta in before['worker'].items():
        if meta is not None:values[rel]=P.snap(WORKER/rel,1000,1000,0o644)[1]
    for key,raw in values.items():
        for suffix in ['backup','independent']:write(backup_name(key,suffix),raw,mode=0o600)
    verify_backups(r);save(r,'BACKED_UP');save(r,'INSTALL')
    for label,root,prefix in [('api',API,'api/'),('static',STATIC,'static/')]:
        r['roots'][label]=mkdir(root);save(r,'INSTALL')
        for key in C['files']:
            if not key.startswith(prefix):continue
            path=destination(key)
            for parent in reversed(path.parent.relative_to(root).parents):
                q=root/parent
                if not q.exists():mkdir(q)
            if not path.parent.exists():mkdir(path.parent)
            write(path,raw_file(key))
    os.symlink(before['venv'],API/'.venv-api');sync(API)
    r['roots']['report']=mkdir(REPORT);save(r,'INSTALL');r['roots']['report_releases']=mkdir(REPORT/'releases');save(r,'INSTALL')
    write(REPORT/'contract',MARKER,1000,992,0o640)
    worker_state(False)
    for key in C['files']:
        if key.startswith('worker/'):
            previous=before['worker'][key[7:]]
            if previous is None or previous['sha256']!=C['files'][key]['sha256']:write(destination(key),raw_file(key),1000,1000,0o644,replace=previous is not None)
    worker_state(True);new_trees(r,True);report_metadata(r,empty=True);verify_backups(r)
    need(snapshot()==before['snapshot'],'PRESERVATION_CHANGED_BEFORE_POINTERS');save(r,'READY')
    P.idle(0);queued_gate();need(P.deployment().get('job_variables',{})==before['old_variables'],'PRE_ACTIVATION_VARIABLE_DRIFT')
    write(ENV,environment(values['env']),mode=0o600,replace=True);save(r,'POINTERS')
    pointer(P.BACKEND_LINK,API,OLD.API);pointer(P.STATIC_LINK,STATIC,OLD.STATIC);restart(API)
    deployment_checks(r,enabled=False)
    # Last mutation affecting normal scheduled execution. No flow is triggered.
    P.idle(0);verify_backups(r);queued_gate();save(r,'ACTIVATE');patch(before['old_variables'],before['new_variables'])
    r['activated_at']=dt.datetime.now(dt.timezone.utc).isoformat();deployment_checks(r,enabled=True)
    verify_backups(r);new_trees(r,True);save(r,'APPLIED')
    return {'status':'APPLIED','phase':'APPLIED','changed':True,'release':C['release'],'transaction':C['transaction'],'report_delivery_enabled':True,'forecast_enabled':True,'operational_enabled':True,'rollback_ready':True,'natural_run':'PENDING','browser':'PENDING_OWNER'}

def rollback():
    global CHANGED,RBEFORE
    r=load_record();need(r['phase']not in {'ROLLBACK','ROLLED_BACK'},'ROLLBACK_NOT_APPLICABLE');before=r['before'];RBEFORE=before
    P.idle(0);verify_backups(r);new_trees(r);OLD.tree_state(OLD.load_record(),complete=True)
    # Unknown state is never overwritten, including a partial apply.
    for rel,meta in before['worker'].items():
        path=WORKER/rel;allowed=[C['files']['worker/'+rel]['sha256']]+([meta['sha256']]if meta else[])
        if os.path.lexists(path):need(P.snap(path,1000,1000,0o644)[0]['sha256']in allowed,'ROLLBACK_WORKER_DRIFT')
        else:need(meta is None,'ROLLBACK_WORKER_MISSING')
    d=P.deployment();need(d.get('job_variables',{})in[before['old_variables'],before['new_variables']]and H.OLD_PLAN.stable_projection(d)==before['projection'],'ROLLBACK_POLICY_DRIFT')
    need(P.snap(ENV,0,0,0o600)[0]['sha256']in{before['env']['sha256'],before['env_after']},'ROLLBACK_ENV_DRIFT')
    protected(r,allow_advance=True);report_metadata(r,partial=True)
    for path,allowed in [(P.BACKEND_LINK,{OLD.API,API}),(P.STATIC_LINK,{OLD.STATIC,STATIC})]:
        s=path.lstat();need(stat.S_ISLNK(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o777)and Path(os.readlink(path))in allowed,'ROLLBACK_POINTER_DRIFT')
    CHANGED=True;save(r,'ROLLBACK')
    if d.get('job_variables',{})==before['new_variables']:patch(before['new_variables'],before['old_variables'])
    P.idle(0)
    for rel,meta in before['worker'].items():
        path=WORKER/rel
        if meta is None:
            if os.path.lexists(path):os.unlink(path);sync(path.parent)
        elif P.snap(path,1000,1000,0o644)[0]['sha256']!=meta['sha256']:write(path,P.snap(backup_name(rel,'backup'),0,0,0o600)[1],1000,1000,0o644,replace=True)
    switched=P.BACKEND_LINK.resolve(strict=True)!=OLD.API
    changed_env=P.snap(ENV,0,0,0o600)[0]['sha256']!=before['env']['sha256']
    if changed_env:write(ENV,P.snap(backup_name('env','backup'),0,0,0o600)[1],mode=0o600,replace=True)
    for path,target in [(P.BACKEND_LINK,OLD.API),(P.STATIC_LINK,OLD.STATIC)]:
        actual=path.resolve(strict=True)
        if actual!=target:pointer(path,target,actual)
    if switched or changed_env:restart(OLD.API)
    else:G['runtime'](OLD.API);P.candidate_environment(True)
    worker_state(False);need(P.deployment().get('job_variables',{})==before['old_variables'],'ROLLBACK_FLAG_VERIFY');report_environment(False)
    protected(r,allow_advance=True);OLD.public_operations();OLD.forecast_checks();verify_backups(r);save(r,'ROLLED_BACK')
    return {'status':'ROLLED_BACK','phase':'ROLLED_BACK','changed':True,'transaction':C['transaction'],'report_delivery_enabled':False,'forecast_enabled':True,'operational_enabled':True,'retained_report_store':True,'rollback_ready':True}
