import json,runpy
from pathlib import Path
ROOT=Path(__file__).parents[1]
SCRIPT=ROOT/'deploy/staging/next24-review/apply-permanent-recovery.py'
M=runpy.run_path(str(SCRIPT))

def test_non_overlap_keeps_all_active_states_blocked():
    for state in ['RUNNING','PENDING','CANCELLING','PAUSED']:
        assert M['blocks']([{'state':{'type':state}}])
    for state in ['COMPLETED','FAILED','CRASHED','CANCELLED']:
        assert not M['blocks']([{'state':{'type':state}}])

def test_modern_concurrency_is_not_confused_with_legacy_null():
    result=M['dep_summary']({'concurrency_limit':None,'global_concurrency_limit':{'limit':1,'active':True,'active_slots':0,'id':'existing'},'concurrency_options':{'collision_strategy':'ENQUEUE'}})
    assert result['global_concurrency_limit']['limit']==1
    assert result['legacy_concurrency_limit'] is None
    assert result['concurrency_options']=={'collision_strategy':'ENQUEUE'}

def test_preservation_covers_collision_and_unrelated_configuration():
    base={'name':'powerflow-entsoe-pipeline','parameters':{'mode':'incremental'},'concurrency_options':None}
    assert M['static_settings'](base)==M['static_settings']({**base,'updated':'dynamic'})
    assert M['static_settings'](base)!=M['static_settings']({**base,'concurrency_options':{'collision_strategy':'CANCEL_NEW'}})

def test_payload_never_forces_cancels_or_creates_runs():
    source=SCRIPT.read_text()
    assert "'force':False" in source
    for forbidden in ['force\':True','/create_flow_run','/resume','/cancel','systemctl\',\'restart','DELETE']:
        assert forbidden not in source
    assert source.index("RESULT['stage']='stage2_preflight'")>source.index("'terminal_state_readback'")
    assert "global_limit is None" in source
