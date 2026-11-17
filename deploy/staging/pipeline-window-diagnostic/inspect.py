"""Read-only observation of the exact retained deployment guard. No mutations."""
import datetime
import json
import re

REASONS={'SCHEDULE_OR_DEPLOYMENT_MISMATCH','CONCURRENCY_OR_COLLISION_MISMATCH','ACTIVE_FLOW_RUNS','INGESTION_OR_ENGINE_PROCESSES','ACTIVE_CONCURRENCY_SLOTS_OR_UNKNOWN','HOURLY_WINDOW_TOO_SHORT','QUEUED_RUN_TOO_CLOSE'}


def inspect(base):
    responses=[];evaluation=[]
    original_api=base['api'];original_datetime=base['datetime']
    class Clock(original_datetime.datetime):
        @classmethod
        def now(cls,tz=None):
            value=original_datetime.datetime.now(tz);evaluation.append(value);return value
    class TimeModule:
        datetime=Clock
        timezone=original_datetime.timezone
        timedelta=original_datetime.timedelta
    def observed_api(path,body=None):
        value=original_api(path,body);responses.append(value);return value
    try:
        base['api']=observed_api;base['datetime']=TimeModule
        facts,ok=base['pipeline']() # unchanged original guard, no substituted values
        if len(responses)!=3 or len(evaluation)!=1:raise ValueError('observation_shape')
        deployment,active,queued=responses;now=evaluation[0]
        next_slot=now.replace(minute=45,second=0,microsecond=0)
        if next_slot<=now:next_slot+=datetime.timedelta(hours=1)
        delta=next_slot-now;hourly_us=delta.days*86400_000_000+delta.seconds*1_000_000+delta.microseconds
        queued_times=[original_datetime.datetime.fromisoformat(run['expected_start_time'].replace('Z','+00:00')) for run in queued]
        nearest=min(queued_times) if queued_times else None
        queued_ok=all(value>now+datetime.timedelta(minutes=10) for value in queued_times)
        slots=(deployment.get('global_concurrency_limit') or {}).get('active_slots')
        if slots is not None and (type(slots)is not int or not 0<=slots<100000):raise ValueError('slots_shape')
        reasons=[]
        for fail,reason in [(not facts['schedule_match'],'SCHEDULE_OR_DEPLOYMENT_MISMATCH'),(not facts['concurrency_match'],'CONCURRENCY_OR_COLLISION_MISMATCH'),(facts['active_runs']!=0,'ACTIVE_FLOW_RUNS'),(facts['ingestion_processes']!=0,'INGESTION_OR_ENGINE_PROCESSES'),(slots!=0,'ACTIVE_CONCURRENCY_SLOTS_OR_UNKNOWN'),(hourly_us<=600_000_000,'HOURLY_WINDOW_TOO_SHORT'),(not queued_ok,'QUEUED_RUN_TOO_CLOSE')]:
            if fail:reasons.append(reason)
        if ok!=not_reasons(reasons) or facts['safe_window']!=(hourly_us>600_000_000 and queued_ok):raise ValueError('guard_observation_mismatch')
        states={key:0 for key in ('RUNNING','PENDING','CANCELLING','PAUSED','UNKNOWN')}
        for run in active:
            state=run.get('state_type') or (run.get('state') or {}).get('type')
            states[state if state in states else 'UNKNOWN']+=1
        offset=datetime.datetime.now().astimezone().utcoffset()
        return {'status':'PASS' if ok else 'BLOCKED','cause':'OBSERVED_EXISTING_GUARD','evaluation_utc':now.astimezone(datetime.timezone.utc).isoformat(),
                'server_local_utc_offset_seconds':int(offset.total_seconds()),'minimum_window_microseconds':600_000_000,'window_comparison':'STRICTLY_GREATER',
                'next_hourly_slot_utc':next_slot.isoformat(),'hourly_window_microseconds':hourly_us,
                'nearest_returned_queued_utc':None if nearest is None else nearest.astimezone(datetime.timezone.utc).isoformat(),
                'queued_window_pass':queued_ok,'active_slots':slots,'active_state_counts':states,'guard_facts':facts,'failed_conditions':reasons,
                'historical_apply_failure_cause':'UNVERIFIED','service_configuration_drift':'UNVERIFIED'}
    except Exception:
        return {'status':'UNVERIFIED','cause':'EVIDENCE_COLLECTION_FAILED'}
    finally:base['api']=original_api;base['datetime']=original_datetime


def not_reasons(reasons):return not reasons


def validate_report(value):
    if type(value)is not dict:raise ValueError('report')
    if value=={'status':'UNVERIFIED','cause':'EVIDENCE_COLLECTION_FAILED'}:return value
    keys={'status','cause','evaluation_utc','server_local_utc_offset_seconds','minimum_window_microseconds','window_comparison','next_hourly_slot_utc','hourly_window_microseconds','nearest_returned_queued_utc','queued_window_pass','active_slots','active_state_counts','guard_facts','failed_conditions','historical_apply_failure_cause','service_configuration_drift'}
    if set(value)!=keys or value['status'] not in ('PASS','BLOCKED') or value['cause']!='OBSERVED_EXISTING_GUARD':raise ValueError('report_schema')
    for key in ('evaluation_utc','next_hourly_slot_utc','nearest_returned_queued_utc'):
        if value[key] is None and key=='nearest_returned_queued_utc':continue
        if type(value[key])is not str or re.fullmatch(r'[0-9T:.+-]{20,35}',value[key]) is None or not value[key].endswith('+00:00'):raise ValueError('utc')
        datetime.datetime.fromisoformat(value[key])
    if value['minimum_window_microseconds']!=600_000_000 or value['window_comparison']!='STRICTLY_GREATER' or type(value['hourly_window_microseconds'])is not int or not 0<value['hourly_window_microseconds']<=3600_000_000:raise ValueError('threshold')
    if type(value['server_local_utc_offset_seconds'])is not int or not -86400<value['server_local_utc_offset_seconds']<86400:raise ValueError('timezone')
    f=value['guard_facts'];s=value['active_state_counts'];r=value['failed_conditions']
    if type(f)is not dict or set(f)!={'schedule_match','concurrency_match','active_runs','scheduled_runs','ingestion_processes','safe_window'}:raise ValueError('facts')
    for k,v in f.items():
        if k in ('active_runs','scheduled_runs','ingestion_processes'):
            if type(v)is not int or not 0<=v<=32768:raise ValueError('count')
        elif type(v)is not bool:raise ValueError('boolean')
    if type(s)is not dict or set(s)!={'RUNNING','PENDING','CANCELLING','PAUSED','UNKNOWN'} or any(type(x)is not int or not 0<=x<=100 for x in s.values()) or sum(s.values())!=f['active_runs']:raise ValueError('states')
    slots=value['active_slots']
    if slots is not None and (type(slots)is not int or not 0<=slots<100000):raise ValueError('slots')
    if type(value['queued_window_pass'])is not bool or type(r)is not list or len(r)!=len(set(r)) or not set(r)<=REASONS:raise ValueError('reasons')
    expected=[]
    for fail,label in [(not f['schedule_match'],'SCHEDULE_OR_DEPLOYMENT_MISMATCH'),(not f['concurrency_match'],'CONCURRENCY_OR_COLLISION_MISMATCH'),(bool(f['active_runs']),'ACTIVE_FLOW_RUNS'),(bool(f['ingestion_processes']),'INGESTION_OR_ENGINE_PROCESSES'),(slots!=0,'ACTIVE_CONCURRENCY_SLOTS_OR_UNKNOWN'),(value['hourly_window_microseconds']<=600_000_000,'HOURLY_WINDOW_TOO_SHORT'),(not value['queued_window_pass'],'QUEUED_RUN_TOO_CLOSE')]:
        if fail:expected.append(label)
    if r!=expected or (value['status']=='PASS')!=not_reasons(r) or f['safe_window']!=(value['hourly_window_microseconds']>600_000_000 and value['queued_window_pass']):raise ValueError('contradiction')
    if value['historical_apply_failure_cause']!='UNVERIFIED' or value['service_configuration_drift']!='UNVERIFIED':raise ValueError('assurance')
    return value


if __name__=='__main__':
    try:
        result=validate_report(inspect(BASE));print(json.dumps(result,sort_keys=True));raise SystemExit(0 if result['status']=='PASS' else 1)
    except Exception:
        print('{"status":"UNVERIFIED","cause":"EVIDENCE_COLLECTION_FAILED"}');raise SystemExit(1)
