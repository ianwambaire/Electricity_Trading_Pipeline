"""Exact-run persisted withholding evidence only; no inference or receipt scan."""
import datetime as dt
import hashlib
import json
import re

FLOW='01a1a1e9-4922-757b-a031-6de577b518d5'
SCHEDULED='2026-11-03T16:45:00+00:00'
REASONS={
 'Required price history unavailable for a fresh issue hour.':'PRICE_HISTORY',
 'Required load history unavailable for a fresh issue hour.':'LOAD_HISTORY',
 'Required load history unavailable at fresh price issue hours.':'JOINT_PRICE_LOAD_HOUR',
 'Current generation unavailable at fresh issue hours.':'JOINT_GENERATION_HOUR',
 'No complete operational weather hour is available.':'WEATHER_COMPLETENESS',
 'Operational weather unavailable at fresh market issue hours.':'JOINT_WEATHER_HOUR',
 'No fresh issue hour has 31 finite market and weather features.':'FINITE_31_FEATURES',
 'Silver has no observable issue-time rows.':'SILVER_EMPTY',
 'Latest Silver hour lacks complete exact-hour feature history.':'SILVER_HISTORY',
}
PREFIXES={'Price source unavailable: ':'PRICE_SOURCE','Load source unavailable: ':'LOAD_SOURCE','Current generation unavailable: ':'GENERATION_SOURCE','Operational weather unavailable: ':'WEATHER_SOURCE','Issue-time features unavailable: ':'FEATURE_COLUMNS'}

def need(ok,code):
    if not ok:raise ValueError(code)

def classify(reason):
    need(type(reason)is str and len(reason.encode())<=8192,'REASON_SCHEMA')
    result={'reason_sha256':hashlib.sha256(reason.encode()).hexdigest(),'gate':'UNVERIFIED','reason':None}
    if reason in REASONS:result.update(gate=REASONS[reason],reason=reason)
    else:
        for prefix,gate in PREFIXES.items():
            if reason.startswith(prefix):result.update(gate=gate,reason=prefix.rstrip(': ')+' (details redacted).');break
        match=re.fullmatch(r'Latest complete market hour for (price|load) (\S+) exceeds the ([0-9]+(?:\.[0-9]+)?)-hour freshness threshold\.',reason)
        if match:
            hour=R['stamp'](match[2]).isoformat();threshold=float(match[3]);need(0<threshold<=24,'THRESHOLD_SCHEMA')
            result.update(gate=match[1].upper()+'_FRESHNESS',reason='Latest complete market hour exceeds the recorded freshness threshold.',latest_hour=hour,threshold_hours=threshold)
    return result

def detail(c,flow,task,value,internal,stage):
    need(value.get('next24h_publication_status')=='SKIPPED_WITHHELD' and value.get('next24h_forecast_status')=='WITHHELD' and value.get('next24h_forecast_generated')is False and stage['status']=='WITHHELD','WITHHOLDING_STATUS_DISAGREEMENT')
    when=R['stamp'](value['next24h_forecast_withheld_at_utc']);need(R['stamp'](task['start_time'])<=when<=R['stamp'](flow['end_time']),'WITHHELD_TIME')
    margin=dt.timedelta(seconds=2)
    rows=c.execute('SELECT timestamp_utc,substr(details_json,1,262145) AS details FROM operational_incidents WHERE component=? AND event_type=? AND timestamp_utc>=? AND timestamp_utc<=? ORDER BY id LIMIT 13',('next24h forecast','forecast_withheld',(R['stamp'](task['start_time'])-margin).isoformat(),(R['stamp'](flow['end_time'])+dt.timedelta(seconds=5)).isoformat())).fetchall()
    need(len(rows)<=12,'INCIDENT_BOUND');matches=[]
    for row in rows:
        need(type(row['details'])is str and len(row['details'].encode())<=262144,'INCIDENT_SIZE')
        d=json.loads(row['details'])
        if d.get('run_id')==internal:matches.append((row,d))
    out={'internal_run_uuid':internal,'delivery_status':'SKIPPED_WITHHELD','forecast_status':'WITHHELD','receipt_expected':False,'withheld_at':when.isoformat(),'gaps':[]}
    if not matches:out['gaps']=['MISSING_WITHHOLDING_INCIDENT'];return out
    need(len(matches)==1,'INCIDENT_ASSOCIATION_AMBIGUOUS');row,d=matches[0]
    need(R['stamp'](d['timestamp'])==when and R['stamp'](task['start_time'])-margin<=R['stamp'](row['timestamp_utc'])<=R['stamp'](flow['end_time'])+dt.timedelta(seconds=5),'INCIDENT_TIME_BINDING')
    need(d.get('forecast_freshness_status')=='WITHHELD','INCIDENT_STATUS')
    raw_hours=d.get('latest_complete_hours');need(type(raw_hours)is dict and set(raw_hours)=={'price','load','generation'},'MARKET_HOUR_SCHEMA')
    need(raw_hours==value.get('next24h_latest_complete_market_hours'),'MARKET_HOUR_BINDING')
    out['latest_complete_hours']={k:R['stamp'](v).isoformat() if v is not None else None for k,v in raw_hours.items()}
    out['failed_prerequisite']=classify(d.get('reason'))
    if out['failed_prerequisite']['gate']=='UNVERIFIED':out['gaps']=['UNRECOGNIZED_REASON_REDACTED']
    return out

def inspect():
    report={'status':'BLOCKED','flow_run_id':FLOW,'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'gaps':[],'read_only':True}
    try:
        flow=R['prefect_request']('GET','/flow_runs/'+FLOW)
        need(flow['id']==FLOW and flow['auto_scheduled']is True and R['stamp'](flow['expected_start_time'])==R['stamp'](SCHEDULED),'TARGET_RUN_BINDING')
        need(R['state'](flow)=='COMPLETED','RUN_NOT_COMPLETED')
        need(R['stamp'](flow['start_time'])<=R['stamp'](flow['end_time'])<=R['stamp'](report['observed_at']),'FLOW_TIMES')
        report.update(scheduled_at=R['stamp'](flow['expected_start_time']).isoformat(),completed_at=R['stamp'](flow['end_time']).isoformat())
        tasks=R['prefect_request']('POST','/task_runs/filter',{'task_runs':{'flow_run_id':{'any_':[FLOW]}},'limit':100})
        task=R['task'](tasks,'Generate next24h production forecast',flow)
        R['task'](tasks,'Publish validated staging next24h forecast',flow)
        report['forecast_task_id']=task['id'];report.update(R['database_outcome'](flow,task));report['status']='PARTIAL' if report['gaps'] else 'PASS'
    except Exception as error:
        text=str(error);code=text if isinstance(error,ValueError) and re.fullmatch('[A-Z0-9_]{1,80}',text) else 'EVIDENCE_UNVERIFIED'
        report['gaps'].append(code);report['status']='BLOCKED' if code=='RUN_NOT_COMPLETED' else 'PARTIAL'
    return report

def validate_report(report):
    allowed={'status','flow_run_id','observed_at','gaps','read_only','scheduled_at','completed_at','forecast_task_id','internal_run_uuid','delivery_status','forecast_status','receipt_expected','withheld_at','latest_complete_hours','failed_prerequisite'}
    need(type(report)is dict and set(report)<=allowed and len(json.dumps(report,allow_nan=False))<=16384,'REPORT_SCHEMA')
    need(report['status']in {'PASS','PARTIAL','BLOCKED'} and report['flow_run_id']==FLOW and report['read_only']is True,'REPORT_IDENTITY')
    need(type(report['gaps'])is list and len(report['gaps'])<=8 and all(type(g)is str and re.fullmatch('[A-Z0-9_]{1,80}',g) for g in report['gaps']),'REPORT_GAPS')
    for key in ['observed_at','scheduled_at','completed_at','withheld_at']:
        if key in report:R['stamp'](report[key])
    if 'forecast_task_id'in report:R['uid'](report['forecast_task_id'])
    if 'internal_run_uuid'in report:need(re.fullmatch('[0-9a-f]{32}',report['internal_run_uuid']),'REPORT_INTERNAL_ID')
    for key,value in [('delivery_status','SKIPPED_WITHHELD'),('forecast_status','WITHHELD'),('receipt_expected',False)]:
        if key in report:need(report[key]==value,'REPORT_STATUS')
    if 'latest_complete_hours'in report:
        need(set(report['latest_complete_hours'])=={'price','load','generation'},'REPORT_HOURS')
        for v in report['latest_complete_hours'].values():
            if v is not None:R['stamp'](v)
    if 'failed_prerequisite'in report:
        d=report['failed_prerequisite'];need(set(d)<= {'reason_sha256','gate','reason','latest_hour','threshold_hours'},'REPORT_REASON')
        need(type(d['reason_sha256'])is str and re.fullmatch('[0-9a-f]{64}',d['reason_sha256']),'REPORT_HASH')
        safe=set(REASONS)|{p.rstrip(': ')+' (details redacted).' for p in PREFIXES}|{'Latest complete market hour exceeds the recorded freshness threshold.'}
        need(d['reason']is None or d['reason']in safe,'REPORT_REASON_TEXT')
        need(d['gate']in set(REASONS.values())|set(PREFIXES.values())|{'UNVERIFIED','PRICE_FRESHNESS','LOAD_FRESHNESS'},'REPORT_GATE')
        if 'latest_hour'in d:R['stamp'](d['latest_hour'])
        if 'threshold_hours'in d:need(type(d['threshold_hours'])in (int,float) and 0<d['threshold_hours']<=24,'REPORT_THRESHOLD')
    if report['status']=='PASS':need(not report['gaps'] and report.get('failed_prerequisite',{}).get('gate')not in {None,'UNVERIFIED'},'REPORT_PASS')
    return report

if __name__=='__main__':
    R['detail']=detail
    try:
        result=validate_report(inspect());print(json.dumps(result,sort_keys=True,allow_nan=False));raise SystemExit(0 if result['status']=='PASS' else 1)
    except Exception:
        print('{"diagnostic_failed":true}');raise SystemExit(1)
