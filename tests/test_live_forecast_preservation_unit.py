"""Offline unit tests for the preservation reporting candidate."""
import ast
from pathlib import Path

import pytest

SOURCE = (
    Path(__file__).parents[1]
    / "deploy/staging/live-forecast-preservation-review-v1/preservation.py"
)

COMPONENTS = (
    "production", "forecast", "store", "helper",
    "policy", "environment", "nginx",
)


class PreservationError(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise PreservationError(code)


def load_candidate():
    tree = ast.parse(SOURCE.read_bytes(), feature_version=(3, 9))
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        for node in ast.walk(tree)
    )
    namespace = {"need": need}
    exec(compile(tree, str(SOURCE), "exec"), namespace)
    return namespace


def baseline():
    return {key: "original" for key in COMPONENTS}


def test_unchanged_state_passes():
    candidate = load_candidate()
    before = baseline()
    after = before.copy()

    assert candidate["same"](before, after) is None
    assert before == after


@pytest.mark.parametrize("component", COMPONENTS)
def test_component_drift_fails_closed(component):
    candidate = load_candidate()
    before = baseline()
    after = before.copy()
    after[component] = "PRIVATE_SECRET_VALUE"

    with pytest.raises(
        PreservationError,
        match=f"^PRESERVATION_DRIFT_{component.upper()}$",
    ):
        candidate["same"](before, after)


@pytest.mark.parametrize("change", ["missing", "extra", "invalid"])
def test_invalid_schema_fails_closed(change):
    candidate = load_candidate()
    before = baseline()
    after = before.copy()

    if change == "missing":
        after.pop("forecast")
    elif change == "extra":
        after["unexpected"] = "value"
    else:
        after = []

    with pytest.raises(
        PreservationError, match="^PRESERVATION_SCHEMA$"
    ):
        candidate["same"](before, after)


def test_multiple_differences_have_deterministic_order():
    candidate = load_candidate()
    before = baseline()
    after = before.copy()
    after["nginx"] = "changed"
    after["forecast"] = "changed"

    assert candidate["preservation_differences"](
        before, after
    ) == ("forecast", "nginx")
