"""Fixed metadata-only coordinator; producer traversal is never tested as root."""
import json
import os
import pwd
import re
import stat
import sys

LABELS=('FILESYSTEM_ROOT','SERVICE_DATA_PARENT','REPORT_STORE_PARENT')
CHILD_CODES={'TRAVERSAL_PASS','PRODUCER_UID_MISMATCH','PRODUCER_GID_MISMATCH','PRODUCER_SAVED_ID_MISMATCH','PRODUCER_SUPPLEMENTARY_GROUPS_PRESENT','PRODUCER_SECURITY_CONTEXT_UNVERIFIED','PRODUCER_TRAVERSAL_DENIED','PATH_SYMLINK_OR_TYPE_VIOLATION','PATH_MISSING','PATH_LOOKUP_DENIED','PROBE_RUNTIME_UNSUPPORTED','PROBE_OS_ERROR','PROBE_INTERNAL_ERROR'}
CHILD_ARGV=['/usr/bin/setpriv','--no-new-privs','--reuid=1000','--regid=1000','--clear-groups','/usr/bin/python3','-I','-S','-B','-']
SERVICE_ARGV=['/usr/bin/systemctl','show','powerflow-prefect-worker.service','--no-pager','--property=User,Group,MainPID']

STAGES={'HOST','OS_TOOLS','PRODUCER_IDENTITY','PARENT_METADATA','PRODUCER_ACCESS','PARENT_STABILITY','COMPLETE'}
STAGE='HOST'
REASONS=CHILD_CODES|{'PROBE_GROUP_CONTEXT_DIFFERENCE','PRODUCER_TRAVERSAL_MODE_DENIED','PRODUCER_TRAVERSAL_OS_POLICY_DENIED','PRODUCER_PROBE_TIMEOUT','PRODUCER_PROBE_OUTPUT_LIMIT','PRODUCER_INTERPRETER_EXECUTION_FAILED','PRODUCER_PRIVILEGE_DROP_FAILED','PRODUCER_PYTHON_STARTUP_FAILED','PRODUCER_ACCOUNT_MISSING','PRODUCER_ACCOUNT_IDENTITY_MISMATCH','WORKER_IDENTITY_QUERY_FAILED','WORKER_IDENTITY_FORMAT','WORKER_SERVICE_IDENTITY_MISMATCH','WORKER_PID_UNVERIFIED','WORKER_PROCESS_IDENTITY_FORMAT','WORKER_RUNTIME_IDENTITY_MISMATCH','WORKER_GROUP_FORMAT','PROC_SCOPE','WORKER_STATUS_BOUND','PARENT_METADATA_UNSAFE','OS_TOOL_LAYOUT_UNVERIFIED','OS_TOOL_PARENT_UNSAFE','OS_TOOL_METADATA_UNSAFE','PRODUCER_PROBE_SUPERVISOR_UNVERIFIED','PRODUCER_PROBE_OUTPUT_UNVERIFIED','PRODUCER_PROBE_EXIT_UNVERIFIED','LINUX_COORDINATOR_IDENTITY_REQUIRED','LINUX_PATH_RUNTIME_UNSUPPORTED','PARENT_METADATA_CHANGED','DIAGNOSTIC_COMMAND_SCOPE','DIAGNOSTIC_INPUT_SCOPE','DIAGNOSTIC_EXECUTION_BOUND','WORKER_PROCESS_UNAVAILABLE','METADATA_OS_ERROR','DIAGNOSTIC_INTERNAL_ERROR'}

class Stop(ValueError):pass

def need(ok,code):
    if not ok:raise Stop(code)

def identities():
    try:user=pwd.getpwnam('ec2-user')
    except KeyError:raise Stop('PRODUCER_ACCOUNT_MISSING')from None
    need((user.pw_uid,user.pw_gid)==(1000,1000),'PRODUCER_ACCOUNT_IDENTITY_MISMATCH')
    result=bounded_run(SERVICE_ARGV,timeout=5,limit=4096,grace=5)
    need(result['returncode']==0 and result['failure']is None,'WORKER_IDENTITY_QUERY_FAILED')
    try:
        fields={}
        for line in result['stdout'].decode('utf-8').splitlines():
            if not line:continue
            key,value=line.split('=',1);need(key not in fields,'WORKER_IDENTITY_FORMAT');fields[key]=value
    except (ValueError,UnicodeError):raise Stop('WORKER_IDENTITY_FORMAT')from None
    need(set(fields)=={'User','Group','MainPID'}and fields['User']==fields['Group']=='ec2-user','WORKER_SERVICE_IDENTITY_MISMATCH')
    pid=fields['MainPID'];need(re.fullmatch('[1-9][0-9]{0,8}',pid)is not None and int(pid)>1,'WORKER_PID_UNVERIFIED')
    raw=read_proc('/proc/'+pid+'/status')
    rows={line.split(b':',1)[0]:line.split(b':',1)[1].strip()for line in raw.splitlines()if b':'in line}
    try:
        uid=[int(n)for n in rows[b'Uid'].split()];gid=[int(n)for n in rows[b'Gid'].split()];groups=[int(n)for n in rows[b'Groups'].split()]
    except (ValueError,KeyError):raise Stop('WORKER_PROCESS_IDENTITY_FORMAT')from None
    need(uid==gid==[1000]*4,'WORKER_RUNTIME_IDENTITY_MISMATCH')
    need(len(groups)<=64 and len(groups)==len(set(groups))and all(n>=0 for n in groups),'WORKER_GROUP_FORMAT')
    return sorted(groups)

def read_proc(path):
    # Exact systemctl-selected worker PID/status only; never environ or cmdline.
    need(re.fullmatch('/proc/[1-9][0-9]{0,8}/status',path)is not None,'PROC_SCOPE')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        raw=os.read(fd,16385);need(len(raw)<=16384,'WORKER_STATUS_BOUND');return raw
    finally:os.close(fd)

def metadata():
    result=[];fd=os.open('/',os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for label,name in zip(LABELS,['.','srv','powerflow']):
            s=os.stat(name,dir_fd=fd,follow_symlinks=False)
            need(stat.S_ISDIR(s.st_mode),'PATH_SYMLINK_OR_TYPE_VIOLATION')
            # Existing preflight requires safe root-owned, non-writable parents.
            need(s.st_uid==0 and not s.st_mode&0o022,'PARENT_METADATA_UNSAFE')
            result.append({'id':label,'uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode),'identity':(s.st_dev,s.st_ino,s.st_ctime_ns)})
            if label!='FILESYSTEM_ROOT':
                nxt=os.open(name,os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
    finally:os.close(fd)
    return result

def trusted_commands():
    # Trusted OS tools only; symlink targets are metadata-checked, never executed
    # under a substituted path. This does not establish independent binary hashes.
    for path in ['/usr/bin/setpriv','/usr/bin/python3','/usr/bin/systemctl']:
        actual=os.path.realpath(path)
        need(actual.startswith('/usr/bin/'),'OS_TOOL_LAYOUT_UNVERIFIED')
        parent=os.stat('/usr/bin',follow_symlinks=False);s=os.stat(actual,follow_symlinks=False)
        need(stat.S_ISDIR(parent.st_mode)and parent.st_uid==0 and not parent.st_mode&0o022,'OS_TOOL_PARENT_UNSAFE')
        need(stat.S_ISREG(s.st_mode)and s.st_uid==0 and not s.st_mode&0o022 and s.st_mode&0o111,'OS_TOOL_METADATA_UNSAFE')

def permits(row,groups):
    mode=row['mode']
    return bool(mode&(0o100 if row['uid']==1000 else 0o010 if row['gid']in {1000,*groups}else 0o001))

def public_metadata(rows):
    return [{'path_id':r['id'],'owner':'ROOT'if r['uid']==0 else'OTHER','group':'ROOT_GROUP'if r['gid']==0 else'PRODUCER_GROUP'if r['gid']==1000 else'API_READER_GROUP'if r['gid']==992 else'OTHER','mode':format(r['mode'],'04o'),'cleared_producer_mode_allows_search':permits(r,[])}for r in rows]

def child_result(result):
    need(set(result)=={'returncode','stdout','stderr','failure'}and type(result['returncode'])is int and type(result['stdout'])is bytes and type(result['stderr'])is bytes and len(result['stdout'])<=2048 and len(result['stderr'])<=2048,'PRODUCER_PROBE_OUTPUT_UNVERIFIED')
    if result['failure']=='TIMEOUT':return {'reason':'PRODUCER_PROBE_TIMEOUT','path_id':'NONE','errno':None}
    if result['failure']=='OUTPUT_LIMIT':return {'reason':'PRODUCER_PROBE_OUTPUT_LIMIT','path_id':'NONE','errno':None}
    need(result['failure']is None,'PRODUCER_PROBE_SUPERVISOR_UNVERIFIED')
    try:
        def pairs(items):
            out={}
            for k,v in items:need(k not in out,'PRODUCER_PROBE_OUTPUT_UNVERIFIED');out[k]=v
            return out
        value=json.loads(result['stdout'],object_pairs_hook=pairs)
    except (ValueError,TypeError):
        # Only known tool prefixes are inspected in memory. No raw excerpts leave
        # this function; startup errors are NOT reported as permission denial.
        lines=result['stderr'].lower().splitlines()
        if any(line.startswith(b'setpriv:')and b'failed to execute'in line for line in lines):reason='PRODUCER_INTERPRETER_EXECUTION_FAILED'
        elif any(line.startswith(b'setpriv:')for line in lines):reason='PRODUCER_PRIVILEGE_DROP_FAILED'
        elif any(b'fatal python error:'in line or line.startswith(b'python:')for line in lines):reason='PRODUCER_PYTHON_STARTUP_FAILED'
        else:reason='PRODUCER_PROBE_OUTPUT_UNVERIFIED'
        return {'reason':reason,'path_id':'NONE','errno':None}
    need(type(value)is dict and set(value)=={'version','reason','path_id','errno'},'PRODUCER_PROBE_OUTPUT_UNVERIFIED')
    need(type(value['version'])is int and value['version']==1 and value['reason']in CHILD_CODES and value['path_id']in {*LABELS,'NONE'},'PRODUCER_PROBE_OUTPUT_UNVERIFIED')
    need(value['errno']is None or type(value['errno'])is int and value['errno']in {1,2,13,20,40,95},'PRODUCER_PROBE_OUTPUT_UNVERIFIED')
    need(result['returncode']==(0 if value['reason']=='TRAVERSAL_PASS'else 1),'PRODUCER_PROBE_EXIT_UNVERIFIED')
    return {k:value[k]for k in ['reason','path_id','errno']}

def inspect():
    global STAGE
    STAGE='HOST'
    need(sys.platform=='linux'and sys.version_info>=(3,9)and os.getuid()==os.geteuid()==os.getgid()==os.getegid()==0,'LINUX_COORDINATOR_IDENTITY_REQUIRED')
    need(hasattr(os,'O_PATH')and hasattr(os,'O_NOFOLLOW'),'LINUX_PATH_RUNTIME_UNSUPPORTED')
    STAGE='OS_TOOLS';trusted_commands()
    STAGE='PRODUCER_IDENTITY';groups=identities()
    STAGE='PARENT_METADATA';before=metadata()
    STAGE='PRODUCER_ACCESS'
    result=bounded_run(CHILD_ARGV,input=PRODUCER,timeout=5,limit=2048,grace=5)
    child=child_result(result);STAGE='PARENT_STABILITY';after=metadata();need(before==after,'PARENT_METADATA_CHANGED')
    reason=child['reason']
    if reason=='PRODUCER_TRAVERSAL_DENIED':
        need(child['path_id']in LABELS,'PRODUCER_PROBE_OUTPUT_UNVERIFIED');row=next(r for r in before if r['id']==child['path_id'])
        reason='PROBE_GROUP_CONTEXT_DIFFERENCE'if not permits(row,[])and permits(row,groups)else'PRODUCER_TRAVERSAL_MODE_DENIED'if not permits(row,[])else'PRODUCER_TRAVERSAL_OS_POLICY_DENIED'
    STAGE='COMPLETE'
    return {'stage':STAGE,'status':'PASS'if reason=='TRAVERSAL_PASS'else'BLOCKED','changed':False,'reason':reason,'producer_probe':child['reason'],'failed_path_id':child['path_id'],'errno':child['errno'],'worker_primary_identity':'MATCH','worker_groups_match_cleared_probe':groups==[],'worker_api_reader_group_present':992 in groups,'directories':public_metadata(before)}


def failure_report(error):
    reason=str(error)if isinstance(error,Stop)else''
    if reason not in REASONS:
        reason='WORKER_PROCESS_UNAVAILABLE'if isinstance(error,OSError)and STAGE=='PRODUCER_IDENTITY'else'METADATA_OS_ERROR'if isinstance(error,OSError)else'DIAGNOSTIC_INTERNAL_ERROR'
    code=getattr(error,'errno',None)
    return {'status':'BLOCKED','changed':False,'stage':STAGE,'reason':reason,'errno':code if type(code)is int and code in{1,2,13,20,40,95}else None}
