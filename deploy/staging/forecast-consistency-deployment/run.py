"""LOCAL package verification by default only with --local-check.
apply/rollback are separate future authorizations; no commands executed on import.
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
PREF='deploy/staging/forecast-consistency-release/'
JOB='deploy/staging/forecast-consistency-deployment/deploy.py'
BASE=PREF+'preflight_readonly.py'
WRAPPER=PREF+'run_preflight.py'
RB=PREF+'rollback_state.py'
RELEASE_SHA='9dc8ce31f1b294c43239824ffa544a76f4fdf6ba334ea8fd72b9431365ed5c19'
ARTIFACTS={JOB,'deploy/staging/forecast-consistency-deployment/run.py','deploy/staging/forecast-consistency-deployment/REVIEW.md',BASE,WRAPPER,RB,'scripts/smoke_staging.py','tests/test_forecast_consistency_deployment.py'}


def read(path,limit=2_000_000):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('regular_file')
        raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('read_bound')
    return raw


def namespace(raw,name,file=None):
    value={'__name__':name}
    if file:value['__file__']=str(file)
    exec(compile(raw,'<verified-'+name+'>','exec'),value)
    return value


def release_files():
    root=ROOT/'data/backups/private-staging-releases/phase-forecast-consistency-20261101-v1/release'
    raw=read(root/'release-manifest.json')
    if hashlib.sha256(raw).hexdigest()!=RELEASE_SHA:raise ValueError('release_manifest')
    manifest=json.loads(raw);result={}
    for name,item in manifest['files'].items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts:raise ValueError('release_path')
        data=read(root/p)
        if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('release_hash')
        if p.parts[0] not in ('api','static'):continue # proposals NEVER installed
        result[name]={**item,'base64':base64.b64encode(data).decode()}
    if len([x for x in result if x.startswith('api/')])!=26 or len([x for x in result if x.startswith('static/')])!=37:raise ValueError('release_scope')
    if 'api/src/api/forecast_source.py' not in result:raise ValueError('missing_selector')
    return result


def assemble(blobs,files,action):
    if action not in ('apply','rollback'):raise ValueError('action')
    text=''
    for label,key in [('BASE',BASE),('ROLLBACK',RB)]:
        text+=label+"={'__name__':'verified_dependency'}\nexec(compile("+repr(blobs[key])+",'<verified-dependency>','exec'),"+label+")\n"
    text+='CONFIG='+repr({'files':files})+'\nACTION='+repr(action)+'\n'
    text+='exec(compile('+repr(blobs[JOB])+",'<verified-staging-job>','exec'),{'__name__':'__main__','BASE':BASE,'ROLLBACK':ROLLBACK,'CONFIG':CONFIG,'ACTION':ACTION})\n"
    raw=text.encode()
    if len(raw)>2_000_000:raise ValueError('assembled_bound')
    return raw


def verify(expected,action):
    raw=read(HERE/'MANIFEST.json')
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('manifest_hash')
    manifest=json.loads(raw)
    if manifest['schema_version']!=1 or set(manifest['artifacts'])!=ARTIFACTS or manifest['release_manifest_sha256']!=RELEASE_SHA:raise ValueError('manifest_scope')
    blobs={}
    for name,item in manifest['artifacts'].items():
        data=read(ROOT/name)
        if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('artifact_hash')
        blobs[name]=data
    files=release_files();payload=assemble(blobs,files,action)
    if hashlib.sha256(payload).hexdigest()!=manifest['assembled_sha256'][action]:raise ValueError('assembled_hash')
    wrapper=namespace(blobs[WRAPPER],'wrapper',ROOT/WRAPPER);wrapper['profile']()
    return payload,wrapper,namespace(blobs[BASE],'base')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('apply','rollback'));parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--local-check',action='store_true');a=parser.parse_args()
    capture=None;summary={'exit_status':None,'failure_category':'LOCAL_VERIFICATION_FAILURE','report':None}
    try:
        payload,wrapper,base=verify(a.manifest_sha256,a.action)
        if a.local_check:print('{"local_integrity":"PASS","remote_attempts":0}');return 0
        command=wrapper['ssh_argv'](wrapper['profile']())
        seconds=300 if a.action=='apply' else 180
        command[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s '+str(seconds)+'s /usr/bin/python3 -I -S -B -'
        capture=Path(tempfile.mkdtemp(prefix='staging-'+a.action+'-',dir=wrapper['PRIVATE']/'preflight'));capture.chmod(0o700)
        result=base['bounded_run'](command,input=payload,timeout=seconds+60,limit=131072,grace=5)
        summary={'exit_status':result['returncode'],'failure_category':result['failure'],'report':None}
        for label in ('stdout','stderr'):
            with os.fdopen(os.open(capture/(label+'.private'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as stream:stream.write(result[label])
        if not result['failure']:
            try:
                report=json.loads(result['stdout'])
                # Fixed output: never echo unvalidated exception text or paths.
                need_keys={'status','phase','production_preserved','missing_publication_verified','resources_before','reason','automatic_rollback'}
                if not isinstance(report,dict) or not set(report)<=need_keys:raise ValueError('report')
                if report.get('status') not in ('DEPLOYED','ROLLED_BACK','PARTIAL','BLOCKED'):raise ValueError('report_status')
                for key in ('phase','reason'):
                    if key in report and (type(report[key])is not str or not report[key].replace('_','').isupper() or len(report[key])>80):raise ValueError('report_label')
                for key in ('production_preserved','missing_publication_verified','automatic_rollback'):
                    if key in report and type(report[key])is not bool:raise ValueError('report_boolean')
                if 'resources_before' in report and (set(report['resources_before'])!={'available_bytes','swap_used_bytes'} or any(type(x)is not int or x<0 for x in report['resources_before'].values())):raise ValueError('report_resources')
                summary['report']=report
            except Exception:summary['failure_category']=wrapper['failure_category'](result['returncode'],result['stderr']) if result['returncode'] else 'UNEXPECTED_OUTPUT'
    except Exception:
        if capture is not None:summary['failure_category']='CAPTURE_OR_EXECUTION_FAILURE'
    if capture is not None:
        try:
            with os.fdopen(os.open(capture/'sanitized.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as stream:json.dump(summary,stream,indent=2)
        except Exception:summary['failure_category']='REPORT_WRITE_FAILURE'
    try:print(json.dumps(summary,sort_keys=True))
    except OSError:return 1
    return 0 if summary['exit_status']==0 and summary['failure_category'] is None and summary['report'] and summary['report']['status'] in ('DEPLOYED','ROLLED_BACK') else 1

if __name__=='__main__':raise SystemExit(main())
