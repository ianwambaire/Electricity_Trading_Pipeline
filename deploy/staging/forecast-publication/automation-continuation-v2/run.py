"""Hash-bound apply/rollback; --local-check never connects. No implicit rollback."""
import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import tempfile
ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent
PREFIX='deploy/staging/forecast-publication/'
JOB=PREFIX+'automation-continuation-v2/job.py'
BASE='deploy/staging/forecast-consistency-release/preflight_readonly.py'
WRAPPER='deploy/staging/forecast-consistency-release/run_preflight.py'
GUARD='deploy/staging/forecast-consistency-deployment/deploy.py'
SOURCES={'tools/automatic.py':PREFIX+'automatic.py','tools/publish.py':PREFIX+'publish.py','tools/prepare.py':PREFIX+'prepare.py','tools/shared/__init__.py':'src/shared/__init__.py','tools/shared/forecast_publication.py':'src/shared/forecast_publication.py','pipeline':'src/scheduled_pipeline.py','delivery':'src/shared/forecast_delivery.py','launcher':PREFIX+'powerflow-publish-next24','sudoers':PREFIX+'automation-continuation-v2/sudoers.rule'}
PRIOR_MANIFEST='deploy/staging/forecast-publication/automation-continuation/MANIFEST.json'
PRIOR_SHA='62b03da0c79211714777aa0d6f20bf97d12b2b54b6e4ca069fb4ed82ee1778a4'
PRIOR_TRANSACTION='bc5480db704d411cb7f4288b9357ff3a'
ORIGINAL_MANIFEST='deploy/staging/forecast-publication/automation-deployment/MANIFEST.json'
ORIGINAL_SHA='48a17404aa82c2fc16ab961311a7007224e1ee7016ecbc6ca5de04bed8aed389'
ORIGINAL_TRANSACTION='73080d9ca8fd4c3f9f143fd4ae84a123'
ARTIFACTS=set(SOURCES.values())|{'tests/test_automatic_publication_deployment.py',JOB,BASE,WRAPPER,GUARD,PREFIX+'AUTOMATION-SOURCE-MANIFEST.json',PREFIX+'AUTOMATION-REVIEW.md',PREFIX+'README.md',PREFIX+'automation-continuation-v2/run.py',PREFIX+'automation-continuation-v2/REVIEW.md',PREFIX+'automation-continuation-v2/build.py','tests/test_automation_preflight_paths.py','tests/test_automatic_publication.py'}
def read(path,limit=1000000):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise ValueError('file_type')
        raw=f.read(limit+1)
    if len(raw)>limit:raise ValueError('file_bound')
    return raw
def sha(raw):return hashlib.sha256(raw).hexdigest()
def namespace(raw,name,path=None,extra=None):
    ns={'__name__':name}
    if path:ns['__file__']=str(path)
    if extra:ns.update(extra)
    exec(compile(raw,'<verified-'+name+'>','exec'),ns);return ns
def assemble(blobs,config,action):
    if action not in {'preflight','apply','rollback'}:raise ValueError('action')
    config=json.loads(json.dumps(config,sort_keys=True))
    text="BASE={'__name__':'verified_base'}\nexec(compile("+repr(blobs[BASE])+",'<verified-base>','exec'),BASE)\n"
    text+="GUARD={'__name__':'verified_guard','BASE':BASE}\nexec(compile("+repr(blobs[GUARD])+",'<verified-guard>','exec'),GUARD)\n"
    text+='CONFIG='+repr(config)+'\nACTION='+repr(action)+'\n'
    text+='exec(compile('+repr(blobs[JOB])+",'<verified-job>','exec'),{'__name__':'__main__','CONFIG':CONFIG,'ACTION':ACTION,'BASE':BASE,'GUARD':GUARD})\n"
    return text.encode()
def verify_original():
    raw=read(ROOT/ORIGINAL_MANIFEST)
    if sha(raw)!=ORIGINAL_SHA:raise ValueError('original_manifest_hash')
    m=json.loads(raw)
    if m['config']['transaction']!=ORIGINAL_TRANSACTION:raise ValueError('original_transaction')
    for name,item in m['artifacts'].items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts:raise ValueError('original_path')
        data=read(ROOT/p)
        if len(data)!=item['bytes'] or sha(data)!=item['sha256']:raise ValueError('original_source_hash')
    return m['config']

def verify(expected,action):
    raw=read(HERE/'MANIFEST.json')
    if sha(raw)!=expected:raise ValueError('manifest_hash')
    m=json.loads(raw)
    if set(m)!={'version','artifacts','config','payload_sha256'} or m['version']!=1 or set(m['artifacts'])!=ARTIFACTS:raise ValueError('manifest_scope')
    blobs={}
    for name,item in m['artifacts'].items():
        data=read(ROOT/name)
        if len(data)!=item['bytes'] or sha(data)!=item['sha256']:raise ValueError('artifact_hash')
        blobs[name]=data
    config=m['config'];old=verify_original()
    prior_raw=read(ROOT/PRIOR_MANIFEST)
    if sha(prior_raw)!=PRIOR_SHA or config.get('prior_manifest_sha256')!=PRIOR_SHA or config.get('prior_transaction')!=PRIOR_TRANSACTION:raise ValueError('prior_continuation_binding')
    prior=json.loads(prior_raw)
    for name,item in prior['artifacts'].items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts:raise ValueError('prior_path')
        data=read(ROOT/p)
        if len(data)!=item['bytes'] or sha(data)!=item['sha256']:raise ValueError('prior_source_hash')
    if config.get('original_manifest_sha256')!=ORIGINAL_SHA or config.get('original_transaction')!=ORIGINAL_TRANSACTION or (config['transaction'] in {ORIGINAL_TRANSACTION,PRIOR_TRANSACTION} or not re.fullmatch('[0-9a-f]{32}',config['transaction'])):raise ValueError('continuation_binding')
    if config['original_tools']!=old['original_tools']:raise ValueError('original_tools_binding')
    if config['installed_tools']!=old['installed_tools'] or config['worker_base_sha256']!=old['worker_base_sha256']:raise ValueError('retained_dependency_binding')
    source=json.loads(blobs[PREFIX+'AUTOMATION-SOURCE-MANIFEST.json'])
    if not set(source['sources'])<=ARTIFACTS or config['installed_tools']!=source['installed_tools']:raise ValueError('source_manifest_scope')
    for name,item in source['sources'].items():
        if sha(blobs[name])!=item['sha256'] or len(blobs[name])!=item['bytes']:raise ValueError('source_manifest_hash')
    for name,value in config['installed_tools'].items():
        if sha(blobs[SOURCES['tools/'+name]])!=value:raise ValueError('tool_dependency_hash')
    if set(config['files'])!=set(SOURCES):raise ValueError('executable_closure')
    for name,path in SOURCES.items():
        item=config['files'][name];raw=base64.b64decode(item['base64'],validate=True)
        if raw!=blobs[path] or sha(raw)!=item['sha256'] or len(raw)!=item['bytes']:raise ValueError('retained_bytes')
    payload=assemble(blobs,config,action)
    if len(payload)>1000000 or sha(payload)!=m['payload_sha256'][action]:raise ValueError('payload_hash')
    wrapper=namespace(blobs[WRAPPER],'wrapper',ROOT/WRAPPER);wrapper['profile']()
    return payload,wrapper,namespace(blobs[BASE],'base'),config['transaction']
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['preflight','apply','rollback']);p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args()
    folder=None;result={'exit_status':None,'failure_category':'LOCAL_VERIFICATION_FAILURE','report':None}
    try:
        payload,w,b,transaction=verify(a.manifest_sha256,a.action)
        if a.local_check:print('{"local_integrity":"PASS","remote_attempts":0}');return 0
        os.umask(0o077);folder=Path(tempfile.mkdtemp(prefix='publication-automation-'+a.action+'-',dir=w['PRIVATE']/'preflight'))
        argv=w['ssh_argv'](w['profile']());bound=60 if a.action=='preflight' else 120 if a.action=='apply' else 90
        argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s '+str(bound)+'s /usr/bin/python3 -I -S -B -'
        r=b['bounded_run'](argv,input=payload,timeout=bound+60,limit=131072,grace=5)
        for key in ['stdout','stderr']:
            with (folder/(key+'.private')).open('xb') as f:f.write(r[key])
        result={'exit_status':r['returncode'],'failure_category':r['failure'],'report':None}
        if not r['failure']:
            try:
                report=json.loads(r['stdout'])
                allowed={'status','transaction','phase','changed','resources','automatic_publication','publication_executed','service_restart','preservation','retained_private_tools','cause','shared_directory','retained_tools','error_category','operation','path_id','errno','check_scope'}
                if type(report)is not dict or not set(report)<=allowed or report.get('publication_executed') is not False:raise ValueError()
                if report.get('status') not in ['INITIAL_PREFLIGHT_PASS','APPLIED','ROLLED_BACK','PARTIAL','BLOCKED']:raise ValueError()
                if report.get('transaction')!=transaction or type(report.get('changed'))is not bool:raise ValueError()
                success=report['status']==('INITIAL_PREFLIGHT_PASS' if a.action=='preflight' else 'APPLIED' if a.action=='apply' else 'ROLLED_BACK')
                if 'check_scope' in report and report['check_scope']!='INITIAL_HOST_AND_ORIGINAL_TOOLS':raise ValueError()
                if a.action=='preflight' and (report.get('changed') is not False or (success and report.get('check_scope')!='INITIAL_HOST_AND_ORIGINAL_TOOLS')):raise ValueError()
                if (r['returncode']==0)!=success:raise ValueError()
                if 'resources' in report and (type(report['resources'])is not dict or set(report['resources'])!={'available_bytes','swap_used_bytes'} or any(type(v)is not int or v<0 for v in report['resources'].values())):raise ValueError()
                if report.get('automatic_publication','ENABLED_FOR_NATURAL_RUNS')!='ENABLED_FOR_NATURAL_RUNS' or report.get('preservation','PASS')!='PASS':raise ValueError()
                if report.get('service_restart',False) is not False or report.get('retained_private_tools',True) is not True:raise ValueError()
                if report.get('phase') not in ['PREFLIGHT','BACKUP','INSTALL','ACTIVATION','DISABLE','RESTORE','COMPLETE']:raise ValueError()
                if 'shared_directory' in report and report['shared_directory'] not in {'CREATED','VERIFIED_PREEXISTING','PRESERVED_PREEXISTING','NOT_CREATED','RETAINED_NONEMPTY','REMOVED_EMPTY_CREATED'}:raise ValueError()
                if report.get('retained_tools','VERIFIED_REUSED')!='VERIFIED_REUSED':raise ValueError()
                if 'error_category' in report and report['error_category'] not in {'GUARD_FAILED','MISSING_PATH','PERMISSION_DENIED','PATH_CONFLICT','OS_ERROR','VALIDATION_ERROR'}:raise ValueError()
                for key in ['operation','path_id']:
                    if key in report and (type(report[key])is not str or not re.fullmatch('[A-Z0-9_]{1,80}',report[key])):raise ValueError()
                if 'errno' in report and report['errno'] is not None and (type(report['errno'])is not int or not 0<=report['errno']<=65535):raise ValueError()
                if 'cause' in report and (not isinstance(report['cause'],str) or not report['cause'].replace('_','').isalnum() or len(report['cause'])>80):raise ValueError()
                result['report']=report
            except Exception:result['failure_category']=w['failure_category'](r['returncode'],r['stderr']) if r['returncode'] else 'UNEXPECTED_OUTPUT'
    except Exception:
        if folder:result['failure_category']='EXECUTION_OR_CAPTURE_FAILURE'
    if folder:(folder/'assessment.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,sort_keys=True));return 0 if result['exit_status']==0 and not result['failure_category'] and result['report'] else 1
if __name__=='__main__':raise SystemExit(main())
