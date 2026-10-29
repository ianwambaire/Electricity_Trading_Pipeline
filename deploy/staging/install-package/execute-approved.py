#!/usr/bin/env python3
"""Separate explicit approval required. One bounded operation, no retries or cleanup."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ID='phase-staging-https-ready-20261026'
TARGET='ec2-user@3.228.243.164'
INCOMING='/home/ec2-user/powerflow-staging-incoming-'+ID+'-r2'
CONTROL='/var/lib/powerflow-staging-install/'+ID
OPTIONS=['-i','/Users/iannganga/.ssh/powerflow-key.pem','-o','IdentitiesOnly=yes','-o','BatchMode=yes',
 '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts',
 '-o','ConnectTimeout=10','-o','ConnectionAttempts=1','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2','-o','LogLevel=ERROR']

def require(x,message):
    if not x:raise RuntimeError(message)

def verify(directory,expected):
    raw=(directory/'bundle.json').read_bytes();require(hashlib.sha256(raw).hexdigest()==expected,'bundle_hash')
    bundle=json.loads(raw);require(bundle['release_id']==ID,'release_id')
    names=['bundle.json',*bundle['control_hashes'],*[x['name'] for x in bundle['artifacts']]]
    require(len(names)==len(set(names)) and set(names)=={p.name for p in directory.iterdir()},'local_bundle_exact_inventory')
    for name,h in bundle['control_hashes'].items():
        require(not (directory/name).is_symlink() and hashlib.sha256((directory/name).read_bytes()).hexdigest()==h,'control_hash')
    for item in bundle['artifacts']:
        p=directory/item['name'];require(not p.is_symlink() and p.stat().st_size==item['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256'],'artifact_hash')
    return bundle,names

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('transfer','install','activate','rollback'));p.add_argument('--bundle',type=Path,required=True);p.add_argument('--sha256',required=True);args=p.parse_args()
    os.umask(0o077);bundle,names=verify(args.bundle,args.sha256)
    root=Path(__file__).resolve().parents[3];supervisor=root/'deploy/remediation/a3-bounded-local.py'
    require(hashlib.sha256(supervisor.read_bytes()).hexdigest()=='9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40','supervisor_hash')
    spec=importlib.util.spec_from_file_location('bounded',supervisor);bounded=importlib.util.module_from_spec(spec);spec.loader.exec_module(bounded)
    capture=Path(tempfile.mkdtemp(prefix='powerflow-staging-'+args.action+'-',dir='/private/tmp'))
    def once(label,command,seconds,stdin=None):
        with (capture/(label+'.stdout')).open('xb') as out,(capture/(label+'.stderr')).open('xb') as err:
            # Supervisor inherits only these private descriptors; TERM group, then KILL+5s.
            code='import importlib.util,sys; s=importlib.util.spec_from_file_location("bounded",sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); raise SystemExit(m.run(sys.argv[3:],seconds=int(sys.argv[2]),grace=5))'
            r=subprocess.run([sys.executable,'-I','-B','-c',code,str(supervisor),str(seconds),*command],stdin=stdin,stdout=out,stderr=err)
        require(r.returncode==0,label+'_exit_'+str(r.returncode))
    try:
        if args.action=='transfer':
            # Two bounded transport operations; first directory is exclusive, no sudo.
            remote="umask 077; test ! -e '"+INCOMING+"' && test ! -L '"+INCOMING+"' && mkdir -m 700 '"+INCOMING+"'"
            once('incoming-directory',['ssh',*OPTIONS,TARGET,remote],30)
            once('public-artifact-transfer',['scp',*OPTIONS,*[str(args.bundle/n) for n in names],TARGET+':'+INCOMING+'/'],120)
        elif args.action=='install':
            with (args.bundle/'bootstrap.py').open('rb') as source:
                once('isolated-install',['ssh',*OPTIONS,TARGET,'sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 660s /usr/bin/python3.14 -I -S -B - '+args.sha256],700,source)
        else:
            remote_seconds=300 if args.action=='activate' else 120
            # Private bundle/control hashes checked by installer; stdin launcher binds bundle too.
            launcher=("import hashlib,pathlib,runpy,sys; p=pathlib.Path('"+CONTROL+"'); "
                      "assert hashlib.sha256((p/'bundle.json').read_bytes()).hexdigest()=='"+args.sha256+"'; "
                      "assert hashlib.sha256((p/'install.py').read_bytes()).hexdigest()=='"+bundle['control_hashes']['install.py']+"'; "
                      "sys.argv=[str(p/'install.py'),'"+args.action+"']; runpy.run_path(str(p/'install.py'),run_name='__main__')\n").encode()
            with tempfile.TemporaryFile() as source:
                source.write(launcher);source.seek(0)
                once(args.action,['ssh',*OPTIONS,TARGET,'sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s '+str(remote_seconds)+'s /usr/bin/python3.14 -I -S -B -'],remote_seconds+40,source)
        print(json.dumps({'action':args.action,'exit_status':0,'capture_directory':str(capture),'automatic_retry':False,'automatic_rollback':False}))
    except RuntimeError as e:
        print(json.dumps({'action':args.action,'status':'STOPPED','safe_error':str(e),'capture_directory':str(capture),'automatic_retry':False}));return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
