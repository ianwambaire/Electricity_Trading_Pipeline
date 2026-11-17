"""Offline isolated tests only: never SSH, Certbot, Nginx or live paths."""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('staging_issue', ROOT / 'deploy/staging/issue-staging-certificate.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_baseline_exact_paths_digest_and_symlink_guard(tmp_path):
    target = tmp_path / 'public'; target.write_text('original')
    baseline = tmp_path / 'baseline'
    baseline.write_text(hashlib.sha256(target.read_bytes()).hexdigest() + '  ' + str(target) + '\n')
    m.hash_matches(baseline, [str(target)])
    with pytest.raises(RuntimeError, match='baseline_paths'):
        m.hash_matches(baseline, [str(tmp_path / 'another')])
    target.write_text('changed')
    with pytest.raises(RuntimeError, match='preservation_hash_mismatch'):
        m.hash_matches(baseline, [str(target)])
    link = tmp_path / 'link'; link.symlink_to(baseline)
    with pytest.raises(RuntimeError, match='baseline_not_regular'):
        m.hash_matches(link, [str(target)])


def test_failed_preflight_does_not_write_or_invoke_certbot(tmp_path, monkeypatch, capsys):
    audit = tmp_path / 'audit'; monkeypatch.setattr(m, 'AUDIT', audit)
    def fail(): raise RuntimeError('preservation_hash_mismatch')
    monkeypatch.setattr(m, 'preflight', fail)
    monkeypatch.setattr(m, 'command', lambda *a, **k: pytest.fail('must not issue'))
    previous = m.os.umask(0o077)
    try: assert m.main() == 1
    finally: m.os.umask(previous)
    assert not audit.exists()
    assert json.loads(capsys.readouterr().out)['issuance_invocations'] == 0


@pytest.mark.parametrize('fail_issuance', [False, True])
def test_one_issuance_private_preview_and_preservation_on_failure(tmp_path, monkeypatch, capsys, fail_issuance):
    audit = tmp_path / 'audit'; monkeypatch.setattr(m, 'AUDIT', audit)
    monkeypatch.setattr(m, 'preflight', lambda: b'unchanged services')
    monkeypatch.setattr(m, 'service_snapshot', lambda: b'unchanged services')
    monkeypatch.setattr(m, 'original_service_check', lambda: None)
    preservation = []
    monkeypatch.setattr(m, 'hash_matches', lambda *a: preservation.append(a))
    calls = []
    def command(label, args, **kwargs):
        calls.append((label, args))
        if label == 'certbot':
            assert args.count('/usr/bin/certbot') == 1
            assert args[args.index('--domain') + 1] == m.HOST
            assert args[args.index('--config-dir') + 1] == str(m.CERTDIR)
            assert '--no-directory-hooks' in args and '--config' in args
            assert '--force-renewal' not in args and '--nginx' not in args
            if fail_issuance: raise RuntimeError('certbot_failed_exit_1')
        if label == 'public_certificate':
            return b'notBefore=Oct 26 00:00:00 2026 GMT\nnotAfter=Jan 24 00:00:00 2027 GMT\nX509v3 Subject Alternative Name:\n    DNS:staging.powerflowenergy.dev\n'
        return b''
    monkeypatch.setattr(m, 'command', command)
    previous = m.os.umask(0o077)
    try: assert m.main() == (1 if fail_issuance else 0)
    finally: m.os.umask(previous)
    result = json.loads(capsys.readouterr().out)
    assert result['issuance_invocations'] == 1
    assert result['production_preservation'] == 'passed'
    assert len(preservation) == 2
    assert len([c for c in calls if c[0] == 'certbot']) == 1
    assert (audit / 'report.json').stat().st_mode & 0o777 == 0o600
    assert (audit / 'staging-https-preview.conf').exists() is not fail_issuance
    assert result['https_preview_installed'] is False
    assert result['renewal_timer_enabled'] is False


@pytest.mark.parametrize('states,passes', [([b'active'] * 6, True),
                                         ([b'active'] * 5 + [b'inactive'], False)])
def test_every_required_service_must_be_active(monkeypatch, states, passes):
    monkeypatch.setattr(m, 'command', lambda *a, **kw: b'\n'.join(states))
    if passes:
        m.active_service_check()
    else:
        with pytest.raises(RuntimeError, match='required_service_not_active'):
            m.active_service_check()
