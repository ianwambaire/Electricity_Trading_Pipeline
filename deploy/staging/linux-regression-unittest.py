"""Offline candidate regression subset; stdlib unittest, synthetic DB/JWKS only."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

sys.path.insert(0,'/candidate/src')
from api.app import APISettings, create_app
from api.runtime import RuntimeSettings
from api.security import SecuritySettings, CognitoVerifier, JwksCache
from fastapi.testclient import TestClient
from joserfc import jwk, jwt

ADMIN=('/admin/operations','/admin/forecast/provenance','/admin/models/linear-feature-influence',
       '/admin/monitoring/forecast-vintages','/admin/monitoring/exogenous-readiness',
       '/monitoring/forecast-vintages','/monitoring/exogenous-readiness')

class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=jwk.RSAKey.generate_key(2048,parameters={'kid':'offline-key','alg':'RS256','use':'sig'})
        cls.identity=SecuritySettings('https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool',frozenset({'testclient'}))
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.app=create_app(APISettings.from_root(self.root),security_settings=self.identity,
                            runtime_settings=RuntimeSettings('staging',('testserver',)))
        self.app.state.cognito_verifier=CognitoVerifier(self.identity,JwksCache(self.identity.jwks_url,
            fetch=lambda _: {'keys':[self.key.as_dict(private=False)]}))
        self.app.state.account_gateway=SimpleNamespace(assert_active=lambda _token,_scopes,subject:{'sub':subject})
        self.client=TestClient(self.app);self.client.__enter__()
    def tearDown(self):self.client.__exit__(None,None,None);self.tmp.cleanup()
    def token(self,groups=None,**changes):
        now=int(time.time());claims=dict(iss=self.identity.issuer,sub='01234567-89ab-4def-8123-0123456789ab',
            client_id='testclient',token_use='access',iat=now-1,exp=now+300,scope='openid')
        if groups is not None:claims['cognito:groups']=groups
        claims.update(changes)
        return {'Authorization':'Bearer '+jwt.encode({'alg':'RS256','kid':self.key.kid},claims,self.key)}
    def database(self):
        p=self.root/'database/electricity_trading.db';p.parent.mkdir()
        with sqlite3.connect(p) as db:
            db.execute('CREATE TABLE pipeline_runs(id INTEGER,run_time TEXT,status TEXT,message TEXT)')
            db.execute('CREATE TABLE data_quality_results(id INTEGER,check_time TEXT,check_name TEXT,status TEXT)')
            db.execute('INSERT INTO pipeline_runs VALUES(1,?,?,?)',('2026-10-01T00:00:00Z','SUCCESS',json.dumps({'next24h_forecast_status':'WITHHELD'})))
        self.app.state.readiness._until=0
        return p
    def test_compiled_dependencies_and_pins(self):
        import numpy,pandas,_cffi_backend,pydantic_core
        from cryptography.hazmat.primitives import hashes
        assert numpy.array([1,2,3]).sum()==6
        assert pandas.DataFrame({'value':[1,2]}).value.sum()==3
        h=hashes.Hash(hashes.SHA256());h.update(b'offline');assert len(h.finalize())==32
        for line in Path('/candidate/requirements/api.lock').read_text().splitlines():
            if '==' in line:
                name,version=line.split('==');self.assertEqual(importlib.metadata.version(name),version)
    def test_process_health_and_missing_dependency_readiness(self):
        self.assertEqual(self.client.get('/health').status_code,200)
        self.assertEqual(self.client.get('/ready').status_code,503)
        self.assertFalse((self.root/'database').exists())
    def test_readiness_required_schema_and_no_database_write(self):
        p=self.database();before=hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(self.client.get('/ready').status_code,200)
        self.client.get('/pipeline/status')
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),before)
    def test_all_seven_analyst_denials_and_unauthenticated_denials(self):
        for path in ADMIN:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code,401)
                self.assertEqual(self.client.get(path,headers=self.token()).status_code,403)
    def test_verified_groups_and_admin_access_boundary(self):
        for groups,role in [([], 'Analyst'),(['powerflow-admins-evil'],'Analyst'),(['powerflow-admins'],'Admin')]:
            with self.subTest(role=role,groups=groups):
                self.assertEqual(self.client.get('/auth/me',headers=self.token(groups)).json()['role'],role)
        for path in ADMIN:self.assertNotIn(self.client.get(path,headers=self.token(['powerflow-admins'])).status_code,(401,403))
    def test_expired_wrong_issuer_client_and_token_use(self):
        for changes in ({'exp':1},{'iss':'https://wrong.invalid'},{'client_id':'wrong'},{'token_use':'id'},{'scope':'email'}):
            with self.subTest(changes=changes):self.assertEqual(self.client.get('/auth/me',headers=self.token(**changes)).status_code,401)
    def test_withheld_and_missing_forecast_is_not_fabricated(self):
        self.database()
        self.assertEqual(self.client.get('/pipeline/status').json()['forecast_status'],'WITHHELD')
        self.assertEqual(self.client.get('/forecast/next24').status_code,404)
    def test_deployed_docs_disabled_and_no_research_imports(self):
        for path in ('/docs','/redoc','/openapi.json'):self.assertEqual(self.client.get(path).status_code,404)
        for name in ('streamlit','prefect','mlflow','boto3','sklearn','joblib'):self.assertNotIn(name,sys.modules)

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CandidateTests))
    print('REGRESSION_JSON='+json.dumps({'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'successful':result.wasSuccessful(),'scope':'offline synthetic data and JWT/JWKS; no real Cognito'}),flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 1)
