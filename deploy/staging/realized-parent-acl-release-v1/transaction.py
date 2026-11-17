"""One FD-bound ACL change; private independent backups and separate rollback."""
import base64
import ctypes
import fcntl
import os
from pathlib import Path
import stat
import uuid

CONTROL=Path(C['control'])
PHASES={'BACKED_UP','CHANGING_ACL','APPLIED','ROLLING_BACK','ROLLED_BACK'}

def sync(fd):os.fsync(fd)

def control_fd(create=False):
    global CHANGED
    safe_parent(CONTROL.parent)
    if create:
        need(not os.path.lexists(CONTROL),'TRANSACTION_ALREADY_EXISTS');os.mkdir(CONTROL,0o700);CHANGED=True;os.chmod(CONTROL,0o700)
        parent=os.open(CONTROL.parent,FLAGS)
        try:sync(parent)
        finally:os.close(parent)
    fd=os.open(CONTROL,FLAGS);s=os.fstat(fd)
    try:need((s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o700),'JOURNAL_DIRECTORY_METADATA');return fd
    except Exception:os.close(fd);raise

def read_private(fd,name):
    need(name in {'snapshot.backup','snapshot.independent','record.json'},'JOURNAL_FILE_SCOPE')
    file=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_NOATIME,dir_fd=fd)
    try:
        s=os.fstat(file);need(stat.S_ISREG(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode),s.st_nlink)==(0,0,0o600,1)and s.st_size<=256*1024,'JOURNAL_FILE_METADATA')
        raw=os.read(file,256*1024+1);need(len(raw)==s.st_size,'JOURNAL_FILE_BOUND')
        after=os.fstat(file);need((s.st_dev,s.st_ino,s.st_size,s.st_mode,s.st_uid,s.st_gid,s.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mode,after.st_uid,after.st_gid,after.st_ctime_ns),'JOURNAL_READ_CHANGED')
        return raw,(s.st_dev,s.st_ino)
    finally:os.close(file)

def write_private(fd,name,raw,replace=False):
    need(name in {'snapshot.backup','snapshot.independent','record.json'}and type(raw)is bytes and len(raw)<=256*1024,'JOURNAL_WRITE_SCOPE')
    need(replace and name=='record.json'or not os.path.lexists(CONTROL/name),'JOURNAL_COLLISION')
    temporary='.acl-journal-'+uuid.uuid4().hex;file=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
    try:
        with os.fdopen(file,'wb')as f:
            os.fchmod(f.fileno(),0o600);f.write(raw);f.flush();os.fsync(f.fileno())
        if replace:os.replace(temporary,name,src_dir_fd=fd,dst_dir_fd=fd)
        else:os.link(temporary,name,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False);os.unlink(temporary,dir_fd=fd)
        sync(fd);need(read_private(fd,name)[0]==raw,'JOURNAL_WRITE_VERIFY')
    finally:
        try:os.unlink(temporary,dir_fd=fd)
        except FileNotFoundError:pass

def valid_record(record):
    need(type(record)is dict and set(record)=={'release','transaction','binding','phase','snapshot_sha256','planned_text','after_access_raw'},'JOURNAL_SCHEMA')
    need((record['release'],record['transaction'],record['binding'])==(C['release'],C['transaction'],C['binding'])and record['phase']in PHASES,'JOURNAL_IDENTITY')
    need(type(record['snapshot_sha256'])is str and len(record['snapshot_sha256'])==64,'JOURNAL_SNAPSHOT_HASH')
    parse(record['planned_text']);need(record['after_access_raw']is None or type(record['after_access_raw'])is str,'JOURNAL_AFTER_ACL')
    return record

def save(fd,record,phase):
    global PHASE
    PHASE=phase;record['phase']=phase;valid_record(record);write_private(fd,'record.json',encode(record),replace=os.path.lexists(CONTROL/'record.json'))

def verified_backup(fd,record):
    valid_record(record);first,identity=read_private(fd,'snapshot.backup');second,other=read_private(fd,'snapshot.independent')
    need(identity!=other and first==second and sha(first)==record['snapshot_sha256'],'BACKUP_INDEPENDENCE_OR_HASH')
    before=json.loads(first);need(set(before)=={'parent','children','worker_groups','library'},'BACKUP_SCHEMA')
    need(record['planned_text']==plan(before['parent']['access_text'],before['worker_groups']),'BACKUP_PLAN_INCONSISTENT')
    need(before['parent']['metadata']['uid']==OWNER and before['parent']['metadata']['gid']==READER_GID and before['parent']['metadata']['mode']==MODE,'BACKUP_METADATA')
    for kind in ['access_raw','default_raw']:
        value=before['parent'][kind]
        need(value is None or type(value)is str and 0<len(base64.b64decode(value,validate=True))<=16384,'BACKUP_XATTR_INVALID')
    return before

def preserve(before,after):
    need(after['parent']['metadata']==before['parent']['metadata'],'PARENT_IDENTITY_OWNER_GROUP_MODE_DRIFT')
    need(after['parent']['default_raw']==before['parent']['default_raw']and after['parent']['default_text']==before['parent']['default_text'],'DEFAULT_ACL_DRIFT')
    need(after['children']==before['children'],'PROTECTED_BOUNDARY_DRIFT')
    need(after['worker_groups']==before['worker_groups']and after['library']==before['library'],'WORKER_OR_LIBACL_DRIFT')

def commit(context,text):
    # The sole target setter: exact named-user plan, explicit unchanged mask.
    handle=context.acl.prepare(text)
    try:
        setter=context.acl.lib.acl_set_fd;setter.argtypes=[ctypes.c_int,ctypes.c_void_p];setter.restype=ctypes.c_int
        result=setter(context.fd,handle)
        need(result==0,'ACL_SET_FD_FAILED') # no chmod/mode fallback of any kind
    finally:context.acl.lib.acl_free(handle)

def apply():
    global PHASE,CHANGED
    with Context()as context:
        fcntl.flock(context.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before,proposed=fresh(context);second,again=fresh(context);need(before==second and proposed==again,'FRESH_GATE_DRIFT')
        fd=control_fd(create=True)
        try:
            raw=encode(before)
            for name in ['snapshot.backup','snapshot.independent']:write_private(fd,name,raw)
            record={'release':C['release'],'transaction':C['transaction'],'binding':C['binding'],'phase':'BACKED_UP','snapshot_sha256':sha(raw),'planned_text':proposed,'after_access_raw':None}
            verified_backup(fd,record);save(fd,record,'BACKED_UP')
            idle();need(observe(context)==before,'PRE_MUTATION_ACL_DRIFT');save(fd,record,'CHANGING_ACL')
            commit(context,proposed)
            after=observe(context);preserve(before,after);verify_plan(before['parent']['access_text'],after['parent']['access_text'],before['worker_groups'])
            probe(True);need(observe(context)==after,'POSTCHECK_ACL_DRIFT')
            record['after_access_raw']=after['parent']['access_raw'];verified_backup(fd,record);save(fd,record,'APPLIED')
        finally:os.close(fd)
    return {'status':'APPLIED','phase':'APPLIED','changed':True,'reason':'UID_SEARCH_ONLY_GRANTED','target_uid':UID,'owner_group_mode_preserved':True,'mask_preserved':True,'protected_boundaries_denied':True,'rollback_ready':True}

def restore(context,before):
    # Only this access-ACL xattr on the pinned target. Default ACL never changes.
    raw=before['parent']['access_raw']
    need(metadata(context.fd)==before['parent']['metadata'],'ROLLBACK_TARGET_IDENTITY')
    if raw is None:os.removexattr(context.fd,ACCESS)
    else:os.setxattr(context.fd,ACCESS,base64.b64decode(raw,validate=True))

def rollback():
    global PHASE,CHANGED
    idle()
    with Context()as context:
        fcntl.flock(context.fd,fcntl.LOCK_EX|fcntl.LOCK_NB);fd=control_fd()
        try:
            record=valid_record(json.loads(read_private(fd,'record.json')[0]));need(record['phase']not in {'ROLLED_BACK','ROLLING_BACK'},'ROLLBACK_NOT_APPLICABLE')
            before=verified_backup(fd,record);current=observe(context);preserve(before,current)
            original=current['parent']==before['parent']
            if not original:
                verify_plan(before['parent']['access_text'],current['parent']['access_text'],before['worker_groups'])
                if record['after_access_raw']is not None:need(current['parent']['access_raw']==record['after_access_raw'],'ROLLBACK_AFTER_ACL_DRIFT')
            probe(not original);idle();need(observe(context)==current,'ROLLBACK_FRESH_DRIFT')
            CHANGED=True;save(fd,record,'ROLLING_BACK')
            if not original:restore(context,before)
            restored=observe(context);need(restored==before,'EXACT_ACL_RESTORATION_FAILED');probe(False)
            verified_backup(fd,record);save(fd,record,'ROLLED_BACK')
        finally:os.close(fd)
    return {'status':'ROLLED_BACK','phase':'ROLLED_BACK','changed':True,'reason':'EXACT_ORIGINAL_ACL_RESTORED','target_uid':UID,'owner_group_mode_preserved':True,'mask_preserved':True,'protected_boundaries_denied':True,'rollback_ready':True}
