#!/usr/bin/env python3
"""A2 PROPOSAL ONLY. Fixed A1 backup -> one new isolated restore; no cleanup.

Run once through approved SSH stdin with isolated Python and an outer timeout.
Standard library only; never imports application/configuration/recovery code.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import sys
import time

BACKUP_ID = '20261026T022230.137446Z'
BACKUP_DIR = Path('/home/ec2-user/powerflow-recovery-phase5d2-operational') / BACKUP_ID
DESTINATION = Path('/home/ec2-user/powerflow-a2-restore-20261026T022230.137446Z')
PRODUCTION_ROOT = Path('/home/ec2-user/Electricity_Trading_Pipeline')
EXPECTED_SHA256 = '21fcb0e920ffaf13f214e39720e1176e012086d6ffa7b8a7ed736b6e4ab79690'
EXPECTED_COUNTS = {
    'pipeline_runs': 891, 'data_quality_results': 16525,
    'operational_incidents': 1485, 'pipeline_stage_timings': 11561,
}
# name, declared type, NOT NULL, default, PK position: repository schema contract.
EXPECTED_COLUMNS = {
    'pipeline_runs': [('id','INTEGER',0,None,1),('run_time','TEXT',1,None,0),('status','TEXT',1,None,0),('records_processed','INTEGER',0,None,0),('message','TEXT',0,None,0)],
    'data_quality_results': [('id','INTEGER',0,None,1),('check_time','TEXT',1,None,0),('check_name','TEXT',1,None,0),('status','TEXT',1,None,0),('message','TEXT',0,None,0)],
    'operational_incidents': [('id','INTEGER',0,None,1),('timestamp_utc','TEXT',1,None,0),('severity','TEXT',1,None,0),('component','TEXT',1,None,0),('event_type','TEXT',1,None,0),('status','TEXT',1,None,0),('message','TEXT',1,None,0),('details_json','TEXT',0,None,0)],
    'pipeline_stage_timings': [('id','INTEGER',0,None,1),('run_id','TEXT',1,None,0),('stage_name','TEXT',1,None,0),('start_timestamp_utc','TEXT',1,None,0),('end_timestamp_utc','TEXT',1,None,0),('duration_seconds','REAL',1,None,0),('status','TEXT',1,None,0)],
}
# index name: (owning table, ordered (column, descending) keys).
EXPECTED_INDEXES = {
    'idx_pipeline_runs_run_time': ('pipeline_runs', [('run_time',1)]),
    'idx_data_quality_results_check_time': ('data_quality_results', [('check_time',1)]),
    'idx_operational_incidents_time': ('operational_incidents', [('timestamp_utc',1)]),
    'idx_operational_incidents_event': ('operational_incidents', [('component',0),('event_type',0),('id',1)]),
    'idx_pipeline_stage_timings_run': ('pipeline_stage_timings', [('run_id',0),('id',0)]),
    'idx_pipeline_stage_timings_time': ('pipeline_stage_timings', [('start_timestamp_utc',1)]),
}


class Refused(Exception):
    pass


class Deadline(Exception):
    pass


class Interrupted(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Refused(code)


def fingerprint(info):
    # Access time can change from reads; it is deliberately not a content test.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def open_private_input(path, stack):
    require(path.resolve(strict=True) == path, 'input_path_not_canonical')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    stream = stack.enter_context(os.fdopen(fd, 'rb'))
    info = os.fstat(stream.fileno())
    require(stat.S_ISREG(info.st_mode), 'input_not_regular')
    require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0, 'input_permissions')
    return stream, fingerprint(info)


def digest(stream, deadline):
    stream.seek(0)
    result = hashlib.sha256()
    while True:
        require(time.monotonic() < deadline, 'deadline')
        block = stream.read(1024*1024)
        if not block:
            break
        result.update(block)
    return result.hexdigest()


def no_sidecars(path):
    for suffix in ('-wal','-shm','-journal'):
        require(not os.path.lexists(str(path)+suffix), 'backup_sidecar_present')


def readonly(path, deadline, stack):
    connection = sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True, timeout=1)
    stack.callback(connection.close)
    extension_toggle = getattr(connection, 'enable_load_extension', None)
    if extension_toggle is not None:
        extension_toggle(False)
    connection.execute('PRAGMA trusted_schema=OFF')
    connection.execute('PRAGMA temp_store=MEMORY')
    connection.execute('PRAGMA cache_size=-4096')
    connection.execute('PRAGMA query_only=ON')
    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    return connection


def identifier(name):
    return '"'+name.replace('"','""')+'"'


def schema(connection, *, include_triggers=False):
    kinds = "('table','index','view','trigger')" if include_triggers else "('table','index','view')"
    return [dict(zip(('type','name','table','sql'), row)) for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
        "AND type IN "+kinds+" ORDER BY type,name")]


def core_contract(connection, objects):
    tables = sorted(item['name'] for item in objects if item['type']=='table')
    require(set(EXPECTED_COLUMNS).issubset(tables), 'required_table_missing')
    for table, expected in EXPECTED_COLUMNS.items():
        columns = [(r[1], r[2].upper(), r[3], r[4], r[5]) for r in connection.execute('PRAGMA table_info('+identifier(table)+')')]
        require(columns == expected, 'core_columns_mismatch')
    indexes = {item['name']:item for item in objects if item['type']=='index'}
    for name, (table, expected) in EXPECTED_INDEXES.items():
        require(name in indexes and indexes[name]['table']==table, 'core_index_missing')
        keys = [(r[2],r[3]) for r in connection.execute('PRAGMA index_xinfo('+identifier(name)+')') if r[5]]
        require(keys == expected, 'core_index_mismatch')
    return tables


def copy_image(source, destination, expected_bytes, deadline):
    # O_EXCL: never overwrite. Even a partial file remains for approved cleanup.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as target:
        source.seek(0)
        count = 0
        while True:
            require(time.monotonic() < deadline, 'deadline')
            chunk = source.read(1024*1024)
            if not chunk:
                break
            count += len(chunk)
            require(count <= expected_bytes, 'backup_grew_during_copy')
            target.write(chunk)
        target.flush()
        os.fsync(target.fileno())
        require(count == expected_bytes, 'copy_size_mismatch')


def run_restore(backup_dir, destination, expected_sha256, expected_counts, *, limit_seconds=90):
    """Arguments exist for isolated unit fixtures; the CLI exposes NO overrides."""
    started = time.monotonic()
    deadline = started + limit_seconds
    result = {
        'status':'failed', 'stage':'preflight', 'backup_id':BACKUP_ID,
        'destination_created':False, 'original_sha256_verified_before_restore':False,
        'source_backup_and_manifest_unchanged':False,
        'integrity_check':'not_run', 'foreign_key_check':'not_run',
        'foreign_key_violations':None, 'foreign_key_definition_count':None,
        'schema_check':'not_run', 'row_counts':{}, 'counts_match_a1':False,
        'readonly_query_succeeded':False, 'restore_seconds':None,
        'restored_database_bytes':None, 'result_file_written':False,
        'off_host_backup_verified':False, 'full_application_recovery_verified':False,
    }
    old_umask = os.umask(0o077)
    old_alarm = signal.getsignal(signal.SIGALRM)
    old_term = signal.getsignal(signal.SIGTERM)
    def alarm(_signum, _frame):
        raise Deadline()
    def terminate(_signum, _frame):
        raise Interrupted()
    try:
        signal.signal(signal.SIGALRM, alarm)
        signal.signal(signal.SIGTERM, terminate)
        signal.setitimer(signal.ITIMER_REAL, limit_seconds)
        with ExitStack() as stack:
            require(backup_dir.is_absolute() and destination.is_absolute(), 'paths_not_absolute')
            require(backup_dir.resolve(strict=True)==backup_dir, 'backup_path_not_canonical')
            require(destination.parent.resolve(strict=True)==destination.parent, 'destination_parent_not_canonical')
            require(not os.path.lexists(destination), 'destination_exists')
            require(destination!=backup_dir and backup_dir not in destination.parents and destination not in backup_dir.parents, 'destination_overlaps_backup')
            require(destination!=PRODUCTION_ROOT and PRODUCTION_ROOT not in destination.parents and destination not in PRODUCTION_ROOT.parents, 'destination_overlaps_production')
            parent_info = destination.parent.stat()
            require(parent_info.st_uid==os.geteuid() and parent_info.st_mode & 0o022 == 0, 'destination_parent_permissions')
            directory_info = backup_dir.stat()
            require(directory_info.st_uid==os.geteuid() and stat.S_IMODE(directory_info.st_mode) & 0o077 == 0, 'backup_directory_permissions')
            source_path = backup_dir/'electricity_trading.db'
            manifest_path = backup_dir/'manifest.json'
            no_sidecars(source_path)
            source, source_before = open_private_input(source_path, stack)
            manifest_file, manifest_before = open_private_input(manifest_path, stack)
            source_size = os.fstat(source.fileno()).st_size
            require(0 < source_size <= 128*1024*1024, 'backup_size_limit')
            require(0 < os.fstat(manifest_file.fileno()).st_size <= 1024*1024, 'manifest_size_limit')
            manifest_bytes = manifest_file.read(1024*1024+1)
            manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
            manifest = json.loads(manifest_bytes)
            require(type(manifest) is dict and manifest.get('backup_db')=='electricity_trading.db', 'manifest_identity')
            require(manifest.get('sha256')==expected_sha256 and type(manifest.get('file_size_bytes')) is int and manifest['file_size_bytes']==source_size, 'manifest_digest_or_size')
            result['stage'] = 'backup_digest'
            require(digest(source, deadline)==expected_sha256, 'backup_sha256_mismatch')
            result['original_sha256_verified_before_restore'] = True
            result['original_backup_bytes'] = source_size
            original = readonly(source_path, deadline, stack)
            original_schema = schema(original)
            original_all_objects = schema(original, include_triggers=True)
            tables = core_contract(original, original_schema)
            require(manifest.get('schema_objects')==original_schema and manifest.get('tables')==tables, 'manifest_schema_mismatch')
            fs = os.statvfs(destination.parent)
            available, total = fs.f_bavail*fs.f_frsize, fs.f_blocks*fs.f_frsize
            workspace = 3*source_size + 64*1024*1024
            require(available - workspace >= total//4, 'free_space_guard')
            result['workspace_allowance_bytes'] = workspace
            result['stage'] = 'restore_copy'
            destination.mkdir(mode=0o700, parents=False, exist_ok=False)
            result['destination_created'] = True
            restored_path = destination/'restored-electricity_trading.db'
            copy_started = time.monotonic()
            copy_image(source, restored_path, source_size, deadline)
            result['restore_seconds'] = round(time.monotonic()-copy_started, 6)
            restored_file, _ = open_private_input(restored_path, stack)
            result['restored_database_bytes'] = os.fstat(restored_file.fileno()).st_size
            result['restored_sha256'] = digest(restored_file, deadline)
            require(result['restored_sha256']==expected_sha256, 'restored_sha256_mismatch')
            result['stage'] = 'restored_validation'
            restored = readonly(restored_path, deadline, stack)
            integrity = restored.execute('PRAGMA integrity_check').fetchall()
            result['integrity_check'] = 'ok' if integrity==[('ok',)] else 'failed'
            require(result['integrity_check']=='ok', 'restored_integrity_failed')
            try:
                violations = sum(1 for _ in restored.execute('PRAGMA foreign_key_check'))
                result['foreign_key_check'] = 'completed'
                result['foreign_key_violations'] = violations
            except sqlite3.Error:
                result['foreign_key_check'] = 'error'
                raise
            restored_schema = schema(restored)
            core_contract(restored, restored_schema)
            restored_all_objects = schema(restored, include_triggers=True)
            require(restored_schema==original_schema and restored_all_objects==original_all_objects, 'restored_schema_mismatch')
            result['schema_check'] = 'core_contract_and_all_manifest_objects_match'
            result['schema_table_count'] = len(tables)
            result['noninternal_schema_object_count'] = len(restored_all_objects)
            result['foreign_key_definition_count'] = sum(len({row[0] for row in restored.execute('PRAGMA foreign_key_list('+identifier(table)+')')}) for table in tables)
            result['row_counts'] = {table:restored.execute('SELECT COUNT(*) FROM '+identifier(table)).fetchone()[0] for table in EXPECTED_COLUMNS}
            result['counts_match_a1'] = result['row_counts']==expected_counts
            result['readonly_query_succeeded'] = restored.execute('PRAGMA query_only').fetchone()[0]==1
            no_sidecars(source_path)
            no_sidecars(restored_path)
            require(digest(source, deadline)==expected_sha256, 'backup_changed_after_restore')
            manifest_file.seek(0)
            require(hashlib.sha256(manifest_file.read(1024*1024+1)).hexdigest()==manifest_digest, 'manifest_changed_after_restore')
            require(fingerprint(source_path.lstat())==source_before and fingerprint(manifest_path.lstat())==manifest_before, 'input_metadata_changed')
            result['source_backup_and_manifest_unchanged'] = True
            require(result['foreign_key_violations']==0, 'foreign_key_violations')
            require(result['counts_match_a1'], 'a1_row_count_mismatch')
            require(result['readonly_query_succeeded'], 'readonly_query_failed')
            require(stat.S_IMODE(destination.stat().st_mode)==0o700 and stat.S_IMODE(restored_path.stat().st_mode)==0o600, 'restored_permissions')
            result['status'] = 'passed'
            result['stage'] = 'completed'
    except Deadline:
        result['error_code'] = 'timeout'
    except (Interrupted, KeyboardInterrupt):
        result['error_code'] = 'interrupted'
    except Refused as error:
        result['error_code'] = 'timeout' if str(error)=='deadline' else str(error)
    except sqlite3.Error:
        result['error_code'] = 'timeout' if time.monotonic()>=deadline else 'sqlite_validation_error'
    except (OSError, ValueError, TypeError, KeyError):
        result['error_code'] = 'filesystem_or_manifest_failure'
    except Exception:
        result['error_code'] = 'unexpected_failure'
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_alarm)
        signal.signal(signal.SIGTERM, old_term)
        os.umask(old_umask)
    result['total_seconds'] = round(time.monotonic()-started, 6)
    if result['destination_created']:
        # Report only metadata for this attempt's partial/complete output.
        if result['restored_database_bytes'] is None:
            try:
                info = (destination/'restored-electricity_trading.db').lstat()
                if stat.S_ISREG(info.st_mode):
                    result['restored_database_bytes'] = info.st_size
            except OSError:
                pass
        try:
            # New file only. Never replace a prior result, even after failure.
            fd = os.open(destination/'verification.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as report:
                result['result_file_written'] = True
                json.dump(result, report, indent=2)
                report.flush()
                os.fsync(report.fileno())
        except OSError:
            result['status'] = 'failed'
            result['result_file_written'] = False
            result['error_code'] = 'result_record_failure'
    return result


def main():
    if len(sys.argv)!=1:
        print(json.dumps({'status':'failed','error_code':'arguments_not_allowed'}))
        return 1
    result = run_restore(BACKUP_DIR, DESTINATION, EXPECTED_SHA256, EXPECTED_COUNTS)
    print(json.dumps(result, indent=2))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
