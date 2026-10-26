#!/usr/bin/env python3
"""APPROVAL REQUIRED: one staging certificate issuance; never install/reload Nginx."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import stat
import subprocess

HOST = 'staging.powerflowenergy.dev'
EMAIL = 'iannganga11079@gmail.com'
STATE = Path('/var/lib/powerflow-staging-https-20261026')
AUDIT = STATE / 'issuance-continuation-20261026'
CONF = Path('/etc/nginx/conf.d/powerflow-staging-acme.conf')
WEBROOT = Path('/var/www/powerflow-staging-acme')
CERTDIR = Path('/etc/letsencrypt-powerflow-staging')
WORKDIR = Path('/var/lib/letsencrypt-powerflow-staging')
LOGDIR = Path('/var/log/letsencrypt-powerflow-staging')
LIVE = CERTDIR / 'live' / HOST
PRODUCTION = ['/etc/nginx/conf.d/powerflow.conf',
              '/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem']
UNITS = ['powerflow-api.service', 'powerflow-streamlit.service',
         'powerflow-prefect-worker.service', 'powerflow-prefect-server.service',
         'postgresql.service']
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C',
       'HOME': '/root', 'PYTHONDONTWRITEBYTECODE': '1'}
HTTPS_PREVIEW = '''# PREVIEW ONLY: not installed or activated by this continuation.
server {
    listen 443 ssl;
    server_name staging.powerflowenergy.dev;
    ssl_certificate /etc/letsencrypt-powerflow-staging/live/staging.powerflowenergy.dev/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt-powerflow-staging/live/staging.powerflowenergy.dev/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    server_tokens off;
    access_log off;
    error_log /var/log/nginx/powerflow-staging-https-error.log crit;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer always;
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/powerflow-staging-acme;
        default_type text/plain;
        try_files $uri =404;
    }
    location / { return 404; }
}
'''


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def hash_matches(baseline, expected):
    require(baseline.is_file() and not baseline.is_symlink(), 'baseline_not_regular')
    require(baseline.stat().st_size <= 4096, 'baseline_size')
    entries = {}
    for line in baseline.read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (/.+)', line)
        require(match is not None, 'baseline_format')
        require(match[2] not in entries, 'baseline_duplicate')
        entries[match[2]] = match[1]
    require(set(entries) == set(expected), 'baseline_paths')
    for name in expected:
        digest = hashlib.sha256()
        with open(name, 'rb') as handle:
            for block in iter(lambda: handle.read(65536), b''):
                digest.update(block)
        require(digest.hexdigest() == entries[name], 'preservation_hash_mismatch')


def command(label, args, seconds=5, capture_audit=False):
    result = subprocess.run(args, capture_output=True, timeout=seconds, env=ENV)
    if capture_audit:
        for suffix, data in [('stdout', result.stdout), ('stderr', result.stderr)]:
            with (AUDIT / (label + '.' + suffix)).open('xb') as handle:
                handle.write(data)
    require(result.returncode == 0, label + '_failed_exit_' + str(result.returncode))
    return result.stdout


def service_snapshot():
    return command('service_snapshot', [
        '/usr/bin/systemctl', 'show', *UNITS,
        '--property=Id,MainPID,ActiveState,SubState'])


def original_service_check():
    baseline = STATE / 'services-before'
    require(baseline.is_file() and not baseline.is_symlink(), 'service_baseline_not_regular')
    require(baseline.stat().st_size <= 4096, 'service_baseline_size')
    current = command('original_services', [
        '/usr/bin/systemctl', 'show', 'powerflow-api.service',
        'powerflow-streamlit.service', '--property=Id,MainPID,ActiveState,SubState'])
    require(current == baseline.read_bytes(), 'original_service_identity_mismatch')


def active_service_check():
    states = command('active_services', [
        '/usr/bin/systemctl', 'show', 'nginx.service', *UNITS,
        '--property=ActiveState', '--value'])
    require(states.split() == [b'active'] * (len(UNITS) + 1), 'required_service_not_active')


def preflight():
    require(os.geteuid() == 0, 'root_required')
    for tool in ['/usr/bin/certbot', '/usr/bin/timeout', '/usr/bin/openssl',
                 '/usr/bin/systemctl']:
        require(os.access(tool, os.X_OK), 'required_executable_missing')
    require(Path('/etc/pki/tls/certs/ca-bundle.crt').is_file(), 'ca_bundle_missing')
    require(STATE.is_dir() and not STATE.is_symlink(), 'state_directory_invalid')
    require(STATE.stat().st_uid == 0 and
            stat.S_IMODE(STATE.stat().st_mode) & 0o077 == 0, 'state_directory_permissions')
    require(not os.path.lexists(AUDIT), 'continuation_already_exists')
    require(Path('/etc/nginx/conf.d').is_dir() and
            not Path('/etc/nginx/conf.d').is_symlink(), 'nginx_directory_invalid')
    require(CONF.is_file() and not CONF.is_symlink(), 'staging_http_config_invalid')
    hash_matches(STATE / 'staging-http.sha256', [str(CONF)])
    hash_matches(STATE / 'production-before.sha256', PRODUCTION)
    original_service_check()
    require(WEBROOT.is_dir() and not WEBROOT.is_symlink(), 'webroot_invalid')
    probe = WEBROOT / '.well-known/acme-challenge/preflight-probe'
    require(probe.is_file() and not probe.is_symlink() and
            probe.stat().st_size <= 4096, 'probe_invalid')
    require(probe.read_bytes() == b'powerflow-staging-acme-preflight\n', 'probe_content_mismatch')
    for directory in [CERTDIR, WORKDIR, LOGDIR]:
        require(directory.is_dir() and not directory.is_symlink(), 'isolated_directory_invalid')
        info = directory.stat()
        require(info.st_uid == 0 and stat.S_IMODE(info.st_mode) & 0o077 == 0,
                'isolated_directory_permissions')
        require(not any(directory.iterdir()), 'isolated_directory_not_empty')
    for path in [LIVE, CERTDIR / 'archive' / HOST, CERTDIR / 'renewal' / (HOST + '.conf')]:
        require(not os.path.lexists(path), 'staging_lineage_already_exists')
    # Exactly one fresh loopback GET; no DNS, redirect, or response-body output.
    connection = http.client.HTTPConnection('127.0.0.1', 80, timeout=3)
    try:
        connection.request('GET', '/.well-known/acme-challenge/preflight-probe',
                           headers={'Host': HOST})
        response = connection.getresponse()
        require(response.status == 200 and response.read(4097) ==
                b'powerflow-staging-acme-preflight\n', 'loopback_probe_failed')
    finally:
        connection.close()
    active_service_check()
    return service_snapshot()


def main():
    os.umask(0o077)
    report = {'status': 'failed', 'phase': 'preflight', 'issuance_invocations': 0,
              'production_preservation': 'not_checked_after_attempt',
              'https_preview_installed': False, 'renewal_timer_enabled': False}
    created = False
    before = None
    try:
        before = preflight()  # All baseline checks precede payload writes.
        AUDIT.mkdir(mode=0o700)
        created = True
        with (AUDIT / 'services-before').open('xb') as handle:
            handle.write(before)
        report['phase'] = 'certificate_issuance'
        report['issuance_invocations'] = 1
        command('certbot', [
            '/usr/bin/timeout', '--signal=TERM', '--kill-after=5s', '60s',
            '/usr/bin/certbot', 'certonly', '--config', '/dev/null',
            '--config-dir', str(CERTDIR), '--work-dir', str(WORKDIR),
            '--logs-dir', str(LOGDIR), '--no-directory-hooks',
            '--webroot', '--webroot-path', str(WEBROOT), '--cert-name', HOST,
            '--domain', HOST, '--email', EMAIL, '--agree-tos', '--non-interactive',
        ], seconds=70, capture_audit=True)
        report['phase'] = 'certificate_validation'
        command('hostname', ['/usr/bin/openssl', 'x509', '-in', str(LIVE / 'cert.pem'),
                            '-noout', '-checkhost', HOST])
        command('remaining_validity', ['/usr/bin/openssl', 'x509', '-in',
                str(LIVE / 'cert.pem'), '-noout', '-checkend', '2592000'])
        command('chain', ['/usr/bin/openssl', 'verify', '-CAfile',
                '/etc/pki/tls/certs/ca-bundle.crt', '-untrusted', str(LIVE / 'chain.pem'),
                str(LIVE / 'cert.pem')])
        public = command('public_certificate', ['/usr/bin/openssl', 'x509', '-in',
                str(LIVE / 'cert.pem'), '-noout', '-dates', '-ext', 'subjectAltName']).decode()
        require(re.findall(r'DNS:([^,\s]+)', public) == [HOST], 'unexpected_certificate_names')
        report['certificate'] = {'hostname': HOST, 'chain_valid': True,
                                 'remaining_validity_over_30_days': True,
                                 'public_dates_and_SAN': public.strip().splitlines()}
        report['phase'] = 'private_https_preview'
        with (AUDIT / 'staging-https-preview.conf').open('x') as handle:
            handle.write(HTTPS_PREVIEW)
        report['status'] = 'passed'
        report['phase'] = 'complete'
    except RuntimeError as error:
        report['error'] = str(error)  # Fixed internal codes, never provider messages.
    except subprocess.TimeoutExpired:
        report['error'] = 'bounded_subcommand_timeout'
    except Exception:
        report['error'] = 'operation_failed_details_withheld'
    finally:
        if created:
            # Read-only verification even after an issuance/validation failure;
            # never attempt repair, retry, deletion or automatic rollback.
            try:
                hash_matches(STATE / 'production-before.sha256', PRODUCTION)
                hash_matches(STATE / 'staging-http.sha256', [str(CONF)])
                original_service_check()
                after = service_snapshot()
                require(after == before, 'service_identity_changed_during_continuation')
                report['production_preservation'] = 'passed'
            except Exception:
                report['production_preservation'] = 'failed_or_unverified'
                report['status'] = 'failed'
            with (AUDIT / 'report.json').open('x') as handle:
                json.dump(report, handle, indent=2)
            report['private_audit_directory'] = str(AUDIT)
        print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
