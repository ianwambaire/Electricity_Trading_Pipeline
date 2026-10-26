"""Pure parser tests only. Never run the host inspection function."""
import importlib.util
from pathlib import Path
import json
ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('inspection',ROOT/'deploy/preflight/inspect-production-readonly.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_config_summary_never_exposes_secret_directives_or_values():
    text='''server { listen 443 ssl; server_name powerflowenergy.dev; location /api/ { proxy_pass http://127.0.0.1:8000/; proxy_set_header Authorization "Bearer synthetic-sensitive"; } try_files $uri /index.html; ssl_certificate /public/cert.pem; ssl_certificate_key /private/key.pem; add_header X-Frame-Options DENY; }'''
    result=m.safe_nginx(text);rendered=json.dumps(result)
    assert result['spa_fallback'] and result['api_locations'] and result['upstream_loopback_ports']==[8000]
    assert result['private_key_directive_present']
    assert 'synthetic-sensitive' not in rendered and '/private/key.pem' not in rendered


def test_nonloopback_upstreams_and_unrelated_hosts_are_not_emitted():
    result=m.safe_nginx('server { server_name private.internal; location / { proxy_pass https://user:password@private.internal; } }')
    assert result['server_names']==[] and result['upstream_loopback_ports']==[]
    assert 'password' not in json.dumps(result)
