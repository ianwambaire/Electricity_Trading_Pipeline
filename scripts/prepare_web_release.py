#!/usr/bin/env python3
"""Local-only PowerFlow release preparation. Dry-run by default; never deploys.

Allowlisted source/static files only. No Git, shell, network, AWS, SSH, dependency
installation, symlink switching, database access or production configuration write.
This artifact must still pass Linux/runtime/data/authentication staging gates.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

ROOT = Path(__file__).resolve().parents[1]
SETTING_KEYS = {'origin', 'cognito_issuer', 'cognito_client_id', 'cognito_domain', 'api_port', 'previous_release'}
STATIC_EXTENSIONS = {'.html','.js','.css','.svg','.png','.jpg','.jpeg','.webp','.ico','.woff','.woff2','.ttf','.txt','.json'}
FIXTURE_MARKERS = (b'preflight-fixture', b'LOCAL PREFLIGHT ONLY', b'visual-fixture', b'Isolated UI test')


def require(ok, code):
    if not ok:
        raise ValueError(code)


def settings_checked(settings):
    from urllib.parse import urlsplit
    require(type(settings) is dict and set(settings) == SETTING_KEYS, 'settings_keys')
    origin = urlsplit(settings['origin'])
    require(origin.scheme == 'https' and origin.hostname and origin.netloc == origin.hostname
            and not origin.path and not origin.query and not origin.fragment, 'origin_requires_exact_https_host')
    issuer = urlsplit(settings['cognito_issuer'])
    require(issuer.scheme == 'https' and issuer.netloc == 'cognito-idp.us-east-1.amazonaws.com'
            and re.fullmatch(r'/us-east-1_[A-Za-z0-9]+', issuer.path or '')
            and not issuer.query and not issuer.fragment, 'issuer')
    domain = urlsplit(settings['cognito_domain'])
    require(domain.scheme == 'https' and domain.hostname and domain.hostname.endswith('.amazoncognito.com')
            and domain.netloc == domain.hostname and not domain.path and not domain.query and not domain.fragment, 'cognito_domain')
    require(type(settings['api_port']) is int and settings['api_port'] == 8010, 'candidate_port_must_be_8010')
    client = settings['cognito_client_id']
    require(isinstance(client,str) and re.fullmatch(r'[a-z0-9]{10,64}', client)
            and not any(x in client for x in ('replace','example','approved','placeholder')), 'approved_public_client_id_required')
    previous = settings['previous_release']
    require(previous is None or isinstance(previous,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', previous), 'previous_release')
    return dict(settings)


def read_file(path):
    require(path.is_file() and not path.is_symlink(), 'regular_file_required')
    require(path.resolve(strict=True) == path.absolute(), 'symlink_ancestor_refused')
    require(path.stat().st_size <= 16*1024*1024, 'file_limit')
    return path.read_bytes()


def static_files(dist):
    require(dist.is_dir() and not dist.is_symlink(), 'dist_directory')
    paths = sorted(dist.rglob('*'))
    require(paths and len(paths) <= 2000, 'dist_file_count')
    result = {}
    for path in paths:
        require(not path.is_symlink(), 'dist_symlink')
        if path.is_dir():
            continue
        rel = path.relative_to(dist)
        require(not any(p.startswith('.') or p in ('src','tests','node_modules','data','database','deploy') for p in rel.parts), 'private_static_path')
        require((path.suffix.lower() in STATIC_EXTENSIONS or rel.as_posix() == 'fonts/SourceSans3-LICENSE.md') and path.suffix != '.map', 'static_extension')
        require(path.suffix != '.json' or rel.as_posix() == 'build-config.json', 'unexpected_static_json')
        body=read_file(path)
        require(not any(marker in body for marker in FIXTURE_MARKERS), 'fixture_static')
        require(b'-----BEGIN PRIVATE KEY-----' not in body and b'-----BEGIN RSA PRIVATE KEY-----' not in body
                and not re.search(rb'AKIA[A-Z0-9]{16}',body), 'obvious_secret_static')
        result['static/'+rel.as_posix()] = body
    require('static/index.html' in result, 'index_missing')
    require(re.search(rb'src="/assets/[^"/]+\.js"', result['static/index.html']), 'hashed_entry_missing')
    # Validate local HTML resources so an incomplete build cannot be packaged.
    for ref in re.findall(rb'(?:src|href)="(/[^"#]+)"', result['static/index.html']):
        require('static/'+ref.decode().lstrip('/') in result, 'html_resource_missing')
    return result


def check_build_provenance(files, settings):
    metadata=json.loads(files.get('static/build-config.json', b'null'))
    require(isinstance(metadata,dict) and metadata.get('schemaVersion') == 1 and metadata.get('apiBase') == '/api'
            and metadata.get('releaseEligible') is True and metadata.get('origin') == settings['origin'], 'release_build_provenance')
    public_config={'authority':settings['cognito_issuer'], 'domain':settings['cognito_domain'],
                   'clientId':settings['cognito_client_id'], 'redirectUri':settings['origin']+'/auth/callback',
                   'logoutUri':settings['origin']+'/', 'apiBase':'/api'}
    public_digest=hashlib.sha256(json.dumps(public_config,separators=(',',':')).encode()).hexdigest()
    require(metadata.get('publicConfigSha256') == public_digest, 'public_config_digest')
    javascript=b'\n'.join(body for name,body in files.items() if name.endswith('.js'))
    require(all(value.encode() in javascript for value in (settings['cognito_client_id'], settings['cognito_issuer'],
            settings['origin']+'/auth/callback', settings['origin']+'/')), 'built_oidc_settings_mismatch')

def prepare(root, dist, settings, release_id, output=None):
    settings=settings_checked(settings)
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', release_id), 'release_id')
    require(release_id != settings['previous_release'], 'previous_equals_candidate')
    files=static_files(dist)
    check_build_provenance(files,settings)
    for name in ('api','shared'):
        paths=sorted((root/'src'/name).glob('*.py'))
        require(paths, 'api_source_missing')
        for path in paths: files['api/src/'+name+'/'+path.name]=read_file(path)
    for name in ('api.lock','shared.txt'):
        files['api/requirements/'+name]=read_file(root/'requirements'/name)
    for name in ('powerflow-react-api.service','nginx-http.conf','security-headers.conf','powerflowenergy.dev.conf','api.env.example','cognito-production-client.json'):
        files['proposals/'+name]=read_file(root/'deploy/preflight'/name)
    manifest={
        'format':1,'release_id':release_id,'deployment_authorized':False,
        'settings':settings,'callback_url':settings['origin']+'/auth/callback',
        'logout_url':settings['origin']+'/',
        'rollback':{'previous_release':settings['previous_release'],'automatic_switch':False,
                    'database_restore':False,'streamlit_stop_authorized':False},
        'excluded':['datasets','databases','model_artifacts','environment_files','credentials','node_modules','tests','source_maps','python_virtualenv'],
        'remaining_gates':['approved_release_and_identity','linux_dependency_imports','nginx_and_systemd_syntax','published_data_and_forecast_availability','authentication_roles_and_logout','capacity_and_tls','recovery_and_rollback'],
        'files':{name:{'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()} for name,body in sorted(files.items())},
    }
    require(sum(len(body) for body in files.values()) <= 64*1024*1024, 'package_size_limit')
    if output is not None:
        require(output.is_absolute() and output.parent.resolve(strict=True) == output.parent, 'canonical_output')
        require(not os.path.lexists(output), 'output_exists')
        require(root.resolve() != output and root.resolve() not in output.parents, 'output_outside_repository_required')
        parent=output.parent.stat()
        require(parent.st_uid == os.geteuid() and parent.st_mode & 0o022 == 0, 'output_parent_permissions')
        fs=os.statvfs(output.parent)
        require(fs.f_bavail*fs.f_frsize >= 2*sum(len(b) for b in files.values())+64*1024*1024, 'free_space')
        output.mkdir(mode=0o700)
        # No deletion on failure: preserve partial local artifact for review.
        for name,body in [*sorted(files.items()),('release-manifest.json',(json.dumps(manifest,indent=2)+'\n').encode())]:
            dest=output/name; dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as handle:handle.write(body)
    return manifest


def verify_package(directory):
    require(directory.is_absolute() and directory.resolve(strict=True) == directory, 'canonical_package')
    manifest=json.loads(read_file(directory/'release-manifest.json'))
    require(manifest.get('format') == 1 and manifest.get('deployment_authorized') is False, 'manifest_format')
    settings_checked(manifest['settings'])
    check_build_provenance(static_files(directory/'static'),manifest['settings'])
    expected=set(manifest['files'])|{'release-manifest.json'}
    actual=set()
    for path in directory.rglob('*'):
        require(not path.is_symlink(), 'package_symlink')
        if path.is_file():actual.add(path.relative_to(directory).as_posix())
    require(actual == expected, 'package_inventory')
    for name,item in manifest['files'].items():
        relative=Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts, 'manifest_path')
        body=read_file(directory/relative)
        require(len(body) == item['bytes'] and hashlib.sha256(body).hexdigest() == item['sha256'], 'package_digest')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist',type=Path,default=ROOT/'frontend/dist')
    parser.add_argument('--settings',type=Path)
    parser.add_argument('--release-id')
    parser.add_argument('--verify',type=Path,help='Read-only verification of an existing local package')
    parser.add_argument('--write',type=Path,help='Explicit new local output directory; absent means dry-run')
    args=parser.parse_args()
    try:
        if args.verify:
            require(args.settings is None and args.release_id is None and args.write is None, 'verify_exclusive')
            result=verify_package(args.verify)
        else:
            require(args.settings is not None and args.release_id is not None, 'settings_and_release_required')
            settings=json.loads(read_file(args.settings))
            result=prepare(ROOT,args.dist,settings,args.release_id,args.write)
        print(json.dumps({'status':'passed','mode':'verify' if args.verify else 'write' if args.write else 'dry-run',
                          'release_id':result['release_id'],'file_count':len(result['files']),
                          'total_bytes':sum(x['bytes'] for x in result['files'].values()),
                          'deployment_authorized':False}))
        return 0
    except (OSError,ValueError,TypeError,KeyError):
        print(json.dumps({'status':'failed','partial_artifacts_retained':True,'deployment_authorized':False}))
        return 1


if __name__=='__main__':raise SystemExit(main())
