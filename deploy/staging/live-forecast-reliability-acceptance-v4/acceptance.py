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
def preservation_checks(record):
    before=record['baseline'];after=baseline_preservation()
    need(set(after)=={'production','forecast','store','helper','policy','environment','nginx'},'PRESERVATION_SCHEMA')
    for key in ('helper','policy','environment','nginx'):
        need(after[key]==before[key],'PRESERVATION_DRIFT_'+key.upper())
    # Replay only the two proven pipeline-owned output digests; every actual
    # protected production read/hash/service comparison remains exact.
    outputs=PRES.historical_output_hashes(before['forecast'])
    need(PRES.replay_production(before['production'],outputs)=='MATCH_EXCEPT_PIPELINE_OUTPUTS','PRESERVATION_DRIFT_PRODUCTION')
    old=before['forecast'];new=after['forecast']
    need(set(new)==set(old) and all(new[k]==old[k] for k in old if k not in {'pointer','bundle'}),'PRESERVATION_DRIFT_FORECAST_METADATA')
    need(PRES.store_history(before['store'],record['activated_at'])=='BASELINE_RECONSTRUCTED_SUBSET','PRESERVATION_DRIFT_STORE_RETENTION')
    return after

def stable_components(before,after):
    need(set(before)==set(after),'PRESERVATION_SCHEMA')
    for key in ('production','forecast','store','helper','policy','environment','nginx'):
        need(before[key]==after[key],'READBACK_CHANGED_'+key.upper())

def deployment_checks(record):
    P.idle(0)
    old_trees();tree_state(record,complete=True);G['runtime'](API);P.candidate_environment(True)
    need(P.BACKEND_LINK.resolve(strict=True)==API and P.STATIC_LINK.resolve(strict=True)==STATIC,'ACTIVE_POINTERS')
    need(B['request'](8010,'/health')[0]==B['request'](8010,'/ready')[0]==200,'CANDIDATE_HEALTH')
    code,raw=B['request'](443,'/',tls=True)
    need(code==200 and sha(raw)==C['files']['static/index.html']['sha256'],'STATIC_ROUTING')
    need(P.runtime_closure(Path(record['baseline']['venv']))==record['baseline']['runtime'],'PRESERVATION_DRIFT_RUNTIME')
    snapshot=preservation_checks(record)
    public_operations();return forecast_checks(),snapshot
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
    checks,snapshot=deployment_checks(record);now=dt.datetime.now(dt.timezone.utc)
    # Actual server records, never the scheduled clock alone. Bounded no polling.
    flows=B['api']('/flow_runs/filter',{'deployments':{'id':{'any_':[H.OLD_PLAN.DEPLOYMENT]}},'flow_runs':{'start_time':{'after_':record['activated_at'],'is_null_':False}},'sort':'START_TIME_DESC','limit':20})
    need(type(flows)is list and len(flows)<=20,'RUN_QUERY_BOUND')
    natural=started_natural(flows)
    starts=[H.OP.timestamp(f['start_time']) for f in flows if f.get('start_time')is not None]
    need(starts==sorted(starts,reverse=True),'RUN_ORDER')
    need(len({f['id'] for f in flows})==len(flows),'RUN_IDENTITIES')
    need(natural or len(flows)<20,'NATURAL_SELECTION_TRUNCATED')
    report={'status':'PARTIAL','changed':False,'phase':'READ_ONLY',**checks,'browser':'PENDING_OWNER','analyst_authorization':'PENDING_OWNER'}
    if not natural:
        stable_components(snapshot,baseline_preservation());P.idle(0)
        return {**report,'reason':'NO_POST_ACTIVATION_NATURAL_RUN'}
    flow=max(natural,key=lambda f:H.OP.timestamp(f['start_time']))
    need(H.OP.timestamp(flow['start_time'])>H.OP.timestamp(record['activated_at']),'RUN_BEFORE_ACTIVATION')
    report.update(run_id=flow['id'],run_state=flow.get('state_type'))
    if flow.get('state_type')not in {'COMPLETED','FAILED','CRASHED','CANCELLED'}:
        stable_components(snapshot,baseline_preservation());P.idle(0)
        return {**report,'reason':'NATURAL_RUN_NOT_TERMINAL'}
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
                  pipeline_run_id=evidence['execution']['pipeline_run_id'],inference=evidence['inference']['outcome'],delivery=evidence['delivery']['outcome'],latest_receipt_id=evidence['inference']['receipt_id'],latest_bundle_sha256=evidence['delivery']['bundle_sha256'],scheduled_at=evidence['execution']['scheduled_at'],completed_at=evidence['execution']['completed_at'])
    report.update(active_association(evidence,now,record['baseline']['forecast']))
    if report['operational_status']!='VALID':report['backend_status']='PARTIAL'
    stable_components(snapshot,baseline_preservation());P.idle(0)
    return report

def persisted_issue_time(value):
    producer=types.ModuleType('shared.verified_issue_parser');producer.__package__='shared'
    exec(compile(H.artifact('helper/shared/operational_evidence_producer.py'),'<verified-issue-parser>','exec'),producer.__dict__)
    return producer.persisted_issue_timestamp(value)

def associated_publication(evidence,bundle,digest):
    need(evidence['delivery']['outcome']=='PUBLISHED' and evidence['delivery']['bundle_sha256']==digest,'FORECAST_PUBLICATION_ASSOCIATION')
    need(evidence['delivery']['receipt_id']==evidence['inference']['receipt_id']==bundle['execution']['run_id'],'FORECAST_RECEIPT_ASSOCIATION')
    need(H.OP.timestamp(evidence['inference']['issue_time'])==persisted_issue_time(bundle['forecasts'][0]['issue_time']),'FORECAST_ISSUE_ASSOCIATION')

def active_association(latest,now,baseline_forecast):
    contract=sys.modules['shared.forecast_publication'];availability=available_module()
    try:bundle=availability.read_active(Path('/srv/powerflow/forecast-publications'),now)
    except (contract.ExpiredPublication,contract.MissingPublication):
        return {'backend_status':'PARTIAL','active_publication':'UNAVAILABLE'}
    except contract.Withheld:
        need(False,'ACTIVE_FORECAST_INVALID')
    fingerprint=P.forecast_fingerprint();digest=fingerprint.get('bundle')
    need(fingerprint.get('pointer')=='releases/'+str(digest),'ACTIVE_FORECAST_POINTER')
    need(sha(__import__('json').dumps(bundle,sort_keys=True,separators=(',',':'),allow_nan=False).encode())==digest,'ACTIVE_FORECAST_HASH')
    active=latest
    if latest['delivery']['outcome']=='PUBLISHED':
        need(latest['delivery']['bundle_sha256']==digest,'LATEST_PUBLICATION_POINTER')
    if latest['delivery']['outcome']!='PUBLISHED' or latest['delivery']['bundle_sha256']!=digest:
        # A newer withheld/duplicate run may leave an earlier genuine admitted
        # publication current. Verify that earlier run independently; never
        # scan forecast history or substitute a different pointer for serving.
        matches=[]
        for path in H.entries(P.STORE/'releases',256):
            need(__import__('re').fullmatch('[0-9a-f]{64}',path.name)is not None,'STORE_RELEASE_ID')
            _,raw=P.snap(path/'evidence.json',0,992,0o640);item=H.OP.validate(raw,path.name,now)
            if item['delivery']['outcome']=='PUBLISHED' and item['delivery']['bundle_sha256']==digest:
                matches.append(item)
        need(len(matches)==1,'ACTIVE_NATURAL_ASSOCIATION')
        active=matches[0]
        need(H.OP.timestamp(active['execution']['scheduled_at'])<=H.OP.timestamp(latest['execution']['scheduled_at']),'ACTIVE_RUN_ORDER')
        capture=sys.modules['shared.operational_capture'];flow=capture.query(active['execution']['flow_run_id'])
        need(flow.get('id')==active['execution']['flow_run_id'],'ACTIVE_FLOW_IDENTITY')
        raw,_=capture.capture_terminal(flow['id'],flow['state']['id']);reconstructed=H.OP.decode(raw)
        need(all(active[k]==reconstructed[k] for k in ['execution','inference','delivery','provenance','version']),'ACTIVE_NATURAL_ASSOCIATION')
    associated_publication(active,bundle,digest)
    # Existing capture validates authentic receipt files; bind their reconstructed
    # bundle to the actual pointer, not merely to matching issue/model values.
    capture=sys.modules['shared.operational_capture'];source=capture.Source();run=bundle['execution']['run_id'];H.OP.identifier(run)
    folder=source.root/'data/reports/next24h_inference'/run
    files={n:source.file(folder,n) for n in ('forecast.csv','provenance.json','model.json','evidence.json','integrity.json')}
    producer=sys.modules['shared.operational_evidence_producer'];reconstructed,receipt_hash=producer.receipt_bundle(files,now)
    need(reconstructed==bundle and receipt_hash==digest,'ACTIVE_RECEIPT_INTEGRITY')
    need(P.forecast_fingerprint()==fingerprint,'FORECAST_POINTER_CHANGED')
    issue=contract.time(bundle['forecasts'][0]['issue_time']);expiry=issue+availability.SERVING_HORIZON
    baseline_raw=B['read'](Path('/srv/powerflow/forecast-publications')/baseline_forecast['pointer']/'bundle.json',100000)
    need(sha(baseline_raw)==baseline_forecast['bundle'],'BASELINE_FORECAST_HASH')
    baseline_issue=contract.time(__import__('json').loads(baseline_raw)['forecasts'][0]['issue_time'])
    need(issue>=baseline_issue,'FORECAST_OLDER_THAN_BASELINE')
    targets=[contract.time(row['target_time']) for row in bundle['forecasts']]
    future=[target for target in targets if target>now]
    need(future and now<expiry,'ACTIVE_HORIZON_EXPIRED')
    return {'backend_status':'PASS' if latest['execution']['outcome']=='COMPLETED' and latest['delivery']['outcome']=='PUBLISHED' and active['execution']==latest['execution'] else 'PARTIAL',
            'active_publication':'VERIFIED','receipt_id':run,'bundle_sha256':digest,
            'active_flow_run_id':active['execution']['flow_run_id'],'active_pipeline_run_id':active['execution']['pipeline_run_id'],
            'issue_time':issue.isoformat(),'expires_at':expiry.isoformat(),'refresh_due_at':(issue+contract.MAX_AGE).isoformat(),
            'observed_at':now.isoformat(),'remaining_predictions':len(future),'elapsed_predictions':24-len(future),
            'next_target_time':future[0].isoformat(),'last_target_time':targets[-1].isoformat(),
            'refresh_delayed':now>=issue+contract.MAX_AGE}
