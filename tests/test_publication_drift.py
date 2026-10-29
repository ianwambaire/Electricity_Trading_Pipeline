"""Local metadata-fixture regressions; never remote calls or production data writes."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import pytest
ROOT=Path(__file__).parents[1]
helper=runpy.run_path(str(ROOT/'deploy/staging/prepare-publication-revision.py'))
inspection=json.loads((ROOT/'deploy/staging/PUBLICATION-DRIFT-RESULTS.json').read_bytes())
approved=json.loads((ROOT/'deploy/staging/install-package/BUNDLE-MANIFEST.json').read_bytes())
previous=json.loads((ROOT/'deploy/staging/PUBLICATION-PREFLIGHT-RESULTS.json').read_bytes())


def test_revision_only_adopts_verified_observations_and_remains_unapproved():
    revision=helper['prepare'](inspection,approved,previous)
    assert len(revision['sources'])==12 and len(revision['changes'])==5
    assert not revision['publication_authorized']
    assert revision['snapshot_hash']['sha256']==approved['publication_plan'][-1]['sha256']
    assert sum(x['metadata']['bytes'] for x in revision['sources'])+revision['snapshot_metadata']['bytes']==102895837

@pytest.mark.parametrize('change',['unstable','wrong_source','permissions','sensitive','bad_timestamps','snapshot_changed','unexpected_source'])
def test_revision_rejects_unsafe_or_unverified_refresh(change):
    report=copy.deepcopy(inspection);r=report['files'][0]
    if change=='unstable':r['stable_across_inspection']=False
    elif change=='wrong_source':r['source']='/unapproved'
    elif change=='permissions':r['metadata']['mode']='0o666'
    elif change=='sensitive':r['summary']['sensitivity_review_required']=True
    elif change=='bad_timestamps':r['summary']['invalid_timestamp_rows']=1
    elif change=='snapshot_changed':report['files'][-1]['sha256']='a'*64
    elif change=='unexpected_source':r['relative_path']='data/not-approved.csv'
    with pytest.raises(AssertionError):helper['prepare'](report,approved,previous)


def test_original_R2_behavior_and_new_local_permission_fix_are_bounded():
    for name in ('bootstrap.py','install.py'):
        new=(ROOT/'deploy/staging/install-package'/name).read_text()
        original=new.replace("INCOMING=Path('/home/ec2-user/powerflow-staging-incoming-'+ID+'-r2')","INCOMING=Path('/home/ec2-user/powerflow-staging-incoming-'+ID)")
        if name=='install.py':
            original=original.replace("    else:\n        path.mkdir(mode=mode)\n        # mkdir's mode is filtered by umask077; apply the reviewed mode explicitly.\n        # Existing directories are never chmodded by this helper.\n        path.chmod(mode)","    else:path.mkdir(mode=mode)")
            start=original.index('    except OSError as error:');end=original.index('    if CONTROL.is_dir():\n        # Exclusive output captures',start)
            original=original[:start]+original[end:]
        assert hashlib.sha256(original.encode()).hexdigest()==approved['control_hashes'][name]
    for name in ('publisher.py','cgroup_bpf.py'):
        assert hashlib.sha256((ROOT/'deploy/staging/install-package'/name).read_bytes()).hexdigest()==approved['control_hashes'][name]


def test_diagnostic_exact_scope_and_local_csv_checks(tmp_path):
    m=runpy.run_path(str(ROOT/'deploy/staging/diagnose-publication-drift.py'))
    assert {(x['source'],x['sha256']) for x in m['PLAN']}=={(x['source'],x['sha256']) for x in approved['publication_plan']}
    f=tmp_path.resolve()/'market.csv';f.write_text('timestamp,value\n2026-10-26T12:00:00Z,1\n')
    assert m['stable_hash'](f)['sha256']==hashlib.sha256(f.read_bytes()).hexdigest()
    assert m['contents_summary'](f)['invalid_timestamp_rows']==0
    f.write_text('timestamp,value\ninvalid,1\n')
    assert m['contents_summary'](f)['invalid_timestamp_rows']==1
