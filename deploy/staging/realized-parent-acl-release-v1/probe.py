"""Fixed cleared-group producer probe. security_context is verified parent code."""
import json
import os
import stat
import sys

PATH='/srv/powerflow'
BOUNDARIES=(('PUBLISHED','published'),('FORECAST','forecast-publications'),('OPERATIONAL','operational-publications'))

def result(reason,search=None,read=None,write=None,boundary='NONE'):
    return {'version':1,'status':'PASS'if reason=='PROBE_PASS'else'BLOCKED','reason':reason,'parent_search':search,'parent_read':read,'parent_write':write,'boundary':boundary}

def check():
    if sys.platform!='linux' or not hasattr(os,'O_PATH'):return result('PROBE_RUNTIME_UNSUPPORTED')
    if os.getresuid()!=(1000,1000,1000)or os.getresgid()!=(1000,1000,1000)or os.getgroups()!=[]:return result('PRODUCER_IDENTITY_MISMATCH')
    if not security_context():return result('PRODUCER_SECURITY_CONTEXT_UNVERIFIED')
    fd=os.open(PATH,os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        s=os.fstat(fd)
        if not stat.S_ISDIR(s.st_mode)or(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))!=(0,992,0o750):return result('PARENT_METADATA_MISMATCH')
        flags=[os.access('.',mode,dir_fd=fd,follow_symlinks=False)for mode in [os.X_OK,os.R_OK,os.W_OK]]
        search,read,write=flags
        if search!=EXPECT_SEARCH or read or write:return result('PARENT_ACCESS_MISMATCH',*flags)
        try:readfd=os.open(PATH,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        except OSError as error:
            if error.errno not in {1,13}:return result('PROBE_OS_ERROR',*flags)
        else:os.close(readfd);return result('PARENT_LISTING_AVAILABLE',*flags)
        if EXPECT_SEARCH:
            for label,name in BOUNDARIES:
                s=os.stat(name,dir_fd=fd,follow_symlinks=False)
                if not stat.S_ISDIR(s.st_mode):return result('PROTECTED_BOUNDARY_TYPE',*flags,boundary=label)
                if any(os.access(name,mode,dir_fd=fd,follow_symlinks=False)for mode in [os.R_OK,os.W_OK,os.X_OK]):return result('PROTECTED_BOUNDARY_ACCESS',*flags,boundary=label)
                try:readfd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                except OSError as error:
                    if error.errno not in {1,13}:return result('PROBE_OS_ERROR',*flags,boundary=label)
                else:os.close(readfd);return result('PROTECTED_BOUNDARY_READABLE',*flags,boundary=label)
        return result('PROBE_PASS',*flags)
    finally:os.close(fd)

def main():
    try:value=check()
    except Exception:value=result('PROBE_OS_ERROR')
    print(json.dumps(value,sort_keys=True));return 0 if value['status']=='PASS'else 1
if __name__=='__main__':raise SystemExit(main())
