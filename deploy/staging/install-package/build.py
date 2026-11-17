#!/usr/bin/env python3
"""Local-only bundle builder. No Git, remote hosts, publication data or credentials."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[3]
ID='phase-staging-https-ready-20261026'
CANDIDATE=Path('/private/tmp/powerflow-react-stage-review-dudwnuhr/candidate')


def digest(b):return hashlib.sha256(b).hexdigest()


def archive(path,files):
    with path.open('xb') as out,gzip.GzipFile(filename='',mode='wb',fileobj=out,mtime=0) as compressed,tarfile.open(fileobj=compressed,mode='w|') as tar:
        for name,body in sorted(files.items()):
            t=tarfile.TarInfo(name);t.size=len(body);t.mode=0o600;t.mtime=0;tar.addfile(t,io.BytesIO(body))


def build(wheel_export,observations_path=None):
    os.umask(0o077);out=Path(tempfile.mkdtemp(prefix='powerflow-install-bundle-',dir='/private/tmp'))
    manifest_raw=(CANDIDATE/'release-manifest.json').read_bytes()
    assert digest(manifest_raw)=='50be8e7a20c462eb8850d9bf61b77bb655f687f85c725cbd3d903b7ff14aad27'
    manifest=json.loads(manifest_raw);release={}
    for name,item in manifest['files'].items():
        p=CANDIDATE/name;assert not p.is_symlink();body=p.read_bytes()
        assert len(body)==item['bytes'] and digest(body)==item['sha256'];release[name]=body
    assert len(release)==68
    release['release-manifest.json']=manifest_raw
    archive(out/'release.tar.gz',release)
    wheelmanifest=(ROOT/'deploy/staging/LINUX-WHEEL-MANIFEST.json').read_bytes()
    assert digest(wheelmanifest)=='1ae7da081a467988380614e346c01f256601369fd17196d635c6e71c7035693b'
    wm=json.loads(wheelmanifest);wheels={}
    expected={x['filename']:x for x in wm['wheels']}
    with tarfile.open(wheel_export,'r:') as tar:
        for m in tar:
            if m.isdir() and m.name in ('.','./'):continue
            name=m.name.removeprefix('./');assert m.isfile() and name not in wheels and name in {*expected,'manifest.json'}
            body=tar.extractfile(m).read()
            if name=='manifest.json':assert body==wheelmanifest
            else:assert len(body)==expected[name]['bytes'] and digest(body)==expected[name]['sha256']
            wheels[name]=body
    assert set(wheels)==set(expected)|{'manifest.json'}
    archive(out/'wheels.tar.gz',wheels)
    for name in ('install.py','publisher.py','cgroup_bpf.py','bootstrap.py'):(out/name).write_bytes((ROOT/'deploy/staging/install-package'/name).read_bytes())
    (out/'linux-regression-unittest.py').write_bytes((ROOT/'deploy/staging/linux-regression-unittest.py').read_bytes())
    (out/'activate-staging-https.py').write_bytes((ROOT/'deploy/staging/activate-staging-https.py').read_bytes())
    support=(ROOT/'deploy/preflight/nginx-http.conf').read_text()
    support='\n'.join(x for x in support.splitlines() if not x.strip().startswith('server_tokens '))+'\n'
    (out/'staging-support.conf').write_text(support)
    observations_path=observations_path or ROOT/'deploy/staging/PUBLICATION-PREFLIGHT-RESULTS.json'
    observations=json.loads(observations_path.read_bytes())
    inventory=json.loads((ROOT/'deploy/staging/PUBLICATION-INVENTORY.json').read_bytes())
    expected_sources={x['relative_path'] for x in inventory['files']}
    assert len(observations['sources'])==12 and {x['relative_path'] for x in observations['sources']}==expected_sources
    plan=[]
    for row in observations['sources']:
        assert row['stable_during_hash'] and row['summary']['stable_during_summary']
        plan.append({'relative_path':row['relative_path'],'source':observations['source_root']+'/'+row['relative_path'],
            'sha256':row['sha256'],'bytes':row['metadata']['bytes'],'uid':row['metadata']['uid'],'gid':row['metadata']['gid'],'mode':int(row['metadata']['mode'],8),
            'freshness':{'observed_as_of_utc':observations['as_of_utc'],'summary':row['summary']}})
    inventory=json.loads((ROOT/'deploy/staging/PUBLICATION-INVENTORY.json').read_bytes())
    backup=inventory['operational_snapshot'];meta=observations['snapshot_metadata']
    plan.append({'relative_path':'database/electricity_trading.db','source':backup['source'],'sha256':backup['expected_sha256'],
        'bytes':meta['bytes'],'uid':meta['uid'],'gid':meta['gid'],'mode':int(meta['mode'],8),
        'freshness':{'classification':'HISTORICAL','snapshot_cutoff_utc':'2026-10-26T02:22:00Z','accepted_by_owner':True,'not_current_operational_state':True}})
    artifact_names=('release.tar.gz','wheels.tar.gz','linux-regression-unittest.py','activate-staging-https.py','staging-support.conf')
    artifacts=[{'name':n,'bytes':(out/n).stat().st_size,'sha256':digest((out/n).read_bytes())} for n in artifact_names]
    code={n:digest((out/n).read_bytes()) for n in ('install.py','publisher.py','cgroup_bpf.py','bootstrap.py')}
    bundle={'format':1,'release_id':ID,'deployment_authorized':False,'control_hashes':code,'artifacts':artifacts,
        'release_archive_inventory':{n:{'bytes':len(b),'sha256':digest(b)} for n,b in release.items()},
        'wheel_archive_inventory':{n:{'bytes':len(b),'sha256':digest(b)} for n,b in wheels.items()},
        'publication_plan':plan,'publication_provenance':{'source_preflight_sha256':digest(observations_path.read_bytes()),'inventory_observed_as_of_utc':observations['as_of_utc'],'owner_accepts_historical_A1':True},
        'preserved_hashes':{'/etc/nginx/conf.d/powerflow.conf':'407a3ba22e0d2ef74ed638e942f1e7a91336342eed0074008bb8484d62928d7d','/etc/nginx/conf.d/powerflow-staging-acme.conf':'4d3f247575b0f5c1d447d6efac43711ab5f7c438185d32d2fa708e8bc1a41e4c'},
        'candidate_unit_sha256':digest(release['proposals/powerflow-candidate-api.service']),
        'candidate_env_sha256':digest(release['proposals/api.env.example']),
        'candidate_nginx_sha256':digest(release['proposals/staging.powerflowenergy.dev.conf']),
        'disk_budget_bytes':sum(x['bytes'] for x in plan)+sum(x['bytes'] for x in artifacts)*3+300*1024**2}
    raw=(json.dumps(bundle,indent=2)+'\n').encode();(out/'bundle.json').write_bytes(raw)
    print(json.dumps({'bundle_directory':str(out),'bundle_sha256':digest(raw),'bootstrap_sha256':code['bootstrap.py'],
                      'release_id':ID,'publication_data_files':len(plan),'publication_data_bytes':sum(x['bytes'] for x in plan),
                      'private_transfer_bytes':sum(p.stat().st_size for p in out.iterdir()),'disk_budget_plus_3GiB_bytes':bundle['disk_budget_bytes']+3*1024**3,'artifacts':artifacts,'control_hashes':code},indent=2))
    return out

if __name__=='__main__':
    import sys
    build(Path(sys.argv[1]),Path(sys.argv[2]) if len(sys.argv)>2 else None)
