"""Shared authored specification data for new workflow-run fixtures.

These helpers make a deliberately small, complete specification for mechanics
tests.  They are fixture data rather than a stand-in for model-generated plans.
Malformed-input tests should keep constructing their malformed documents
directly, so their rejection remains attributable to the runtime contract.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


def authored_specification(goal: str, *, step_count: int = 1) -> dict[str, Any]:
    """Return the complete authored specification used by test-only new runs."""
    if step_count < 1:
        raise ValueError("an authored specification needs at least one deliverable")
    return {
        "version": 1,
        "goal": goal,
        "deliverables": [
            {
                "id": f"D{index}",
                "description": "one outcome",
                "requirements": [f"FR{index}"],
            }
            for index in range(1, step_count + 1)
        ],
        "functional_requirements": [
            {
                "id": f"FR{index}",
                "description": "outcome",
                "acceptance": ["observable criterion"],
            }
            for index in range(1, step_count + 1)
        ],
        "nfrs": [
            {
                "id": "NFR1",
                "description": "test-local execution constraint",
                "acceptance": ["checks pass within fixture workspace"],
                "scope": "all",
            }
        ],
        "assumptions": [],
        "out_of_scope": [],
        "unresolved": [],
    }


def _step_contract(index: int) -> dict[str, Any]:
    return {
        "role": "deliverable",
        "deliverables": [f"D{index}"],
        "requirements": [f"FR{index}"],
        "verifies": [f"FR{index}", "NFR1"],
        "ready_when": ["all declared suppliers accepted"],
        "done_when": ["declared evidence/checks pass"],
    }


def specified(workflow: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-copy a valid authored workflow and add its required v2 traceability."""
    document = deepcopy(dict(workflow))
    if document.get("version") == 2 and "specification" in document:
        return document
    goal = document.get("goal")
    steps = document.get("steps")
    if not isinstance(goal, str) or not isinstance(steps, list):
        raise ValueError("specified() requires a valid authored workflow fixture")

    document["version"] = 2
    document["specification"] = authored_specification(goal, step_count=len(steps))
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError("specified() requires object workflow steps")
        step["contract"] = _step_contract(index)
    return document


def planning_fixture(
    plan: Mapping[str, Any], bindings: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return authored prompt specification and copied bindings with contracts."""
    goal = plan.get("goal")
    if not isinstance(goal, str):
        raise ValueError("planning fixture needs a plan goal")
    plan_steps = plan.get("steps")
    if not isinstance(plan_steps, list):
        raise ValueError("planning fixture needs plan steps")
    augmented_bindings = deepcopy(dict(bindings))
    for index, step in enumerate(plan_steps, start=1):
        if not isinstance(step, Mapping) or not isinstance(step.get("id"), str):
            raise ValueError("planning fixture plan steps need IDs")
        binding = augmented_bindings.get(step["id"])
        if isinstance(binding, dict):
            binding["contract"] = _step_contract(index)
    # Backchain's optional _initial_evidence map remains untouched because it
    # is not an execution binding and has no step contract.
    return authored_specification(goal, step_count=len(plan_steps)), augmented_bindings
