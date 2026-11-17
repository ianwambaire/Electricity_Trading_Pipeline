import json
from pathlib import Path
ROOT=Path(__file__).parents[1]

def test_proposed_schedule_is_hourly_utc_and_preserves_quality_gate():
    proposal=json.loads((ROOT/'deploy/staging/next24-review/SCHEDULE-PROPOSAL.json').read_text())
    assert proposal['status']=='PROPOSAL_ONLY_NOT_APPLIED'
    assert proposal['current']=={'cron':'0 * * * *','timezone':'UTC','concurrency_limit':None}
    assert proposal['proposed']=={'cron':'45 * * * *','timezone':'UTC','concurrency_limit':1}
    assert '3-hour issue-time freshness' in proposal['preserve']
    # Local desired configuration now mirrors the separately approved live update.
    assert 'cron: "45 * * * *"' in (ROOT/'prefect.yaml').read_text()


def test_reconciliation_is_exact_two_records_and_never_forces_or_cancels():
    proposal=json.loads((ROOT/'deploy/staging/next24-review/RECONCILIATION-PROPOSAL.json').read_text())
    assert proposal['not_authorized_now'] is True
    assert len(proposal['requests'])==2
    assert proposal['requests'][0]['path']=='/task_runs/'+proposal['required_task_id']+'/set_state'
    assert proposal['requests'][1]['path']=='/flow_runs/'+proposal['required_flow_id']+'/set_state'
    for request in proposal['requests']:
        assert request['method']=='POST'
        assert request['json']['force'] is False
        assert request['json']['state']['type']=='CRASHED'
