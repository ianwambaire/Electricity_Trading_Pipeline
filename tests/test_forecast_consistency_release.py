"""Reproducible local packaging with synthetic build inputs, no deployment."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat

import pytest
from test_web_release_preparation import inputs

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('consistency_release',ROOT/'deploy/staging/forecast-consistency-release/prepare.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


def required(root):
    for name in release.REQUIRED:
        p=root/name.removeprefix('api/');p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# synthetic runtime module\n')


def writable(directory):
    directory.chmod(0o700)
    for p in directory.rglob('*'):
        p.chmod(0o700 if p.is_dir() else 0o600)


def test_manifest_reproducibility_required_modules_and_private_exclusions(inputs,tmp_path):
    root,dist,settings=inputs;required(root)
    for name in ['.env','database/private.db','deploy/staging/a03-price-recovery/final/private.json','tests/synthetic.py']:
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('must not be packaged')
    first=release.prepare(dist,None,'consistency-1',root=root,settings=settings)
    second=release.prepare(dist,None,'consistency-1',root=root,settings=settings)
    raw=lambda m:(json.dumps(m,indent=2)+'\n').encode()
    assert hashlib.sha256(raw(first)).hexdigest()==hashlib.sha256(raw(second)).hexdigest()
    assert all(name in first['files'] for name in release.REQUIRED)
    assert not any('a03-price-recovery' in name or 'private.db' in name or name.endswith('.env') or name.startswith('tests/') for name in first['files'])
    output=tmp_path/'sealed'
    try:
        written=release.prepare(dist,output,'consistency-1',root=root,settings=settings)
        assert release.builder().verify_package(output)==written==first
        assert stat.S_IMODE(output.stat().st_mode)==0o500
        assert all(stat.S_IMODE(p.stat().st_mode)==0o400 for p in output.rglob('*') if p.is_file())
        with pytest.raises(ValueError):release.prepare(dist,output,'consistency-1',root=root,settings=settings)
    finally:
        if output.exists():writable(output)


def test_missing_selector_and_non_staging_origin_are_blockers(inputs):
    root,dist,settings=inputs
    with pytest.raises(ValueError,match='required_consistency_module_missing'):
        release.prepare(dist,None,'candidate',root=root,settings=settings)
    required(root);settings['origin']='https://powerflowenergy.dev'
    with pytest.raises(ValueError,match='staging_origin_only'):
        release.prepare(dist,None,'candidate',root=root,settings=settings)


def test_local_build_and_package_tampering_are_rejected(inputs,tmp_path):
    root,dist,settings=inputs;required(root)
    metadata=json.loads((dist/'build-config.json').read_text());metadata['releaseEligible']=False
    (dist/'build-config.json').write_text(json.dumps(metadata))
    with pytest.raises(ValueError,match='release_build_provenance'):
        release.prepare(dist,None,'candidate',root=root,settings=settings)
    metadata['releaseEligible']=True;(dist/'build-config.json').write_text(json.dumps(metadata))
    out=tmp_path/'candidate'
    try:
        release.prepare(dist,out,'candidate',root=root,settings=settings)
        path=out/'api/src/api/forecast_source.py';path.chmod(0o600);path.write_text('changed bytes')
        with pytest.raises(ValueError,match='package_digest'):release.builder().verify_package(out)
    finally:
        if out.exists():writable(out)


def rollback_helper():
    spec=importlib.util.spec_from_file_location('rollback_state',ROOT/'deploy/staging/forecast-consistency-release/rollback_state.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def rollback_record():
    return dict(schema_version=1,previous_backend='/opt/powerflow/releases/context-hotfix',
        previous_static='/var/www/powerflow-staging/releases/original-react',
        installed_backend='/opt/powerflow/releases/consistency-v1',
        installed_static='/var/www/powerflow-staging/releases/consistency-v1',
        original_env_sha256='a'*64,installed_env_sha256='b'*64,
        environment_backup='/var/lib/powerflow-staging/forecast-consistency-20261101-v1/previous-api.env',
        environment_uid=0,environment_gid=0,environment_mode='0600')


def test_independent_backend_static_and_exact_environment_rollback():
    restore=rollback_helper().restore_targets(rollback_record())
    assert restore['backend'].endswith('/context-hotfix')
    assert restore['static'].endswith('/original-react')
    assert restore['environment_sha256']=='a'*64
    assert restore['backend'].split('/')[-1]!=restore['static'].split('/')[-1]


@pytest.mark.parametrize('key,value',[
    ('previous_backend','/opt/powerflow/releases/../production'),
    ('previous_static','/var/www/powerflow/releases/production'),
    ('schema_version',True),('environment_uid',False),('environment_mode','0644'),('environment_uid',992),('original_env_sha256','unknown'),
    ('environment_backup','/etc/powerflow/react-api.env')])
def test_rollback_record_rejects_cross_scope_and_inexact_environment(key,value):
    record=rollback_record();record[key]=value
    with pytest.raises(ValueError):rollback_helper().validate(record)


def test_supported_build_uses_explicit_public_settings_and_refuses_overwrite(tmp_path,monkeypatch):
    from types import SimpleNamespace
    spec=importlib.util.spec_from_file_location('staging_build',ROOT/'deploy/staging/forecast-consistency-release/build.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    calls=[]
    def run(command,**kwargs):
        calls.append((command,kwargs));return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess,'run',run)
    monkeypatch.setattr(module.os,'umask',lambda _:None)
    out=tmp_path/'new-dist'
    module.build(out)
    command,kwargs=calls[0]
    assert command[:3]==['npm','run','build:release']
    assert command[command.index('--origin')+1]=='https://staging.powerflowenergy.dev'
    assert kwargs['env']['VITE_COGNITO_CLIENT_ID']
    assert kwargs['env']['VITE_COGNITO_AUTHORITY'].startswith('https://cognito-idp.')
    out.mkdir()
    with pytest.raises(ValueError,match='existing_output'):module.build(out)
    assert len(calls)==1
