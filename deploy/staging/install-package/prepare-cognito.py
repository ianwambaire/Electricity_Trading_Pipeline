"""LOCAL JSON transform only; never contacts AWS. Separate Cognito approval required."""
import json
import os
from pathlib import Path
import sys

ALLOWED={'UserPoolId','ClientId','ClientName','RefreshTokenValidity','AccessTokenValidity','IdTokenValidity',
 'TokenValidityUnits','ReadAttributes','WriteAttributes','ExplicitAuthFlows','SupportedIdentityProviders',
 'CallbackURLs','LogoutURLs','DefaultRedirectURI','AllowedOAuthFlows','AllowedOAuthScopes',
 'AllowedOAuthFlowsUserPoolClient','AnalyticsConfiguration','PreventUserExistenceErrors',
 'EnableTokenRevocation','EnablePropagateAdditionalUserContextData','AuthSessionValidity','RefreshTokenRotation'}

def prepare(raw):
    before=raw['UserPoolClient'];assert not before.get('ClientSecret'),'SPA unexpectedly has a client secret'
    assert set(before)<=ALLOWED|{'CreationDate','LastModifiedDate'},'Unrecognized client field; STOP rather than dropping it'
    assert before['ClientId']=='4t8s6a673a18qhbauqac8rhdcf' and before['UserPoolId']=='us-east-1_NLoYFRvex'
    result={k:v for k,v in before.items() if k in ALLOWED}
    for key,value in [('CallbackURLs','https://staging.powerflowenergy.dev/auth/callback'),('LogoutURLs','https://staging.powerflowenergy.dev/')]:
        assert isinstance(result.get(key),list)
        result[key]=list(result[key])
        if value not in result[key]:result[key].append(value)
    assert {k:v for k,v in result.items() if k not in ('CallbackURLs','LogoutURLs')}=={k:v for k,v in before.items() if k in ALLOWED and k not in ('CallbackURLs','LogoutURLs')}
    return result

if __name__=='__main__':
    os.umask(0o077);result=prepare(json.loads(Path(sys.argv[1]).read_text()))
    with Path(sys.argv[2]).open('x') as h:json.dump(result,h,indent=2)
    print('Local additive client update prepared; not applied.')
