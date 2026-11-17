"""A2 preparation: disposable synthetic SQLite images, never production paths/SSH."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import time
from types import SimpleNamespace

import pytest
from operational_recovery import sqlite_schema_objects, sqlite_table_names

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('a2_proposal', ROOT/'deploy/remediation/restore-operational-sqlite.py')
a2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a2)


def refresh_manifest(directory):
    database = directory/'electricity_trading.db'
    with sqlite3.connect(database) as db:
        objects, tables = sqlite_schema_objects(db), sqlite_table_names(db)
    checksum = hashlib.sha256(database.read_bytes()).hexdigest()
    manifest = {'backup_db':database.name, 'sha256':checksum, 'file_size_bytes':database.stat().st_size,
                'tables':tables, 'schema_objects':objects}
    (directory/'manifest.json').write_text(json.dumps(manifest))
    (directory/'manifest.json').chmod(0o600)
    database.chmod(0o600)
    return checksum


@pytest.fixture
def image(tmp_path):
    directory = (tmp_path/'synthetic-a1').resolve()
    directory.mkdir(mode=0o700)
    with sqlite3.connect(directory/'electricity_trading.db') as db:
        db.executescript((ROOT/'database/schema.sql').read_text())
        counts = a2.EXPECTED_COUNTS
        db.executemany('INSERT INTO pipeline_runs(run_time,status,records_processed,message) VALUES(?,?,?,?)',
                       [('2026-01-01T00:00:00Z','SUCCESS',1,'Fixture')]*counts['pipeline_runs'])
        db.executemany('INSERT INTO data_quality_results(check_time,check_name,status,message) VALUES(?,?,?,?)',
                       [('2026-01-01T00:00:00Z','fixture','PASSED','Fixture')]*counts['data_quality_results'])
        db.executemany('INSERT INTO operational_incidents(timestamp_utc,severity,component,event_type,status,message) VALUES(?,?,?,?,?,?)',
                       [('2026-01-01T00:00:00Z','INFO','Fixture','fixture','CLOSED','Fixture')]*counts['operational_incidents'])
        db.executemany('INSERT INTO pipeline_stage_timings(run_id,stage_name,start_timestamp_utc,end_timestamp_utc,duration_seconds,status) VALUES(?,?,?,?,?,?)',
                       [('fixture','fixture','2026-01-01T00:00:00Z','2026-01-01T00:00:01Z',1,'SUCCESS')]*counts['pipeline_stage_timings'])
    checksum = refresh_manifest(directory)
    return directory, (tmp_path/'new-isolated').resolve(), checksum


def execute(image, **kwargs):
    source, destination, checksum = image
    return a2.run_restore(source, destination, checksum, dict(a2.EXPECTED_COUNTS), **kwargs)


def test_full_fixture_restore_readonly_integrity_schema_counts_and_no_input_changes(image):
    source, destination, checksum = image
    before = {p.name:p.read_bytes() for p in source.iterdir()}
    result = execute(image)
    assert result['status']=='passed', result
    assert result['original_sha256_verified_before_restore']
    assert result['source_backup_and_manifest_unchanged']
    assert result['restored_sha256']==checksum
    assert result['restored_database_bytes']==(source/'electricity_trading.db').stat().st_size
    assert result['integrity_check']=='ok' and result['foreign_key_check']=='completed'
    assert result['foreign_key_violations']==0 and result['foreign_key_definition_count']==0
    assert result['counts_match_a1'] and result['row_counts']==a2.EXPECTED_COUNTS
    assert result['readonly_query_succeeded'] and result['restore_seconds']>=0
    assert result['schema_check']=='core_contract_and_all_manifest_objects_match'
    assert result['result_file_written']
    assert result['off_host_backup_verified'] is False
    assert result['full_application_recovery_verified'] is False
    assert {p.name:p.read_bytes() for p in source.iterdir()}==before
    assert stat.S_IMODE(destination.stat().st_mode)==0o700
    for path in destination.iterdir():assert stat.S_IMODE(path.stat().st_mode)==0o600
    assert json.loads((destination/'verification.json').read_text())==result
    uri=(destination/'restored-electricity_trading.db').as_uri()+'?mode=ro&immutable=1'
    with sqlite3.connect(uri,uri=True) as db:
        with pytest.raises(sqlite3.OperationalError):db.execute('DELETE FROM pipeline_runs')


@pytest.mark.parametrize('kind',['directory','file','symlink'])
def test_existing_destinations_are_never_overwritten_or_cleaned(image,kind):
    source,destination,_=image
    if kind=='directory':destination.mkdir();(destination/'keep.txt').write_text('keep')
    elif kind=='file':destination.write_text('keep')
    else:destination.symlink_to(source,target_is_directory=True)
    result=execute(image)
    assert result['status']=='failed' and result['error_code']=='destination_exists'
    assert result['destination_created'] is False
    assert os.path.lexists(destination)
    if kind=='directory':assert (destination/'keep.txt').read_text()=='keep'
    elif kind=='file':assert destination.read_text()=='keep'
    else:assert destination.is_symlink()


def test_corrupt_original_digest_refuses_before_destination_creation(image):
    source,destination,_=image
    with (source/'electricity_trading.db').open('ab') as f:f.write(b'corrupt')
    # Preserve manifest size agreement to exercise actual digest comparison.
    p=source/'manifest.json';m=json.loads(p.read_text());m['file_size_bytes']=(source/'electricity_trading.db').stat().st_size;p.write_text(json.dumps(m))
    result=execute(image)
    assert result['error_code']=='backup_sha256_mismatch'
    assert not destination.exists()


def test_manifest_schema_mismatch_and_size_mismatch_are_not_silently_accepted(image):
    source,destination,_=image
    p=source/'manifest.json';m=json.loads(p.read_text());m['schema_objects']=[];p.write_text(json.dumps(m))
    assert execute(image)['error_code']=='manifest_schema_mismatch'
    assert not destination.exists()
    m['file_size_bytes']+=1;p.write_text(json.dumps(m))
    assert execute(image)['error_code']=='manifest_digest_or_size'


@pytest.mark.parametrize('suffix',['-wal','-shm','-journal'])
def test_unexpected_backup_sidecar_stops_without_checkpoint_or_delete(image,suffix):
    source,destination,_=image
    sidecar=source/('electricity_trading.db'+suffix);sidecar.write_bytes(b'fixture')
    result=execute(image)
    assert result['error_code']=='backup_sidecar_present'
    assert sidecar.read_bytes()==b'fixture' and not destination.exists()


@pytest.mark.parametrize('change',['column','index'])
def test_reviewed_core_schema_is_enforced_without_migration(image,change):
    source,destination,_=image
    with sqlite3.connect(source/'electricity_trading.db') as db:
        db.execute('ALTER TABLE pipeline_runs RENAME COLUMN message TO other_message' if change=='column' else 'DROP INDEX idx_pipeline_runs_run_time')
    changed=(source,destination,refresh_manifest(source))
    result=execute(changed)
    assert result['error_code']==('core_columns_mismatch' if change=='column' else 'core_index_missing')
    assert not destination.exists()


def test_insufficient_space_creates_no_destination(image,monkeypatch):
    monkeypatch.setattr(a2.os,'statvfs',lambda _:SimpleNamespace(f_bavail=1,f_frsize=4096,f_blocks=1000000))
    result=execute(image)
    assert result['error_code']=='free_space_guard' and not image[1].exists()


def test_fk_violations_are_separate_and_all_failed_artifacts_are_preserved(image):
    source,destination,_=image
    with sqlite3.connect(source/'electricity_trading.db') as db:
        db.executescript('CREATE TABLE fixture_parent(id INTEGER PRIMARY KEY); CREATE TABLE fixture_child(id INTEGER PRIMARY KEY,parent INTEGER REFERENCES fixture_parent(id)); INSERT INTO fixture_child VALUES(1,99);')
    changed=(source,destination,refresh_manifest(source))
    result=execute(changed)
    assert result['status']=='failed' and result['error_code']=='foreign_key_violations'
    assert result['integrity_check']=='ok' and result['foreign_key_violations']==1
    assert result['foreign_key_definition_count']==1 and result['counts_match_a1']
    assert (destination/'restored-electricity_trading.db').is_file()
    assert (destination/'verification.json').is_file()


def test_a1_count_mismatch_fails_with_aggregate_evidence_not_row_values(image):
    source,destination,checksum=image
    counts=dict(a2.EXPECTED_COUNTS);counts['pipeline_runs']+=1
    result=a2.run_restore(source,destination,checksum,counts)
    assert result['error_code']=='a1_row_count_mismatch'
    assert result['row_counts']==a2.EXPECTED_COUNTS
    assert (destination/'verification.json').is_file()


def test_timeout_preserves_new_directory_and_restores_signal_handlers(image,monkeypatch):
    old=signal.getsignal(signal.SIGALRM)
    monkeypatch.setattr(a2,'copy_image',lambda *_:time.sleep(1))
    result=execute(image,limit_seconds=0.1)
    assert result['error_code']=='timeout'
    assert result['destination_created'] and (image[1]/'verification.json').exists()
    assert signal.getsignal(signal.SIGALRM)==old
    assert result['total_seconds']<1


def test_partial_copy_error_never_deletes_artifacts(image,monkeypatch):
    def partial(_source,destination,*_):
        destination.write_bytes(b'partial');destination.chmod(0o600)
        raise OSError('sensitive fixture detail must not surface')
    monkeypatch.setattr(a2,'copy_image',partial)
    result=execute(image)
    assert result['status']=='failed'
    assert (image[1]/'restored-electricity_trading.db').read_bytes()==b'partial'
    assert 'sensitive fixture detail' not in json.dumps(result)
    assert (image[1]/'verification.json').exists()


def test_additional_legacy_tables_are_preserved_without_misreporting_scope(image):
    source,destination,_=image
    with sqlite3.connect(source/'electricity_trading.db') as db:
        db.execute('CREATE TABLE legacy_fixture(id INTEGER PRIMARY KEY,payload TEXT)')
        db.execute("INSERT INTO legacy_fixture VALUES(1,'Fixture only')")
    changed=(source,destination,refresh_manifest(source))
    result=execute(changed)
    assert result['status']=='passed' and result['schema_table_count']==5
    assert result['restored_sha256']==changed[2]
    assert 'Fixture only' not in json.dumps(result)


@pytest.mark.parametrize('pragma',['integrity','foreign_key'])
def test_validation_errors_do_not_become_zero_violations_or_delete_outputs(image,monkeypatch,pragma):
    original=a2.readonly
    class Proxy:
        def __init__(self,connection):self.connection=connection
        def execute(self,sql,*args):
            if pragma=='integrity' and sql=='PRAGMA integrity_check':
                return SimpleNamespace(fetchall=lambda:[('sensitive fixture page details',)])
            if pragma=='foreign_key' and sql=='PRAGMA foreign_key_check':
                raise sqlite3.OperationalError('sensitive fixture FK details')
            return self.connection.execute(sql,*args)
    def changed(path,*args):
        connection=original(path,*args)
        return Proxy(connection) if path.name=='restored-electricity_trading.db' else connection
    monkeypatch.setattr(a2,'readonly',changed)
    result=execute(image)
    assert result['status']=='failed'
    assert result['foreign_key_violations'] is None
    assert result['foreign_key_check']==('not_run' if pragma=='integrity' else 'error')
    assert 'sensitive fixture' not in json.dumps(result)
    assert (image[1]/'restored-electricity_trading.db').exists()


def test_cli_runs_with_isolated_stdlib_and_rejects_any_override_before_reads():
    import subprocess
    import sys
    result=subprocess.run([sys.executable,'-I','-S','-B',str(ROOT/'deploy/remediation/restore-operational-sqlite.py'),'--destination','/never-read'],capture_output=True,text=True)
    assert result.returncode==1
    assert json.loads(result.stdout)=={'status':'failed','error_code':'arguments_not_allowed'}
    assert not result.stderr


def test_source_size_and_input_modes_are_guarded_before_restore(image):
    source,destination,_=image
    (source/'manifest.json').chmod(0o644)
    assert execute(image)['error_code']=='input_permissions'
    assert not destination.exists()
    (source/'manifest.json').chmod(0o600)
    with (source/'electricity_trading.db').open('r+b') as db:db.truncate(129*1024*1024)
    assert execute(image)['error_code']=='backup_size_limit'
    assert not destination.exists()


def test_triggers_are_preserved_and_compared_without_execution(image):
    source,destination,_=image
    with sqlite3.connect(source/'electricity_trading.db') as db:
        db.execute("CREATE TRIGGER fixture_no_writes AFTER INSERT ON pipeline_runs BEGIN UPDATE pipeline_runs SET message='must never run in A2'; END")
    changed=(source,destination,refresh_manifest(source))
    result=execute(changed)
    assert result['status']=='passed' and result['row_counts']==a2.EXPECTED_COUNTS
    assert result['noninternal_schema_object_count']==11
    assert result['source_backup_and_manifest_unchanged']


@pytest.mark.parametrize('exception',[a2.Interrupted,KeyboardInterrupt])
def test_interrupted_attempt_is_retained_and_sanitized(image,monkeypatch,exception):
    def interrupt(*_):raise exception()
    monkeypatch.setattr(a2,'copy_image',interrupt)
    result=execute(image)
    assert result['status']=='failed' and result['error_code']=='interrupted'
    assert image[1].exists() and (image[1]/'verification.json').exists()
