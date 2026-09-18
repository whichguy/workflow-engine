"""Generated and compound black-box contracts for the v2 frontier.

These tests intentionally know only the declared workflow document and JSON CLI
packets.  ``tests.graph_oracle`` does not import the engine, so a scheduler bug
cannot be hidden by a duplicated runtime helper.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

try:  # Support both ``python -m unittest`` and direct local invocation.
    from tests.graph_oracle import (
        BlackBoxWorkflowRunner,
        GraphOracle,
        loom_workflow,
        oracle_negative_controls,
        redundant_transitive_workflow,
        runtime_hashes,
        seeded_workflow,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script convenience
    from graph_oracle import (  # type: ignore[no-redef]
        BlackBoxWorkflowRunner,
        GraphOracle,
        loom_workflow,
        oracle_negative_controls,
        redundant_transitive_workflow,
        runtime_hashes,
        seeded_workflow,
    )


ROOT = Path(__file__).resolve().parents[1]


class GeneratedGraphCliTest(unittest.TestCase):
    """Exercise topology, capacity, receipts, and cold recovery as one contract."""

    maxDiff = None

    def run_document(
        self, document: dict[str, object], *, label: str, max_active: int
    ) -> tuple[BlackBoxWorkflowRunner, object]:
        temporary = tempfile.TemporaryDirectory(prefix=f"weave-{label}-")
        self.addCleanup(temporary.cleanup)
        runner = BlackBoxWorkflowRunner(
            root=ROOT,
            base=Path(temporary.name),
            document=document,
            max_active=max_active,
            label=label,
        )
        return runner, runner.run_to_completion()

    def test_oracle_negative_controls_are_explicit_and_do_not_mutate_the_runtime(self) -> None:
        """Bad synthetic packets must fail oracle checks; source bytes stay untouched."""
        before = runtime_hashes(ROOT)
        controls = oracle_negative_controls()
        self.assertEqual(runtime_hashes(ROOT), before)
        self.assertEqual(
            {control["case"] for control in controls},
            {"premature-terminal", "missing-direct-dependency-receipt", "over-capacity"},
        )
        for control in controls:
            self.assertEqual(control["kind"], "oracle-self-test")
            self.assertFalse(control["runtime_mutated"])
            self.assertTrue(control["rejected"], control)
            self.assertTrue(control["message"], control)

    def test_seeded_small_dags_cover_capacity_partial_claims_and_cold_next(self) -> None:
        """Eight deterministic, shuffled DAGs vary capacities 2/3/5 and completion order."""
        capacities = (2, 3, 5, 2, 3, 5, 2, 3)
        for seed, max_active in enumerate(capacities):
            with self.subTest(seed=seed, max_active=max_active):
                document = seeded_workflow(seed)
                oracle = GraphOracle(document)
                self.assertNotEqual(
                    [step["id"] for step in document["steps"]], list(oracle.topology),
                    "the fixture must keep declaration order distinct from dependency order",
                )
                # This graph generator always includes a declared direct edge
                # that is transitively implied.  The driver checks that it
                # stays in C's direct receipt set rather than being collapsed.
                self.assertEqual(
                    set(oracle.steps["S06"].needs), {"S00", "S03", "S05"}
                )
                runner, result = self.run_document(
                    document, label=f"seed-{seed}", max_active=max_active
                )
                self.assertEqual(result.status, "complete")
                self.assertEqual(set(result.completed_steps), set(oracle.steps))
                self.assertEqual(result.final_packet["status"], "complete")
                self.assertGreater(result.max_packet_bytes, 0)
                self.assertGreater(result.elapsed_ms, 0)
                self.assertLessEqual(result.transitions, 300)
                self.assertGreaterEqual(
                    sum(event["operation"] == "next" for event in result.trace), 2
                )
                self.assertTrue(
                    any(event["operation"] == "claim-ready" for event in result.trace),
                    runner.trace,
                )

    def test_redundant_transitive_edge_keeps_every_declared_receipt(self) -> None:
        """C must receive both A and B receipts even though B already needs A."""
        document = redundant_transitive_workflow()
        runner, result = self.run_document(document, label="transitive", max_active=5)
        self.assertEqual(result.status, "complete")
        self.assertEqual(set(result.completed_steps), {"A", "B", "C", "D"})
        # The independent oracle validates both ``dependencies`` fields on C;
        # retaining the check here makes the intended edge shape reviewable.
        self.assertEqual(runner.oracle.steps["C"].needs, ("A", "B"))

    def test_loom_compound_fixture_has_overlapping_diamonds_and_waits_for_all_leaves(self) -> None:
        """A->{B,C}->D->{E,F,G}; H(E,F), I(F,G), J(H,I), K/L plus terminal M."""
        example_path = ROOT / "examples" / "loom.workflow.json"
        self.assertTrue(example_path.is_file(), "Loom example is part of the public contract")
        document = json.loads(example_path.read_text(encoding="utf-8"))
        self.assertEqual(document["name"], "loom")
        oracle = GraphOracle(document)
        self.assertEqual(oracle.steps["H"].needs, ("E", "F"))
        self.assertEqual(oracle.steps["I"].needs, ("F", "G"))
        self.assertEqual(oracle.steps["J"].needs, ("H", "I"))
        self.assertEqual({step_id for step_id, step in oracle.steps.items() if not any(
            step_id in candidate.needs for candidate in oracle.steps.values()
        )}, {"K", "L", "M"})

        runner, result = self.run_document(document, label="loom", max_active=3)
        self.assertEqual(result.status, "complete")
        self.assertEqual(set(result.completed_steps), set(oracle.steps))

        claim_events = [event for event in result.trace if event["operation"] == "claim-ready"]
        self.assertEqual(claim_events[0]["claimed"], ["A"])
        # M is dependency-ready from the beginning, but the script keeps the
        # prompt globally exclusive while it fills a disjoint B/C agent batch.
        self.assertTrue(
            any(
                set(event["claimed"]) == {"B", "C"}
                and "M" in event["ready"]
                and set(event["active"]) == {"B", "C"}
                for event in claim_events
            ),
            claim_events,
        )
        self.assertEqual(result.final_packet["active_count"], 0)
        self.assertEqual(result.final_packet["ready_frontier"], [])

    def test_helper_loom_shape_matches_the_reviewable_example_topology(self) -> None:
        """Keep the experiment fixture and the checked-in example synchronized by graph shape."""
        example = GraphOracle(json.loads((ROOT / "examples" / "loom.workflow.json").read_text()))
        helper = GraphOracle(loom_workflow())
        self.assertEqual(
            {step_id: (step.kind, step.needs) for step_id, step in example.steps.items()},
            {step_id: (step.kind, step.needs) for step_id, step in helper.steps.items()},
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
