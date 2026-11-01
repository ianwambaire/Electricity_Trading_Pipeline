"""Cold local packaged-API verification. No listener, providers or production data."""
import argparse
from pathlib import Path
import os
import subprocess
import sys
import tempfile

CHILD=r'''
import importlib.abc,json,socket,sys
from pathlib import Path
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'streamlit','sklearn','joblib','mlflow','prefect','boto3','processing'}:
            raise AssertionError('Unexpected API runtime dependency')
sys.meta_path.insert(0,Block())
def no_network(*args,**kwargs):raise AssertionError('External network forbidden')
socket.create_connection=no_network
sys.path.insert(0,str(Path(sys.argv[1])/'api/src'))
from dataclasses import replace
from types import SimpleNamespace
from fastapi.testclient import TestClient
from api.app import APISettings,create_app
from api.security import SecuritySettings,CognitoVerifier,JwksCache
from joserfc import jwk,jwt
import time
root=Path(sys.argv[2])/'absent-data'
settings=replace(APISettings.from_root(root),next24_publication_root=Path(sys.argv[2])/'absent-publication')
security=SecuritySettings('https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OfflineTest',frozenset({'offlineclient'}))
app=create_app(settings,security_settings=security)
key=jwk.RSAKey.generate_key(2048,parameters={'kid':'local','alg':'RS256','use':'sig'})
app.state.cognito_verifier=CognitoVerifier(security,JwksCache(security.jwks_url,fetch=lambda _:{'keys':[key.as_dict(private=False)]}))
app.state.account_gateway=SimpleNamespace(assert_active=lambda _token,_scopes,subject:{'sub':subject})
def token(admin=False):
    now=int(time.time())
    value={'iss':security.issuer,'sub':'11111111-1111-4111-8111-111111111111','client_id':'offlineclient','token_use':'access','scope':'openid','iat':now-1,'exp':now+300}
    if admin:value['cognito:groups']=['powerflow-admins']
    return jwt.encode({'alg':'RS256','kid':'local'},value,key)
routes=['/admin/operations','/admin/forecast/provenance','/admin/models/linear-feature-influence','/admin/monitoring/forecast-vintages','/admin/monitoring/exogenous-readiness','/monitoring/forecast-vintages','/monitoring/exogenous-readiness']
with TestClient(app) as client:
    assert client.get('/health').status_code==200
    assert client.get('/ready').status_code==503 # synthetic data root is deliberately absent
    for path in routes:
        assert client.get(path).status_code==401
        assert client.get(path,headers={'Authorization':'Bearer '+token()}).status_code==403
    forecast=client.get('/forecast/next24')
    assert forecast.status_code==503 and forecast.json()=={'detail':{'code':'FORECAST_WITHHELD'}}
    evidence=client.get('/admin/forecast/provenance',headers={'Authorization':'Bearer '+token(True)})
    assert evidence.status_code==503 and evidence.json()==forecast.json()
    summary=client.get('/operations/summary').json()
    assert summary['forecast_status']=='MISSING_PUBLICATION' and summary['health']=='Unavailable'
assert not root.exists()
print(json.dumps({'status':'PASS','scope':'local cold packaged API, synthetic absent sources; NOT Linux/staging acceptance','admin_denials':len(routes),'network':'blocked','research_ui_dependencies':'blocked','production_access':False}))
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--release',type=Path,required=True);args=p.parse_args()
    release=args.release
    if not release.is_absolute() or release.resolve(strict=True)!=release:raise ValueError('canonical_release_required')
    with tempfile.TemporaryDirectory(prefix='powerflow-package-runtime-') as temporary:
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':temporary,'AWS_EC2_METADATA_DISABLED':'true','PYTHONDONTWRITEBYTECODE':'1','MPLBACKEND':'Agg'}
        result=subprocess.run([sys.executable,'-I','-B','-c',CHILD,str(release),temporary],env=env,cwd=temporary,
                              capture_output=True,timeout=45)
        if result.returncode:
            print('{"status":"FAIL","raw_output_withheld":true}');raise SystemExit(result.returncode)
        print(result.stdout.decode().strip())


if __name__=='__main__':main()
