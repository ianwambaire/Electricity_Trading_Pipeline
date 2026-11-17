"""Helper-only guarded apply/rollback. Never publishes, patches Prefect or restarts."""
import json
import os
import stat
import uuid
PHASE='PREFLIGHT';CHANGED=False
PHASES={'BACKED_UP','INSTALL','READY','RULE_INSTALLED','ACTIVATE','APPLIED','ROLLBACK','ROLLED_BACK'}


def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def writable():
    return {target(key) for key in C['files']}|{CONTROL/'record.json'}|{CONTROL/(key+suffix) for key in ['launcher','sudoers'] for suffix in ['.backup','.independent']}

def write(path,raw,mode=0o600,exclusive=False,expected=None):
    need(path in writable(),'WRITE_SCOPE');P.safe(path.parent)
    need(not os.path.lexists(path) if exclusive else expected is not None and P.snap(path,0,0,mode)[0]['sha256']==expected,'WRITE_DRIFT')
    temporary=path.parent/('.helper-'+C['transaction']+'-'+uuid.uuid4().hex)
    try:
        with os.fdopen(os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),'wb') as f:
            os.fchown(f.fileno(),0,0);os.fchmod(f.fileno(),mode);f.write(raw);f.flush();os.fsync(f.fileno())
        if exclusive:
            # Atomic no-replace for new immutable files and backup copies.
            os.link(temporary,path,follow_symlinks=False);os.unlink(temporary)
        else:
            need(P.snap(path,0,0,mode)[0]['sha256']==expected,'WRITE_DRIFT')
            os.replace(temporary,path)
        sync(path.parent);meta,value=P.snap(path,0,0,mode);need(value==raw,'WRITE_VERIFY');return meta
    finally:
        if os.path.lexists(temporary):os.unlink(temporary)

def mkdir(path):
    need(path in {CONTROL,NEW,NEW/'shared'},'DIRECTORY_SCOPE');P.safe(path.parent);need(not os.path.lexists(path),'DIRECTORY_COLLISION')
    os.mkdir(path,0o700);os.chown(path,0,0);os.chmod(path,0o700);sync(path);sync(path.parent)
    return [path.lstat().st_dev,path.lstat().st_ino]

def validate_record(record):
    need(type(record)is dict and set(record)=={'release','transaction','binding','phase','baseline','backups','new_root_identity'},'RECORD_SCHEMA')
    need(record['release']==C['release'] and record['transaction']==C['transaction'] and record['binding']==C['binding'] and record['phase']in PHASES,'TRANSACTION_BINDING')
    need(set(record['backups'])=={'launcher','sudoers'} and all(record['backups'][k]==C['old_files'][k] for k in record['backups']),'BACKUP_BINDING')
    need(type(record['baseline'])is dict and set(record['baseline'])=={'production','forecast','store','policy','v5_record','privileges'} and record['baseline']['privileges']==C['old_files'],'BASELINE_SCHEMA')
    identity=record['new_root_identity'];need(identity is None or type(identity)is list and len(identity)==2 and all(type(x)is int and x>=0 for x in identity),'CREATION_IDENTITY')
    return record

def save(record,phase):
    global PHASE
    PHASE=phase;record['phase']=phase;validate_record(record)
    path=CONTROL/'record.json';expected=P.snap(path,0,0,0o600)[0]['sha256'] if os.path.lexists(path) else None
    write(path,json.dumps(record,sort_keys=True).encode(),exclusive=expected is None,expected=expected)

def load_record():
    P.safe(CONTROL);s=CONTROL.lstat();need(stat.S_ISDIR(s.st_mode) and (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o700),'CONTROL_METADATA')
    _,raw=P.snap(CONTROL/'record.json',0,0,0o600);return validate_record(json.loads(raw))

def verified_backups(record):
    validate_record(record)
    for key,meta in record['backups'].items():
        copies=[]
        for suffix in ['.backup','.independent']:
            path=CONTROL/(key+suffix);s=path.lstat();need(s.st_nlink==1,'BACKUP_HARDLINK')
            info,_=P.snap(path,0,0,0o600);need(info['sha256']==meta['sha256'] and info['bytes']==meta['bytes'],'BACKUP_HASH');copies.append((s.st_dev,s.st_ino))
        need(copies[0]!=copies[1],'BACKUP_NOT_INDEPENDENT')

def preservation(before,after):
    need(all(before[k]==after[k] for k in ['production','forecast','store','policy','v5_record']),'PRESERVATION_DRIFT')

def new_tree(record,complete=False):
    if os.path.lexists(NEW):
        s=NEW.lstat();need(record['new_root_identity']==[s.st_dev,s.st_ino],'NEW_ROOT_IDENTITY')
        tree(NEW,expected_new(),partial=not complete)
    else:need(record['new_root_identity']is None,'NEW_ROOT_MISSING')

def apply():
    global PHASE,CHANGED
    baseline=fresh();again=fresh();need(baseline==again,'FRESH_PREFLIGHT_DRIFT')
    PHASE='BACKUP';CHANGED=True;mkdir(CONTROL)
    for key,meta in C['old_files'].items():
        actual,raw=P.snap(target(key),0,0,meta['mode']);need(actual==meta,'BACKUP_SOURCE_DRIFT')
        write(CONTROL/(key+'.backup'),raw,exclusive=True);write(CONTROL/(key+'.independent'),raw,exclusive=True)
    record={'release':C['release'],'transaction':C['transaction'],'binding':C['binding'],'phase':'BACKED_UP','baseline':baseline,'backups':C['old_files'],'new_root_identity':None}
    verified_backups(record);save(record,'BACKED_UP');save(record,'INSTALL')
    record['new_root_identity']=mkdir(NEW);save(record,'INSTALL');mkdir(NEW/'shared')
    for key in C['files']:
        if key.startswith('helper/'):write(target(key),artifact(key),exclusive=True)
    new_tree(record,complete=True);installed_probe();verified_backups(record);save(record,'READY')
    # Recheck every preservation and idle-window gate immediately before the
    # two digest-bound privilege files change. Launcher replacement is activation.
    preservation(baseline,common('old'));new_tree(record,complete=True)
    P.process(['/usr/sbin/visudo','-cf','-'],input=artifact('sudoers'))
    write(P.RULE,artifact('sudoers'),mode=0o440,expected=C['old_files']['sudoers']['sha256'])
    P.process(['/usr/sbin/visudo','-c']);save(record,'RULE_INSTALLED')
    idle();verified_backups(record);save(record,'ACTIVATE')
    write(P.LAUNCHER,artifact('launcher'),mode=0o755,expected=C['old_files']['launcher']['sha256'])
    after=common('new');preservation(baseline,after);new_tree(record,complete=True);installed_probe();save(record,'APPLIED')
    return {'status':'APPLIED','phase':'APPLIED','changed':True,'release':C['release'],'transaction':C['transaction'],'operational_enabled':True,'helper_version':'v2','forecast_preserved':True,'services_restarted':False,'natural_run_acceptance':'PENDING','rollback_ready':True}

def rollback():
    global PHASE,CHANGED
    record=load_record();need(record['phase']not in {'ROLLED_BACK','ROLLBACK'},'ROLLBACK_NOT_APPLICABLE')
    verified_backups(record);new_tree(record);before=common('mixed')
    # Natural publications may have advanced since apply; preserve the current
    # read-only fingerprints rather than deleting/reverting any forecast/evidence.
    need(all(before[k]==record['baseline'][k] for k in ['production','policy','v5_record']),'ROLLBACK_BASELINE_DRIFT')
    for key in ['launcher','sudoers']:
        meta,_=P.snap(target(key),0,0,C['old_files'][key]['mode']);need(meta['sha256']in {C['old_files'][key]['sha256'],C['files'][key]['sha256']},'ROLLBACK_PRIVILEGE_DRIFT')
    P.process(['/usr/sbin/visudo','-cf','-'],input=P.read(CONTROL/'sudoers.backup'))
    CHANGED=True;save(record,'ROLLBACK')
    # Old launcher first, old digest rule last: intermediate states deny the
    # helper rather than permitting a root shell or unbound executable.
    for key in ['launcher','sudoers']:
        meta,_=P.snap(target(key),0,0,C['old_files'][key]['mode'])
        if meta['sha256']!=C['old_files'][key]['sha256']:
            write(target(key),P.read(CONTROL/(key+'.backup')),mode=C['old_files'][key]['mode'],expected=meta['sha256'])
    P.process(['/usr/sbin/visudo','-c']);after=common('old');preservation(before,after);verified_backups(record);new_tree(record);save(record,'ROLLED_BACK')
    return {'status':'ROLLED_BACK','phase':'ROLLED_BACK','changed':True,'release':C['release'],'transaction':C['transaction'],'operational_enabled':True,'helper_version':'v1','forecast_preserved':True,'services_restarted':False,'retained_versioned_helper':True}
