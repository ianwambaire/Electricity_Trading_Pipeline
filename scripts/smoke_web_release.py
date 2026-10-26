"""Local in-process HTTP release rehearsal, never an installed Nginx validator.

Uses synthetic persisted API fixtures plus real built static bytes; no listener,
provider request, credentials, production services or data mutation is involved.
Run from repo root: venv/bin/python -B scripts/smoke_web_release.py --dist frontend/dist
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from api.app import APISettings, create_app
from api.runtime import RuntimeSettings
from api.security import SecuritySettings, CurrentUser, require_authenticated_user
from preflight_server import fixture_data

ROUTES=('/', '/analytics','/forecasting','/anomalies','/models','/pipeline','/profile')
ADMIN=('/admin/operations','/admin/forecast/provenance','/admin/models/linear-feature-influence',
       '/admin/monitoring/forecast-vintages','/admin/monitoring/exogenous-readiness',
       '/monitoring/forecast-vintages','/monitoring/exogenous-readiness')


def frontend_rehearsal(dist, backend):
    """Mirrors required routing/cache semantics for local contract tests only."""
    dist=dist.resolve()
    index=(dist/'index.html').read_bytes()
    def handle(request):
        path=request.path_params.get('path','')
        if request.method not in {'GET','HEAD'}:
            return Response(status_code=405,headers={'Cache-Control':'no-store'})
        if path.startswith('api/'):
            route='/'+path[4:]
            if route.split('/')[1] in {'ready','docs','redoc','openapi.json'}:
                return Response(status_code=404,headers={'Cache-Control':'no-store'})
            result=backend.get(route)
            headers={key:value for key,value in result.headers.items() if key.lower() not in {'content-length','content-encoding'}}
            return Response(result.content,status_code=result.status_code,headers=headers)
        if path=='api' or any(part.startswith('.') for part in path.split('/')) or path.split('/')[0] in {'src','tests','node_modules','deploy','database','data','artifacts'}:
            return Response(status_code=404,headers={'Cache-Control':'no-store'})
        if path.startswith('assets/'):
            target=dist/path
            if not target.is_file() or target.is_symlink() or dist not in target.resolve().parents:
                return Response(status_code=404,headers={'Cache-Control':'no-store'})
            media='text/css' if target.suffix=='.css' else 'text/javascript' if target.suffix=='.js' else 'application/octet-stream'
            return Response(target.read_bytes(),media_type=media,headers={'Cache-Control':'public, max-age=31536000, immutable','X-Content-Type-Options':'nosniff'})
        return Response(index,media_type='text/html',headers={'Cache-Control':'no-cache, no-store, must-revalidate','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer'})
    return Starlette(routes=[Route('/{path:path}',handle,methods=['GET','HEAD','POST','PATCH','DELETE','PUT'])])


def run(dist):
    manifest=json.loads((dist/'build-config.json').read_text())
    if manifest.get('apiBase')!='/api' or manifest.get('releaseEligible') is not True:
        raise ValueError('An explicit-origin release candidate is required')
    with tempfile.TemporaryDirectory(prefix='powerflow-release-smoke-') as temp:
        root=Path(temp)/'synthetic';fixture_data(root,Path(temp)/'absent')
        security=SecuritySettings('https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OfflineTest',frozenset({'offlineclient'}))
        app=create_app(APISettings.from_root(root),security_settings=security,runtime_settings=RuntimeSettings('staging',('testserver',)))
        # Any attempted account/provider access must fail the rehearsal.
        class OfflineGateway:
            def assert_active(self,*args,**kwargs):raise AssertionError('Provider access forbidden in local smoke')
        app.state.account_gateway=OfflineGateway()
        with TestClient(app) as api, TestClient(frontend_rehearsal(dist,api)) as web:
            for path in (*ROUTES,'/auth/callback'):
                result=web.get(path)
                assert result.status_code==200 and result.content==(dist/'index.html').read_bytes()
                assert 'no-store' in result.headers['cache-control']
            for path in ('/api/health','/api/pipeline/status','/api/market/coverage','/api/market/summary','/api/models/summary','/api/anomalies/summary','/api/forecast/next24'):
                response=web.get(path);assert response.status_code==200,path
                assert response.headers['cache-control']=='no-store'
            assert web.get('/api/ready').status_code==404
            assert web.get('/api/docs').status_code==404
            assert web.get('/api/no-such-route').status_code==404
            assert web.get('/assets/no-such-file.js').status_code==404
            for route in ADMIN:assert web.get('/api'+route).status_code==401
            app.dependency_overrides[require_authenticated_user]=lambda:CurrentUser('01234567-89ab-4def-8123-0123456789ab','Analyst')
            for route in ADMIN:assert web.get('/api'+route).status_code==403
            app.dependency_overrides.clear()
            # Isolated readiness vs process health distinction, no provider request.
            assert api.get('/ready').status_code==200
            app.state.cognito_verifier=None
            assert api.get('/health').status_code==200 and api.get('/ready').status_code==503
        return {'scope':'local in-process routing/API rehearsal; SYNTHETIC data, dependency-overridden Analyst; no live JWT/OIDC/Nginx proof',
                'pages':len(ROUTES),'callback_fallback':True,'analyst_denials':len(ADMIN),'api_base':'/api',
                'index_sha256':hashlib.sha256((dist/'index.html').read_bytes()).hexdigest(),'origin':manifest['origin'],'production_deployed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dist',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(run(args.dist.resolve()),indent=2))
