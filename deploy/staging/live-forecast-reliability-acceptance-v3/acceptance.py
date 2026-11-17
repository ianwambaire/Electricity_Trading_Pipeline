"""Read-only routed checks and post-natural-run evidence. No auth/secret access."""
import sys
import types

def available_module():
    name='shared.forecast_availability'
    if name not in sys.modules:
        m=types.ModuleType(name);m.__package__='shared';sys.modules[name]=m
        exec(compile(raw_file('api/src/shared/forecast_availability.py'),'<verified-forecast-availability>','exec'),m.__dict__)
    return sys.modules[name]
def forecast_checks():
    contract=sys.modules['shared.forecast_publication'];availability=available_module()
    before=P.forecast_fingerprint()
    code,headers,body=P.http('/api/forecast/next24');ops=P.http('/api/operations/summary')
    need(headers['cache-control']=='no-store' and ops[0]==200 and ops[1]['cache-control']=='no-store','FORECAST_HTTP')
    try:bundle=availability.read_active(Path('/srv/powerflow/forecast-publications'))
    except contract.ExpiredPublication:bundle=None;status='EXPIRED'
    except contract.MissingPublication:bundle=None;status='MISSING_PUBLICATION'
    except contract.Withheld:bundle=None;status='WITHHELD'
    if bundle is None:
        need(code==503 and body=={'detail':{'code':'FORECAST_WITHHELD'}} and ops[2].get('forecast_status')==status,'WITHHELD_CONSISTENCY')
    else:
        issue=contract.time(bundle['forecasts'][0]['issue_time']);p=body.get('publication',{})
        need(code==200 and body.get('row_count')==24 and len(body.get('forecasts',[]))==24,'FORECAST_200')
        need(p.get('status')=='VALID' and p.get('availability_policy')=='ISSUE_HORIZON_V1','AVAILABILITY_POLICY')
        need(contract.time(p['issue_time'])==issue and contract.time(p['expires_at'])==issue+availability.SERVING_HORIZON and contract.time(p['refresh_due_at'])==issue+contract.MAX_AGE,'HORIZON_METADATA')
        need(contract.time(p['completed_at'])==contract.time(bundle['execution']['completed_at']),'EXECUTION_COMPLETION')
        need(ops[2].get('forecast_status')=='VALID' and contract.time(ops[2]['forecast_expires_at'])==contract.time(p['expires_at']) and contract.time(ops[2]['forecast_refresh_due_at'])==contract.time(p['refresh_due_at']),'OPERATIONS_CONSISTENCY')
        for actual,row in zip(body['forecasts'],bundle['forecasts']):
            need(set(actual)==set(row) and actual['predicted_price_eur_mwh']==row['predicted_price_eur_mwh'] and actual['horizon_hours']==row['horizon_hours'] and actual['model_release']==row['model_release'] and all(contract.time(actual[k])==contract.time(row[k]) for k in ['issue_time','target_time']),'FORECAST_VALUES')
        status='VALID'
    need(before==P.forecast_fingerprint(),'FORECAST_POINTER_CHANGED')
    return {'forecast_http':code,'forecast_status':status,'prediction_count':24 if bundle else 0}
def public_operations():
    first=P.http('/api/operations/current');second=P.http('/api/pipeline/current')
    need(first[0]==second[0]==200 and first[1]['cache-control']==second[1]['cache-control']=='no-store' and first[2]==second[2] and 'admin'not in first[2],'PUBLIC_OPERATIONS')
    need(set(first[2])=={'status','evidence_id','observed_at','scheduled_at','fresh_until','forecast_eligibility','current_execution'},'PUBLIC_FIELD_SCOPE')
    execution=first[2]['current_execution']
    need(execution is None or set(execution)=={'scheduled_at','started_at','completed_at','execution_outcome','inference_outcome','publication_outcome','source'},'PUBLIC_EXECUTION_SCOPE')
    need(P.http('/api/admin/operations/current')[0]==401,'ANONYMOUS_ADMIN_BOUNDARY')
    return first[2]
def deployment_checks(record):
    old_trees();tree_state(record,complete=True);G['runtime'](API);P.candidate_environment(True)
    need(P.BACKEND_LINK.resolve(strict=True)==API and P.STATIC_LINK.resolve(strict=True)==STATIC,'ACTIVE_POINTERS')
    need(B['request'](8010,'/health')[0]==B['request'](8010,'/ready')[0]==200,'CANDIDATE_HEALTH')
    code,raw=B['request'](443,'/',tls=True)
    need(code==200 and sha(raw)==C['files']['static/index.html']['sha256'],'STATIC_ROUTING')
    same({k:v for k,v in record['baseline'].items() if k not in {'venv','runtime'}},baseline_preservation())
    need(P.runtime_closure(Path(record['baseline']['venv']))==record['baseline']['runtime'],'RUNTIME_CHANGED')
    public_operations();return forecast_checks()
def started_natural(flows):
    """Prefect start-time filters coalesce NULL start_time to expected_start_time.

    Ignore only explicitly unstarted scheduled records; never fabricate a start
    timestamp or treat a malformed terminal record as an absent natural run.
    """
    result=[]
    for flow in flows:
        need(type(flow)is dict,'RUN_SCHEMA')
        if flow.get('auto_scheduled')is not True or flow.get('deployment_id')!=H.OLD_PLAN.DEPLOYMENT:
            continue
        if flow.get('start_time')is None:
            need(flow.get('state_type')=='SCHEDULED','NATURAL_START_MISSING')
            continue
        H.OP.timestamp(flow['start_time'])
        result.append(flow)
    return result
def accept_report():
    record=load_record();need(record['phase']=='APPLIED' and record['activated_at'],'TRANSACTION_NOT_APPLIED');verified_backups(record)
    checks=deployment_checks(record);now=dt.datetime.now(dt.timezone.utc)
    # Actual server records, never the scheduled clock alone. Bounded no polling.
    flows=B['api']('/flow_runs/filter',{'deployments':{'id':{'any_':[H.OLD_PLAN.DEPLOYMENT]}},'flow_runs':{'start_time':{'after_':record['activated_at'],'is_null_':False}},'sort':'START_TIME_DESC','limit':20})
    need(type(flows)is list and len(flows)<20,'RUN_QUERY_BOUND')
    natural=started_natural(flows)
    report={'status':'PARTIAL','changed':False,'phase':'READ_ONLY',**checks,'browser':'PENDING_OWNER','analyst_authorization':'PENDING_OWNER'}
    if not natural:return {**report,'reason':'NO_POST_ACTIVATION_NATURAL_RUN'}
    flow=max(natural,key=lambda f:H.OP.timestamp(f['start_time']))
    need(H.OP.timestamp(flow['start_time'])>H.OP.timestamp(record['activated_at']),'RUN_BEFORE_ACTIVATION')
    report.update(run_id=flow['id'],run_state=flow.get('state_type'))
    if flow.get('state_type')not in {'COMPLETED','FAILED','CRASHED','CANCELLED'}:return {**report,'reason':'NATURAL_RUN_NOT_TERMINAL'}
    # Reuse V2's corrected, verified association producer, not the original V1
    # timestamp parser. Only capture_terminal's read-only subset was assembled.
    producer=types.ModuleType('shared.acceptance_producer');producer.__package__='shared'
    exec(compile(H.artifact('helper/shared/operational_evidence_producer.py'),'<verified-v2-producer>','exec'),producer.__dict__)
    capture=sys.modules['shared.operational_capture'];capture.from_snapshot=producer.from_snapshot
    raw,_=capture.capture_terminal(flow['id'],flow['state']['id']);reconstructed=H.OP.decode(raw)
    digest=P.snap(P.STORE/'current',0,992,0o640)[1].decode().strip()
    need(__import__('re').fullmatch('[0-9a-f]{64}',digest)is not None,'OPERATIONAL_POINTER')
    committed=P.snap(P.STORE/'releases'/digest/'evidence.json',0,992,0o640)[1];evidence=H.OP.validate(committed,digest,now)
    need(all(evidence[k]==reconstructed[k] for k in ['execution','inference','delivery','provenance','version']),'NATURAL_RUN_ASSOCIATION')
    need(public_operations()==H.OP.view(committed,digest,now=now),'OPERATIONAL_HTTP_ASSOCIATION')
    need(P.snap(P.STORE/'current',0,992,0o640)[1].decode().strip()==digest,'OPERATIONAL_POINTER_CHANGED')
    report.update(reason='OWNER_BROWSER_AND_ANALYST_AUTHORIZATION_PENDING',operational_status=H.OP.view(committed,digest,now=now)['status'],evidence_sha256=digest,
                  pipeline_run_id=evidence['execution']['pipeline_run_id'],inference=evidence['inference']['outcome'],delivery=evidence['delivery']['outcome'])
    return report
