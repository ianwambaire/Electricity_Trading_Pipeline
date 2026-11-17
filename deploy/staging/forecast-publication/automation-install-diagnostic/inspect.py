"""Metadata/code-hash observations only. No subprocess, network or mutation API.
CONFIG is supplied as data by the separately hash-verified local runner.
"""
import datetime as dt
import hashlib
import json
import os
import stat
import sys

MAX_FILE=200000
OWNER=GROUP=0
class Stop(ValueError):pass
def require(value,cause):
    if not value:raise Stop(cause)
def kind(mode):
    return 'DIRECTORY' if stat.S_ISDIR(mode) else 'REGULAR_FILE' if stat.S_ISREG(mode) else 'SYMLINK' if stat.S_ISLNK(mode) else 'OTHER'
def metadata(info):
    return {'exists':True,'type':kind(info.st_mode),'uid':info.st_uid,'gid':info.st_gid,'mode':format(stat.S_IMODE(info.st_mode),'04o'),'links':info.st_nlink}
def flags():return os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,'O_NOATIME',0)
def anchor(path):
    # Every ancestor is anchored; no symlink resolution or permissive fallback.
    require(path.startswith('/') and all(p not in {'.','..'} for p in path.split('/')),'PATH_SCOPE')
    fd=os.open('/',flags())
    try:
        for part in path.split('/')[1:]:
            if not part:continue
            before=os.stat(part,dir_fd=fd,follow_symlinks=False)
            require(stat.S_ISDIR(before.st_mode),'UNSAFE_ANCESTOR')
            new=os.open(part,flags(),dir_fd=fd);after=os.fstat(new)
            if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):os.close(new);raise Stop('PATH_CHANGED')
            os.close(fd);fd=new
        return fd
    except Exception:os.close(fd);raise

def observe(path,hash_file=False):
    parent,name=path.rsplit('/',1);fd=anchor(parent)
    try:
        try:info=os.stat(name,dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError:return {'exists':False}
        result=metadata(info)
        if stat.S_ISLNK(info.st_mode):
            if hash_file:raise Stop('SYMLINK_REJECTED')
            return result
        if hash_file:
            require(stat.S_ISREG(info.st_mode) and info.st_size<=MAX_FILE,'FILE_TYPE_OR_BOUND')
            if info.st_uid!=OWNER or info.st_gid!=GROUP or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:
                result['hash_status']='UNVERIFIED_UNSAFE_METADATA';return result
            file=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|getattr(os,'O_NOATIME',0),dir_fd=fd)
            with os.fdopen(file,'rb') as stream:
                before=os.fstat(stream.fileno());require((before.st_dev,before.st_ino)==(info.st_dev,info.st_ino),'FILE_CHANGED')
                raw=stream.read(MAX_FILE+1);after=os.fstat(stream.fileno())
                require(len(raw)<=MAX_FILE and len(raw)==before.st_size and (before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns),'FILE_CHANGED_OR_BOUND')
            result.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        return result
    finally:os.close(fd)

def dac(path,uid=1000,gid=1000):
    # Passive POSIX owner/primary-group/other bits only; never claim ACL/namespace proof.
    fd=os.open('/',flags())
    try:
        for part in path.split('/')[1:]:
            if not part:continue
            info=os.stat(part,dir_fd=fd,follow_symlinks=False)
            require(stat.S_ISDIR(info.st_mode),'UNSAFE_ANCESTOR')
            bits=(info.st_mode>>(6 if info.st_uid==uid else 3 if info.st_gid==gid else 0))&7
            if not bits&1:return False
            new=os.open(part,flags(),dir_fd=fd);os.close(fd);fd=new
        info=os.fstat(fd);bits=(info.st_mode>>(6 if info.st_uid==uid else 3 if info.st_gid==gid else 0))&7
        return bits&5==5
    finally:os.close(fd)

def inventory(root,expected):
    records={};issues=[]
    root_meta=observe(root)
    if not root_meta['exists']:return {'root':root_meta,'files':{},'state':'MISSING','issues':['TOOLS_MISSING']}
    require(root_meta['type']=='DIRECTORY','TOOLS_NOT_DIRECTORY')
    if (root_meta['uid'],root_meta['gid'],root_meta['mode'])!=(OWNER,GROUP,'0700'):issues.append('TOOLS_DIRECTORY_METADATA')
    pending=[('',root)];found=set();count=0
    while pending:
        relative,path=pending.pop();fd=anchor(path)
        try:
            names=[]
            with os.scandir(fd) as entries:
                for entry in entries:
                    count+=1;require(count<=24,'INVENTORY_BOUND');names.append(entry.name)
            for name in sorted(names):
                label=relative+name
                # No arbitrary names, file contents or unapproved subtrees are disclosed/read.
                require(label in expected or label=='shared','UNEXPECTED_ENTRY')
                info=os.stat(name,dir_fd=fd,follow_symlinks=False)
                require(not stat.S_ISLNK(info.st_mode),'SYMLINK_REJECTED')
                if label=='shared':
                    require(stat.S_ISDIR(info.st_mode),'TOOLS_SHARED_TYPE')
                    shared=metadata(info);records['shared/']=shared
                    if (shared['uid'],shared['gid'],shared['mode'])!=(OWNER,GROUP,'0700'):issues.append('TOOLS_DIRECTORY_METADATA')
                    pending.append(('shared/',path+'/'+name))
                else:
                    require(stat.S_ISREG(info.st_mode),'TOOLS_FILE_TYPE')
                    record=observe(path+'/'+name,True);found.add(label)
                    record['hash_match']=record['sha256']==expected[label] if 'sha256' in record else None
                    record['metadata_match']=(record['uid'],record['gid'],record['mode'])==(OWNER,GROUP,'0600') and record['links']==1
                    records[label]=record
                    if record['hash_match'] is False:issues.append('TOOLS_HASH_MISMATCH')
                    if not record['metadata_match']:issues.append('TOOLS_FILE_METADATA')
        finally:os.close(fd)
    missing=sorted(set(expected)-found)
    if missing:issues.append('INCOMPLETE_INVENTORY')
    return {'root':root_meta,'files':records,'missing_files':missing,'state':'MATCH' if not issues else 'MISMATCH' if any('HASH' in x or 'METADATA' in x for x in issues) else 'INCOMPLETE','issues':sorted(set(issues))}

CAUSES={'PATH_SCOPE','UNSAFE_ANCESTOR','PATH_CHANGED','SYMLINK_REJECTED','FILE_TYPE_OR_BOUND','FILE_CHANGED','FILE_CHANGED_OR_BOUND','TOOLS_NOT_DIRECTORY','INVENTORY_BOUND','UNEXPECTED_ENTRY','TOOLS_SHARED_TYPE','TOOLS_FILE_TYPE'}
def inspect(config):
    out={'schema_version':1,'status':'UNVERIFIED','transaction':config['transaction'],'original_manifest_sha256':config['original_manifest_sha256'],'observed_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'remote_mutations':False,'historical_cause':'UNVERIFIED','evidence_basis':'CURRENT_POST_ROLLBACK_METADATA','stage':'PRODUCTION_DIRECTORY'}
    try:
        parent=observe(config['production_parent']);out['production_parent']=parent
        if parent.get('type')=='SYMLINK':raise Stop('SYMLINK_REJECTED')
        if parent['exists'] and parent['type']=='DIRECTORY':
            shared=observe(config['production_parent']+'/shared');out['production_shared']=shared
            if shared.get('type')=='SYMLINK':raise Stop('SYMLINK_REJECTED')
            if shared['exists'] and shared['type']=='DIRECTORY':
                shared['primary_group_posix_read_traverse']=dac(config['production_parent']+'/shared',config['pipeline_uid'],config['pipeline_gid'])
                shared['effective_pipeline_access']='UNVERIFIED'
                shared['access_identity']={'uid':config['pipeline_uid'],'gid':config['pipeline_gid'],'supplementary_groups':'UNVERIFIED'}
                out['interpretation']='MISSING_PARENT_NOT_OBSERVED_NOW'
            elif not shared['exists']:out['interpretation']='CONSISTENT_WITH_REPRODUCED_MISSING_PARENT'
            else:out['interpretation']='CURRENT_DESTINATION_TYPE_DEFECT'
        else:
            out['production_shared']={'exists':None};out['interpretation']='PRODUCTION_PARENT_UNAVAILABLE'
        out['stage']='RETAINED_TOOLS';out['tools']=inventory(config['tools_root'],config['expected_files'])
        out['stage']='COMPLETE';out['status']='OBSERVED' if out['tools']['state'] in {'MATCH','MISSING','INCOMPLETE'} and out['interpretation']!='CURRENT_DESTINATION_TYPE_DEFECT' else 'FINDINGS'
    except Exception as error:
        out['cause']=str(error) if type(error)is Stop and str(error) in CAUSES else 'MISSING_ANCESTOR' if isinstance(error,FileNotFoundError) else 'PERMISSION_DENIED' if isinstance(error,PermissionError) else 'INSPECTION_FAILED'
    return out

if __name__=='__main__':
    result=inspect(CONFIG)
    raw=json.dumps(result,sort_keys=True)
    if len(raw.encode())>16384:raw=json.dumps({'status':'UNVERIFIED','cause':'OUTPUT_BOUND','remote_mutations':False})
    print(raw);raise SystemExit(0 if result['status']=='OBSERVED' else 1)
