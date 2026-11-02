"""LOCAL package verification by default only with --local-check.
apply/rollback are separate future authorizations; no commands executed on import.
"""
import argparse
import base64
import hashlib
import json
import os
import re
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


def assemble(blobs,files,action,transaction_id):
    if action not in ('reactivate','rollback','diagnose-backend') or type(transaction_id)is not str or re.fullmatch('[0-9a-f]{32}',transaction_id) is None:raise ValueError('action_or_transaction')
    text=''
    for label,key in [('BASE',BASE),('ROLLBACK',RB)]:
        text+=label+"={'__name__':'verified_dependency'}\nexec(compile("+repr(blobs[key])+",'<verified-dependency>','exec'),"+label+")\n"
    text+='CONFIG='+repr({'files':files,'transaction_id':transaction_id})+'\nACTION='+repr(action)+'\n'
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
    files=release_files();payload=assemble(blobs,files,action,manifest['transaction_id'])
    if hashlib.sha256(payload).hexdigest()!=manifest['assembled_sha256'][action]:raise ValueError('assembled_hash')
    wrapper=namespace(blobs[WRAPPER],'wrapper',ROOT/WRAPPER);wrapper['profile']()
    return payload,wrapper,namespace(blobs[BASE],'base')


FAILURE_REASONS=set(['ACTION_SCOPE', 'ADDRESS_FAMILIES', 'ADMIN_AUTH_BOUNDARY', 'API_BODY_BOUND', 'API_PROBE_SCOPE', 'ASSET_COLLISION', 'ATOMIC_FILE_VERIFY', 'BACKEND_BASELINE_DRIFT', 'BACKUP_ENV_VERIFY', 'BODY_MISMATCH', 'BPF_ATTACHMENTS', 'CACHE_MISMATCH', 'CANDIDATE_IDENTITY', 'CANDIDATE_NOT_RUNNING', 'CANDIDATE_RESTART_FAILED', 'CANDIDATE_SWAP_ACTIVITY', 'CGROUP_LAYOUT', 'CGROUP_LIMITS', 'COMMAND_SCOPE', 'CONTROL_PERMISSIONS', 'DEPENDENCY_METADATA', 'DESTINATION_CONFLICT', 'DISK_GATE', 'ENTRY_ASSETS', 'ENV_BASELINE_DRIFT', 'ENV_DRIFT', 'ENV_KEY_ALREADY_PRESENT', 'ENV_PERMISSIONS', 'HISTORICAL_API', 'HISTORICAL_SEPARATION', 'HTTPS_ASSET_HASH', 'HTTPS_INDEX_HASH', 'HTTP_ACCEPTANCE', 'IMDS_DENY', 'INPUT_COUNTS', 'INPUT_HASH', 'INPUT_PATH', 'INPUT_SCOPE', 'INSPECTION_OR_INSTALLATION_FAILED', 'INSTALLED_HASH', 'INSTALLED_TARGET_DRIFT', 'LEGACY_ASSET_MISMATCH', 'LEGACY_BACKUP_MISMATCH', 'LEGACY_CONTROL_PERMISSIONS', 'LEGACY_FILE_PERMISSIONS', 'LEGACY_RECORD_DRIFT', 'LEGACY_RECORD_MISMATCH', 'LEGACY_STATIC_MISMATCH', 'LISTENER_OWNERSHIP', 'OLD_ASSET_DRIFT', 'PIPELINE_OR_WINDOW_GATE', 'POINTER_DRIFT', 'POINTER_LAYOUT', 'POINTER_REQUIRED', 'POINTER_VERIFY', 'PROCESS_SECURITY', 'PRODUCTION_DRIFT', 'PRODUCTION_SERVICE_STATE', 'RAM_GATE', 'RESTORED_POINTER_MISMATCH', 'RETAINED_DIRECTORY_PERMISSIONS', 'RETAINED_FILE_HASH', 'RETAINED_FILE_PERMISSIONS', 'RETAINED_MISSING_FILE_OR_DIRECTORY', 'RETAINED_PATH_SCOPE', 'RETAINED_SCAN_BOUND', 'RETAINED_SYMLINK', 'RETAINED_UNEXPECTED_DIRECTORY', 'RETAINED_UNEXPECTED_FILE', 'RETAINED_VENV', 'ROLLBACK_ALREADY_COMPLETE', 'ROLLBACK_BACKEND_HASH', 'ROLLBACK_ENV_DRIFT', 'ROLLBACK_ENV_HASH', 'ROLLBACK_HTTPS', 'ROLLBACK_POINTER_DRIFT', 'ROLLBACK_POSTCHECK', 'ROLLBACK_RECORD', 'ROLLBACK_STATE', 'ROLLBACK_STATIC_HASH', 'ROLLBACK_TARGET_SCOPE', 'ROOT_REQUIRED', 'RUNNING_CODE_TARGET', 'SANDBOX_PROPERTIES', 'SELECTOR_MISSING', 'SINGLE_WORKER', 'STARTUP_READINESS', 'STATIC_INDEX_MISSING', 'STATIC_INVENTORY_BOUND', 'STATIC_SIZE_BOUND', 'STATUS_MISMATCH', 'TRANSACTION_BASELINE', 'TRANSACTION_COLLISION', 'TRANSACTION_HASH', 'TRANSACTION_ID', 'TRANSACTION_INVENTORY', 'TRANSACTION_ORIGINAL_STATE', 'TRANSACTION_PARENT_PERMISSIONS', 'TRANSACTION_RECORD_MISMATCH', 'TRANSACTION_RECORD_SCHEMA', 'TRANSACTION_TARGET_MISMATCH', 'UNEXPECTED_PUBLICATION_ROOT', 'UNSAFE_PATH', 'VENV_TARGET'])
BACKEND_STEPS={'RECORD_SAVE','ENV_UPDATE','POINTER_SWITCH','RESTART','READINESS','RUNTIME',
    'FORECAST_CONTRACT','PRESERVATION','CAPACITY','RUNTIME_RECHECK','PRESERVATION_RECHECK','RETAINED_RECHECK'}
ERROR_CAUSES={'PERMISSION_DENIED','MISSING_FILE','TIMEOUT','OS_ERROR','VALUE_ERROR','MISSING_KEY','UNEXPECTED_EXCEPTION'}
FAILURE_REASONS|={'BACKEND_'+step+'_'+cause for step in BACKEND_STEPS for cause in ERROR_CAUSES}
DIAGNOSTIC_STEPS={'SERVICE_METADATA','TRANSACTION','POINTERS','ENVIRONMENT','PERMISSIONS'}
DIAGNOSTIC_BOOLS={'candidate_active','candidate_running','unit_identity_match','transaction_record_valid',
    'transaction_rolled_back','backup_hash_valid','backend_original','backend_release','static_original',
    'env_original','env_installed','env_safe','parent_permissions_safe'}
DIAGNOSTIC_INTS={'exec_main_code','exec_main_status','status_errno','restart_count'}
UNIT_RESULTS={'success','exit-code','signal','core-dump','timeout','watchdog','start-limit-hit','resources','protocol','oom-kill','OTHER'}


def validate_diagnostic(report,code):
    fields={'status','phase','facts','cause_codes','historical_failure_proven'}
    if code!=0 or type(report)is not dict or set(report)!=fields:raise ValueError('diagnostic_schema')
    if report['phase']!='DIAGNOSTIC' or report['historical_failure_proven'] is not False:raise ValueError('diagnostic_evidence')
    facts=report['facts'];causes=report['cause_codes']
    if type(facts)is not dict or set(facts)!=DIAGNOSTIC_BOOLS|DIAGNOSTIC_INTS|{'last_unit_result'}:raise ValueError('diagnostic_fields')
    for key,value in facts.items():
        if value is None:continue
        if key in DIAGNOSTIC_BOOLS and type(value)is not bool:raise ValueError('diagnostic_boolean')
        if key in DIAGNOSTIC_INTS and (type(value)is not int or not 0<=value<2**63):raise ValueError('diagnostic_number')
        if key=='last_unit_result' and (type(value)is not str or value not in UNIT_RESULTS):raise ValueError('diagnostic_result')
    allowed={step+'_'+cause for step in DIAGNOSTIC_STEPS for cause in ERROR_CAUSES}
    if type(causes)is not list or len(causes)>5 or any(type(x)is not str or x not in allowed for x in causes) or len(set(causes))!=len(causes):raise ValueError('diagnostic_causes')
    expected='UNVERIFIED' if causes else 'DIAGNOSTIC_COMPLETE'
    if report['status']!=expected or (not causes and any(v is None for v in facts.values())):raise ValueError('diagnostic_status')
    return report


PHASES={'PREFLIGHT','INSTALL','BACKEND_ACTIVATION','STATIC_ACTIVATION','COMPLETE','ROLLBACK','ROLLED_BACK'}


def validate_report(report,action,code):
    if action=='diagnose-backend':
        if code==0:return validate_diagnostic(report,code)
        if type(report)is not dict or report.get('phase')!='PREFLIGHT' or report.get('status')!='BLOCKED':raise ValueError('diagnostic_failure')
        return validate_report(report,'rollback',code)
    action='apply' if action=='reactivate' else action
    if action not in ('apply','rollback') or type(code)is not int or type(report)is not dict:raise ValueError('report_schema')
    success='DEPLOYED' if action=='apply' else 'ROLLED_BACK'
    if code==0:
        fields={'status','phase','production_preserved'}
        if action=='apply':fields|={'missing_publication_verified','resources_before'}
        if set(report)!=fields or report['status']!=success or report['phase']!=('COMPLETE' if action=='apply' else 'ROLLED_BACK') or report['production_preserved'] is not True:raise ValueError('success_evidence')
        if action=='apply':
            if report['missing_publication_verified'] is not True:raise ValueError('missing_publication_evidence')
            values=report['resources_before']
            if type(values)is not dict or set(values)!={'available_bytes','swap_used_bytes'} or any(type(x)is not int or not 0<=x<2**63 for x in values.values()) or values['available_bytes']<768*1024**2:raise ValueError('resource_evidence')
    else:
        if code!=1 or set(report)!={'status','phase','reason','automatic_rollback'} or report['status'] not in ('BLOCKED','PARTIAL') or report['phase'] not in PHASES or report['reason'] not in FAILURE_REASONS or report['automatic_rollback'] is not False:raise ValueError('failure_evidence')
        allowed={'PREFLIGHT','ROLLBACK'} if action=='rollback' else PHASES-{'ROLLBACK','ROLLED_BACK'}
        if report['phase'] not in allowed:raise ValueError('action_phase')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('reactivate','rollback','diagnose-backend'));parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--local-check',action='store_true');a=parser.parse_args()
    capture=None;summary={'exit_status':None,'failure_category':'LOCAL_VERIFICATION_FAILURE','report':None}
    try:
        payload,wrapper,base=verify(a.manifest_sha256,a.action)
        if a.local_check:print('{"local_integrity":"PASS","remote_attempts":0}');return 0
        command=wrapper['ssh_argv'](wrapper['profile']())
        seconds=300 if a.action=='reactivate' else 30 if a.action=='diagnose-backend' else 180
        command[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s '+str(seconds)+'s /usr/bin/python3 -I -S -B -'
        capture=Path(tempfile.mkdtemp(prefix='staging-'+a.action+'-',dir=wrapper['PRIVATE']/'preflight'));capture.chmod(0o700)
        result=base['bounded_run'](command,input=payload,timeout=seconds+60,limit=131072,grace=5)
        summary={'exit_status':result['returncode'],'failure_category':result['failure'],'report':None}
        for label in ('stdout','stderr'):
            with os.fdopen(os.open(capture/(label+'.private'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as stream:stream.write(result[label])
        if not result['failure']:
            try:
                report=validate_report(json.loads(result['stdout']),a.action,result['returncode'])
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
    return 0 if summary['exit_status']==0 and summary['failure_category'] is None and summary['report'] and summary['report']['status'] in ('DEPLOYED','ROLLED_BACK','DIAGNOSTIC_COMPLETE') else 1

if __name__=='__main__':raise SystemExit(main())
