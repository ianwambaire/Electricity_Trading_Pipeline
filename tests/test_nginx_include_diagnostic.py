"""Offline fixture configs only; no SSH/Nginx/systemd execution."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('nginx_include_diag', ROOT / 'deploy/staging/diagnose-nginx-include.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def test_lines_comments_quotes_and_inline_blocks():
    text = '# include fake;\nhttp { include "conf.d/*.conf";\nlog_format x "include fake;";\ninclude\n mime.types; }\n'
    assert m.include_lines(text) == [2, 4]


def test_rejected_pattern_reports_line_without_following_and_discovers_site(tmp_path):
    root = tmp_path / 'nginx'; (root / 'conf.d').mkdir(parents=True)
    (root / 'nginx.conf').write_text('# header\ninclude /outside/unapproved/*.conf;\nhttp { include conf.d/*.conf; }\n')
    (root / 'conf.d/known.conf').write_text('server { listen 80; }')
    report = m.inspect(root, root / 'conf.d/staging.conf')
    first = report['first_rejected_include_observed']
    assert first['line'] == 2 and first['reviewer_result'] == 'unapproved_include_pattern'
    assert first['pattern'] == '/outside/unapproved/*.conf'
    assert first['expansion'] == 'NOT_EXPANDED'
    assert report['one_observed_http_include_site'] is True
    assert report['all_include_branches_reviewed'] is False
    assert len(report['source_files_read']) == 2


def test_nested_source_line_and_hierarchy(tmp_path):
    root = tmp_path / 'nginx'; (root / 'conf.d').mkdir(parents=True)
    (root / 'nginx.conf').write_text('http { include conf.d/*.conf; }')
    nested = root / 'conf.d/site.conf'; nested.write_text('# hi\nserver {\ninclude /another/shared.conf;\n}')
    report = m.inspect(root, root / 'conf.d/new.conf')
    rejected = report['first_rejected_include_observed']
    assert rejected['source_file'] == str(nested) and rejected['line'] == 3
    assert rejected['context'] == ['http', 'server']
    assert rejected['include_hierarchy'][0]['line'] == 1


def test_non_path_tokens_are_redacted():
    assert m.safe_pattern('/usr/share/nginx/modules/*.conf') == '/usr/share/nginx/modules/*.conf'
    assert 'user:credential' not in m.safe_pattern('https://user:credential@example.invalid')
