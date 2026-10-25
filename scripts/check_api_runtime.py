"""Offline API-only import/lifecycle probe. Never touches production data or identity."""
import importlib.abc
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


class ExcludeResearch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'mlflow', 'streamlit', 'prefect', 'sklearn', 'boto3'}:
            raise ImportError('API attempted a non-API runtime import')
        return None


def main():
    # Use the caller's real config at module import; invalid deployed config fails.
    blocker = ExcludeResearch()
    sys.meta_path.insert(0, blocker)
    try:
        from api.app import APISettings, create_app
        from api.runtime import RuntimeSettings
        from api.security import SecuritySettings
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory(prefix='powerflow-api-import-') as directory:
            root = Path(directory)
            # Test-only issuer/client; no token requests, no network and no accounts.
            security = SecuritySettings('https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OfflineTest', frozenset({'offlineclient'}))
            app = create_app(APISettings.from_root(root), security_settings=security,
                             runtime_settings=RuntimeSettings('staging', ('testserver',)))
            with TestClient(app) as client:
                assert client.get('/health').status_code == 200
                assert client.get('/ready').status_code == 503
                assert client.get('/admin/operations').status_code == 401
                assert client.get('/docs').status_code == 404
                assert client.get('/forecast/next24').status_code == 404
            assert not (root/'database').exists()
        print(json.dumps({'status':'ok', 'scope':'offline API imports and lifespan; no live provider/data validation',
                          'python':sys.version.split()[0]}))
    finally:
        sys.meta_path.remove(blocker)


if __name__ == '__main__':
    main()
