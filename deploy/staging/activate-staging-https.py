#!/usr/bin/env python3
"""Approval required. Activate ONE staging placeholder vhost; rollback is separate approval."""
import argparse
import fnmatch
import glob
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shlex
import socket
import ssl
import stat
import subprocess
import time

HOST = 'staging.powerflowenergy.dev'
STATE = Path('/var/lib/powerflow-staging-https-20261026')
ISSUANCE = STATE / 'issuance-continuation-20261026'
PREVIEW = ISSUANCE / 'staging-https-preview.conf'
PREVIEW_SHA = '85ad4c7ec303b638033831cb7ebfd5b73b669c80b249926c8e1446ba70124396'
AUDIT = STATE / 'https-activation-20261026'
TARGET = Path('/etc/nginx/conf.d/powerflow-staging-https.conf')
HTTP_CONF = Path('/etc/nginx/conf.d/powerflow-staging-acme.conf')
LIVE = Path('/etc/letsencrypt-powerflow-staging/live/staging.powerflowenergy.dev')
CA = '/etc/pki/tls/certs/ca-bundle.crt'
PRODUCTION = ['/etc/nginx/conf.d/powerflow.conf',
              '/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem']
UNITS = ['nginx.service', 'powerflow-api.service', 'powerflow-streamlit.service',
         'powerflow-prefect-worker.service', 'powerflow-prefect-server.service',
         'postgresql.service']
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C',
       'HOME': '/root', 'PYTHONDONTWRITEBYTECODE': '1'}
PROBE_URL = '/.well-known/acme-challenge/preflight-probe'
PROBE_BODY = b'powerflow-staging-acme-preflight\n'
EXPIRY = 'Jan 24 07:38:12 2027 GMT'
CERTBOT_OPTIONS = Path('/etc/letsencrypt/options-ssl-nginx.conf')


def require(value, code):
    if not value: raise RuntimeError(code)


def read_regular(path, limit=65536):
    require(path.is_file() and not path.is_symlink(), 'regular_file_required')
    require(path.stat().st_size <= limit, 'file_size_limit')
    return path.read_bytes()


def digest(data): return hashlib.sha256(data).hexdigest()


def read_certbot_options():
    """Exact exception: descriptor-relative traversal, no symlinks or writable ancestors."""
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(CERTBOT_OPTIONS.parts[1:]):
            parent = os.fstat(descriptor)
            require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == 0 and
                    not parent.st_mode & 0o022, 'unsafe_certbot_options_parent')
            final = index == len(CERTBOT_OPTIONS.parts[1:]) - 1
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if not final: flags |= os.O_DIRECTORY
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
                not info.st_mode & 0o7022, 'unsafe_certbot_options_file')
        require(info.st_size <= 65536, 'file_size_limit')
        with os.fdopen(os.dup(descriptor), 'rb') as handle:
            body = handle.read(65537)
        require(len(body) <= 65536, 'file_size_limit')
        after = os.fstat(descriptor)
        require(all(getattr(after, key) == getattr(info, key) for key in
                    ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')),
                'certbot_options_changed_during_read')
        return body
    finally:
        os.close(descriptor)


def check_baseline(path, expected):
    entries = {}
    for line in read_regular(path, 4096).decode().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (/.+)', line)
        require(match is not None, 'baseline_format')
        require(match[2] not in entries, 'baseline_duplicate')
        entries[match[2]] = match[1]
    require(set(entries) == set(expected), 'baseline_paths')
    for name in expected:
        require(digest(Path(name).read_bytes()) == entries[name], 'baseline_hash_changed')


def command(label, args, audit=None, seconds=12):
    result = subprocess.run(args, capture_output=True, timeout=seconds, env=ENV)
    if audit:
        for suffix, data in [('stdout', result.stdout), ('stderr', result.stderr)]:
            with (audit / (label + '.' + suffix)).open('xb') as handle: handle.write(data)
    require(result.returncode == 0, label + '_exit_' + str(result.returncode))
    return result.stdout, result.stderr


def snapshot():
    return command('services', ['/usr/bin/systemctl', 'show', *UNITS,
                               '--property=Id,MainPID,ActiveState,SubState'])[0]


def preservation():
    check_baseline(STATE / 'production-before.sha256', PRODUCTION)
    check_baseline(STATE / 'staging-http.sha256', [str(HTTP_CONF)])
    actual = command('original_services', ['/usr/bin/systemctl', 'show',
        'powerflow-api.service', 'powerflow-streamlit.service',
        '--property=Id,MainPID,ActiveState,SubState'])[0]
    require(actual == read_regular(STATE / 'services-before', 4096), 'original_service_changed')


def nginx_test(label, audit=None):
    _, error = command(label, ['/usr/bin/timeout', '--signal=TERM', '--kill-after=5s',
                              '5s', '/usr/sbin/nginx', '-t'], audit)
    require(not re.search(rb'\[(warn|error|emerg|alert|crit)\]', error, re.I), 'nginx_warning')


def review_config(allow_target=False, config_root=Path('/etc/nginx')):
    """Conservative bounded parser: unsupported syntax/includes STOP before reload."""
    allowed = [config_root, Path('/usr/share/nginx/modules'),
               Path('/usr/lib64/nginx/modules')]
    cache, hashes, sites = {}, {}, []
    stack = []
    expanded = [0]

    def load(path, context=(), certbot_exception=False):
        path = Path(path)
        real = path.resolve()
        require(any(base in real.parents for base in allowed) or
                (certbot_exception and path == CERTBOT_OPTIONS and real == path),
                'unapproved_include_root')
        require(len(stack) < 8 and real not in stack, 'include_cycle_or_depth')
        if real not in cache:
            require(len(cache) < 32, 'configuration_count_limit')
            body = read_certbot_options() if certbot_exception else read_regular(real)
            require(sum(len(x) for x in cache.values()) + len(body) <= 524288, 'configuration_bytes_limit')
            cache[real] = body
            hashes[str(real)] = digest(body)
        lex = shlex.shlex(cache[real].decode(), posix=True, punctuation_chars='{};')
        lex.whitespace_split = True
        lex.commenters = '#'
        tokens = []
        for token in lex:
            if token and set(token) <= set('{};'): tokens.extend(token)
            else: tokens.append(token)
        stack.append(real)
        position = [0]

        def parse(ctx, nested=False):
            nodes = []
            while position[0] < len(tokens):
                if tokens[position[0]] == '}':
                    require(nested, 'unexpected_closing_brace')
                    position[0] += 1
                    return nodes
                words = []
                while position[0] < len(tokens) and tokens[position[0]] not in '{};':
                    words.append(tokens[position[0]]); position[0] += 1
                require(words and position[0] < len(tokens), 'unsupported_configuration_syntax')
                end = tokens[position[0]]; position[0] += 1
                require(end in (';', '{'), 'invalid_directive_end')
                expanded[0] += 1
                require(expanded[0] <= 4096, 'expanded_directive_limit')
                name, args = words[0], words[1:]
                if name == 'include':
                    require(end == ';' and len(args) == 1 and '$' not in args[0], 'unsupported_include')
                    pattern = Path(args[0])
                    if not pattern.is_absolute(): pattern = config_root / pattern
                    require('..' not in pattern.parts, 'include_parent_traversal')
                    exception = args[0] == str(CERTBOT_OPTIONS)
                    require(any(base in pattern.parents for base in allowed) or exception,
                            'unapproved_include_pattern')
                    require(not any(c in str(pattern.parent) for c in '*?['), 'wildcard_include_directory')
                    if pattern.parent == TARGET.parent and fnmatch.fnmatchcase(TARGET.name, pattern.name): sites.append(ctx)
                    # Never glob the exception: missing/unsafe files must fail closed.
                    if exception:
                        nodes.extend(load(CERTBOT_OPTIONS, ctx, certbot_exception=True))
                        continue
                    matches = sorted(glob.glob(str(pattern)))
                    require(len(matches) <= 32, 'include_match_limit')
                    for match in matches: nodes.extend(load(match, ctx))
                else:
                    children = parse(ctx + (name,), True) if end == '{' else None
                    nodes.append((name, args, children, str(real)))
            require(not nested, 'unclosed_block')
            return nodes

        result = parse(context)
        stack.pop()
        return result

    nodes = load(config_root / 'nginx.conf')
    require(sites == [('http',)], 'target_not_in_one_http_include_site')
    summary, stage_http, stage_https = [], 0, 0

    def walk(items, ctx=()):
        nonlocal stage_http, stage_https
        for name, args, children, source in items:
            if name == 'server' and ctx == ('http',):
                require(children is not None, 'server_block_required')
                listeners = [a for n, a, _, _ in children if n == 'listen']
                names = [v.lower().rstrip('.') for n, a, _, _ in children if n == 'server_name' for v in a]
                values = [a[0] for a in listeners if a]
                tls = any(v == '443' or v.endswith(':443') for v in values)
                http = any(v == '80' or v.endswith(':80') for v in values)
                require(not any('$' in v for v in values), 'dynamic_listener')
                if tls:
                    for a in listeners:
                        if a and (a[0] == '443' or a[0].endswith(':443')):
                            require(set(a[1:]) <= {'ssl', 'default_server', 'ipv6only=on', 'ipv6only=off'},
                                    'unsupported_tls_listener_options')
                    require(not any(v.startswith('~') or '*' in v or v.startswith('.') for v in names),
                            'wildcard_or_regex_tls_server_requires_review')
                if HOST in names:
                    if http:
                        require(source == str(HTTP_CONF), 'unexpected_staging_http_server')
                        stage_http += 1
                    if tls:
                        require(allow_target and source == str(TARGET), 'existing_staging_https_conflict')
                        stage_https += 1
                summary.append({'source': source, 'listen': values,
                    'known_names': [v for v in names if v in (HOST, 'powerflowenergy.dev', 'www.powerflowenergy.dev')],
                    'other_name_count': sum(v not in (HOST, 'powerflowenergy.dev', 'www.powerflowenergy.dev') for v in names)})
            if children is not None: walk(children, ctx + (name,))
    walk(nodes)
    require(stage_http == 1 and stage_https == (1 if allow_target else 0), 'staging_server_count')
    require(any('443' in x['listen'] for x in summary), 'expected_ipv4_443_listener_missing')
    return hashes, summary


class LoopbackHTTPS(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection(('127.0.0.1', 443), timeout=2)
        try: self.sock = self._context.wrap_socket(raw, server_hostname=HOST)
        except Exception:
            raw.close()
            raise


def request(path, tls, expected_leaf=None):
    context = ssl.create_default_context(cafile=CA) if tls else None
    connection = LoopbackHTTPS(HOST, timeout=2, context=context) if tls else http.client.HTTPConnection('127.0.0.1', 80, timeout=2)
    try:
        connection.connect()
        if tls:
            require(digest(connection.sock.getpeercert(binary_form=True)) == expected_leaf, 'served_leaf_mismatch')
            require(ssl.cert_time_to_seconds(connection.sock.getpeercert()['notAfter']) ==
                    ssl.cert_time_to_seconds(EXPIRY), 'served_expiry_mismatch')
        connection.request('GET', path, headers={'Host': HOST})
        response = connection.getresponse()
        body = response.read(4097)
        return response.status, body
    finally: connection.close()


def certificate_checks():
    command('cert_hostname', ['/usr/bin/openssl', 'x509', '-in', str(LIVE / 'cert.pem'), '-noout', '-checkhost', HOST])
    command('cert_validity', ['/usr/bin/openssl', 'x509', '-in', str(LIVE / 'cert.pem'), '-noout', '-checkend', '2592000'])
    command('cert_chain', ['/usr/bin/openssl', 'verify', '-CAfile', CA, '-untrusted', str(LIVE / 'chain.pem'), str(LIVE / 'cert.pem')])
    public = command('cert_public', ['/usr/bin/openssl', 'x509', '-in', str(LIVE / 'cert.pem'), '-noout', '-dates', '-ext', 'subjectAltName'])[0].decode()
    require(re.findall(r'DNS:([^,\s]+)', public) == [HOST], 'certificate_SAN')
    require('notAfter=' + EXPIRY in public, 'certificate_expiry_changed')
    # Public certificate only. Never open or hash privkey.pem.
    leaf = digest(ssl.PEM_cert_to_DER_cert((LIVE / 'cert.pem').read_text()))
    require((LIVE / 'privkey.pem').is_file(), 'certificate_key_path_missing')
    return leaf, public.strip().splitlines()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['activate', 'rollback'])
    action = parser.parse_args(argv).action
    os.umask(0o077)
    report = {'action': action, 'status': 'failed', 'phase': 'preflight', 'reload_invocations': 0,
              'production_preservation': 'not_checked_after_attempt'}
    audit = None
    before = None
    try:
        require(os.geteuid() == 0, 'root_required')
        require(STATE.is_dir() and not STATE.is_symlink(), 'state_directory_invalid')
        require(STATE.stat().st_uid == 0 and stat.S_IMODE(STATE.stat().st_mode) & 0o077 == 0, 'state_permissions')
        require(TARGET.parent.is_dir() and not TARGET.parent.is_symlink(), 'nginx_directory_invalid')
        for path in ['/usr/sbin/nginx', '/usr/bin/timeout', '/usr/bin/openssl', '/usr/bin/systemctl']:
            require(os.access(path, os.X_OK), 'required_executable_missing')
        preview = read_regular(PREVIEW)
        require(digest(preview) == PREVIEW_SHA, 'preview_hash_changed')
        preservation()
        states = command('active', ['/usr/bin/systemctl', 'show', *UNITS, '--property=ActiveState', '--value'])[0]
        require(states.split() == [b'active'] * len(UNITS), 'required_service_not_active')
        before = snapshot()
        if action == 'activate':
            require(not os.path.lexists(TARGET) and not os.path.lexists(AUDIT), 'activation_destination_exists')
            leaf, dates = certificate_checks()
            hashes, summary = review_config(False)
            require(request(PROBE_URL, False) == (200, PROBE_BODY), 'http_probe_failed')
            AUDIT.mkdir(mode=0o700)
            audit = AUDIT
            with (audit / 'services-before').open('xb') as handle: handle.write(before)
            with (audit / 'config-before.json').open('x') as handle: json.dump(hashes, handle, indent=2)
            report['configuration_review'] = summary
            report['certificate_dates_SAN'] = dates
            nginx_test('baseline_nginx', audit)
            # Configuration must remain unchanged during preflight.
            require(all(digest(Path(p).read_bytes()) == h for p, h in hashes.items()), 'configuration_changed_during_review')
            report['phase'] = 'install_staging_only_vhost'
            fd = os.open(TARGET, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, 'wb') as handle: handle.write(preview)
            # umask077 intentionally overrides create mode; make only this new public config0644.
            os.chmod(TARGET, 0o644)
            report['target_installed'] = True
            nginx_test('installed_nginx', audit)
            after_hashes, _ = review_config(True)
            require(after_hashes == {**hashes, str(TARGET): PREVIEW_SHA}, 'unexpected_configuration_delta')
            require(digest(read_regular(TARGET)) == PREVIEW_SHA, 'installed_hash_changed')
            preservation()
        else:
            require(AUDIT.is_dir() and not AUDIT.is_symlink(), 'activation_audit_missing')
            require(digest(read_regular(TARGET)) == PREVIEW_SHA, 'rollback_target_changed')
            require(not os.path.lexists(AUDIT / 'rollback'), 'rollback_already_attempted')
            (AUDIT / 'rollback').mkdir(mode=0o700)
            audit = AUDIT / 'rollback'
            report['phase'] = 'disable_staging_only_vhost'
            os.rename(TARGET, audit / 'disabled-staging-https.conf')
            report['target_disabled'] = True
            nginx_test('rollback_nginx', audit)
            review_config(False)
            preservation()
        report['phase'] = 'graceful_reload'
        report['reload_invocations'] = 1
        command('reload', ['/usr/bin/timeout', '--signal=TERM', '--kill-after=5s', '10s',
                           '/usr/bin/systemctl', 'reload', 'nginx'], audit, seconds=20)
        report['reload_command_succeeded'] = True
        if action == 'activate':
            report['phase'] = 'loopback_verification'
            # Readiness polling only: up to10 TLS GETs, one second apart. Never repeat reload.
            ready = False
            for attempt in range(10):
                report['tls_readiness_requests'] = attempt + 1
                try:
                    status, _ = request('/', True, leaf)
                    if status == 404:
                        ready = True
                        break
                except (OSError, RuntimeError, http.client.HTTPException): pass
                if attempt < 9: time.sleep(1)
            require(ready, 'tls_readiness_failed')
            require(request(PROBE_URL, True, leaf) == (200, PROBE_BODY), 'https_acme_probe_failed')
            require(request(PROBE_URL, False) == (200, PROBE_BODY), 'http_acme_probe_failed')
            report['https_verification'] = {'hostname_and_chain': 'verified', 'issued_leaf_matches': True,
                                          'root_status': 404, 'https_acme_status': 200, 'http_acme_status': 200}
        else:
            require(request(PROBE_URL, False) == (200, PROBE_BODY), 'rollback_http_probe_failed')
        report['status'] = 'passed'
        report['phase'] = 'complete'
    except RuntimeError as error: report['error'] = str(error)
    except subprocess.TimeoutExpired: report['error'] = 'bounded_subcommand_timeout'
    except Exception: report['error'] = 'operation_failed_details_withheld'
    finally:
        if audit:
            try:
                preservation()
                require(snapshot() == before, 'service_identity_changed')
                report['production_preservation'] = 'passed'
            except Exception:
                report['production_preservation'] = 'failed_or_unverified'
                report['status'] = 'failed'
            with (audit / 'report.json').open('x') as handle: json.dump(report, handle, indent=2)
            report['private_audit_directory'] = str(audit)
        print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__': raise SystemExit(main())
