"""Offline activation safety checks. Never Nginx, systemd, SSH, TLS or live paths."""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('staging_https_activation', ROOT / 'deploy/staging/activate-staging-https.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


@pytest.fixture
def config(tmp_path, monkeypatch):
    root = tmp_path / 'nginx'; (root / 'conf.d').mkdir(parents=True)
    target = root / 'conf.d/staging-https.conf'
    http = root / 'conf.d/staging-http.conf'
    monkeypatch.setattr(m, 'TARGET', target); monkeypatch.setattr(m, 'HTTP_CONF', http)
    (root / 'nginx.conf').write_text('events {} http { include ' + str(root / 'conf.d/*.conf') + '; }')
    http.write_text('server { listen 80; server_name ' + m.HOST + '; }')
    (root / 'conf.d/production.conf').write_text('server { listen 443 ssl; server_name powerflowenergy.dev; }')
    return root, target, http


def test_review_requires_one_http_install_site_and_preserves_source_hashes(config):
    root, target, http = config
    hashes, summary = m.review_config(config_root=root)
    assert str(http) in hashes and str(target) not in hashes
    assert len(summary) == 2
    target.write_text('server { listen 443 ssl; server_name ' + m.HOST + '; }')
    with pytest.raises(RuntimeError, match='existing_staging_https_conflict'):
        m.review_config(config_root=root)
    after, _ = m.review_config(True, config_root=root)
    assert set(after) == set(hashes) | {str(target)}


@pytest.mark.parametrize('name', [m.HOST, m.HOST.upper(), '*.powerflowenergy.dev', '~.*'])
def test_conflicting_tls_names_stop(config, name):
    root, _, _ = config
    (root / 'conf.d/other.conf').write_text('server { listen 443 ssl; server_name ' + name + '; }')
    with pytest.raises(RuntimeError): m.review_config(config_root=root)


def test_unapproved_include_stops_before_install(config):
    root, target, _ = config
    (root / 'nginx.conf').write_text('include /outside/secret.conf;')
    with pytest.raises(RuntimeError, match='unapproved_include_pattern'):
        m.review_config(config_root=root)
    assert not target.exists()


def test_duplicate_http_include_site_is_rejected(config):
    root, _, _ = config
    (root / 'nginx.conf').write_text('http { include ' + str(root / 'conf.d/*.conf') + '; include ' + str(root / 'conf.d/*.conf') + '; }')
    with pytest.raises(RuntimeError, match='target_not_in_one_http_include_site'):
        m.review_config(config_root=root)


def test_quoted_semicolon_and_adjacent_braces_parse(config):
    root, _, _ = config
    (root / 'nginx.conf').write_text('events{} http{ log_format safe "a;b"; include ' + str(root / 'conf.d/*.conf') + ';}')
    hashes, _ = m.review_config(config_root=root)
    assert len(hashes) == 3


def test_nginx_warning_prevents_reload(monkeypatch):
    monkeypatch.setattr(m, 'command', lambda *a: (b'', b'nginx: [warn] conflicting server name'))
    with pytest.raises(RuntimeError, match='nginx_warning'): m.nginx_test('check')


def test_preflight_failure_does_not_install_or_reload(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(m.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(m, 'STATE', tmp_path / 'absent')
    monkeypatch.setattr(m, 'command', lambda *a, **kw: pytest.fail('no command after failed state guard'))
    previous = m.os.umask(0o077)
    try: assert m.main(['activate']) == 1
    finally: m.os.umask(previous)
    d = json.loads(capsys.readouterr().out)
    assert d['reload_invocations'] == 0 and d['error'] == 'state_directory_invalid'


def test_preview_binding_and_no_certbot_training_or_deployment():
    import ast
    issue = ast.parse((ROOT / 'deploy/staging/issue-staging-certificate.py').read_text())
    preview = next(n.value.value for n in issue.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'HTTPS_PREVIEW' for t in n.targets))
    assert hashlib.sha256(preview.encode()).hexdigest() == m.PREVIEW_SHA
    tree = ast.parse((ROOT / 'deploy/staging/activate-staging-https.py').read_text())
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert '/usr/bin/certbot' not in strings
    assert not {'restart', 'start', 'stop', 'enable', 'disable'} & set(strings)


@pytest.mark.parametrize('failure', ['validation', 'readiness', None])
def test_activation_never_reloads_twice_or_auto_rolls_back(tmp_path, monkeypatch, capsys, failure):
    state = tmp_path / 'state'; state.mkdir(mode=0o700)
    audit = state / 'activation'
    target = tmp_path / 'conf.d/staging.conf'; target.parent.mkdir()
    preview = state / 'preview.conf'; preview.write_bytes(b'approved-preview')
    monkeypatch.setattr(m, 'STATE', state); monkeypatch.setattr(m, 'AUDIT', audit)
    monkeypatch.setattr(m, 'TARGET', target); monkeypatch.setattr(m, 'PREVIEW', preview)
    monkeypatch.setattr(m, 'PREVIEW_SHA', m.digest(preview.read_bytes()))
    monkeypatch.setattr(m.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(m.os, 'access', lambda *a: True)
    original_stat = Path.stat
    def test_stat(path, *a, **kw):
        result = original_stat(path, *a, **kw)
        if path == state:
            values = list(result); values[4] = 0
            return m.os.stat_result(values)
        return result
    monkeypatch.setattr(Path, 'stat', test_stat)
    monkeypatch.setattr(m, 'preservation', lambda: None)
    monkeypatch.setattr(m, 'snapshot', lambda: b'stable')
    monkeypatch.setattr(m, 'certificate_checks', lambda: ('leaf', ['public certificate']))
    monkeypatch.setattr(m, 'review_config', lambda installed: (
        {str(target): m.PREVIEW_SHA} if installed else {}, []))
    labels = []
    def command(label, args, audit=None, **kwargs):
        labels.append(label)
        if label == 'active': return b'active\n' * len(m.UNITS), b''
        if label == 'installed_nginx' and failure == 'validation':
            raise RuntimeError('installed_nginx_exit_1')
        return b'', b''
    monkeypatch.setattr(m, 'command', command)
    monkeypatch.setattr(m.time, 'sleep', lambda *_: None)
    def request(path, tls, *args):
        if tls and path == '/':
            if failure == 'readiness': raise RuntimeError('tls_not_ready')
            return 404, b''
        return 200, m.PROBE_BODY
    monkeypatch.setattr(m, 'request', request)
    previous = m.os.umask(0o077)
    try: assert m.main(['activate']) == (0 if failure is None else 1)
    finally: m.os.umask(previous)
    report = json.loads(capsys.readouterr().out)
    assert labels.count('reload') == (0 if failure == 'validation' else 1)
    assert target.exists() # No automatic deletion/rollback on failure.
    assert not (audit / 'rollback').exists()
    assert report['production_preservation'] == 'passed'
    if failure == 'readiness': assert report['tls_readiness_requests'] == 10


@pytest.fixture
def options(config, monkeypatch):
    root, _, _ = config
    # Redirect ONLY fixture path operations; production exception remains exact.
    real = root.parent / 'options-fixture.conf'
    real.write_text('ssl_session_cache shared:le_nginx_SSL:10m;')
    resolve = Path.resolve
    monkeypatch.setattr(Path, 'resolve', lambda p, *a, **kw:
                        p if p == m.CERTBOT_OPTIONS else resolve(p, *a, **kw))
    monkeypatch.setattr(m, 'read_certbot_options', lambda: real.read_bytes())
    (root / 'conf.d/production.conf').write_text(
        'server { listen 443 ssl; server_name powerflowenergy.dev; include '
        + str(m.CERTBOT_OPTIONS) + '; }')
    return root, real


def test_exact_options_is_parsed_hashed_and_nested_include_reviewed(options):
    root, real = options
    hashes, _ = m.review_config(config_root=root)
    assert hashes[str(m.CERTBOT_OPTIONS)] == m.digest(real.read_bytes())
    real.write_text('include /etc/letsencrypt/another.conf;')
    with pytest.raises(RuntimeError, match='unapproved_include_pattern'):
        m.review_config(config_root=root)


@pytest.mark.parametrize('pattern', [
    '/etc/letsencrypt/*.conf', '/etc/letsencrypt/options-ssl-nginx.con?',
    '/etc/letsencrypt/./options-ssl-nginx.conf',
    '/etc//letsencrypt/options-ssl-nginx.conf',
    '/etc/letsencrypt/../letsencrypt/options-ssl-nginx.conf',
    'etc/letsencrypt/options-ssl-nginx.conf',
    '/etc/letsencrypt/other.conf',
])
def test_options_aliases_and_wildcards_rejected(config, pattern):
    root, _, _ = config
    (root / 'conf.d/production.conf').write_text('include ' + pattern + ';')
    with pytest.raises((RuntimeError, OSError)):
        m.review_config(config_root=root)


def test_options_directives_cannot_hide_staging_conflict(options):
    root, real = options
    real.write_text('server_name ' + m.HOST + ';')
    with pytest.raises(RuntimeError, match='existing_staging_https_conflict'):
        m.review_config(config_root=root)


@pytest.mark.parametrize('mode,uid', [(0o100644, 0), (0o100664, 0),
    (0o100666, 0), (0o100644, 1000), (0o040755, 0), (0o104644, 0)])
def test_options_descriptor_security(tmp_path, monkeypatch, mode, uid):
    from types import SimpleNamespace
    import os
    real = tmp_path / 'file'; real.write_bytes(b'ssl_prefer_server_ciphers on;')
    actual_open, actual_fstat = os.open, os.fstat
    descriptors = set()
    def fake_open(path, flags, **kwargs):
        assert flags & os.O_NOFOLLOW
        if path == '/': return actual_open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        if path == 'options-ssl-nginx.conf':
            fd = actual_open(real, os.O_RDONLY); descriptors.add(fd); return fd
        assert flags & os.O_DIRECTORY
        return actual_open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    def fake_stat(fd):
        info = actual_fstat(fd)
        return SimpleNamespace(st_mode=mode if fd in descriptors else 0o040755,
            st_uid=uid if fd in descriptors else 0, st_size=info.st_size,
            st_dev=info.st_dev, st_ino=info.st_ino,
            st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns)
    monkeypatch.setattr(m.os, 'open', fake_open)
    monkeypatch.setattr(m.os, 'fstat', fake_stat)
    if mode == 0o100644 and uid == 0:
        assert m.read_certbot_options() == real.read_bytes()
    else:
        with pytest.raises(RuntimeError, match='unsafe_certbot_options_file'):
            m.read_certbot_options()


def test_options_symlink_rejected_locally(tmp_path, monkeypatch):
    # Traverse actual fixture descriptors, with root-owner checks simulated locally.
    import os
    from types import SimpleNamespace
    target = tmp_path / 'target'; target.write_text('safe;')
    link = tmp_path / 'options-ssl-nginx.conf'; link.symlink_to(target)
    actual_open, actual_fstat = os.open, os.fstat
    def fake_open(path, flags, **kw):
        assert flags & os.O_NOFOLLOW
        if path == 'options-ssl-nginx.conf': return actual_open(link, flags)
        return actual_open(tmp_path, flags)
    def fake_stat(fd):
        info = actual_fstat(fd)
        return SimpleNamespace(st_mode=0o040755, st_uid=0)
    monkeypatch.setattr(m.os, 'open', fake_open)
    monkeypatch.setattr(m.os, 'fstat', fake_stat)
    with pytest.raises(OSError): m.read_certbot_options()


def test_symlink_from_allowed_root_cannot_reach_exception(config):
    root, _, _ = config
    (root / 'conf.d/alias.conf').symlink_to(m.CERTBOT_OPTIONS)
    with pytest.raises(RuntimeError, match='unapproved_include_root'):
        m.review_config(config_root=root)


@pytest.mark.parametrize('parent_mode,parent_uid', [(0o040777, 0), (0o040775, 0), (0o040755, 1000)])
def test_unsafe_options_parent_rejected(monkeypatch, parent_mode, parent_uid):
    from types import SimpleNamespace
    original_fstat = m.os.fstat
    monkeypatch.setattr(m.os, 'fstat', lambda fd:
                        SimpleNamespace(st_mode=parent_mode, st_uid=parent_uid))
    with pytest.raises(RuntimeError, match='unsafe_certbot_options_parent'):
        m.read_certbot_options()


def test_options_cannot_bypass_directive_limit(options):
    root, real = options
    real.write_text('ssl_prefer_server_ciphers on;' * 4097)
    with pytest.raises(RuntimeError, match='expanded_directive_limit'):
        m.review_config(config_root=root)
