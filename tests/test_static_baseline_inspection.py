"""Offline comparison/security tests. Never connect to a host."""
import ast
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'deploy/staging/static-baseline-inspection-v1'
def load():
    spec=importlib.util.spec_from_file_location('offline_static_inspection',HERE/'inspect.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_exact_missing_unexpected_and_hash_differences():
    m=load();a={'index.html':'a'*64,'assets/old.js':'b'*64};b={'index.html':'c'*64,'assets/new.js':'d'*64}
    assert m.difference(a,b)=={'missing':{'assets/old.js':'b'*64},'unexpected':{'assets/new.js':'d'*64},'hash_mismatched':{'index.html':{'expected':'a'*64,'observed':'c'*64}}}
    assert m.difference(a,a)=={'missing':{},'unexpected':{},'hash_mismatched':{}}

@pytest.mark.parametrize('path',['../secret','/outside','assets/../../outside','assets//x','assets/./x','x?token=secret','x\nsecret'])
def test_relative_path_rejection(path):
    m=load()
    with pytest.raises(m.Stop):m.table({path:'a'*64})

@pytest.mark.parametrize('mode,uid',[(0o100666,0),(0o120777,0),(0o100644,1000)])
def test_unsafe_metadata(mode,uid):
    m=load()
    with pytest.raises(m.Stop):m.metadata(SimpleNamespace(st_mode=mode,st_uid=uid),False)

def test_inventory_on_native_fixtures_and_symlink_rejection(tmp_path,monkeypatch):
    m=load();(tmp_path/'index.html').write_bytes(b'index');(tmp_path/'assets').mkdir();(tmp_path/'assets/app.js').write_bytes(b'code')
    real_open=os.open
    monkeypatch.setattr(os,'O_NOATIME',getattr(os,'O_NOATIME',0),raising=False)
    monkeypatch.setattr(m,'metadata',lambda *a:None) # Linux ownership is tested separately; fixture owner is local user.
    fd=real_open(tmp_path,os.O_RDONLY|os.O_DIRECTORY)
    try:
        assert m.inventory(fd)=={'index.html':m.sha(b'index'),'assets/app.js':m.sha(b'code')}
        (tmp_path/'assets/link.js').symlink_to(tmp_path/'index.html')
        with pytest.raises(OSError):m.inventory(fd)
    finally:os.close(fd)

def test_original_inventory_construction_is_not_original_deployment_rule():
    m=json.loads((ROOT/'deploy/staging/operational-evidence-release-v1/MANIFEST.json').read_text())
    a=json.loads((ROOT/'data/backups/private-staging-releases/phase-api-body-bound-20261102-v2/release/release-manifest.json').read_text())
    current={k[7:]:v['sha256'] for k,v in a['files'].items() if k.startswith('static/')}
    expected=m['config']['old_static_inventory']
    assert len(current)==37 and len(expected)==62 and len(expected.keys()-current.keys())==25
    assert all(expected[k]==v for k,v in current.items())
    import hashlib
    earlier='/var/www/powerflow-staging/releases/phase-forecast-consistency-20261101-v1'
    assert hashlib.sha256(earlier.encode()).hexdigest()!='4d9590d765bc745f120412525ed0d117d251236d278234aada2433d0f97ad374'

def test_original_record_correlates_inventory_not_host_hash_adoption(monkeypatch):
    m=load();approved={'index.html':'a'*64};old={'index.html':'b'*64,'assets/old.js':'c'*64}
    record={'transaction_id':m.TX,'phase':'COMPLETE','new_static':m.ROOT,'previous_static':'fixture','old_static_files':old,'retained_assets':{'assets/old.js':'c'*64}}
    monkeypatch.setattr(m,'PREDECESSOR_SHA',m.sha(b'fixture'));monkeypatch.setattr(m,'directory',lambda p:999);monkeypatch.setattr(m.os,'close',lambda fd:None)
    monkeypatch.setattr(m,'file_bytes',lambda *a:json.dumps(record).encode())
    observed={**approved,'assets/old.js':'c'*64}
    result=m.retained_record(approved,observed)
    assert result['expected_deployed_count']==2 and result['differences']==m.difference(observed,observed)
    record['retained_assets']={}
    with pytest.raises(m.Stop):m.retained_record(approved,observed)

def test_output_is_bounded_and_errors_sanitized(monkeypatch,capsys):
    m=load();monkeypatch.setattr(m.sys,'platform','linux');monkeypatch.setattr(m.os,'getuid',lambda:0);monkeypatch.setattr(m.os,'geteuid',lambda:0)
    monkeypatch.setattr(m.os,'O_NOATIME',0,raising=False);m.EXPECTED={};m.APPROVED={}
    monkeypatch.setattr(m,'pointer',lambda:(_ for _ in ()).throw(OSError('secret /unapproved/path')))
    assert m.main()==1
    raw=capsys.readouterr().out;assert 'secret' not in raw and '/unapproved' not in raw
    assert json.loads(raw)['reason']=='READ_ONLY_OBSERVATION_FAILED'

def test_no_mutation_network_import_or_retry_entrypoints():
    source=(HERE/'inspect.py').read_text();tree=ast.parse(source,feature_version=(3,9))
    calls={getattr(n.func,'attr',getattr(n.func,'id','')) for n in ast.walk(tree) if isinstance(n,ast.Call)}
    assert not calls&{'write','mkdir','chmod','chown','unlink','replace','symlink','request','connect','system','Popen','run','publish','apply','rollback'}
    imports={n.name for node in ast.walk(tree) if isinstance(node,ast.Import) for n in node.names}
    assert imports=={'hashlib','json','os','re','stat','sys'}
    assert 'O_NOFOLLOW' in source and 'O_NOATIME' in source
    ast.parse((HERE/'run.py').read_text(),feature_version=(3,9))

def test_manifest_and_payload_closure_and_no_transport_on_local_check(monkeypatch):
    spec=importlib.util.spec_from_file_location('offline_static_runner',HERE/'run.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    import hashlib
    raw=(HERE/'MANIFEST.json').read_bytes();payload,wrapper,base=m.verify(hashlib.sha256(raw).hexdigest())
    assert payload==(HERE/'inspect.payload.py').read_bytes()
    monkeypatch.setattr(m,'verify',lambda h:(payload,None,None))
    monkeypatch.setattr(m.argparse.ArgumentParser,'parse_args',lambda p:SimpleNamespace(manifest_sha256='fixture',local_check=True))
    assert m.main()==0
