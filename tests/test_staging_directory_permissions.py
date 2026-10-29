"""Local-only regressions for restrictive umask and failed subprocess spawn evidence."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('fixed_installer',ROOT/'deploy/staging/install-package/install.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

@pytest.mark.parametrize('mode',[0o755,0o750,0o700])
def test_explicit_new_directory_mode_survives_private_umask(tmp_path,mode):
    path=tmp_path.resolve()/'new-parent';old=os.umask(0o077)
    try:installer.mkdir_new_or_safe(path,mode)
    finally:os.umask(old)
    assert path.stat().st_mode&0o777==mode


def test_existing_directory_is_not_silently_repermissioned(tmp_path,monkeypatch):
    path=tmp_path.resolve();monkeypatch.setattr(installer.Path,'stat',lambda p:SimpleNamespace(st_mode=0o40700,st_uid=0))
    calls=[];monkeypatch.setattr(installer.Path,'chmod',lambda *args:calls.append(args))
    installer.mkdir_new_or_safe(path,0o755)
    assert not calls


def test_permission_error_reports_operation_uid_and_errno_without_environment(tmp_path,monkeypatch):
    monkeypatch.setattr(installer,'CONTROL',tmp_path.resolve())
    def denied(*args,**kwargs):raise PermissionError(13,'Permission denied','/opt/powerflow/releases/approved/.venv-api/bin/python')
    monkeypatch.setattr(installer.subprocess,'run',denied)
    with pytest.raises(RuntimeError,match='candidate_offline_regressions_spawn_errno_13'):
        installer.run('candidate-offline-regressions',['/opt/powerflow/releases/approved/.venv-api/bin/python','-B','probe.py'],uid=992,gid=992,env={'SECRET':'never-record'})
    logs=list(tmp_path.glob('*.spawn-error.json'));assert len(logs)==1
    data=json.loads(logs[0].read_bytes());assert data['errno']==13 and data['requested_uid']==992 and data['operation']=='subprocess_spawn'
    assert 'SECRET' not in logs[0].read_text() and 'never-record' not in logs[0].read_text()
    assert logs[0].stat().st_mode&0o777==0o600


def load_resume():
    spec=importlib.util.spec_from_file_location('resume_R2',ROOT/'deploy/staging/resume-r2-install.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_guarded_repair_checks_all_parents_before_any_change(monkeypatch):
    resume=load_resume();paths=[(Path('/opt/powerflow'),0,0o755),(Path('/opt/powerflow/releases'),0,0o755),(Path('/var/www/powerflow-staging'),0,0o755),(Path('/var/www/powerflow-staging/releases'),0,0o755),(Path('/srv/powerflow'),992,0o750)]
    states={p:SimpleNamespace(st_mode=0o40700,st_uid=0,st_gid=gid) for p,gid,mode in paths};changes=[]
    monkeypatch.setattr(resume.Path,'is_symlink',lambda p:False)
    monkeypatch.setattr(resume.Path,'stat',lambda p:states[p])
    def change(p,mode):changes.append((p,mode));states[p].st_mode=0o40000|mode
    monkeypatch.setattr(resume.Path,'chmod',change)
    states[paths[-1][0]].st_gid=1
    with pytest.raises(RuntimeError,match='repair_parent_metadata_changed'):resume.repair_parent_modes(paths,992)
    assert changes==[]
    states[paths[-1][0]].st_gid=992;resume.repair_parent_modes(paths,992)
    assert changes==[(p,mode) for p,gid,mode in paths]


def test_resume_never_republishes_reinstalls_or_starts_services():
    source=(ROOT/'deploy/staging/resume-r2-install.py').read_text()
    assert 'publisher.publish' not in source and 'm.install(' not in source
    assert "'start'" not in source and "'reload'" not in source and "'daemon-reload'" not in source
    assert 'resume-r2.started' in source and 'EXPECTED_BUNDLE=' in source
    assert "['/usr/bin/systemd-analyze','verify'" in source
    compile(source,'resume-r2-install.py','exec')
