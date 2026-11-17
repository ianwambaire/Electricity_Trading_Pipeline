"""Read-only post-natural-run acceptance; never invokes publisher/installer hooks."""
import datetime as dt
import json
import os
from pathlib import Path


def inspect():
    P=PREFLIGHT;need=PLAN.need;now=dt.datetime.now(dt.timezone.utc)
    record=json.loads(P.read(P.CONTROL/'record.json'));PLAN.record_valid(record,CONFIG)
    need(record['phase']=='APPLIED' and record.get('activation_bounds')is not None,'ACTIVATION_NOT_VERIFIED')
    for rel,spec in CONFIG['worker'].items():
        meta,_=P.snap(P.PRODUCTION/rel,1000,1000,0o644);need(meta['sha256']==CONFIG['files']['worker/'+rel]['sha256'],'WORKER_DRIFT')
    need(P.deployment().get('job_variables',{})==record['new_variables'] and PLAN.stable_projection(P.deployment())==record['projection'],'ACTIVATION_DRIFT')
    flows=P.BASE['api']('/flow_runs/filter',{'deployments':{'id':{'any_':[PLAN.DEPLOYMENT]}},'flow_runs':{'state':{'type':{'any_':['COMPLETED','FAILED','CRASHED','CANCELLED']}}},'sort':'EXPECTED_START_TIME_DESC','limit':20})
    flow=PRODUCER.latest_natural(flows,PLAN.DEPLOYMENT,now)
    need(OP.timestamp(flow['expected_start_time'])>=OP.timestamp(record['activation_bounds'][1]),'NO_POST_ACTIVATION_RUN')
    P.safe(P.STORE);need(os.path.lexists(P.STORE/'current'),'NO_OPERATIONAL_PUBLICATION');digest=P.read(P.STORE/'current',66).decode('ascii')
    need(__import__('re').fullmatch('[0-9a-f]{64}\n',digest)is not None,'OPERATIONAL_POINTER')
    digest=digest.strip();release=P.STORE/'releases'/digest;P.safe(release)
    raw=P.read(release/'evidence.json',16385);published=OP.validate(raw,digest,now)
    need(published['execution']['flow_run_id']==flow['id'],'LATEST_RUN_NOT_DELIVERED')
    fresh_raw,_=CAPTURE.capture_terminal(flow['id'],flow['state']['id'])
    fresh=OP.decode(fresh_raw)
    if published['delivery']['outcome']=='PUBLISHED':
        need(P.forecast_fingerprint().get('bundle')==published['delivery']['bundle_sha256'],'FORECAST_POINTER_RECEIPT')
    need(all(fresh[k]==published[k] for k in ['execution','inference','delivery','provenance','version']),'PERSISTED_ASSOCIATION_MISMATCH')
    expected=OP.view(raw,digest,now=now)
    pub=P.http('/api/operations/current');pipeline=P.http('/api/pipeline/current')
    need(pub[0]==pipeline[0]==200 and pub[1]['cache-control']==pipeline[1]['cache-control']=='no-store','CURRENT_HTTP')
    need(pub[2]==pipeline[2]==expected and 'admin' not in pub[2],'CROSS_ENDPOINT_MISMATCH')
    need(P.http('/api/admin/operations/current')[0]==401,'ADMIN_BOUNDARY')
    # Current forecast remains independently selected; receipt publication history
    # cannot establish current eligibility. Normal expiry is explicitly allowed.
    forecast_code,headers,body=P.http('/api/forecast/next24');operations=P.http('/api/operations/summary')
    need(headers['cache-control']=='no-store' and operations[0]==200,'FORECAST_HTTP')
    if forecast_code==200:
        bundle=FORECAST.read_active(Path('/srv/powerflow/forecast-publications'))
        need(body.get('row_count')==24 and len(body.get('forecasts',[]))==24 and operations[2].get('forecast_status')=='VALID','FORECAST_CONSISTENCY')
        for actual,row in zip(body['forecasts'],bundle['forecasts']):
            need(actual['predicted_price_eur_mwh']==row['predicted_price_eur_mwh'] and OP.timestamp(actual['target_time'])==OP.timestamp(row['target_time']) and actual['model_release']==row['model_release'],'FORECAST_VALUES')
    else:need(forecast_code==503 and body=={'detail':{'code':'FORECAST_WITHHELD'}} and operations[2].get('forecast_status')in {'EXPIRED','WITHHELD','MISSING_PUBLICATION'},'FORECAST_WITHHELD')
    need(P.read(P.STORE/'current',66).decode().strip()==digest,'OPERATIONAL_POINTER_CHANGED')
    return {'status':'PARTIAL','reason':'OWNER_ADMIN_AND_REACT_ACCEPTANCE_PENDING' if expected['status']=='VALID' else 'OPERATIONAL_EVIDENCE_NOT_CURRENT','operational_status':expected['status'],
            'evidence_sha256':digest,'natural_run':flow['id'],'execution':published['execution']['outcome'],
            'inference':published['inference']['outcome'],'forecast_delivery':published['delivery']['outcome'],
            'forecast_http':forecast_code,'forecast_status':operations[2].get('forecast_status'),
            'admin_projection_same_source':OP.view(raw,digest,now=now,admin=True).get('evidence_id')==expected['evidence_id'],
            'observed_at':published['observed_at'],'fresh_until':expected['fresh_until'],'changed':False,'historical_fallback':False,'browser':'PENDING_OWNER'}
