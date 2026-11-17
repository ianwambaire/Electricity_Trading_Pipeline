"""Synthetic, local-only publication diagnostic coverage. Never SSH."""
import ast
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import shared.forecast_publication as contract
from test_forecast_publication import fixture,encoded,ISSUE,NOW

ROOT=Path(__file__).resolve().parents[1];DIR=ROOT/'deploy/staging/forecast-consistency-release'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
D=load('publication_inspection',DIR/'publication_diagnostic.py')
R=load('publication_runner',DIR/'run_publication_diagnostic.py')
B=load('publication_core',DIR/'preflight_readonly.py')


def context(bundle=None):
    raw,digest=encoded(bundle or fixture());target='releases/'+digest
    base={'PUBLICATION':Path('/synthetic'), 'publication_metadata':lambda:({},True),
          'os':SimpleNamespace(readlink=lambda p:target),'re':B.re,
          'read':lambda path,limit:raw,'PublicationInspectionError':B.PublicationInspectionError}
    c=vars(contract).copy();c['validate']=lambda raw,h:contract.validate(raw,h,NOW)
    return base,c


@pytest.mark.parametrize('state',['VALID','EXPIRED','INVALID'])
def test_contract_classification_and_no_feature_output(state):
    bundle=fixture()
    if state=='INVALID':bundle['forecasts'].pop()
    b,c=context(bundle)
    if state=='EXPIRED':c['validate']=lambda raw,h:contract.validate(raw,h,ISSUE+dt.timedelta(hours=4))
    result=D.validate_report(D.inspect(b,c))
    assert result['publication_state']==state and result['effective_candidate_access']=='UNVERIFIED'
    assert result['prediction_count']==(0 if state=='INVALID' else 24)
    assert 'feature' not in json.dumps(result) and 'forecasts' not in result


@pytest.mark.parametrize('cause,state',[('MISSING_PATH','MISSING'),('PERMISSION_DENIED','UNVERIFIED'),('IO_ERROR','UNVERIFIED'),('POINTER_ESCAPE','INVALID'),('HASH_MISMATCH','INVALID')])
def test_sanitized_metadata_failure(cause,state):
    b,c=context()
    def fail():raise B.PublicationInspectionError('ROOT',cause)
    b['publication_metadata']=fail
    result=D.validate_report(D.inspect(b,c));assert result['publication_state']==state and result['cause']==cause


def test_pointer_change_is_not_followed():
    b,c=context();calls=iter(['releases/'+'0'*64,'releases/'+'1'*64])
    b['os']=SimpleNamespace(readlink=lambda p:next(calls))
    b['read']=lambda *a:pytest.fail('Changed target must not be read')
    result=D.validate_report(D.inspect(b,c));assert result['cause']=='POINTER_DRIFT'


@pytest.mark.parametrize('field,value',[('cause','PRIVATE_SENTINEL'),('effective_candidate_access','PASS'),('publication_state','PASS'),('prediction_count',99)])
def test_report_rejects_unexpected_output(field,value):
    b,c=context();result=D.inspect(b,c);result[field]=value
    with pytest.raises(ValueError):D.validate_report(result)


def test_manifest_closure_and_assembled_hash():
    m=json.loads((DIR/'PUBLICATION-DIAGNOSTIC.json').read_bytes());assert set(m['artifacts'])==R.ARTIFACTS
    blobs={}
    for name,meta in m['artifacts'].items():
        raw=(ROOT/name).read_bytes();assert len(raw)==meta['bytes'] and hashlib.sha256(raw).hexdigest()==meta['sha256'];blobs[name]=raw
    assert hashlib.sha256(R.assemble(blobs)).hexdigest()==m['remote_payload_sha256']
    tree=ast.parse(R.assemble(blobs).decode());assert tree is not None
    # Only three explicit verified-source compilations. No base main()/preflight.
    text=R.assemble(blobs).decode();assert "BASE['main']" not in text


def test_missing_hash_stops_before_any_binding_or_transport(monkeypatch):
    monkeypatch.setattr(R,'namespace',lambda *a:pytest.fail('Do not load unverified helpers'))
    with pytest.raises(ValueError,match='manifest_hash'):R.verify('0'*64)


def test_diagnostic_source_is_stdlib_and_no_mutation_or_network_calls():
    tree=ast.parse((DIR/'publication_diagnostic.py').read_text(),feature_version=(3,9))
    assert [alias.name for node in tree.body if isinstance(node,ast.Import) for alias in node.names]==['json']
    text=(DIR/'publication_diagnostic.py').read_text()
    for forbidden in ('subprocess','socket','urllib','chmod','mkdir','unlink','predict(','nsenter'):
        assert forbidden not in text
