"""Local immutable staging packaging using the existing web release builder.

No SSH, network, installation, service command or publication operation.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
REQUIRED=('api/src/api/app.py','api/src/api/forecast_source.py','api/src/api/operations_summary.py','api/src/shared/forecast_publication.py')


def builder():
    spec=importlib.util.spec_from_file_location('existing_web_release',ROOT/'scripts/prepare_web_release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def prepare(dist, output, release_id, *, root=ROOT, settings=None):
    tool=builder()
    settings=settings or json.loads((HERE/'release-settings.json').read_text())
    tool.require(settings['origin']=='https://staging.powerflowenergy.dev','staging_origin_only')
    for name in REQUIRED:
        tool.require((root/name.removeprefix('api/')).is_file(),'required_consistency_module_missing')
    manifest=tool.prepare(root,dist,settings,release_id)  # dry-run first
    tool.require(all(name in manifest['files'] for name in REQUIRED),'required_modules_not_packaged')
    for name,item in manifest['files'].items():
        if name.startswith('api/'):
            allowed=(re.fullmatch(r'api/src/(api|shared)/[A-Za-z_][A-Za-z0-9_]*\.py',name)
                     or name in ('api/requirements/api.lock','api/requirements/shared.txt'))
            tool.require(bool(allowed),'unapproved_backend_path')
    if output is None:return manifest
    written=tool.prepare(root,dist,settings,release_id,output)
    tool.require(manifest==written,'source_changed_during_packaging')
    tool.require(tool.verify_package(output)==manifest,'package_verification')
    # Reproducibility check: rebuilding the same manifest from identical inputs
    # must yield the exact original bytes; no new package is written here.
    repeated=tool.prepare(root,dist,settings,release_id)
    tool.require(repeated==manifest,'non_reproducible_inputs')
    for path in output.rglob('*'):
        if path.is_file():path.chmod(0o400)
    for path in sorted((p for p in output.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):path.chmod(0o500)
    output.chmod(0o500)
    tool.verify_package(output)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist',type=Path,required=True)
    parser.add_argument('--release-id',required=True)
    parser.add_argument('--write',type=Path,help='New canonical private directory outside repository; absent is dry-run')
    args=parser.parse_args()
    manifest=prepare(args.dist,args.write,args.release_id)
    raw=(json.dumps(manifest,indent=2)+'\n').encode()
    print(json.dumps({'local_only':True,'deployment_authorized':False,'release_id':manifest['release_id'],
        'release_manifest_sha256':hashlib.sha256(raw).hexdigest(),'files':len(manifest['files']),
        'bytes':sum(v['bytes'] for v in manifest['files'].values()),'sealed':args.write is not None}))


if __name__=='__main__':main()
