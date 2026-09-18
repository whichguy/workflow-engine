"""Focused contracts for specification v1 and runtime step traceability."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from specification import (  # noqa: E402
    SpecificationError,
    step_context,
    validate_contracts,
    validate_specification,
)


def _specification(goal: str = "Ship both independently verifiable outcomes") -> dict:
    return {
        "version": 1,
        "goal": goal,
        "deliverables": [
            {
                "id": "D1",
                "description": "First independently verifiable outcome",
                "requirements": ["FR1"],
            },
            {
                "id": "D2",
                "description": "Second independently verifiable outcome",
                "requirements": ["FR2"],
            },
        ],
        "functional_requirements": [
            {
                "id": "FR1",
                "description": "First behavior exists",
                "acceptance": ["The first behavior has observable evidence."],
            },
            {
                "id": "FR2",
                "description": "Second behavior exists",
                "acceptance": ["The second behavior has observable evidence."],
            },
        ],
        "nfrs": [
            {
                "id": "NFR-GLOBAL",
                "description": "Both outcomes retain their regression boundary",
                "acceptance": ["Relevant checks pass for each outcome."],
                "scope": "all",
            },
            {
                "id": "NFR-D1",
                "description": "The first outcome has its focused quality check",
                "acceptance": ["The focused D1 quality check passes."],
                "scope": ["D1"],
            },
        ],
        "assumptions": ["The test fixture has no external dependency."],
        "out_of_scope": ["Production rollout is exercised by a host-level test."],
        "unresolved": [],
    }


def _contract(
    role: str,
    deliverables: list[str],
    *,
    requirements: list[str] | None = None,
    verifies: list[str] | None = None,
    shared_reason: str | None = None,
) -> dict:
    contract = {
        "role": role,
        "deliverables": list(deliverables),
        "requirements": list(requirements or []),
        "verifies": list(verifies or []),
        "ready_when": ["Declared dependencies have accepted receipts."],
        "done_when": ["Declared outputs and checks provide evidence."],
    }
    if role != "deliverable":
        contract["shared_reason"] = shared_reason or f"{role} serves the declared scope."
    elif shared_reason is not None:
        contract["shared_reason"] = shared_reason
    return contract


def _valid_steps() -> list[dict]:
    return [
        {
            "id": "setup",
            "needs": [],
            "contract": _contract("setup", ["D1", "D2"]),
        },
        {
            "id": "impl-d1",
            "needs": ["setup"],
            "contract": _contract(
                "deliverable", ["D1"], requirements=["FR1"], verifies=["FR1"]
            ),
        },
        {
            "id": "impl-d2",
            "needs": ["setup"],
            "contract": _contract(
                "deliverable", ["D2"], requirements=["FR2"], verifies=["FR2"]
            ),
        },
        {
            "id": "release",
            "needs": ["impl-d1", "impl-d2"],
            "contract": _contract("release", ["D1", "D2"]),
        },
        {
            "id": "smoke-d1",
            "needs": ["release"],
            "contract": _contract(
                "verification", ["D1"], verifies=["NFR-GLOBAL", "NFR-D1"]
            ),
        },
        {
            "id": "smoke-d2",
            "needs": ["release"],
            "contract": _contract("verification", ["D2"], verifies=["NFR-GLOBAL"]),
        },
    ]


class SpecificationContractTests(unittest.TestCase):
    maxDiff = None

    def test_setup_two_deliverables_release_and_post_release_smoke_are_valid(self) -> None:
        spec = validate_specification(_specification())
        coverage = validate_contracts(spec, _valid_steps())

        self.assertEqual(
            coverage["FR1"],
            {
                "scope": ["D1"],
                "implemented_by": ["impl-d1"],
                "verified_by": {"D1": ["impl-d1"]},
            },
        )
        self.assertEqual(coverage["NFR-GLOBAL"]["scope"], ["D1", "D2"])
        self.assertEqual(
            coverage["NFR-GLOBAL"]["verified_by"],
            {"D1": ["smoke-d1"], "D2": ["smoke-d2"]},
        )

    def test_multifan_join_may_supply_release_transitively(self) -> None:
        steps = _valid_steps()
        steps.insert(
            3,
            {
                "id": "integration",
                "needs": ["impl-d1", "impl-d2"],
                "contract": _contract("integration", ["D1", "D2"]),
            },
        )
        next(step for step in steps if step["id"] == "release")["needs"] = ["integration"]

        coverage = validate_contracts(_specification(), steps)

        self.assertEqual(coverage["FR2"]["implemented_by"], ["impl-d2"])

    def test_terminal_delivery_leaves_do_not_need_a_synthetic_release(self) -> None:
        spec = _specification()
        spec["nfrs"] = [spec["nfrs"][0]]
        steps = _valid_steps()[:3]
        steps[1]["contract"]["verifies"].append("NFR-GLOBAL")
        steps[2]["contract"]["verifies"].append("NFR-GLOBAL")

        coverage = validate_contracts(spec, steps)

        self.assertEqual(
            coverage["NFR-GLOBAL"]["verified_by"],
            {"D1": ["impl-d1"], "D2": ["impl-d2"]},
        )

    def test_unknown_and_duplicate_references_are_rejected(self) -> None:
        cases: list[tuple[str, dict, list[dict]]] = []

        bad_spec = _specification()
        bad_spec["deliverables"][0]["requirements"] = ["MISSING"]
        cases.append(("unknown spec FR", bad_spec, _valid_steps()))

        duplicate_spec = _specification()
        duplicate_spec["deliverables"][0]["requirements"] = ["FR1", "FR1"]
        cases.append(("duplicate spec FR", duplicate_spec, _valid_steps()))

        unknown_step_ref = _valid_steps()
        unknown_step_ref[1]["needs"] = ["not-a-step"]
        cases.append(("unknown needs", _specification(), unknown_step_ref))

        duplicate_contract_ref = _valid_steps()
        duplicate_contract_ref[4]["contract"]["verifies"] = ["NFR-D1", "NFR-D1"]
        cases.append(("duplicate verifies", _specification(), duplicate_contract_ref))

        unknown_contract_ref = _valid_steps()
        unknown_contract_ref[1]["contract"]["deliverables"] = ["D-UNKNOWN"]
        cases.append(("unknown contract deliverable", _specification(), unknown_contract_ref))

        for name, spec, steps in cases:
            with self.subTest(name=name):
                with self.assertRaises(SpecificationError):
                    validate_contracts(spec, steps)

    def test_missing_fr_and_scoped_nfr_coverage_are_rejected(self) -> None:
        missing_fr = _valid_steps()
        missing_fr[1]["contract"]["verifies"] = []
        with self.assertRaisesRegex(SpecificationError, "FR1.*no verifier"):
            validate_contracts(_specification(), missing_fr)

        missing_global_nfr = _valid_steps()
        missing_global_nfr[5]["contract"]["verifies"] = []
        with self.assertRaisesRegex(SpecificationError, "NFR-GLOBAL.*D2"):
            validate_contracts(_specification(), missing_global_nfr)

        missing_scoped_nfr = _valid_steps()
        scoped_spec = _specification()
        scoped_spec["nfrs"][1]["scope"] = ["D1", "D2"]
        with self.assertRaisesRegex(SpecificationError, "NFR-D1.*D2"):
            validate_contracts(scoped_spec, missing_scoped_nfr)

    def test_setup_may_claim_only_an_explicit_readiness_nfr(self) -> None:
        outcome_claim = _valid_steps()
        outcome_claim[0]["contract"]["verifies"] = ["NFR-GLOBAL"]
        with self.assertRaisesRegex(SpecificationError, "only when verification_stage"):
            validate_contracts(_specification(), outcome_claim)

        readiness_spec = _specification()
        readiness_spec["nfrs"][0]["verification_stage"] = "readiness"
        readiness_claim = _valid_steps()
        readiness_claim[0]["contract"]["verifies"] = ["NFR-GLOBAL"]

        coverage = validate_contracts(readiness_spec, readiness_claim)

        self.assertIn("setup", coverage["NFR-GLOBAL"]["verified_by"]["D1"])
        self.assertIn("setup", coverage["NFR-GLOBAL"]["verified_by"]["D2"])

    def test_deliverable_role_cannot_coarsen_multiple_outcomes(self) -> None:
        steps = _valid_steps()
        steps[1]["contract"]["deliverables"] = ["D1", "D2"]
        steps[1]["contract"]["requirements"] = ["FR1", "FR2"]

        with self.assertRaisesRegex(SpecificationError, "exactly one deliverable"):
            validate_contracts(_specification(), steps)

    def test_setup_and_release_missing_dependency_guards_are_rejected(self) -> None:
        setup_escape = _valid_steps()
        setup_escape[1]["needs"] = []
        with self.assertRaisesRegex(SpecificationError, "setup step.*ancestor"):
            validate_contracts(_specification(), setup_escape)

        release_escape = _valid_steps()
        release_escape[3]["needs"] = ["impl-d1"]
        with self.assertRaisesRegex(SpecificationError, "release step.*impl-d2"):
            validate_contracts(_specification(), release_escape)

    def test_early_fr_verification_is_rejected(self) -> None:
        steps = _valid_steps()
        steps[1]["contract"]["verifies"] = []
        steps.insert(
            1,
            {
                "id": "early-fr-check",
                "needs": ["setup"],
                "contract": _contract("verification", ["D1"], verifies=["FR1"]),
            },
        )

        with self.assertRaisesRegex(SpecificationError, "FR verifier.*not an implementer"):
            validate_contracts(_specification(), steps)

    def test_exact_goal_unknown_fields_and_strict_text_types_are_rejected(self) -> None:
        exact_goal = " Preserve every original byte \n"
        spec = _specification(exact_goal)
        normalised = validate_specification(spec, goal=exact_goal)
        self.assertEqual(normalised["goal"], exact_goal)
        self.assertEqual(normalised["assumptions"], spec["assumptions"])
        with self.assertRaisesRegex(SpecificationError, "exactly match"):
            validate_specification(spec, goal="Preserve every original byte")

        cases = []
        bool_version = _specification()
        bool_version["version"] = True
        cases.append(bool_version)
        unknown_field = _specification()
        unknown_field["unexpected"] = "no"
        cases.append(unknown_field)
        empty_deliverable_requirements = _specification()
        empty_deliverable_requirements["deliverables"][0]["requirements"] = []
        cases.append(empty_deliverable_requirements)
        empty_nfr_acceptance = _specification()
        empty_nfr_acceptance["nfrs"][0]["acceptance"] = []
        cases.append(empty_nfr_acceptance)
        nontext_assumption = _specification()
        nontext_assumption["assumptions"] = [1]
        cases.append(nontext_assumption)
        unresolved = _specification()
        unresolved["unresolved"] = ["Need an external choice"]
        cases.append(unresolved)

        for raw in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(SpecificationError):
                    validate_specification(raw)

    def test_nfr_verification_stage_is_strict_and_omission_is_preserved(self) -> None:
        normalised = validate_specification(_specification())
        self.assertNotIn("verification_stage", normalised["nfrs"][0])

        unknown_stage = _specification()
        unknown_stage["nfrs"][0]["verification_stage"] = "before-output"
        with self.assertRaisesRegex(SpecificationError, "verification_stage"):
            validate_specification(unknown_stage)

    def test_step_context_propagates_scoped_fr_and_all_applicable_nfrs(self) -> None:
        spec = validate_specification(_specification())
        release = next(step for step in _valid_steps() if step["id"] == "release")
        context = step_context(spec, release)

        self.assertEqual(context["step_id"], "release")
        self.assertEqual(context["role"], "release")
        self.assertEqual([item["id"] for item in context["deliverables"]], ["D1", "D2"])
        self.assertEqual(
            [item["id"] for item in context["functional_requirements"]], ["FR1", "FR2"]
        )
        self.assertEqual(
            [item["id"] for item in context["nfrs"]], ["NFR-GLOBAL", "NFR-D1"]
        )
        self.assertEqual(context["requirements"], [])
        self.assertEqual(context["verifies"], [])
        self.assertTrue(context["ready_when"])
        self.assertTrue(context["done_when"])

    def test_bad_dependency_cycle_is_defensively_rejected(self) -> None:
        steps = _valid_steps()
        steps[0]["needs"] = ["impl-d1"]

        with self.assertRaisesRegex(SpecificationError, "cycle"):
            validate_contracts(_specification(), steps)

    def test_step_context_returns_independent_values(self) -> None:
        spec = validate_specification(_specification())
        context = step_context(spec, _valid_steps()[1])
        context["deliverables"][0]["description"] = "changed only in caller context"

        self.assertEqual(spec["deliverables"][0]["description"], "First independently verifiable outcome")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
