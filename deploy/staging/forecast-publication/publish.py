"""Local preparation CLI; execution on EC2 requires separate explicit approval."""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

from shared.forecast_publication import MAX_BYTES, Withheld, require, validate, safe_file, read_active

DEFAULT_ROOT = Path('/srv/powerflow/forecast-publications')

def safe_directory(path):
    require(path.is_dir() and not path.is_symlink() and path.stat().st_uid in (0,os.geteuid()) and not path.stat().st_mode & 0o022)

def pointer(root):
    if not os.path.lexists(root/'current'):
        return None
    target = os.readlink(root/'current')
    require(re.fullmatch(r'releases/[0-9a-f]{64}', target) is not None)
    return target.split('/')[1]

@contextlib.contextmanager
def locked(root):
    safe_directory(root);safe_directory(root/'releases')
    fd=os.open(root/'.publication.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)

def switch(root, digest, expected_current, clock):
    require(pointer(root)==expected_current)
    if digest is not None:
        path=root/'releases'/digest
        safe_directory(path)
        validate(safe_file(path/'bundle.json'),digest,clock())
        pending=root/('.pointer-'+uuid.uuid4().hex)
        os.symlink('releases/'+digest,pending)
        # A second expiry check immediately before atomic activation.
        validate(safe_file(path/'bundle.json'),digest,clock())
        os.replace(pending,root/'current')
    elif expected_current is not None:
        # Retain withdrawn pointer for audit; missing current is WITHHELD.
        os.rename(root/'current',root/('.withdrawn-'+uuid.uuid4().hex))
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

def publish(root, source, digest, expected_current, clock=lambda:dt.datetime.now(dt.timezone.utc)):
    root=Path(root);source=Path(source)
    with locked(root):
        require(pointer(root)==expected_current)
        raw=safe_file(source);validate(raw,digest,clock())
        destination=root/'releases'/digest
        require(not os.path.lexists(destination))
        temporary=root/'releases'/('.partial-'+uuid.uuid4().hex)
        temporary.mkdir(mode=0o750);os.chmod(temporary,0o750)
        file=temporary/'bundle.json'
        with file.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.chmod(file,0o640)
        if os.geteuid()==0:
            # Dedicated staging reader group; no world-readable operational data.
            os.chown(temporary,0,992);os.chown(file,0,992)
        validate(safe_file(file),digest,clock())
        directory_fd=os.open(temporary,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory_fd)
        finally:os.close(directory_fd)
        os.rename(temporary,destination)
        directory_fd=os.open(root/'releases',os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory_fd)
        finally:os.close(directory_fd)
        switch(root,digest,expected_current,clock)
        return {'published_sha256':digest,'previous_sha256':expected_current,'bytes':len(raw)}

def rollback(root, current, previous, clock=lambda:dt.datetime.now(dt.timezone.utc)):
    root=Path(root)
    require(re.fullmatch('[0-9a-f]{64}',current or '') is not None)
    require(previous is None or re.fullmatch('[0-9a-f]{64}',previous) is not None)
    with locked(root):
        switch(root,previous,current,clock)
    return {'previous_current':current,'restored':previous,'withdrawn':previous is None}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['publish','verify','rollback','withdraw'])
    parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--expected-current',default='none')
    parser.add_argument('--previous')
    args=parser.parse_args()
    require(args.root==DEFAULT_ROOT and os.geteuid()==0)
    safe_directory(args.root.parent);safe_directory(args.root.parent.parent)
    if args.action=='publish':
        require(args.source is not None)
        result=publish(args.root,args.source,args.sha256,None if args.expected_current=='none' else args.expected_current)
    elif args.action=='verify':
        with locked(args.root):
            require(pointer(args.root)==args.sha256)
            bundle=read_active(args.root)
            result={'status':'VALID','sha256':args.sha256,'issue':bundle['forecasts'][0]['issue_time']}
    else:
        require(args.action=='withdraw' or args.previous is not None)
        result=rollback(args.root,args.sha256,None if args.action=='withdraw' else args.previous)
    print(json.dumps(result))

if __name__=='__main__':
    try:main()
    except Exception:
        print(json.dumps({'status':'STOPPED','reason':'Publication safety gate failed. No automatic retry or rollback.'}));raise SystemExit(1)
