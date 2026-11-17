import ast
from pathlib import Path
import runpy
ROOT=Path(__file__).parents[1]
SCRIPT=ROOT/'deploy/staging/next24-review/inspect-prefect-recovery.py'

def test_prefect_state_history_uses_existing_api_route():
    source=SCRIPT.read_text();ast.parse(source)
    assert "request('/flow_run_states/?'+urllib.parse.urlencode({'flow_run_id':rid}))" in source
    assert "'/flow_runs/'+rid+'/states'" not in source

def test_partial_core_evidence_is_preserved_before_optional_history():
    source=SCRIPT.read_text()
    assert source.index('PARTIAL.update(out)',source.index("out['data']"))<source.index("states=request(")
    assert "PARTIAL.update(error_type=" in source
    module=runpy.run_path(str(SCRIPT))
    assert module['PARTIAL']=={}
