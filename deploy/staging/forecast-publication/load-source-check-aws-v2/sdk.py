"""Verified in-memory SDK loader and fixed read-only IAM-role secret adapter.

Loaded only after the permanent production UID/GID drop. No production imports,
site hooks, SDK native extensions, plaintext logging or credential fallback.
"""
import base64
import gzip
import hashlib
import importlib.abc
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import re
import resource
import ssl
import sys
import types
import urllib.parse

REGION = 'us-east-1'
SERVICES = {'ssm': '2014-11-06', 'secretsmanager': '2017-10-17'}
OPERATIONS = {'ssm': 'GetParameter', 'secretsmanager': 'GetSecretValue'}
BODY_LIMIT = 131072
CAUSES = {'AWS_CONFIGURATION_REJECTED', 'AWS_ROLE_UNVERIFIED', 'AWS_ACCESS_FAILED',
          'AWS_ACCESS_DENIED', 'AWS_SECRET_NOT_FOUND', 'AWS_DECRYPTION_FAILED',
          'AWS_REQUEST_REJECTED', 'AWS_RESPONSE_BOUND', 'AWS_EMPTY_SECRET',
          'SDK_RUNTIME_MISMATCH', 'SDK_IMPORT_REJECTED', 'SDK_IDENTITY_REJECTED',
          'SDK_DEPENDENCY_MISMATCH', 'SDK_MODEL_REJECTED', 'SDK_TLS_REJECTED'}


class Blocked(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise Blocked(code)


class MemorySDK(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Only held manifest-bound .py bytes can satisfy third-party imports."""
    ROOTS = {'boto3', 'botocore', 's3transfer', 'jmespath', 'dateutil', 'urllib3', 'six'}
    DENIED = {'awscrt', 'certifi', 'OpenSSL', 'brotli', 'brotlicffi', 'zstandard', 'chardet', 'charset_normalizer'}

    def __init__(self, files):
        self.files = files
        self.loaded = set()

    def path(self, name):
        stem = name.replace('.', '/')
        return stem + '/__init__.py' if stem + '/__init__.py' in self.files else stem + '.py'

    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split('.')[0]
        if root in self.DENIED:
            raise ModuleNotFoundError('optional_sdk_extension_disabled', name=fullname)
        if root not in self.ROOTS:
            if root in getattr(sys, 'stdlib_module_names', set()) or root.startswith('_sysconfigdata_'):
                return None  # Trusted OS stdlib only; interpreter runs -I -S.
            raise ModuleNotFoundError('nonstdlib_dependency_not_bound', name=fullname)
        if fullname.startswith('six.moves') and 'six.py' in self.loaded:
            # Virtual aliases are created by the verified six module's own
            # importer; they are not source files or disk import fallbacks.
            return None
        name = self.path(fullname)
        if name not in self.files:
            raise ModuleNotFoundError('sdk_module_not_bound', name=fullname)
        return importlib.util.spec_from_loader(fullname, self, is_package=name.endswith('/__init__.py'))

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path = self.path(module.__name__)
        module.__file__ = '/verified-sdk/' + path
        if path.endswith('/__init__.py'):
            module.__path__ = [module.__file__.rsplit('/', 1)[0]]
        self.loaded.add(path)
        exec(compile(self.files[path], module.__file__, 'exec'), module.__dict__)

    def install(self):
        need(not any(name.split('.')[0] in self.ROOTS | self.DENIED for name in sys.modules), 'SDK_IMPORT_REJECTED')
        sys.meta_path.insert(0, self)


def memory_models(files):
    # Import happens through MemorySDK. No installed data-loader path is opened.
    from botocore.loaders import Loader
    from botocore.exceptions import DataNotFoundError

    class Models(Loader):
        def __init__(self):
            super().__init__(extra_search_paths=[], include_default_search_paths=False)

        def load_data_with_path(self, name):
            need(type(name) is str and '..' not in name and not name.startswith('/'), 'SDK_MODEL_REJECTED')
            stem = 'botocore/data/' + name + '.json'
            raw = files.get(stem)
            if raw is None and stem + '.gz' in files:
                with gzip.GzipFile(fileobj=io.BytesIO(files[stem + '.gz'])) as stream:
                    raw = stream.read(8_000_001)
                    need(len(raw) <= 8_000_000, 'SDK_MODEL_REJECTED')
            if raw is None:
                raise DataNotFoundError(data_path='bound_model_missing')
            return json.loads(raw), '/verified-sdk/' + stem

        def list_available_services(self, type_name):
            return [name for name, version in SERVICES.items()
                    if any('botocore/data/' + name + '/' + version + '/' + type_name + suffix in files for suffix in ('.json', '.json.gz'))]

        def list_api_versions(self, service_name, type_name):
            if service_name not in self.list_available_services(type_name):
                raise DataNotFoundError(data_path='bound_model_missing')
            return [SERVICES[service_name]]

        def is_builtin_path(self, path):
            return path.startswith('/verified-sdk/botocore/data/')

    return Models()


def _selection(provider, env):
    backend = provider['secrets_backend'](env)
    need(backend in SERVICES, 'AWS_CONFIGURATION_REJECTED')
    provider['_reject_static_aws_credentials'](env, 'ENTSOE_API_KEY')
    region = provider['_aws_region'](env)
    need(region == REGION, 'AWS_CONFIGURATION_REJECTED')
    identifier = provider['_secret_identifier']('ENTSOE_API_KEY', backend, env)
    # Use the configured identifier only. No CLI identifier or default-backend
    # substitution. Do not report it, even in hashes or exception text.
    need(type(identifier) is str and 0 < len(identifier) <= 2048, 'AWS_CONFIGURATION_REJECTED')
    if identifier.startswith('arn:'):
        pattern = (r'arn:aws:' + backend + ':' + REGION + r':[0-9]{12}:' +
                   (r'parameter/[A-Za-z0-9_./-]+' if backend == 'ssm' else r'secret:[A-Za-z0-9_./+=@-]+'))
    else:
        pattern = r'[A-Za-z0-9_./-]+' if backend == 'ssm' else r'[A-Za-z0-9_./+=@-]+'
    if backend == 'ssm':
        pattern += r'(?::[A-Za-z0-9_.-]{1,100})?'  # Existing GetParameter label/version semantics.
    # These are opaque AWS resource identifiers used only as JSON values, not
    # filesystem paths. Preserve valid dotted names and configured selectors.
    need(re.fullmatch(pattern, identifier) is not None, 'AWS_CONFIGURATION_REJECTED')
    # Ignore profile/files/process/container providers entirely: production
    # accepts only iam-role credentials. Reject configured alternate routes.
    forbidden = {'AWS_PROFILE', 'AWS_DEFAULT_PROFILE', 'AWS_CONFIG_FILE', 'AWS_SHARED_CREDENTIALS_FILE',
        'AWS_WEB_IDENTITY_TOKEN_FILE', 'AWS_ROLE_ARN', 'AWS_ROLE_SESSION_NAME',
        'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI', 'AWS_CONTAINER_CREDENTIALS_FULL_URI',
        'AWS_CONTAINER_AUTHORIZATION_TOKEN', 'AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE',
        'AWS_EC2_METADATA_SERVICE_ENDPOINT', 'AWS_EC2_METADATA_SERVICE_ENDPOINT_MODE',
        'AWS_ENDPOINT_URL', 'AWS_ENDPOINT_URL_SSM', 'AWS_ENDPOINT_URL_SECRETS_MANAGER',
        'AWS_CA_BUNDLE', 'AWS_SECURITY_TOKEN'}
    need(not any(str(env.get(k, '')).strip() for k in forbidden), 'AWS_CONFIGURATION_REJECTED')
    need(str(env.get('AWS_EC2_METADATA_DISABLED', 'false')).lower() == 'false', 'AWS_CONFIGURATION_REJECTED')
    return backend, region, identifier


def selection(provider, env):
    try:
        return _selection(provider, env)
    except provider['SecretConfigurationError']:
        raise Blocked('AWS_CONFIGURATION_REJECTED') from None


def os_ca():
    path = ssl.get_default_verify_paths().cafile
    need(path is not None, 'SDK_TLS_REJECTED')
    # OS trust store and ancestors must be root controlled. Only this data file,
    # never code or a configured AWS_CA_BUNDLE, is used by the SDK's HTTPS stack.
    target = Path(path).resolve(strict=True)
    for item in (target,) + tuple(target.parents):
        stat = item.stat()
        need(stat.st_uid == 0 and not stat.st_mode & 0o022, 'SDK_TLS_REJECTED')
    need(target.is_file(), 'SDK_TLS_REJECTED')
    return str(target)


def install_transport_guard(backend, identifier, state):
    import botocore.httpsession
    import botocore.awsrequest
    import urllib3.connectionpool
    original_send = botocore.httpsession.URLLib3Session.send
    original_urlopen = urllib3.connectionpool.HTTPConnectionPool.urlopen
    endpoint = 'https://' + backend + '.' + REGION + '.amazonaws.com/'
    aws_sent = [False]
    metadata_counts = {'token': 0, 'role': 0, 'credentials': 0}

    def no_redirect(pool, method, url, *args, **kwargs):
        kwargs['redirect'] = False
        return original_urlopen(pool, method, url, *args, **kwargs)

    urllib3.connectionpool.HTTPConnectionPool.urlopen = no_redirect

    class BoundedResponse(botocore.awsrequest.AWSResponse):
        @property
        def content(self):
            try:
                if self._content is None:
                    length = self.headers.get('content-length')
                    if length is not None:
                        need(str(length).isdecimal() and int(length) <= BODY_LIMIT, 'AWS_RESPONSE_BOUND')
                    parts, total = [], 0
                    for chunk in self.raw.stream(amt=4096, decode_content=False):
                        total += len(chunk)
                        need(total <= BODY_LIMIT, 'AWS_RESPONSE_BOUND')
                        parts.append(chunk)
                    self._content = b''.join(parts)
                return self._content
            except Blocked:
                state['failure'] = 'AWS_RESPONSE_BOUND'
                raise

    # The verified SDK constructs AWSResponse inside send(), so enforce its body
    # bound before SDK JSON parsing (not after it has buffered an unlimited body).
    botocore.awsrequest.AWSResponse = BoundedResponse

    def send(session, request):
        try:
            need(not session._proxy_config._proxies, 'AWS_REQUEST_REJECTED')
            if request.url == endpoint:
                need(request.method == 'POST' and not aws_sent[0], 'AWS_REQUEST_REJECTED')
                expected = {'Name': identifier, 'WithDecryption': True} if backend == 'ssm' else {'SecretId': identifier}
                body = request.body
                def unique(pairs):
                    value = {}
                    for key, item in pairs:
                        need(key not in value, 'AWS_REQUEST_REJECTED')
                        value[key] = item
                    return value
                need(isinstance(body, (str, bytes)) and len(body) <= 8192
                     and json.loads(body, object_pairs_hook=unique) == expected, 'AWS_REQUEST_REJECTED')
                target = request.headers.get('X-Amz-Target')
                if isinstance(target, bytes):
                    target = target.decode('ascii')
                wanted = 'AmazonSSM.GetParameter' if backend == 'ssm' else 'secretsmanager.GetSecretValue'
                need(target == wanted and session._verify and not session._proxy_config._proxies, 'AWS_REQUEST_REJECTED')
                aws_sent[0] = True
            else:
                parsed = urllib.parse.urlsplit(request.url)
                need(parsed.scheme == 'http' and parsed.netloc == '169.254.169.254'
                     and not parsed.query and not parsed.fragment, 'AWS_REQUEST_REJECTED')
                if parsed.path == '/latest/api/token':
                    kind = 'token'
                    need(request.method == 'PUT', 'AWS_REQUEST_REJECTED')
                elif parsed.path == '/latest/meta-data/iam/security-credentials/':
                    kind = 'role'
                    need(request.method == 'GET' and request.headers.get('x-aws-ec2-metadata-token'), 'AWS_REQUEST_REJECTED')
                else:
                    kind = 'credentials'
                    need(request.method == 'GET' and re.fullmatch(r'/latest/meta-data/iam/security-credentials/[A-Za-z0-9+=,.@_-]{1,128}', parsed.path)
                         and request.headers.get('x-aws-ec2-metadata-token'), 'AWS_REQUEST_REJECTED')
                metadata_counts[kind] += 1
                need(metadata_counts[kind] <= 1, 'AWS_REQUEST_REJECTED')
            response = original_send(session, request)
            need(response.status_code not in {301, 302, 303, 307, 308}, 'AWS_REQUEST_REJECTED')
            return response
        except Blocked as error:
            state['failure'] = str(error)
            raise

    botocore.httpsession.URLLib3Session.send = send


def sdk_facade(files, backend, region, identifier, state):
    import boto3
    import botocore.config
    import botocore.credentials
    import botocore.utils
    import botocore.exceptions
    need(boto3.__version__ == '1.43.98', 'SDK_DEPENDENCY_MISMATCH')
    ca = os_ca()
    install_transport_guard(backend, identifier, state)

    class Client:
        def __init__(self, client):
            self.client = client
            self.called = False

        def invoke(self, method, kwargs):
            need(not self.called and method == OPERATIONS[backend], 'AWS_REQUEST_REJECTED')
            expected = {'Name': identifier, 'WithDecryption': True} if backend == 'ssm' else {'SecretId': identifier}
            need(kwargs == expected, 'AWS_REQUEST_REJECTED')
            self.called = True
            try:
                function = self.client.get_parameter if backend == 'ssm' else self.client.get_secret_value
                response = function(**kwargs)
                value = response.get('Parameter', {}).get('Value') if backend == 'ssm' else response.get('SecretString')
                if backend == 'secretsmanager' and value is None:
                    value = response.get('SecretBinary')
                if value is None or not value or isinstance(value, str) and not value.strip():
                    state['failure'] = 'AWS_EMPTY_SECRET'
                return response
            except botocore.exceptions.ClientError as error:
                code = error.response.get('Error', {}).get('Code')
                state['failure'] = {'AccessDeniedException': 'AWS_ACCESS_DENIED',
                    'AccessDenied': 'AWS_ACCESS_DENIED', 'ParameterNotFound': 'AWS_SECRET_NOT_FOUND',
                    'ResourceNotFoundException': 'AWS_SECRET_NOT_FOUND', 'DecryptionFailure': 'AWS_DECRYPTION_FAILED'}.get(code, 'AWS_ACCESS_FAILED')
                raise

        def get_parameter(self, **kwargs):
            return self.invoke('GetParameter', kwargs)

        def get_secret_value(self, **kwargs):
            return self.invoke('GetSecretValue', kwargs)

    class Session:
        def __init__(self, **kwargs):
            need(kwargs == {'region_name': region}, 'AWS_CONFIGURATION_REJECTED')
            self.value = boto3.Session(region_name=region)
            session = self.value._session
            session.register_component('data_loader', memory_models(files))
            # No shared credentials, credential_process, web identity, ECS,
            # environment or profile provider can run before iam-role rejection.
            fetcher = botocore.utils.InstanceMetadataFetcher(timeout=2, num_attempts=1,
                base_url='http://169.254.169.254/', env={'AWS_EC2_METADATA_DISABLED': 'false'},
                config={'ec2_metadata_v1_disabled': True})
            resolver = botocore.credentials.CredentialResolver([
                botocore.credentials.InstanceMetadataProvider(iam_role_fetcher=fetcher)])
            session.register_component('credential_provider', resolver)
            self.created = False

        def get_credentials(self):
            credentials = self.value.get_credentials()
            need(credentials is not None and getattr(credentials, 'method', None) == 'iam-role', 'AWS_ROLE_UNVERIFIED')
            state['iam_role'] = True
            return credentials

        def client(self, name):
            need(name == backend and not self.created and state.get('iam_role'), 'AWS_REQUEST_REJECTED')
            self.created = True
            config = botocore.config.Config(region_name=region, signature_version='v4',
                connect_timeout=3, read_timeout=5, retries={'total_max_attempts': 1, 'mode': 'standard'},
                proxies={}, use_fips_endpoint=False, use_dualstack_endpoint=False,
                ignore_configured_endpoint_urls=True)
            client = self.value.client(name, region_name=region,
                endpoint_url='https://' + backend + '.' + region + '.amazonaws.com', verify=ca, config=config)
            need(client.meta.endpoint_url == 'https://' + backend + '.' + region + '.amazonaws.com', 'AWS_REQUEST_REJECTED')
            return Client(client)

    return types.SimpleNamespace(Session=Session)


def obtain(provider, env, files, facade_factory=sdk_facade):
    state = {'iam_role': False, 'failure': None}
    backend, region, identifier = selection(provider, env)
    provider['boto3'] = facade_factory(files, backend, region, identifier, state)
    # Reuse the exact production implementation, without its optional lru_cache.
    # The one-shot diagnostic must never cache the retrieved ENTSO-E secret.
    provider['_load_aws_secret'] = getattr(provider['_load_aws_secret'], '__wrapped__', provider['_load_aws_secret'])
    try:
        value = provider['get_secret']('ENTSOE_API_KEY', environment=env)
        need(state['iam_role'], 'AWS_ROLE_UNVERIFIED')
        need(type(value) is str and 0 < len(value) <= 4096, 'AWS_EMPTY_SECRET')
        return value
    except Blocked:
        raise
    except Exception:
        raise Blocked(state['failure'] or ('AWS_ACCESS_FAILED' if state['iam_role'] else 'AWS_ROLE_UNVERIFIED')) from None


def main():
    # Only the trusted parent supplies this bounded in-memory envelope. Never
    # print tracebacks, identifiers, client errors or SDK debug logging.
    logging.disable(logging.CRITICAL)
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        need(os.getresuid() == os.getresgid() == (1000, 1000, 1000) and os.getgroups() == [], 'SDK_IDENTITY_REJECTED')
        need(sys.version_info[:2] == (3, 14), 'SDK_RUNTIME_MISMATCH')
        with open('/proc/self/status', 'rb') as stream:
            status = stream.read(65537)
        need(len(status) <= 65536, 'SDK_IDENTITY_REJECTED')
        fields = dict(line.split(':', 1) for line in status.decode().splitlines() if ':' in line)
        need(all(int(fields.get(name, '1').strip(), 16) == 0 for name in ('CapEff', 'CapPrm', 'CapAmb')), 'SDK_IDENTITY_REJECTED')
        raw = sys.stdin.buffer.read(8_000_001)
        need(len(raw) <= 8_000_000, 'SDK_DEPENDENCY_MISMATCH')
        envelope = json.loads(raw)
        need(set(envelope) == {'files', 'environment'}, 'SDK_DEPENDENCY_MISMATCH')
        files = {name: base64.b64decode(value, validate=True) for name, value in envelope['files'].items()}
        need(set(files) == set(SDK_FILES), 'SDK_DEPENDENCY_MISMATCH')
        for name, content in files.items():
            need(SDK_FILES[name] == {'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}, 'SDK_DEPENDENCY_MISMATCH')
        MemorySDK(files).install()
        value = obtain(PROVIDER, envelope['environment'], files)
        # This is an internal bounded pipe to the unprivileged parent, never
        # retained evidence/stdout of SSH. The parent validates then discards it.
        print(json.dumps({'ok': True, 'secret': value}, ensure_ascii=True))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, Blocked) and str(error) in CAUSES else 'AWS_ACCESS_FAILED'
        print(json.dumps({'ok': False, 'cause': code}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
