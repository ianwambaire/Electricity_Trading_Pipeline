"""Local disposable release artifacts only; no network, deployment or Git."""
import importlib.util
import json
from pathlib import Path
import stat

import pytest

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('web_release',ROOT/'scripts/prepare_web_release.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


@pytest.fixture
def inputs(tmp_path):
    root=tmp_path/'repo'; dist=root/'frontend/dist'; (dist/'assets').mkdir(parents=True)
    (dist/'index.html').write_text('<script src="/assets/index-abcd.js"></script>')
    (dist/'assets/index-abcd.js').write_text('console.log("fixture-free application")')
    for name in ('api','shared'):
        path=root/'src'/name;path.mkdir(parents=True);(path/'__init__.py').write_text('')
    (root/'requirements').mkdir()
    for name in ('api.lock','shared.txt'):(root/'requirements'/name).write_text('# locked fixture\n')
    proposals=root/'deploy/preflight';proposals.mkdir(parents=True)
    for name in ('powerflow-react-api.service','nginx-http.conf','security-headers.conf','powerflowenergy.dev.conf','api.env.example','cognito-production-client.json'):
        (proposals/name).write_text('review-only')
    staging=root/'deploy/staging';staging.mkdir(parents=True)
    for name in ('staging.powerflowenergy.dev.conf','powerflow-candidate-api.service','activate-staging.sh','rollback-staging.sh','switch-candidate.sh','api.env.example'):
        (staging/name).write_text('staging-review-only')
    settings=dict(origin='https://staging.powerflowenergy.dev',cognito_issuer='https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool',cognito_client_id='testclient1234567890',cognito_domain='https://test.auth.us-east-1.amazoncognito.com',api_port=8010,previous_release='old-1')
    (dist/'assets/index-abcd.js').write_text(json.dumps([settings['cognito_client_id'],settings['cognito_issuer'],settings['origin']+'/auth/callback',settings['origin']+'/']))
    import hashlib
    public={'authority':settings['cognito_issuer'],'domain':settings['cognito_domain'],'clientId':settings['cognito_client_id'],'redirectUri':settings['origin']+'/auth/callback','logoutUri':settings['origin']+'/', 'apiBase':'/api'}
    metadata=dict(schemaVersion=1,apiBase='/api',releaseEligible=True,origin=settings['origin'],publicConfigSha256=hashlib.sha256(json.dumps(public,separators=(',',':')).encode()).hexdigest())
    (dist/'build-config.json').write_text(json.dumps(metadata))
    return root,dist,settings


def test_dry_run_writes_nothing_and_records_rollback(inputs,tmp_path):
    root,dist,settings=inputs
    before=set(tmp_path.rglob('*'))
    manifest=release.prepare(root,dist,settings,'candidate-2')
    assert set(tmp_path.rglob('*'))==before
    assert manifest['deployment_authorized'] is False
    assert manifest['rollback']['previous_release']=='old-1'
    assert manifest['rollback']['database_restore'] is False
    assert 'static/assets/index-abcd.js' in manifest['files']
    assert 'proposals/staging.powerflowenergy.dev.conf' in manifest['files']
    assert 'proposals/powerflowenergy.dev.conf' not in manifest['files']
    assert 'proposals/cognito-production-client.json' not in manifest['files']


def test_write_private_package_hashes_and_refuse_overwrite(inputs,tmp_path):
    import hashlib
    root,dist,settings=inputs; output=tmp_path/'release'
    manifest=release.prepare(root,dist,settings,'candidate-2',output)
    assert stat.S_IMODE(output.stat().st_mode)==0o700
    for name,item in manifest['files'].items():
        path=output/name
        assert stat.S_IMODE(path.stat().st_mode)==0o600
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
    assert json.loads((output/'release-manifest.json').read_text())==manifest
    with pytest.raises(ValueError):release.prepare(root,dist,settings,'candidate-2',output)


@pytest.mark.parametrize('extra,body',[('.env','secret'),('assets/index.js.map','{}'),('tests/test.js','fake'),('assets/key.pem','fake')])
def test_private_or_development_artifacts_refused(inputs,extra,body):
    root,dist,settings=inputs;path=dist/extra;path.parent.mkdir(exist_ok=True);path.write_text(body)
    with pytest.raises(ValueError):release.prepare(root,dist,settings,'candidate-2')


@pytest.mark.parametrize('body',[b'LOCAL PREFLIGHT ONLY',b'-----BEGIN PRIVATE KEY-----',b'AKIA1234567890ABCDEF'])
def test_obvious_secret_or_fixture_static_refused(inputs,body):
    root,dist,settings=inputs;(dist/'assets/index-abcd.js').write_bytes(body)
    with pytest.raises(ValueError):release.prepare(root,dist,settings,'candidate-2')


def test_symlink_and_missing_resource_refused(inputs,tmp_path):
    root,dist,settings=inputs;(dist/'assets/escape.js').symlink_to(tmp_path/'other')
    with pytest.raises(ValueError):release.prepare(root,dist,settings,'candidate-2')
    (dist/'assets/escape.js').unlink();(dist/'index.html').write_text('<script src="/assets/missing.js"></script>')
    with pytest.raises(ValueError):release.prepare(root,dist,settings,'candidate-2')


@pytest.mark.parametrize('key,value',[('api_port',8000),('origin','http://staging.example'),('origin','https://example/path'),('cognito_client_id','replacewithapprovedclientid'),('previous_release','../old'),('client_secret','secret')])
def test_settings_invalid_or_secret_keys_refused(inputs,key,value):
    root,dist,settings=inputs;settings[key]=value
    with pytest.raises(ValueError):release.prepare(root,dist,settings,'candidate-2')


def test_repository_output_and_previous_candidate_refused(inputs):
    root,dist,settings=inputs
    with pytest.raises(ValueError):release.prepare(root,dist,settings,'candidate-2',root/'release')
    with pytest.raises(ValueError):release.prepare(root,dist,settings,'old-1')


def test_readonly_verification_rejects_tamper_and_extra_files(inputs,tmp_path):
    root,dist,settings=inputs;output=tmp_path/'release'
    manifest=release.prepare(root,dist,settings,'candidate-2',output)
    assert release.verify_package(output)==manifest
    path=output/'static/assets/index-abcd.js';original=path.read_bytes();path.write_bytes(b'tamper')
    with pytest.raises(ValueError):release.verify_package(output)
    path.write_bytes(original);(output/'unexpected.txt').write_text('extra')
    with pytest.raises(ValueError):release.verify_package(output)


def test_built_oidc_configuration_must_match_settings(inputs):
    root,dist,settings=inputs;settings['origin']='https://another.example'
    with pytest.raises(ValueError):release.prepare(root,dist,settings,'candidate-2')


@pytest.mark.parametrize('key,value',[('releaseEligible',False),('origin','https://other.example'),('publicConfigSha256','0'*64),('apiBase','http://localhost:8000')])
def test_build_provenance_must_match_reviewed_settings(inputs,key,value):
    root,dist,settings=inputs;path=dist/'build-config.json';metadata=json.loads(path.read_text());metadata[key]=value;path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):release.prepare(root,dist,settings,'candidate-2')


def test_static_font_license_is_kept_but_arbitrary_markdown_refused(tmp_path):
    dist=tmp_path/'dist';dist.mkdir();(dist/'assets').mkdir();(dist/'fonts').mkdir()
    (dist/'index.html').write_text('<script src="/assets/index-safe.js"></script>')
    (dist/'assets/index-safe.js').write_text('export const safe=true')
    (dist/'fonts/SourceSans3-LICENSE.md').write_text('Source Sans 3 font license')
    assert 'static/fonts/SourceSans3-LICENSE.md' in release.static_files(dist)
    (dist/'private-notes.md').write_text('not a permitted distribution asset')
    with pytest.raises(ValueError,match='static_extension'):release.static_files(dist)
