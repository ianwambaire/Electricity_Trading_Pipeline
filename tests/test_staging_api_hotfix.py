import importlib.util,json,os
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
@pytest.fixture
def hotfix():
    spec=importlib.util.spec_from_file_location('context_hotfix',ROOT/'deploy/staging/api-hotfix/hotfix.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_inputs_are_exact_two_file_fix(hotfix):
    inputs=json.loads(hotfix.INPUTS_JSON)
    assert set(inputs['patches'])=={'src/shared/market_context.py','src/shared/price_aggregation.py'}
    assert len(inputs['original'])==22
    import base64,hashlib,ast
    for name,item in inputs['patches'].items():
        data=base64.b64decode(item['base64'])
        assert data==(ROOT/name).read_bytes()
        assert hashlib.sha256(data).hexdigest()==item['sha256'];ast.parse(data)

def test_atomic_pointer_switch_and_conflicts(hotfix,tmp_path,monkeypatch):
    old=tmp_path/'old';new=tmp_path/'new';old.mkdir();new.mkdir()
    link=tmp_path/'react-current';link.symlink_to(old);monkeypatch.setattr(hotfix,'LINK',link)
    hotfix.pointer(old,new);assert link.resolve()==new
    with pytest.raises(RuntimeError,match='current_pointer_changed'):hotfix.pointer(old,new)
    hotfix.pointer(new,old);assert link.resolve()==old
    (tmp_path/'react-current.context-hotfix-pending').write_text('retain')
    with pytest.raises(RuntimeError,match='pointer_temp_conflict'):hotfix.pointer(old,new)
    assert link.resolve()==old

def test_guards_and_no_other_service_mutations(hotfix):
    text=(ROOT/'deploy/staging/api-hotfix/hotfix.py').read_text()
    assert "command(['/usr/bin/systemctl','restart',UNIT])" in text
    for forbidden in ['daemon-reload','nginx -t','reload','pip install','rmtree','unlink(']:assert forbidden not in text
    assert '>768*1024' in text
    assert "memory.swap.max" in text and "memory.max" in text
    assert "verify_base();before=baseline()" in text
    assert "not os.path.lexists(NEW)" in text

def test_regular_rejects_symlink(hotfix,tmp_path):
    file=tmp_path/'file';file.write_text('data');link=tmp_path/'link';link.symlink_to(file)
    with pytest.raises(RuntimeError,match='unsafe_file'):hotfix.regular(link)
