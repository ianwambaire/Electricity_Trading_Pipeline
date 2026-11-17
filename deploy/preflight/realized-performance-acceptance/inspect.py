"""Fixed-run inspection; independent evidence sections, stdlib-only remote client."""
import datetime as dt
import hashlib
import http.client
import json
import math
import re
import socket
import ssl
import uuid

FLOW='01a1bc5e-d54b-761c-88df-9d1a6571452c'
PIPELINE='6dc962a38d9a4bd9b05d1b8d1931ec56'
DEPLOYMENT='47e5ef51-26d0-44b6-b119-2c40d0e77397'
SCHEDULED='2026-11-08T18:45:00Z'
MONITOR='Monitor next24h realized forecast errors'
TERMINAL={'COMPLETED','FAILED','CRASHED','CANCELLED'}
STATES=TERMINAL|{'SCHEDULED','PENDING','RUNNING','CANCELLING','PAUSED'}
CLASSES={'PermissionError','FileNotFoundError','ModuleNotFoundError','ImportError','ValueError','TypeError','AttributeError','AssertionError','RuntimeError','OSError','InvalidReport','Withheld','KeyError','JSONDecodeError','ParserError','EmptyDataError','InvalidEvidence'}
REASONS={'Invalid forecast target alignment.':'INVALID_FORECAST_TARGET_ALIGNMENT','Duplicate forecast identity.':'DUPLICATE_FORECAST_IDENTITY','Invalid forecast or observed value.':'INVALID_NUMERIC_INPUT','UTC scoring time required.':'UTC_SCORING_TIME_REQUIRED','REALIZED_REPORT_INVALID':'REALIZED_REPORT_INVALID','Actual hourly price timestamps must be unique.':'DUPLICATE_OBSERVED_HOURS','Observed ENTSO-E prices contain duplicate timestamps.':'DUPLICATE_PRICE_TIMESTAMPS'}
CODES={'REALIZED_REPORT_MISSING','REALIZED_INPUTS_MISSING','REALIZED_REPORT_FAILED','REALIZED_REPORT_INVALID','FORECAST_WITHHELD'}
STAGES={'HOST_GUARD','FLOW','TASKS','MONITORING','LOGS','OPERATIONAL_PUBLICATION','REPORT_PUBLICATION','FORECAST_API','OPERATIONS_API','OPERATIONS_SUMMARY','REALIZED_API','API_CONSISTENCY','REPORT_CONSISTENCY','RECEIPT_RECONSTRUCTION','PROTECTED_STATE'}
ERRORS={'SCHEMA','IDENTITY','TIMESTAMP','STATE','TIMELINE','TRUNCATED','MISSING','AMBIGUOUS','DEPENDENCY_UNVERIFIED','HTTP_STATUS','REDIRECT_BLOCKED','RESPONSE_TOO_LARGE','CONTENT_TYPE','JSON_INVALID','NETWORK_TIMEOUT','TLS_FAILURE','NETWORK_FAILURE','REQUEST_SCOPE','STATE_CONTRADICTION','POINTER_CHANGED','API_MISMATCH','TASK_NOT_TERMINAL','SOURCE_ADVANCED','CONTRACT_INVALID','PUBLICATION_NOT_TARGET','UNVERIFIED_CHECK','OS_ERROR','GUARD_FAILED'}

APPROVED_GATES=set()
OPERATIONS={'TRANSACTION','WINDOW','BACKUPS','INSTALLED_API','INSTALLED_WORKER','ACTIVATION_TIME','PREFECT_IDENTITY','OPERATIONAL_POINTER','REPORT_DOCUMENT','PROTECTED_SNAPSHOT','REPORT_ENVIRONMENT','REPORT_POLICY','FINAL_WINDOW'}
class Rejected(ValueError):
    def __init__(self,code,operation=None,gate=None,cause=None):
        self.code=code if code in ERRORS else'UNVERIFIED_CHECK'
        self.detail={}
        if operation in OPERATIONS:self.detail['operation']=operation
        if gate in APPROVED_GATES:self.detail['gate']=gate
        if cause in CLASSES:self.detail['exception_class']=cause
        super().__init__(self.code)

def need(ok,code='SCHEMA'):
    if not ok:raise Rejected(code)

def uuid_text(value):
    try:need(type(value)is str and str(uuid.UUID(value))==value,'IDENTITY')
    except (ValueError,AttributeError,TypeError):raise Rejected('IDENTITY')from None
    return value

def stamp(value):
    try:
        need(type(value)is str,'TIMESTAMP');parsed=dt.datetime.fromisoformat(value.replace('Z','+00:00'));need(parsed.tzinfo is not None and parsed.utcoffset()==dt.timedelta(0),'TIMESTAMP');return parsed.astimezone(dt.timezone.utc)
    except (ValueError,TypeError,OverflowError):raise Rejected('TIMESTAMP')from None

def utc(value):return None if value is None else stamp(value).isoformat()
def sha(raw):return hashlib.sha256(raw).hexdigest()

def strict_json(raw):
    def pairs(items):
        out={}
        for key,value in items:need(key not in out,'JSON_INVALID');out[key]=value
        return out
    def invalid(_):raise Rejected('JSON_INVALID')
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
    except (ValueError,TypeError,UnicodeError,RecursionError):raise Rejected('JSON_INVALID')from None


def diagnosis(text,symbols):
    need(type(text)is str and len(text)<=131072)
    frames=[]
    for path,line,name in re.findall(r'File ["\']([^"\']+)["\'], line ([0-9]{1,6}), in ([A-Za-z_][A-Za-z_0-9]*)',text):
        for rel,functions in symbols.items():
            if path.endswith('/'+rel)and name in functions:
                frame={'module':rel,'function':name,'line':int(line)}
                if frame not in frames:frames.append(frame)
    need(len(frames)<=32)
    denied=None
    for literal,code in [('powerflow','REPORT_PARENT'),('realized-performance','REPORT_ROOT'),('.publication.lock','PUBLICATION_LOCK'),('report.json','REPORT_DOCUMENT')]:
        if re.search(r'PermissionError[^\n]{0,200}["\']'+re.escape(literal)+r'["\']',text):denied=code
    return {'exception_classes':sorted(c for c in CLASSES if re.search(r'\b'+c+r'(?=[:(])',text)),
            'errno_codes':sorted({int(v)for v in re.findall(r'\[Errno (1|2|5|13|20|30|40|95)\]',text)}),
            'recognized_reasons':sorted(v for k,v in REASONS.items()if k in text),
            'approved_frames':frames,'denied_component':denied,
            'upstream_not_completed':bool(re.search(r'Upstream task run .*did not reach a [\'\"]COMPLETED[\'\"] state',text))}


def request_spec(operation,task=None,window=None):
    # Filter POSTs are read queries. No caller-supplied methods, origins or URLs.
    if operation=='FLOW':return 4200,'GET','/api/flow_runs/'+FLOW,None,524288
    if operation=='TASKS':return 4200,'POST','/api/task_runs/filter',{'flow_runs':{'id':{'any_':[FLOW]}},'limit':100,'offset':0},1048576
    if operation=='LOGS':
        uuid_text(task);need(type(window)is tuple and len(window)==2,'REQUEST_SCOPE')
        a,b=map(stamp,window);need(a<b and(b-a).total_seconds()<=1200,'REQUEST_SCOPE')
        return 4200,'POST','/api/logs/filter',{'logs':{'flow_run_id':{'any_':[FLOW]},'task_run_id':{'any_':[task]},'timestamp':{'after_':window[0],'before_':window[1]}},'limit':50,'offset':0,'sort':'TIMESTAMP_DESC'},1048576
    paths={'FORECAST_API':'/api/forecast/next24','OPERATIONS_API':'/api/operations/current','OPERATIONS_SUMMARY':'/api/operations/summary','REALIZED_API':'/api/forecast/realized-evaluation'}
    need(operation in paths,'REQUEST_SCOPE');return 443,'GET',paths[operation],None,262144


def validation_fields(body):
    # FastAPI validation errors: locations/types only, never msg/input/ctx/body.
    output=[]
    if type(body)is not dict or type(body.get('detail'))is not list:return output
    allowed={'body','path','sort','limit','offset','flow_runs','id','any_','logs','timestamp','flow_run_id','task_run_id','after_','before_'}
    kinds={'missing','enum','extra_forbidden','uuid_parsing','json_invalid','literal_error','int_parsing','greater_than_equal','less_than_equal','value_error'}
    for item in body['detail'][:8]:
        if type(item)is not dict:continue
        loc=item.get('loc');kind=item.get('type')
        if type(loc)is list and len(loc)<=8 and all(type(x)is str and x in allowed or type(x)is int and 0<=x<=100 for x in loc)and kind in kinds:
            output.append({'location':loc,'category':kind})
    return output


class HTTP:
    def __init__(self,connection_factory=None):self.factory=connection_factory;self.calls=set();self.probes=[]
    def get(self,operation,task=None,window=None):
        need(operation not in self.calls,'REQUEST_SCOPE');spec=request_spec(operation,task,window);self.calls.add(operation)
        port,method,path,body,bound=spec
        probe={'endpoint':operation,'method':method,'http_status':None,'response_bytes':0,'error':None,'validation':[]};self.probes.append(probe)
        conn=None
        try:
            if self.factory:conn=self.factory(port)
            elif port==4200:conn=http.client.HTTPConnection('127.0.0.1',4200,timeout=4)
            else:
                conn=http.client.HTTPSConnection('staging.powerflowenergy.dev',timeout=5,context=ssl.create_default_context())
                conn._create_connection=lambda address,timeout,source_address=None:socket.create_connection(('127.0.0.1',443),timeout)
            conn.request(method,path,body=None if body is None else json.dumps(body),headers={'Content-Type':'application/json','Accept':'application/json'})
            response=conn.getresponse();status=response.status;need(type(status)is int and 100<=status<=599)
            probe['http_status']=status;raw=response.read(bound+1);probe['response_bytes']=len(raw)
            need(len(raw)<=bound,'RESPONSE_TOO_LARGE')
            if 300<=status<400:raise Rejected('REDIRECT_BLOCKED')
            content=(response.getheader('Content-Type')or'').split(';')[0].lower();need(content=='application/json','CONTENT_TYPE')
            value=strict_json(raw)
            if port==4200 and status!=200:
                probe['validation']=validation_fields(value);raise Rejected('HTTP_STATUS')
            if port==443 and status not in{200,404,503}:raise Rejected('HTTP_STATUS')
            cache=response.getheader('Cache-Control')
            return status,value,cache=='no-store'
        except Rejected as error:probe['error']=error.code;raise
        except ssl.SSLError:probe['error']='TLS_FAILURE';raise Rejected('TLS_FAILURE')from None
        except (TimeoutError,socket.timeout):probe['error']='NETWORK_TIMEOUT';raise Rejected('NETWORK_TIMEOUT')from None
        except (OSError,http.client.HTTPException):probe['error']='NETWORK_FAILURE';raise Rejected('NETWORK_FAILURE')from None
        finally:
            if conn is not None:conn.close()


def run_state(row):
    need(type(row)is dict and type(row.get('state'))is dict)
    value=row['state'].get('type');need(value in STATES,'STATE')
    need(row.get('state_type')is None or row['state_type']==value,'STATE_CONTRADICTION')
    uuid_text(row['state'].get('id'));stamp(row['state'].get('timestamp'))
    return value


def verified_flow(row):
    need(type(row)is dict and row.get('id')==FLOW and row.get('deployment_id')==DEPLOYMENT and row.get('auto_scheduled')is True,'IDENTITY')
    need(stamp(row.get('expected_start_time'))==stamp(SCHEDULED),'IDENTITY')
    value=run_state(row);need(value in TERMINAL,'TASK_NOT_TERMINAL')
    need(stamp(row.get('start_time'))<=stamp(row.get('end_time')),'TIMELINE')
    return row,{'run_id':FLOW,'state':value,'scheduled_at':utc(row['expected_start_time']),'started_at':utc(row['start_time']),'completed_at':utc(row['end_time'])}


def verified_tasks(rows):
    need(type(rows)is list and len(rows)<100,'TRUNCATED')
    seen=set()
    for row in rows:
        need(type(row)is dict and row.get('flow_run_id')==FLOW,'IDENTITY');identifier=uuid_text(row.get('id'));need(identifier not in seen,'IDENTITY');seen.add(identifier)
    return rows


def task_summaries(rows,symbols):
    prefixes={'INFERENCE':'Generate next24h production forecast','AUTOMATIC_PUBLICATION':'Publish validated staging next24h forecast','MONITORING':MONITOR}
    selected=[]
    for row in rows:
        role=next((role for role,prefix in prefixes.items()if type(row.get('name'))is str and row['name'].startswith(prefix)),None)
        if role is None:continue
        state=run_state(row)
        selected.append({'role':role,'task_id':row['id'],'state':state,'state_timestamp':utc(row['state']['timestamp']),'diagnosis':diagnosis(row['state'].get('message')or'',symbols)})
    return {'received_rows':len(rows),'related_tasks':selected}


def verified_task(rows,flow,symbols):
    rows=verified_tasks(rows)
    found=[r for r in rows if type(r.get('name'))is str and r['name'].startswith(MONITOR)]
    need(len(found)==1,'MISSING'if not found else'AMBIGUOUS');row=found[0];value=run_state(row)
    for key in ['start_time','end_time']:
        if row.get(key)is not None:need(stamp(flow['start_time'])<=stamp(row[key])<=stamp(flow['end_time'])+dt.timedelta(seconds=5),'TIMELINE')
    if row.get('start_time')and row.get('end_time'):need(stamp(row['start_time'])<=stamp(row['end_time']),'TIMELINE')
    d=diagnosis(row['state'].get('message')or'',symbols)
    names={'Completed','Failed','Crashed','Cancelled','NotReady','Pending','Running','Scheduled','AwaitingRetry','Retrying','Cached','RolledBack'}
    summary={'task_id':row['id'],'state':value,'state_name':row['state'].get('name')if row['state'].get('name')in names else'UNRECOGNIZED','state_timestamp':utc(row['state']['timestamp']),'started_at':utc(row.get('start_time')),'completed_at':utc(row.get('end_time')),'diagnosis':d}
    if row.get('start_time')and row.get('end_time'):a,b=stamp(row['start_time']),stamp(row['end_time']);basis='TASK_TIMES'
    else:a,b=stamp(flow['start_time']),stamp(flow['end_time']);basis='FLOW_TIMES_NOT_TASK_TIMES'
    need((b-a).total_seconds()<=1140,'TIMELINE')
    return row,summary,((a-dt.timedelta(seconds=30)).isoformat(),(b+dt.timedelta(seconds=30)).isoformat()),basis


class Inspection:
    def __init__(self,context,http,symbols):self.context=context;self.http=http;self.symbols=symbols;self.sections={};self.internal={}
    def collect(self,name,fn,summary=lambda v:v):
        need(name in STAGES)
        try:
            value=fn();self.sections[name]={'status':'VERIFIED','evidence':summary(value)};self.internal[name]=value;return value
        except Rejected as error:self.sections[name]={'status':'UNVERIFIED','reason':error.code,**error.detail}
        except OSError:self.sections[name]={'status':'UNVERIFIED','reason':'OS_ERROR'}
        except Exception:self.sections[name]={'status':'UNVERIFIED','reason':'UNVERIFIED_CHECK'}
        return None
    def skip(self,name):self.sections[name]={'status':'NOT_CHECKED','reason':'DEPENDENCY_UNVERIFIED'}
    def execute(self):
        if self.collect('HOST_GUARD',self.context.guard)is None:return self.result()
        flow=self.collect('FLOW',lambda:verified_flow(self.http.get('FLOW')[1]),lambda v:v[1])
        task=None;window=None
        if flow is not None:
            rows=self.collect('TASKS',lambda:verified_tasks(self.http.get('TASKS')[1]),lambda v:task_summaries(v,self.symbols))
            if rows is not None:
                selected=self.collect('MONITORING',lambda:verified_task(rows,flow[0],self.symbols),lambda v:v[1])
                if selected is not None:
                    task,_,window,basis=selected
                    def logs():
                        rows=self.http.get('LOGS',task['id'],window)[1];need(type(rows)is list and len(rows)<=50)
                        clean=[]
                        for row in rows:
                            need(type(row)is dict and row.get('flow_run_id')==FLOW and row.get('task_run_id')==task['id'],'IDENTITY')
                            need(stamp(window[0])<=stamp(row.get('timestamp'))<=stamp(window[1]),'TIMELINE')
                            message=row.get('message');d=diagnosis(message,self.symbols)
                            if d['exception_classes']or d['approved_frames']or d['recognized_reasons']or d['upstream_not_completed']:clean.append({'timestamp':utc(row['timestamp']),'diagnosis':d})
                        return{'entries':clean,'limit_reached':len(rows)==50,'window_basis':basis,'window_start':window[0],'window_end':window[1]}
                    self.collect('LOGS',logs)
                else:self.skip('LOGS')
            else:self.skip('MONITORING');self.skip('LOGS')
        else:self.skip('TASKS');self.skip('MONITORING');self.skip('LOGS')
        # These use fixed roots/endpoints, not identifiers obtained from failed
        # sections. A failure never substitutes unrelated evidence as target proof.
        op=self.collect('OPERATIONAL_PUBLICATION',self.context.operational)
        publication=self.collect('REPORT_PUBLICATION',self.context.publication,lambda v:v['summary'])
        bodies={}
        for name in ['FORECAST_API','OPERATIONS_API','OPERATIONS_SUMMARY','REALIZED_API']:
            def get(name=name):
                status,body,no_store=self.http.get(name);need(type(body)is dict);need(no_store,'SCHEMA')
                code=(body.get('detail')or{}).get('code')if type(body.get('detail'))is dict else None
                if status!=200:need(code in CODES,'SCHEMA')
                evidence={'http_status':status,'cache_no_store':no_store,'error_code':code}
                if name=='FORECAST_API'and status==200:
                    predictions=body.get('forecasts');need(type(predictions)is list and len(predictions)==body.get('row_count')==24)
                    for h,row in enumerate(predictions,1):
                        need(type(row)is dict and row.get('horizon_hours')==h)
                        need(stamp(row.get('target_time'))==stamp(row.get('issue_time'))+dt.timedelta(hours=h),'TIMESTAMP')
                        need(type(row.get('predicted_price_eur_mwh'))in{int,float}and math.isfinite(row['predicted_price_eur_mwh']))
                    need(type(body.get('publication'))is dict and body['publication'].get('status')=='VALID')
                    evidence['prediction_count']=len(predictions)
                if name=='OPERATIONS_API'and status==200:need(body.get('status')in{'VALID','STALE','MISSING','INVALID'});evidence['operational_status']=body['status']
                if name=='OPERATIONS_SUMMARY'and status==200:
                    need(body.get('forecast_status')in{'VALID','EXPIRED','MISSING_PUBLICATION','WITHHELD'});evidence['forecast_status']=body['forecast_status']
                if name=='REALIZED_API'and status==200:
                    need(body.get('report_status')in{'VALID','STALE'}and body.get('data_status')in{'AVAILABLE','INSUFFICIENT_DATA'})
                    need(type(body.get('coverage'))is dict);evidence.update(report_status=body['report_status'],data_status=body['data_status'])
                bodies[name]=(status,body);return evidence
            self.collect(name,get)
        if all(k in bodies for k in ['FORECAST_API','OPERATIONS_API','OPERATIONS_SUMMARY']):
            self.collect('API_CONSISTENCY',lambda:self.context.apis(bodies))
        else:self.skip('API_CONSISTENCY')
        if publication is not None and 'REALIZED_API'in bodies:
            self.collect('REPORT_CONSISTENCY',lambda:self.context.consistency(publication,bodies['REALIZED_API'],task))
        else:self.skip('REPORT_CONSISTENCY')
        if publication is not None and task is not None and publication['summary'].get('state')=='READY':
            self.collect('RECEIPT_RECONSTRUCTION',lambda:self.context.reconstruct(publication,task))
        else:self.skip('RECEIPT_RECONSTRUCTION')
        self.collect('PROTECTED_STATE',self.context.protected)
        return self.result()
    def result(self):
        monitor=self.sections.get('MONITORING',{}).get('evidence',{});complete=monitor.get('state')=='COMPLETED'
        essential=['HOST_GUARD','FLOW','TASKS','MONITORING','LOGS','OPERATIONAL_PUBLICATION','REPORT_PUBLICATION','FORECAST_API','OPERATIONS_API','OPERATIONS_SUMMARY','REALIZED_API','API_CONSISTENCY','REPORT_CONSISTENCY','PROTECTED_STATE']
        verified=all(self.sections.get(k,{}).get('status')=='VERIFIED'for k in essential)
        publication=self.sections.get('REPORT_PUBLICATION',{}).get('evidence',{})
        verified=verified and self.sections.get('LOGS',{}).get('evidence',{}).get('limit_reached')is False
        verified=verified and self.sections.get('OPERATIONAL_PUBLICATION',{}).get('evidence',{}).get('target_association')=='MATCH'
        receipt_ok=publication.get('present')is True and publication.get('state')in{'READY','MISSING_INPUTS'}and publication.get('freshness','VALID')=='VALID'and (publication.get('state')!='READY'or self.sections.get('RECEIPT_RECONSTRUCTION',{}).get('status')=='VERIFIED')
        return {'status':'PASS'if verified and complete and receipt_ok else'BLOCKED','changed':False,'inspected_at':dt.datetime.now(dt.timezone.utc).isoformat(),'target_flow_run_id':FLOW,'target_pipeline_run_id':PIPELINE,'sections':self.sections,'http_probes':self.http.probes,'browser_acceptance':'PENDING_OWNER','analyst_authorization':'PENDING_CLOSED'}
