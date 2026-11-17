"""Standalone read-only diagnostic. Original apply/rollback package is never edited.
No arbitrary command/path/host. Executable bytes retained through transmission.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent
PREFIX='deploy/staging/forecast-publication/automation-install-diagnostic/'
ORIGINAL='deploy/staging/forecast-publication/automation-deployment/MANIFEST.json'
ORIGINAL_SHA='48a17404aa82c2fc16ab961311a7007224e1ee7016ecbc6ca5de04bed8aed389'
TRANSACTION='73080d9ca8fd4c3f9f143fd4ae84a123'
CORE='deploy/staging/forecast-consistency-release/preflight_readonly.py'
WRAPPER='deploy/staging/forecast-consistency-release/run_preflight.py'
ARTIFACTS={PREFIX+'inspect.py',PREFIX+'run.py',PREFIX+'build.py',PREFIX+'REVIEW.md','tests/test_automation_install_diagnostic.py'}
def read(path,limit=1000000):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise ValueError('file_type')
        raw=f.read(limit+1)
    if len(raw)>limit:raise ValueError('file_bound')
    return raw
def sha(raw):return hashlib.sha256(raw).hexdigest()
def original():
    raw=read(ROOT/ORIGINAL)
    if sha(raw)!=ORIGINAL_SHA:raise ValueError('original_manifest_hash')
    m=json.loads(raw)
    if m['config']['transaction']!=TRANSACTION:raise ValueError('original_transaction')
    blobs={}
    for name,item in m['artifacts'].items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts:raise ValueError('original_artifact_path')
        data=read(ROOT/p)
        if len(data)!=item['bytes'] or sha(data)!=item['sha256']:raise ValueError('original_artifact_hash')
        blobs[name]=data
    job='deploy/staging/forecast-publication/automation-deployment/job.py'
    tree=ast.parse(blobs[job]);values={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in {'TOOLS','PRODUCTION'}:
            if not isinstance(node.value,ast.Call) or not isinstance(node.value.func,ast.Name) or node.value.func.id!='Path' or len(node.value.args)!=1:raise ValueError('original_path_binding')
            values[node.targets[0].id]=ast.literal_eval(node.value.args[0])
    if values!={'TOOLS':'/opt/powerflow/forecast-publication-automation','PRODUCTION':'/home/ec2-user/Electricity_Trading_Pipeline'}:raise ValueError('original_path_binding')
    expected=dict(m['config']['installed_tools'])
    expected['automation-manifest.json']=sha(json.dumps(m['config']['installed_tools'],sort_keys=True).encode())
    config={'transaction':TRANSACTION,'original_manifest_sha256':ORIGINAL_SHA,'production_parent':values['PRODUCTION']+'/src','tools_root':values['TOOLS'],'expected_files':expected,'pipeline_uid':1000,'pipeline_gid':1000}
    return config,blobs

def assemble(raw,config):return ('CONFIG='+repr(json.loads(json.dumps(config,sort_keys=True)))+'\n').encode()+raw

def namespace(raw,name,path=None):
    ns={'__name__':name}
    if path:ns['__file__']=str(path)
    exec(compile(raw,'<verified-'+name+'>','exec'),ns);return ns

def verify(expected):
    data=read(HERE/'MANIFEST.json')
    if sha(data)!=expected:raise ValueError('diagnostic_manifest_hash')
    m=json.loads(data)
    if set(m)!={'version','original_manifest_sha256','transaction','artifacts','remote_payload_sha256'} or m['version']!=1 or m['original_manifest_sha256']!=ORIGINAL_SHA or m['transaction']!=TRANSACTION or set(m['artifacts'])!=ARTIFACTS:raise ValueError('diagnostic_scope')
    blobs={}
    for name,item in m['artifacts'].items():
        raw=read(ROOT/name)
        if len(raw)!=item['bytes'] or sha(raw)!=item['sha256']:raise ValueError('diagnostic_artifact_hash')
        blobs[name]=raw
    config,old=original();raw=blobs[PREFIX+'inspect.py'];payload=assemble(raw,config)
    if len(payload)>32768 or sha(payload)!=m['remote_payload_sha256']:raise ValueError('payload_hash')
    # Original installer/rollback code is NEVER compiled, imported or transmitted.
    wrapper=namespace(old[WRAPPER],'wrapper',ROOT/WRAPPER);wrapper['profile']()
    base=namespace(old[CORE],'local_supervisor')
    return payload,wrapper,base,config

CAUSES={'PATH_SCOPE','UNSAFE_ANCESTOR','PATH_CHANGED','SYMLINK_REJECTED','FILE_TYPE_OR_BOUND','FILE_CHANGED','FILE_CHANGED_OR_BOUND','TOOLS_NOT_DIRECTORY','INVENTORY_BOUND','UNEXPECTED_ENTRY','TOOLS_SHARED_TYPE','TOOLS_FILE_TYPE','MISSING_ANCESTOR','PERMISSION_DENIED','INSPECTION_FAILED'}
def validate(value,config,code):
    # Validate the ENTIRE tree against bounded allowlists before any output is exposed.
    if len(json.dumps(value).encode())>16384 or type(value)is not dict:raise ValueError('output_bound')
    keys={'schema_version','status','transaction','original_manifest_sha256','observed_utc','remote_mutations','historical_cause','evidence_basis','stage','production_parent','production_shared','interpretation','tools','cause'}
    if not set(value)<=keys or value.get('schema_version')!=1 or value.get('transaction')!=TRANSACTION or value.get('original_manifest_sha256')!=ORIGINAL_SHA or value.get('remote_mutations') is not False or value.get('historical_cause')!='UNVERIFIED' or value.get('evidence_basis')!='CURRENT_POST_ROLLBACK_METADATA':raise ValueError('report_binding')
    if value.get('status') not in {'OBSERVED','FINDINGS','UNVERIFIED'} or code!=(0 if value['status']=='OBSERVED' else 1):raise ValueError('status')
    if value.get('stage') not in {'PRODUCTION_DIRECTORY','RETAINED_TOOLS','COMPLETE'}:raise ValueError('stage')
    if not isinstance(value.get('observed_utc'),str) or not re.fullmatch(r'[0-9T:.+-]{20,40}',value['observed_utc']):raise ValueError('time')
    if 'cause' in value and value['cause'] not in CAUSES:raise ValueError('cause')
    if 'interpretation' in value and value['interpretation'] not in {'MISSING_PARENT_NOT_OBSERVED_NOW','CONSISTENT_WITH_REPRODUCED_MISSING_PARENT','CURRENT_DESTINATION_TYPE_DEFECT','PRODUCTION_PARENT_UNAVAILABLE'}:raise ValueError('interpretation')
    def meta(record):
        if type(record)is not dict or not set(record)<={'exists','type','uid','gid','mode','links','bytes','sha256','hash_status','hash_match','metadata_match','primary_group_posix_read_traverse','effective_pipeline_access','access_identity'}:raise ValueError('metadata_keys')
        if 'exists' not in record or (type(record['exists'])is not bool and record['exists'] is not None):raise ValueError('exists')
        if record['exists'] is True and not {'type','uid','gid','mode','links'}<=set(record):raise ValueError('missing_metadata')
        for k in ['uid','gid','links','bytes']:
            if k in record and (type(record[k])is not int or not 0<=record[k]<=100000000):raise ValueError('metadata_number')
        if 'mode' in record and not re.fullmatch('[0-7]{4}',record['mode']):raise ValueError('mode')
        if 'type' in record and record['type'] not in {'DIRECTORY','REGULAR_FILE','SYMLINK','OTHER'}:raise ValueError('type')
        if 'sha256' in record and not re.fullmatch('[0-9a-f]{64}',record['sha256']):raise ValueError('hash')
        for k in ['hash_match','metadata_match','primary_group_posix_read_traverse']:
            if k in record and type(record[k])is not bool and not (k=='hash_match' and record[k] is None):raise ValueError('metadata_boolean')
        for k in ['effective_pipeline_access','hash_status']:
            if k in record and record[k] not in {'UNVERIFIED','UNVERIFIED_UNSAFE_METADATA'}:raise ValueError('access')
        if 'access_identity' in record and record['access_identity']!={'uid':config['pipeline_uid'],'gid':config['pipeline_gid'],'supplementary_groups':'UNVERIFIED'}:raise ValueError('identity')
    for k in ['production_parent','production_shared']:
        if k in value:meta(value[k])
    if 'tools' in value:
        tools=value['tools']
        if type(tools)is not dict or not set(tools)<={'root','files','state','issues','missing_files'} or tools.get('state') not in {'MATCH','MISSING','MISMATCH','INCOMPLETE'}:raise ValueError('tools')
        meta(tools['root']);files=tools['files']
        if type(files)is not dict or not set(files)<=set(config['expected_files'])|{'shared/'}:raise ValueError('inventory')
        for record in files.values():meta(record)
        if type(tools.get('missing_files',[]))is not list or not set(tools.get('missing_files',[]))<=set(config['expected_files']):raise ValueError('missing_files')
        if type(tools.get('issues'))is not list or not set(tools['issues'])<={'TOOLS_MISSING','TOOLS_DIRECTORY_METADATA','TOOLS_HASH_MISMATCH','TOOLS_FILE_METADATA','INCOMPLETE_INVENTORY'}:raise ValueError('issues')
        if value['status']=='OBSERVED' and tools['state']=='MISMATCH':raise ValueError('unsafe_status')
    if value['status']!='UNVERIFIED':
        if value.get('stage')!='COMPLETE' or not {'production_parent','production_shared','interpretation','tools'}<=set(value):raise ValueError('incomplete_report')
        if tools['state']=='MATCH':
            if set(files)!=set(config['expected_files'])|{'shared/'} or tools['issues']:raise ValueError('incomplete_inventory')
            for name,expected in config['expected_files'].items():
                if files[name].get('sha256')!=expected or files[name].get('hash_match') is not True or files[name].get('metadata_match') is not True:raise ValueError('false_match')
        if tools['state']=='INCOMPLETE' and set(tools.get('missing_files',[]))!=set(config['expected_files'])-set(files):raise ValueError('missing_inventory')
    elif 'cause' not in value:raise ValueError('missing_failure_cause')
    return value

def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['inspect-install-state']);p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args()
    capture=None;out={'exit_status':None,'failure_category':'LOCAL_VERIFICATION_FAILURE','report':None}
    try:
        payload,w,b,config=verify(a.manifest_sha256)
        if a.local_check:print('{"local_integrity":"PASS","remote_attempts":0}');return 0
        os.umask(0o077);capture=Path(tempfile.mkdtemp(prefix='automation-install-state-',dir=w['PRIVATE']/'preflight'))
        argv=w['ssh_argv'](w['profile']());argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 30s /usr/bin/python3 -I -S -B -'
        r=b['bounded_run'](argv,input=payload,timeout=90,limit=32768,grace=5)
        for name in ['stdout','stderr']:
            with (capture/(name+'.private')).open('xb') as stream:stream.write(r[name])
        out={'exit_status':r['returncode'],'failure_category':r['failure'],'report':None}
        if r['failure'] is None:
            try:out['report']=validate(json.loads(r['stdout']),config,r['returncode'])
            except Exception:out['failure_category']=w['failure_category'](r['returncode'],r['stderr']) if r['returncode'] else 'UNEXPECTED_OUTPUT'
    except Exception:
        if capture is not None:out['failure_category']='EXECUTION_OR_CAPTURE_FAILURE'
    if capture is not None:(capture/'assessment.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps(out,sort_keys=True));return 0 if out['exit_status']==0 and out['report'] is not None and out['failure_category'] is None else 1
if __name__=='__main__':raise SystemExit(main())
