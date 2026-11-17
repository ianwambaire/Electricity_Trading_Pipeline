"""One-attempt hash-bound SSH inspection. Requires separate remote authorization.
Only local private captures/profile are written. No arbitrary remote command API.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
PRIVATE=ROOT/'data/backups/private-staging-releases/phase-forecast-consistency-20261101-v1'
PROFILE_SHA='6b8457d4e55d1cacdd66871e1778d43bb208a5c39d5ea9e1a47b6aba1f93b096'
TARGET_SHA='f5ab84b2a2be98b70e4f528642368b20e170d93595e6f6e9c98f7037974c1623'
KNOWN_HOSTS_SHA='df8fab3b5c8c08a6d2f85c4208e280b1ca61b75dad6168c0bdc29c4567cc73b2'
SUPERVISOR_SHA='9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40'
RELEASE_SHA='9dc8ce31f1b294c43239824ffa544a76f4fdf6ba334ea8fd72b9431365ed5c19'
TOOLS_SHA='5dbb4a5665c9c76c4daa510f98e85152dfb291b1afd5ceac477edda13bba271b'
REMOTE='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 120s /usr/bin/python3 -I -S -B -'
ARTIFACTS={'deploy/staging/forecast-consistency-release/preflight_readonly.py',
           'deploy/staging/forecast-consistency-release/run_preflight.py',
           'deploy/remediation/a3-bounded-local.py',
           'deploy/staging/forecast-consistency-release/PREFLIGHT-REVIEW.md',
           'tests/test_forecast_consistency_preflight.py'}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def file_bytes(path,limit=2_000_000):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('unsafe_local_file')
        raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('local_read_bound')
    return raw

def verify_hash(path,expected):
    raw=file_bytes(path)
    if sha(raw)!=expected:raise ValueError('hash_mismatch')
    return raw

def verify_package(expected):
    if re.fullmatch('[0-9a-f]{64}',expected) is None:raise ValueError('invalid_review_hash')
    raw=verify_hash(HERE/'PREFLIGHT-REVIEW.json',expected); review=json.loads(raw)
    if set(review['artifacts'])!=ARTIFACTS or review['schema_version']!=1:raise ValueError('review_scope')
    verified={}
    for rel,d in review['artifacts'].items():
        content=verify_hash(ROOT/rel,d['sha256'])
        if len(content)!=d['bytes']: raise ValueError('artifact_size')
        verified[rel]=content
    supervisor=verified['deploy/remediation/a3-bounded-local.py']
    if sha(supervisor)!=SUPERVISOR_SHA:raise ValueError('supervisor_hash')
    # Verify preserved originals without regenerating/repackaging either manifest.
    release=PRIVATE/'release'
    manifest=json.loads(verify_hash(release/'release-manifest.json',RELEASE_SHA))
    for name,item in manifest['files'].items():
        rel=Path(name)
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('release_path')
        content=verify_hash(release/rel,item['sha256'])
        if len(content)!=item['bytes']:raise ValueError('release_size')
    tools=json.loads(verify_hash(PRIVATE/'TOOLS-MANIFEST.json',TOOLS_SHA))
    for item in tools['artifacts']:
        rel=Path(item['path'])
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('tools_path')
        verify_hash(PRIVATE/'tooling'/rel,item['sha256'])
    payload=verified['deploy/staging/forecast-consistency-release/preflight_readonly.py']
    return payload,supervisor

def private_file(path):
    if path.resolve(strict=True)!=path:raise ValueError('private_file_symlink')
    st=path.stat()
    if st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)!=0o600 or not stat.S_ISREG(st.st_mode):raise ValueError('private_permissions')
    if stat.S_IMODE(path.parent.stat().st_mode)!=0o700:raise ValueError('private_parent_permissions')

def profile():
    path=PRIVATE/'preflight/connection.json';private_file(path)
    data=json.loads(verify_hash(path,PROFILE_SHA))
    if set(data)!={'target','identity_file','known_hosts','known_hosts_sha256'} or sha(data['target'].encode())!=TARGET_SHA:
        raise ValueError('target_identity')
    key=Path(data['identity_file']);known=Path(data['known_hosts'])
    private_file(known)
    if data['known_hosts_sha256']!=KNOWN_HOSTS_SHA:raise ValueError('host_key_binding')
    verify_hash(known,KNOWN_HOSTS_SHA)
    # Metadata only: never open/read the private key.
    st=key.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o077:
        raise ValueError('identity_permissions')
    return data

def ssh_argv(p):
    options=['BatchMode=yes','IdentitiesOnly=yes','StrictHostKeyChecking=yes',
       'UserKnownHostsFile='+p['known_hosts'],'GlobalKnownHostsFile=/dev/null',
       'ConnectTimeout=10','ConnectionAttempts=1','ServerAliveInterval=10','ServerAliveCountMax=2',
       'LogLevel=ERROR','ForwardAgent=no','ClearAllForwardings=yes','PermitLocalCommand=no',
       'ControlMaster=no','ControlPath=none','IdentityAgent=none','AddKeysToAgent=no','UpdateHostKeys=no']
    argv=['/usr/bin/ssh','-F','/dev/null','-T','-i',p['identity_file']]
    for option in options:argv+=['-o',option]
    return argv+[p['target'],REMOTE]

def failure_category(code,stderr):
    lower=stderr.lower()
    if code==124:return 'TIMEOUT'
    if b'host key verification failed' in lower or b'remote host identification has changed' in lower:return 'HOST_KEY_FAILURE'
    if b'sudo:' in lower:return 'SUDO_FAILURE'
    if code==255:return 'SSH_FAILURE'
    return 'REMOTE_FAILURE'

def execute(payload,supervisor,p,destination,run=None):
    # Compile only the retained verified payload. Its bounded IO helper is also
    # the local 180-second supervisor; no executable source pathname is reopened.
    if type(payload)is not bytes or type(supervisor)is not bytes:raise ValueError('verified_bytes_required')
    contract={'__name__':'verified_readonly_contract'}
    exec(compile(payload,'<verified-readonly-contract>','exec'),contract)
    runner=contract['bounded_run'] if run is None else run
    result=runner(ssh_argv(p),input=payload,timeout=180,limit=131072,grace=5)
    code=result['returncode']
    summary={'exit_status':code,'report_produced':False,'failure_category':result['failure'],'report':None}
    try:
        for name,raw in (('stdout.private',result['stdout']),('stderr.private',result['stderr'])):
            if len(raw)>131072:raise ValueError('capture_limit')
            with os.fdopen(os.open(destination/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as stream:stream.write(raw)
    except Exception:
        summary['failure_category']='CAPTURE_FAILURE';return summary
    if result['failure']:return summary
    try:
        report=contract['validate_report'](json.loads(result['stdout']))
        if (code==0)!=(report['status']=='PASS'):raise ValueError('exit_status_mismatch')
        summary.update(report_produced=True,report=report,failure_category=None if code==0 else 'CHECKS_BLOCKED')
    except Exception:
        summary['failure_category']=failure_category(code,result['stderr']) if code else 'UNEXPECTED_OUTPUT'
    return summary

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-sha256',required=True)
    parser.add_argument('--local-check',action='store_true',help='verify locally; NEVER invokes SSH')
    args=parser.parse_args(); destination=None
    try:
        payload,supervisor=verify_package(args.review_sha256);p=profile()
        if args.local_check:
            print(json.dumps({'local_integrity':'PASS','remote_attempts':0}));return 0
        # Private evidence writes are local only. Existing ignored root, no arbitrary output path.
        parent=PRIVATE/'preflight';destination=Path(tempfile.mkdtemp(prefix='inspection-',dir=parent));destination.chmod(0o700)
        summary=execute(payload,supervisor,p,destination)
    except subprocess.TimeoutExpired:
        summary={'exit_status':124,'report_produced':False,'failure_category':'SUPERVISOR_FAILURE','report':None}
    except Exception:
        summary={'exit_status':1,'report_produced':False,'failure_category':'LOCAL_VERIFICATION_FAILURE','report':None}
    if destination is not None:
        path=destination/'sanitized.json'
        try:
            with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as stream:json.dump(summary,stream,indent=2)
        except Exception:summary['failure_category']='REPORT_WRITE_FAILURE'
    try:print(json.dumps(summary,sort_keys=True))
    except OSError:return 1
    return 0 if summary.get('exit_status')==0 and summary.get('report_produced') and summary.get('failure_category') is None else 1

if __name__=='__main__':raise SystemExit(main())
