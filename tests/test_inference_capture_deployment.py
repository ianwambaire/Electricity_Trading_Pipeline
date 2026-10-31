"""Local/mocked validation only; these tests never invoke SSH or production."""
import ast
import base64
import hashlib
import json
from pathlib import Path
import runpy

import pytest

ROOT=Path(__file__).parents[1]
PACKAGE=ROOT/'deploy/staging/inference-evidence-deployment'


def module():
    return runpy.run_path(str(PACKAGE/'deploy-capture.py'),run_name='local_test_only')


def test_exact_three_payloads_and_support_hashes():
    config=module()['CONFIG']
    assert set(config['files'])=={'src/models/next24h.py','src/models/next24h_production.py','src/models/inference_evidence.py'}
    for path,item in config['files'].items():
        raw=base64.b64decode(item['base64'],validate=True)
        assert raw==(ROOT/path).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==item['sha256']
        compile(raw,path,'exec')
    for path,digest in config['dependencies'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest


def test_verified_pre_capture_reconstruction_and_read_only_result():
    report=json.loads((PACKAGE/'PREFLIGHT-RESULTS.json').read_text())
    assert report['read_only'] and report['stage']=='complete' and not report['errors']
    assert report['schedule_verified'] and not report['active_runs']
    assert all(v['matches'] for v in json.loads((PACKAGE/'BASELINE-COMPARISON.json').read_text()).values())


def test_service_gate_excludes_dynamic_memory_counters():
    tree=ast.parse((PACKAGE/'deploy-capture.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='identities')
    assert 'MemoryCurrent' not in ast.unparse(function)
    assert 'MainPID' in ast.unparse(function)


def test_no_production_triggers_or_service_mutations():
    source=(PACKAGE/'deploy-capture.py').read_text()
    for forbidden in ['restart','reload','set_state','PATCH','git rev-parse','model.predict','run_next24h_forecast(']:
        assert forbidden not in source.replace("'service_restart':False",'')
    assert "['RUNNING','PENDING','CANCELLING','PAUSED']" in source
    assert "schedule_window_under_ten_minutes" in source
    assert "source_changed_before_backup" in source
    assert "backup_readback" in source


def test_write_path_is_exclusive_and_does_not_follow_symlinks(tmp_path):
    m=module();path=tmp_path/'private';m['private_write'](path,b'one',0o600)
    with pytest.raises(FileExistsError):m['private_write'](path,b'two',0o600)
    link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(FileExistsError):m['private_write'](link,b'two',0o600)
    assert path.read_bytes()==b'one'


def test_guards_reject_before_any_write(monkeypatch):
    m=module();monkeypatch.setattr(m['os'],'geteuid',lambda:0)
    with pytest.raises(RuntimeError,match='identity_or_root'):m['main']('apply')
    assert not m['RESULT']['installed']


def test_runner_binds_payload_hash_and_timeouts():
    raw=(PACKAGE/'deploy-capture.py').read_bytes();runner=(PACKAGE/'run-deployment.py').read_text()
    assert hashlib.sha256(raw).hexdigest() in runner
    assert '90s' in runner and 'kill-after=5s' in runner and 'StrictHostKeyChecking=yes' in runner
    ast.parse(runner)
