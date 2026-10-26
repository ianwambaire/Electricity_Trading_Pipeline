"""Local fixtures only: hashing, redaction and immutable standalone SQLite checks."""
import hashlib
import importlib.util
import sqlite3
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
p=ROOT/'deploy/staging/publication-preflight-readonly.py'
s=importlib.util.spec_from_file_location('pub',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)


def test_hash_and_symlink_refusal(tmp_path):
    p=tmp_path/'x';p.write_bytes(b'public fixture');r=m.stable_hash(p)
    assert r['sha256']==hashlib.sha256(p.read_bytes()).hexdigest() and r['stable_during_hash']
    q=tmp_path/'link';q.symlink_to(p)
    with pytest.raises(OSError):m.stable_hash(q)


def test_csv_aggregates_and_sensitive_flags_never_emit_rows(tmp_path):
    p=tmp_path/'x.csv';p.write_text('timestamp,email,value\n2026-10-01T00:00:00Z,PRIVATE,42\n')
    r=m.contents_summary(p)
    assert r['row_count']==1 and r['sensitive_header_count']==1 and 'PRIVATE' not in str(r)
    assert r['latest_aware_utc']=='2026-10-01T00:00:00+00:00'


def test_immutable_read_is_hash_bound_and_creates_no_sidecars(tmp_path,monkeypatch):
    p=tmp_path/'fixture.db'
    with sqlite3.connect(p) as db:
        db.execute('CREATE TABLE pipeline_runs(id,run_time,status,message)')
        db.execute('CREATE TABLE data_quality_results(id,check_time,check_name,status)')
        db.execute('CREATE TABLE operational_incidents(id)');db.execute('CREATE TABLE pipeline_stage_timings(id)')
    monkeypatch.setattr(m,'BACKUP_SHA',hashlib.sha256(p.read_bytes()).hexdigest())
    monkeypatch.setattr(m,'TABLE_COUNTS',{k:0 for k in m.TABLE_COUNTS})
    before=p.read_bytes();r=m.readonly_snapshot(p)
    assert r['counts_match_A1'] and r['same_file_after_query']
    assert p.read_bytes()==before and not any(tmp_path.glob('*-wal')) and not any(tmp_path.glob('*-shm'))
    monkeypatch.setattr(m,'BACKUP_SHA','0'*64)
    with pytest.raises(ValueError,match='snapshot_hash_changed'):m.readonly_snapshot(p)


def test_backup_sidecars_skip_connection(tmp_path,monkeypatch):
    p=tmp_path/'fixture.db';p.write_bytes(b'not database');Path(str(p)+'-wal').write_bytes(b'')
    monkeypatch.setattr(m,'BACKUP_SHA',hashlib.sha256(p.read_bytes()).hexdigest())
    monkeypatch.setattr(m.sqlite3,'connect',lambda *a,**k:pytest.fail('no connection with sidecars'))
    assert m.readonly_snapshot(p)['status']=='SKIPPED_SIDECAR_PRESENT'
