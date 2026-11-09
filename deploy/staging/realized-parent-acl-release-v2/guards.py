"""Read-only ACL support, exact target/inventory, effective-access and idle gates."""
import os
from pathlib import Path
import stat
import sys

CHILD_ARGV=['/usr/bin/setpriv','--no-new-privs','--reuid=1000','--regid=1000','--clear-groups','/usr/bin/python3','-I','-S','-B','-']
PROBE_REASONS={'PROBE_PASS','PROBE_RUNTIME_UNSUPPORTED','PRODUCER_IDENTITY_MISMATCH','PRODUCER_SECURITY_CONTEXT_UNVERIFIED','PARENT_METADATA_MISMATCH','PARENT_ACCESS_MISMATCH','PROBE_OS_ERROR','PARENT_LISTING_AVAILABLE','PROTECTED_BOUNDARY_TYPE','PROTECTED_BOUNDARY_ACCESS','PROTECTED_BOUNDARY_READABLE'}

class Context:
    def __enter__(self):
        need(sys.platform=='linux'and sys.version_info>=(3,9)and os.uname().machine=='x86_64','LINUX_RUNTIME_REQUIRED')
        need(os.getuid()==os.geteuid()==os.getgid()==os.getegid()==0,'ROOT_COORDINATOR_REQUIRED')
        need(hasattr(os,'O_NOATIME')and hasattr(os,'O_PATH'),'LINUX_FILESYSTEM_API_REQUIRED')
        self.fd=root_fd()
        try:self.acl=ACL();return self
        except Exception:os.close(self.fd);raise
    def __exit__(self,*args):self.acl.close();os.close(self.fd)

def idle():
    _,ok=BASE.pipeline();need(ok,'PIPELINE_OR_WINDOW_GATE')

def probe(granted):
    payload=PROBE_GRANTED if granted else PROBE_DENIED
    r=process(CHILD_ARGV,input=payload,timeout=5,limit=4096,grace=5)
    need(r['failure']is None,'PRODUCER_PROBE_TIMEOUT_OR_BOUND')
    try:
        def unique(items):
            out={}
            for k,v in items:need(k not in out,'PRODUCER_PROBE_OUTPUT_INVALID');out[k]=v
            return out
        value=json.loads(r['stdout'],object_pairs_hook=unique)
    except (ValueError,TypeError):raise Stop('PRODUCER_PROBE_STARTUP_OR_OUTPUT_FAILED')from None
    need(type(value)is dict and set(value)=={'version','status','reason','parent_search','parent_read','parent_write','boundary'},'PRODUCER_PROBE_OUTPUT_INVALID')
    need(type(value['version'])is int and value['version']==1 and type(value['reason'])is str and value['reason']in PROBE_REASONS and value['status']in {'PASS','BLOCKED'},'PRODUCER_PROBE_OUTPUT_INVALID')
    need(value['boundary']in {'NONE','PUBLISHED','FORECAST','OPERATIONAL'},'PRODUCER_PROBE_OUTPUT_INVALID')
    for k in ['parent_search','parent_read','parent_write']:need(value[k]is None or type(value[k])is bool,'PRODUCER_PROBE_OUTPUT_INVALID')
    if value['status']!='PASS':raise Stop(value['reason'])
    need(r['returncode']==0 and value['reason']=='PROBE_PASS'and value['parent_search']is granted and value['parent_read']is value['parent_write']is False and value['boundary']=='NONE','PRODUCER_PROBE_RESULT_INCONSISTENT')
    return value

def boundary_states(context,worker_groups):
    names=[];os.lseek(context.fd,0,os.SEEK_SET)
    with os.scandir(context.fd)as entries:
        for entry in entries:
            names.append(entry.name);need(len(names)<=3 and entry.name in CHILDREN,'PARENT_CHILD_INVENTORY_DRIFT')
    need(set(names)==set(CHILDREN)and len(names)==3,'PARENT_CHILD_INVENTORY_DRIFT')
    result={}
    for name in CHILDREN:
        fd=os.open(name,FLAGS,dir_fd=context.fd)
        try:
            state=snapshot(fd,context.acl);m=state['metadata']
            need((m['uid'],m['gid'],m['mode'])==(OWNER,READER_GID,MODE),'PROTECTED_BOUNDARY_METADATA')
            deny_boundary(state['access_text'],worker_groups);result[name]=state
        finally:os.close(fd)
    return result

def observe(context):
    # Recheck the fixed name still identifies the pinned inode; never follow a
    # replacement link. No report files, datasets or databases are opened.
    checkfd=root_fd()
    try:need(metadata(checkfd)==metadata(context.fd),'TARGET_PATH_REPLACED')
    finally:os.close(checkfd)
    groups=META.identities();need(READER_GID not in groups,'WORKER_API_READER_GROUP_FORBIDDEN');parent=snapshot(context.fd,context.acl)
    need(parent['metadata']['mode']==MODE and parent['metadata']['uid']==OWNER and parent['metadata']['gid']==READER_GID,'VERIFIED_PARENT_BASELINE_DRIFT')
    deny_default(parent['default_text'],groups)
    children=boundary_states(context,groups)
    need(not os.fstatvfs(context.fd).f_flag&os.ST_RDONLY,'TARGET_FILESYSTEM_READ_ONLY')
    return {'parent':parent,'children':children,'worker_groups':groups,'library':context.acl.identity}

def fresh(context):
    idle();need(not os.path.lexists(C['control']),'TRANSACTION_ALREADY_EXISTS');safe_parent(Path(C['control']).parent)
    capacity=os.statvfs(Path(C['control']).parent)
    need(capacity.f_bavail*capacity.f_frsize>=4*1024**2 and capacity.f_favail>=8,'BACKUP_STORAGE_INSUFFICIENT')
    before=observe(context);proposed=plan(before['parent']['access_text'],before['worker_groups']);verify_rollback_readiness(before,proposed);context.acl.validate_plan(proposed)
    need(parse(context.acl.get(context.fd))==parse(before['parent']['access_text']),'ACL_SUPPORT_READBACK_CHANGED')
    probe(False)
    need(observe(context)==before,'FRESH_ACL_OR_ISOLATION_DRIFT')
    return before,proposed

def preflight():
    with Context()as context:fresh(context)
    return {'status':'PREFLIGHT_PASS','phase':'READ_ONLY','changed':False,'reason':'ACL_SEARCH_ONLY_PLAN_VERIFIED','target_uid':UID,'owner_group_mode_preserved':True,'mask_preserved':True,'protected_boundaries_denied':True,'rollback_ready':True}
