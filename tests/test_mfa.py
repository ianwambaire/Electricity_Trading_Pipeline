"""Isolated Cognito MFA contract tests; no account enrollment or AWS access."""
import time

import pytest
from fastapi import HTTPException
from api.account_service import AccountGateway, SELF_SERVICE_SCOPE
from api.mfa_service import EnrollmentStore, mfa_status
from test_account_management import account_client  # noqa: F401 -- pytest fixture
from test_api_security import signing, token, auth, ISSUER  # noqa: F401


def ready(account_client, **kwargs):
    c, h, calls, state = account_client(**kwargs)
    c.app.state.account_totp_enabled = True
    state['mfa_test'] = True
    return c, h, calls, state


def setup(c, h):
    r = c.post('/account/mfa/setup', headers=h)
    assert r.status_code == 200
    assert r.headers['cache-control'] == 'no-store'
    return r.json()


def test_release_flag_never_enrolls_by_default(account_client):
    c, h, calls, _ = account_client()
    assert c.get('/account/profile', headers=h).json()['mfa_management'] == 'unavailable'
    assert c.post('/account/mfa/setup', headers=h).status_code == 409
    assert not any(op == 'AssociateSoftwareToken' for op, _ in calls)


def test_local_subject_scope_excludes_every_other_account(account_client):
    from test_api_security import SUB
    c, h, calls, _ = ready(account_client)
    c.app.state.account_totp_test_subject = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
    assert c.get('/account/profile', headers=h).json()['mfa_management'] == 'unavailable'
    assert c.post('/account/mfa/setup', headers=h).status_code == 409
    assert not any(op == 'AssociateSoftwareToken' for op, _ in calls)
    c.app.state.account_totp_test_subject = SUB
    assert c.get('/account/profile', headers=h).json()['mfa_management'] == 'available'
    setup(c, h)


def test_invalid_local_subject_never_enables_enrollment(account_client, monkeypatch):
    monkeypatch.setenv('POWERFLOW_ACCOUNT_TOTP_ENABLED', 'true')
    monkeypatch.setenv('POWERFLOW_ACCOUNT_TOTP_TEST_SUBJECT', 'profile-label-or-typo')
    c, h, calls, _ = account_client()
    assert c.app.state.account_totp_enabled is False
    assert c.post('/account/mfa/setup', headers=h).status_code == 409
    assert not any(op == 'AssociateSoftwareToken' for op, _ in calls)


def test_native_setup_verification_preference_and_live_readback(account_client, caplog):
    c, h, calls, state = ready(account_client)
    assert c.get('/account/profile', headers=h).json()['mfa_management'] == 'available'
    s = setup(c, h)
    assert set(s) == {'secret', 'setup_ticket', 'expires_in'} and s['expires_in'] == 300
    assert s['secret'] == 'JBSWY3DPEHPK3PXP'
    # Ephemeral server metadata must contain no key, submitted code or access token.
    assert all(s['secret'] not in repr(e) and h['Authorization'] not in repr(e)
               for e in c.app.state.mfa_enrollments._entries.values())
    r = c.post('/account/mfa/verify', headers=h, json={'setup_ticket': s['setup_ticket'], 'code': '123456'})
    assert r.status_code == 200 and r.json() == {'status': 'mfa_enabled'}
    assert s['secret'] not in caplog.text and '123456' not in caplog.text
    mutations = [(op, b) for op, b in calls if op in {'AssociateSoftwareToken', 'VerifySoftwareToken', 'SetUserMFAPreference'}]
    assert [op for op, _ in mutations] == ['AssociateSoftwareToken', 'VerifySoftwareToken', 'SetUserMFAPreference']
    assert set(mutations[0][1]) == {'AccessToken'}
    assert set(mutations[1][1]) == {'AccessToken', 'UserCode'}
    assert mutations[2][1]['SoftwareTokenMfaSettings'] == {'Enabled': True, 'PreferredMfa': True}
    p = c.get('/account/profile', headers=h).json()
    assert p['mfa_status'] == 'enabled' and p['role'] == 'Analyst'
    assert c.post('/account/mfa/setup', headers=h).status_code == 409
    for path in ['/admin/forecast/provenance','/admin/monitoring/forecast-vintages','/admin/monitoring/exogenous-readiness',
                 '/admin/models/linear-feature-influence','/admin/operations','/monitoring/forecast-vintages','/monitoring/exogenous-readiness']:
        assert c.get(path, headers=h).status_code == 403


@pytest.mark.parametrize('kwargs,attribute', [({'google': True},None), ({'factors': []},None),
                                             ({'factor_error':'OperationNotEnabledException'},None), ({},'email_verified')])
def test_native_eligibility_federation_and_recovery_fail_closed(account_client, kwargs, attribute):
    c, h, calls, state = ready(account_client, **kwargs)
    if attribute: state['attributes'][attribute] = 'false'
    assert c.post('/account/mfa/setup', headers=h).status_code == 409
    assert not any(op == 'AssociateSoftwareToken' for op, _ in calls)


@pytest.mark.parametrize('path,body', [('/setup',None),('/verify',{'setup_ticket':'a'*43,'code':'123456'}),('/cancel',{'setup_ticket':'a'*43})])
def test_mfa_requires_live_valid_own_account_and_scope(account_client, signing, path, body):
    c, h, calls, state = ready(account_client)
    for changes in [{'token_use':'id'}, {'client_id':'other'}, {'iss':'wrong'}, {'exp':1}]:
        bad = auth(token(signing, scope='openid '+SELF_SERVICE_SCOPE, auth_time=int(time.time()), **changes))
        assert c.post('/account/mfa'+path, headers=bad, json=body).status_code == 401
    assert c.post('/account/mfa'+path, json=body).status_code == 401
    assert c.post('/account/mfa'+path, headers=auth(token(signing)), json=body).status_code == 403
    state['revoked'] = True
    assert c.post('/account/mfa'+path, headers=h, json=body).status_code == 401
    assert not any(op in {'AssociateSoftwareToken','VerifySoftwareToken','SetUserMFAPreference'} for op, _ in calls)


def test_setup_and_verify_require_fresh_authentication(account_client, signing):
    c, h, calls, _ = ready(account_client)
    s = setup(c,h)
    for auth_time in [None,int(time.time())-601]:
        old = auth(token(signing, scope='openid '+SELF_SERVICE_SCOPE, auth_time=auth_time))
        for path,body in [('/setup',None),('/verify',{'setup_ticket':s['setup_ticket'],'code':'123456'})]:
            assert c.post('/account/mfa'+path,headers=old,json=body).status_code==403
    assert not any(op=='VerifySoftwareToken' for op,_ in calls)


@pytest.mark.parametrize('body',[{'code':'12345'},{'code':'１２３４５６'},{'code':'1234567'}, {'code':'123456','username':'other'},
                                {'code':'123456','role':'Admin'}, {'code':'123456','AccessToken':'other'}, {'code':123456}])
def test_mfa_input_and_targets_are_redacted(account_client,body,caplog):
    c,h,calls,_=ready(account_client);s=setup(c,h)
    r=c.post('/account/mfa/verify',headers=h,json={'setup_ticket':s['setup_ticket'],**body})
    assert r.status_code==422 and r.json()=={'detail':{'code':'INVALID_ACCOUNT_INPUT'}}
    assert s['setup_ticket'] not in r.text and s['setup_ticket'] not in caplog.text
    assert not any(op=='VerifySoftwareToken' for op,_ in calls)
    assert c.post('/account/mfa/setup?username=other',headers=h).status_code==422


def test_wrong_code_attempt_limit_and_provider_rejection(account_client):
    c,h,calls,state=ready(account_client);s=setup(c,h)
    state['errors']['VerifySoftwareToken']={'__type':'CodeMismatchException','message':'secret diagnostic 123456'}
    for _ in range(5):
        r=c.post('/account/mfa/verify',headers=h,json={'setup_ticket':s['setup_ticket'],'code':'123456'})
        assert r.status_code==400 and r.json()['detail']['code']=='MFA_INVALID_CODE'
        assert 'diagnostic' not in r.text and '123456' not in r.text
    assert c.post('/account/mfa/verify',headers=h,json={'setup_ticket':s['setup_ticket'],'code':'123456'}).status_code==409
    assert not any(op=='SetUserMFAPreference' for op,_ in calls)


def test_partial_preference_failure_retry_does_not_reverify_or_replace(account_client):
    c,h,calls,state=ready(account_client);s=setup(c,h)
    state['errors']['SetUserMFAPreference']={'__type':'InternalErrorException'}
    body={'setup_ticket':s['setup_ticket'],'code':'123456'}
    assert c.post('/account/mfa/verify',headers=h,json=body).status_code==503
    del state['errors']['SetUserMFAPreference']
    assert c.post('/account/mfa/verify',headers=h,json=body).json()=={'status':'mfa_enabled'}
    assert len([op for op,_ in calls if op=='VerifySoftwareToken'])==1


def test_verify_status_must_succeed_and_setup_response_is_bounded(account_client):
    c,h,calls,state=ready(account_client);state['setup_result']={'SecretCode':'not valid'}
    assert c.post('/account/mfa/setup',headers=h).status_code==503
    assert not c.app.state.mfa_enrollments._entries
    del state['setup_result'];s=setup(c,h);state['verify_result']={'Status':'ERROR'}
    assert c.post('/account/mfa/verify',headers=h,json={'setup_ticket':s['setup_ticket'],'code':'123456'}).status_code==400
    assert not any(op=='SetUserMFAPreference' for op,_ in calls)


def test_cancel_discards_only_setup_and_cannot_disable_mfa(account_client):
    c,h,calls,state=ready(account_client);s=setup(c,h)
    assert c.post('/account/mfa/cancel',headers=h,json={'setup_ticket':s['setup_ticket']}).json()=={'status':'setup_cancelled'}
    assert c.post('/account/mfa/verify',headers=h,json={'setup_ticket':s['setup_ticket'],'code':'123456'}).status_code==409
    assert c.post('/account/mfa/disable',headers=h).status_code==404
    assert not any(op=='SetUserMFAPreference' for op,_ in calls)


@pytest.mark.parametrize('value',[{'UserMFASettingList':None},{'UserMFASettingList':[{}]},
                                 {'UserMFASettingList':['future_factor']},{'PreferredMfaSetting':'SOFTWARE_TOKEN_MFA'},
                                 {'PreferredMfaSetting':True}])
def test_unknown_mfa_state_never_offers_enrollment(account_client,value):
    c,h,calls,state=ready(account_client);state['mfa']=value
    assert mfa_status(value)=='unknown'
    assert c.get('/account/profile',headers=h).json()['mfa_management']=='unavailable'
    assert c.post('/account/mfa/setup',headers=h).status_code==409
    assert not any(op=='AssociateSoftwareToken' for op,_ in calls)


def test_store_expiry_owner_binding_concurrency_and_bounds():
    now=[0];s=EnrollmentStore(clock=lambda:now[0],limit=1);e=s.begin('one',10)
    assert 'secret' not in vars(e) and 'token' not in vars(e)
    with pytest.raises(HTTPException):s.begin('one',10)
    with pytest.raises(HTTPException):s.begin('two',10)
    for subject,ticket,at in [('two',e.ticket,10),('one','b'*43,10),('one',e.ticket,11)]:
        with pytest.raises(HTTPException):
            with s.use(subject,ticket,at):pass
    with s.use('one',e.ticket,10):
        with pytest.raises(HTTPException):
            with s.use('one',e.ticket,10):pass
    now[0]=301
    with pytest.raises(HTTPException):
        with s.use('one',e.ticket,10):pass
    assert s.begin('two',20)


@pytest.mark.parametrize('operation,payload',[
    ('AssociateSoftwareToken',{'Username':'other'}),('VerifySoftwareToken',{'UserCode':'123456','Username':'other'}),
    ('SetUserMFAPreference',{'SoftwareTokenMfaSettings':{'Enabled':False,'PreferredMfa':False}}),
    ('SetUserMFAPreference',{'SoftwareTokenMfaSettings':{'Enabled':1,'PreferredMfa':1}}),
    ('SetUserMFAPreference',{'SMSMfaSettings':{'Enabled':True}}),
])
def test_gateway_cannot_target_accounts_or_remove_factors(operation,payload):
    gateway=AccountGateway(ISSUER)
    with pytest.raises(HTTPException) as error:gateway.call(operation,'fixture',**payload)
    assert error.value.status_code==422
