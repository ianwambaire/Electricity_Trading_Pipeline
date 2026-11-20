"""Regression for Prefect dispatching a scheduled run 0.297 seconds early."""
import datetime as dt
import hashlib

import pytest

from shared import operational_evidence as contract
from shared.operational_scheduling import latest_natural, natural
from test_operational_evidence import fixture, NOW


@pytest.mark.parametrize("early_seconds", [0, 0.297153, 1])
def test_accept_bounded_early_start_without_changing_timestamps(early_seconds):
    evidence = fixture()
    execution = evidence["execution"]
    scheduled = contract.timestamp(execution["scheduled_at"])
    started = scheduled - dt.timedelta(seconds=early_seconds)
    execution["started_at"] = started.isoformat()
    raw = contract.canonical(evidence)
    checked = contract.validate(raw, hashlib.sha256(raw).hexdigest(), NOW)
    assert checked["execution"]["started_at"] == started.isoformat()

    flow = dict(
        id=execution["flow_run_id"],
        deployment_id=execution["deployment_id"],
        auto_scheduled=True,
        expected_start_time=execution["scheduled_at"],
        start_time=execution["started_at"],
        end_time=execution["completed_at"],
        state={"type": "COMPLETED"},
    )
    assert natural(flow, execution["deployment_id"], NOW)[0] == started
    assert latest_natural([flow], execution["deployment_id"], NOW) is flow


@pytest.mark.parametrize("case", ["too_early", "early_completion", "future_start"])
def test_reject_invalid_timeline(case):
    evidence = fixture()
    execution = evidence["execution"]
    scheduled = contract.timestamp(execution["scheduled_at"])
    if case == "too_early":
        execution["started_at"] = (scheduled - dt.timedelta(seconds=1.000001)).isoformat()
    elif case == "early_completion":
        execution["started_at"] = (scheduled - dt.timedelta(seconds=0.5)).isoformat()
        execution["completed_at"] = (scheduled - dt.timedelta(seconds=0.1)).isoformat()
    else:
        execution["started_at"] = (NOW + dt.timedelta(seconds=1)).isoformat()
    raw = contract.canonical(evidence)
    with pytest.raises(contract.InvalidEvidence, match="^TIMELINE$"):
        contract.validate(raw, hashlib.sha256(raw).hexdigest(), NOW)

    flow = dict(
        id=execution["flow_run_id"],
        deployment_id=execution["deployment_id"],
        auto_scheduled=True,
        expected_start_time=execution["scheduled_at"],
        start_time=execution["started_at"],
        end_time=execution["completed_at"],
        state={"type": "COMPLETED"},
    )
    with pytest.raises(contract.InvalidEvidence, match="^TIMELINE$"):
        natural(flow, execution["deployment_id"], NOW)


def test_production_receipt_adapter_uses_scheduler_tolerance(writer):
    reader = writer.load_evidence_reader()
    assert reader.__globals__["natural"] is natural


def test_latest_run_is_not_replaced_by_older_completed_run():
    evidence = fixture()
    execution = evidence["execution"]
    flow = dict(
        id=execution["flow_run_id"],
        deployment_id=execution["deployment_id"],
        auto_scheduled=True,
        expected_start_time=execution["scheduled_at"],
        start_time=None,
        end_time=None,
        state={"type": "RUNNING"},
    )
    with pytest.raises(contract.InvalidEvidence, match="^NOT_TERMINAL$"):
        latest_natural([flow], execution["deployment_id"], NOW)
