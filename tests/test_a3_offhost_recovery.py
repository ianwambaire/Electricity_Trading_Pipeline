"""Local disposable fixtures and fake S3 only; never AWS or SSH."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('a3', ROOT/'deploy/remediation/a3-offhost-recovery.py')
a3 = importlib.util.module_from_spec(spec); spec.loader.exec_module(a3)


class S3:
    def __init__(self): self.objects = {}; self.calls = []
    def put_object(self, **kw):
        self.calls.append(kw)
        assert kw['IfNoneMatch'] == '*' and kw['ServerSideEncryption'] == 'AES256'
        if kw['Key'] in self.objects: raise ValueError('precondition')
        self.objects[kw['Key']] = kw['Body']; return {'VersionId':'v1'}
    def head_object(self, **kw):
        body = self.objects[kw['Key']]
        return dict(ContentLength=len(body),ChecksumSHA256=a3.checksum(body),ServerSideEncryption='AES256',VersionId='v1')
    def get_object(self, **kw):
        return dict(self.head_object(**kw),Body=io.BytesIO(self.objects[kw['Key']]))


def test_validator_hash_and_contract():
    assert a3.validator().EXPECTED_SHA256 == a3.SHA


def test_conditional_upload_versions_and_no_overwrite():
    s3 = S3(); data = dict(zip(a3.NAMES, (b'database', b'{}')))
    result = a3.upload(s3, a3.BUCKET, data)
    assert len(result['objects']) == 2
    assert all(x['version'] == 'v1' for x in result['objects'].values())
    with pytest.raises(ValueError): a3.upload(s3, a3.BUCKET, data)


def test_upload_verification_failure_preserves_first_object():
    s3 = S3(); s3.head_object = lambda **kw: dict(ContentLength=0)
    with pytest.raises(ValueError): a3.upload(s3, a3.BUCKET,dict(zip(a3.NAMES,(b'x', b'{}'))))
    assert len(s3.objects) == 1


def test_no_overwrite_private_output(tmp_path):
    path=tmp_path/'result'; a3.write_new(path,b'one')
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError): a3.write_new(path,b'two')
    assert path.read_bytes() == b'one'


@pytest.mark.parametrize('account,arn', [('wrong','arn:aws:iam::wrong:user/test'),(a3.ACCOUNT,'arn:aws:iam::'+a3.ACCOUNT+':root')])
def test_root_and_wrong_account_refused(account,arn):
    class STS:
        def get_caller_identity(self): return dict(Account=account,Arn=arn)
    with pytest.raises(ValueError): a3.guard_identity(STS())


def test_receipt_path_injection_rejected_before_get(tmp_path):
    receipt=dict(account=a3.ACCOUNT,region=a3.REGION,backup_id=a3.BACKUP_ID,bucket='fixture',objects={name:dict(key='../escape',version='v1',bytes=1,sha256='x') for name in a3.NAMES})
    with pytest.raises(ValueError): a3.download(S3(),receipt,tmp_path)
    assert not list(tmp_path.iterdir())


def test_private_synthetic_input_rejected_by_pinned_hash(tmp_path):
    tmp_path.chmod(0o700)
    for name in a3.NAMES: a3.write_new(tmp_path/name,b'fake')
    with pytest.raises(ValueError): a3.validate(tmp_path,a3.validator())


def test_bucket_guard_all_controls():
    class Bucket:
        def get_bucket_location(self,**kw): return {'LocationConstraint':None}
        def get_public_access_block(self,**kw): return {'PublicAccessBlockConfiguration':dict.fromkeys(('BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets'), True)}
        def get_bucket_versioning(self,**kw): return {'Status':'Enabled'}
        def get_bucket_encryption(self,**kw): return {'ServerSideEncryptionConfiguration':{'Rules':[{'ApplyServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]}}
        def get_bucket_ownership_controls(self,**kw): return {'OwnershipControls':{'Rules':[{'ObjectOwnership':'BucketOwnerEnforced'}]}}
    bucket=Bucket(); a3.guard_bucket(bucket,'fixture')
    bucket.get_bucket_versioning=lambda **kw: {'Status':'Suspended'}
    with pytest.raises(ValueError): a3.guard_bucket(bucket,'fixture')

# Reuse the disposable A2 fixture, not any persisted production backup.
from test_a2_restoration import image


def test_roundtrip_independent_download_validate_restore(image, tmp_path, monkeypatch):
    source, _, digest = image
    size = (source/a3.NAMES[0]).stat().st_size
    monkeypatch.setattr(a3,'SHA',digest); monkeypatch.setattr(a3,'SIZE',size)
    a2=a3.validator()
    data=a3.validate(source,a2,digest,size)
    s3=S3(); receipt=a3.upload(s3,a3.BUCKET,data)
    download=tmp_path/'independent'; download.mkdir(mode=0o700)
    a3.download(s3,receipt,download)
    a3.validate(download,a2,digest,size)
    result=a2.run_restore(download,tmp_path/'restored',digest,a2.EXPECTED_COUNTS)
    assert result['status']=='passed'
    assert result['counts_match_a1'] and result['readonly_query_succeeded']
    assert result['source_backup_and_manifest_unchanged']


def test_download_checksum_failure_no_file_written(image,tmp_path,monkeypatch):
    source,_,digest=image
    monkeypatch.setattr(a3,'SHA',digest); monkeypatch.setattr(a3,'SIZE',(source/a3.NAMES[0]).stat().st_size)
    s3=S3(); receipt=a3.upload(s3,a3.BUCKET,{n:(source/n).read_bytes() for n in a3.NAMES})
    s3.objects[a3.PREFIX+a3.NAMES[0]]=b'corrupt'
    dest=tmp_path/'empty';dest.mkdir()
    with pytest.raises(ValueError): a3.download(s3,receipt,dest)
    assert not list(dest.iterdir())


def test_local_supervisor_exit_and_timeout():
    import sys
    spec=importlib.util.spec_from_file_location('a3_bound',ROOT/'deploy/remediation/a3-bounded-local.py')
    bound=importlib.util.module_from_spec(spec);spec.loader.exec_module(bound)
    assert bound.run([sys.executable,'-c','raise SystemExit(3)'])==3
    assert bound.run([sys.executable,'-c','import time; time.sleep(10)'],seconds=0.05,grace=0.05)==124


def test_unapproved_bucket_refused_without_s3_calls():
    s3=S3()
    with pytest.raises(ValueError): a3.upload(s3,'wrong-bucket',{})
    assert not s3.calls
