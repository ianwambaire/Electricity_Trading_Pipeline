"""Local mocked production-deployment safety checks. No SSH or production input."""
import ast
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import types

import pytest

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'deploy/staging/a03-price-recovery/final'


def load_body():
    source=(HERE/'deploy-body.py').read_text()
    tree=ast.parse(source)
    space={'Path':Path,'os':os,'stat':__import__('stat'),'json':json,
        'base64':base64,'hashlib':hashlib,'dt':__import__('datetime')}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[]),'<body>','exec'),space)
    def require(ok,reason):
        if not ok:raise RuntimeError(reason)
    space.update(require=require,digest=lambda b:hashlib.sha256(b).hexdigest())
    return space


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    s=load_body()
    parser=tmp_path/'parser.py';prices=tmp_path/'prices.csv';backup=tmp_path/'backup'
    parser.write_bytes(b'old=1\n');prices.write_bytes(b'original\n')
    new=b'new=2\n';candidate=b'original\naddition\n'
    config={'old_parser_sha256':s['digest'](parser.read_bytes()),'new_parser_sha256':s['digest'](new),
        'prices_sha256':s['digest'](prices.read_bytes()),'parser_file':base64.b64encode(new).decode(),
        'xml':base64.b64encode(b'<xml/>').decode(),'xml_sha256':s['digest'](b'<xml/>'),
        'services':{'safe':True},'routing':{'safe':True}}
    s.update(ROOT=tmp_path,PARSER=parser,PRICES=prices,BACKUP=backup,CONFIG=config,
        RESULT={'installed':[],'created':[]},read_large=lambda p:p.read_bytes(),
        strict_path=lambda *a,**k:None,sync_dir=lambda p:None,idle=lambda:None,
        snapshot_unchanged=lambda:None,availability=lambda:{'all':200},
        resources=lambda:{'disk_available_bytes':3*1024**3,'MemAvailable':1024**3},
        require_capacity=lambda x:None)
    def preflight():s['RESULT']['resources_before']=s['resources']()
    def build(raw):
        assert raw==b'original\n'
        s['RESULT']['dry_run']={'added_count':2}
        return candidate
    s.update(base_preflight=preflight,build_candidate=build)
    monkeypatch.setattr(os,'chown',lambda *a:None)
    monkeypatch.setattr(os,'fchown',lambda *a:None)
    return s


def test_success_has_verified_backups_and_only_two_installs(sandbox):
    s=sandbox;s['apply']()
    assert s['RESULT']['status']=='APPLIED'
    assert s['PARSER'].read_bytes()==b'new=2\n'
    assert s['PRICES'].read_bytes()==b'original\naddition\n'
    assert (s['BACKUP']/'parser.original.py').read_bytes()==b'old=1\n'
    assert (s['BACKUP']/'prices.original.csv').read_bytes()==b'original\n'
    assert s['RESULT']['installed']==[str(s['PARSER']),str(s['PRICES'])]
    assert (s['BACKUP'].stat().st_mode & 0o777)==0o700
    assert all((p.stat().st_mode & 0o777)==0o600 for p in s['BACKUP'].iterdir())


@pytest.mark.parametrize('failed_guard',['active_prefect_run','active_ingestion_or_pipeline_process','available_ram_below_768_mib','disk_below_2_gib','schedule_window_under_ten_minutes','service_identity_drift','routing_drift'])
def test_failed_preflight_makes_no_writes(sandbox,failed_guard):
    s=sandbox
    def fail():raise RuntimeError(failed_guard)
    s['base_preflight']=fail
    with pytest.raises(RuntimeError,match=failed_guard):s['apply']()
    assert not s['BACKUP'].exists()
    assert s['RESULT']['created']==[]
    assert s['PARSER'].read_bytes()==b'old=1\n'
    assert s['PRICES'].read_bytes()==b'original\n'


@pytest.mark.parametrize('which',['parser','prices'])
def test_drift_stops_before_backup_creation(sandbox,which):
    s=sandbox;s['PARSER' if which=='parser' else 'PRICES'].write_bytes(b'drift')
    with pytest.raises(RuntimeError,match='drift'):s['apply']()
    assert not s['BACKUP'].exists()


def test_bad_candidate_makes_no_writes(sandbox):
    s=sandbox
    def fail(source):raise RuntimeError('existing_value_conflict')
    s['build_candidate']=fail
    with pytest.raises(RuntimeError,match='existing_value_conflict'):s['apply']()
    assert not s['BACKUP'].exists()


def test_backup_destination_never_overwritten(sandbox):
    s=sandbox;s['BACKUP'].mkdir()
    with pytest.raises(RuntimeError,match='destination_conflict'):s['apply']()
    assert not list(s['BACKUP'].iterdir())


def test_partial_second_install_has_no_automatic_rollback(sandbox):
    s=sandbox;real=s['install_one']
    def install(path,*args):
        if path==s['PRICES']:raise RuntimeError('second_install_failed')
        return real(path,*args)
    s['install_one']=install
    with pytest.raises(RuntimeError,match='second_install_failed'):s['apply']()
    assert s['PARSER'].read_bytes()==b'new=2\n'
    assert s['PRICES'].read_bytes()==b'original\n'
    assert s['RESULT']['installed']==[str(s['PARSER'])]
    assert (s['BACKUP']/'prices.original.csv').exists()


def test_atomic_replace_checks_drift_again(sandbox):
    s=sandbox;target=s['PARSER'];expected=s['CONFIG']['old_parser_sha256']
    s['idle']=lambda:target.write_bytes(b'changed_during_prepare')
    with pytest.raises(RuntimeError,match='source_drift_before_replace'):
        s['install_one'](target,b'new=2\n',expected,0o644)
    assert target.read_bytes()==b'changed_during_prepare'


def test_rollback_exact_candidates_only(sandbox):
    s=sandbox;s['apply']();s['rollback']()
    assert s['PARSER'].read_bytes()==b'old=1\n'
    assert s['PRICES'].read_bytes()==b'original\n'
    assert s['RESULT']['status']=='ROLLED_BACK'


def test_rollback_rejects_new_ingested_data(sandbox):
    s=sandbox;s['apply']();s['PRICES'].write_bytes(b'new scheduled source')
    with pytest.raises(RuntimeError,match='rollback_price_drift'):s['rollback']()
    assert s['PRICES'].read_bytes()==b'new scheduled source'


def test_system_python_39_syntax_and_no_remote_mutation_in_preflight():
    source=(HERE/'preflight-payload.py').read_text()
    ast.parse(source,feature_version=(3,9))
    payload=(HERE/'deploy-payload.py').read_text().replace('__ACTION__',repr('apply'))
    ast.parse(payload,feature_version=(3,9))
    assert 'os.replace(' not in source
    assert '.mkdir(' not in source
    assert "'--mode'" not in source


def test_bounded_wrapper_has_strict_ssh_and_no_retry():
    source=(HERE/'run-deployment.py').read_text()
    assert 'StrictHostKeyChecking=yes' in source
    assert 'ConnectionAttempts=1' in source
    assert '120s /usr/bin/python3 -I -S -B -' in source
    assert "SUPERVISOR_SHA='9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40'" in source
    assert 'subprocess.run' in source
    tree=ast.parse(source)
    assert not any(isinstance(n,ast.While) for n in ast.walk(tree))


def load_payload_definitions():
    text=(HERE/'deploy-payload.py').read_text().replace('__ACTION__',repr('apply'))
    tree=ast.parse(text)
    # No final try/apply dispatch. Definitions/imports/constants only.
    nodes=[]
    for node in tree.body:
        if isinstance(node,ast.Try):break
        if isinstance(node,ast.Expr) and not isinstance(node.value,ast.Constant):continue
        nodes.append(node)
    namespace={}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<payload_test>','exec'),namespace)
    return namespace


def test_independent_process_and_prefect_guards():
    s=load_payload_definitions()
    s['deployment_configuration']=lambda:{'active_slots':0}
    s['api']=lambda path,body:[]
    s['no_ingestion']=lambda:(_ for _ in ()).throw(RuntimeError('active_ingestion_or_pipeline_process'))
    when=__import__('datetime').datetime(2026,11,1,17,0,tzinfo=__import__('datetime').timezone.utc)
    with pytest.raises(RuntimeError,match='active_ingestion'):s['idle'](when)
    s['api']=lambda path,body:[{'state':{'type':'RUNNING'}}]
    with pytest.raises(RuntimeError,match='active_prefect_run'):s['idle'](when)


def test_schedule_window_and_capacity_are_enforced():
    s=load_payload_definitions()
    s['deployment_configuration']=lambda:{'active_slots':0}
    when=__import__('datetime').datetime(2026,11,1,17,40,tzinfo=__import__('datetime').timezone.utc)
    with pytest.raises(RuntimeError,match='ten_minutes'):s['idle'](when)
    with pytest.raises(RuntimeError,match='ram'):s['require_capacity']({'MemAvailable':100,'disk_available_bytes':3*1024**3})
    with pytest.raises(RuntimeError,match='disk'):s['require_capacity']({'MemAvailable':1024**3,'disk_available_bytes':100})


def test_native_31_feature_helper_receives_repaired_price_history(tmp_path):
    import subprocess,sys
    import pandas as pd
    s=load_payload_definitions()
    config=s['CONFIG']
    # Actual verified XML is embedded market data, not credentials or a database.
    rawxml=base64.b64decode(config['xml'])
    from ingestion.fetch_entsoe_data import parse_price_observations
    decoded=parse_price_observations(rawxml.decode())
    index=pd.date_range('2026-10-24T00:00Z','2026-10-31T12:45Z',freq='15min')
    values=pd.DataFrame({'price_eur_mwh':100.0,'source_resolution':'PT15M'},index=index)
    values.index.name='timestamp'
    matching=index.intersection(decoded.index)
    values.loc[matching,'price_eur_mwh']=decoded.loc[matching,'price_eur_mwh']
    values=values.drop(pd.to_datetime(config['timestamps'],utc=True))
    source=values.reset_index().to_csv(index=False).encode()
    child=config['candidate_child'].replace('/home/ec2-user/Electricity_Trading_Pipeline',str(ROOT))
    result=subprocess.run([sys.executable,'-I','-B','-c',child],
        input=json.dumps({'source':base64.b64encode(source).decode(),'xml':config['xml']}).encode(),
        capture_output=True,timeout=30,env={'PATH':'/usr/bin:/bin','HOME':str(tmp_path),'PYTHONDONTWRITEBYTECODE':'1'})
    assert result.returncode==0,result.stderr.decode()
    report=json.loads(result.stdout)
    assert report['report']['historical_price_feature_contract']=='PASS'
    assert report['additions']==config['additions']
    candidate=base64.b64decode(report['candidate'])
    assert all(line in candidate.splitlines(keepends=True) for line in source.splitlines(keepends=True))
    repaired=pd.read_csv(__import__('io').BytesIO(candidate))
    assert pd.to_datetime(repaired.timestamp,utc=True).is_monotonic_increasing
    from ingestion.incremental_utils import latest_stored_timestamp
    path=tmp_path/'candidate.csv';path.write_bytes(candidate)
    assert latest_stored_timestamp(path)==pd.Timestamp('2026-10-31T12:45Z')


def test_xml_binding_rejects_mismatch_before_subprocess():
    s=load_body();s.update(CONFIG={'xml':base64.b64encode(b'bad').decode(),'xml_sha256':'0'*64})
    with pytest.raises(RuntimeError,match='xml_hash_mismatch'):s['build_candidate'](b'source')


def test_manifest_verification_rejects_bad_hash_before_network(tmp_path):
    path=HERE/'run-deployment.py'
    spec=importlib.util.spec_from_file_location('a03_runner',path)
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    runner.HERE=tmp_path/'final';runner.HERE.mkdir()
    (tmp_path/'MANIFEST.json').write_text('{}')
    with pytest.raises(ValueError,match='manifest_hash_mismatch'):runner.verify('0'*64)


def test_manifest_verification_rejects_artifact_drift(tmp_path):
    path=HERE/'run-deployment.py'
    spec=importlib.util.spec_from_file_location('a03_runner_drift',path)
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    runner.ROOT=tmp_path;runner.HERE=tmp_path/'package/final';runner.HERE.mkdir(parents=True)
    (tmp_path/'artifact').write_bytes(b'tampered')
    manifest=json.dumps({'schema_version':1,'artifacts':[{'path':'artifact','sha256':'0'*64}]}).encode()
    (runner.HERE.parent/'MANIFEST.json').write_bytes(manifest)
    with pytest.raises(ValueError,match='artifact_hash_mismatch'):runner.verify(hashlib.sha256(manifest).hexdigest())


def test_receipt_creation_failure_never_replaces_sources(sandbox):
    s=sandbox;real=s['private_write']
    def write(path,*args):
        if path.name=='receipt.json':raise RuntimeError('receipt_write_failure')
        return real(path,*args)
    s['private_write']=write
    with pytest.raises(RuntimeError,match='receipt_write_failure'):s['apply']()
    assert s['RESULT']['installed']==[]
    assert s['PARSER'].read_bytes()==b'old=1\n'
    assert s['PRICES'].read_bytes()==b'original\n'
    assert (s['BACKUP']/'prices.original.csv').exists()
