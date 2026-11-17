"""Hash-bound publication; fixed plan supplied by verified installation bundle."""
import ctypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

COUNTS={"pipeline_runs":891,"data_quality_results":16525,"operational_incidents":1485,"pipeline_stage_timings":11561}


def require(ok,code):
    if not ok:raise RuntimeError(code)


def signature(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns


def no_links(path):
    for p in (path,*path.parents):require(not p.is_symlink(),'symlink_path')


def digest_file(path):
    no_links(path)
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|getattr(os,'O_NOATIME',0)),'rb') as h:
        before=os.fstat(h.fileno());require(stat.S_ISREG(before.st_mode),'source_not_regular')
        digest=hashlib.sha256()
        for data in iter(lambda:h.read(1024*1024),b''):digest.update(data)
        require(signature(before)==signature(os.fstat(h.fileno()))==signature(path.stat()),'source_changed_during_hash')
    return digest.hexdigest(),signature(before)


def validate_sources(plan):
    result={}
    for item in plan:
        p=Path(item['source'])
        if p.suffix=='.db':require(not any(os.path.lexists(str(p)+suffix) for suffix in ('-wal','-shm','-journal')),'approved_snapshot_sidecar_present')
        h,s=digest_file(p)
        info=p.stat()
        for key,actual in (('uid',info.st_uid),('gid',info.st_gid),('mode',stat.S_IMODE(info.st_mode))):
            if key in item:require(item[key]==actual,'approved_source_permission_drift')
        require(h==item['sha256'] and s[2]==item['bytes'],'approved_source_drift')
        result[str(p)]=s
    return result


def rename_exclusive(source,destination):
    libc=ctypes.CDLL(None,use_errno=True)
    require(hasattr(libc,'renameat2'),'renameat2_required')
    fn=libc.renameat2
    fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    fn.restype=ctypes.c_int
    require(fn(-100,os.fsencode(source),-100,os.fsencode(destination),1)==0,'atomic_destination_conflict_or_rename_failure')


def publish(plan,destination,temporary,gid,provenance,rename=rename_exclusive):
    destination,temporary=Path(destination),Path(temporary)
    no_links(destination);no_links(temporary)
    require(destination.parent==temporary.parent,'temporary_not_same_parent')
    require(not os.path.lexists(destination) and not os.path.lexists(temporary),'publication_destination_exists')
    require(destination.parent.is_dir(),'publication_parent_missing')
    # All approved inputs must match before the first publication write.
    before=validate_sources(plan)
    require(os.statvfs(destination.parent).f_bavail*os.statvfs(destination.parent).f_frsize >=
            2*sum(x['bytes'] for x in plan)+2*1024**3,'publication_disk_guard')
    temporary.mkdir(mode=0o700)
    manifest={'format':1,'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'operational_data_classification':'HISTORICAL','operational_snapshot_cutoff_utc':'2026-10-26T02:22:00Z',
        'not_current_operational_state':True,'unvalidated_next24_forecasts_included':False,
        'source_consistency':'exact approved byte set; not simultaneous producer transaction',
        'provenance':provenance,'files':{}}
    for item in plan:
        relative=Path(item['relative_path'])
        require(not relative.is_absolute() and '..' not in relative.parts,'invalid_publication_relative_path')
        source=Path(item['source']);target=temporary/relative
        require(signature(source.stat())==before[str(source)],'source_changed_before_copy')
        h,s=digest_file(source);require(h==item['sha256'] and s==before[str(source)],'source_drift_before_copy')
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|getattr(os,'O_NOATIME',0))
        with os.fdopen(fd,'rb') as src, target.open('xb') as dst:
            require(signature(os.fstat(src.fileno()))==s,'source_inode_changed')
            digest=hashlib.sha256();size=0
            for data in iter(lambda:src.read(1024*1024),b''):
                size+=len(data);require(size<=item['bytes'],'source_grew');dst.write(data);digest.update(data)
            dst.flush();os.fsync(dst.fileno())
            require(signature(os.fstat(src.fileno()))==s,'source_changed_during_copy')
        require(digest.hexdigest()==item['sha256'] and size==item['bytes'],'copied_hash_mismatch')
        os.chown(target,0,gid);target.chmod(0o640)
        manifest['files'][str(relative)]={k:item[k] for k in ('sha256','bytes','freshness')}
    after=validate_sources(plan);require(after==before,'source_set_changed')
    # Only the copied, validated standalone A1 image is opened; never live SQLite.
    dbpath=temporary/'database/electricity_trading.db'
    require(not any(os.path.lexists(str(dbpath)+s) for s in ('-wal','-shm','-journal')),'snapshot_sidecar')
    with dbpath.open('rb') as h:header=h.read(20)
    require(header[:16]==b'SQLite format 3\x00' and header[18:20]==b'\x01\x01','standalone_delete_journal_required')
    connection=sqlite3.connect(dbpath.as_uri()+'?mode=ro&immutable=1',uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        require(connection.execute('PRAGMA integrity_check').fetchall()==[('ok',)],'copied_database_integrity')
        counts={t:connection.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in COUNTS}
        require(counts==COUNTS,'copied_database_counts')
    finally:connection.close()
    manifest['historical_database_counts']=counts
    data=(json.dumps(manifest,indent=2)+'\n').encode()
    with (temporary/'_publication.json').open('xb') as h:h.write(data);h.flush();os.fsync(h.fileno())
    os.chown(temporary/'_publication.json',0,gid);(temporary/'_publication.json').chmod(0o640)
    for p in sorted(temporary.rglob('*')):
        no_links(p)
        if p.is_dir():os.chown(p,0,gid);p.chmod(0o750)
    for item in plan:
        require(digest_file(temporary/item['relative_path'])[0]==item['sha256'],'final_publication_hash')
    # The root stays0700 until all files are complete; only rename reveals it.
    os.chown(temporary,0,gid);temporary.chmod(0o750)
    fd=os.open(temporary,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    require(validate_sources(plan)==before,'source_set_changed_before_publish')
    rename(temporary,destination)
    fd=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return {'data_bytes':sum(x['bytes'] for x in plan),'total_file_bytes':sum(x['bytes'] for x in plan)+len(data),'files':len(plan),'metadata_files':1,'file_mode':'0640','directory_mode':'0750','owner_uid':0,'reader_gid':gid,
            'publication_manifest_sha256':hashlib.sha256(data).hexdigest(),'historical_A1':True}
