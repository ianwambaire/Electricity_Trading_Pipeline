"""Fixed-scope metadata/hash observation. No imports, commands or writes to apps."""
import hashlib
import json
import os
import re
import stat
import sys

RELEASE='phase-api-body-bound-20261102-v2'
ROOT='/var/www/powerflow-staging/releases/'+RELEASE
POINTER='/var/www/powerflow-staging/current'
TX='f2f195174eda43daa8e5593087fbe1d3'
RECORD='/var/lib/powerflow-staging/forecast-consistency-transactions/'+TX+'/state.json'
PREDECESSOR_SHA='4d9590d765bc745f120412525ed0d117d251236d278234aada2433d0f97ad374'

class Stop(ValueError):pass
def need(ok,code):
    if not ok:raise Stop(code)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def relative(name):
    return (type(name)is str and len(name)<=200 and
            re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*',name)is not None and
            all(x not in {'.','..'} for x in name.split('/')))
def table(value):
    need(type(value)is dict and len(value)<=160,'INVENTORY_BOUND')
    need(all(relative(k) and type(v)is str and re.fullmatch('[0-9a-f]{64}',v) for k,v in value.items()),'INVENTORY_SCHEMA')
    return value
def difference(expected,observed):
    table(expected);table(observed)
    return {'missing':{k:expected[k] for k in sorted(expected.keys()-observed.keys())},
            'unexpected':{k:observed[k] for k in sorted(observed.keys()-expected.keys())},
            'hash_mismatched':{k:{'expected':expected[k],'observed':observed[k]} for k in sorted(expected.keys()&observed.keys()) if expected[k]!=observed[k]}}
def metadata(s,directory):
    need((stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)) and s.st_uid==0 and not s.st_mode&0o022,'UNSAFE_METADATA')
def signature(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns
def directory(path):
    # Absolute ancestry opened component by component; never resolve symlinks.
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOATIME)
    try:
        metadata(os.fstat(fd),True)
        for name in path.strip('/').split('/'):
            need(relative(name) and '/' not in name,'PATH_SCOPE')
            new=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOATIME,dir_fd=fd)
            os.close(fd);fd=new;metadata(os.fstat(fd),True)
        return fd
    except BaseException:
        os.close(fd);raise
def file_bytes(fd,name,maximum):
    need(relative(name) and '/' not in name,'PATH_SCOPE')
    handle=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_NOATIME,dir_fd=fd)
    try:
        before=os.fstat(handle);metadata(before,False);need(before.st_size<=maximum,'FILE_BOUND')
        chunks=[];remaining=maximum+1
        while remaining:
            raw=os.read(handle,min(65536,remaining))
            if not raw:break
            chunks.append(raw);remaining-=len(raw)
        raw=b''.join(chunks);need(len(raw)<=maximum,'FILE_BOUND')
        need(signature(before)==signature(os.fstat(handle))==signature(os.stat(name,dir_fd=fd,follow_symlinks=False)),'FILE_CHANGED')
        return raw
    finally:os.close(handle)
def inventory(fd):
    result={};total=[0];directories=[0]
    def visit(parent,prefix,depth):
        need(depth<=4,'DEPTH_BOUND');before=os.fstat(parent)
        with os.scandir(parent) as scan:entries=list(scan)
        need(len(entries)<200,'DIRECTORY_BOUND')
        for entry in entries:
            name=prefix+entry.name;need(relative(name),'PATH_SCOPE')
            s=os.stat(entry.name,dir_fd=parent,follow_symlinks=False)
            if stat.S_ISDIR(s.st_mode):
                directories[0]+=1;need(directories[0]<=32,'DIRECTORY_BOUND')
                child=os.open(entry.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOATIME,dir_fd=parent)
                try:metadata(os.fstat(child),True);visit(child,name+'/',depth+1)
                finally:os.close(child)
            else:
                need(len(result)<160,'INVENTORY_BOUND');raw=file_bytes(parent,entry.name,2000000)
                total[0]+=len(raw);need(total[0]<8*1024**2,'TOTAL_BOUND');result[name]=sha(raw)
        need(signature(before)==signature(os.fstat(parent)),'DIRECTORY_CHANGED')
    visit(fd,'',0);need('index.html' in result,'INDEX_MISSING');return result
def pointer():
    fd=directory('/var/www/powerflow-staging')
    try:
        s=os.stat('current',dir_fd=fd,follow_symlinks=False)
        need(stat.S_ISLNK(s.st_mode) and s.st_uid==0,'POINTER_METADATA')
        value=os.readlink('current',dir_fd=fd)
        need(value in {ROOT,'releases/'+RELEASE},'POINTER_TARGET_MISMATCH')
        return value
    finally:os.close(fd)
def retained_record(approved,observed):
    fd=directory(RECORD.rsplit('/',1)[0])
    try:raw=file_bytes(fd,'state.json',131072)
    finally:os.close(fd)
    record=json.loads(raw)
    need(type(record)is dict and record.get('transaction_id')==TX and record.get('phase')=='COMPLETE' and record.get('new_static')==ROOT,'RECORD_IDENTITY')
    previous=record.get('previous_static')
    need(type(previous)is str and sha(previous.encode())==PREDECESSOR_SHA,'PREDECESSOR_BINDING')
    old=table(record.get('old_static_files'));retained=table(record.get('retained_assets'))
    derived={k:v for k,v in old.items() if re.fullmatch(r'assets/[A-Za-z0-9._-]+\.(js|css|woff2)',k)}
    need(derived==retained,'RETAINED_RECORD_INCONSISTENT')
    need(all(k not in approved or approved[k]==v for k,v in retained.items()),'RECORDED_ASSET_COLLISION')
    combined=dict(retained);combined.update(approved)
    return {'status':'VERIFIED_RECORD','record_sha256':sha(raw),'retained_count':len(retained),'expected_deployed_count':len(combined),'differences':difference(combined,observed)}
def main():
    try:
        need(sys.platform=='linux' and os.geteuid()==os.getuid()==0 and hasattr(os,'O_NOATIME'),'LINUX_ROOT_NOATIME_REQUIRED')
        table(EXPECTED);table(APPROVED);start=pointer();fd=directory(ROOT)
        try:observed=inventory(fd)
        finally:os.close(fd)
        need(pointer()==start,'POINTER_CHANGED')
        report={'status':'PASS','changed':False,'expected_count':len(EXPECTED),'approved_release_count':len(APPROVED),'observed_count':len(observed),'pointer_matches':True,'path_normalization':'POSIX_RELEASE_RELATIVE','differences':difference(EXPECTED,observed),'approved_release_differences':difference(APPROVED,observed)}
        try:report['original_transaction']=retained_record(APPROVED,observed)
        except FileNotFoundError:report['original_transaction']={'status':'MISSING'}
        except (Stop,ValueError,KeyError,TypeError,OSError):report['original_transaction']={'status':'UNVERIFIED'}
        need(pointer()==start,'POINTER_CHANGED')
    except Exception as error:
        report={'status':'BLOCKED','changed':False,'reason':str(error) if isinstance(error,Stop) else 'READ_ONLY_OBSERVATION_FAILED'}
    raw=json.dumps(report,sort_keys=True);need(len(raw.encode())<=131072,'OUTPUT_BOUND');print(raw)
    return 0 if report['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
