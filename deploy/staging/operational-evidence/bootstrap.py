"""Root-owned isolated entrypoint proposal. Never executes from worker checkout."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import types

BASE = Path('/opt/powerflow/operational-evidence-v1')
FILES = {'bootstrap.py', 'shared/__init__.py', 'shared/forecast_publication.py',
         'shared/operational_evidence.py', 'shared/operational_evidence_store.py',
         'shared/operational_evidence_producer.py', 'shared/operational_capture.py'}


def read(path):
    for p in (path, *path.parents):
        s = p.lstat()
        if s.st_uid != 0 or s.st_mode & 0o022 or stat.S_ISLNK(s.st_mode):raise ValueError('IMMUTABLE_CODE_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        s = os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_size > 262144:raise ValueError('CODE_METADATA')
        return f.read(262145)


def load():
    if Path(__file__) != BASE/'bootstrap.py' or os.getuid() != 0 or os.geteuid() != 0:raise ValueError('INSTALLED_ENTRYPOINT_REQUIRED')
    manifest = json.loads(read(BASE/'TOOLS.json'))
    if set(manifest) != FILES:raise ValueError('CLOSURE')
    blobs = {name: read(BASE/name) for name in FILES}
    if any(hashlib.sha256(blob).hexdigest() != manifest[name] for name, blob in blobs.items()):raise ValueError('CODE_HASH')
    package = types.ModuleType('shared'); package.__path__ = [];sys.modules['shared'] = package
    exec(compile(blobs['shared/__init__.py'], '<verified-operational-package>', 'exec'), package.__dict__)
    for name in ('forecast_publication', 'operational_evidence', 'operational_evidence_store', 'operational_evidence_producer', 'operational_capture'):
        module = types.ModuleType('shared.'+name); module.__package__ = 'shared'
        sys.modules[module.__name__] = module; setattr(package, name, module)
        exec(compile(blobs['shared/'+name+'.py'], '<verified-operational-code>', 'exec'), module.__dict__)
    return sys.modules['shared.operational_capture']


if __name__ == '__main__':
    try:
        result, status = load().main(sys.argv[1:])
    except Exception:
        result, status = {'status': 'FAILED', 'reason': 'IMMUTABLE_RUNTIME_UNVERIFIED'}, 1
    print(json.dumps(result));raise SystemExit(status)
