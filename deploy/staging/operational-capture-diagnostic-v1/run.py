"""Reuse the separately preserved one-attempt supervisor, hash verified first."""
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
HERE=Path(__file__).resolve().parent
SUPERVISOR=HERE.parent/'operational-delivery-diagnostic-v1/run.py'
EXPECTED='44937a3788a52884c6a8bacb70fb207a341152d1ebf770d460b577b8fad2e9e9'
def supervisor():
    with os.fdopen(os.open(SUPERVISOR,os.O_RDONLY|os.O_NOFOLLOW),'rb') as f:
        info=os.fstat(f.fileno());assert stat.S_ISREG(info.st_mode) and info.st_size<16384
        raw=f.read(16385)
    assert hashlib.sha256(raw).hexdigest()==EXPECTED
    import types
    m=types.ModuleType('verified_log_supervisor');m.__file__=str(SUPERVISOR)
    exec(compile(raw,'<verified-readonly-supervisor>','exec'),m.__dict__)
    m.HERE=HERE
    return m
if __name__=='__main__':
    try:raise SystemExit(supervisor().main())
    except Exception:print('{"status":"BLOCKED","reason":"SUPERVISOR_INTEGRITY","ssh_attempts":0}');raise SystemExit(1)
