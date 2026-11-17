"""Offline structural checks, not an AWS effective-policy simulation."""
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('a3_access',Path(__file__).parents[1]/'deploy/remediation/prepare-a3-access.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
UPLOAD='arn:aws:iam::870755688674:role/PowerFlowA3Uploader'
READER='arn:aws:iam::870755688674:role/PowerFlowA3Reader'


def test_exact_two_keys_only_and_runtime_delete_block():
    documents=p.policies(UPLOAD,READER)
    statements=documents['bucket-policy.json']['Statement']
    assert all(st['Resource']==p.OBJECTS and st['Effect']=='Deny' for st in statements)
    deletion=next(st for st in statements if st['Sid']=='A3DenyDeletion')
    assert deletion['Principal']=='*' and 'Condition' not in deletion
    assert deletion['Action']==['s3:DeleteObject','s3:DeleteObjectVersion']
    writer=next(st for st in statements if st['Sid']=='A3DenyUnexpectedWriter')
    assert writer['Condition']['ArnNotEquals']['aws:PrincipalArn']==UPLOAD


def test_missing_or_wrong_headers_have_separate_denies():
    statements=p.policies(UPLOAD,READER)['bucket-policy.json']['Statement']
    assert next(st for st in statements if st['Sid']=='A3RequireAES256')['Condition']=={'StringNotEquals':{'s3:x-amz-server-side-encryption':'AES256'}}
    assert next(st for st in statements if st['Sid']=='A3RequireCreateOnly')['Condition']=={'StringNotEquals':{'s3:if-none-match':'*'}}


def test_no_reader_allow_before_real_versions():
    assert all(st['Effect']=='Deny' for st in p.policies(UPLOAD,READER)['reader-policy.json']['Statement'])


def test_reader_versions_scoped_per_object_without_latest_access():
    versions=dict(zip(p.NAMES,('fixture-db-v1','fixture-manifest-v1')))
    allow=[st for st in p.policies(UPLOAD,READER,versions)['reader-policy.json']['Statement'] if st['Effect']=='Allow']
    assert len(allow)==2
    for st,name,resource in zip(allow,p.NAMES,p.OBJECTS):
        assert st['Action']=='s3:GetObjectVersion' and st['Resource']==resource
        assert st['Condition']=={'StringEquals':{'s3:VersionId':versions[name]}}


@pytest.mark.parametrize('arn',['arn:aws:iam::870755688674:root','arn:aws:iam::000000000000:role/X','arn:aws:iam::870755688674:role/PowerFlowEC2Role','arn:aws:iam::870755688674:user/X'])
def test_inappropriate_recovery_identity_refused(arn):
    with pytest.raises(ValueError):p.policies(arn,READER)


def test_roles_must_be_separate_and_versions_nonempty():
    with pytest.raises(ValueError):p.policies(UPLOAD,UPLOAD)
    with pytest.raises(ValueError):p.policies(UPLOAD,READER,dict(zip(p.NAMES,('null','v2'))))


def test_cli_generates_private_new_files_and_refuses_existing(tmp_path):
    import subprocess,sys,json
    output=tmp_path/'proposal'
    command=[sys.executable,'-B',str(Path(p.__file__)),'--uploader-role-arn',UPLOAD,'--reader-role-arn',READER,'--output',str(output)]
    first=subprocess.run(command,capture_output=True,text=True)
    assert first.returncode==0,first.stderr
    assert json.loads(first.stdout)['status']=='prepared_only'
    assert output.stat().st_mode & 0o777==0o700
    original={file.name:file.read_bytes() for file in output.iterdir()}
    assert len(original)==4
    assert all(file.stat().st_mode & 0o777==0o600 for file in output.iterdir())
    assert subprocess.run(command,capture_output=True).returncode!=0
    assert original=={file.name:file.read_bytes() for file in output.iterdir()}


def test_approval_metadata_hashes_and_no_runtime_identity_changes(tmp_path):
    import subprocess,sys,json,hashlib
    output=tmp_path/'proposal'
    command=[sys.executable,'-B',str(Path(p.__file__)),'--uploader-role-arn',UPLOAD,'--reader-role-arn',READER,'--db-version','fixture-db-v1','--manifest-version','fixture-mf-v1','--output',str(output)]
    assert subprocess.run(command,capture_output=True).returncode==0
    metadata=json.loads((output/'approval-metadata.json').read_text())
    assert metadata['runtime_role_preserved']=='PowerFlowEC2Role'
    assert metadata['status']=='proposal_only_not_applied' and metadata['version_bound_reader']
    for name,digest in metadata['sha256'].items():assert hashlib.sha256((output/name).read_bytes()).hexdigest()==digest


@pytest.mark.parametrize('role',[
 'arn:aws:iam::870755688674:role/EXACT_APPROVED_UPLOADER',
 'arn:aws:iam::870755688674:role/TBD',
 'arn:aws:iam::870755688674:role/PLACEHOLDER',
])
def test_generator_rejects_role_placeholders(role):
    with pytest.raises(ValueError):p.policies(role,READER)


@pytest.mark.parametrize('version',['ACTUAL_APPROVED_VERSION','TBD','bad\nvalue','null'])
def test_generator_rejects_version_placeholders(version):
    with pytest.raises(ValueError):p.policies(UPLOAD,READER,dict(zip(p.NAMES,(version,'fixture-mf'))))


# Small evaluator for ONLY the generated condition/operator subset, not a claim
# to simulate AWS IAM/SCP/session-policy evaluation. Identity allows are modeled
# explicitly to demonstrate that the generated explicit denies still win.
def decision(documents,action,resource,context,identity_allow=False):
    import fnmatch
    allow=identity_allow
    def seq(value):return value if isinstance(value,list) else [value]
    for document in documents:
        for st in document['Statement']:
            if not any(fnmatch.fnmatchcase(action,a) for a in seq(st['Action'])):continue
            if not any(fnmatch.fnmatchcase(resource,r) for r in seq(st['Resource'])):continue
            applies=True
            for operator,conditions in st.get('Condition',{}).items():
                for key,wanted in conditions.items():
                    actual=context.get(key)
                    if operator in ('StringEquals','ArnEquals'):matches=actual in seq(wanted)
                    elif operator in ('StringNotEquals','ArnNotEquals'):matches=actual not in seq(wanted)
                    elif operator=='Bool':matches=actual is not None and str(actual).lower() in seq(wanted)
                    else:raise AssertionError('unsupported local subset')
                    applies=applies and matches
            if applies and st['Effect']=='Deny':return 'deny'
            if applies and st['Effect']=='Allow':allow=True
    return 'allow' if allow else 'implicit_deny'


def test_policy_subset_runtime_cannot_touch_recovery_but_other_keys_unaffected():
    docs=p.policies(UPLOAD,READER)
    runtime={'aws:PrincipalArn':'arn:aws:iam::870755688674:role/PowerFlowEC2Role','aws:SecureTransport':'true'}
    for action in ('s3:PutObject','s3:DeleteObject','s3:DeleteObjectVersion','s3:GetObject','s3:GetObjectVersion'):
        assert decision([docs['bucket-policy.json']],action,p.OBJECTS[0],runtime,identity_allow=True)=='deny'
        assert decision([docs['bucket-policy.json']],action,p.BASE+'/data/unrelated',runtime,identity_allow=True)=='allow'


def test_policy_subset_headers_and_tls_are_independent_and_fail_closed():
    docs=p.policies(UPLOAD,READER)
    valid={'aws:PrincipalArn':UPLOAD,'aws:SecureTransport':'true','s3:x-amz-server-side-encryption':'AES256','s3:if-none-match':'*'}
    policies=[docs['bucket-policy.json'],docs['uploader-policy.json']]
    assert decision(policies,'s3:PutObject',p.OBJECTS[0],valid)=='allow'
    for key in ('s3:if-none-match','s3:x-amz-server-side-encryption'):
        bad=dict(valid);del bad[key]
        assert decision(policies,'s3:PutObject',p.OBJECTS[0],bad)=='deny'
    bad=dict(valid,**{'aws:SecureTransport':'false'})
    assert decision(policies,'s3:PutObject',p.OBJECTS[0],bad)=='deny'


def test_reader_explicit_deny_prevents_other_policy_widening_versions():
    versions=dict(zip(p.NAMES,('fixture-db-v1','fixture-mf-v1')))
    docs=p.policies(UPLOAD,READER,versions)
    context={'aws:PrincipalArn':READER,'aws:SecureTransport':'true','s3:VersionId':'fixture-db-v1'}
    policies=[docs['bucket-policy.json'],docs['reader-policy.json']]
    assert decision(policies,'s3:GetObjectVersion',p.OBJECTS[0],context)=='allow'
    for version in (None,'other-version','fixture-mf-v1'):
        bad=dict(context,**{'s3:VersionId':version})
        assert decision(policies,'s3:GetObjectVersion',p.OBJECTS[0],bad,identity_allow=True)=='deny'
    assert decision(policies,'s3:GetObject',p.OBJECTS[0],context,identity_allow=True)=='deny'
    before=p.policies(UPLOAD,READER)['reader-policy.json']
    assert decision([before],'s3:GetObjectVersion',p.OBJECTS[0],context,identity_allow=True)=='deny'
