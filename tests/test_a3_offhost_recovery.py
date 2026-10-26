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
    with pytest.raises(ValueError): a3.guard_identity(STS(),'arn:aws:iam::'+a3.ACCOUNT+':role/ApprovedFixture')


def test_receipt_path_injection_rejected_before_get(tmp_path):
    receipt=dict(account=a3.ACCOUNT,region=a3.REGION,backup_id=a3.BACKUP_ID,bucket=a3.BUCKET,objects={name:dict(key='../escape',version='v1',bytes=1,sha256='x') for name in a3.NAMES})
    s3=S3()
    def forbidden_get(**kw):
        raise AssertionError('GET must not occur before receipt key validation')
    s3.get_object=forbidden_get
    with pytest.raises(ValueError): a3.download(s3,receipt,tmp_path)
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


@pytest.mark.parametrize('actual,expected,allowed', [
    ('arn:aws:sts::'+a3.ACCOUNT+':assumed-role/ApprovedFixture/session', 'arn:aws:iam::'+a3.ACCOUNT+':role/path/ApprovedFixture',True),
    ('arn:aws:sts::'+a3.ACCOUNT+':assumed-role/Other/session', 'arn:aws:iam::'+a3.ACCOUNT+':role/ApprovedFixture',False),
    ('arn:aws:iam::'+a3.ACCOUNT+':user/ApprovedFixture', 'arn:aws:iam::'+a3.ACCOUNT+':role/ApprovedFixture',False),
    ('arn:aws:sts::'+a3.ACCOUNT+':assumed-role/ApprovedFixture/session', 'arn:aws:iam::000000000000:role/ApprovedFixture',False),
])
def test_exact_approved_role_binding(actual,expected,allowed):
    class STS:
        def get_caller_identity(self): return dict(Account=a3.ACCOUNT,Arn=actual)
    if allowed: a3.guard_identity(STS(),expected)
    else:
        with pytest.raises(ValueError): a3.guard_identity(STS(),expected)


def test_supervisor_escalates_group_even_when_leader_exits(monkeypatch):
    import subprocess
    import signal
    spec=importlib.util.spec_from_file_location('a3_bound_fixture',ROOT/'deploy/remediation/a3-bounded-local.py')
    bound=importlib.util.module_from_spec(spec);spec.loader.exec_module(bound)
    class Process:
        pid=99999999
        calls=0
        def wait(self,timeout=None):
            self.calls+=1
            if self.calls==1: raise subprocess.TimeoutExpired('fixture',timeout)
            return 0
    monkeypatch.setattr(bound.subprocess,'Popen',lambda *a,**kw:Process())
    signals=[]
    monkeypatch.setattr(bound.os,'killpg',lambda pid,sig:signals.append(sig))
    assert bound.run(['fixture'],seconds=0,grace=0)==124
    assert signals==[signal.SIGTERM,signal.SIGKILL]


def valid_receipt():
    return dict(account=a3.ACCOUNT,region=a3.REGION,backup_id=a3.BACKUP_ID,bucket=a3.BUCKET,
                objects={a3.NAMES[0]:dict(key=a3.PREFIX+a3.NAMES[0],version='fixture-db-v1',bytes=a3.SIZE,sha256=a3.SHA),
                         a3.NAMES[1]:dict(key=a3.PREFIX+a3.NAMES[1],version='fixture-manifest-v1',bytes=2,sha256=hashlib.sha256(b'{}').hexdigest())})


@pytest.mark.parametrize('field,value', [('key','../escape'),('version','ACTUAL_APPROVED_VERSION'),('version','null'),('version',False),('version','line\nbreak'),('bytes',True),('bytes',0),('bytes',1024*1024+1),('sha256','not-a-checksum')])
def test_bad_manifest_metadata_refused_before_either_get(tmp_path,field,value):
    receipt=valid_receipt();receipt['objects'][a3.NAMES[1]][field]=value
    s3=S3()
    def unexpected(**kw): raise AssertionError('metadata must be fully checked before GET')
    s3.get_object=unexpected
    with pytest.raises(ValueError):a3.download(s3,receipt,tmp_path)
    assert not list(tmp_path.iterdir())


def test_receipt_is_bounded_private_hash_pinned_and_not_symlink(tmp_path):
    a2=a3.validator()
    path=tmp_path/'receipt.json';raw=json.dumps(valid_receipt()).encode();a3.write_new(path,raw)
    checksum=hashlib.sha256(raw).hexdigest()
    assert a3.load_receipt(path,checksum,a3.validator())==valid_receipt()
    with pytest.raises(ValueError):a3.load_receipt(path,'0'*64,a3.validator())
    with pytest.raises(ValueError):a3.load_receipt(path,'ACTUAL_APPROVED_RECEIPT_SHA256',a3.validator())
    path.chmod(0o644)
    with pytest.raises(a2.Refused):a3.load_receipt(path,checksum,a2)
    path.chmod(0o600);link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(a2.Refused):a3.load_receipt(link,checksum,a2)


def test_partial_upload_journal_retains_verified_first_and_unknown_second(tmp_path):
    path=tmp_path/'progress.jsonl';stream,record=a3.progress_writer(path)
    class PartialS3(S3):
        def put_object(self,**kw):
            if kw['Key'].endswith('manifest.json'):raise TimeoutError('unknown remote outcome; do not retry')
            return super().put_object(**kw)
    with stream:
        with pytest.raises(TimeoutError):a3.upload(PartialS3(),a3.BUCKET,dict(zip(a3.NAMES,(b'fixture',b'{}'))),record)
    events=[json.loads(line) for line in path.read_text().splitlines()]
    assert [event['state'] for event in events]==['put_attempting','put_returned','verified','put_attempting']
    assert events[1]['version']=='v1' and events[-1]['name']=='manifest.json'
    assert path.stat().st_mode & 0o777==0o600
    with pytest.raises(FileExistsError):a3.progress_writer(path)


@pytest.mark.parametrize('arn',['arn:aws:iam::'+a3.ACCOUNT+':role/PowerFlowEC2Role',
                                'arn:aws:iam::'+a3.ACCOUNT+':role/EXACT_APPROVED_ROLE',
                                'arn:aws:iam::'+a3.ACCOUNT+'/Role',
                                'arn:aws:iam::'+a3.ACCOUNT+':role/path//Role'])
def test_runtime_malformed_placeholder_role_rejected_before_sts(arn):
    class STS:
        def get_caller_identity(self):raise AssertionError('no AWS call for invalid expected identity')
    with pytest.raises(ValueError):a3.guard_identity(STS(),arn)


def test_output_parent_preflight_refuses_unwritable_or_existing(tmp_path):
    path=tmp_path/'receipt.json'
    tmp_path.chmod(0o700);a3.new_private_parent(path)
    tmp_path.chmod(0o500)
    try:
        with pytest.raises(ValueError):a3.new_private_parent(path)
    finally:tmp_path.chmod(0o700)
    a3.write_new(path,b'fixture')
    with pytest.raises(ValueError):a3.new_private_parent(path)
