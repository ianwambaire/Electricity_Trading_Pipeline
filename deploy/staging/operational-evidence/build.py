"""Deterministic local bindings only. No installer, remote call or activation."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCES = {'bootstrap.py': HERE/'bootstrap.py', 'shared/__init__.py': ROOT/'src/shared/__init__.py'}
for name in ('forecast_publication', 'operational_evidence', 'operational_evidence_store', 'operational_evidence_producer', 'operational_capture'):
    SOURCES['shared/'+name+'.py'] = ROOT/'src/shared'/(name+'.py')
LAUNCHER = b'''#!/bin/sh
# Proposal only: separate guarded installation authorization required.
exec /usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/timeout --signal=TERM --kill-after=5s 30s /usr/bin/python3 -I -S -B /opt/powerflow/operational-evidence-v1/bootstrap.py "$@"
'''


def artifacts():
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in SOURCES.items()}
    uid = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    rule = '# Proposal only; no installation or new privileges authorized.\n'
    rule += 'ec2-user ALL=(root) NOPASSWD: NOSETENV: sha256:'+hashlib.sha256(LAUNCHER).hexdigest()+' /usr/local/sbin/powerflow-publish-operations ^--flow-run '+uid+' --state '+uid+'$\n'
    return {'TOOLS.json': (json.dumps(hashes,sort_keys=True,indent=2)+'\n').encode(),
            'powerflow-publish-operations': LAUNCHER, 'sudoers.rule': rule.encode()}


if __name__ == '__main__':
    for name, raw in artifacts().items():(HERE/name).write_bytes(raw)
    print('Local code-only bindings generated; no installation or activation.')
