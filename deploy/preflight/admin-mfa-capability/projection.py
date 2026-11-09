"""Offline-only configuration projection. No SDK imports, credentials or calls."""
POOL='us-east-1_NLoYFRvex'
CLIENTS=('4t8s6a673a18qhbauqac8rhdcf','5qa93km3lf2bbu3ffnrpea4r3g')

def require(value):
    if not value:raise ValueError('CONFIGURATION_UNVERIFIED')

def project(pool_response,mfa_response,client_responses):
    require(type(pool_response)is dict and type(mfa_response)is dict)
    pool=pool_response.get('UserPool');require(type(pool)is dict and pool.get('Id')==POOL)
    mfa=mfa_response.get('MfaConfiguration');require(type(mfa)is str and mfa in {'OFF','OPTIONAL','ON'})
    # AWS API uses ON, whereas the console calls the policy "required".
    tier=pool.get('UserPoolTier');require(tier is None or type(tier)is str and tier in {'LITE','ESSENTIALS','PLUS'})
    software=mfa_response.get('SoftwareTokenMfaConfiguration',{});require(type(software)is dict)
    totp=software.get('Enabled')
    require(totp is None or type(totp)is bool)
    require(type(client_responses)is list and len(client_responses)==2)
    clients={}
    for raw in client_responses:
        require(type(raw)is dict)
        c=raw.get('UserPoolClient');require(type(c)is dict and c.get('UserPoolId')==POOL and c.get('ClientId')in CLIENTS and c['ClientId']not in clients)
        providers=c.get('SupportedIdentityProviders');scopes=c.get('AllowedOAuthScopes');flows=c.get('AllowedOAuthFlows')
        require(all(type(v)is list and all(type(x)is str for x in v) for v in [providers,scopes,flows]))
        label='react' if c['ClientId']==CLIENTS[0] else 'legacy'
        clients[c['ClientId']]={
            'label':label,'native_supported':'COGNITO'in providers,'google_supported':'Google'in providers,
            'authorization_code_enabled':c.get('AllowedOAuthFlowsUserPoolClient')is True and 'code'in flows,
            'public_client':'ClientSecret'not in c,'self_service_scope_supported':'aws.cognito.signin.user.admin'in scopes,
            'revocation_enabled':c.get('EnableTokenRevocation')is True}
    require(set(clients)==set(CLIENTS))
    device=pool.get('DeviceConfiguration');require(device is None or type(device)is dict)
    acr=pool.get('AcrConfiguration');require(acr is None or type(acr)is dict)
    for key in ('ChallengeRequiredOnNewDevice','DeviceOnlyRememberedOnUserPrompt'):
        require(device is None or device.get(key)is None or type(device[key])is bool)
    policies=pool.get('Policies',{});require(type(policies)is dict)
    signin=policies.get('SignInPolicy',{});require(type(signin)is dict)
    factors=signin.get('AllowedFirstAuthFactors');require(factors is None or type(factors)is list and all(type(f)is str and f in {'PASSWORD','EMAIL_OTP','SMS_OTP','WEB_AUTHN'} for f in factors))
    return {'pool_mfa':{'ON':'REQUIRED','OFF':'OFF','OPTIONAL':'OPTIONAL'}[mfa],
            'totp_enabled':totp,'feature_plan':tier or 'NOT_REPORTED',
            'step_up_plan_eligible':None if tier is None else tier in {'ESSENTIALS','PLUS'},
            'assurance_configuration_reported':acr is not None,
            'remembered_device_configuration_present':device is not None,
            'device_mfa_challenge_required':None if device is None else device.get('ChallengeRequiredOnNewDevice'),
            'device_remembering_owner_opt_in':None if device is None else device.get('DeviceOnlyRememberedOnUserPrompt'),
            'password_first_factor_enabled':None if factors is None else 'PASSWORD'in factors,
            'claims_verified':False,'enforceability':'REQUIRES_SIGNED_SESSION_ACCEPTANCE',
            'clients':[clients[k]for k in CLIENTS]}
