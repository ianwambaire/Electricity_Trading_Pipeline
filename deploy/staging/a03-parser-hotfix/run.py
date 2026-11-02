"""Fixed parser-only apply/rollback runner. No network with --local-check."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
JOB='deploy/staging/a03-parser-hotfix/deploy.py'
SOURCE='src/ingestion/fetch_entsoe_data.py'
BASE='deploy/staging/forecast-consistency-release/preflight_readonly.py'
WRAPPER='deploy/staging/forecast-consistency-release/run_preflight.py'
ARTIFACTS={JOB,SOURCE,BASE,WRAPPER,'deploy/staging/a03-parser-hotfix/run.py',
 'deploy/staging/a03-parser-hotfix/REVIEW.md','deploy/staging/a03-parser-hotfix/BASELINE-COMPARISON.json','tests/test_a03_parser_hotfix.py'}
NEW='8800f34a2d0e3db4056e921a7b6629847402f37c20ff9b3e81d50f3c1d77865f'
OLD='ee1d225895fbf929127a577ca4f85a6855643186a7590cda5eaa27ac6aa21a2a'

def read(path):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        import stat
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise ValueError('regular_file')
        raw=f.read(2000001)
    if len(raw)>2000000:raise ValueError('size_bound')
    return raw

def namespace(raw,name,path=None):
    value={'__name__':name}
    if path is not None:value['__file__']=str(path)
    exec(compile(raw,'<verified-'+name+'>','exec'),value);return value

def assemble(blobs,transaction,action):
    if action not in ('apply','rollback') or type(transaction)is not str or not re.fullmatch('[0-9a-f]{32}',transaction):raise ValueError('action_or_transaction')
    return ("BASE={'__name__':'verified_base'}\nexec(compile("+repr(blobs[BASE])+",'<verified-base>','exec'),BASE)\n"+
      'CONFIG='+repr({'transaction_id':transaction,'source':blobs[SOURCE]})+'\nACTION='+repr(action)+'\n'+
      'exec(compile('+repr(blobs[JOB])+",'<verified-parser-job>','exec'),{'__name__':'__main__','BASE':BASE,'CONFIG':CONFIG,'ACTION':ACTION})\n").encode()

def verify(expected,action):
    raw=read(HERE/'MANIFEST.json')
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('manifest_hash')
    m=json.loads(raw)
    if set(m)!={'version','transaction_id','baseline_sha256','new_sha256','artifacts','assembled_sha256'} or m['version']!=1 or set(m['artifacts'])!=ARTIFACTS or m['baseline_sha256']!=OLD or m['new_sha256']!=NEW:raise ValueError('manifest_scope')
    blobs={}
    for name,item in m['artifacts'].items():
        value=read(ROOT/name)
        if len(value)!=item['bytes'] or hashlib.sha256(value).hexdigest()!=item['sha256']:raise ValueError('artifact_hash')
        blobs[name]=value
    if hashlib.sha256(blobs[SOURCE]).hexdigest()!=NEW:raise ValueError('source_hash')
    payload=assemble(blobs,m['transaction_id'],action)
    if len(payload)>2000000 or hashlib.sha256(payload).hexdigest()!=m['assembled_sha256'][action]:raise ValueError('payload_hash')
    wrapper=namespace(blobs[WRAPPER],'wrapper',ROOT/WRAPPER);wrapper['profile']()
    return payload,wrapper,namespace(blobs[BASE],'base')

REASONS={'ROOT_REQUIRED','TRANSACTION_ID','SOURCE_HASH','UNSAFE_PATH','SOURCE_METADATA','PRODUCTION_BASELINE_DRIFT',
 'TRANSACTION_COLLISION','BACKUP_PARENT_MODE','RAM_GATE','DISK_GATE','PIPELINE_OR_WINDOW_GATE','SERVICE_STATE','MODEL_HASH',
 'WRITE_VERIFICATION','BACKUP_VERIFY','PRODUCTION_DRIFT','SOURCE_DRIFT_AT_REPLACE','INSTALLED_VERIFY','BACKUP_METADATA','ROLLBACK_RECORD',
 'ROLLBACK_SOURCE_DRIFT','ROLLBACK_VERIFY','ACTION_SCOPE','PERMISSION_DENIED','MISSING_FILE','UNEXPECTED_EXCEPTION'}
PHASES={'PREFLIGHT','BACKUPS','INSTALL','VERIFY','COMPLETE','ROLLBACK','ROLLED_BACK'}
def validate(report,action,code):
    if type(report)is not dict or type(code)is not int or action not in ('apply','rollback'):raise ValueError('report')
    if code==0:
        keys={'status','phase','parser_hash_verified','backup_verified','production_preserved','no_services_restarted','resources'}
        if set(report)!=keys or report['status']!=('APPLIED' if action=='apply' else 'ROLLED_BACK') or report['phase']!=('COMPLETE' if action=='apply' else 'ROLLED_BACK'):raise ValueError('success_shape')
        if any(report[k]is not True for k in ('parser_hash_verified','backup_verified','production_preserved','no_services_restarted')):raise ValueError('success_evidence')
        v=report['resources']
        if type(v)is not dict or set(v)!={'available_bytes','swap_used_bytes','disk_available_bytes'} or any(type(n)is not int or not 0<=n<2**63 for n in v.values()) or v['available_bytes']<768*1024**2 or v['disk_available_bytes']<2*1024**3:raise ValueError('resources')
    else:
        if code!=1 or set(report)!={'status','phase','reason','source_may_have_changed','automatic_rollback'} or report['status'] not in ('BLOCKED','PARTIAL') or report['phase'] not in PHASES or report['reason'] not in REASONS or type(report['source_may_have_changed'])is not bool or report['automatic_rollback']is not False:raise ValueError('failure_shape')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('apply','rollback'));p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args()
    summary={'exit_status':None,'failure_category':'LOCAL_INTEGRITY','report':None};capture=None
    try:
        payload,wrapper,base=verify(a.manifest_sha256,a.action)
        if a.local_check:print('{"local_integrity":"PASS","remote_attempts":0}');return 0
        command=wrapper['ssh_argv'](wrapper['profile']());command[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 120s /usr/bin/python3 -I -S -B -'
        capture=Path(tempfile.mkdtemp(prefix='parser-hotfix-'+a.action+'-',dir=wrapper['PRIVATE']/'preflight'));capture.chmod(0o700)
        result=base['bounded_run'](command,input=payload,timeout=180,limit=131072,grace=5)
        summary={'exit_status':result['returncode'],'failure_category':result['failure'],'report':None}
        for label in ('stdout','stderr'):
            with os.fdopen(os.open(capture/(label+'.private'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:f.write(result[label])
        if result['failure']is None:
            try:summary['report']=validate(json.loads(result['stdout']),a.action,result['returncode'])
            except Exception:summary['failure_category']='INVALID_REPORT'
    except Exception:summary['failure_category']='LOCAL_OR_CAPTURE_FAILURE'
    if capture is not None:
        try:
            with os.fdopen(os.open(capture/'sanitized.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as f:json.dump(summary,f,indent=2)
        except Exception:summary['failure_category']='CAPTURE_FAILURE'
    print(json.dumps(summary,sort_keys=True));return 0 if summary['exit_status']==0 and summary['report'] and summary['failure_category']is None else 1
if __name__=='__main__':raise SystemExit(main())
