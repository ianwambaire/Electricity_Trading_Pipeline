"""Single read-only verification; no inference, publication, file writes or retries."""
import ast
import base64
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import sys
import types
import uuid

BINDINGS = __BINDINGS__
# Load only previously reviewed read-only helper functions, never deployment main.
exec(compile(base64.b64decode(BINDINGS['helpers']), '<read_only_helpers>', 'exec'), globals())
RUN = '01a19159-c938-70aa-ab70-bdbbc90dc833'
EXPECTED = dt.datetime(2026,10,31,12,45,tzinfo=dt.timezone.utc)
RECEIPTS = ROOT/'data/reports/next24h_inference'
BACKUP_META = Path('/home/ec2-user/powerflow-inference-evidence-backup-20261031-v1/deployment.json')
OUT = {'stage':'flow','read_only':True,'retry':False,'receipt':'NOT_INSPECTED',
       'publication_validator':'NOT_RUN','artifact_created':False}


def stamp(value):
    result=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    require(result.tzinfo is not None,'timestamp_timezone')
    return result.astimezone(dt.timezone.utc)


def state(run):
    return (run.get('state') or {}).get('type')


def safe_run(run):
    return {k:run.get(k) for k in ['id','deployment_id','expected_start_time','start_time','end_time']} | {
        'state':state(run),'state_name':(run.get('state') or {}).get('name')}


def private_directory(path):
    info=path.lstat()
    require(stat.S_ISDIR(info.st_mode) and not path.is_symlink() and info.st_uid==1000
            and info.st_gid==1000 and stat.S_IMODE(info.st_mode)==0o700,'receipt_directory_permissions')
    return {'uid':1000,'gid':1000,'mode':'0700','symlink':False}


def private_file(path):
    info=path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid==1000 and info.st_gid==1000
            and stat.S_IMODE(info.st_mode)==0o600 and info.st_size<=100000,'receipt_file_permissions_or_size')
    raw=read(path)
    require(len(raw)==info.st_size,'receipt_changed_during_read')
    return raw


def validator_modules():
    contract_raw=base64.b64decode(BINDINGS['contract'])
    require(digest(contract_raw)==BINDINGS['contract_sha256'],'validator_code_hash')
    package=types.ModuleType('shared');package.__path__=[];sys.modules['shared']=package
    contract=types.ModuleType('shared.forecast_publication');sys.modules[contract.__name__]=contract
    exec(compile(contract_raw,'<hash_verified_publication_validator>','exec'),contract.__dict__)
    builder=types.ModuleType('readonly_builder')
    # This extraction contains imports + build only; CLI/main writing code is absent.
    exec(compile(base64.b64decode(BINDINGS['builder']),'<readonly_bundle_validation>','exec'),builder.__dict__)
    return contract,builder


def main():
    flow=api('/flow_runs/'+RUN)
    require(flow.get('id')==RUN and flow.get('deployment_id')==DEP
            and stamp(flow['expected_start_time'])==EXPECTED,'exact_scheduled_run_identity')
    OUT['flow']=safe_run(flow)
    if state(flow)!='COMPLETED':
        OUT['stage']='stopped_run_not_completed';return
    OUT['stage']='tasks'
    tasks=api('/task_runs/filter',{'task_runs':{'flow_run_id':{'any_':[RUN]}},'sort':'EXPECTED_START_TIME_ASC','limit':100})
    require(len(tasks)<100,'task_bound')
    labels={'ingestion':'Fetch ENTSO-E electricity data','weather_ingestion':'Fetch Open-Meteo weather data',
        'silver_transformation':'Build silver dataset','gold_transformation':'Build gold dataset',
        'silver_validation':'Validate silver dataset','gold_validation':'Validate gold dataset',
        'model_verification':'Verify next24h production release','next24_forecasting':'Generate next24h production forecast'}
    recognized={label:[t for t in tasks if str(t.get('name','')).startswith(name)] for label,name in labels.items()}
    OUT['task_results']={label:[{'id':t['id'],'state':state(t),'state_name':(t.get('state') or {}).get('name'),
        'start_time':t.get('start_time'),'end_time':t.get('end_time')} for t in group] or [{'state':'NOT_RUN'}]
        for label,group in recognized.items()}
    OUT['failed_task_count']=sum(state(t) in ['FAILED','CRASHED','CANCELLED'] for t in tasks)
    require(len(recognized['next24_forecasting'])==1,'forecast_task_identity_ambiguous')
    task=recognized['next24_forecasting'][0]
    require(state(task)=='COMPLETED','forecast_task_not_completed')
    start,end=stamp(task['start_time']),stamp(task['end_time'])
    require(stamp(flow['start_time'])<=start<=end<=stamp(flow['end_time']),'task_flow_interval')
    OUT['stage']='preservation_baselines'
    before_services=identities();before_config=baselines()
    deployed=json.loads(read(BACKUP_META))
    OUT['services_match_deployment_baseline']=before_services==deployed['services']
    OUT['routing_certificates_match_deployment_baseline']=before_config==deployed['configuration']
    OUT['source_hashes_pass']=all(digest(read(ROOT/name))==sha for name,sha in BINDINGS['source_hashes'].items())
    require(OUT['source_hashes_pass'],'capture_source_hash_drift')
    OUT['stage']='receipts';OUT['receipt_root_permissions']=private_directory(RECEIPTS)
    entries=list(RECEIPTS.iterdir());require(len(entries)<=256,'receipt_directory_bound')
    contract,builder=validator_modules();matches=[];OUT['partial_directory_count']=0
    for directory in entries:
        if directory.name.startswith('.partial-'):
            OUT['partial_directory_count']+=1;continue
        require(str(uuid.UUID(directory.name))==directory.name,'unexpected_receipt_entry')
        private_directory(directory)
        proof_raw=private_file(directory/'evidence.json');proof=contract.decode(proof_raw)
        execution=proof.get('execution',{})
        if start<=stamp(execution['started_at'])<=stamp(execution['issued_at'])<=stamp(execution['completed_at'])<=end:
            matches.append((directory,proof_raw,proof))
    if not matches:
        OUT.update(receipt='MISSING',stage='complete_no_matching_receipt')
    else:
        require(len(matches)==1,'multiple_receipts_in_exact_task_interval')
        directory,proof_raw,proof=matches[0]
        OUT['receipt']='PRESENT';OUT['inference_uuid']=directory.name
        require(proof['execution']['run_id']==directory.name,'receipt_uuid_mismatch')
        expected_names={'forecast.csv','provenance.json','model.json','evidence.json','integrity.json'}
        require({p.name for p in directory.iterdir()}==expected_names,'receipt_file_inventory')
        blobs={name:private_file(directory/name) for name in expected_names}
        require(blobs['evidence.json']==proof_raw,'evidence_changed_during_inspection')
        integrity=contract.decode(blobs['integrity.json'])
        require(set(integrity)=={'version','run_id','sha256'} and type(integrity['version']) is int
                and integrity['version']==1 and integrity['run_id']==directory.name,'integrity_schema')
        require(integrity['sha256']=={name:digest(blobs[name]) for name in expected_names-{'integrity.json'}},'integrity_hashes')
        OUT['integrity_hashes']='PASS';OUT['receipt_file_permissions']='PASS'
        rows=list(csv.DictReader(io.StringIO(blobs['forecast.csv'].decode())))
        require(len(rows)==24,'forecast_row_count')
        public_rows=[{'issue_time':r['forecast_issue_time'],'target_time':r['target_timestamp'],
            'horizon_hours':int(r['horizon_hours']),'predicted_price_eur_mwh':float(r['predicted_price_eur_mwh']),
            'model_release':r['model_release']} for r in rows]
        manifest=contract.decode(blobs['model.json'])
        contract.verify_inference_receipt(proof,blobs['forecast.csv'],blobs['provenance.json'],blobs['model.json'],public_rows,manifest)
        OUT['reciprocal_hash_binding']='PASS';OUT['schema_version']=proof['version']
        OUT['ordered_feature_count']=len(proof['inference']['feature_names'])
        OUT['feature_order_and_values_match']=proof['inference']['feature_names']==list(contract.FEATURES)
        require(digest(read(ROOT/'artifacts/models/releases/next24h/next24h_release_manifest.json'))==proof['inference']['release_manifest_sha256'],'release_manifest_binding')
        OUT['model_identity']=proof['inference']['model']
        OUT['stage']='forecast_history_binding'
        issue=stamp(public_rows[0]['issue_time'])
        history=list(csv.DictReader(io.StringIO(read(ROOT/'data/reports/next24h_forecast_history.csv').decode())))
        matching=[r for r in history if stamp(r['forecast_issue_time'])==issue and r['model_release']==manifest['release_id']]
        matching.sort(key=lambda r:int(r['horizon_hours']))
        require(len(matching)==24,'persisted_history_issue_coverage')
        require(all(int(h['horizon_hours'])==r['horizon_hours'] and stamp(h['target_timestamp'])==stamp(r['target_time'])
            and math.isclose(float(h['predicted_price_eur_mwh']),r['predicted_price_eur_mwh'],rel_tol=0,abs_tol=1e-12)
            for h,r in zip(matching,public_rows)),'persisted_forecast_values_mismatch')
        OUT['same_successful_inference_binding']='PASS'
        OUT['association_method']='unique_receipt_within_exact_completed_forecast_task_interval_and_matching_persisted_history'
        OUT['issue_time']=issue.isoformat();OUT['freshness_cutoff']=(issue+contract.MAX_AGE).isoformat()
        OUT['target_start']=public_rows[0]['target_time'];OUT['target_end']=public_rows[-1]['target_time']
        OUT['prediction_count']=24;OUT['finite_predictions']=all(math.isfinite(r['predicted_price_eur_mwh']) for r in public_rows)
        OUT['stage']='publication_validation'
        # Source metadata/permissions were independently verified above. Give the unchanged
        # builder frozen in-memory snapshots; neither builder nor validator can write files.
        paths=[directory/name for name in ['forecast.csv','provenance.json','model.json','evidence.json']]
        frozen={str(path):blobs[path.name] for path in paths}
        builder.safe_file=lambda path:frozen[str(path)]
        now=dt.datetime.now(dt.timezone.utc)
        OUT['validation_utc']=now.isoformat();OUT['freshness']='PASS' if dt.timedelta(0)<=now-issue<=contract.MAX_AGE else 'FAIL'
        try:
            raw,bundle_hash=builder.build(*paths,[digest(frozen[str(path)]) for path in paths],now)
            OUT['publication_validator']='PASS';OUT['completeness']='PASS'
            OUT['in_memory_bundle_sha256']=bundle_hash
        except contract.Withheld:
            OUT['publication_validator']='FAIL'
            OUT['completeness']='NOT_VERIFIED_validator_rejected'
            OUT['validator_blocker']='expired_or_future_issue' if OUT['freshness']=='FAIL' else 'full_contract_rejected'
        OUT['receipt_artifact_hashes']={name:digest(raw) for name,raw in blobs.items()}
    OUT['stage']='resources_services'
    OUT['resources']=resources()
    OUT['prefect_configuration']=deployment_configuration()
    OUT['availability']=availability()
    OUT['stable_services_preserved_during_inspection']=before_services==identities()
    OUT['routing_certificates_preserved_during_inspection']=before_config==baselines()
    OUT['stage']='complete'


if __name__=='__main__':
    try:
        main();print(json.dumps(OUT))
    except Exception as error:
        if OUT['receipt']=='PRESENT':OUT['receipt']='INVALID'
        OUT['error']={'type':type(error).__name__,'reason':str(error) if isinstance(error,RuntimeError) else 'details_withheld'}
        if hasattr(error,'code'):OUT['error']['http_status']=error.code
        print(json.dumps(OUT));raise SystemExit(1)
