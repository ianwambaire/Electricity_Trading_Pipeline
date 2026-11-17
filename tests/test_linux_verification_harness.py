"""Offline structural/inventory checks; never invokes Docker or installs packages."""
import ast
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).parents[1]


def test_private_venv_mount_supports_shared_objects_without_changing_scratch():
    driver=(ROOT/'deploy/staging/run-linux-verification.py').read_text()
    phase=(ROOT/'deploy/staging/linux-dependency-phase.py').read_text()
    assert '/venv:rw,exec,nosuid,nodev,size=512m,mode=1777' in driver
    assert '/tmp:rw,nosuid,nodev,size=768m,mode=1777' in driver
    assert '/venv/api-verify' in phase and '/tmp/api-verify' not in phase
    assert "'--network','none'" in driver
    assert "('--privileged'" not in driver and "'--network','host'" not in driver
    assert "('acquire',600),('offline',300)" in driver and 'started+895' in driver
    assert "'--no-index'" in phase and "'--only-binary=:all:'" in phase


def test_exact_wheel_inventory_and_immutable_lock_binding():
    data=(ROOT/'deploy/staging/LINUX-WHEEL-MANIFEST.json').read_bytes();r=json.loads(data)
    assert hashlib.sha256(data).hexdigest()=='1ae7da081a467988380614e346c01f256601369fd17196d635c6e71c7035693b'
    assert r['lock_sha256']=='b1d8bbbec84a08b651b7bdc0b96e5bb94bf6c527297e037357702de00bcc84e3'
    assert len(r['wheels'])==26 and len({w['name'] for w in r['wheels']})==26
    assert all(w['filename'].endswith('.whl') and len(w['sha256'])==64 for w in r['wheels'])
    assert next(w for w in r['wheels'] if w['name']=='python-dateutil')['version']=='3.0.0'


def test_harness_and_regression_sources_compile_without_execution():
    for name in ('linux-dependency-phase.py','run-linux-verification.py','linux-regression-unittest.py'):
        p=ROOT/'deploy/staging'/name;compile(p.read_bytes(),str(p),'exec');ast.parse(p.read_bytes())
