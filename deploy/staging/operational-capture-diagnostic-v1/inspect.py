"""Replay only verified read-only capture; never imports the store or terminal hook."""
import datetime as dt
import re
import stat
import sys

FLOW='01a1b4fd-6f22-7738-8410-7df4e9e73e60'
PIPELINE='3dd2ddfda3b34b1c982a0d7c5342b222'
MODULES={'shared.operational_capture','shared.operational_evidence','shared.operational_evidence_producer','shared.forecast_publication'}
FORBIDDEN={'publish','publish_terminal','deliver_terminal','invoke','notify','main','switch','locked','_publish_locked'}
ERRORS={'InvalidEvidence','Withheld','ExpiredPublication','MissingPublication','ValueError','TypeError','KeyError','AttributeError','NameError','FileNotFoundError','PermissionError','OSError','OperationalError','DatabaseError','JSONDecodeError','TimeoutError'}
# GATES is generated from the exact immutable source closure, never from the host.
GATES={'STORE_METADATA', 'INFERENCE_OUTCOME', 'MISSING_TASK', 'UNEXPECTED_RECEIPT', 'PREFECT_JSON', 'ACTIVE_JOURNAL', 'STAGE_OUTCOME', 'PREFECT_BOUND', 'PREFECT_SCOPE', 'RECEIPT', 'DELIVERY_TASK', 'RECEIPT_BOUND', 'SIZE', 'RECEIPT_INVENTORY', 'TASK_INTERVAL', 'TASK_IDENTITY', 'AMBIGUOUS_TASK', 'NATURAL_RUN_UNVERIFIED', 'SCHEDULE', 'WITHHOLDING', 'FLOW_RETRY_UNVERIFIED', 'SOURCE_METADATA', 'TERMINAL_STATE_CHANGED', 'DATABASE_CHANGED', 'DATABASE_METADATA', 'LINUX_ROOT_REQUIRED', 'TIMESTAMP', 'INTERNAL_ASSOCIATION', 'WITHHELD_TIME', 'FLOW_BOUND', 'RECEIPT_ASSOCIATION', 'RECORD_SCHEMA', 'SOURCE_PATH', 'SCHEMA', 'RECEIPT_INTEGRITY', 'NO_NATURAL_RUN', 'STORE_ANCESTRY', 'NOT_NATURAL', 'SUMMARY_ASSOCIATION', 'PREFECT_SCHEMA', 'IDENTITY', 'NOT_TERMINAL', 'DELIVERY_STATE', 'PROVENANCE', 'EXECUTION_OUTCOME', 'STAGE_TASK_INTERVAL', 'STAGE_INTERVAL', 'AMBIGUOUS_RUN', 'HASH', 'TASK_STATE', 'RECEIPT_IDENTITY', 'STATUS', 'TIMELINE', 'RECORD_BOUND', 'READ_ONLY_SNAPSHOT_REQUIRED', 'INCIDENT_ASSOCIATION', 'SNAPSHOT_UNVERIFIED', 'TASK_FLOW', 'ARGUMENTS', 'ASSOCIATION_UNVERIFIED', 'PREFECT_HTTP', 'SOURCE_CHANGED', 'STABLE_IDENTITY_REQUIRED', 'TASK_BOUND', 'ISSUE_ASSOCIATION', 'INCIDENT_BINDING', 'RECEIPT_TASK', 'RECEIPT_SCHEMA', 'SUMMARY_TIME'}


GATES.update({'TARGET_PIPELINE_IDENTITY','PREFECT_SCOPE','REQUEST_BOUND','READ_ONLY_BOUNDARY','READ_ONLY_CLOSURE','TRACE_ALREADY_ACTIVE'})

def classify(error):
    name=type(error).__name__;result={'exception':name if name in ERRORS else 'UNRECOGNIZED_EXCEPTION'}
    if isinstance(error,OP.InvalidEvidence) and str(error)in GATES:result['gate']=str(error)
    if name in {'OperationalError','DatabaseError'}:
        code=getattr(error,'sqlite_errorcode',None)
        if type(code)is int:result['sqlite_errorcode']=code
    if isinstance(error,OSError) and type(error.errno)is int:result['errno']=error.errno
    return result


class Observation:
    def __init__(self):self.events=[];self.pipeline_verified=False;self.last_stage='START';self.file_id=None
    def trace(self,frame,event,arg):
        module=frame.f_globals.get('__name__')
        if module not in MODULES:return self.trace
        fn=frame.f_code.co_name
        if event=='call':
            PLAN.need(fn not in FORBIDDEN,'READ_ONLY_BOUNDARY')
            if module=='shared.operational_capture' and fn in {'query','snapshot','capture','file','capture_terminal'}:self.last_stage=fn.upper()
        if module=='shared.operational_capture' and fn=='capture' and event in {'line','return','exception'}:
            summary=frame.f_locals.get('summary')
            if isinstance(summary,dict):
                PLAN.need(summary.get('prefect_flow_run_id')==FLOW and summary.get('run_id')==PIPELINE,'TARGET_PIPELINE_IDENTITY')
                self.pipeline_verified=True
        if module=='shared.operational_capture' and fn=='file':
            name=frame.f_locals.get('name');self.file_id=name if name in CAPTURE.NAMES else 'UNAPPROVED_ARTIFACT'
        if event=='exception':
            error=arg[1];item={'module':'shared/'+module.split('.')[1]+'.py','function':fn if re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',fn) else 'GENERATED_EXPRESSION','line':frame.f_lineno,'line_kind':'READONLY_ASSEMBLY' if module=='shared.operational_capture' else 'SOURCE',**classify(error)}
            if module=='shared.operational_capture' and fn in {'file','snapshot'}:
                info=frame.f_locals.get('before')
                if info is not None and isinstance(info,tuple) and hasattr(info,'st_mode'):
                    item['metadata']={'regular':stat.S_ISREG(info.st_mode),'uid':info.st_uid,'gid':info.st_gid,'mode':stat.S_IMODE(info.st_mode),'links':info.st_nlink,'bytes':info.st_size}
            if self.file_id:item['artifact']=self.file_id
            if len(self.events)<96:self.events.append((error,item))
        return self.trace
    def failure(self,error):
        same=[item for identity,item in self.events if identity is error]
        # Earlier specific gates are retained when a wrapper reclassifies an error.
        prior=[item for _,item in self.events if 'gate'in item]
        return {'last_stage':self.last_stage,'failure':classify(error),'propagation':same[-8:],'prior_gates':prior[-8:],'pipeline_association_verified':self.pipeline_verified}


def replay(flow,clock):
    observer=Observation();calls=[]
    def api(identity,tasks=False):
        PLAN.need(identity==FLOW and type(tasks)is bool,'PREFECT_SCOPE')
        calls.append(tasks);PLAN.need(len(calls)<=3,'REQUEST_BOUND')
        return flow if len(calls)==1 else CAPTURE.query(identity,tasks=tasks)
    PLAN.need(not hasattr(CAPTURE,'deliver_terminal') and not hasattr(CAPTURE,'main') and 'shared.operational_evidence_store'not in sys.modules,'READ_ONLY_CLOSURE')
    prior=sys.gettrace();PLAN.need(prior is None,'TRACE_ALREADY_ACTIVE')
    try:
        sys.settrace(observer.trace)
        raw,digest=CAPTURE.capture_terminal(FLOW,flow['state']['id'],api=api,clock=clock)
        return {'capture':'PASS','pipeline_association_verified':observer.pipeline_verified,'evidence_sha256':digest,'captured_bytes':len(raw),'replay_at':clock().isoformat(),'request_count':len(calls)}
    except Exception as error:
        return {'capture':'FAILED','request_count':len(calls),**observer.failure(error)}
    finally:sys.settrace(prior)


def inspect():
    P=PREFLIGHT
    # All installed immutable helper files must still match the reviewed release.
    for key,item in CONFIG['files'].items():
        if key.startswith('helper/'):
            path=__import__('pathlib').Path(item['destination'])
            PLAN.need(P.snap(path,item['uid'],item['gid'],item['mode'])[0]['sha256']==item['sha256'],'HELPER_DRIFT')
    flow=CAPTURE.query(FLOW)
    PLAN.need(flow.get('id')==FLOW and OP.timestamp(flow['expected_start_time'])==OP.timestamp('2026-11-07T08:45:00Z') and flow['state']['type']=='COMPLETED','TARGET_FLOW_IDENTITY')
    OP.identifier(flow['state']['id'])
    now=dt.datetime.now(dt.timezone.utc)
    result=replay(flow,lambda:now)
    return {'status':'PASS','changed':False,'run_id':FLOW,'pipeline_run_id':PIPELINE,'terminal_state':flow['state']['type'],'scheduled_at':flow['expected_start_time'],'completed_at':flow['end_time'],'historical_exception_retained':False,'observations':result}
