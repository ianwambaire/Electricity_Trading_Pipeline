"""One fixed load source check; AWS lookup only in a verified UID-1000 child."""
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import selectors
import resource
import stat
import subprocess
import time

SITE = H['ROOT'] / '.venv-prod/lib/python3.14/site-packages'
RUNTIME = Path('/usr/bin/python3.14')
RUNTIME_SHA = 'ac1b8b9815ac3935d6708cbe8223458a19d9dee438ebe18e88378d61712da8d6'
PHASE = 'INITIAL'
BACKEND = 'UNVERIFIED'
ROLE = False
REQUEST = 'NOT_ATTEMPTED'
RUNTIME_IDENTITY = None
EXTRA_CAUSES = {'SDK_DEPENDENCY_MISMATCH', 'SDK_RUNTIME_MISMATCH', 'SDK_INVENTORY_MISMATCH',
    'SDK_PROCESS_TIMEOUT', 'SDK_OUTPUT_BOUND', 'SDK_PROCESS_FAILURE', 'SDK_UNEXPECTED_OUTPUT'}


def need(ok, cause):
    if not ok:
        raise AWS['Blocked'](cause)


def _root_runtime():
    global RUNTIME_IDENTITY
    # Known root-owned OS interpreter, not the writable production venv binary
    # or its pyvenv.cfg. Every ancestor must be a real root-controlled directory.
    for path in tuple(reversed(RUNTIME.parents)) + (RUNTIME,):
        info = path.lstat()
        need(not stat.S_ISLNK(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022, 'SDK_RUNTIME_MISMATCH')
        need(info.st_mode & (0o010 if info.st_gid == 1000 else 0o001), 'SDK_RUNTIME_MISMATCH')
    need(stat.S_ISREG(info.st_mode) and not info.st_mode & 0o6000 and info.st_mode & 0o111, 'SDK_RUNTIME_MISMATCH')
    raw, identity = H['capture'](RUNTIME, 0, 64_000_000)
    need(hashlib.sha256(raw).hexdigest() == RUNTIME_SHA, 'SDK_RUNTIME_MISMATCH')
    RUNTIME_IDENTITY = identity


def root_runtime():
    try:
        return _root_runtime()
    except Exception:
        raise AWS['Blocked']('SDK_RUNTIME_MISMATCH') from None


def _sdk_files():
    # File bytes are held after hashing. Neither SDK imports nor data loads can
    # reopen them later; child code revalidates the entire envelope before import.
    expected = SDK_LOCK['files']
    actual = set()
    # Anchor SITE and every package entry before even inspecting root metadata.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_NOATIME', 0)
    site = os.open('/', flags)
    try:
        for part in SITE.parts[1:]:
            child = os.open(part, flags, dir_fd=site)
            os.close(site)
            site = child
        for root in SDK_LOCK['code_roots']:
            info = os.stat(root, dir_fd=site, follow_symlinks=False)
            need(not stat.S_ISLNK(info.st_mode), 'SDK_INVENTORY_MISMATCH')
            if stat.S_ISREG(info.st_mode):
                actual.add(root)
                continue
            need(stat.S_ISDIR(info.st_mode), 'SDK_INVENTORY_MISMATCH')
            descriptor = os.open(root, flags, dir_fd=site)
            todo = [(descriptor, root)]
            while todo:
                directory, prefix = todo.pop()
                try:
                    info = os.fstat(directory)
                    need(stat.S_ISDIR(info.st_mode) and info.st_uid in {0, 1000} and not info.st_mode & 0o022, 'SDK_INVENTORY_MISMATCH')
                    access = 0o500 if info.st_uid == 1000 else 0o050 if info.st_gid == 1000 else 0o005
                    need(info.st_mode & access == access, 'SDK_INVENTORY_MISMATCH')
                    with os.scandir(directory) as entries:
                        children = list(entries)
                    need(len(children) <= 1024, 'SDK_INVENTORY_MISMATCH')
                    for entry in children:
                        need(not entry.is_symlink(), 'SDK_INVENTORY_MISMATCH')
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name != '__pycache__':
                                child = os.open(entry.name, flags, dir_fd=directory)
                                todo.append((child, prefix + '/' + entry.name))
                        elif entry.name.endswith('.py'):
                            actual.add(prefix + '/' + entry.name)
                            need(len(actual) <= 512, 'SDK_INVENTORY_MISMATCH')
                        else:
                            need(not entry.name.endswith(('.so', '.pyd', '.dll')), 'SDK_INVENTORY_MISMATCH')
                except Exception:
                    for child, _ in todo:
                        os.close(child)
                    raise
                finally:
                    os.close(directory)
    finally:
        os.close(site)
    need(actual == {name for name in expected if name.endswith('.py')}, 'SDK_INVENTORY_MISMATCH')
    held = {}
    total = 0
    for name, record in expected.items():
        need(not Path(name).is_absolute() and '..' not in Path(name).parts, 'SDK_INVENTORY_MISMATCH')
        raw, _ = H['capture'](SITE / name, (0, 1000), 2_000_000)
        total += len(raw)
        need(total <= 6_000_000 and record == {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}, 'SDK_DEPENDENCY_MISMATCH')
        held[name] = raw
    return held


def sdk_files():
    try:
        return _sdk_files()
    except AWS['Blocked']:
        raise
    except Exception:
        raise AWS['Blocked']('SDK_DEPENDENCY_MISMATCH') from None


def child_run(script, envelope):
    """Child shares timeout's process group: it cannot outlive remote deadline.

    Only this fixed trusted interpreter and verified code are executable. The
    credential identifier is stdin data, never an argv value or retained output.
    """
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'BOTO_DISABLE_CRT': 'true',
           'AWS_CONFIG_FILE': '/dev/null', 'AWS_SHARED_CREDENTIALS_FILE': '/dev/null',
           'BOTO_CONFIG': '/dev/null', 'AWS_EC2_METADATA_DISABLED': 'false'}
    try:
        process = subprocess.Popen([str(RUNTIME), '-I', '-S', '-B', '-c', script.decode()],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd='/', env=env, start_new_session=False)
    except OSError:
        raise AWS['Blocked']('SDK_PROCESS_FAILURE') from None
    selector = selectors.DefaultSelector()
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    deadline, offset = time.monotonic() + 20, 0
    failure = None
    try:
        for stream, name in ((process.stdin, 'stdin'), (process.stdout, 'stdout'), (process.stderr, 'stderr')):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_WRITE if name == 'stdin' else selectors.EVENT_READ, name)
        while selector.get_map() or process.poll() is None:
            if time.monotonic() >= deadline:
                failure = 'SDK_PROCESS_TIMEOUT'
                break
            for key, _ in selector.select(.05):
                if key.data == 'stdin':
                    try:
                        offset += os.write(key.fd, envelope[offset:offset + 8192])
                    except BrokenPipeError:
                        offset = len(envelope)
                    if offset == len(envelope):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                else:
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    value = buffers[key.data]
                    if len(value) + len(chunk) > 65536:
                        failure = 'SDK_OUTPUT_BOUND'
                        break
                    value.extend(chunk)
            if failure:
                break
        if failure:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise AWS['Blocked'](failure)
        return process.wait(timeout=1), bytes(buffers['stdout'])
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        selector.close()
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()


def get_aws_secret(env, held):
    global ROLE
    # Rechecking the controlled OS runtime does not execute it. Parent is already
    # irreversibly UID/GID 1000; child checks its identity before any SDK import.
    info = RUNTIME.lstat()
    need(RUNTIME_IDENTITY == (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
         and info.st_uid == 0 and not info.st_mode & 0o022, 'SDK_RUNTIME_MISMATCH')
    allowed = {'POWERFLOW_SECRETS_BACKEND', 'POWERFLOW_SECRET_ID_ENTSOE_API_KEY',
               'POWERFLOW_SECRETS_PREFIX', 'AWS_REGION', 'AWS_DEFAULT_REGION'}
    selected = {key: value for key, value in env.items() if key in allowed}
    envelope = json.dumps({'files': {name: base64.b64encode(raw).decode() for name, raw in held.items()},
                           'environment': selected}, separators=(',', ':')).encode()
    need(len(envelope) <= 8_000_000, 'SDK_DEPENDENCY_MISMATCH')
    code, output = child_run(CHILD_SOURCE, envelope)
    try:
        response = json.loads(output)
    except Exception:
        raise AWS['Blocked']('SDK_UNEXPECTED_OUTPUT') from None
    need(type(response) is dict and type(response.get('ok')) is bool, 'SDK_UNEXPECTED_OUTPUT')
    if response['ok']:
        need(code == 0 and set(response) == {'ok', 'secret'} and type(response['secret']) is str
             and 0 < len(response['secret']) <= 4096, 'SDK_UNEXPECTED_OUTPUT')
        ROLE = True
        return response['secret']
    need(code == 1 and set(response) == {'ok', 'cause'} and response['cause'] in AWS['CAUSES'], 'SDK_UNEXPECTED_OUTPUT')
    raise AWS['Blocked'](response['cause'])


def report(status, cause=None, comparison=None):
    return {'status': status, 'phase': PHASE, 'cause': cause,
            'credential_backend': BACKEND, 'iam_role_verified': ROLE,
            'source_request': REQUEST, 'comparison': comparison}


def inspect():
    global PHASE, BACKEND, REQUEST
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    PHASE = 'SOURCE_BINDINGS'
    for path, expected in SOURCE_HASHES.items():
        raw, _ = H['capture'](H['ROOT'] / path, 1000, 100000)
        H['need'](hashlib.sha256(raw).hexdigest() == expected, 'SOURCE_DRIFT')
    raw, _ = H['capture'](H['ROOT'] / '.venv-prod/lib/python3.14/site-packages/prefect/workers/base.py', 1000, 100000)
    H['need'](hashlib.sha256(raw).hexdigest() == H['WORKER_SHA'], 'SOURCE_DRIFT')
    PHASE = 'CONFIGURATION'
    pid = H['worker']()
    inherited = H['worker_environment'](pid)
    overrides = H['deployment_environment']()
    env_raw, env_id = H['capture'](H['ROOT'] / '.env', 1000, 65536, secret=True)
    snapshot, snapshot_id = H['capture'](H['ROOT'] / 'data/raw/entsoe/load.csv', 1000, CORE['SNAPSHOT_LIMIT'])
    H['need'](H['worker']() == pid and H['worker_environment'](pid) == inherited
              and H['deployment_environment']() == overrides, 'PROFILE_DRIFT')
    H['need'](H['capture'](H['ROOT'] / '.env', 1000, 65536, secret=True)[1] == env_id, 'PROFILE_DRIFT')
    H['need'](H['capture'](H['ROOT'] / 'data/raw/entsoe/load.csv', 1000, CORE['SNAPSHOT_LIMIT'])[1] == snapshot_id, 'SNAPSHOT_DRIFT')
    PHASE = 'SDK_VERIFICATION'
    # Passive verification only while root; no SDK module or production runtime
    # is executed until after the permanent identity drop.
    root_runtime()
    held = sdk_files()
    PHASE = 'IDENTITY'
    H['drop_identity']()
    PHASE = 'AUTHENTICATION'
    try:
        env, history = H['configured_environment'](env_raw, inherited, overrides)
        BACKEND = PROVIDER['secrets_backend'](env)
    except PROVIDER['SecretConfigurationError']:
        raise AWS['Blocked']('AWS_CONFIGURATION_REJECTED') from None
    need(BACKEND in {'ssm', 'secretsmanager'}, 'AWS_CONFIGURATION_REJECTED')
    AWS['selection'](PROVIDER, env)  # No secret lookup; validates configured route.
    del env_raw, inherited, overrides
    PHASE = 'SDK_VERIFICATION'
    token = get_aws_secret(env, held)
    del env
    PHASE = 'SOURCE_REQUEST'
    REQUEST = 'ATTEMPTED'
    source, failure = CORE['request_source'](lambda name: token if name == 'ENTSOE_API_KEY' else None)
    del token
    if failure:
        return report('BLOCKED', failure['cause'])
    REQUEST = 'COMPLETED'
    PHASE = 'COMPARISON'
    H['need'](H['capture'](H['ROOT'] / 'data/raw/entsoe/load.csv', 1000, CORE['SNAPSHOT_LIMIT'])[1] == snapshot_id, 'SNAPSHOT_DRIFT')
    comparison = CORE['sanitized_compare'](source, snapshot, dt.datetime.now(dt.timezone.utc), history)
    if comparison['status'] != 'CHECKED':
        return report('BLOCKED', comparison['cause'])
    return report('PASS', comparison=comparison)


def main():
    try:
        result = inspect()
    except Exception as error:
        codes = H['CAUSES'] | AWS['CAUSES'] | EXTRA_CAUSES
        cause = str(error) if isinstance(error, (H['Stop'], AWS['Blocked'])) and str(error) in codes else 'EVIDENCE_UNVERIFIED'
        result = report('BLOCKED', cause)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
