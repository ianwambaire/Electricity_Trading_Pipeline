#!/usr/bin/env python3
"""One approved read-only inspection: exact13 sources, no snapshot/publication/remote writes."""
import csv,datetime as dt,hashlib,io,json,os,re,sqlite3,stat,time
from pathlib import Path
LIMIT=128*1024*1024
end=time.monotonic()+100

def opened(path):
    for p in (path,*path.parents):
        if p.is_symlink():raise ValueError('symlink_path')
    return io.TextIOWrapper(os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|getattr(os,'O_NOATIME',0)),'rb'),encoding='utf-8',newline='')

PLAN=[{'relative_path': 'data/processed/silver_electricity_market_data.csv', 'source': '/home/ec2-user/Electricity_Trading_Pipeline/data/processed/silver_electricity_market_data.csv', 'sha256': 'a9c925c6cb020a467d3152d441d1a181d8ec927af2ebb9cab11eb9e1ad7de3c7', 'bytes': 11618469, 'uid': 1000, 'gid': 1000, 'mode': 420, 'freshness': {'observed_as_of_utc': '2026-10-26T12:28:44.413207+00:00', 'summary': {'status': 'aggregate_only', 'row_count': 68411, 'timestamp_column': 'timestamp', 'invalid_timestamp_rows': 0, 'earliest_aware_utc': '2019-01-01T00:00:00+00:00', 'latest_aware_utc': '2026-10-25T21:00:00+00:00', 'latest_naive_timestamp': None, 'latest_aware_age_hours': 15.48, 'timezone_note': 'Naive times are not assumed UTC; no freshness age derived from them', 'sensitive_header_count': 0, 'stable_during_summary': True, 'sensitivity_review_required': False}}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o644', 'bytes': 11618469, 'mtime_utc': '2026-10-26T12:02:14.709497+00:00', 'regular': True, 'directory': False, 'symlink': False}}, {'relative_path': 'data/features/gold_model_features.csv', 'source': '/home/ec2-user/Electricity_Trading_Pipeline/data/features/gold_model_features.csv', 'sha256': 'c12a041a1d40c47e81e434479e09a99130e8b950a1f7e3ea08d1dfed3448f53f', 'bytes': 20934928, 'uid': 1000, 'gid': 1000, 'mode': 420, 'freshness': {'observed_as_of_utc': '2026-10-26T12:28:44.413207+00:00', 'summary': {'status': 'aggregate_only', 'row_count': 67965, 'timestamp_column': 'timestamp', 'invalid_timestamp_rows': 0, 'earliest_aware_utc': '2019-01-08T00:00:00+00:00', 'latest_aware_utc': '2026-10-23T10:00:00+00:00', 'latest_naive_timestamp': None, 'latest_aware_age_hours': 74.48, 'timezone_note': 'Naive times are not assumed UTC; no freshness age derived from them', 'sensitive_header_count': 0, 'stable_during_summary': True, 'sensitivity_review_required': False}}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o644', 'bytes': 20934928, 'mtime_utc': '2026-10-26T12:02:19.299517+00:00', 'regular': True, 'directory': False, 'symlink': False}}, {'relative_path': 'data/raw/entsoe/prices.csv', 'source': '/home/ec2-user/Electricity_Trading_Pipeline/data/raw/entsoe/prices.csv', 'sha256': '776c20a0ef8135622bdb41f605eda1a0568088a5f21c7604ca96678992325cc6', 'bytes': 3224893, 'uid': 1000, 'gid': 1000, 'mode': 384, 'freshness': {'observed_as_of_utc': '2026-10-26T12:28:44.413207+00:00', 'summary': {'status': 'aggregate_only', 'row_count': 96559, 'timestamp_column': 'timestamp', 'invalid_timestamp_rows': 0, 'earliest_aware_utc': '2019-01-01T00:00:00+00:00', 'latest_aware_utc': '2026-10-26T11:45:00+00:00', 'latest_naive_timestamp': None, 'latest_aware_age_hours': 0.73, 'timezone_note': 'Naive times are not assumed UTC; no freshness age derived from them', 'sensitive_header_count': 0, 'stable_during_summary': True, 'sensitivity_review_required': False}}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o600', 'bytes': 3224893, 'mtime_utc': '2026-10-26T12:00:29.759048+00:00', 'regular': True, 'directory': False, 'symlink': False}}, {'relative_path': 'data/raw/entsoe/load.csv', 'source': '/home/ec2-user/Electricity_Trading_Pipeline/data/raw/entsoe/load.csv', 'sha256': '1d5558249ca70d7e05f05b0045c9aa711190949c1a92a0fbe2338025669871ce', 'bytes': 9695097, 'uid': 1000, 'gid': 1000, 'mode': 384, 'freshness': {'observed_as_of_utc': '2026-10-26T12:28:44.413207+00:00', 'summary': {'status': 'aggregate_only', 'row_count': 274101, 'timestamp_column': 'timestamp', 'invalid_timestamp_rows': 0, 'earliest_aware_utc': '2019-01-01T00:00:00+00:00', 'latest_aware_utc': '2026-10-26T10:15:00+00:00', 'latest_naive_timestamp': None, 'latest_aware_age_hours': 2.23, 'timezone_note': 'Naive times are not assumed UTC; no freshness age derived from them', 'sensitive_header_count': 0, 'stable_during_summary': True, 'sensitivity_review_required': False}}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o600', 'bytes': 9695097, 'mtime_utc': '2026-10-26T12:00:50.699141+00:00', 'regular': True, 'directory': False, 'symlink': False}}, {'relative_path': 'data/raw/entsoe/generation.csv', 'source': '/home/ec2-user/Electricity_Trading_Pipeline/data/raw/entsoe/generation.csv', 'sha256': 'bad847a7103c93521b0d55c34a094f0546a0cb02353e3601638aa0d2305c2271', 'bytes': 41207456, 'uid': 1000, 'gid': 1000, 'mode': 384, 'freshness': {'observed_as_of_utc': '2026-10-26T12:28:44.413207+00:00', 'summary': {'status': 'aggregate_only', 'row_count': 274125, 'timestamp_column': 'timestamp', 'invalid_timestamp_rows': 0, 'earliest_aware_utc': '2019-01-01T00:00:00+00:00', 'latest_aware_utc': '2026-10-26T11:15:00+00:00', 'latest_naive_timestamp': None, 'latest_aware_age_hours': 1.23, 'timezone_note': 'Naive times are not assumed UTC; no freshness age derived from them', 'sensitive_header_count': 0, 'stable_during_summary': True, 'sensitivity_review_required': False}}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o600', 'bytes': 41207456, 'mtime_utc': '2026-10-26T12:01:12.889237+00:00', 'regular': True, 'directory': False, 'symlink': False}}, {'relative_path': 'data/raw/weather/open_meteo_weather.csv', 'source': '/home/ec2-user/Electricity_Trading_Pipeline/data/raw/weather/open_meteo_weather.csv', 'sha256': '996b48c8085240cd505105688e75757d29f7f9e2ebd1acda7b2772724974c039', 'bytes': 3170780, 'uid': 1000, 'gid': 1000, 'mode': 384, 'freshness': {'observed_as_of_utc': '2026-10-26T12:28:44.413207+00:00', 'summary': {'status': 'aggregate_only', 'row_count': 68520, 'timestamp_column': 'timestamp', 'invalid_timestamp_rows': 0, 'earliest_aware_utc': '2019-01-01T00:00:00+00:00', 'latest_aware_utc': '2026-10-25T23:00:00+00:00', 'latest_naive_timestamp': None, 'latest_aware_age_hours': 13.48, 'timezone_note': 'Naive times are not assumed UTC; no freshness age derived from them', 'sensitive_header_count': 0, 'stable_during_summary': True, 'sensitivity_review_required': False}}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o600', 'bytes': 3170780, 'mtime_utc': '2026-10-26T00:00:55.545713+00:00', 'regular': True, 'directory': False, 'symlink': False}}, {'relative_path': 'data/reports/actual_vs_predicted.csv', 'source': '/home/ec2-user/Electricity_Trading_Pipeline/data/reports/actual_vs_predicted.csv', 'sha256': 'aa2a197537fce4fcc853093c3b8ace5e5e570ab8018f09ab1733b834883cf488', 'bytes': 806734, 'uid': 1000, 'gid': 1000, 'mode': 384, 'freshness': {'observed_as_of_utc': '2026-10-26T12:28:44.413207+00:00', 'summary': {'status': 'aggregate_only', 'row_count': 15561, 'timestamp_column': 'timestamp', 'invalid_timestamp_rows': 0, 'earliest_aware_utc': '2025-01-01T00:00:00+00:00', 'latest_aware_utc': '2026-10-23T11:00:00+00:00', 'latest_naive_timestamp': None, 'latest_aware_age_hours': 73.48, 'timezone_note': 'Naive times are not assumed UTC; no freshness age derived from them', 'sensitive_header_count': 0, 'stable_during_summary': True, 'sensitivity_review_required': False}}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o600', 'bytes': 806734, 'mtime_utc': '2026-10-24T00:01:47.528594+00:00', 'regular': True, 'directory': False, 'symlink': False}}, {'relative_path': 'data/reports/detected_anomalies.csv', 'source': '/home/ec2-user/Electricity_Trading_Pipeline/data/reports/detected_anomalies.csv', 'sha256': 'ea5b46f8c0aef021f7e7602a5fcc9770bceb7ec93266ef54f94e46608f2db609', 'bytes': 113133, 'uid': 1000, 'gid': 1000, 'mode': 420, 'freshness': {'observed_as_of_utc': '2026-10-26T12:28:44.413207+00:00', 'summary': {'status': 'aggregate_only', 'row_count': 685, 'timestamp_column': 'timestamp', 'invalid_timestamp_rows': 0, 'earliest_aware_utc': '2021-11-24T16:00:00+00:00', 'latest_aware_utc': '2026-09-22T17:00:00+00:00', 'latest_naive_timestamp': None, 'latest_aware_age_hours': 811.48, 'timezone_note': 'Naive times are not assumed UTC; no freshness age derived from them', 'sensitive_header_count': 0, 'stable_during_summary': True, 'sensitivity_review_required': False}}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o644', 'bytes': 113133, 'mtime_utc': '2026-10-26T12:02:31.539572+00:00', 'regular': True, 'directory': False, 'symlink': False}}, {'relative_path': 'data/reports/final_holdout_metrics.csv', 'source': '/home/ec2-user/Electricity_Trading_Pipeline/data/reports/final_holdout_metrics.csv', 'sha256': '60c1830414df97f68c6a2de67c242305427014d5049bc2945bbd8f29e545d0ba', 'bytes': 540, 'uid': 1000, 'gid': 1000, 'mode': 420, 'freshness': {'observed_as_of_utc': '2026-10-26T12:28:44.413207+00:00', 'summary': {'status': 'aggregate_only', 'row_count': 1, 'timestamp_column': None, 'invalid_timestamp_rows': 0, 'earliest_aware_utc': None, 'latest_aware_utc': None, 'latest_naive_timestamp': None, 'latest_aware_age_hours': None, 'timezone_note': 'Naive times are not assumed UTC; no freshness age derived from them', 'sensitive_header_count': 0, 'stable_during_summary': True, 'sensitivity_review_required': False}}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o644', 'bytes': 540, 'mtime_utc': '2026-09-20T07:01:53.884104+00:00', 'regular': True, 'directory': False, 'symlink': False}}, {'relative_path': 'data/reports/feature_importance.csv', 'source': '/home/ec2-user/Electricity_Trading_Pipeline/data/reports/feature_importance.csv', 'sha256': '935e00ee045f485e607fd0429816747757ad4885d046d8e6bc062361c70fe466', 'bytes': 1671, 'uid': 1000, 'gid': 1000, 'mode': 420, 'freshness': {'observed_as_of_utc': '2026-10-26T12:28:44.413207+00:00', 'summary': {'status': 'aggregate_only', 'row_count': 31, 'timestamp_column': None, 'invalid_timestamp_rows': 0, 'earliest_aware_utc': None, 'latest_aware_utc': None, 'latest_naive_timestamp': None, 'latest_aware_age_hours': None, 'timezone_note': 'Naive times are not assumed UTC; no freshness age derived from them', 'sensitive_header_count': 0, 'stable_during_summary': True, 'sensitivity_review_required': False}}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o644', 'bytes': 1671, 'mtime_utc': '2026-10-26T12:02:34.716923+00:00', 'regular': True, 'directory': False, 'symlink': False}}, {'relative_path': 'artifacts/models/final_model_release_manifest.json', 'source': '/home/ec2-user/Electricity_Trading_Pipeline/artifacts/models/final_model_release_manifest.json', 'sha256': '64939ce5317b5aa6cffb169e1f8b9bbc7304508c496b9bcc71d701bfeb2e7dd6', 'bytes': 2749, 'uid': 1000, 'gid': 1000, 'mode': 420, 'freshness': {'observed_as_of_utc': '2026-10-26T12:28:44.413207+00:00', 'summary': {'status': 'parsed_metadata_only', 'sensitive_key_count': 0, 'internal_path_value_count': 0, 'stable_during_summary': True, 'sensitivity_review_required': False}}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o644', 'bytes': 2749, 'mtime_utc': '2026-10-16T09:21:37.384396+00:00', 'regular': True, 'directory': False, 'symlink': False}}, {'relative_path': 'artifacts/models/releases/next24h/next24h_release_manifest.json', 'source': '/home/ec2-user/Electricity_Trading_Pipeline/artifacts/models/releases/next24h/next24h_release_manifest.json', 'sha256': '1b2d4ce56f178bc236de1bb93d4ce30a09f990d9116dadaa609f86c708131650', 'bytes': 2774, 'uid': 1000, 'gid': 1000, 'mode': 420, 'freshness': {'observed_as_of_utc': '2026-10-26T12:28:44.413207+00:00', 'summary': {'status': 'parsed_metadata_only', 'sensitive_key_count': 0, 'internal_path_value_count': 0, 'stable_during_summary': True, 'sensitivity_review_required': False}}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o644', 'bytes': 2774, 'mtime_utc': '2026-09-21T17:14:07.799179+00:00', 'regular': True, 'directory': False, 'symlink': False}}, {'relative_path': 'database/electricity_trading.db', 'source': '/home/ec2-user/powerflow-recovery-phase5d2-operational/20261026T022230.137446Z/electricity_trading.db', 'sha256': '21fcb0e920ffaf13f214e39720e1176e012086d6ffa7b8a7ed736b6e4ab79690', 'bytes': 12115968, 'uid': 1000, 'gid': 1000, 'mode': 384, 'freshness': {'classification': 'HISTORICAL', 'snapshot_cutoff_utc': '2026-10-26T02:22:00Z', 'accepted_by_owner': True, 'not_current_operational_state': True}, 'previous_metadata': {'exists': True, 'uid': 1000, 'gid': 1000, 'mode': '0o600', 'bytes': 12115968, 'mtime_utc': '2026-10-26T02:22:31.500734+00:00', 'regular': True, 'directory': False, 'symlink': False}}]
COUNTS={'pipeline_runs': 891, 'data_quality_results': 16525, 'operational_incidents': 1485, 'pipeline_stage_timings': 11561}
def metadata(path):
    try:s=path.lstat()
    except FileNotFoundError:return {'exists':False}
    return {'exists':True,'uid':s.st_uid,'gid':s.st_gid,'mode':oct(stat.S_IMODE(s.st_mode)),
            'bytes':s.st_size,'mtime_utc':dt.datetime.fromtimestamp(s.st_mtime,dt.timezone.utc).isoformat(),
            'regular':stat.S_ISREG(s.st_mode),'directory':stat.S_ISDIR(s.st_mode),'symlink':stat.S_ISLNK(s.st_mode)}


def stamp(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns


def stable_hash(path):
    for parent in path.parents:
        if parent.is_symlink():raise ValueError('symlink_ancestor')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|getattr(os,"O_NOATIME",0))
    with os.fdopen(fd,'rb') as handle:
        before=os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size>LIMIT:raise ValueError('file_type_or_size_limit')
        h=hashlib.sha256();size=0
        for block in iter(lambda:handle.read(1024*1024),b''):
            size+=len(block)
            if size>LIMIT:raise ValueError('file_size_limit')
            h.update(block)
        after=os.fstat(handle.fileno())
    return {'sha256':h.hexdigest(),'stable_during_hash':stamp(before)==stamp(after)==stamp(path.stat()),'bytes_hashed':size}


def contents_summary(path):
    """Only schema/time aggregates/sensitivity flags; never return raw rows or values."""
    before=path.stat()
    if path.suffix=='.json':
        if before.st_size>131072:return {'status':'json_size_limit'}
        with opened(path) as h:body=json.load(h);sensitive=0;internal=0
        def walk(value):
            nonlocal sensitive,internal
            if isinstance(value,dict):
                for k,v in value.items():
                    sensitive+=bool(re.search(r'password|secret|token|credential|access.key|email',str(k),re.I));walk(v)
            elif isinstance(value,list):
                for v in value:walk(v)
            elif isinstance(value,str):internal+=value.startswith(('/home/','/Users/','/etc/','/opt/','s3://'))
        walk(body)
        return {'status':'parsed_metadata_only','sensitive_key_count':sensitive,'internal_path_value_count':internal,
                'stable_during_summary':stamp(before)==stamp(path.stat()),'sensitivity_review_required':bool(sensitive or internal)}
    latest_aware=None;earliest_aware=None;latest_naive=None;rows=0;invalid=0
    with opened(path) as handle:
        reader=csv.DictReader(handle);headers=reader.fieldnames or []
        sensitive=sum(bool(re.search(r'password|secret|token|credential|access.key|email|user.id',key,re.I)) for key in headers)
        key=next((k for k in ('timestamp','target_timestamp','datetime','time','target_time','forecast_issue_time') if k in headers),None)
        for row in reader:
            rows+=1
            if rows>1000000:raise ValueError('csv_row_limit')
            if key and row.get(key):
                try:
                    t=dt.datetime.fromisoformat(row[key].replace('Z','+00:00'))
                    if t.tzinfo:
                        t=t.astimezone(dt.timezone.utc)
                        latest_aware=t if latest_aware is None or t>latest_aware else latest_aware
                        earliest_aware=t if earliest_aware is None or t<earliest_aware else earliest_aware
                    else:latest_naive=t if latest_naive is None or t>latest_naive else latest_naive
                except (ValueError,TypeError):invalid+=1
    now=dt.datetime.now(dt.timezone.utc)
    return {'status':'aggregate_only','row_count':rows,'timestamp_column':key,'invalid_timestamp_rows':invalid,
            'earliest_aware_utc':earliest_aware.isoformat() if earliest_aware else None,
            'latest_aware_utc':latest_aware.isoformat() if latest_aware else None,
            'latest_naive_timestamp':latest_naive.isoformat() if latest_naive else None,
            'latest_aware_age_hours':round((now-latest_aware).total_seconds()/3600,2) if latest_aware else None,
            'timezone_note':'Naive times are not assumed UTC; no freshness age derived from them',
            'sensitive_header_count':sensitive,'stable_during_summary':stamp(before)==stamp(path.stat()),
            'sensitivity_review_required':bool(sensitive)}



def main():
    report={'status':'incomplete','read_only':True,'source_count':13,'as_of_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'files':[],'errors':[],
            'limitations':['No old source bytes retained for bytewise diff; pipeline causality is inferred, not proven','Stable file reads do not prove simultaneous cross-file producer transaction','Only approved standalone A1 database opened; live production DB not accessed','No logs, credentials, model binaries or unapproved source paths inspected']}
    if os.geteuid()!=0:raise RuntimeError('root_required_for_noatime_reads')
    for item in PLAN:
        path=Path(item['source']);row={'relative_path':item['relative_path'],'source':str(path),'previous_sha256':item['sha256'],'previous_metadata':item['previous_metadata']}
        try:
            row['metadata']=metadata(path);row.update(stable_hash(path));row['changed']=row['sha256']!=item['sha256']
            if not row['stable_during_hash']:raise ValueError('unstable_source_hash')
            if path.suffix=='.db':
                sides={s:metadata(Path(str(path)+s)) for s in ('-wal','-shm','-journal')}
                if any(x['exists'] for x in sides.values()):raise ValueError('snapshot_sidecar_present')
                if row['changed']:raise ValueError('immutable_A1_changed_do_not_open')
                connection=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True,timeout=0.25)
                connection.set_progress_handler(lambda:1 if time.monotonic()>end else 0,1000)
                try:
                    connection.execute('PRAGMA query_only=ON');connection.execute('BEGIN')
                    integrity=connection.execute('PRAGMA integrity_check').fetchall()
                    fk=connection.execute('PRAGMA foreign_key_check').fetchall()
                    tables={x[0] for x in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    counts={name:connection.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in COUNTS}
                    row['sqlite']={'uri_mode':'ro&immutable=1','integrity_ok':integrity==[('ok',)],'integrity_result_count':len(integrity),'foreign_key_violation_count':len(fk),'required_tables_present':set(COUNTS)<=tables,'counts':counts,'counts_match_A1':counts==COUNTS,'sidecars':sides,'historical_cutoff_utc':'2026-10-26T02:22:00Z'}
                    if integrity!=[('ok',)] or fk or counts!=COUNTS:raise ValueError('snapshot_validation_failed')
                finally:connection.close()
            else:row['summary']=contents_summary(path)
            row['recheck']=stable_hash(path)
            if row['recheck']['sha256']!=row['sha256'] or not row['recheck']['stable_during_hash']:raise ValueError('source_changed_during_validation')
        except Exception as e:
            row['error_type']=type(e).__name__;row['safe_error']=str(e) if isinstance(e,ValueError) and re.fullmatch('[a-z_]+',str(e)) else 'details_withheld'
            report['errors'].append({'relative_path':item['relative_path'],'error_type':row['error_type'],'safe_error':row['safe_error']})
        report['files'].append(row)
        if time.monotonic()>end:
            report['errors'].append({'safe_error':'internal_deadline'});break
    # Re-hash the full approved set after all summaries; no sleeps or retry loops.
    if not report['errors']:
        for row in report['files']:
            current=stable_hash(Path(row['source']))
            row['stable_across_inspection']=current['sha256']==row['sha256'] and current['stable_during_hash']
            if not row['stable_across_inspection']:report['errors'].append({'relative_path':row['relative_path'],'safe_error':'source_set_changed'})
    report['changed_files']=[x['relative_path'] for x in report['files'] if x.get('changed')]
    report['status']='complete' if not report['errors'] and len(report['files'])==13 else 'incomplete'
    report['completed_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
    print(json.dumps(report,indent=2));return 0 if report['status']=='complete' else 1

if __name__=='__main__':raise SystemExit(main())
