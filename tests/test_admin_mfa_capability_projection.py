"""Offline projection only. No SDK/client creation or AWS access."""
import ast
import importlib.util
import json
from pathlib import Path
import pytest
P=Path(__file__).parents[1]/'deploy/preflight/admin-mfa-capability/projection.py'
s=importlib.util.spec_from_file_location('mfa_projection',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def fixture():
    pool={'UserPool':{'Id':m.POOL,'UserPoolTier':'ESSENTIALS','AcrConfiguration':{'Level4':{'AcrValue':'SECRET_DO_NOT_EXPORT'}},'Private':'SECRET'}}
    mfa={'MfaConfiguration':'OPTIONAL','SoftwareTokenMfaConfiguration':{'Enabled':True}}
    clients=[{'UserPoolClient':{'UserPoolId':m.POOL,'ClientId':c,'SupportedIdentityProviders':['COGNITO','Google'],'AllowedOAuthScopes':['openid','aws.cognito.signin.user.admin'],'AllowedOAuthFlows':['code'],'AllowedOAuthFlowsUserPoolClient':True,'EnableTokenRevocation':True}}for c in m.CLIENTS]
    return pool,mfa,clients

def test_valid_capability_does_not_claim_signed_mfa_acceptance():
    r=m.project(*fixture());assert r['step_up_plan_eligible']is True and r['totp_enabled']is True
    assert r['claims_verified']is False and r['enforceability']=='REQUIRES_SIGNED_SESSION_ACCEPTANCE'
    assert all(c['native_supported']and c['google_supported']for c in r['clients'])
    assert 'SECRET'not in json.dumps(r)and m.POOL not in json.dumps(r)
@pytest.mark.parametrize('tier',['LITE','ESSENTIALS','PLUS',None])
def test_tier_does_not_substitute_for_rollout_or_claim_proof(tier):
    p,a,c=fixture();p['UserPool']['UserPoolTier']=tier;r=m.project(p,a,c)
    assert r['step_up_plan_eligible']==(None if tier is None else tier!='LITE') and r['claims_verified']is False
@pytest.mark.parametrize('mode',['OFF','OPTIONAL','ON'])
def test_actual_aws_mfa_enum(mode):
    p,a,c=fixture();a['MfaConfiguration']=mode;assert m.project(p,a,c)['pool_mfa']=={'ON':'REQUIRED','OFF':'OFF','OPTIONAL':'OPTIONAL'}[mode]
def test_no_read_of_secret_value():
    class Secret:
        def __repr__(self):raise AssertionError('SECRET_READ')
    p,a,c=fixture();c[0]['UserPoolClient']['ClientSecret']=Secret();r=m.project(p,a,c)
    assert r['clients'][0]['public_client']is False and 'SECRET'not in json.dumps(r)
@pytest.mark.parametrize('kind',['pool','client','duplicate','mode','totp','tier'])
def test_missing_or_ambiguous_configuration_fail_closed(kind):
    p,a,c=fixture()
    if kind=='pool':p['UserPool']['Id']='other'
    elif kind=='client':c[0]['UserPoolClient']['ClientId']='other'
    elif kind=='duplicate':c[1]=c[0]
    elif kind=='mode':a['MfaConfiguration']='REQUIRED'
    elif kind=='totp':a['SoftwareTokenMfaConfiguration']['Enabled']='yes'
    else:p['UserPool']['UserPoolTier']='unknown'
    with pytest.raises(ValueError,match='CONFIGURATION_UNVERIFIED'):m.project(p,a,c)
def test_missing_rollout_metadata_is_unknown_not_success():
    p,a,c=fixture();p['UserPool'].pop('AcrConfiguration');p['UserPool'].pop('UserPoolTier');r=m.project(p,a,c)
    assert r['assurance_configuration_reported']is False and r['step_up_plan_eligible']is None

def test_python39_no_network_credentials_or_sdk_imports():
    tree=ast.parse(P.read_bytes(),feature_version=(3,9));assert not any(isinstance(n,(ast.Import,ast.ImportFrom))for n in ast.walk(tree))


@pytest.mark.parametrize('factors',[['PASSWORD'],['WEB_AUTHN'],None])
def test_native_factor_and_device_policy_are_explicit_not_inferred(factors):
    p,a,c=fixture();p['UserPool']['Policies']={'SignInPolicy':{'AllowedFirstAuthFactors':factors}}
    p['UserPool']['DeviceConfiguration']={'ChallengeRequiredOnNewDevice':True,'DeviceOnlyRememberedOnUserPrompt':True}
    r=m.project(p,a,c);assert r['password_first_factor_enabled']==(None if factors is None else 'PASSWORD'in factors)
    assert r['device_mfa_challenge_required']is True and r['claims_verified']is False
