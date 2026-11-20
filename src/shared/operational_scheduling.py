"""Scheduler dispatch tolerance for the production evidence projection."""
from types import FunctionType

from . import operational_evidence_producer as producer
from .operational_evidence import (
    SCHEDULER_START_TOLERANCE,
    identifier,
    require,
    timestamp,
)


def natural(flow, expected_deployment, observed_at):
    identifier(expected_deployment)
    identifier(flow["id"])
    require(
        flow["deployment_id"] == expected_deployment
        and flow.get("auto_scheduled") is True,
        "NOT_NATURAL",
    )
    scheduled = timestamp(flow["expected_start_time"])
    require(
        scheduled.minute == 45
        and scheduled.second == scheduled.microsecond == 0
        and scheduled <= observed_at,
        "SCHEDULE",
    )
    require(
        flow["state"]["type"] in {"COMPLETED", "FAILED", "CANCELLED", "CRASHED"},
        "NOT_TERMINAL",
    )
    start = timestamp(flow["start_time"])
    end = timestamp(flow["end_time"])
    require(
        scheduled - SCHEDULER_START_TOLERANCE <= start <= end <= observed_at
        and scheduled <= end,
        "TIMELINE",
    )
    return start, end


# Preserve the existing latest-run selection and prohibit falling back to an
# older completed run when the latest scheduled run is still pending.
_latest_natural = FunctionType(
    producer._latest_natural.__code__,
    dict(producer._latest_natural.__globals__, natural=natural),
)
latest_natural = FunctionType(
    producer.latest_natural.__code__,
    dict(producer.latest_natural.__globals__, _latest_natural=_latest_natural),
)
