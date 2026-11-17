"""Current scoped CSV comparison, explicitly NOT historical reconstruction."""
import csv
import datetime as dt
import hashlib
import io
import json
import math
import statistics
from pathlib import Path

ISSUES=['2026-11-03T14:00:00+00:00','2026-11-03T15:00:00+00:00']
ROOT=Path('/home/ec2-user/Electricity_Trading_Pipeline')

def need(ok,code):
    if not ok:raise ValueError(code)

def time(value):return R['stamp'](value)

def hours(issue,source):return sorted({issue-dt.timedelta(hours=i) for i in range(25)}|({issue-dt.timedelta(hours=168)} if source=='price' else set()))

def analyze(raw,source,withheld_at):
    field='price_eur_mwh' if source=='price' else 'load_mw';issues=[time(x) for x in ISSUES]
    required=set().union(*(set(hours(i,source)) for i in issues));byhour={h:[] for h in required}
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8')))
    need(reader.fieldnames is not None and {'timestamp',field}<=set(reader.fieldnames) and len(reader.fieldnames)==len(set(reader.fieldnames)),'SOURCE_SCHEMA')
    seen=set();resolutions={};scoped_duplicates=set();global_duplicate=False
    for count,row in enumerate(reader,1):
        need(count<=1_000_000 and None not in row,'SOURCE_ROW_BOUND_OR_SCHEMA')
        stamp=time(row['timestamp']);hour=stamp.replace(minute=0,second=0,microsecond=0)
        if stamp in seen:global_duplicate=True;scoped_duplicates.add(stamp) if hour in required else None
        seen.add(stamp)
        resolution=(row.get('source_resolution') or 'PT15M') if source=='price' else 'PT15M'
        if source=='price':
            # Only required 2026 hours use PT15M fallback; legacy source-wide
            # validation uses the SAME declared transition as the bound cleaner.
            resolution=row.get('source_resolution') or ('PT15M' if stamp>=time('2025-09-30T22:00:00+00:00') else 'PT60M')
            need(resolution in {'PT15M','PT60M'},'PRICE_RESOLUTION')
            previous=resolutions.setdefault(hour,resolution);need(previous==resolution,'PRICE_MIXED_RESOLUTION')
        if hour not in required:continue
        try:value=float(row[field])
        except (TypeError,ValueError):value=float('nan')
        byhour[hour].append((stamp,value,resolution));need(len(byhour[hour])<=16,'SCOPED_POINT_BOUND')
    output=[]
    for issue in issues:
        defects=[];usable={};means={}
        for h in hours(issue,source):
            points=byhour[h];resolution=points[0][2] if points else 'PT15M'
            expected={h+dt.timedelta(minutes=15*i) for i in range(4 if resolution=='PT15M' else 1)}
            actual={p[0] for p in points};missing=sorted(expected-actual);invalid=sorted({p[0] for p in points if not math.isfinite(p[1])});offgrid=sorted(actual-expected);duplicates=sorted(actual&scoped_duplicates)
            complete=len(points)==len(expected) and not(missing or invalid or offgrid or duplicates or global_duplicate)
            mean=sum(p[1] for p in points)/len(points) if complete else float('nan')
            complete=complete and math.isfinite(mean);usable[h]=complete;means[h]=mean
            if not complete:defects.append({'hour':h.isoformat(),'missing':[x.isoformat() for x in missing],'invalid':[x.isoformat() for x in invalid],'off_grid':[x.isoformat() for x in offgrid],'duplicates':[x.isoformat() for x in duplicates],'observed_count':len(points),'resolution':resolution})
        fresh=dt.timedelta(0)<=time(withheld_at)-issue<=dt.timedelta(hours=3)
        completed=issue<time(withheld_at).replace(minute=0,second=0,microsecond=0)
        available=usable[issue];history=all(usable.values())
        if history:
            values=[means[issue-dt.timedelta(hours=i)] for i in range(24)]
            try:history=math.isfinite(statistics.mean(values)) and (source!='price' or math.isfinite(statistics.stdev(values)))
            except (OverflowError,ValueError):history=False
        output.append({'issue':issue.isoformat(),'current_hour_usable':available,'current_history_complete':history,'fresh_at_withholding_clock':fresh,'hour_finished_at_withholding':completed,'current_snapshot_eligible_at_recorded_clock':history and fresh and completed,'failed_prerequisites':(['SOURCE_DUPLICATES'] if global_duplicate else [])+([] if available else ['CURRENT_HOUR'])+([] if history else ['LAG_OR_ROLLING_HISTORY'])+([] if fresh else ['FRESHNESS'])+([] if completed else ['HOUR_NOT_FINISHED']),'defects':defects})
    return {'sha256':hashlib.sha256(raw).hexdigest(),'global_duplicate_timestamps':global_duplicate,'candidates':output}

def inspect():
    out={'status':'PARTIAL','read_only':True,'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'historical_state':'NOT_RECONSTRUCTIBLE_FROM_CURRENT_CSV','gaps':[]}
    try:
        historical=W['validate_report'](W['inspect']());out['persisted_evidence']=historical
        need(historical['status']=='PASS' and historical['internal_run_uuid']=='025ef1c9a1da4867a05aecb718028afa' and historical['failed_prerequisite']['gate']=='JOINT_PRICE_LOAD_HOUR','TARGET_WITHHOLDING_BINDING')
        for name,expected in SOURCE_HASHES.items():
            path=ROOT/name;need(hashlib.sha256(READ['capture'](path.parent,path.name,1000,200000)).hexdigest()==expected,'DEPLOYED_SOURCE_DRIFT')
        snapshots={};sources={}
        for source,name in [('price','prices.csv'),('load','load.csv')]:
            p=ROOT/'data/raw/entsoe'/name;started=dt.datetime.now(dt.timezone.utc).isoformat()
            raw=READ['capture'](p.parent,p.name,1000,32*1024**2)
            snapshots[source]=(p,hashlib.sha256(raw).hexdigest());sources[source]=analyze(raw,source,historical['withheld_at'])
            sources[source]['snapshot_started_at']=started;sources[source]['snapshot_finished_at']=dt.datetime.now(dt.timezone.utc).isoformat()
        for source,(p,digest) in snapshots.items():need(hashlib.sha256(READ['capture'](p.parent,p.name,1000,32*1024**2)).hexdigest()==digest,'SOURCE_CHANGED_DURING_INSPECTION')
        out['current_sources']=sources
        out['joint_candidates']=[{'issue':ISSUES[i],'current_snapshot_joint_eligible_at_recorded_clock':all(sources[s]['candidates'][i]['current_snapshot_eligible_at_recorded_clock'] for s in ['price','load']),'recorded_watermark_hour_availability':{s:'NOT_COMPLETE_AT_WITHHOLDING' if time(ISSUES[i])>time(historical['latest_complete_hours'][s]) else 'COMPLETE_HOUR_AT_WATERMARK_CAPTURE' if time(ISSUES[i])==time(historical['latest_complete_hours'][s]) else 'EXACT_HOUR_NOT_PROVEN_BY_WATERMARK' for s in ['price','load']},'arrival_time':'UNKNOWN_NO_PER_OBSERVATION_INGESTION_HISTORY'} for i in range(2)]
        out['status']='PASS';out['gaps']=['HISTORICAL_OBSERVATION_ARRIVAL_TIMES_UNVERIFIED','UPSTREAM_VS_INGESTION_CAUSE_UNVERIFIED']
    except Exception as e:
        text=str(e);code=text if isinstance(e,ValueError) and text.replace('_','').isalnum() and text.upper()==text and len(text)<=80 else 'EVIDENCE_UNVERIFIED'
        out['gaps'].append(code)
    return out

def validate_report(value):
    need(type(value)is dict and set(value)<= {'status','read_only','observed_at','historical_state','gaps','persisted_evidence','current_sources','joint_candidates'} and len(json.dumps(value,allow_nan=False))<=49152,'REPORT_SCHEMA')
    need(value['status'] in {'PASS','PARTIAL'} and value['read_only']is True and value['historical_state']=='NOT_RECONSTRUCTIBLE_FROM_CURRENT_CSV','REPORT_STATUS');time(value['observed_at'])
    need(type(value['gaps'])is list and all(type(g)is str and g.replace('_','').isalnum() and g.upper()==g and len(g)<=80 for g in value['gaps']),'REPORT_GAPS')
    if 'persisted_evidence'in value:W['validate_report'](value['persisted_evidence'])
    # Closed scalar vocabulary: no raw CSV values, paths or unexpected text can exit.
    safe={'price','load','current_sources','joint_candidates'}
    for source,record in value.get('current_sources',{}).items():
        need(source in {'price','load'} and set(record)=={'sha256','global_duplicate_timestamps','candidates','snapshot_started_at','snapshot_finished_at'},'REPORT_SOURCE')
        need(type(record['sha256'])is str and len(record['sha256'])==64 and all(c in '0123456789abcdef' for c in record['sha256']),'REPORT_HASH')
        time(record['snapshot_started_at']);time(record['snapshot_finished_at']);need(type(record['global_duplicate_timestamps'])is bool and len(record['candidates'])==2,'REPORT_CANDIDATES')
        for row in record['candidates']:
            need(set(row)=={'issue','current_hour_usable','current_history_complete','fresh_at_withholding_clock','hour_finished_at_withholding','current_snapshot_eligible_at_recorded_clock','failed_prerequisites','defects'} and row['issue']in ISSUES,'REPORT_CANDIDATE')
            need(all(type(row[k])is bool for k in ['current_hour_usable','current_history_complete','fresh_at_withholding_clock','hour_finished_at_withholding','current_snapshot_eligible_at_recorded_clock']),'REPORT_FLAGS')
            need(set(row['failed_prerequisites'])<= {'SOURCE_DUPLICATES','CURRENT_HOUR','LAG_OR_ROLLING_HISTORY','FRESHNESS','HOUR_NOT_FINISHED'},'REPORT_FAILURE')
            for d in row['defects']:
                need(set(d)=={'hour','missing','invalid','off_grid','duplicates','observed_count','resolution'} and time(d['hour'])in hours(time(row['issue']),source),'REPORT_DEFECT')
                need(type(d['observed_count'])is int and 0<=d['observed_count']<=16 and d['resolution']in {'PT15M','PT60M'},'REPORT_COUNT')
                for k in ['missing','invalid','off_grid','duplicates']:
                    need(type(d[k])is list and len(d[k])<=16,'REPORT_POINTS')
                    for t in d[k]:need(time(d['hour'])<=time(t)<time(d['hour'])+dt.timedelta(hours=1),'REPORT_TIMESTAMP')
    for row in value.get('joint_candidates',[]):
        need(set(row)=={'issue','current_snapshot_joint_eligible_at_recorded_clock','recorded_watermark_hour_availability','arrival_time'} and row['issue']in ISSUES and type(row['current_snapshot_joint_eligible_at_recorded_clock'])is bool,'REPORT_JOINT')
        need(row['arrival_time']=='UNKNOWN_NO_PER_OBSERVATION_INGESTION_HISTORY' and set(row['recorded_watermark_hour_availability'])=={'price','load'} and set(row['recorded_watermark_hour_availability'].values())<= {'NOT_COMPLETE_AT_WITHHOLDING','COMPLETE_HOUR_AT_WATERMARK_CAPTURE','EXACT_HOUR_NOT_PROVEN_BY_WATERMARK'},'REPORT_HISTORICAL')
    if value['status']=='PASS':need(set(value.get('current_sources',{}))=={'price','load'} and len(value.get('joint_candidates',[]))==2,'REPORT_PASS')
    return value

if __name__=='__main__':
    try:
        result=validate_report(inspect());print(json.dumps(result,sort_keys=True,allow_nan=False));raise SystemExit(0 if result['status']=='PASS' else 1)
    except Exception:
        print('{"diagnostic_failed":true}');raise SystemExit(1)
