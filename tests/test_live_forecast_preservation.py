"""Local reproduction of the actual acceptance gate; no host/network access."""
import ast
import hashlib
import json
from pathlib import Path
import types
import pytest

ROOT=Path(__file__).parents[1]
V2=ROOT/'deploy/staging/live-forecast-reliability-release-v2'
V3=ROOT/'deploy/staging/live-forecast-reliability-acceptance-v3'
CANDIDATE=ROOT/'deploy/staging/live-forecast-preservation-review-v1/preservation.py'
KEYS=('production','forecast','store','helper','policy','environment','nginx')
class Stop(ValueError):pass
def need(value,code):
    if not value:raise Stop(code)
def functions(path,names):
    tree=ast.parse(path.read_bytes());tree.body=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name in names]
    assert {n.name for n in tree.body}==set(names)
    return compile(tree,str(path),'exec')
def original():
    scope={'need':need};exec(functions(V2/'guards.py',{'same'}),scope);return scope['same']
def candidate():
    scope={'need':need};exec(compile(CANDIDATE.read_bytes(),str(CANDIDATE),'exec'),scope);return scope
def baseline():
    return {'production':'production-at-install','forecast':{'pointer':'releases/'+'a'*64,'bundle':'a'*64},'store':'store-at-install','helper':'helper','policy':'policy','environment':'environment','nginx':'nginx'}

def test_actual_acceptance_gate_rejects_legitimate_new_publications():
    before=baseline();after=baseline();after['forecast']={'pointer':'releases/'+'b'*64,'bundle':'b'*64};after['store']='new-valid-evidence'
    with pytest.raises(Stop,match='^PRESERVATION_DRIFT$'):original()(before,after)
    assert candidate()['preservation_differences'](before,after)==('forecast','store')
    # Reporting correction does NOT approve the new state or weaken equality.
    with pytest.raises(Stop,match='^PRESERVATION_DRIFT_FORECAST$'):candidate()['same'](before,after)

@pytest.mark.parametrize('key',KEYS)
def test_each_failure_identifies_only_approved_component(key):
    before=baseline();after=baseline();after[key]='PRIVATE_PATH password=SECRET TOKEN sensitive-body'
    with pytest.raises(Stop)as error:candidate()['same'](before,after)
    assert str(error.value)=='PRESERVATION_DRIFT_'+key.upper()
    assert len(str(error.value))<=80
@pytest.mark.parametrize('keys',[('production','forecast','store'),('helper','nginx'),KEYS])
def test_multiple_differences_bounded_and_deterministic(keys):
    before=baseline();after=baseline()
    for key in keys:after[key]='changed'
    expected=tuple(k for k in KEYS if k in keys)
    assert candidate()['preservation_differences'](before,after)==expected
    assert candidate()['preservation_differences'](dict(reversed(list(before.items()))),dict(reversed(list(after.items()))))==expected
    with pytest.raises(Stop,match='^PRESERVATION_DRIFT_'+expected[0].upper()+'$'):candidate()['same'](before,after)
@pytest.mark.parametrize('change',['missing','extra','not-dict'])
def test_schema_rejects_unapproved_names_without_disclosure(change):
    before=baseline();after=baseline()
    if change=='missing':after.pop('forecast')
    elif change=='extra':after['SECRET_PRIVATE_PATH']='secret'
    else:after=[]
    with pytest.raises(Stop,match='^PRESERVATION_SCHEMA$'):candidate()['same'](before,after)
def test_equal_values_and_no_mutation():
    before=baseline();after=json.loads(json.dumps(before));raw=json.dumps([before,after])
    assert original()(before,after)is None and candidate()['same'](before,after)is None
    assert json.dumps([before,after])==raw

def test_full_real_deployment_checks_preserves_check_order_and_failure(monkeypatch):
    # Run unchanged V3 deployment_checks with the new reporting function only.
    scope=candidate();calls=[];before=baseline();after=baseline();after['policy']='changed'
    scope.update(old_trees=lambda:calls.append('old-trees'),tree_state=lambda *a,**k:calls.append('new-trees'),
        G={'runtime':lambda _:calls.append('sandbox')},API='new-api',STATIC='new-static',
        B={'request':lambda *a,**k:(200,b'index')},sha=lambda _: 'index-hash',
        C={'files':{'static/index.html':{'sha256':'index-hash'}}},baseline_preservation=lambda:after,
        public_operations=lambda:calls.append('public'),forecast_checks=lambda:calls.append('forecast'),Path=Path)
    link=lambda target:types.SimpleNamespace(resolve=lambda **_:target)
    scope['P']=types.SimpleNamespace(candidate_environment=lambda _:calls.append('environment'),BACKEND_LINK=link('new-api'),STATIC_LINK=link('new-static'))
    exec(functions(V3/'acceptance.py',{'deployment_checks'}),scope)
    with pytest.raises(Stop,match='^PRESERVATION_DRIFT_POLICY$'):scope['deployment_checks']({'baseline':dict(before,venv='venv',runtime='runtime')})
    assert calls==['old-trees','new-trees','sandbox','environment'] # no subsequent API/evidence checks after drift

def test_production_opaque_fingerprint_includes_mutable_pipeline_outputs():
    p=ROOT/'deploy/staging/forecast-consistency-release/preflight_readonly.py'
    tree=ast.parse(p.read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='fingerprints')
    code=ast.unparse(fn)
    assert 'data/reports/next24h_forecast.csv'in code and 'data/reports/next24h_forecast_provenance.json'in code
    assert 'sha(json.dumps(values, sort_keys=True).encode())'in code
    # Same static files/services, a legitimate output update still changes hash.
    digest=lambda values:hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()
    old={'nginx':'fixed','model':'fixed','forecast.csv':'old'};new=dict(old,**{'forecast.csv':'new'})
    assert digest(old)!=digest(new)

def test_store_fingerprint_includes_new_releases_and_current():
    source=(ROOT/'deploy/staging/operational-capture-helper-release-v2/preflight.py').read_bytes()
    tree=ast.parse(source);fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='store_snapshot')
    text=ast.unparse(fn)
    assert "result['releases'][path.name]"in text and "result['current']"in text and 'OP.validate'in text
    assert 'sha(json.dumps(result, sort_keys=True).encode())'in text

def test_baseline_is_install_time_not_natural_run_snapshot():
    tree=ast.parse((V2/'transaction.py').read_bytes());apply=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='apply')
    text=ast.unparse(apply);assert "'baseline': before"in text and "save(r, 'APPLIED')"in text
    acceptance=ast.unparse(ast.parse((V3/'acceptance.py').read_bytes()))
    assert "same({k: v for k, v in record['baseline'].items() if k not in {'venv', 'runtime'}}, baseline_preservation())"in acceptance

def test_candidate_has_no_io_network_or_mutation_and_python39():
    tree=ast.parse(CANDIDATE.read_bytes(),feature_version=(3,9))
    assert not any(isinstance(n,(ast.Import,ast.ImportFrom))for n in ast.walk(tree))
    allowed={'need','type','set','tuple','preservation_differences'}
    for node in ast.walk(tree):
        if isinstance(node,ast.Call):assert isinstance(node.func,ast.Name)and node.func.id in allowed or isinstance(node.func,ast.Attribute)and node.func.attr=='upper'
