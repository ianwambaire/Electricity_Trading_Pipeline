"""Corrected read-only association. Prefect IDs and internal run UUIDs are distinct."""
import base64
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import types

BINDINGS=__BINDINGS__
exec(compile(base64.b64decode(BINDINGS['helpers']),'<read_only_helpers>','exec'),globals())
exec(compile(base64.b64decode(BINDINGS['receipt_helpers']),'<read_only_receipt_helpers>','exec'),globals())
FLOW='01a19190-d059-77f4-8bd6-a6551880062c'
TASK='01a19236-d917-7c79-b8b2-aa8745cae244'
RECEIPTS=ROOT/'data/reports/next24h_inference'
OUT={'stage':'prefect','read_only':True,'retry':False,'actual_outcome':'UNKNOWN','forecast_generated':'UNKNOWN'}


def associate_internal_run(rows, task_start, task_end, flow_start, flow_end):
    matches=[]
    for row in rows:
        internal=row['run_id']
        require(isinstance(internal,str) and re.fullmatch('[0-9a-f]{32}',internal),'internal_run_uuid_format')
        first,last=stamp(row['start_timestamp_utc']),stamp(row['end_timestamp_utc'])
        if row['stage_name']=='Next24h forecast generation' and first<=last and abs((first-task_start).total_seconds())<=2 and abs((last-task_end).total_seconds())<=2 and flow_start-dt.timedelta(seconds=2)<=first<=last<=flow_end+dt.timedelta(seconds=2):
            matches.append(row)
    require(len(matches)==1,'forecast_stage_association_not_unique')
    return matches[0]


def database_association(flow,task):
    database=ROOT/'database/electricity_trading.db';before=database.stat()
    require(not database.is_symlink() and stat.S_ISREG(before.st_mode),'database_identity')
    def journals():return any(Path(str(database)+suffix).exists() and Path(str(database)+suffix).stat().st_size>0 for suffix in ['-wal','-journal'])
    require(not journals(),'active_database_journal_requires_separate_review')
    connection=sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1',uri=True,timeout=2)
    connection.row_factory=sqlite3.Row
    result={}
    try:
        connection.execute('PRAGMA query_only=ON')
        tables={'pipeline_stage_timings','pipeline_runs','operational_incidents'}
        connection.set_authorizer(lambda action,a,b,c,d:sqlite3.SQLITE_OK if action==sqlite3.SQLITE_SELECT or action==sqlite3.SQLITE_READ and a in tables else sqlite3.SQLITE_DENY)
        start,end=stamp(task['start_time']),stamp(task['end_time']);fs,fe=stamp(flow['start_time']),stamp(flow['end_time'])
        rows=[dict(r) for r in connection.execute('SELECT id,run_id,stage_name,start_timestamp_utc,end_timestamp_utc,duration_seconds,status '
            'FROM pipeline_stage_timings WHERE stage_name=? AND start_timestamp_utc>=? AND start_timestamp_utc<=? '
            'AND end_timestamp_utc>=? AND end_timestamp_utc<=? ORDER BY id LIMIT 10',
            ('Next24h forecast generation',(start-dt.timedelta(seconds=2)).isoformat(),(start+dt.timedelta(seconds=2)).isoformat(),
             (end-dt.timedelta(seconds=2)).isoformat(),(end+dt.timedelta(seconds=2)).isoformat()))]
        require(len(rows)<10,'forecast_stage_bound')
        selected=associate_internal_run(rows,start,end,fs,fe);internal=selected['run_id']
        stages=[dict(r) for r in connection.execute('SELECT id,run_id,stage_name,start_timestamp_utc,end_timestamp_utc,duration_seconds,status '
            'FROM pipeline_stage_timings WHERE run_id=? AND stage_name IN (?,?,?,?) ORDER BY id LIMIT 12',
            (internal,'Total pipeline','ENTSO-E ingestion','Next24h model verification','Next24h forecast generation'))]
        require(len(stages)<12,'associated_stage_bound')
        totals=[r for r in stages if r['stage_name']=='Total pipeline']
        require(len(totals)==1,'total_stage_not_unique')
        total=totals[0]
        require(fs-dt.timedelta(seconds=2)<=stamp(total['start_timestamp_utc'])<=stamp(total['end_timestamp_utc'])<=fe+dt.timedelta(seconds=2),'total_stage_outside_prefect_flow')
        pipeline=[]
        for row in connection.execute('SELECT id,run_time,status,message FROM pipeline_runs WHERE run_time>=? AND run_time<=? ORDER BY id DESC LIMIT 12',
                ((fs-dt.timedelta(seconds=2)).isoformat(),(fe+dt.timedelta(seconds=5)).isoformat())):
            data=json.loads(row['message'] or '{}')
            if data.get('run_id')==internal:
                allowed=['run_id','status','next24h_forecast_status','next24h_forecast_generated',
                         'next24h_forecast_issue_time','next24h_forecast_withheld_at_utc',
                         'next24h_forecast_freshness_status','next24h_latest_complete_market_hours']
                pipeline.append({'id':row['id'],'run_time':row['run_time'],'status':row['status'],
                                 'metadata':{k:data[k] for k in allowed if k in data}})
        require(len(pipeline)==1,'pipeline_summary_association_not_unique')
        incidents=[]
        for row in connection.execute('SELECT id,timestamp_utc,status,details_json FROM operational_incidents '
            'WHERE component=? AND event_type=? AND timestamp_utc>=? AND timestamp_utc<=? ORDER BY id DESC LIMIT 12',
            ('next24h forecast','forecast_withheld',(start-dt.timedelta(seconds=2)).isoformat(),(fe+dt.timedelta(seconds=5)).isoformat())):
            details=json.loads(row['details_json'] or '{}')
            if details.get('run_id')==internal:
                incidents.append({'id':row['id'],'timestamp_utc':row['timestamp_utc'],'status':row['status'],
                    'internal_run_uuid':internal,'withheld_at_utc':details.get('timestamp'),
                    'source':details.get('source'),'withholding':safe_reason(details.get('reason')),
                    'latest_complete_hours':{k:stamp(v).isoformat() if v else None for k,v in details.get('latest_complete_hours',{}).items() if k in ['price','load','generation']}})
        result={'internal_run_uuid':internal,'association_method':'unique_forecast_stage_matches_exact_task_interval_and_internal_total_stage_within_prefect_flow',
                'forecast_stage':selected,'related_stages':stages,'pipeline_outcome':pipeline[0],'withholding_incidents':incidents}
    finally:connection.close()
    after=database.stat()
    require(not journals() and (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'database_changed_during_read')
    result['database_consistency']='PASS_no_active_journal_and_unchanged_file_metadata'
    return result


def generated_receipt(metadata):
    require(len(metadata['matching'])==1,'generated_receipt_association_not_unique')
    identity=metadata['matching'][0]['inference_uuid'];directory=RECEIPTS/identity
    names={'forecast.csv','provenance.json','model.json','evidence.json','integrity.json'}
    require({p.name for p in directory.iterdir()}==names,'receipt_inventory')
    blobs={name:read(directory/name) for name in names}
    proof=json.loads(blobs['evidence.json']);integrity=json.loads(blobs['integrity.json'])
    require(integrity['run_id']==identity==proof['execution']['run_id'],'inference_uuid_binding')
    require(integrity['sha256']=={name:digest(blobs[name]) for name in names-{'integrity.json'}},'receipt_hash_binding')
    raw=base64.b64decode(BINDINGS['contract']);require(digest(raw)==BINDINGS['contract_sha256'],'validator_hash')
    contract=types.ModuleType('readonly_contract');exec(compile(raw,'<existing_readonly_contract>','exec'),contract.__dict__)
    rows=[{'issue_time':r['forecast_issue_time'],'target_time':r['target_timestamp'],'horizon_hours':int(r['horizon_hours']),
        'predicted_price_eur_mwh':float(r['predicted_price_eur_mwh']),'model_release':r['model_release']}
        for r in csv.DictReader(io.StringIO(blobs['forecast.csv'].decode()))]
    manifest=json.loads(blobs['model.json'])
    contract.verify_inference_receipt(proof,blobs['forecast.csv'],blobs['provenance.json'],blobs['model.json'],rows,manifest)
    require(len(rows)==24,'forecast_count')
    issue=stamp(rows[0]['issue_time'])
    require(all(r['horizon_hours']==i and stamp(r['issue_time'])==issue and stamp(r['target_time'])==issue+dt.timedelta(hours=i)
                and math.isfinite(r['predicted_price_eur_mwh']) for i,r in enumerate(rows,1)),'forecast_alignment')
    return {'inference_uuid':identity,'forecast_artifact':str(directory/'forecast.csv'),'forecast_sha256':digest(blobs['forecast.csv']),
            'issue_time':issue.isoformat(),'predictions':24,'hash_binding':'PASS'}


def main():
    flow=api('/flow_runs/'+FLOW);task=api('/task_runs/'+TASK)
    require(flow.get('id')==FLOW and flow.get('deployment_id')==DEP and stamp(flow['expected_start_time'])==dt.datetime(2026,10,31,13,45,tzinfo=dt.timezone.utc),'flow_identity')
    require(task.get('id')==TASK and task.get('flow_run_id')==FLOW and str(task.get('name','')).startswith('Generate next24h production forecast'),'task_identity')
    require((flow.get('state') or {}).get('type')=='COMPLETED' and (task.get('state') or {}).get('type')=='COMPLETED','execution_not_complete')
    OUT['prefect']={'flow_run_id':FLOW,'forecast_task_id':TASK,'flow_start':flow['start_time'],'flow_end':flow['end_time'],
                   'task_start':task['start_time'],'task_end':task['end_time'],'task_return_persisted':(task.get('state') or {}).get('data') is not None}
    OUT['stage']='internal_association';association=database_association(flow,task);OUT.update(association)
    start,end=stamp(task['start_time']),stamp(task['end_time'])
    OUT['stage']='receipts';OUT['receipt_metadata']=receipts(start,end)
    OUT['deployed_source_hashes_pass']=all(digest(read(ROOT/name))==sha for name,sha in BINDINGS['source_hashes'].items())
    require(OUT['deployed_source_hashes_pass'],'deployed_source_drift')
    summary=association['pipeline_outcome']['metadata'];stage=association['forecast_stage']
    status=summary.get('next24h_forecast_status')
    if status is not None:OUT['actual_outcome']=status
    elif stage['status']=='WITHHELD':OUT['actual_outcome']='WITHHELD'
    if OUT['actual_outcome']=='WITHHELD':
        require(stage['status']=='WITHHELD' and summary.get('next24h_forecast_generated') is False,'withholding_outcome_disagreement')
        OUT['forecast_generated']='NO'
        require(not OUT['receipt_metadata']['matching'],'receipt_exists_despite_withheld_outcome')
        OUT['capture_assessment']='EXPECTED_BEHAVIOR'
        OUT['capture_explanation']='quality_gate_raises_ForecastUnavailable_before_model_predict_and_receipt_creation'
    elif summary.get('next24h_forecast_generated') is True:
        OUT['forecast_generated']='YES';OUT['generated_forecast']=generated_receipt(OUT['receipt_metadata'])
        OUT['capture_assessment']='EXPECTED_BEHAVIOR_receipt_found'
    else:OUT['capture_assessment']='NOT_ESTABLISHED'
    OUT['local_diagnostic_correction']='Resolve internal UUID via stage times; incident and pipeline filters must use that UUID, never the Prefect ID.'
    OUT['stage']='complete'


if __name__=='__main__':
    try:main();print(json.dumps(OUT))
    except Exception as error:
        OUT['error']={'type':type(error).__name__,'reason':str(error) if isinstance(error,RuntimeError) else 'details_withheld'}
        if hasattr(error,'code'):OUT['error']['http_status']=error.code
        print(json.dumps(OUT));raise SystemExit(1)
