"""Single-document atomic publication; separate namespace, never forecast pointers.

Root/releases and marker must be independently provisioned. Producer owns only
this derived-data namespace. Candidate API receives a read-only mount/group read.
"""
import contextlib
import datetime as dt
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import uuid
from .realized_report import MAX_BYTES,require,validate,encode,stamp
MARKER=b'powerflow-realized-performance-v1\n'
FLAGS=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW

def directory(parent,name):
    fd=os.open(name,FLAGS,dir_fd=parent);s=os.fstat(fd)
    try:require(stat.S_ISDIR(s.st_mode) and s.st_uid in {0,1000,os.geteuid()} and not s.st_mode&0o022);return fd
    except Exception:os.close(fd);raise

def read_file(parent,name,limit=MAX_BYTES):
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
    try:
        s=os.fstat(fd);require(stat.S_ISREG(s.st_mode) and s.st_uid in {0,1000,os.geteuid()} and not s.st_mode&0o022 and s.st_nlink==1 and s.st_size<=limit)
        with os.fdopen(os.dup(fd),'rb')as f:raw=f.read(limit+1)
        after=os.fstat(fd);require(len(raw)==s.st_size and (s.st_size,s.st_mtime_ns,s.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns));return raw
    finally:os.close(fd)

@contextlib.contextmanager
def opened(root):
    p=Path(root);require(p.is_absolute() and '..'not in p.parts)
    fd=os.open('/',FLAGS)
    try:
        for part in p.parts[1:]:nxt=directory(fd,part);os.close(fd);fd=nxt
        require(read_file(fd,'contract',100)==MARKER)
        releases=directory(fd,'releases')
        try:yield fd,releases
        finally:os.close(releases)
    finally:os.close(fd)

def pointer(fd):
    try:raw=read_file(fd,'current',65)
    except FileNotFoundError:return None
    require(re.fullmatch(b'[0-9a-f]{64}\n',raw)is not None);return raw.decode().strip()

def content(releases,digest):
    require(re.fullmatch('[0-9a-f]{64}',digest)is not None);fd=directory(releases,digest)
    try:raw=read_file(fd,'report.json');require(hashlib.sha256(raw).hexdigest()==digest);return raw
    finally:os.close(fd)

def read_active(root,now):
    with opened(root)as(fd,releases):
        selected=pointer(fd)
        if selected is None:raise FileNotFoundError('REALIZED_REPORT_MISSING')
        raw=content(releases,selected);document=validate(raw,now)
        require(pointer(fd)==selected);return document,selected

def write(parent,name,raw):
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o640,dir_fd=parent)
    try:
        os.fchmod(fd,0o640)
        with os.fdopen(os.dup(fd),'wb')as f:f.write(raw);f.flush();os.fsync(f.fileno())
    finally:os.close(fd)

def publish(root,document,*,now=None):
    now=now or dt.datetime.now(dt.timezone.utc);raw=encode(document);validate(raw,now);digest=hashlib.sha256(raw).hexdigest()
    with opened(root)as(fd,releases):
        lock=os.open('.publication.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=fd)
        temporary=None
        try:
            s=os.fstat(lock);require(stat.S_ISREG(s.st_mode) and s.st_uid==os.geteuid() and s.st_nlink==1 and not s.st_mode&0o077)
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            previous=pointer(fd)
            if previous:
                old=validate(content(releases,previous),now);require(stamp(document['generated_at'])>=stamp(old['generated_at']))
                if document['generated_at']==old['generated_at']:require(digest==previous)
            try:os.mkdir(digest,0o2700,dir_fd=releases)
            except FileExistsError:require(content(releases,digest)==raw)
            else:
                target=directory(releases,digest)
                try:write(target,'report.json',raw);os.fchmod(target,0o2750);os.fsync(target)
                finally:os.close(target)
            require(content(releases,digest)==raw);os.fsync(releases)
            temporary='.current-'+uuid.uuid4().hex;write(fd,temporary,(digest+'\n').encode())
            require(pointer(fd)==previous)
            os.replace(temporary,'current',src_dir_fd=fd,dst_dir_fd=fd);temporary=None;os.fsync(fd)
            return digest
        finally:
            if temporary:
                try:os.unlink(temporary,dir_fd=fd)
                except FileNotFoundError:pass
            os.close(lock)
