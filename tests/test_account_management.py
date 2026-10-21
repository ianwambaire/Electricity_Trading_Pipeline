"""Own-account Cognito management: real JWT verification, mocked provider, no AWS writes."""
import json
import time
from unittest.mock import patch

import httpx
import pytest
from api.account_service import AccountGateway, SELF_SERVICE_SCOPE
from test_api_security import client, signing, token, auth, SUB, ISSUER

DOMAIN = 'https://verified-test.auth.us-east-1.amazoncognito.com'


@pytest.fixture
def account_client(tmp_path, signing):
    def build(*, google=False, factors=None, factor_error=None):
        calls=[]
        attributes={'sub':SUB,'name':'Native Test','email':'person@example.test',
                    'email_verified':'true','preferred_username':'market_analyst',
                    'custom:private':'never-display'}
        if google: attributes['identities']=json.dumps([{'providerName':'Google','userId':'internal-linked-id'}])
        state={'revoked':False,'factors':['PASSWORD'] if factors is None else factors,'errors':{},'attributes':attributes}
        def handler(request):
            if request.url.path.endswith('/.well-known/openid-configuration'):
                return httpx.Response(200,json={'issuer':ISSUER,'userinfo_endpoint':DOMAIN+'/oauth2/userInfo'})
            if request.url.host=='verified-test.auth.us-east-1.amazoncognito.com':
                assert request.headers['authorization'].startswith('Bearer ')
                return httpx.Response(401,json={'error':'invalid_token'}) if state['revoked'] else httpx.Response(200,json={'sub':SUB})
            assert str(request.url)=='https://cognito-idp.us-east-1.amazonaws.com/'
            operation=request.headers['x-amz-target'].rsplit('.',1)[-1]
            body=json.loads(request.content)
            assert 'AccessToken' in body
            calls.append((operation,body))
            if state['revoked']:return httpx.Response(400,json={'__type':'NotAuthorizedException','message':'Access Token has been revoked'})
            if operation in state['errors']:return httpx.Response(400,json=state['errors'][operation])
            if operation=='GetUser':return httpx.Response(200,json={'Username':'internal-user-id','UserAttributes':[{'Name':k,'Value':v} for k,v in attributes.items()],**state.get('mfa',{})})
            if operation=='GetUserAuthFactors':
                if factor_error:return httpx.Response(400,json={'__type':factor_error})
                return httpx.Response(200,json={'Username':'internal-user-id','ConfiguredUserAuthFactors':state['factors']})
            if operation=='UpdateUserAttributes':
                for row in body['UserAttributes']:attributes[row['Name']]=row['Value']
            elif operation=='AssociateSoftwareToken' and state.get('mfa_test'):
                return httpx.Response(200,json=state.get('setup_result',{'SecretCode':'JBSWY3DPEHPK3PXP'}))
            elif operation=='VerifySoftwareToken' and state.get('mfa_test'):
                return httpx.Response(200,json=state.get('verify_result',{'Status':'SUCCESS'}))
            elif operation=='SetUserMFAPreference' and state.get('mfa_test'):
                state['mfa']={'UserMFASettingList':['SOFTWARE_TOKEN_MFA'],'PreferredMfaSetting':'SOFTWARE_TOKEN_MFA'}
            elif operation=='GlobalSignOut':state['revoked']=True
            elif operation!='ChangePassword':raise AssertionError('Unexpected provider mutation')
            return httpx.Response(200,json={})
        c=client(tmp_path,signing)
        c.app.state.account_gateway=AccountGateway(ISSUER,transport=httpx.MockTransport(handler))
        now=int(time.time())
        headers=auth(token(signing,scope='openid email profile '+SELF_SERVICE_SCOPE,auth_time=now-5))
        return c,headers,calls,state
    return build


def test_profile_retrieval_native_and_google_never_invent_password(account_client):
    for google,factors,expected in [(False,['PASSWORD'],True),(True,[],False),(True,['PASSWORD'],True)]:
        c,headers,calls,state=account_client(google=google,factors=factors)
        response=c.get('/account/profile',headers=headers)
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        data=response.json()
        assert data['password_configured'] is expected and data['role']=='Analyst'
        assert data['name_editable'] is (not google)
        assert data['connected_providers']==(['Google'] if google else [])
        assert data['email_editable'] is False and data['mfa_management']==('provider_managed' if google else 'unavailable')
        assert data['mfa_status']=='not_enabled'
        assert all(value not in response.text for value in ['internal-user-id','internal-linked-id','never-display',SUB,'AccessToken'])
        assert [op for op,_ in calls]==['GetUser','GetUserAuthFactors']


def test_missing_factor_capability_never_creates_password_control(account_client):
    c,headers,_,_=account_client(factor_error='OperationNotEnabledException')
    assert c.get('/account/profile',headers=headers).json()['password_configured'] is None
    assert c.post('/account/password',headers=headers,json={'current_password':'Previous!1','new_password':'NewPassword!2'}).status_code==409


def test_profile_updates_only_permitted_own_attributes(account_client):
    c,headers,calls,state=account_client()
    response=c.patch('/account/profile',headers=headers,json={'name':'Updated Name','preferred_username':'updated_label'})
    assert response.status_code==200
    update=[body for op,body in calls if op=='UpdateUserAttributes'][0]
    assert set(update)=={'AccessToken','UserAttributes'}
    assert {r['Name']:r['Value'] for r in update['UserAttributes']}=={'name':'Updated Name','preferred_username':'updated_label'}
    assert c.get('/account/profile',headers=headers).json()['name']=='Updated Name'
    assert state['attributes']['sub']==SUB


@pytest.mark.parametrize('body',[{}, {'name':''}, {'name':None}, {'name':'a\x00b'}, {'preferred_username':'x'*129}, {'name':'Valid','username':'other-user'}, {'sub':'other-user'}, {'role':'Admin'}, {'email':'other@example.test'}, {'email_verified':True}])
def test_invalid_unsupported_or_other_account_updates_are_rejected(account_client,body):
    c,headers,calls,_=account_client()
    response=c.patch('/account/profile',headers=headers,json=body)
    assert response.status_code==422
    assert response.json()=={'detail':{'code':'INVALID_ACCOUNT_INPUT'}}
    assert not any(op=='UpdateUserAttributes' for op,_ in calls)


def test_google_mapped_name_is_not_overwritten_but_preferred_label_is_editable(account_client):
    c,headers,calls,_=account_client(google=True,factors=[])
    assert c.patch('/account/profile',headers=headers,json={'name':'Local Name'}).status_code==409
    assert not any(op=='UpdateUserAttributes' for op,_ in calls)
    assert c.patch('/account/profile',headers=headers,json={'preferred_username':'google_label'}).status_code==200


def test_password_change_requires_confirmed_factor_and_actual_current_password(account_client):
    c,headers,calls,state=account_client()
    body={'current_password':'Previous!1','new_password':'NewPassword!2'}
    assert c.post('/account/password',headers=headers,json=body).json()=={'status':'password_changed'}
    operation=[r for op,r in calls if op=='ChangePassword'][0]
    assert operation['PreviousPassword']=='Previous!1' and operation['ProposedPassword']=='NewPassword!2'
    assert set(operation)=={'AccessToken','PreviousPassword','ProposedPassword'}
    state['errors']['ChangePassword']={'__type':'NotAuthorizedException','message':'Incorrect password. secret provider diagnostic'}
    response=c.post('/account/password',headers=headers,json=body)
    assert response.status_code==400 and response.json()['detail']['code']=='INCORRECT_PASSWORD'
    assert all(s not in response.text for s in ['Previous!1','NewPassword!2','secret'])
    c,headers,calls,state=account_client(google=True,factors=[])
    assert c.post('/account/password',headers=headers,json=body).status_code==409
    assert not any(op=='ChangePassword' for op,_ in calls)


def test_password_input_errors_never_echo_submitted_secrets(account_client,caplog):
    c,headers,calls,_=account_client()
    secret='do-not-echo-secret!1'
    response=c.post('/account/password',headers=headers,json={'current_password':secret,'new_password':secret,'Username':'another-account'})
    assert response.status_code==422 and secret not in response.text and secret not in caplog.text
    assert not any(op=='ChangePassword' for op,_ in calls)
    assert c.patch('/account/profile',headers=headers,json={'name':'x'*17000}).status_code==413
    assert c.patch('/account/profile?username=another',headers=headers,json={'name':'Valid'}).status_code==422


@pytest.mark.parametrize('path,method,body',[('/account/profile','get',None),('/account/profile','patch',{'name':'Updated'}),('/account/password','post',{'current_password':'Previous!1','new_password':'NewPassword!2'}),('/account/sign-out-all','post',None)])
def test_account_actions_require_valid_authentication(account_client,signing,path,method,body):
    c,headers,calls,_=account_client()
    assert c.request(method,path,json=body).status_code==401
    for changes in [{'token_use':'id'},{'client_id':'otherclient'},{'exp':1},{'iss':'https://wrong.invalid'}]:
        bad=auth(token(signing,scope='openid '+SELF_SERVICE_SCOPE,**changes))
        assert c.request(method,path,headers=bad,json=body).status_code==401
    assert not calls


def test_old_scopes_need_reconnection_but_existing_auth_me_still_works(account_client,signing):
    c,_,calls,_=account_client()
    headers=auth(token(signing))
    assert c.get('/auth/me',headers=headers).status_code==200
    response=c.get('/account/profile',headers=headers)
    assert response.status_code==403 and response.json()['detail']['code']=='ACCOUNT_RECONNECT_REQUIRED'
    assert not calls  # Legacy scope uses the trusted OIDC user-info endpoint.


def test_cross_device_signout_requires_recent_login_and_revoked_tokens_fail_everywhere(account_client,signing):
    c,headers,calls,state=account_client()
    old=auth(token(signing,scope='openid '+SELF_SERVICE_SCOPE,auth_time=int(time.time())-3600))
    response=c.post('/account/sign-out-all',headers=old)
    assert response.status_code==403 and response.json()['detail']['code']=='FRESH_SIGN_IN_REQUIRED'
    assert not any(op=='GlobalSignOut' for op,_ in calls)
    legacy=auth(token(signing,**{'cognito:groups':['powerflow-admins']}))
    assert c.post('/account/sign-out-all',headers=headers,json={'username':'someone-else'}).status_code==422
    assert c.post('/account/sign-out-all',headers=headers).json()=={'status':'signed_out'}
    for h in [headers,legacy]:
        for path in ['/auth/me','/account/profile','/admin/operations','/monitoring/forecast-vintages']:
            assert c.get(path,headers=h).status_code==401
    assert c.get('/health').status_code==200


def test_provider_errors_fail_closed_no_stale_or_sensitive_details(account_client):
    c,headers,calls,state=account_client()
    state['errors']['GetUser']={'__type':'InternalErrorException','message':'private infrastructure diagnostic'}
    r=c.get('/account/profile',headers=headers)
    assert r.status_code==503 and 'private' not in r.text
    state['errors']['GetUser']={'__type':'NotAuthorizedException','message':'Access Token has expired'}
    assert c.get('/account/profile',headers=headers).status_code==401
    state['errors']['GetUser']={'__type':'TooManyRequestsException','message':'private'}
    assert c.get('/account/profile',headers=headers).status_code==429


def test_mfa_and_email_actions_are_not_exposed(account_client):
    c,headers,calls,_=account_client()
    assert c.post('/account/mfa',headers=headers,json={'enabled':True}).status_code==404
    assert c.post('/account/email',headers=headers,json={'email':'new@example.test'}).status_code==404
    assert c.post('/account/email/verify',headers=headers,json={'code':'123456'}).status_code==404
    assert not calls


@pytest.mark.parametrize('metadata',[{'issuer':ISSUER,'userinfo_endpoint':'https://evil.invalid/oauth2/userInfo'}, {'issuer':'wrong','userinfo_endpoint':DOMAIN+'/oauth2/userInfo'}, {'issuer':ISSUER,'userinfo_endpoint':99}])
def test_discovery_does_not_allow_untrusted_userinfo_endpoints(metadata):
    from fastapi import HTTPException
    gateway=AccountGateway(ISSUER,transport=httpx.MockTransport(lambda _:httpx.Response(200,json=metadata)))
    with pytest.raises(HTTPException) as error:gateway.assert_active('fixture-token',frozenset({'openid'}),SUB)
    assert error.value.status_code==503


@pytest.mark.parametrize('field', ['cognito:groups', 'custom:role', 'user_id'])
def test_self_service_cannot_target_or_promote_account(account_client, field):
    c, headers, calls, _ = account_client()
    assert c.get('/account/profile', headers=headers).json()['role'] == 'Analyst'
    assert c.patch('/account/profile', headers=headers, json={field: 'powerflow-admins'}).status_code == 422
    assert c.get('/admin/operations', headers=headers).status_code == 403
    assert not any(op == 'UpdateUserAttributes' for op, _ in calls)


@pytest.mark.parametrize('field', ['email', 'email_verified', 'phone_number', 'phone_number_verified',
    'sub', 'username', 'identities', 'cognito:groups', 'cognito:roles', 'cognito:preferred_role',
    'custom:admin', 'UserAttributes', 'AccessToken'])
def test_security_sensitive_fields_never_reach_provider(account_client, field):
    c, headers, calls, _ = account_client()
    response = c.patch('/account/profile', headers=headers, json={field: 'untrusted-value'})
    assert response.status_code == 422
    assert not any(op == 'UpdateUserAttributes' for op, _ in calls)


def test_provider_attribute_permission_denial_does_not_expire_session(account_client):
    c, headers, _, state = account_client()
    state['errors']['UpdateUserAttributes'] = {
        '__type': 'NotAuthorizedException',
        'message': 'A client attempted to write unauthorized attribute. private diagnostic',
    }
    result = c.patch('/account/profile', headers=headers, json={'name': 'Allowed Name'})
    assert result.status_code == 403
    assert result.json() == {'detail': {'code': 'ATTRIBUTE_NOT_WRITABLE'}}
    assert 'private' not in result.text
    assert c.get('/auth/me', headers=headers).status_code == 200
    state['errors']['UpdateUserAttributes']['message'] = 'Access Token has been revoked'
    assert c.patch('/account/profile', headers=headers, json={'name': 'Allowed Name'}).status_code == 401


@pytest.mark.parametrize('rows', [
    [{'Name': 'email', 'Value': 'other@example.test'}],
    [{'Name': 'cognito:groups', 'Value': 'powerflow-admins'}],
    [{'Name': 'name', 'Value': 'Valid', 'Username': 'other-user'}],
    [{'Name': 'name', 'Value': 'One'}, {'Name': 'name', 'Value': 'Two'}],
])
def test_gateway_defense_rejects_non_profile_attribute_writes(rows):
    from fastapi import HTTPException
    def unexpected(_request):
        raise AssertionError('Forbidden write reached Cognito')
    gateway = AccountGateway(ISSUER, transport=httpx.MockTransport(unexpected))
    with pytest.raises(HTTPException) as result:
        gateway.call('UpdateUserAttributes', 'fixture', UserAttributes=rows)
    assert result.value.status_code == 422


def test_profile_changes_cannot_influence_signed_group_authorization(account_client, signing):
    c, headers, _, _ = account_client()
    assert c.patch('/account/profile', headers=headers, json={
        'name': 'Administrator', 'preferred_username': 'powerflow-admins',
    }).status_code == 200
    assert c.get('/auth/me', headers=headers).json()['role'] == 'Analyst'
    assert c.get('/admin/operations', headers=headers).status_code == 403
    admin = auth(token(signing, scope='openid '+SELF_SERVICE_SCOPE,
        **{'cognito:groups': ['powerflow-admins'], 'name': 'Analyst', 'role': 'Analyst'}))
    assert c.get('/auth/me', headers=admin).json()['role'] == 'Admin'


def test_live_provider_subject_must_match_verified_token_before_any_update(account_client):
    c, headers, calls, state = account_client()
    state['attributes']['sub'] = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
    assert c.get('/account/profile', headers=headers).status_code == 401
    assert c.patch('/account/profile', headers=headers, json={'name': 'Allowed'}).status_code == 401
    assert not any(op == 'UpdateUserAttributes' for op, _ in calls)


@pytest.mark.parametrize('operation', ['AdminUpdateUserAttributes', 'AdminAddUserToGroup', 'AdminLinkProviderForUser', 'DeleteUser'])
def test_gateway_never_exposes_administration_linking_or_account_deletion(operation):
    from fastapi import HTTPException
    def unexpected(_request):
        raise AssertionError('Unsupported operation reached provider')
    gateway = AccountGateway(ISSUER, transport=httpx.MockTransport(unexpected))
    with pytest.raises(HTTPException) as result:
        gateway.call(operation, 'fixture', Username='someone-else')
    assert result.value.status_code == 409
