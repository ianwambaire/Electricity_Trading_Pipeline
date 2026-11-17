"""Offline AWS protocol and SDK integrity tests. Sockets are forbidden in SDK subprocesses."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'deploy/staging/forecast-publication/load-source-check-aws-v2'
OLD = ROOT / 'deploy/staging/forecast-publication/load-source-check'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


r = load(HERE / 'run.py', 'aws_source_runner_test')
sdk = load(HERE / 'sdk.py', 'aws_sdk_unit_test')
old = load(OLD / 'run.py', 'old_load_source_runner_test')


def provider():
    return old.namespace(old.provider_source((ROOT / r.PROVIDER).read_bytes()), 'verified_provider_fixture')


def inspector():
    p = provider()
    h = {'__name__': 'verified_host_fixture', 'PROVIDER': p,
         'PARSER': old.namespace((OLD / 'vendor/parser.py').read_bytes(), 'parser_fixture'),
         'VARIABLES': old.namespace((OLD / 'vendor/variables.py').read_bytes(), 'variables_fixture')}
    exec(compile(r.host_source((OLD / 'inspect.py').read_bytes()), '<verified-host-fixture>', 'exec'), h)
    space = {'__name__': 'aws_inspector_fixture', 'H': h, 'PROVIDER': p, 'AWS': sdk.__dict__,
             'CORE': old.namespace((OLD / 'check.py').read_bytes(), 'core_fixture'),
             'SDK_LOCK': json.loads((HERE / 'SDK-LOCK.json').read_bytes()), 'CHILD_SOURCE': b'# held source'}
    exec(compile((HERE / 'inspect.py').read_bytes(), '<inspector-fixture>', 'exec'), space)
    return space


@pytest.mark.parametrize('backend,identifier', [('ssm', '/powerflow/production/ENTSOE_API_KEY'),
                                               ('secretsmanager', 'powerflow/production/ENTSOE_API_KEY')])
def test_production_selection_semantics(backend, identifier):
    p = provider()
    assert sdk.selection(p, {'POWERFLOW_SECRETS_BACKEND': backend}) == (backend, 'us-east-1', identifier)
    selected = sdk.selection(p, {'POWERFLOW_SECRETS_BACKEND': backend,
        'POWERFLOW_SECRET_ID_ENTSOE_API_KEY': 'fixture/ENTSOE_API_KEY', 'ENTSOE_API_KEY': 'must-not-fallback'})
    assert selected[2] == 'fixture/ENTSOE_API_KEY'


@pytest.mark.parametrize('env', [
    {}, {'POWERFLOW_SECRETS_BACKEND': 'env'}, {'POWERFLOW_SECRETS_BACKEND': 'other'},
    {'POWERFLOW_SECRETS_BACKEND': 'ssm', 'AWS_REGION': 'eu-west-1'},
    {'POWERFLOW_SECRETS_BACKEND': 'ssm', 'AWS_ACCESS_KEY_ID': 'PRIVATE'},
    {'POWERFLOW_SECRETS_BACKEND': 'ssm', 'AWS_PROFILE': 'PRIVATE'},
    {'POWERFLOW_SECRETS_BACKEND': 'ssm', 'AWS_ENDPOINT_URL': 'https://PRIVATE'},
    {'POWERFLOW_SECRETS_BACKEND': 'ssm', 'AWS_EC2_METADATA_DISABLED': 'true'},
    {'POWERFLOW_SECRETS_BACKEND': 'ssm', 'AWS_EC2_METADATA_SERVICE_ENDPOINT': 'http://PRIVATE'},
    {'POWERFLOW_SECRETS_BACKEND': 'ssm', 'POWERFLOW_SECRET_ID_ENTSOE_API_KEY': 'https://PRIVATE'},
    {'POWERFLOW_SECRETS_BACKEND': 'secretsmanager', 'POWERFLOW_SECRET_ID_ENTSOE_API_KEY': 'arn:aws:secretsmanager:eu-west-1:123456789012:secret:PRIVATE'},
])
def test_invalid_configuration_has_no_fallback_or_lookup(env):
    with pytest.raises(sdk.Blocked, match='AWS_CONFIGURATION_REJECTED'):
        sdk.selection(provider(), env)


@pytest.mark.parametrize('identifier', ['/fixture/key:3', '/fixture/key:production',
                                      'arn:aws:ssm:us-east-1:123456789012:parameter/fixture/key:3'])
def test_configured_ssm_selectors_are_preserved(identifier):
    env = {'POWERFLOW_SECRETS_BACKEND': 'ssm', 'POWERFLOW_SECRET_ID_ENTSOE_API_KEY': identifier}
    assert sdk.selection(provider(), env)[2] == identifier


@pytest.mark.parametrize('backend', ['ssm', 'secretsmanager'])
def test_original_get_secret_exact_sdk_methods_uncached(backend):
    p = provider()
    calls = []
    def facade(files, service, region, identifier, state):
        assert (service, region) == (backend, 'us-east-1')
        class Session:
            def __init__(self, **kwargs):
                assert kwargs == {'region_name': 'us-east-1'}
                calls.append('session')
            def get_credentials(self):
                state['iam_role'] = True
                return types.SimpleNamespace(method='iam-role')
            def client(self, name):
                assert name == backend
                return self
            def get_parameter(self, **kwargs):
                assert backend == 'ssm' and kwargs == {'Name': identifier, 'WithDecryption': True}
                calls.append('GetParameter')
                return {'Parameter': {'Value': 'fixture-secret'}}
            def get_secret_value(self, **kwargs):
                assert backend == 'secretsmanager' and kwargs == {'SecretId': identifier}
                calls.append('GetSecretValue')
                return {'SecretBinary': b'fixture-secret'}
        return types.SimpleNamespace(Session=Session)
    env = {'POWERFLOW_SECRETS_BACKEND': backend, 'ENTSOE_API_KEY': 'must-not-fallback'}
    for _ in range(2):
        assert sdk.obtain(p, env, {}, facade) == 'fixture-secret'
    assert calls.count('session') == 2
    assert not hasattr(p['_load_aws_secret'], 'cache_info')


def test_sdk_failure_and_nonrole_do_not_use_env_token():
    p = provider()
    def facade(files, service, region, identifier, state):
        class Session:
            def __init__(self, **kwargs): pass
            def get_credentials(self): return types.SimpleNamespace(method='env')
            def client(self, *args): pytest.fail('non-role credentials reached AWS API')
        return types.SimpleNamespace(Session=Session)
    with pytest.raises(sdk.Blocked, match='AWS_ROLE_UNVERIFIED'):
        sdk.obtain(p, {'POWERFLOW_SECRETS_BACKEND': 'ssm', 'ENTSOE_API_KEY': 'must-not-fallback'}, {}, facade)


SMOKE = r'''
import pathlib,json,importlib.util,os,sys,io,socket,base64,logging
root=pathlib.Path(sys.argv[1]);backend=sys.argv[2];scenario=sys.argv[3]
here=root/'deploy/staging/forecast-publication/load-source-check-aws-v2'
spec=importlib.util.spec_from_file_location('offline_sdk',here/'sdk.py');s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
site=root/'venv/lib/python3.14/site-packages';lock=json.loads((here/'SDK-LOCK.json').read_bytes())
files={name:(site/name).read_bytes() for name in lock['files']}
os.environ.clear();os.environ.update({'AWS_CONFIG_FILE':'/dev/null','AWS_SHARED_CREDENTIALS_FILE':'/dev/null','BOTO_CONFIG':'/dev/null','BOTO_DISABLE_CRT':'true'})
def denied(*args,**kwargs):raise AssertionError('REAL_NETWORK_FORBIDDEN')
socket.socket.connect=denied;socket.getaddrinfo=denied
logging.disable(logging.CRITICAL)
loader=s.MemorySDK(files);loader.install()
import urllib3.connectionpool,urllib3.response
calls=[]
def fake(pool,method,url,**kwargs):
 assert kwargs.get('redirect') is False
 calls.append((pool.host,method,url))
 status=200
 if pool.host=='169.254.169.254':
  if url=='/latest/api/token':
   body=b'fixture-imds-token'
   if scenario=='imds_v1':status=404;body=b''
  elif url=='/latest/meta-data/iam/security-credentials/':body=b'fixture-role'
  else:body=json.dumps({'AccessKeyId':'fixture-access','SecretAccessKey':'fixture-key','Token':'fixture-session','Expiration':'2099-01-01T00:00:00Z'}).encode()
 else:
  assert pool.host==backend+'.us-east-1.amazonaws.com' and method=='POST' and url=='/'
  assert pool.cert_reqs=='CERT_REQUIRED' and pool.ca_certs=='/fixture/trusted-ca.pem'
  request=json.loads(kwargs['body'])
  assert request==({'Name':'/powerflow/production/ENTSOE_API_KEY','WithDecryption':True} if backend=='ssm' else {'SecretId':'powerflow/production/ENTSOE_API_KEY'})
  if scenario=='denied':status=400;body=b'{"__type":"AccessDeniedException","message":"PRIVATE_ARN_OR_SECRET"}'
  elif scenario=='server_error':status=500;body=b'{"__type":"InternalServerError","message":"PRIVATE"}'
  elif scenario=='redirect':status=302;body=b''
  elif scenario=='missing':body=b'{}'
  elif scenario=='body_bound':body=b'x'*(s.BODY_LIMIT+1)
  elif backend=='ssm':body=b'{"Parameter":{"Value":"fixture-entsoe"}}'
  elif scenario=='binary':body=json.dumps({'SecretBinary':base64.b64encode(b'fixture-entsoe').decode()}).encode()
  else:body=b'{"SecretString":"fixture-entsoe"}'
 headers={'Content-Type':'application/x-amz-json-1.1','Content-Length':str(len(body))}
 if scenario=='redirect' and pool.host!='169.254.169.254':headers['Location']='https://unapproved.invalid/PRIVATE'
 if scenario=='header_bound' and pool.host!='169.254.169.254':headers['Content-Length']=str(s.BODY_LIMIT+1)
 return urllib3.response.HTTPResponse(body=io.BytesIO(body),status=status,headers=headers,preload_content=False)
urllib3.connectionpool.HTTPConnectionPool.urlopen=fake
s.os_ca=lambda:'/fixture/trusted-ca.pem'
if scenario in {'bad_url','bad_method','mutation_target','bad_identifier','duplicate_identifier'}:
 import boto3
 original_client=boto3.Session.client
 def client(self,*args,**kwargs):
  value=original_client(self,*args,**kwargs)
  def tamper(request,**kwargs):
   if scenario=='bad_url':request.url='https://unapproved.invalid/'
   elif scenario=='bad_method':request.method='PUT'
   elif scenario=='mutation_target':request.headers['X-Amz-Target']=b'AmazonSSM.PutParameter'
   elif scenario=='duplicate_identifier':request.body=b'{"Name":"unapproved","Name":"/powerflow/production/ENTSOE_API_KEY","WithDecryption":true}'
   else:request.body=b'{"Name":"unapproved","WithDecryption":true}'
  value.meta.events.register('before-send.'+backend+'.'+s.OPERATIONS[backend],tamper)
  return value
 boto3.Session.client=client
p={'__name__':'retained_provider'};exec(compile((root/'src/powerflow_secrets.py').read_text().replace('import boto3\n',''),'<provider>','exec'),p)
try:
 value=s.obtain(p,{'POWERFLOW_SECRETS_BACKEND':backend,'ENTSOE_API_KEY':'must-not-fallback'},files)
 assert value=='fixture-entsoe' and len(calls)==4
 assert calls[:3]==[('169.254.169.254','PUT','/latest/api/token'),('169.254.169.254','GET','/latest/meta-data/iam/security-credentials/'),('169.254.169.254','GET','/latest/meta-data/iam/security-credentials/fixture-role')]
 outcome='PASS'
except s.Blocked as error:outcome=str(error)
assert 'awscrt' not in sys.modules and 'certifi' not in sys.modules
assert all(name in files for name in loader.loaded)
print(json.dumps({'outcome':outcome,'loaded':len(loader.loaded),'mock_http_calls':len(calls),'real_network_calls':0}))
'''


@pytest.mark.parametrize('backend,scenario,expected', [
    ('ssm', 'success', 'PASS'), ('secretsmanager', 'success', 'PASS'),
    ('secretsmanager', 'binary', 'PASS'), ('ssm', 'denied', 'AWS_ACCESS_DENIED'),
    ('secretsmanager', 'denied', 'AWS_ACCESS_DENIED'), ('ssm', 'missing', 'AWS_EMPTY_SECRET'),
    ('ssm', 'body_bound', 'AWS_RESPONSE_BOUND'), ('ssm', 'header_bound', 'AWS_RESPONSE_BOUND'),
    ('ssm', 'imds_v1', 'AWS_ROLE_UNVERIFIED'),
    ('ssm', 'server_error', 'AWS_ACCESS_FAILED'), ('ssm', 'redirect', 'AWS_REQUEST_REJECTED'),
    ('ssm', 'bad_url', 'AWS_REQUEST_REJECTED'), ('ssm', 'bad_method', 'AWS_REQUEST_REJECTED'),
    ('ssm', 'mutation_target', 'AWS_REQUEST_REJECTED'), ('ssm', 'bad_identifier', 'AWS_REQUEST_REJECTED'),
    ('ssm', 'duplicate_identifier', 'AWS_REQUEST_REJECTED'),
])
def test_real_verified_sdk_with_mocked_imds_and_aws_transport(backend, scenario, expected):
    response = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', SMOKE, str(ROOT), backend, scenario],
                              capture_output=True, timeout=10, check=True)
    report = json.loads(response.stdout)
    assert report['outcome'] == expected and report['real_network_calls'] == 0
    assert report['loaded'] > 100
    assert b'PRIVATE' not in response.stdout and b'fixture-entsoe' not in response.stdout


def test_host_reuse_preserves_configuration_without_old_dispatch():
    source = r.host_source((OLD / 'inspect.py').read_bytes())
    assert b'if __name__' not in source and b"need(backend == 'env'" not in source
    space = {'__name__': 'host', 'PROVIDER': provider(),
             'PARSER': old.namespace((OLD / 'vendor/parser.py').read_bytes(), 'parser'),
             'VARIABLES': old.namespace((OLD / 'vendor/variables.py').read_bytes(), 'variables')}
    exec(compile(source, '<host>', 'exec'), space)
    for backend in ['ssm', 'secretsmanager']:
        env, _ = space['configured_environment'](('POWERFLOW_SECRETS_BACKEND=' + backend).encode(), {}, {})
        assert env['POWERFLOW_SECRETS_BACKEND'] == backend
    # All old side-effecting dispatch is absent; only selected read-only helpers.
    assert 'inspect' not in space and 'main' not in space


def test_capture_keeps_scalar_owners_exact_and_only_allows_fixed_sdk_pair(tmp_path):
    h = inspector()['H']
    path = tmp_path / 'sdk.py'
    path.write_bytes(b'# fixture')
    path.chmod(0o600)
    assert h['capture'](path, os.getuid(), 100)[0] == b'# fixture'
    with pytest.raises(h['Stop'], match='READ_METADATA'):
        h['capture'](path, (os.getuid(),), 100)
    if os.getuid() not in {0, 1000}:
        with pytest.raises(h['Stop'], match='READ_METADATA'):
            h['capture'](path, (0, 1000), 100)
    outside = tmp_path / 'link'
    outside.symlink_to(path)
    with pytest.raises(OSError):
        h['capture'](outside, os.getuid(), 100)


def fake_flow(monkeypatch):
    i = inspector()
    h = i['H']
    phases = []
    snapshot = b'timestamp,load_mw\n2026-11-03T15:00:00Z,12345\n'
    def capture(path, owner, limit, **kwargs):
        raw = b'POWERFLOW_SECRETS_BACKEND=ssm' if path.name == '.env' else snapshot if path.name == 'load.csv' else b'code'
        return raw, (1, 2, 3, 4, 5)
    h.update({'capture': capture, 'worker': lambda: '123', 'worker_environment': lambda _: {},
              'deployment_environment': lambda: {}, 'drop_identity': lambda: phases.append('dropped'),
              'WORKER_SHA': hashlib.sha256(b'code').hexdigest()})
    i.update({'SOURCE_HASHES': {}, 'root_runtime': lambda: phases.append('runtime-hashed'),
              'sdk_files': lambda: phases.append('sdk-hashed') or {},
              'resource': types.SimpleNamespace(setrlimit=lambda *args: None, RLIMIT_CORE=4)})
    def get_secret(env, held):
        assert phases == ['runtime-hashed', 'sdk-hashed', 'dropped']
        phases.append('aws-lookup')
        i['ROLE'] = True
        return 'fixture-entsoe'
    i['get_aws_secret'] = get_secret
    source = b'<Acknowledgement_MarketDocument><Reason><code>999</code><text>No matching data found</text></Reason></Acknowledgement_MarketDocument>'
    def request(callback):
        assert phases[-1] == 'aws-lookup' and callback('ENTSOE_API_KEY') == 'fixture-entsoe'
        phases.append('source-request')
        return source, None
    i['CORE']['request_source'] = request
    return i, phases


def test_full_mocked_order_and_no_secret_report(monkeypatch):
    i, phases = fake_flow(monkeypatch)
    report = i['inspect']()
    assert report['credential_backend'] == 'ssm' and report['iam_role_verified'] is True
    assert report['source_request'] == 'COMPLETED' and phases.count('source-request') == 1
    assert r.validate_report(report, old.validate_report)['status'] == 'PASS'
    assert 'fixture-entsoe' not in json.dumps(report) and '12345' not in json.dumps(report)


def test_sdk_failure_prevents_source_request(monkeypatch):
    i, phases = fake_flow(monkeypatch)
    def failure(env, held): raise sdk.Blocked('SDK_DEPENDENCY_MISMATCH')
    i['get_aws_secret'] = failure
    with pytest.raises(sdk.Blocked): i['inspect']()
    assert 'source-request' not in phases and i['REQUEST'] == 'NOT_ATTEMPTED'


def test_runtime_mismatch_before_privilege_drop_or_lookup(monkeypatch):
    i, phases = fake_flow(monkeypatch)
    def failure(): raise sdk.Blocked('SDK_RUNTIME_MISMATCH')
    i['root_runtime'] = failure
    with pytest.raises(sdk.Blocked, match='SDK_RUNTIME_MISMATCH'): i['inspect']()
    assert not phases


def test_parent_secret_child_protocol_rejects_unexpected_output():
    i = inspector()
    fake_stat = types.SimpleNamespace(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4,
                                     st_ctime_ns=5, st_uid=0, st_mode=stat.S_IFREG | 0o755)
    class Runtime:
        def lstat(self): return fake_stat
    i.update({'RUNTIME': Runtime(), 'RUNTIME_IDENTITY': (1, 2, 3, 4, 5),
              'child_run': lambda *args: (0, b'PRIVATE_SECRET unstructured')})
    with pytest.raises(sdk.Blocked, match='SDK_UNEXPECTED_OUTPUT'):
        i['get_aws_secret']({'POWERFLOW_SECRETS_BACKEND': 'ssm'}, {})


def test_private_child_envelope_omits_unused_tokens():
    i = inspector()
    fake_stat = types.SimpleNamespace(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4,
                                     st_ctime_ns=5, st_uid=0, st_mode=stat.S_IFREG | 0o755)
    class Runtime:
        def lstat(self): return fake_stat
    def child(script, envelope):
        body = json.loads(envelope)
        assert body['environment'] == {'POWERFLOW_SECRETS_BACKEND': 'ssm'}
        assert b'must-not-fallback' not in envelope
        return 0, b'{"ok":true,"secret":"fixture-entsoe"}'
    i.update({'RUNTIME': Runtime(), 'RUNTIME_IDENTITY': (1, 2, 3, 4, 5), 'child_run': child})
    assert i['get_aws_secret']({'POWERFLOW_SECRETS_BACKEND': 'ssm', 'ENTSOE_API_KEY': 'must-not-fallback'}, {}) == 'fixture-entsoe'


def test_unbound_module_and_native_extension_rejected():
    loader = sdk.MemorySDK({'six.py': b''})
    with pytest.raises(ModuleNotFoundError): loader.find_spec('boto3')
    for name in ['awscrt', 'certifi', 'OpenSSL', 'unexpected_package']:
        with pytest.raises(ModuleNotFoundError): loader.find_spec(name)


def test_child_dependency_hash_mismatch_prevents_import(monkeypatch, capsys):
    import base64
    import io
    expected = {'boto3/__init__.py': {'bytes': 3, 'sha256': hashlib.sha256(b'abc').hexdigest()}}
    envelope = json.dumps({'files': {'boto3/__init__.py': base64.b64encode(b'xyz').decode()}, 'environment': {}}).encode()
    monkeypatch.setattr(sdk, 'SDK_FILES', expected, raising=False)
    monkeypatch.setattr(sdk, 'os', types.SimpleNamespace(getresuid=lambda: (1000, 1000, 1000), getresgid=lambda: (1000, 1000, 1000), getgroups=lambda: []))
    monkeypatch.setattr(sdk, 'sys', types.SimpleNamespace(version_info=(3, 14), stdin=types.SimpleNamespace(buffer=io.BytesIO(envelope))))
    monkeypatch.setattr(sdk, 'resource', types.SimpleNamespace(setrlimit=lambda *a: None, RLIMIT_CORE=4))
    monkeypatch.setattr(sdk, 'logging', types.SimpleNamespace(disable=lambda *a: None, CRITICAL=50))
    monkeypatch.setattr(sdk, 'open', lambda *a: io.BytesIO(b'CapEff:\t0\nCapPrm:\t0\nCapAmb:\t0\n'), raising=False)
    monkeypatch.setattr(sdk.MemorySDK, 'install', lambda *a: pytest.fail('changed SDK imported'))
    assert sdk.main() == 1
    assert json.loads(capsys.readouterr().out) == {'ok': False, 'cause': 'SDK_DEPENDENCY_MISMATCH'}


def test_missing_runtime_and_sdk_have_specific_sanitized_causes():
    i = inspector()
    def missing(): raise FileNotFoundError('/PRIVATE_RUNTIME_OR_SDK')
    i['_root_runtime'] = missing
    i['_sdk_files'] = missing
    with pytest.raises(sdk.Blocked, match='SDK_RUNTIME_MISMATCH'):
        i['root_runtime']()
    with pytest.raises(sdk.Blocked, match='SDK_DEPENDENCY_MISMATCH'):
        i['sdk_files']()


@pytest.mark.parametrize('identity,version,cause', [
    ((0, 0, 0), (3, 14), 'SDK_IDENTITY_REJECTED'),
    ((1000, 1000, 1000), (3, 9), 'SDK_RUNTIME_MISMATCH'),
])
def test_sdk_child_identity_and_runtime_gate_before_import(monkeypatch, capsys, identity, version, cause):
    monkeypatch.setattr(sdk, 'os', types.SimpleNamespace(getresuid=lambda: identity, getresgid=lambda: identity, getgroups=lambda: []))
    monkeypatch.setattr(sdk, 'sys', types.SimpleNamespace(version_info=version))
    monkeypatch.setattr(sdk, 'resource', types.SimpleNamespace(setrlimit=lambda *a: None, RLIMIT_CORE=4))
    monkeypatch.setattr(sdk, 'logging', types.SimpleNamespace(disable=lambda *a: None, CRITICAL=50))
    monkeypatch.setattr(sdk.MemorySDK, 'install', lambda *a: pytest.fail('SDK imported before identity/runtime gate'))
    assert sdk.main() == 1
    assert json.loads(capsys.readouterr().out) == {'ok': False, 'cause': cause}


def test_sdk_child_capabilities_gate_before_lookup(monkeypatch, capsys):
    monkeypatch.setattr(sdk, 'os', types.SimpleNamespace(getresuid=lambda: (1000, 1000, 1000), getresgid=lambda: (1000, 1000, 1000), getgroups=lambda: []))
    monkeypatch.setattr(sdk, 'sys', types.SimpleNamespace(version_info=(3, 14)))
    monkeypatch.setattr(sdk, 'resource', types.SimpleNamespace(setrlimit=lambda *a: None, RLIMIT_CORE=4))
    monkeypatch.setattr(sdk, 'logging', types.SimpleNamespace(disable=lambda *a: None, CRITICAL=50))
    monkeypatch.setattr(sdk, 'open', lambda *a: __import__('io').BytesIO(b'CapEff:\t1\nCapPrm:\t1\nCapAmb:\t0\n'), raising=False)
    assert sdk.main() == 1
    assert json.loads(capsys.readouterr().out)['cause'] == 'SDK_IDENTITY_REJECTED'


@pytest.mark.parametrize('scenario', ['success', 'timeout', 'output_bound'])
def test_sdk_child_supervisor_with_only_local_synthetic_process(scenario):
    i = inspector()
    calls = []
    code = ('import sys;sys.stderr.write("PRIVATE_DIAGNOSTIC");print(\'{"ok":false,"cause":"AWS_ACCESS_FAILED"}\')'
            if scenario == 'success' else 'import time;time.sleep(5)' if scenario == 'timeout'
            else 'import sys;sys.stdout.write("x"*70000);sys.stdout.flush()')
    def popen(argv, **kwargs):
        calls.append(argv)
        assert argv[:5] == ['/usr/bin/python3.14', '-I', '-S', '-B', '-c']
        assert kwargs['start_new_session'] is False and kwargs['cwd'] == '/'
        assert kwargs['env']['AWS_CONFIG_FILE'] == kwargs['env']['AWS_SHARED_CREDENTIALS_FILE'] == '/dev/null'
        assert not any(key in kwargs['env'] for key in ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'ENTSOE_API_KEY'])
        return subprocess.Popen([sys.executable, '-I', '-S', '-B', '-c', code], **kwargs)
    i['subprocess'] = types.SimpleNamespace(Popen=popen, TimeoutExpired=subprocess.TimeoutExpired, PIPE=subprocess.PIPE)
    if scenario == 'timeout':
        i['time'] = types.SimpleNamespace(monotonic=iter([0, 21]).__next__)
    if scenario == 'success':
        status, out = i['child_run'](b'# verified fixed source', b'{}')
        assert status == 0 and b'PRIVATE_DIAGNOSTIC' not in out
    else:
        with pytest.raises(sdk.Blocked, match='SDK_PROCESS_TIMEOUT' if scenario == 'timeout' else 'SDK_OUTPUT_BOUND'):
            i['child_run'](b'# verified fixed source', b'{}')
    assert len(calls) == 1


def test_runtime_identity_change_blocks_child():
    i = inspector()
    fake_stat = types.SimpleNamespace(st_dev=1, st_ino=99, st_size=3, st_mtime_ns=4,
                                     st_ctime_ns=5, st_uid=0, st_mode=stat.S_IFREG | 0o755)
    class Runtime:
        def lstat(self): return fake_stat
    i.update({'RUNTIME': Runtime(), 'RUNTIME_IDENTITY': (1, 2, 3, 4, 5),
              'child_run': lambda *args: pytest.fail('changed runtime executed')})
    with pytest.raises(sdk.Blocked, match='SDK_RUNTIME_MISMATCH'):
        i['get_aws_secret']({'POWERFLOW_SECRETS_BACKEND': 'ssm'}, {})


def test_sdk_process_launch_failure_is_sanitized_without_retry():
    i = inspector()
    calls = []
    def failure(*args, **kwargs):
        calls.append(True)
        raise OSError('PRIVATE_RUNTIME_DETAILS')
    i['subprocess'] = types.SimpleNamespace(Popen=failure, PIPE=subprocess.PIPE)
    with pytest.raises(sdk.Blocked, match='SDK_PROCESS_FAILURE'):
        i['child_run'](b'# fixed verified code', b'{}')
    assert calls == [True]


def test_metadata_and_sdk_byte_inventory_are_exact():
    import importlib.metadata
    lock = json.loads((HERE / 'SDK-LOCK.json').read_bytes())
    site = importlib.metadata.distribution('boto3').locate_file('')
    assert len(lock['files']) == 215
    for name, record in lock['files'].items():
        raw = (site / name).read_bytes()
        assert record == {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


@pytest.mark.parametrize('value', [
    {'status': 'BLOCKED', 'phase': 'AUTHENTICATION', 'cause': 'PRIVATE_SECRET', 'credential_backend': 'ssm', 'iam_role_verified': False, 'source_request': 'NOT_ATTEMPTED', 'comparison': None},
    {'status': 'BLOCKED', 'phase': 'AUTHENTICATION', 'cause': 'AWS_ACCESS_DENIED', 'credential_backend': 'PRIVATE_ARN', 'iam_role_verified': False, 'source_request': 'NOT_ATTEMPTED', 'comparison': None},
])
def test_report_rejects_freeform_secrets(value):
    with pytest.raises(ValueError): r.validate_report(value, old.validate_report)


def test_new_manifest_complete_old_package_preserved():
    m = json.loads((HERE / 'MANIFEST.json').read_bytes())
    original = r.original_manifest((ROOT / r.ORIGINAL).read_bytes())
    assert set(m['artifacts']) == set(original['artifacts']) | r.NEW_FILES | {r.ORIGINAL}
    blobs = {}
    for name, item in m['artifacts'].items():
        blobs[name] = (ROOT / name).read_bytes()
        assert item == {'bytes': len(blobs[name]), 'sha256': r.sha(blobs[name])}
    assert r.sha(r.assemble(blobs)) == m['payload_sha256']
    assert all(m['artifacts'][name] == item for name, item in original['artifacts'].items())


@pytest.mark.parametrize('mutation', ['hash', 'size', 'dependency', 'payload'])
def test_package_mismatch_before_ssh_or_profile(monkeypatch, mutation):
    m = json.loads((HERE / 'MANIFEST.json').read_bytes())
    name = next(iter(m['artifacts']))
    if mutation == 'hash': m['artifacts'][name]['sha256'] = '0' * 64
    elif mutation == 'size': m['artifacts'][name]['bytes'] += 1
    elif mutation == 'dependency': m['artifacts']['unexpected.py'] = m['artifacts'][name]
    else: m['payload_sha256'] = '0' * 64
    modified = json.dumps(m).encode()
    read = r.read
    monkeypatch.setattr(r, 'read', lambda path: modified if path == HERE / 'MANIFEST.json' else read(path))
    # Assembly may execute a verified local builder namespace; no profile or SSH.
    namespace = r.namespace
    def load_namespace(raw, name, file=None):
        assert name != 'verified_ssh_wrapper'
        return namespace(raw, name, file)
    monkeypatch.setattr(r, 'namespace', load_namespace)
    with pytest.raises(ValueError): r.verify(r.sha(modified))


def test_verified_payload_and_validator_survive_path_substitution(monkeypatch):
    original_namespace = r.namespace
    def namespace(raw, name, file=None):
        value = original_namespace(raw, name, file)
        if name == 'verified_ssh_wrapper': value['profile'] = lambda: {}
        return value
    monkeypatch.setattr(r, 'namespace', namespace)
    raw = (HERE / 'MANIFEST.json').read_bytes()
    payload, wrapper, supervisor, validator = r.verify(r.sha(raw))
    monkeypatch.setattr(r, 'read', lambda *args: pytest.fail('reopened executable after verification'))
    report = {'status': 'BLOCKED', 'phase': 'SDK_VERIFICATION', 'cause': 'SDK_DEPENDENCY_MISMATCH',
              'credential_backend': 'ssm', 'iam_role_verified': False,
              'source_request': 'NOT_ATTEMPTED', 'comparison': None}
    assert validator(report) == report and callable(supervisor)
    assert type(payload) is bytes and payload


def test_python39_parent_and_sdk_source_grammar():
    for name in ['sdk.py', 'inspect.py', 'run.py', 'build.py', 'lock_sdk.py']:
        ast.parse((HERE / name).read_text(), feature_version=(3, 9))
    text = (HERE / 'inspect.py').read_text()
    assert 'start_new_session=False' in text  # SDK cannot escape outer timeout group.
    assert not any(token in text for token in ['.mkdir(', '.write_text(', '.write_bytes(', '.unlink(', '.chmod(', '.chown('])
    assert r.REMOTE == old.REMOTE and r.LIMITS['attempts'] == 1
