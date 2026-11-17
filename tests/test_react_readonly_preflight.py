"""Local fixed-path/redaction/primitive tests only; no preflight/SSH execution."""
import ast
import importlib.util
import json
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
p=ROOT/'deploy/staging/preflight-react-readonly.py'
s=importlib.util.spec_from_file_location('readonly',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)


def test_metadata_never_reads_environment_contents(tmp_path):
    p=tmp_path/'react-api.env';p.write_text('SECRET=never-output')
    r=m.metadata(p)
    assert r['regular'] and 'SECRET' not in json.dumps(r)
    assert m.metadata(tmp_path/'missing')=={'exists':False}


def test_config_reports_facts_not_raw_text(tmp_path):
    p=tmp_path/'config';p.write_text('server_name staging.powerflowenergy.dev;\n# PRIVATE_VALUE\ninclude /sensitive/path;')
    r=m.config(p)
    assert r['staging_name_present'] and r['include_count']==1
    assert 'PRIVATE_VALUE' not in json.dumps(r) and '/sensitive/path' not in json.dumps(r)


def test_read_refuses_symlink_and_oversized_file(tmp_path):
    p=tmp_path/'file';p.write_text('abc');q=tmp_path/'link';q.symlink_to(p)
    with pytest.raises(OSError):m.read(q)
    with pytest.raises(ValueError):m.read(p,2)


def test_payload_has_no_service_or_nginx_mutations():
    tree=ast.parse(p.read_text())
    strings=[x.value for x in ast.walk(tree) if isinstance(x,ast.Constant) and isinstance(x.value,str)]
    assert not {'restart','reload','start','stop','daemon-reload','enable','-t','-T','certonly'} & set(strings)
    assert not any('privkey.pem' in x for x in strings)
    assert 'capture_output=True' in p.read_text() and 'timeout=8' in p.read_text()
    compile(p.read_bytes(),str(p),'exec')
    ast.parse(p.read_bytes(),feature_version=(3,9))


def test_non_root_produces_json_and_stops(monkeypatch,capsys):
    monkeypatch.setattr(m.os,'geteuid',lambda:1000)
    monkeypatch.setattr(m,'run',lambda *_:pytest.fail('no subcommands without sudo'))
    assert m.main()==1
    assert json.loads(capsys.readouterr().out)['errors'][-1]['exception_type']=='RootRequired'


def test_subcommand_failure_never_exposes_stderr(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(m.subprocess,'run',lambda *a,**k:
                        SimpleNamespace(returncode=1,stdout=b'private',stderr=b'private'))
    with pytest.raises(RuntimeError,match='^subcommand_failed$'):
        m.run(['/usr/bin/systemctl','show','nginx.service'])


def test_only_missing_candidate_unit_is_expected(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(m.subprocess,'run',lambda *a,**k:
        SimpleNamespace(returncode=1,stdout=b'LoadState=not-found\n',stderr=b''))
    args=['/usr/bin/systemctl','show','powerflow-candidate-api.service','--property='+m.PROPERTIES]
    assert 'not-found' in m.run(args)
    with pytest.raises(RuntimeError):m.run(['/usr/bin/systemctl','show','powerflow-api.service'])
