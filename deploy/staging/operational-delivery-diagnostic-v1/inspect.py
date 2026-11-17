"""Fixed post-activation run, existing hook logs and store metadata only.
Never invokes capture_terminal, helper, publisher, subprocess, or writes.
"""
import datetime as dt
import http.client as http_client
import json
import os
import re
import stat
import time

SLOT='2026-11-07T08:45:00+00:00'
PREFIX='Operational evidence terminal delivery: '
STATUS={'PUBLISHED','SKIPPED_DUPLICATE','SKIPPED_OLDER_RUN','FAILED','DISABLED','SKIPPED_NOT_NATURAL'}
REASONS={'CAPTURE_UNVERIFIED','OPERATIONAL_STORE_UNCERTAIN','IMMUTABLE_RUNTIME_UNVERIFIED','EVIDENCE_REJECTED','CAPTURE_OR_STORE_UNVERIFIED','TERMINAL_CAPTURE_UNVERIFIED','HOOK_UNAVAILABLE','UNSUPPORTED_TERMINAL_STATE'}
EXCEPTIONS={'NameError','AttributeError','TypeError','ImportError','ModuleNotFoundError','PermissionError','FileNotFoundError','TimeoutError','ValueError','RuntimeError'}

def log_body(flow):
    OP.identifier(flow['id'])
    return {'logs':{'flow_run_id':{'any_':[flow['id']]},'timestamp':{'after_':flow['start_time'],'before_':(OP.timestamp(flow['end_time'])+dt.timedelta(seconds=120)).isoformat()},'text':{'query':'operational'}},'limit':64,'offset':0,'sort':'TIMESTAMP_ASC'}

def logs(flow):
    conn=http_client.HTTPConnection('127.0.0.1',4200,timeout=3)
    try:
        conn.request('POST','/api/logs/filter',body=json.dumps(log_body(flow)),headers={'Content-Type':'application/json','Accept-Encoding':'identity'})
        response=conn.getresponse()
        PLAN.need(response.status==200 and (response.getheader('Content-Type') or '').split(';')[0]=='application/json','LOG_HTTP')
        PLAN.need(response.getheader('Content-Encoding') in (None,'identity'),'LOG_ENCODING')
        raw=response.read(262145);PLAN.need(len(raw)<=262144,'LOG_BOUND')
        def pairs(items):
            result={}
            for key,value in items:PLAN.need(key not in result,'LOG_JSON');result[key]=value
            return result
        value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:PLAN.need(False,'LOG_JSON'));PLAN.need(type(value)is list and len(value)<64,'LOG_RECORD_BOUND')
        return value
    finally:conn.close()

def sanitize_logs(rows,flow):
    result=[]
    for row in rows:
        PLAN.need(row.get('flow_run_id')==flow['id'],'LOG_FLOW_IDENTITY')
        stamp=OP.timestamp(row['timestamp']);PLAN.need(OP.timestamp(flow['start_time'])<=stamp<=OP.timestamp(flow['end_time'])+dt.timedelta(seconds=120),'LOG_TIME_SCOPE')
        message=row.get('message');PLAN.need(isinstance(message,str) and len(message)<=65536,'LOG_MESSAGE_BOUND')
        item={'at':stamp.isoformat()}
        if message.startswith(PREFIX):
            try:value=json.loads(message[len(PREFIX):])
            except Exception:value=None
            if type(value)is dict and set(value)<= {'status','reason'} and value.get('status')in STATUS and ('reason'not in value or value['reason']in REASONS):
                item.update(kind='TERMINAL_RESULT',**value)
            else:item['kind']='MALFORMED_TERMINAL_RESULT'
        elif '_operational_evidence_terminal_hook' in message:
            item['kind']='HOOK_STARTED' if 'Running hook' in message else 'HOOK_FINISHED' if 'finished running successfully' in message else 'HOOK_LOG'
        elif 'Operational flow identity unavailable' in message:item['kind']='FLOW_IDENTITY_UNAVAILABLE'
        elif 'Operational task identity unavailable' in message:item['kind']='TASK_IDENTITY_UNAVAILABLE'
        else:item['kind']='OTHER_OPERATIONAL_LOG'
        item['exceptions']=sorted(c for c in EXCEPTIONS if re.search(r'\b'+c+r':',message))
        item['locations']=[x for x in ['_operational_evidence_terminal_hook','operational_terminal.py','operational_capture.py','bootstrap.py'] if x in message]
        item['missing_symbol'] = next((x for x in ['json','logger','os','notify'] if "name '"+x+"' is not defined" in message),None)
        result.append(item)
    return result

def summary(connection,flow):
    deadline=time.monotonic()+2
    connection.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
    try:rows=connection.execute('SELECT substr(message,1,262145) FROM pipeline_runs WHERE run_time>=? AND run_time<=? LIMIT 13',(flow['start_time'],flow['end_time'])).fetchmany(13)
    finally:connection.set_progress_handler(None,0)
    PLAN.need(len(rows)<13,'SUMMARY_BOUND')
    matching=[v for (raw,) in rows for v in [PRODUCER.bounded_json(raw)] if v.get('prefect_flow_run_id')==flow['id']]
    PLAN.need(len(matching)==1,'STABLE_IDENTITY_REQUIRED');v=matching[0]
    internal=v.get('run_id');PLAN.need(isinstance(internal,str) and re.fullmatch('[0-9a-f]{32}',internal),'PIPELINE_IDENTITY')
    inference=v.get('next24h_forecast_status');delivery=v.get('next24h_publication_status')
    PLAN.need(inference in {'GENERATED','UNCHANGED','WITHHELD','FAILED','UNAVAILABLE',None},'INFERENCE_STATUS')
    PLAN.need(delivery in {'PUBLISHED','SKIPPED_WITHHELD','SKIPPED_EXPIRED','SKIPPED_DUPLICATE','REJECTED_OLDER_ISSUE','DISABLED','REJECTED_INFERENCE','FAILED',None},'DELIVERY_STATUS')
    return {'pipeline_run_id':internal,'inference':inference,'forecast_delivery':delivery}

def store():
    P=PREFLIGHT;P.safe(P.STORE);P.safe(P.STORE/'releases')
    result={'current_exists':False,'lock_exists':False,'releases':[],'partial_count':0}
    for name in ['current','.publication.lock']:
        try:s=(P.STORE/name).lstat()
        except FileNotFoundError:continue
        PLAN.need(stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_gid in ({992} if name=='current' else {0,992}) and not s.st_mode&0o022,'STORE_ENTRY_METADATA')
        result['current_exists' if name=='current' else 'lock_exists']=True
    fd=CAPTURE.directory(P.STORE/'releases')
    try:
        with os.scandir(fd) as entries:
            for i,entry in enumerate(entries):
                PLAN.need(i<16 and not entry.is_symlink() and entry.is_dir(follow_symlinks=False),'STORE_INVENTORY')
                s=entry.stat(follow_symlinks=False);PLAN.need(s.st_uid==0 and s.st_gid==992 and stat.S_IMODE(s.st_mode)==0o750,'STORE_RELEASE_METADATA')
                if re.fullmatch('[0-9a-f]{64}',entry.name):result['releases'].append({'id':entry.name,'mtime':dt.datetime.fromtimestamp(s.st_mtime,dt.timezone.utc).isoformat()})
                else:PLAN.need(re.fullmatch(r'\.partial-[0-9a-f]{32}',entry.name)is not None,'STORE_ENTRY_SCOPE');result['partial_count']+=1
    finally:os.close(fd)
    return result

def source_metadata():
    parent=CAPTURE.directory(PREFLIGHT.PRODUCTION/'database')
    try:
        result={}
        for name in ['electricity_trading.db','electricity_trading.db-wal','electricity_trading.db-shm','electricity_trading.db-journal']:
            try:info=os.stat(name,dir_fd=parent,follow_symlinks=False)
            except FileNotFoundError:continue
            PLAN.need(stat.S_ISREG(info.st_mode),'SOURCE_METADATA_TYPE')
            result['database' if name=='electricity_trading.db' else name.rsplit('-',1)[1]]={'bytes':info.st_size,'uid':info.st_uid,'gid':info.st_gid,'mode':stat.S_IMODE(info.st_mode),'links':info.st_nlink,'mtime':dt.datetime.fromtimestamp(info.st_mtime,dt.timezone.utc).isoformat()}
        return result
    finally:os.close(parent)

def inspect():
    P=PREFLIGHT
    record=json.loads(P.read(P.CONTROL/'record.json'));PLAN.record_valid(record,CONFIG)
    PLAN.need(record['phase']=='APPLIED' and record.get('activation_bounds'),'ACTIVATION_NOT_VERIFIED')
    for key,item in CONFIG['files'].items():
        if key.startswith('helper/') or key in {'launcher','sudoers'}:
            PLAN.need(P.snap(__import__('pathlib').Path(item['destination']),item['uid'],item['gid'],item['mode'])[0]['sha256']==item['sha256'],'HELPER_DRIFT')
    for rel in CONFIG['worker']:
        PLAN.need(P.snap(P.PRODUCTION/rel,1000,1000,0o644)[0]['sha256']==CONFIG['files']['worker/'+rel]['sha256'],'WORKER_DRIFT')
    flows=P.BASE['api']('/flow_runs/filter',{'deployments':{'id':{'any_':[PLAN.DEPLOYMENT]}},'flow_runs':{'expected_start_time':{'after_':'2026-11-07T08:44:59+00:00','before_':'2026-11-07T08:45:01+00:00'}},'limit':4})
    matches=[f for f in flows if OP.timestamp(f['expected_start_time'])==OP.timestamp(SLOT)]
    PLAN.need(len(matches)==1,'EXACT_RUN_AMBIGUOUS');flow=matches[0]
    PRODUCER.natural(flow,PLAN.DEPLOYMENT,dt.datetime.now(dt.timezone.utc))
    PLAN.need(OP.timestamp(flow['expected_start_time'])>=OP.timestamp(record['activation_bounds'][1]),'PRE_ACTIVATION')
    result={'status':'PARTIAL','changed':False,'run_id':flow['id'],'terminal_state':flow['state']['type'],'scheduled_at':flow['expected_start_time'],'started_at':flow['start_time'],'completed_at':flow['end_time'],'state_at':flow['state'].get('timestamp'),'operational_enabled':P.deployment().get('job_variables',{}).get('env',{}).get(PLAN.FLAG)=='true'}
    result['logs']=sanitize_logs(logs(flow),flow)
    tasks=CAPTURE.query(flow['id'],tasks=True)
    for t in tasks:OP.identifier(t['id']);PLAN.need(t.get('flow_run_id')==flow['id'],'TASK_FLOW_IDENTITY')
    ft=[t for t in tasks if isinstance(t.get('name'),str) and (t['name']==PRODUCER.FORECAST_TASK or t['name'].startswith(PRODUCER.FORECAST_TASK+'-'))]
    PLAN.need(len(ft)<=1,'FORECAST_TASK_AMBIGUOUS')
    result['forecast_task']=[{'id':t['id'],'state':t['state']['type']} for t in ft]
    result['source_metadata']=source_metadata()
    try:
        with CAPTURE.Source().snapshot() as connection:result['summary']=summary(connection,flow)
    except Exception as error:result['summary_failure']=str(error) if isinstance(error,OP.InvalidEvidence) and re.fullmatch('[A-Z_]{1,60}',str(error)) else 'SUMMARY_UNVERIFIED'
    result['store']=store()
    result['status']='PASS'
    return result
