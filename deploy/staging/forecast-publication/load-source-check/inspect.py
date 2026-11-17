"""Fixed host adapter. Only run from retained manifest-verified source bytes."""
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import re
import stat
import urllib.request

ROOT = Path('/home/ec2-user/Electricity_Trading_Pipeline')
DEP = '47e5ef51-26d0-44b6-b119-2c40d0e77397'
UNIT = 'powerflow-prefect-worker.service'
WORKER_SHA = '703c596378c2679b26ef107f117a71bb17ba5c851d32a4343ab712362c04b1c6'
CURRENT_PHASE = 'INITIAL'


class Stop(ValueError):
    pass


CAUSES = {'READ_BOUND', 'READ_METADATA', 'READ_DRIFT', 'SOURCE_DRIFT',
          'WORKER_STATE', 'WORKER_IDENTITY', 'WORKER_PROCESS', 'WORKER_ENV',
          'DEPLOYMENT_IDENTITY', 'DEPLOYMENT_ENV', 'POOL_TEMPLATE', 'HTTP_BOUND',
          'HTTP_STATUS', 'ENV_SYNTAX', 'ENDPOINT_DRIFT', 'HISTORY_CONFIGURATION',
          'AUTH_BACKEND_REQUIRES_VERIFIED_SDK', 'IDENTITY_DROP', 'PROFILE_DRIFT',
          'SNAPSHOT_DRIFT', 'DEPENDENCY_RUNTIME'}


def need(ok, code):
    if not ok:
        raise Stop(code)


def capture(path, owner, limit, secret=False):
    """Walk fixed ancestors with no-follow descriptors; retain verified bytes."""
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts, 'READ_METADATA')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        # Root reads persistent files with NOATIME; procfs has no persistent
        # access-time update. No permission fallback or retry is allowed.
        noatime = getattr(os, 'O_NOATIME', 0) if path.parts[1] != 'proc' else 0
        raw_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | noatime, dir_fd=fd)
        with os.fdopen(raw_fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            need(stat.S_ISREG(before.st_mode) and before.st_uid == owner and not before.st_mode & 0o022, 'READ_METADATA')
            if secret:
                need(not before.st_mode & 0o077, 'READ_METADATA')
            need(before.st_size <= limit, 'READ_BOUND')
            raw = stream.read(limit + 1)
            need(len(raw) <= limit, 'READ_BOUND')
            after = os.fstat(stream.fileno())
            fields = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            need(fields(before) == fields(after), 'READ_DRIFT')
            info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            need(fields(info) == fields(after), 'READ_DRIFT')
            return raw, fields(after)
    finally:
        os.close(fd)


def worker():
    argv = ['/usr/bin/systemctl', 'show', UNIT, '--no-pager',
            '--property=ActiveState,SubState,User,Group,MainPID,WorkingDirectory']
    result = BOUNDED(argv, timeout=5, limit=4096, grace=1)
    need(not result['failure'] and result['returncode'] == 0, 'WORKER_STATE')
    data = dict(line.split('=', 1) for line in result['stdout'].decode().splitlines())
    need(data.get('ActiveState') == 'active' and data.get('SubState') == 'running', 'WORKER_STATE')
    need(data.get('User') == data.get('Group') == 'ec2-user' and data.get('WorkingDirectory') == str(ROOT), 'WORKER_IDENTITY')
    pid = data.get('MainPID', '')
    need(re.fullmatch('[1-9][0-9]{0,8}', pid) is not None, 'WORKER_PROCESS')
    return pid


def worker_environment(pid):
    # Fixed service PID only. Hold raw bytes privately in memory; never log them.
    raw, _ = capture(Path('/proc') / pid / 'environ', 1000, 131072, secret=True)
    status, _ = capture(Path('/proc') / pid / 'status', 1000, 65536)
    ids = dict(line.split(':', 1) for line in status.decode().splitlines() if ':' in line)
    need(ids.get('Uid', '').split() == ['1000'] * 4 and ids.get('Gid', '').split() == ['1000'] * 4, 'WORKER_IDENTITY')
    entries = raw.rstrip(b'\0').split(b'\0')
    need(all(b'=' in entry for entry in entries), 'WORKER_ENV')
    pairs = [entry.decode().split('=', 1) for entry in entries]
    need(len({p[0] for p in pairs}) == len(pairs), 'WORKER_ENV')
    return dict(pairs)


def prefect(path):
    need(path in {'/deployments/' + DEP, '/work_pools/electricity-pool'}, 'DEPLOYMENT_IDENTITY')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise Stop('HTTP_STATUS')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request('http://127.0.0.1:4200/api' + path, method='GET')
    with opener.open(request, timeout=3) as response:
        need(response.status == 200 and response.geturl() == request.full_url, 'HTTP_STATUS')
        raw = response.read(100001)
        need(len(raw) <= 100000, 'HTTP_BOUND')
        return json.loads(raw)


def deployment_environment(api=prefect):
    value = api('/deployments/' + DEP)
    need(value.get('id') == DEP and value.get('entrypoint') == 'src/scheduled_pipeline.py:powerflow_entsoe_pipeline'
         and value.get('work_pool_name') == 'electricity-pool', 'DEPLOYMENT_IDENTITY')
    pool = api('/work_pools/electricity-pool')
    template = pool.get('base_job_template') or {}
    config = template.get('job_configuration') or {}
    variables = (template.get('variables') or {}).get('properties') or {}
    need(pool.get('type') == 'process' and config.get('env') == '{{ env }}'
         and (variables.get('env') or {}).get('default', {}) in ({}, None), 'POOL_TEMPLATE')
    job = value.get('job_variables') or {}
    need(job.get('command') in (None, '') and job.get('working_dir', str(ROOT)) == str(ROOT), 'DEPLOYMENT_ENV')
    env = job.get('env', {})
    need(isinstance(env, dict) and len(env) <= 100 and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()), 'DEPLOYMENT_ENV')
    return env


def configured_environment(raw, inherited, overrides):
    """Existing python-dotenv parser/interpolation, override=False semantics."""
    env = dict(inherited)
    env.update(overrides)
    if env.get('PYTHON_DOTENV_DISABLED', '').casefold() not in {'1', 'true', 't', 'yes', 'y'}:
        resolved = {}
        for binding in PARSER['parse_stream'](io.StringIO(raw.decode('utf-8'))):
            need(not binding.error, 'ENV_SYNTAX')
            if binding.key is None:
                continue
            value = binding.value
            if value is not None:
                context = dict(resolved)
                context.update(env)
                value = ''.join(atom.resolve(context) for atom in VARIABLES['parse_variables'](value))
            resolved[binding.key] = value
        for key, value in resolved.items():
            if key not in env and value is not None:
                env[key] = value
    need((env.get('ENTSOE_ENDPOINT_URL') or 'https://web-api.tp.entsoe.eu/api') == 'https://web-api.tp.entsoe.eu/api', 'ENDPOINT_DRIFT')
    backend = PROVIDER['secrets_backend'](env)
    # Do not change provider or use a fallback token if an AWS backend is configured.
    need(backend == 'env', 'AUTH_BACKEND_REQUIRES_VERIFIED_SDK')
    history = env.get('POWERFLOW_HISTORY_START_DATE') or '2019-01-01'
    need(re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}', history) is not None, 'HISTORY_CONFIGURATION')
    start = dt.datetime.combine(dt.date.fromisoformat(history), dt.time(), dt.timezone.utc)
    last = env.get('POWERFLOW_HISTORY_END_DATE') or '2025-09-30'
    need(re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}', last) is not None
         and start.date() <= dt.date.fromisoformat(last), 'HISTORY_CONFIGURATION')
    return env, start


def drop_identity():
    need(os.geteuid() == 0 and pwd.getpwnam('ec2-user').pw_uid == pwd.getpwnam('ec2-user').pw_gid == 1000, 'WORKER_IDENTITY')
    os.setgroups([])
    os.setresgid(1000, 1000, 1000)
    os.setresuid(1000, 1000, 1000)
    need(os.getresuid() == os.getresgid() == (1000, 1000, 1000) and os.getgroups() == [], 'IDENTITY_DROP')
    # In-memory process state only. Do not let inherited certificate/proxy or
    # Python configuration affect the fixed HTTPS request.
    os.environ.clear()
    os.environ.update({'PATH': '/usr/bin:/bin', 'LANG': 'C'})


def inspect():
    global CURRENT_PHASE
    CURRENT_PHASE = 'SOURCE_BINDINGS'
    for path, expected in SOURCE_HASHES.items():
        raw, _ = capture(ROOT / path, 1000, 100000)
        need(hashlib.sha256(raw).hexdigest() == expected, 'SOURCE_DRIFT')
    raw, _ = capture(ROOT / '.venv-prod/lib/python3.14/site-packages/prefect/workers/base.py', 1000, 100000)
    need(hashlib.sha256(raw).hexdigest() == WORKER_SHA, 'SOURCE_DRIFT')
    CURRENT_PHASE = 'CONFIGURATION'
    pid = worker()
    inherited = worker_environment(pid)
    overrides = deployment_environment()
    env_raw, env_identity = capture(ROOT / '.env', 1000, 65536, secret=True)
    CURRENT_PHASE = 'SNAPSHOT'
    snapshot, snapshot_identity = capture(ROOT / 'data/raw/entsoe/load.csv', 1000, CORE['SNAPSHOT_LIMIT'])
    # Recheck captured environment, service PID, deployment overrides and snapshot
    # before discarding root privileges. Drift never produces a provider request.
    need(worker() == pid and worker_environment(pid) == inherited and deployment_environment() == overrides, 'PROFILE_DRIFT')
    need(capture(ROOT / '.env', 1000, 65536, secret=True)[1] == env_identity, 'PROFILE_DRIFT')
    need(capture(ROOT / 'data/raw/entsoe/load.csv', 1000, CORE['SNAPSHOT_LIMIT'])[1] == snapshot_identity, 'SNAPSHOT_DRIFT')
    CURRENT_PHASE = 'IDENTITY'
    drop_identity()
    # No application/third-party/runtime imports. All executable bytes were held
    # and hash-verified locally before SSH; only trusted OS stdlib is imported.
    CURRENT_PHASE = 'AUTHENTICATION'
    env, history = configured_environment(env_raw, inherited, overrides)
    del env_raw, inherited, overrides
    def secret(name):
        need(name == 'ENTSOE_API_KEY', 'DEPLOYMENT_ENV')
        return PROVIDER['get_secret'](name, environment=env)
    CURRENT_PHASE = 'SOURCE_REQUEST'
    source, failure = CORE['request_source'](secret)
    if failure:
        return {'status': 'BLOCKED', 'phase': CURRENT_PHASE, 'cause': failure['cause'], 'comparison': None}
    CURRENT_PHASE = 'COMPARISON'
    need(capture(ROOT / 'data/raw/entsoe/load.csv', 1000, CORE['SNAPSHOT_LIMIT'])[1] == snapshot_identity, 'SNAPSHOT_DRIFT')
    comparison = CORE['sanitized_compare'](source, snapshot, dt.datetime.now(dt.timezone.utc), history)
    return {'status': 'PASS' if comparison['status'] == 'CHECKED' else 'BLOCKED',
            'phase': CURRENT_PHASE, 'cause': None if comparison['status'] == 'CHECKED' else comparison['cause'],
            'comparison': comparison if comparison['status'] == 'CHECKED' else None}


def main():
    try:
        report = inspect()
    except Exception as error:
        cause = str(error) if isinstance(error, Stop) and str(error) in CAUSES else 'EVIDENCE_UNVERIFIED'
        report = {'status': 'BLOCKED', 'phase': CURRENT_PHASE, 'cause': cause, 'comparison': None}
    print(json.dumps(report, allow_nan=False, sort_keys=True))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
