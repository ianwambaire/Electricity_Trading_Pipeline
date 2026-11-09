"""One fixed unprivileged search-permission check. No data or environment reads."""
import json
import os
import stat
import sys

PATHS=(('FILESYSTEM_ROOT','/'),('SERVICE_DATA_PARENT','srv'),('REPORT_STORE_PARENT','powerflow'))
CODES={'TRAVERSAL_PASS','PRODUCER_UID_MISMATCH','PRODUCER_GID_MISMATCH','PRODUCER_SAVED_ID_MISMATCH','PRODUCER_SUPPLEMENTARY_GROUPS_PRESENT','PRODUCER_SECURITY_CONTEXT_UNVERIFIED','PRODUCER_TRAVERSAL_DENIED','PATH_SYMLINK_OR_TYPE_VIOLATION','PATH_MISSING','PATH_LOOKUP_DENIED','PROBE_RUNTIME_UNSUPPORTED','PROBE_OS_ERROR','PROBE_INTERNAL_ERROR'}

def result(reason,path_id='NONE',errno=None):
    return {'version':1,'reason':reason,'path_id':path_id,'errno':errno}

def security_context():
    # Only this process's kernel identity/security metadata. No environments,
    # command lines, credentials or application files. procfs has no disk atime.
    fd=os.open('/proc/'+str(os.getpid())+'/status',os.O_RDONLY|os.O_NOFOLLOW)
    try:
        raw=os.read(fd,16385)
        if len(raw)>16384:return False
    finally:os.close(fd)
    fields={line.split(b':',1)[0]:line.split(b':',1)[1].strip()for line in raw.splitlines()if b':'in line}
    try:return fields[b'NoNewPrivs']==b'1' and all(int(fields[k],16)==0 for k in [b'CapEff',b'CapPrm',b'CapAmb'])
    except (KeyError,ValueError):return False

def check():
    if sys.platform!='linux' or not all(hasattr(os,k)for k in ['O_PATH','O_NOFOLLOW','getresuid','getresgid']):return result('PROBE_RUNTIME_UNSUPPORTED')
    if (os.getuid(),os.geteuid())!=(1000,1000):return result('PRODUCER_UID_MISMATCH')
    if (os.getgid(),os.getegid())!=(1000,1000):return result('PRODUCER_GID_MISMATCH')
    if os.getresuid()!=(1000,1000,1000)or os.getresgid()!=(1000,1000,1000):return result('PRODUCER_SAVED_ID_MISMATCH')
    if os.getgroups()!=[]:return result('PRODUCER_SUPPLEMENTARY_GROUPS_PRESENT')
    if not security_context():return result('PRODUCER_SECURITY_CONTEXT_UNVERIFIED')
    fd=None;path_id='FILESYSTEM_ROOT'
    try:
        fd=os.open('/',os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW)
        for path_id,name in PATHS:
            name='.'if path_id=='FILESYSTEM_ROOT'else name
            s=os.stat(name,dir_fd=fd,follow_symlinks=False)
            if not stat.S_ISDIR(s.st_mode):return result('PATH_SYMLINK_OR_TYPE_VIOLATION',path_id)
            # Exactly the original X_OK requirement, under the real/effective
            # producer identity. Never attempt with a privileged identity/group.
            if not os.access(name,os.X_OK,dir_fd=fd,follow_symlinks=False):return result('PRODUCER_TRAVERSAL_DENIED',path_id)
            if path_id!='FILESYSTEM_ROOT':
                nxt=os.open(name,os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
        return result('TRAVERSAL_PASS')
    except OSError as error:
        reason='PATH_MISSING'if error.errno==2 else'PATH_LOOKUP_DENIED'if error.errno in {1,13}else'PATH_SYMLINK_OR_TYPE_VIOLATION'if error.errno in {20,40}else'PROBE_OS_ERROR'
        return result(reason,path_id,error.errno if error.errno in {1,2,13,20,40,95}else None)
    finally:
        if fd is not None:os.close(fd)

def main():
    try:report=check()
    except Exception:report=result('PROBE_INTERNAL_ERROR')
    print(json.dumps(report,sort_keys=True));return 0 if report['reason']=='TRAVERSAL_PASS'else 1
if __name__=='__main__':raise SystemExit(main())
