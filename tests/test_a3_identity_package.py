"""Only local JSON and fake SDK sessions; no IAM account changes or credentials."""
import importlib.util
import json
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('a3_session',ROOT/'deploy/remediation/run-a3-session.py')
a3=importlib.util.module_from_spec(spec);spec.loader.exec_module(a3)


def test_exact_operator_mfa_roles_and_in_memory_credentials(capsys):
    class STS:
        def get_caller_identity(self):return {'Account':a3.ACCOUNT,'Arn':a3.OPERATOR}
        def assume_role(self,**kw):
            assert kw['RoleArn']==a3.ROLES['restore'] and kw['DurationSeconds']==900
            assert kw['SerialNumber']=='arn:aws:iam::'+a3.ACCOUNT+':mfa/PowerFlowA3Operator'
            assert kw['TokenCode']=='123456'
            return {'Credentials':{'AccessKeyId':'synthetic-access','SecretAccessKey':'synthetic-secret','SessionToken':'synthetic-session'}}
    received={}
    def factory(**kw):received.update(kw);return 'RAM-session'
    assert a3.assume(STS(),factory,'restore','arn:aws:iam::'+a3.ACCOUNT+':mfa/PowerFlowA3Operator',lambda _: '123456')=='RAM-session'
    assert received['aws_secret_access_key']=='synthetic-secret'
    assert capsys.readouterr().out==''


@pytest.mark.parametrize('arn',['arn:aws:iam::870755688674:root','arn:aws:iam::870755688674:user/Other','arn:aws:sts::870755688674:assumed-role/PowerFlowEC2Role/s'])
def test_root_runtime_other_identity_stops_before_prompt_or_assume(arn):
    class STS:
        def get_caller_identity(self):return {'Account':a3.ACCOUNT,'Arn':arn}
        def assume_role(self,**kw):raise AssertionError('must not assume')
    with pytest.raises(ValueError):a3.assume(STS(),lambda **kw:None,'upload','arn:aws:iam::'+a3.ACCOUNT+':mfa/PowerFlowA3Operator',lambda _: pytest.fail('must not ask for a code'))


def test_proposed_role_trust_only_new_operator_with_recent_mfa():
    package=ROOT/'deploy/remediation/a3-access-package'
    trust=json.loads((package/'mfa-operator-trust.json').read_text())['Statement']
    assert len(trust)==1 and trust[0]['Principal']=={'AWS':a3.OPERATOR}
    assert trust[0]['Action']=='sts:AssumeRole'
    assert trust[0]['Condition']=={'Bool':{'aws:MultiFactorAuthPresent':'true'},'NumericLessThanEquals':{'aws:MultiFactorAuthAge':'300'}}
    grants=json.loads((package/'operator-policy.json').read_text())['Statement']
    assert grants[0]['Action']=='sts:AssumeRole' and set(grants[0]['Resource'])==set(a3.ROLES.values())


def test_package_does_not_expand_other_pipeline_objects():
    bucket=json.loads((ROOT/'deploy/remediation/a3-access-package/bucket-policy.json').read_text())
    targets={'arn:aws:s3:::powerflow-data-ian-2026-870755688674-us-east-1-an/recovery/phase5d2-a3/20261026T022230.137446Z/'+name for name in ('electricity_trading.db','manifest.json')}
    assert all(set(statement['Resource'])==targets for statement in bucket['Statement'])


def test_review_hashes_and_pinned_payload_are_current():
    import hashlib
    for filename in ('deploy/remediation/a3-access-package/SHA256SUMS.json','deploy/preflight/INSPECTION-SHA256.json'):
        for path,digest in json.loads((ROOT/filename).read_text()).items():
            assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    assert hashlib.sha256((ROOT/'deploy/remediation/a3-offhost-recovery.py').read_bytes()).hexdigest()==a3.PAYLOAD_SHA256


def test_runner_requires_owner_terminal_before_any_provider_use(monkeypatch,capsys):
    from types import SimpleNamespace
    monkeypatch.setattr(a3.sys,'argv',['run-a3-session.py','upload','--source-profile','not-read','--mfa-device-arn','arn:aws:iam::870755688674:mfa/PowerFlowA3Operator'])
    monkeypatch.setattr(a3.sys,'stdin',SimpleNamespace(isatty=lambda:False))
    assert a3.main()==1
    assert 'interactive Terminal' in capsys.readouterr().out


def test_signin_is_exact_same_device_and_no_remote_or_s3_grant():
    policy=json.loads((ROOT/'deploy/remediation/a3-access-package/operator-policy.json').read_text())
    signin=policy['Statement'][1]
    assert set(signin['Action'])=={'signin:AuthorizeOAuth2Access','signin:CreateOAuth2Token'}
    assert signin['Resource']=='arn:aws:signin:us-east-1:870755688674:oauth2/public-client/localhost'
    assert 'Condition' not in signin # Do not create circular MFA/login authorization.


def test_rejected_mfa_does_not_create_session_or_leak_code(capsys):
    class STS:
        def get_caller_identity(self):return {'Account':a3.ACCOUNT,'Arn':a3.OPERATOR}
        def assume_role(self,**kw):raise ValueError('denied')
    with pytest.raises(ValueError):a3.assume(STS(),lambda **kw:pytest.fail('no session'),'upload','arn:aws:iam::'+a3.ACCOUNT+':mfa/PowerFlowA3Operator',lambda _: '123456')
    assert '123456' not in capsys.readouterr().out


@pytest.mark.parametrize('action',['upload','restore'])
def test_authentication_only_never_imports_or_executes_s3_payload(monkeypatch,capsys,action):
    import boto3,logging
    from types import SimpleNamespace
    monkeypatch.setattr(a3.sys,'argv',['run-a3-session.py',action,'--source-profile','operator','--mfa-device-arn','arn:aws:iam::'+a3.ACCOUNT+':mfa/PowerFlowA3Operator','--authentication-only'])
    monkeypatch.setattr(a3.sys,'stdin',SimpleNamespace(isatty=lambda:True))
    monkeypatch.setattr(a3.sys,'stderr',SimpleNamespace(isatty=lambda:True))
    monkeypatch.setattr(logging,'disable',lambda *_:None)
    class Session:
        def client(self,name,**kw):assert name=='sts';return self
        def get_caller_identity(self):
            return {'Account':a3.ACCOUNT,'Arn':'arn:aws:sts::'+a3.ACCOUNT+':assumed-role/'+a3.ROLES[action].rsplit('/',1)[1]+'/acceptance'}
    monkeypatch.setattr(boto3,'Session',lambda **kw:Session())
    monkeypatch.setattr(a3,'assume',lambda *args:Session())
    monkeypatch.setattr(a3.importlib.util,'spec_from_file_location',lambda *args:pytest.fail('no payload import allowed'))
    assert a3.main()==0
    output=capsys.readouterr().out
    assert 'authenticated' in output and 'STS only' in output
