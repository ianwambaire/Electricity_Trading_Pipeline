"""Guarded staging pointers/new trees only. No Prefect/config/publisher mutation."""
import json
import os
import stat
import time
import uuid

PHASE='PREFLIGHT';CHANGED=False
PHASES={'BACKED_UP','INSTALL','READY','POINTERS','APPLIED','ROLLBACK','ROLLED_BACK'}
def sync(p):
    fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
def allowed_files():
    return {CONTROL/'record.json',CONTROL/'pointers.backup',CONTROL/'pointers.independent'}|{(API if k.startswith('api/') else STATIC)/k.split('/',1)[1] for k in C['files']}
def write(p,raw,mode=0o644,replace=False):
    need(p in allowed_files(),'WRITE_SCOPE');P.safe(p.parent)
    need(replace and p==CONTROL/'record.json' or not os.path.lexists(p),'WRITE_COLLISION')
    temporary=p.parent/('.forecast-release-'+C['transaction']+'-'+uuid.uuid4().hex)
    try:
        with os.fdopen(os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'wb') as f:
            os.fchown(f.fileno(),0,0);os.fchmod(f.fileno(),mode);f.write(raw);f.flush();os.fsync(f.fileno())
        if replace:os.replace(temporary,p)
        else:os.link(temporary,p,follow_symlinks=False);os.unlink(temporary)
        sync(p.parent);need(P.snap(p,0,0,mode)[1]==raw,'WRITE_VERIFY')
    finally:
        if os.path.lexists(temporary):os.unlink(temporary)
def mkdir(p):
    allowed={CONTROL,API,STATIC}
    for f in allowed_files():
        for root in [API,STATIC]:
            if f.is_relative_to(root):allowed.update(q for q in f.parents if q==root or q.is_relative_to(root))
    need(p in allowed,'DIRECTORY_SCOPE');P.safe(p.parent);need(not os.path.lexists(p),'DIRECTORY_COLLISION')
    os.mkdir(p,0o700);os.chown(p,0,0);os.chmod(p,0o700 if p==CONTROL else 0o755);sync(p);sync(p.parent)
    return [p.lstat().st_dev,p.lstat().st_ino]
def record_valid(r):
    need(type(r)is dict and set(r)=={'release','transaction','binding','phase','baseline','pointers','roots','activated_at'},'JOURNAL_SCHEMA')
    need((r['release'],r['transaction'],r['binding'])==(C['release'],C['transaction'],C['binding']) and r['phase']in PHASES,'JOURNAL_IDENTITY')
    need(r['pointers']=={'api':str(P.API),'static':str(P.STATIC)},'BACKUP_POINTER_IDENTITY')
    need(type(r['baseline'])is dict and set(r['baseline'])=={'production','forecast','store','helper','policy','environment','nginx','venv','runtime'},'BASELINE_SCHEMA')
    need(str(B['canonical'](P.API/'.venv-api',Path('/opt/powerflow/releases')))==r['baseline']['venv'],'RUNTIME_BASELINE_IDENTITY')
    need(set(r['roots'])<={'api','static'} and all(type(v)is list and len(v)==2 and all(type(n)is int for n in v) for v in r['roots'].values()),'ROOT_IDENTITY')
    need(r['activated_at']is None or H.OP.timestamp(r['activated_at'])<=dt.datetime.now(dt.timezone.utc),'ACTIVATION_TIME')
    return r
def save(r,phase):
    global PHASE
    PHASE=phase;r['phase']=phase;record_valid(r)
    write(CONTROL/'record.json',json.dumps(r,sort_keys=True).encode(),0o600,replace=os.path.lexists(CONTROL/'record.json'))
def load_record():
    P.safe(CONTROL);s=CONTROL.lstat();need((s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o700),'JOURNAL_METADATA')
    return record_valid(json.loads(P.snap(CONTROL/'record.json',0,0,0o600)[1]))
def verified_backups(r):
    record_valid(r);identities=[];expected=json.dumps(r['pointers'],sort_keys=True).encode()
    for suffix in ['backup','independent']:
        p=CONTROL/('pointers.'+suffix);s=p.lstat();need(s.st_nlink==1,'BACKUP_HARDLINK')
        need(P.snap(p,0,0,0o600)[1]==expected,'BACKUP_BYTES');identities.append((s.st_dev,s.st_ino))
    need(identities[0]!=identities[1],'BACKUP_NOT_INDEPENDENT')
def tree_state(r,complete=False):
    for prefix,root in [('api/',API),('static/',STATIC)]:
        label=prefix[:-1]
        if not os.path.lexists(root):need(label not in r['roots'],'CREATED_ROOT_MISSING');continue
        s=root.lstat();need(r['roots'].get(label)==[s.st_dev,s.st_ino] and stat.S_ISDIR(s.st_mode) and (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o755),'CREATED_ROOT_DRIFT')
        expected=inventory(prefix);seen={};allowed_dirs={'.'};seen_dirs={'.'}
        for rel in expected:allowed_dirs.update(p.as_posix() for p in Path(rel).parents)
        for parent,dirs,files in os.walk(root,followlinks=False):
            need(len(dirs)+len(files)<200,'TREE_BOUND')
            for name in dirs:
                p=Path(parent)/name
                if p==API/'.venv-api':
                    link=p.lstat();need(stat.S_ISLNK(link.st_mode) and link.st_uid==link.st_gid==0 and str(p.resolve(strict=True))==r['baseline']['venv'],'VENV_LINK');continue
                relative=p.relative_to(root).as_posix();need(relative in allowed_dirs,'UNEXPECTED_RELEASE_DIRECTORY');P.safe(p);seen_dirs.add(relative)
            for name in files:
                p=Path(parent)/name;rel=p.relative_to(root).as_posix();need(rel in expected,'UNEXPECTED_RELEASE_FILE')
                need(p.lstat().st_nlink==1,'RELEASE_HARDLINK');seen[rel]=P.snap(p,0,0,0o644)[0]['sha256'];need(seen[rel]==expected[rel],'NEW_RELEASE_DRIFT')
        if complete:
            need(seen==expected and seen_dirs==allowed_dirs,'RELEASE_INCOMPLETE')
            if prefix=='api/':need((API/'.venv-api').is_symlink() and str((API/'.venv-api').resolve(strict=True))==r['baseline']['venv'],'VENV_LINK')
def old_trees():
    P.assert_files(P.API,{k[4:]:v['sha256'] for k,v in OLD['files'].items() if k.startswith('api/')})
    need(G['inventory'](P.STATIC)=={k[7:]:v['sha256'] for k,v in OLD['files'].items() if k.startswith('static/')},'OLD_STATIC_DRIFT')
def pointer(p,target,expected):
    need(p==P.BACKEND_LINK and target in (P.API,API) or p==P.STATIC_LINK and target in (P.STATIC,STATIC),'POINTER_SCOPE')
    s=p.lstat();need(stat.S_ISLNK(s.st_mode) and s.st_uid==s.st_gid==0 and p.resolve(strict=True)==expected,'POINTER_DRIFT')
    P.safe(p.parent);temporary=p.parent/('.forecast-pointer-'+C['transaction']+'-'+uuid.uuid4().hex)
    try:os.symlink(str(target),temporary);os.replace(temporary,p);sync(p.parent)
    finally:
        if os.path.lexists(temporary):os.unlink(temporary)
    need(p.resolve(strict=True)==target,'POINTER_VERIFY')
def restart(expected):
    result=B['bounded_run'](['/usr/bin/systemctl','restart',H.OLD_PLAN.UNIT],timeout=45,limit=8192,grace=5)
    need(result['returncode']==0 and not result['failure'],'CANDIDATE_RESTART')
    # Bounded read-only readiness observations; never repeat installation/restart.
    ready=False
    for _ in range(10):
        try:ready=B['request'](8010,'/health')[0]==B['request'](8010,'/ready')[0]==200
        except Exception:pass
        if ready:break
        time.sleep(.5)
    need(ready,'CANDIDATE_STARTUP');G['runtime'](expected);P.candidate_environment(True)
def apply():
    global CHANGED
    before=fresh();same(before,fresh())
    CHANGED=True;mkdir(CONTROL)
    r={'release':C['release'],'transaction':C['transaction'],'binding':C['binding'],'phase':'BACKED_UP','baseline':before,'pointers':{'api':str(P.API),'static':str(P.STATIC)},'roots':{},'activated_at':None}
    raw=json.dumps(r['pointers'],sort_keys=True).encode()
    for suffix in ['backup','independent']:write(CONTROL/('pointers.'+suffix),raw,0o600)
    verified_backups(r);save(r,'BACKED_UP');save(r,'INSTALL')
    for prefix,root in [('api/',API),('static/',STATIC)]:
        r['roots'][prefix[:-1]]=mkdir(root);save(r,'INSTALL')
        for key in C['files']:
            if not key.startswith(prefix):continue
            p=root/key[len(prefix):]
            for parent in reversed(p.parent.relative_to(root).parents):
                q=root/parent
                if not q.exists():mkdir(q)
            if not p.parent.exists():mkdir(p.parent)
            write(p,raw_file(key))
    os.symlink(before['venv'],API/'.venv-api');sync(API)
    tree_state(r,complete=True);old_trees();import_probe(Path(before['venv']));save(r,'READY')
    same({k:v for k,v in before.items() if k not in {'venv','runtime'}},baseline_preservation())
    P.idle(sum(v['bytes'] if v['bytes']is not None else v['max_bytes'] for v in C['files'].values())*3);verified_backups(r);save(r,'POINTERS')
    pointer(P.BACKEND_LINK,API,P.API);pointer(P.STATIC_LINK,STATIC,P.STATIC);restart(API)
    r['activated_at']=dt.datetime.now(dt.timezone.utc).isoformat();deployment_checks(r)
    verified_backups(r);tree_state(r,complete=True);save(r,'APPLIED')
    return {'status':'APPLIED','phase':'APPLIED','changed':True,'release':C['release'],'transaction':C['transaction'],'forecast_enabled':True,'operational_enabled':True,'rollback_ready':True,'browser':'PENDING_OWNER','natural_run':'PENDING'}
def rollback():
    global CHANGED
    r=load_record();need(r['phase']not in {'ROLLBACK','ROLLED_BACK'},'ROLLBACK_NOT_APPLICABLE')
    verified_backups(r);tree_state(r);old_trees();P.idle(0)
    need(P.runtime_closure(Path(r['baseline']['venv']))==r['baseline']['runtime'],'ROLLBACK_RUNTIME_DRIFT')
    current=baseline_preservation()
    need(all(current[k]==r['baseline'][k] for k in ['production','helper','policy','environment','nginx']),'ROLLBACK_PRESERVATION_DRIFT')
    for p,allowed in [(P.BACKEND_LINK,[P.API,API]),(P.STATIC_LINK,[P.STATIC,STATIC])]:
        s=p.lstat();need(stat.S_ISLNK(s.st_mode) and (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o777) and p.resolve(strict=True)in allowed and os.readlink(p)==str(p.resolve(strict=True)),'ROLLBACK_POINTER_DRIFT')
    changed=P.BACKEND_LINK.resolve(strict=True)==API
    CHANGED=True;save(r,'ROLLBACK')
    for p,target in [(P.BACKEND_LINK,P.API),(P.STATIC_LINK,P.STATIC)]:
        actual=p.resolve(strict=True)
        if actual!=target:pointer(p,target,actual)
    if changed:restart(P.API)
    else:G['runtime'](P.API);P.candidate_environment(True)
    H.health();same(current,baseline_preservation());verified_backups(r);tree_state(r);save(r,'ROLLED_BACK')
    return {'status':'ROLLED_BACK','phase':'ROLLED_BACK','changed':True,'release':C['release'],'transaction':C['transaction'],'forecast_enabled':True,'operational_enabled':True,'retained_release_evidence':True}
