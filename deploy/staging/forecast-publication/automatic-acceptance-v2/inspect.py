"""Fixed-scope read-only acceptance. Dependencies injected from verified bytes.
No application imports, publisher entrypoint, writable SQLite or remote files.
"""
import datetime as dt
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import uuid

ROOT=Path('/home/ec2-user/Electricity_Trading_Pipeline')
RECEIPTS=ROOT/'data/reports/next24h_inference'
PUBLICATION=Path('/srv/powerflow/forecast-publications')
DEP='47e5ef51-26d0-44b6-b119-2c40d0e77397'
ACTIVATED='2026-11-03T14:56:20.355989+00:00' # conservative successful-apply evidence time
STATUSES={'PUBLISHED','SKIPPED_WITHHELD','SKIPPED_EXPIRED','SKIPPED_DUPLICATE','REJECTED_OLDER_ISSUE','DISABLED','REJECTED_INFERENCE','FAILED'}
NAMES={'forecast.csv','provenance.json','model.json','evidence.json','integrity.json'}
class Stop(ValueError):pass

def need(value,code):
    if not value:raise Stop(code)

def stamp(value):
    result=dt.datetime.fromisoformat(value.replace('Z','+00:00'));need(result.tzinfo is not None,'TIMESTAMP_TIMEZONE')
    return result.astimezone(dt.timezone.utc)

def uid(value):
    need(type(value)is str and str(uuid.UUID(value))==value,'UUID_FORMAT');return value

def state(value):return (value.get('state') or {}).get('type')

def task(tasks,prefix,flow):
    found=[t for t in tasks if t.get('name','').startswith(prefix)]
    need(len(found)==1,'TASK_ASSOCIATION');t=found[0];uid(t['id'])
    need(t.get('flow_run_id')==flow['id'] and state(t)=='COMPLETED','TASK_STATE_OR_FLOW')
    need(stamp(flow['start_time'])<=stamp(t['start_time'])<=stamp(t['end_time'])<=stamp(flow['end_time']),'TASK_INTERVAL')
    return t

def receipt_bundle(files,identity,contract,builder,now):
    need(set(files)==NAMES,'RECEIPT_INVENTORY')
    proof=contract.decode(files['evidence.json']);integrity=contract.decode(files['integrity.json'])
    hashes={n:hashlib.sha256(files[n]).hexdigest() for n in NAMES-{'integrity.json'}}
    need(set(integrity)=={'version','run_id','sha256'} and type(integrity['version'])is int and integrity['version']==1
         and integrity['run_id']==proof['execution']['run_id']==uid(identity) and integrity['sha256']==hashes,'RECEIPT_HASH_BINDING')
    old_file,old_validate=builder.safe_file,builder.validate;expired=False
    def validate(raw,digest,clock):
        nonlocal expired
        try:return contract.validate(raw,digest,clock)
        except contract.ExpiredPublication:
            expired=True;return contract.decode(raw) # structural validation already passed at ACTUAL UTC
    paths=[Path(n) for n in ('forecast.csv','provenance.json','model.json','evidence.json')]
    try:
        builder.safe_file=lambda p:files[str(p)]
        builder.validate=validate
        raw,digest=builder.build(*paths,[hashes[str(p)] for p in paths],now)
    finally:builder.safe_file, builder.validate=old_file,old_validate
    return contract.decode(raw),digest,hashes,expired

def prefect_request(method,path,body=None):
    """Exactly three read operations at the original loopback HTTP origin.

    Prefect filters are read-only POSTs. No auth, proxy, redirects, arbitrary
    origin, query parameters or mutation endpoints are accepted.
    """
    operation='SCOPE'
    def require(ok,code):need(ok,'PREFECT_'+operation+'_'+code)
    def identifier(value,code):
        try:return uid(value)
        except (ValueError,TypeError,AttributeError):raise Stop('PREFECT_'+operation+'_'+code) from None
    require(type(path)is str and type(method)is str,'REQUEST')
    if path=='/flow_runs/filter':
        operation='FLOW_FILTER'
        expected={'deployments':{'id':{'any_':[DEP]}},'flow_runs':{'state':{'type':{'any_':['COMPLETED']}}},'sort':'EXPECTED_START_TIME_DESC','limit':20}
        require(method=='POST','METHOD');require(type(body)is dict and type(body.get('limit'))is int and body==expected,'BODY')
        identity=None
    elif path=='/task_runs/filter':
        operation='TASK_FILTER';require(method=='POST','METHOD')
        try:
            ids=body['task_runs']['flow_run_id']['any_']
            require(type(ids)is list and len(ids)==1,'BODY')
            identity=identifier(ids[0],'REQUEST_IDENTIFIER')
        except (KeyError,TypeError,IndexError):raise Stop('PREFECT_TASK_FILTER_BODY') from None
        require(type(body)is dict and type(body.get('limit'))is int and body=={'task_runs':{'flow_run_id':{'any_':[identity]}},'limit':100},'BODY')
    elif re.fullmatch(r'/flow_runs/[0-9a-f-]{36}',path):
        operation='FLOW_DETAIL';identity=identifier(path[len('/flow_runs/'):],'REQUEST_IDENTIFIER')
        require(method=='GET','METHOD');require(body is None,'BODY')
    else:raise Stop('PREFECT_SCOPE_PATH')
    connection=None
    try:
        # Same origin/authentication/HTTP behavior as the reviewed BASE helper.
        connection=http.client.HTTPConnection('127.0.0.1',4200,timeout=3)
        connection.request(method,'/api'+path,body=None if body is None else json.dumps(body,allow_nan=False),headers={'Content-Type':'application/json'})
        response=connection.getresponse()
        require(not 300<=response.status<400,'REDIRECT')
        require(response.status==200,'HTTP_STATUS')
        raw=response.read(1_000_001)
        require(type(raw)is bytes and len(raw)<=1_000_000,'RESPONSE_BOUND')
        require((response.getheader('Content-Type') or '').split(';')[0].strip().lower()=='application/json','CONTENT_TYPE')
        def pairs(items):
            value={}
            for key,item in items:require(key not in value,'RESPONSE_JSON');value[key]=item
            return value
        try:value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:require(False,'RESPONSE_JSON'))
        except (ValueError,UnicodeError,RecursionError) as error:
            if type(error)is Stop:raise
            raise Stop('PREFECT_'+operation+'_RESPONSE_JSON') from None
        if operation=='FLOW_DETAIL':require(type(value)is dict,'RESPONSE_SCHEMA');rows=[value]
        else:
            require(type(value)is list and (len(value)<100 if operation=='TASK_FILTER' else len(value)<=20),'RESPONSE_BOUND');rows=value
        seen=set()
        for row in rows:
            require(type(row)is dict,'RESPONSE_SCHEMA')
            row_id=identifier(row.get('id'),'RESPONSE_IDENTIFIER');require(row_id not in seen,'RESPONSE_DUPLICATE');seen.add(row_id)
            require(type(row.get('state'))is dict and type(row['state'].get('type'))is str,'RESPONSE_SCHEMA')
            if operation=='TASK_FILTER':
                require(identifier(row.get('flow_run_id'),'RESPONSE_IDENTIFIER')==identity,'RESPONSE_ASSOCIATION')
                require(type(row.get('name'))is str,'RESPONSE_SCHEMA')
            else:
                require(identifier(row.get('deployment_id'),'RESPONSE_IDENTIFIER')==DEP,'RESPONSE_ASSOCIATION')
                if identity is not None:require(row_id==identity,'RESPONSE_ASSOCIATION')
        return value
    except Stop:raise
    except (socket.timeout,TimeoutError):raise Stop('PREFECT_'+operation+'_TIMEOUT') from None
    except http.client.HTTPException:raise Stop('PREFECT_'+operation+'_HTTP_PROTOCOL') from None
    except OSError:raise Stop('PREFECT_'+operation+'_IO_ERROR') from None
    finally:
        if connection is not None:connection.close()

class Remote:
    """All access destinations and SQL are fixed. No arbitrary command API."""
    def sources(self):
        for name,path in [('pipeline',ROOT/'src/scheduled_pipeline.py'),('delivery',ROOT/'src/shared/forecast_delivery.py')]:
            raw=READ['capture'](path.parent,path.name,1000,200000)
            need(hashlib.sha256(raw).hexdigest()==SOURCE_HASHES[name],'DEPLOYED_SOURCE_DRIFT')
    def clock(self):return dt.datetime.now(dt.timezone.utc)
    def runs(self):
        return prefect_request('POST','/flow_runs/filter',{'deployments':{'id':{'any_':[DEP]}},'flow_runs':{'state':{'type':{'any_':['COMPLETED']}}},'sort':'EXPECTED_START_TIME_DESC','limit':20})
    def flow(self,identity):return prefect_request('GET','/flow_runs/'+uid(identity))
    def tasks(self,identity):
        return prefect_request('POST','/task_runs/filter',{'task_runs':{'flow_run_id':{'any_':[uid(identity)]}},'limit':100})
    def receipt(self,t):
        fd=directory(RECEIPTS);matches=[];total=0
        try:
            with os.scandir(fd) as entries:
                for entry in entries:
                    total+=1;need(total<=512,'RECEIPT_SCAN_BOUND')
                    need(not entry.is_symlink(),'RECEIPT_SYMLINK')
                    if entry.name.startswith('.partial-'):continue
                    uid(entry.name);need(entry.is_dir(follow_symlinks=False),'RECEIPT_DIRECTORY')
                    proof=CONTRACT.decode(READ['capture'](RECEIPTS/entry.name,'evidence.json',1000))
                    e=proof['execution']
                    if stamp(t['start_time'])<=stamp(e['started_at'])<=stamp(e['issued_at'])<=stamp(e['completed_at'])<=stamp(t['end_time']):matches.append((entry.name,proof))
            need(len(matches)<=1,'RECEIPT_ASSOCIATION_AMBIGUOUS')
            if not matches:return None
            identity,proof=matches[0];sub=os.open(identity,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            try:
                with os.scandir(sub) as entries:inventory=[e.name for e in entries]
                need(len(inventory)==5 and set(inventory)==NAMES,'RECEIPT_INVENTORY')
            finally:os.close(sub)
            files={name:READ['capture'](RECEIPTS/identity,name,1000) for name in NAMES}
            need(CONTRACT.decode(files['evidence.json'])==proof,'RECEIPT_CHANGED')
            return identity,files
        finally:os.close(fd)
    def history(self,bundle):
        READ['persisted'](READ['capture'](RECEIPTS.parent,'next24h_forecast_history.csv',1000,64000000),bundle)
    def outcome(self,flow,t):return database_outcome(flow,t)
    def publication(self):
        diagnostic=DIAGNOSTIC['validate_report'](DIAGNOSTIC['inspect'](BASE,CONTRACT.__dict__))
        if diagnostic['publication_state'] not in {'VALID','EXPIRED'}:return diagnostic,None,None
        target=os.readlink(PUBLICATION/'current');need(re.fullmatch('releases/[0-9a-f]{64}',target),'POINTER_ESCAPE')
        raw=READ['capture'](PUBLICATION/target,'bundle.json',0)
        digest=target.split('/')[1]
        try:CONTRACT.validate(raw,digest)
        except CONTRACT.ExpiredPublication:pass
        need(os.readlink(PUBLICATION/'current')==target,'POINTER_DRIFT')
        return diagnostic,raw,target
    def recheck(self,target):
        BASE['publication_metadata']();need(os.readlink(PUBLICATION/'current')==target,'POINTER_DRIFT')
    def http(self,path):return request(path)

def directory(path):
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in Path(path).parts[1:]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=child
        return fd
    except Exception:os.close(fd);raise

def database_outcome(flow,t):
    path=ROOT/'database/electricity_trading.db';parent=directory(path.parent)
    fd=None;c=None
    def journals():
        for suffix in ['-wal','-journal','-shm']:
            try:s=os.stat(path.name+suffix,dir_fd=parent,follow_symlinks=False)
            except FileNotFoundError:continue
            need(stat.S_ISREG(s.st_mode) and s.st_size==0,'DATABASE_ACTIVE_JOURNAL')
    try:
        journals();fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent);before=os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_uid==1000 and not before.st_mode&0o022,'DATABASE_METADATA')
        c=sqlite3.connect('file:/proc/self/fd/'+str(fd)+'?mode=ro&immutable=1',uri=True,timeout=2)
        c.execute('PRAGMA query_only=ON');c.row_factory=sqlite3.Row
        c.set_authorizer(lambda action,a,b,*rest:sqlite3.SQLITE_OK if action==sqlite3.SQLITE_SELECT or action==sqlite3.SQLITE_READ and a in {'pipeline_runs','pipeline_stage_timings'} or action==sqlite3.SQLITE_FUNCTION and b=='substr' else sqlite3.SQLITE_DENY)
        budget=[0]
        def progress():budget[0]+=1;return int(budget[0]>20000)
        c.set_progress_handler(progress,1000)
        start,end=stamp(t['start_time']),stamp(t['end_time']);margin=dt.timedelta(seconds=2)
        rows=list(c.execute('SELECT run_id,start_timestamp_utc,end_timestamp_utc,status FROM pipeline_stage_timings WHERE stage_name=? AND start_timestamp_utc>=? AND start_timestamp_utc<=? AND end_timestamp_utc>=? AND end_timestamp_utc<=? LIMIT 3',('Next24h forecast generation',(start-margin).isoformat(),(start+margin).isoformat(),(end-margin).isoformat(),(end+margin).isoformat())))
        need(len(rows)==1 and re.fullmatch('[0-9a-f]{32}',rows[0]['run_id']),'INTERNAL_RUN_ASSOCIATION')
        internal=rows[0]['run_id'];found=[]
        records=c.execute('SELECT status,run_time,substr(message,1,262145) AS message FROM pipeline_runs WHERE run_time>=? AND run_time<=? ORDER BY id DESC LIMIT 13',(stamp(flow['start_time']).isoformat(),(stamp(flow['end_time'])+dt.timedelta(seconds=5)).isoformat())).fetchall()
        need(len(records)<=12,'PIPELINE_RECORD_BOUND')
        for row in records:
            need(len(row['message'].encode())<=262144,'PIPELINE_MESSAGE_BOUND');value=json.loads(row['message'])
            if value.get('run_id')==internal:
                need(row['status']=='SUCCESS' and value.get('status')=='SUCCESS','PIPELINE_OUTCOME')
                found.append(value)
        need(len(found)==1,'PIPELINE_RECORD_ASSOCIATION')
        value=found[0]
        if value.get('next24h_forecast_generated') is True:need(rows[0]['status']=='SUCCESS','FORECAST_STAGE_STATUS')
        return {'internal_run_id':internal,'status':value.get('next24h_publication_status'),'forecast_status':value.get('next24h_forecast_status'),'generated':value.get('next24h_forecast_generated'),'issue':value.get('next24h_forecast_issue_time')}
    finally:
        if c:c.close()
        if fd is not None:
            after=os.fstat(fd);current=os.stat(path.name,dir_fd=parent,follow_symlinks=False)
            os.close(fd)
            try:
                journals();need((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)==(current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns,current.st_ctime_ns),'DATABASE_CHANGED')
            finally:os.close(parent)
        else:os.close(parent)

def request(path):
    need(path in {'/api/forecast/next24','/api/operations/summary'},'HTTP_SCOPE')
    # Nginx staging TLS route, fixed hostname/SNI, trusted system CA; no redirects/proxy/auth tokens.
    c=http.client.HTTPSConnection('staging.powerflowenergy.dev',timeout=10 if path.endswith('/operations/summary') else 5)
    try:
        c.request('GET',path);r=c.getresponse();raw=r.read(262145)
        need(len(raw)<=262144,'HTTP_BODY_BOUND')
        need((r.getheader('Content-Type') or '').split(';')[0].strip().lower()=='application/json','HTTP_CONTENT_TYPE')
        return r.status,{k.lower():v for k,v in r.getheaders() if k.lower() in {'cache-control','content-type'}},json.loads(raw)
    finally:c.close()

def api_checks(io,bundle,now,out):
    started=io.clock()
    code,headers,body=io.http('/api/forecast/next24');out['forecast_http']=code
    now=io.clock();out['api_checked_at']=now.isoformat()
    need(any(v.strip().lower()=='no-store' for v in headers.get('cache-control','').split(',')),'API_CACHE')
    out['cache_control']='no-store'
    issue=stamp(bundle['forecasts'][0]['issue_time']);expired=now>issue+CONTRACT.MAX_AGE
    crossing=started<=issue+CONTRACT.MAX_AGE<now
    if crossing:out['gaps'].append('FRESHNESS_BOUNDARY_DURING_READBACK')
    if code==503:
        need(body=={'detail':{'code':'FORECAST_WITHHELD'}},'API_WITHHELD_CONTRACT')
        out['api_predictions']=0;out['api_state']='WITHHELD'
        need(expired,'API_WITHHELD_WHILE_ELIGIBLE')
    else:
        need(code==200 and (not expired or crossing),'API_STATUS_OR_EXPIRY')
        need(type(body)is dict and body.get('row_count')==24 and type(body.get('forecasts'))is list and len(body['forecasts'])==24,'API_PREDICTION_COUNT')
        for actual,expected in zip(body['forecasts'],bundle['forecasts']):
            need(set(actual)==set(expected),'API_ROW_SCHEMA')
            for name in ['issue_time','target_time']:need(stamp(actual[name])==stamp(expected[name]),'API_TARGET_ALIGNMENT')
            need(type(actual['horizon_hours'])is int and actual['horizon_hours']==expected['horizon_hours'] and actual['model_release']==expected['model_release'],'API_MODEL_OR_HORIZON')
            value=actual['predicted_price_eur_mwh'];need(type(value)in(int,float) and math.isfinite(value) and value==expected['predicted_price_eur_mwh'],'API_VALUES')
        p=body.get('publication');need(type(p)is dict and set(p)=={'status','issue_time','expires_at','completed_at'},'API_PROVENANCE')
        need(p['status']=='VALID' and stamp(p['issue_time'])==issue and stamp(p['expires_at'])==issue+CONTRACT.MAX_AGE and stamp(p['completed_at'])==stamp(bundle['execution']['completed_at']),'API_PROVENANCE')
        out.update(api_predictions=24,api_state='VALID',api_binding='VALUES_MODEL_ISSUE_COMPLETION')
    started=io.clock();code,headers,body=io.http('/api/operations/summary');out['operations_http']=code
    need(code==200 and type(body)is dict,'OPERATIONS_HTTP')
    ended=io.clock();expected='EXPIRED' if ended>issue+CONTRACT.MAX_AGE else 'VALID'
    if started<=issue+CONTRACT.MAX_AGE<ended:
        out['gaps'].append('FRESHNESS_BOUNDARY_DURING_OPERATIONS');need(body.get('forecast_status')in {'VALID','EXPIRED'},'OPERATIONS_DISAGREEMENT');expected=body['forecast_status']
    else:need(body.get('forecast_status')==expected,'OPERATIONS_DISAGREEMENT')
    if expected=='VALID':
        reason=body.get('forecast_reason','');need(issue.isoformat() in reason and (issue+CONTRACT.MAX_AGE).isoformat() in reason,'OPERATIONS_PROVENANCE')
    out['operations_status']=expected

def inspect(io,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    out={'status':'BLOCKED','inspected_at':now.isoformat(),'phase':'RUN','run':None,'receipt':None,'delivery_status':None,'publication':'UNVERIFIED','gaps':[],'react':'PENDING_BROWSER','read_only':True}
    try:
        io.sources();out['deployed_source_binding']='PASS'
        runs=io.runs();need(type(runs)is list and len(runs)<=20,'FLOW_BOUND')
        eligible=[]
        for r in runs:
            if r.get('deployment_id')!=DEP or state(r)!='COMPLETED' or r.get('auto_scheduled')is not True:continue
            scheduled=stamp(r['expected_start_time'])
            if scheduled>=stamp(ACTIVATED) and scheduled.minute==45 and scheduled.second==scheduled.microsecond==0 and stamp(ACTIVATED)<=stamp(r['start_time'])<=stamp(r['end_time'])<=now:eligible.append(r)
        need(eligible,'NO_COMPLETED_POST_ACTIVATION_NATURAL_RUN')
        chosen=max(eligible,key=lambda r:stamp(r['expected_start_time']));uid(chosen['id']);flow=io.flow(chosen['id'])
        need(all(flow.get(k)==chosen.get(k) for k in ['id','deployment_id','auto_scheduled']) and state(flow)=='COMPLETED'
             and all(stamp(flow[k])==stamp(chosen[k]) for k in ['expected_start_time','start_time','end_time']),'FLOW_CHANGED')
        out['run']={k:flow[k] for k in ['id','expected_start_time','start_time','end_time']}
        tasks=io.tasks(flow['id']);need(type(tasks)is list and len(tasks)<100,'TASK_BOUND')
        t=task(tasks,'Generate next24h production forecast',flow)
        out['phase']='DELIVERY';delivery=io.outcome(flow,t);s=delivery['status']
        need(s is None or s in STATUSES,'UNRECOGNIZED_DELIVERY_STATUS');out['delivery_status']=s
        need(s is not None,'MISSING_DELIVERY_STATUS')
        out['phase']='RECEIPT';result=io.receipt(t);need(result is not None,'MISSING_RECEIPT')
        identity,files=result;bundle,digest,hashes,expired=receipt_bundle(files,identity,CONTRACT,BUILDER,now)
        need(stamp(t['start_time'])<=stamp(bundle['execution']['started_at'])<=stamp(bundle['execution']['issued_at'])<=stamp(bundle['execution']['completed_at'])<=stamp(t['end_time']),'RECEIPT_TASK_INTERVAL')
        need(delivery.get('generated')is True and delivery.get('forecast_status')in {'GENERATED','UNCHANGED'} and stamp(delivery['issue'])==stamp(bundle['forecasts'][0]['issue_time']),'DELIVERY_RECEIPT_ASSOCIATION')
        io.history(bundle)
        out['receipt']=identity;out['receipt_hashes']=hashes;out['features']=31;out['receipt_integrity']='PASS';out['model']=bundle['model']
        out['association']='UNIQUE_FORECAST_TASK_RECEIPT_INTERNAL_STAGE_ISSUE_AND_ACTIVE_BUNDLE'
        out['phase']='PUBLICATION';diagnostic,raw,target=io.publication();out['publication']=diagnostic['publication_state']
        out['publication_phase']=diagnostic.get('phase','NONE');out['publication_cause']=diagnostic.get('cause','NONE')
        need(raw is not None,'PUBLICATION_NOT_VALIDATED')
        if target!='releases/'+digest or hashlib.sha256(raw).hexdigest()!=digest:
            need(s!='PUBLISHED','PUBLICATION_RECEIPT_MISMATCH')
            out['gaps'].append('ACTIVE_PUBLICATION_DIFFERENT_RECEIPT');out['status']='PARTIAL';return out
        need(CONTRACT.decode(raw)==bundle,'PUBLICATION_BUNDLE_MISMATCH');out['bundle_sha256']=digest;out['pointer_binding']='PASS'
        issue=stamp(bundle['forecasts'][0]['issue_time']);cutoff=issue+CONTRACT.MAX_AGE
        out['timing']={'issue':issue.isoformat(),'expiry':cutoff.isoformat(),'expired_at_inspection':expired,'remaining_at_inspection_seconds':(cutoff-now).total_seconds(),'publication_time':None,'publication_time_evidence':'NOT_PERSISTED'}
        p=task(tasks,'Publish validated staging next24h forecast',flow)
        need(stamp(p['start_time'])>=stamp(t['end_time']),'DELIVERY_TASK_ORDER')
        out['publication_task_id']=p['id']
        if s=='PUBLISHED':
            lower,upper=stamp(p['start_time']),stamp(p['end_time']);need(issue<=lower<=cutoff,'PUBLISHED_OUTSIDE_ELIGIBILITY')
            if upper>cutoff:out['gaps'].append('PUBLICATION_TIME_BOUNDARY_UNVERIFIED')
            out['timing'].update(publication_interval_start=lower.isoformat(),publication_interval_end=upper.isoformat(),completion_to_publication_seconds_bounds=[(lower-stamp(flow['end_time'])).total_seconds(),(upper-stamp(flow['end_time'])).total_seconds()],remaining_at_publication_seconds_bounds=[(cutoff-upper).total_seconds(),(cutoff-lower).total_seconds()])
        out['phase']='API';api_checks(io,bundle,now,out);io.recheck(target)
        if s!='PUBLISHED':out['gaps'].append('DELIVERY_DID_NOT_PUBLISH_THIS_RUN')
        if io.clock()>cutoff:out['gaps'].append('EXPIRED_AT_INSPECTION')
        out['status']='PARTIAL' if out['gaps'] else 'PASS';out['phase']='COMPLETE'
    except Exception as error:
        code=str(error) if type(error)is Stop and re.fullmatch('[A-Z0-9_]{1,80}',str(error)) else 'EVIDENCE_UNVERIFIED'
        out['gaps'].append(code);out['status']='BLOCKED' if code=='NO_COMPLETED_POST_ACTIVATION_NATURAL_RUN' else 'PARTIAL' if code in {'MISSING_RECEIPT','MISSING_DELIVERY_STATUS','PUBLICATION_NOT_VALIDATED','EVIDENCE_UNVERIFIED'} else 'FAILED'
    return out

def validate_report(report):
    allowed={'status','inspected_at','phase','run','receipt','delivery_status','publication','publication_phase','publication_cause','gaps','react','read_only','deployed_source_binding','receipt_hashes','features','receipt_integrity','association','model','bundle_sha256','pointer_binding','timing','publication_task_id','forecast_http','cache_control','api_predictions','api_state','api_binding','api_checked_at','operations_http','operations_status'}
    need(type(report)is dict and set(report)<=allowed and len(json.dumps(report,allow_nan=False).encode())<=32768,'REPORT_SCHEMA')
    need(report['status'] in {'PASS','PARTIAL','BLOCKED','FAILED'} and report['phase'] in {'RUN','DELIVERY','RECEIPT','PUBLICATION','API','COMPLETE'} and report['read_only']is True and report['react']=='PENDING_BROWSER','REPORT_STATUS')
    stamp(report['inspected_at'])
    need(type(report['gaps'])is list and len(report['gaps'])<=8 and all(type(x)is str and re.fullmatch('[A-Z0-9_]{1,80}',x) for x in report['gaps']),'REPORT_GAPS')
    if report['run'] is not None:
        r=report['run'];need(type(r)is dict and set(r)=={'id','expected_start_time','start_time','end_time'},'REPORT_RUN');uid(r['id'])
        for k in ['expected_start_time','start_time','end_time']:stamp(r[k])
    if report['receipt']is not None:uid(report['receipt'])
    need(report['delivery_status']is None or report['delivery_status'] in STATUSES,'REPORT_DELIVERY')
    need(report['publication'] in {'UNVERIFIED','MISSING','INVALID','VALID','EXPIRED'},'REPORT_PUBLICATION')
    for k in ['publication_phase','publication_cause']:
        if k in report:need(type(report[k])is str and re.fullmatch('[A-Z0-9_]{1,80}',report[k]),'REPORT_PUBLICATION_DIAGNOSTIC')
    for k in ['deployed_source_binding','receipt_integrity','pointer_binding']:
        if k in report:need(report[k]=='PASS','REPORT_GATE')
    for k,expected in [('association','UNIQUE_FORECAST_TASK_RECEIPT_INTERNAL_STAGE_ISSUE_AND_ACTIVE_BUNDLE'),('api_binding','VALUES_MODEL_ISSUE_COMPLETION'),('cache_control','no-store')]:
        if k in report:need(report[k]==expected,'REPORT_TEXT')
    if 'features' in report:need(type(report['features'])is int and report['features']==31,'REPORT_FEATURES')
    if 'model' in report:need(type(report['model'])is dict and set(report['model'])=={'release','model_sha256','feature_contract_sha256'} and report['model']['release']=='next24h-hgb-2026-09-21-v1' and all(type(report['model'][k])is str and re.fullmatch('[0-9a-f]{64}',report['model'][k]) for k in ['model_sha256','feature_contract_sha256']),'REPORT_MODEL')
    if 'publication_task_id' in report:uid(report['publication_task_id'])
    if 'api_checked_at' in report:stamp(report['api_checked_at'])
    if 'receipt_hashes' in report:need(set(report['receipt_hashes'])==NAMES-{'integrity.json'} and all(type(x)is str and re.fullmatch('[0-9a-f]{64}',x) for x in report['receipt_hashes'].values()),'REPORT_HASHES')
    if 'bundle_sha256' in report:need(type(report['bundle_sha256'])is str and re.fullmatch('[0-9a-f]{64}',report['bundle_sha256']),'REPORT_HASH')
    for k in ['forecast_http','operations_http']:
        if k in report:need(type(report[k])is int and report[k] in {200,401,403,404,409,500,502,503,504},'REPORT_HTTP')
    if 'api_predictions' in report:need(type(report['api_predictions'])is int and report['api_predictions']in {0,24},'REPORT_COUNT')
    if 'api_state' in report:need(report['api_state']in {'VALID','WITHHELD'},'REPORT_API')
    if 'operations_status' in report:need(report['operations_status']in {'VALID','EXPIRED'},'REPORT_OPERATIONS')
    if 'timing' in report:
        t=report['timing'];need(type(t)is dict and set(t)<= {'issue','expiry','expired_at_inspection','remaining_at_inspection_seconds','publication_time','publication_time_evidence','publication_interval_start','publication_interval_end','completion_to_publication_seconds_bounds','remaining_at_publication_seconds_bounds'},'REPORT_TIMING')
        need(t['publication_time']is None and t['publication_time_evidence']=='NOT_PERSISTED' and type(t['expired_at_inspection'])is bool,'REPORT_TIMING_EVIDENCE')
        for k in ['issue','expiry','publication_interval_start','publication_interval_end']:
            if k in t:stamp(t[k])
        need(type(t['remaining_at_inspection_seconds']) in (float,int) and math.isfinite(t['remaining_at_inspection_seconds']),'REPORT_SECONDS')
        for k in ['completion_to_publication_seconds_bounds','remaining_at_publication_seconds_bounds']:
            if k in t:need(type(t[k])is list and len(t[k])==2 and all(type(x)in (float,int) and math.isfinite(x) for x in t[k]) and t[k][0]<=t[k][1],'REPORT_INTERVAL')
    if report['status']=='PASS':
        need(not report['gaps'] and report['phase']=='COMPLETE' and report.get('delivery_status')=='PUBLISHED' and report.get('pointer_binding')=='PASS' and report.get('api_state')=='VALID' and report.get('api_predictions')==24 and report.get('operations_status')=='VALID','REPORT_PASS_EVIDENCE')
    return report

if __name__=='__main__':
    try:
        report=validate_report(inspect(Remote()));print(json.dumps(report,sort_keys=True,allow_nan=False));raise SystemExit(0 if report['status']=='PASS' else 1)
    except Exception:
        print('{"inspection_failed":true}');raise SystemExit(1)
