#!/usr/bin/env python3
"""Hash-verified stdin bootstrap; copies only public artifacts to a new root-private control dir."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import types

ID='phase-staging-https-ready-20261026'
INCOMING=Path('/home/ec2-user/powerflow-staging-incoming-'+ID+'-r2')
CONTROL=Path('/var/lib/powerflow-staging-install')/ID


def need(x,code):
    if not x:raise RuntimeError(code)


def read(path):
    for p in (path,*path.parents):need(not p.is_symlink(),'bootstrap_symlink')
    need(path.is_file() and path.stat().st_size<=64*1024**2,'bootstrap_file_limit')
    return path.read_bytes()


def main(expected):
    need(os.geteuid()==0,'root_required');need(re.fullmatch('[a-f0-9]{64}',expected),'bundle_hash_format')
    raw=read(INCOMING/'bundle.json');need(hashlib.sha256(raw).hexdigest()==expected,'bundle_hash_changed')
    bundle=json.loads(raw);need(bundle['release_id']==ID,'release_id')
    verified={}
    for name,h in bundle['control_hashes'].items():
        need(re.fullmatch('[A-Za-z0-9._-]+',name),'bootstrap_control_name')
        data=read(INCOMING/name);need(hashlib.sha256(data).hexdigest()==h,'bootstrap_control_hash');verified[name]=data
    for item in bundle['artifacts']:
        name=item['name'];need(re.fullmatch('[A-Za-z0-9._-]+',name),'bootstrap_artifact_name')
        data=read(INCOMING/name);need(len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256'],'bootstrap_artifact_hash');verified[name]=data
    module=types.ModuleType('verified_publisher');exec(compile(verified['publisher.py'],'verified_publisher','exec'),module.__dict__)
    module.validate_sources(bundle['publication_plan'])
    for path in (Path('/srv/powerflow'),Path('/srv/powerflow/published'),Path('/opt/powerflow/releases')/ID,Path('/var/www/powerflow-staging/releases')/ID,CONTROL):
        need(not os.path.lexists(path),'bootstrap_destination_conflict')
    mem=int(re.search(r'MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text())[1])*1024
    need(mem>=768*1024**2,'bootstrap_memory_guard')
    for path in ('/srv','/var','/opt'):
        fs=os.statvfs(path);need(fs.f_bavail*fs.f_frsize>=bundle['disk_budget_bytes']+3*1024**3,'bootstrap_disk_guard')
    os.umask(0o077)
    if CONTROL.parent.exists():
        s=CONTROL.parent.stat();need(s.st_uid==0 and not s.st_mode&0o077,'bootstrap_control_parent_permissions')
    else:CONTROL.parent.mkdir(mode=0o700)
    CONTROL.mkdir(mode=0o700)
    for name,data in {'bundle.json':raw,**verified}.items():
        fd=os.open(CONTROL/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as h:h.write(data);h.flush();os.fsync(h.fileno())
    # No production working tree or venv is modified. Installer is now root-private.
    result=subprocess.run(['/usr/bin/python3.14','-I','-S','-B',str(CONTROL/'install.py'),'install'],timeout=600,
                          env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C','PYTHONDONTWRITEBYTECODE':'1'})
    return result.returncode

if __name__=='__main__':
    try:raise SystemExit(main(sys.argv[1]))
    except (RuntimeError,OSError,ValueError,IndexError,subprocess.TimeoutExpired) as e:
        print(json.dumps({'status':'failed','phase':'bootstrap','error_type':type(e).__name__,
                          'safe_error':str(e) if isinstance(e,RuntimeError) else 'details_withheld','retry':False}));raise SystemExit(1)
