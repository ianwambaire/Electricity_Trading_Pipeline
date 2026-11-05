"""Offline-tested atomic store primitive; no CLI, provisioning or live wiring.

Same immutable-release/CAS/lock pattern as forecast publication,
with a mandatory distinct namespace marker. Never imports the forecast publisher.
"""
import contextlib
import datetime as dt
import fcntl
import os
from pathlib import Path
import re
import stat
import uuid

from .operational_evidence import InvalidEvidence, MAX_BYTES, UTC, require, validate, view, timestamp

MARKER = b'powerflow-operational-evidence-v1\n'
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def metadata(fd, directory=False):
    s = os.fstat(fd)
    require((stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode))
            and s.st_uid in (0, os.geteuid()) and not s.st_mode & 0o022, 'PATH')
    return s


def directory(parent, name):
    fd = os.open(name, FLAGS, dir_fd=parent)
    try:
        metadata(fd, True)
        return fd
    except Exception:
        os.close(fd)
        raise


def read_file(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = metadata(fd)
        require(before.st_size <= MAX_BYTES and before.st_nlink == 1, 'SIZE')
        with os.fdopen(os.dup(fd), 'rb') as f:
            raw = f.read(MAX_BYTES + 1)
        after = os.fstat(fd)
        require(len(raw) <= MAX_BYTES and
                (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'INTEGRITY')
        return raw
    finally:
        os.close(fd)


@contextlib.contextmanager
def opened(root):
    path = Path(root)
    require(path.is_absolute() and '..' not in path.parts, 'PATH')
    fd = os.open('/', FLAGS)
    try:
        # Anchored no-follow traversal: even substituted ancestor symlinks fail.
        for part in path.parts[1:]:
            nxt = os.open(part, FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
        metadata(fd, True)
        require(read_file(fd, 'contract') == MARKER, 'NAMESPACE')
        releases = directory(fd, 'releases')
        try:
            yield fd, releases
        finally:
            os.close(releases)
    finally:
        os.close(fd)


def pointer(root):
    try:
        fd = os.open('current', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
    except FileNotFoundError:
        return None
    try:
        info = metadata(fd)
        # Atomic replacement can unlink the already-open OLD pointer. Its bytes
        # remain immutable; nlink=0 is expected for that pinned reader, not drift.
        require(info.st_size == 65 and info.st_nlink in (0, 1), 'POINTER')
        with os.fdopen(os.dup(fd), 'rb') as f:
            raw = f.read(66)
        require(re.fullmatch(b'[0-9a-f]{64}\n', raw) is not None, 'POINTER')
        return raw[:64].decode('ascii')
    finally:
        os.close(fd)


def content(releases, digest):
    require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest) is not None, 'POINTER')
    fd = directory(releases, digest)
    try:
        return read_file(fd, 'evidence.json')
    finally:
        os.close(fd)


def read_current(root, *, now, admin=False):
    try:
        with opened(root) as (r, releases):
            digest = pointer(r)  # resolve once; old releases are never deleted
            if digest is None:
                return view(now=now, admin=admin)
            return view(content(releases, digest), digest, now=now, admin=admin)
    except FileNotFoundError:
        if not os.path.lexists(root):
            return view(now=now, admin=admin)
        result = view(now=now, admin=admin)
        result.update(status='INVALID', failure='INCOMPLETE_STORE')
        return result
    except (OSError, InvalidEvidence) as error:
        result = view(now=now, admin=admin)
        category = str(error) if isinstance(error, InvalidEvidence) else 'IO_ERROR'
        require(category in {'PATH', 'SIZE', 'INTEGRITY', 'NAMESPACE', 'POINTER', 'IO_ERROR'}, 'SCHEMA')
        result.update(status='INVALID', failure=category)

        return result


@contextlib.contextmanager
def locked(root):
    with opened(root) as (r, releases):
        fd = os.open('.publication.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=r)
        try:
            metadata(fd)
            require(os.fstat(fd).st_nlink == 1, 'PATH')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield r, releases
        finally:
            os.close(fd)


def fresh(raw, digest, now):
    b = validate(raw, digest, now)
    require(view(raw, digest, now=now)['status'] == 'VALID', 'STALE')
    return b


def switch(r, releases, digest, expected, clock):
    require(pointer(r) == expected, 'CONFLICT')
    raw = content(releases, digest)
    fresh(raw, digest, clock())
    pending = '.pointer-' + uuid.uuid4().hex
    fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o640, dir_fd=r)
    with os.fdopen(fd, 'wb') as f:
        os.fchown(f.fileno(), os.geteuid(), os.fstat(r).st_gid)
        os.fchmod(f.fileno(), 0o640)
        f.write((digest + '\n').encode('ascii'))
        f.flush()
        os.fsync(f.fileno())
    try:
        fresh(raw, digest, clock())  # freshness recheck immediately before activation
        os.replace(pending, 'current', src_dir_fd=r, dst_dir_fd=r)
        os.fsync(r)
    finally:
        try:
            os.unlink(pending, dir_fd=r)
        except FileNotFoundError:
            pass


def publish(root, raw, digest, expected_current, *, clock=lambda: dt.datetime.now(UTC)):
    """Trusted producer only; fresh content, monotonic schedule and CAS under lock.

    A post-switch fsync failure is uncertain success: do not retry automatically.
    Preserved immutable content + expected pointer enable independent recovery.
    """
    new = fresh(raw, digest, clock())  # validate before even creating the lock
    with locked(root) as (r, releases):
        require(pointer(r) == expected_current, 'CONFLICT')
        if expected_current is not None:
            old_raw = content(releases, expected_current)
            old = validate(old_raw, expected_current, clock())  # stale is valid structure
            require(timestamp(new['execution']['scheduled_at']) >= timestamp(old['execution']['scheduled_at']), 'OLDER_RUN')
            if timestamp(new['execution']['scheduled_at']) == timestamp(old['execution']['scheduled_at']):
                require(all(new['execution'][k] == old['execution'][k] for k in ('flow_run_id', 'deployment_id')), 'IDENTITY')
                if old['execution']['pipeline_run_id'] is not None:
                    require(new['execution']['pipeline_run_id'] == old['execution']['pipeline_run_id'], 'IDENTITY')
                if old['execution']['started_at'] is not None:
                    require(new['execution']['started_at'] == old['execution']['started_at'] and
                            new['execution']['outcome'] not in {'SCHEDULED', 'PENDING'}, 'TERMINAL_DRIFT')
                require(timestamp(new['observed_at']) >= timestamp(old['observed_at']), 'OLDER_OBSERVATION')
                require(old['execution']['outcome'] in {'SCHEDULED', 'PENDING', 'RUNNING'} or
                        new['execution'] == old['execution'] and new['inference'] == old['inference'] and new['delivery'] == old['delivery'], 'TERMINAL_DRIFT')
        if digest == expected_current:
            return {'outcome': 'UNCHANGED', 'current': digest, 'previous': expected_current}
        try:
            os.stat(digest, dir_fd=releases, follow_symlinks=False)
        except FileNotFoundError:
            temporary = '.partial-' + uuid.uuid4().hex
            os.mkdir(temporary, 0o750, dir_fd=releases)
            t = directory(releases, temporary)
            try:
                os.fchown(t, os.geteuid(), os.fstat(r).st_gid)
                os.fchmod(t, 0o750)
                fd = os.open('evidence.json', os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o640, dir_fd=t)
                with os.fdopen(fd, 'wb') as f:
                    os.fchown(f.fileno(), os.geteuid(), os.fstat(r).st_gid)
                    os.fchmod(f.fileno(), 0o640)
                    f.write(raw)
                    f.flush()
                    os.fsync(f.fileno())
                require(read_file(t, 'evidence.json') == raw, 'INTEGRITY')
                fresh(raw, digest, clock())
                os.fsync(t)
            finally:
                os.close(t)
            # No writer outside this lock may modify the trusted store.
            os.rename(temporary, digest, src_dir_fd=releases, dst_dir_fd=releases)
            os.fsync(releases)
        else:
            require(content(releases, digest) == raw, 'INTEGRITY')
        switch(r, releases, digest, expected_current, clock)
        return {'outcome': 'PUBLISHED', 'current': digest, 'previous': expected_current}


def restore(root, expected_current, previous, *, clock=lambda: dt.datetime.now(UTC)):
    """Explicit recovery only. Older evidence may be restored only while fresh.

    No automatic rollback; old release bytes and failed partials remain retained.
    """
    with locked(root) as (r, releases):
        switch(r, releases, previous, expected_current, clock)
    return {'current': previous, 'previous': expected_current}
