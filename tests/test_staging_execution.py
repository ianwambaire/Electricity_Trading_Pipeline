"""Offline template and smoke-protocol checks; not evidence of Linux installation."""
from pathlib import Path
import importlib.util
import httpx
import pytest
ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('staging_smoke',ROOT/'scripts/smoke_staging.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_smoke_covers_pages_roles_and_withheld_without_writes():
    calls=[]
    def handler(req):
        calls.append(req)
        assert req.method=='GET'
        path=req.url.path
        if path in (*m.PAGES,'/auth/callback'):
            return httpx.Response(200,text='<div id="root"></div>',headers={'content-type':'text/html'})
        if path=='/api/ready':return httpx.Response(404)
        if path.removeprefix('/api') in m.ADMIN:
            token=req.headers.get('authorization')
            return httpx.Response(401 if not token else 403 if token=='Bearer analyst' else 404)
        if path=='/api/auth/me':return httpx.Response(200,json={'role':'Analyst' if req.headers['authorization']=='Bearer analyst' else 'Admin'})
        if path=='/api/forecast/next24':return httpx.Response(404)
        return httpx.Response(200)
    with httpx.Client(base_url='https://staging.powerflowenergy.dev',transport=httpx.MockTransport(handler)) as c:
        assert m.verify(c,'analyst','admin')['analyst_admin_denials']==7
    assert len([q for q in calls if q.url.path in m.PAGES])==7


def test_smoke_fails_if_analyst_has_admin_access():
    def handler(req):
        if req.url.path in (*m.PAGES,'/auth/callback'):return httpx.Response(200,text='<div id="root">',headers={'content-type':'text/html'})
        if req.url.path=='/api/ready':return httpx.Response(404)
        if req.url.path=='/api/admin/operations' and not req.headers.get('authorization'):return httpx.Response(401)
        return httpx.Response(200)
    with httpx.Client(base_url='https://staging.powerflowenergy.dev',transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(AssertionError):m.verify(c,'analyst','admin')


def test_staging_virtual_host_never_claims_apex_and_hides_internal_routes():
    t=(ROOT/'deploy/staging/staging.powerflowenergy.dev.conf').read_text()
    assert 'server_name staging.powerflowenergy.dev;' in t
    assert 'server_name powerflowenergy.dev' not in t
    assert 'proxy_pass http://127.0.0.1:8010/;' in t
    assert 'ready|docs|redoc|openapi' in t and '$proxy_add_x_forwarded_for' not in t
    assert '/var/www/powerflow-staging/current' in t
    assert 'try_files $uri =404;' in t and 'proxy_intercept_errors off' in t
    for name in ('activate-staging.sh','rollback-staging.sh'):
        t=(ROOT/'deploy/staging'/name).read_text()
        assert 'nginx -t' in t and 'systemctl reload nginx' in t
        assert 'systemctl restart' not in t and 'rm ' not in t
        assert 'powerflow-streamlit' not in t and 'powerflow-api.service' not in t


@pytest.mark.parametrize('script',['activate-staging.sh','rollback-staging.sh','switch-candidate.sh'])
@pytest.mark.parametrize('bad',['..','.','/tmp/other','-x','x/../../other'])
def test_shell_rejects_destination_escape_before_any_operation(script,bad):
    import subprocess
    args=['bash',str(ROOT/'deploy/staging'/script),bad]
    if script=='switch-candidate.sh':args.append('safe-record')
    assert subprocess.run(args,capture_output=True).returncode==64
