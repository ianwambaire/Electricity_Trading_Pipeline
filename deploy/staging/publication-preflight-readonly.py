#!/usr/bin/env python3
"""One fixed-inventory read-only inspection. No publication, backup or live-DB connection."""
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import time

ROOT=Path('/home/ec2-user/Electricity_Trading_Pipeline')
DEST=Path('/srv/powerflow/published')
BACKUP=Path('/home/ec2-user/powerflow-recovery-phase5d2-operational/20261026T022230.137446Z/electricity_trading.db')
BACKUP_SHA='21fcb0e920ffaf13f214e39720e1176e012086d6ffa7b8a7ed736b6e4ab79690'
# Inventory values embedded locally from the reviewed PUBLICATION-INVENTORY.json.
FILES = [{'relative_path': 'data/processed/silver_electricity_market_data.csv', 'local_sha256': '9c806daa13c10ea2c50dd3a8b3390a34d721a395a8919f55e244decf55ed7ea9'}, {'relative_path': 'data/features/gold_model_features.csv', 'local_sha256': '1e5c105b5bda87de79fdc4d7783f92c20a76b4444725518b9a460c685ce40a82'}, {'relative_path': 'data/raw/entsoe/prices.csv', 'local_sha256': 'c80fff2feb1b7f229d8016d8058bb9147d53a65a46d2d51a1117e247fa1336dc'}, {'relative_path': 'data/raw/entsoe/load.csv', 'local_sha256': '4489af456204d3b226563f3805d60fee60efb9ca42b51b488900dd2664c64101'}, {'relative_path': 'data/raw/entsoe/generation.csv', 'local_sha256': 'ff0bbd07d96a60569e05f89a7768ef74ce6606d9777f40f3b159c0b11904b622'}, {'relative_path': 'data/raw/weather/open_meteo_weather.csv', 'local_sha256': '7cdd411aa800388536999ba66c8ecc0dc8aac70dc06e7a25fba0e5e48d28f2af'}, {'relative_path': 'data/reports/actual_vs_predicted.csv', 'local_sha256': 'a7dbc56d78738763354c4936dfd26c12147e647ab107fadf1036fb8dd31bd204'}, {'relative_path': 'data/reports/detected_anomalies.csv', 'local_sha256': 'a117c0f9f6cbeda97e6a40610c03122083f6a86c5ea46c3ba41d44894c4fbf9a'}, {'relative_path': 'data/reports/final_holdout_metrics.csv', 'local_sha256': '60c1830414df97f68c6a2de67c242305427014d5049bc2945bbd8f29e545d0ba'}, {'relative_path': 'data/reports/feature_importance.csv', 'local_sha256': '935e00ee045f485e607fd0429816747757ad4885d046d8e6bc062361c70fe466'}, {'relative_path': 'artifacts/models/final_model_release_manifest.json', 'local_sha256': '64939ce5317b5aa6cffb169e1f8b9bbc7304508c496b9bcc71d701bfeb2e7dd6'}, {'relative_path': 'artifacts/models/releases/next24h/next24h_release_manifest.json', 'local_sha256': '1b2d4ce56f178bc236de1bb93d4ce30a09f990d9116dadaa609f86c708131650'}]
TABLE_COUNTS={'pipeline_runs':891,'data_quality_results':16525,'operational_incidents':1485,'pipeline_stage_timings':11561}
LIMIT=128*1024*1024

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
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
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
        body=json.loads(path.read_bytes());sensitive=0;internal=0
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
    with path.open(encoding='utf-8',newline='') as handle:
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


def readonly_snapshot(path):
    h=stable_hash(path)
    if h['sha256']!=BACKUP_SHA or not h['stable_during_hash']:raise ValueError('snapshot_hash_changed')
    sides={suffix:metadata(Path(str(path)+suffix)) for suffix in ('-wal','-shm','-journal')}
    if any(x['exists'] for x in sides.values()):return {'status':'SKIPPED_SIDECAR_PRESENT','sidecars':sides}
    before=path.stat()
    connection=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True,timeout=0.25)
    connection.set_progress_handler(lambda:1 if time.monotonic()>end else 0,1000)
    try:
        connection.execute('PRAGMA query_only=ON');connection.execute('BEGIN')
        counts={name:connection.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in TABLE_COUNTS}
        connection.execute('SELECT id,run_time,status,message FROM pipeline_runs LIMIT 0')
        connection.execute('SELECT id,check_time,check_name,status FROM data_quality_results LIMIT 0')
        return {'status':'consistent_known_standalone_snapshot_read','uri_mode':'ro&immutable=1','counts':counts,
                'counts_match_A1':counts==TABLE_COUNTS,'same_file_after_query':stamp(before)==stamp(path.stat()),
                'sidecars_after':{suffix:metadata(Path(str(path)+suffix)) for suffix in ('-wal','-shm','-journal')},
                'sensitivity':'Operational records potentially sensitive; only aggregate counts/zero-row schema queried'}
    finally:connection.close()


def main():
    report={'scope':'fixed publication inventory and interpreter facts only','as_of_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'sources':[],'errors':[],'production_writes':False,'limitations':[
            'Stable individual reads do not establish a coherent cross-file publication snapshot',
            'No credentials, environment files, logs, binary models or excluded reports read',
            'Freshness uses timestamp aggregates only; metadata flags do not constitute a complete secrets audit',
            'Live SQLite not opened: a read-only WAL connection may touch SHM state',
            'No effective ProtectHome/unit/BPF enforcement test; mode-bit analysis only']}
    def collect(name,call):
        try:report[name]=call()
        except Exception as error:report['errors'].append({'check':name,'exception_type':type(error).__name__,
            'safe_code':str(error) if isinstance(error,ValueError) and re.fullmatch('[a-z_]+',str(error)) else None})
    if os.geteuid()!=0:raise RuntimeError('noninteractive_sudo_required')
    for item in FILES:
        path=ROOT/item['relative_path'];row={'relative_path':item['relative_path'],'source':str(path),
            'destination':str(DEST/item['relative_path']),'metadata':metadata(path)}
        if row['metadata']['exists']:
            try:
                row.update(stable_hash(path));row['matches_local_inventory']=row['sha256']==item['local_sha256']
                row['readable_as_inspector']=True;row['summary']=contents_summary(path)
            except Exception as error:row['inspection_error_type']=type(error).__name__
        report['sources'].append(row)
    collect('snapshot_metadata',lambda:metadata(BACKUP))
    collect('snapshot_hash',lambda:stable_hash(BACKUP))
    collect('snapshot_read',lambda:readonly_snapshot(BACKUP))
    live=ROOT/'database/electricity_trading.db'
    collect('live_db_metadata_only',lambda:{'database':metadata(live),'sidecars':{s:metadata(Path(str(live)+s)) for s in ('-wal','-shm','-journal')},'connection':'SKIPPED_TO_AVOID_POSSIBLE_SHM_WRITES'})
    def destination():
        info={str(p):metadata(p) for p in (Path('/srv'),Path('/srv/powerflow'),DEST)}
        if any(x.is_symlink() for x in (Path('/srv'),Path('/srv/powerflow'),DEST)):
            return {'paths':info,'status':'SYMLINK_CONFLICT'}
        if not DEST.exists():return {'paths':info,'status':'ABSENT_NO_EXISTING_CONTENTS'}
        if not DEST.is_dir():return {'paths':info,'status':'NOT_DIRECTORY_CONFLICT'}
        # No traversal/reading existing destination contents; count bounded top-level entries only.
        count=0;truncated=False
        with os.scandir(DEST) as entries:
            for _ in entries:
                count+=1
                if count>=100:truncated=True;break
        return {'paths':info,'status':'EXISTING_REQUIRES_REVIEW','top_level_count_bounded':count,'count_truncated':truncated}
    collect('destination',destination)
    def capacity():
        fs=os.statvfs('/srv');m={k:int(v)*1024 for k,v in re.findall(r'(?m)^(MemAvailable|SwapTotal|SwapFree):\s+(\d+) kB',Path('/proc/meminfo').read_text())}
        footprint=sum(row.get('bytes_hashed',0) for row in report['sources'])+report.get('snapshot_metadata',{}).get('bytes',0)
        required=footprint+202856*1024+37472*1024+2*1024**3+1024**3
        return {'available_bytes':fs.f_bavail*fs.f_frsize,'memory_bytes':m,'observed_publication_bytes':footprint,
                'measured_venv_bytes':202856*1024,'measured_wheelhouse_bytes':37472*1024,
                'required_bytes_including_2GiB_reserve_and_1GiB_extra_workspace':required,
                'disk_guard_pass':fs.f_bavail*fs.f_frsize>=required,'memory_768MiB_guard_pass':m['MemAvailable']>=768*1024**2,
                'footprint_complete':all('bytes_hashed' in row for row in report['sources'])}
    collect('capacity',capacity)
    def interpreter():
        code='import sys,sysconfig,platform,json,os; print(json.dumps({"python":platform.python_version(),"abi":sysconfig.get_config_var("SOABI"),"libc":platform.libc_ver(),"real_executable":os.path.realpath(sys.executable),"base_prefix":sys.base_prefix,"stdlib":sysconfig.get_path("stdlib")}))'
        p=subprocess.run([str(ROOT/'.venv-prod/bin/python'),'-I','-S','-B','-c',code],capture_output=True,timeout=10,
            env={'PATH':'/usr/bin:/bin','LANG':'C','PYTHONDONTWRITEBYTECODE':'1'})
        if p.returncode:raise ValueError('interpreter_probe_failed')
        r=json.loads(p.stdout);facts={}
        for key in ('real_executable','base_prefix','stdlib'):
            path=Path(r[key]);ancestors=list(reversed(path.parents))+[path]
            modes={str(x):metadata(x) for x in ancestors}
            facts[key]={'metadata_chain':modes,'hidden_by_ProtectHome':any(r[key]==x or r[key].startswith(x+'/') for x in ('/home','/root','/run/user')),
                        'world_mode_traversable':all(x.get('exists') and not x.get('symlink') and int(x['mode'],8)&1 for name,x in modes.items() if name!=str(path))}
        for key,check in facts.items():
            leaf=check['metadata_chain'][r[key]]
            check['leaf_world_readable']=bool(leaf.get('exists') and int(leaf['mode'],8)&4)
            check['leaf_world_executable']=bool(leaf.get('exists') and int(leaf['mode'],8)&1)
        r['path_checks']=facts;r['effective_systemd_enforcement']='UNVERIFIED'
        return r
    collect('interpreter',interpreter)
    report['status']='complete' if not report['errors'] and not any('inspection_error_type' in r for r in report['sources']) else 'incomplete'
    report['deployment_authorized']=False
    print(json.dumps(report,indent=2));return 0 if report['status']=='complete' else 1

end=time.monotonic()+100
if __name__=='__main__':raise SystemExit(main())
