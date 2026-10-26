"""No AWS, listener, real accounts or production forecast data."""
import importlib.util
import json
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

spec=importlib.util.spec_from_file_location('smoke_web_release',Path(__file__).parents[1]/'scripts/smoke_web_release.py')
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)


def test_candidate_routing_api_auth_and_readiness(tmp_path):
    (tmp_path/'index.html').write_text('<html><div id="root"></div></html>')
    (tmp_path/'build-config.json').write_text(json.dumps(dict(apiBase='/api',releaseEligible=True,origin='https://candidate.example.test')))
    result=smoke.run(tmp_path)
    assert result['pages']==7 and result['analyst_denials']==7 and not result['production_deployed']


def test_local_build_not_silently_treated_as_release(tmp_path):
    (tmp_path/'build-config.json').write_text(json.dumps(dict(apiBase='/api',releaseEligible=False)))
    with pytest.raises(ValueError):smoke.run(tmp_path)


def test_existing_pages_and_other_apis_work_when_next24_is_unavailable(tmp_path):
    (tmp_path/'index.html').write_text('<html><div id="root"></div></html>')
    (tmp_path/'build-config.json').write_text(json.dumps(dict(apiBase='/api',releaseEligible=True,origin='https://candidate.example.test')))
    result=smoke.run(tmp_path,next24_available=False)
    assert result['pages']==7 and result['next24_available'] is False
