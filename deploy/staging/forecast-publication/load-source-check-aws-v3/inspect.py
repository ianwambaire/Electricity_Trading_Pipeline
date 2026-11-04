"""Passive SDK verification only. No SDK imports, credentials or source access."""
import datetime as dt
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat

SITE = H['ROOT'] / '.venv-prod/lib/python3.14/site-packages'
CATEGORIES = {'FILE_MISSING', 'FILE_TYPE_MISMATCH', 'PERMISSION_MISMATCH', 'OWNER_MISMATCH',
              'HASH_MISMATCH', 'SYMLINK_OR_PATH_VIOLATION',
              'SDK_VERSION_OR_LAYOUT_MISMATCH', 'OTHER_VERIFICATION_FAILURE'}
STAGES = {'NOT_STARTED', 'RUNTIME', 'SITE_ANCHOR', 'CODE_ROOT', 'CODE_DIRECTORY',
          'CODE_INVENTORY', 'FILE_PARENT', 'FILE_METADATA', 'FILE_OPEN', 'FILE_READ',
          'FILE_STABILITY', 'FILE_INTEGRITY', 'COMPLETE'}
STATE = {'dependency_id': None, 'category': None, 'stage': 'NOT_STARTED', 'verified_files': 0}


class VerificationFailure(ValueError):
    pass


def approved_ids():
    values = {'SDK_SITE', 'SDK_INVENTORY', 'PYTHON_RUNTIME'} | set(SDK_LOCK['files'])
    values.update('SDK_PACKAGE:' + root for root in SDK_LOCK['code_roots'])
    for name in SDK_LOCK['files']:
        values.update(str(p) for p in Path(name).parents if str(p) != '.')
    return values


def location(stage, identifier):
    STATE['stage'] = stage
    # Unexpected inventory names never escape, even if they contain a secret.
    STATE['dependency_id'] = identifier if identifier in approved_ids() else 'SDK_INVENTORY'


def fail(category):
    STATE['category'] = category if category in CATEGORIES else 'OTHER_VERIFICATION_FAILURE'
    raise VerificationFailure('sdk_verification_failed')


def require(ok, category):
    if not ok:
        fail(category)


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def filesystem_failure(error, parent=None, name=None, directory=False):
    if isinstance(error, OSError):
        if error.errno == errno.ENOENT:
            fail('FILE_MISSING')
        if error.errno in {errno.EACCES, errno.EPERM}:
            fail('PERMISSION_MISMATCH')
        if error.errno == errno.ELOOP:
            fail('SYMLINK_OR_PATH_VIOLATION')
        if error.errno in {errno.ENOTDIR, errno.EISDIR, errno.ENXIO, errno.ENODEV}:
            # Inspect only the already approved anchored component, never its
            # symlink target. This distinguishes O_DIRECTORY symlink failures.
            if parent is not None and name is not None:
                try:
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except OSError:
                    fail('SYMLINK_OR_PATH_VIOLATION' if directory else 'FILE_TYPE_MISMATCH')
                if stat.S_ISLNK(info.st_mode):
                    fail('SYMLINK_OR_PATH_VIOLATION')
            fail('FILE_TYPE_MISMATCH')
    fail('OTHER_VERIFICATION_FAILURE')


def directory_fd(path, stage, identifier):
    location(stage, identifier)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_NOATIME', 0)
    descriptor = os.open('/', flags)
    try:
        for part in path.parts[1:]:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except OSError as error:
                filesystem_failure(error, descriptor, part, directory=True)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def metadata(info, directory=False):
    require(not stat.S_ISLNK(info.st_mode), 'SYMLINK_OR_PATH_VIOLATION')
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), 'FILE_TYPE_MISMATCH')
    require(info.st_uid in {0, 1000}, 'OWNER_MISMATCH')
    require(not info.st_mode & 0o022, 'PERMISSION_MISMATCH')
    access = (0o500 if info.st_uid == 1000 else 0o050 if info.st_gid == 1000 else 0o005) if directory else (
        0o400 if info.st_uid == 1000 else 0o040 if info.st_gid == 1000 else 0o004)
    require(info.st_mode & access == access, 'PERMISSION_MISMATCH')


def inventory():
    actual = set()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_NOATIME', 0)
    site = directory_fd(SITE, 'SITE_ANCHOR', 'SDK_SITE')
    try:
        for root in SDK_LOCK['code_roots']:
            safe_root = 'SDK_PACKAGE:' + root
            location('CODE_ROOT', safe_root)
            try:
                info = os.stat(root, dir_fd=site, follow_symlinks=False)
                require(not stat.S_ISLNK(info.st_mode), 'SYMLINK_OR_PATH_VIOLATION')
                if root.endswith('.py'):
                    require(stat.S_ISREG(info.st_mode), 'FILE_TYPE_MISMATCH')
                    actual.add(root)
                    continue
                require(stat.S_ISDIR(info.st_mode), 'FILE_TYPE_MISMATCH')
                descriptor = os.open(root, flags, dir_fd=site)
            except OSError as error:
                filesystem_failure(error, site, root, directory=not root.endswith('.py'))
            pending = [(descriptor, root)]
            while pending:
                directory, prefix = pending.pop()
                location('CODE_DIRECTORY', prefix if prefix in approved_ids() else safe_root)
                try:
                    metadata(os.fstat(directory), directory=True)
                    with os.scandir(directory) as scan:
                        children = sorted(scan, key=lambda entry: entry.name)
                    require(len(children) <= 1024, 'SDK_VERSION_OR_LAYOUT_MISMATCH')
                    for entry in children:
                        name = prefix + '/' + entry.name
                        location('CODE_INVENTORY', name if name in approved_ids() else safe_root)
                        require(not entry.is_symlink(), 'SYMLINK_OR_PATH_VIOLATION')
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name != '__pycache__':
                                child = os.open(entry.name, flags, dir_fd=directory)
                                pending.append((child, name))
                        elif entry.name.endswith('.py'):
                            actual.add(name)
                            require(len(actual) <= 512, 'SDK_VERSION_OR_LAYOUT_MISMATCH')
                        else:
                            require(not entry.name.endswith(('.so', '.pyd', '.dll')), 'SDK_VERSION_OR_LAYOUT_MISMATCH')
                except OSError as error:
                    for child, _ in pending:
                        os.close(child)
                    filesystem_failure(error, directory, entry.name if 'entry' in locals() else None, directory=True)
                except BaseException:
                    for child, _ in pending:
                        os.close(child)
                    raise
                finally:
                    os.close(directory)
    finally:
        os.close(site)
    expected = {name for name in SDK_LOCK['files'] if name.endswith('.py')}
    location('CODE_INVENTORY', 'SDK_INVENTORY')
    if expected - actual:
        location('CODE_INVENTORY', sorted(expected - actual)[0])
        fail('FILE_MISSING')
    require(actual == expected, 'SDK_VERSION_OR_LAYOUT_MISMATCH')


def capture_file(name):
    require(name in SDK_LOCK['files'] and not Path(name).is_absolute()
            and '..' not in Path(name).parts, 'SYMLINK_OR_PATH_VIOLATION')
    parent = directory_fd((SITE / name).parent, 'FILE_PARENT', name)
    basename = Path(name).name
    try:
        location('FILE_METADATA', name)
        initial = os.stat(basename, dir_fd=parent, follow_symlinks=False)
        metadata(initial)
        require(initial.st_size <= 2_000_000, 'OTHER_VERIFICATION_FAILURE')
        location('FILE_OPEN', name)
        file = os.open(basename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_NOATIME', 0), dir_fd=parent)
        with os.fdopen(file, 'rb') as stream:
            before = os.fstat(stream.fileno())
            metadata(before)
            require(identity(initial) == identity(before), 'SYMLINK_OR_PATH_VIOLATION')
            location('FILE_READ', name)
            raw = stream.read(2_000_001)
            require(len(raw) <= 2_000_000, 'OTHER_VERIFICATION_FAILURE')
            after = os.fstat(stream.fileno())
            location('FILE_STABILITY', name)
            require(identity(before) == identity(after), 'SYMLINK_OR_PATH_VIOLATION')
            named = os.stat(basename, dir_fd=parent, follow_symlinks=False)
            require(identity(named) == identity(after), 'SYMLINK_OR_PATH_VIOLATION')
            return raw
    except OSError as error:
        filesystem_failure(error, parent, basename)
    finally:
        os.close(parent)


def version_mismatch(name, raw):
    if not name.endswith('.dist-info/METADATA'):
        return False
    expected = [version for package, version in SDK_LOCK['versions'].items()
                if name == package.replace('-', '_') + '-' + version + '.dist-info/METADATA']
    if len(expected) != 1:
        return True
    observed = re.findall(rb'^Version:[ \t]*([^\r\n]{0,128})\r?$', raw, flags=re.M)
    return observed != [expected[0].encode('ascii')]


def sdk_files():
    STATE.update(dependency_id=None, category=None, stage='NOT_STARTED', verified_files=0)
    try:
        inventory()
        held, total = {}, 0
        for name in sorted(SDK_LOCK['files']):
            location('FILE_PARENT', name)
            raw = capture_file(name)
            total += len(raw)
            location('FILE_INTEGRITY', name)
            require(total <= 6_000_000, 'OTHER_VERIFICATION_FAILURE')
            record = SDK_LOCK['files'][name]
            if record != {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}:
                fail('SDK_VERSION_OR_LAYOUT_MISMATCH' if version_mismatch(name, raw) else 'HASH_MISMATCH')
            held[name] = raw
            STATE['verified_files'] += 1
        STATE.update(dependency_id=None, category=None, stage='COMPLETE')
        return held
    except VerificationFailure:
        raise
    except OSError as error:
        filesystem_failure(error)
    except Exception:
        fail('OTHER_VERIFICATION_FAILURE')


def main():
    runtime_ok = False
    location('RUNTIME', 'PYTHON_RUNTIME')
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        try:
            RUNTIME_CHECK()
        except OSError as error:
            filesystem_failure(error)
        except Exception:
            fail('SDK_VERSION_OR_LAYOUT_MISMATCH')
        runtime_ok = True
        sdk_files()
        status = 'PASS'
    except VerificationFailure:
        status = 'BLOCKED'
    except Exception:
        STATE['category'] = 'OTHER_VERIFICATION_FAILURE'
        status = 'BLOCKED'
    report = {'status': status, 'runtime_verified': runtime_ok, 'sdk_verification': dict(STATE),
              'aws_attempted': False, 'source_attempted': False}
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if status == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
