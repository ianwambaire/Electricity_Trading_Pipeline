"""Hash-bound one-time staging publication setup. Separate authorization required.
--local-check never connects. No publication or arbitrary remote command option.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
JOB='deploy/staging/forecast-publication/setup_first.py'
CORE='deploy/staging/forecast-consistency-release/preflight_readonly.py'
WRAPPER='deploy/staging/forecast-consistency-release/run_preflight.py'
PACKET_SHA='faeec014b4cde838fcffb3c285eef1995f38547d443162e529fa90ec7209a6b3'
PACKET=ROOT/('data/backups/private-staging-releases/forecast-publication-tools-'+PACKET_SHA+'/tools.tar.gz')
ARTIFACTS={JOB,CORE,WRAPPER,'deploy/staging/forecast-publication/run_first_setup.py',
 'deploy/staging/forecast-publication/FIRST-PUBLICATION-REVIEW.md','tests/test_first_publication_setup.py'}

def read(path,limit=200000):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise ValueError('regular_file')
        raw=f.read(limit+1)
    if len(raw)>limit:raise ValueError('read_bound')
    return raw

def namespace(raw,name,file=None):
    value={'__name__':name}
    if file is not None:value['__file__']=str(file)
    exec(compile(raw,'<verified-'+name+'>','exec'),value);return value

def assemble(blobs,packet):
    return ("BASE={'__name__':'verified_base'}\nexec(compile("+repr(blobs[CORE])+",'<verified-base>','exec'),BASE)\n"+
     'CONFIG='+repr({'packet':base64.b64encode(packet).decode()})+'\n'+
     'exec(compile('+repr(blobs[JOB])+",'<verified-setup>','exec'),{'__name__':'__main__','BASE':BASE,'CONFIG':CONFIG})\n").encode()

def verify(expected):
    raw=read(HERE/'FIRST-SETUP-MANIFEST.json')
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('manifest_hash')
    m=json.loads(raw)
    if set(m)!={'version','packet_sha256','packet_bytes','artifacts','payload_sha256'} or m['version']!=1 or set(m['artifacts'])!=ARTIFACTS or m['packet_sha256']!=PACKET_SHA or m['packet_bytes']!=6470:raise ValueError('manifest_scope')
    blobs={}
    for name,item in m['artifacts'].items():
        data=read(ROOT/name)
        if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('artifact_hash')
        blobs[name]=data
    packet=read(PACKET,6470)
    if len(packet)!=6470 or hashlib.sha256(packet).hexdigest()!=PACKET_SHA:raise ValueError('packet_hash')
    payload=assemble(blobs,packet)
    if len(payload)>200000 or hashlib.sha256(payload).hexdigest()!=m['payload_sha256']:raise ValueError('payload_hash')
    wrapper=namespace(blobs[WRAPPER],'wrapper',ROOT/WRAPPER);wrapper['profile']()
    return payload,wrapper,namespace(blobs[CORE],'base')

REASONS={'ROOT_REQUIRED','CONFIG_SCOPE','PACKET_HASH','PACKET_INVENTORY','PACKET_SOURCE_HASH','PACKET_MANIFEST','UNSAFE_DIRECTORY','DIRECTORY_MODE','DIRECTORY_GROUP','FILE_TYPE','READ_BOUND','TOOLS_INVENTORY','TOOLS_METADATA','TOOLS_HASH','INSPECTION_COMMAND_FAILED','CANDIDATE_IDENTITY','ACCESS_SCOPE','CANDIDATE_DIRECTORY_ACCESS','CANDIDATE_CHANGED','WRITE_SCOPE','SYSTEM_EXECUTABLE','NOT_FIRST_PUBLICATION','TOOLS_WRITE_VERIFY','PUBLISHER_DIRECTORY_ACCESS','SETUP_CHECK_FAILED'}

def validate(report,code):
    if type(report)is not dict:raise ValueError('report')
    if code==0:
        if set(report)!={'status','phase','changed','tools','candidate_directory_access','candidate_bundle_access','publisher_directory_access','active_pointer_absent','publication_performed'} or report['status']!='SETUP_READY' or report['phase']!='COMPLETE' or type(report['changed'])is not bool or report['tools'] not in {'INSTALLED','REUSED'} or report['candidate_directory_access']!='PASS' or report['candidate_bundle_access']!='UNVERIFIED_NO_BUNDLE' or report['publisher_directory_access']!='PASS' or report['active_pointer_absent'] is not True or report['publication_performed'] is not False:raise ValueError('success_evidence')
    else:
        if code!=1 or set(report)!={'status','phase','changed','reason','publication_performed'} or type(report['changed'])is not bool or report['status']!=('PARTIAL' if report['changed'] else 'BLOCKED') or report['phase'] not in {'PREFLIGHT','SETUP','ACCESS'} or report['reason'] not in REASONS or report['publication_performed'] is not False:raise ValueError('failure_evidence')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args()
    capture=None;out={'exit_status':None,'failure_category':'LOCAL_VERIFICATION_FAILURE','report':None}
    try:
        payload,w,b=verify(a.manifest_sha256)
        if a.local_check:print('{"local_integrity":"PASS","remote_attempts":0}');return 0
        argv=w['ssh_argv'](w['profile']());argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/python3 -I -S -B -'
        capture=Path(tempfile.mkdtemp(prefix='first-publication-setup-',dir=w['PRIVATE']/'preflight'));capture.chmod(0o700)
        result=b['bounded_run'](argv,input=payload,timeout=120,limit=131072,grace=5)
        out={'exit_status':result['returncode'],'failure_category':result['failure'],'report':None}
        for name in ('stdout','stderr'):
            with os.fdopen(os.open(capture/(name+'.private'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:f.write(result[name])
        if not result['failure']:
            try:out['report']=validate(json.loads(result['stdout']),result['returncode'])
            except Exception:out['failure_category']=w['failure_category'](result['returncode'],result['stderr']) if result['returncode'] else 'UNEXPECTED_OUTPUT'
    except Exception:
        if capture is not None:out['failure_category']='EXECUTION_OR_CAPTURE_FAILURE'
    if capture is not None:
        try:
            with os.fdopen(os.open(capture/'sanitized.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as f:json.dump(out,f,indent=2)
        except Exception:out['failure_category']='REPORT_WRITE_FAILURE'
    try:print(json.dumps(out,sort_keys=True))
    except OSError:return 1
    return 0 if out['exit_status']==0 and out['report'] is not None and not out['failure_category'] else 1

if __name__=='__main__':raise SystemExit(main())
