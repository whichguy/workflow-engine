"""Prompt-entry integration tests using authored Backchain fixture plans.

These fixtures are deliberately authored.  They exercise the real selected
Backchain package-only adapter and the public CLI; they do not claim a model's
semantic planning or convergence review.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "workflow" / "scripts" / "workflow"
EXAMPLES = ROOT / "examples"
PLANS = EXAMPLES / "plans"
BACKCHAIN = Path(os.environ.get("WORKFLOW_TEST_BACKCHAIN_ROOT", ROOT.parent / "backchain"))


def _backchain_available() -> bool:
    return (
        (BACKCHAIN / "harness" / "run-prompt.sh").is_file()
        and (BACKCHAIN / "schema" / "plan.schema.json").is_file()
    )


@unittest.skipUnless(_backchain_available(), "Backchain source checkout unavailable")
class PromptExampleTests(unittest.TestCase):
    """Run named prompt recipes through planning, package validation, and execution."""

    maxDiff = None

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="workflow-prompt-examples-")
        self.addCleanup(self.tempdir.cleanup)
        self.base = Path(self.tempdir.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()

    def call(self, *args: object, success: bool = True) -> dict[str, Any]:
        completed = subprocess.run(
            [sys.executable, str(CLI), *(str(arg) for arg in args)],
            cwd=self.base,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertTrue(
            completed.stdout.strip(),
            f"CLI emitted no JSON for {args!r}; stderr:\n{completed.stderr}",
        )
        try:
            packet = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - assertion diagnostic
            self.fail(f"CLI stdout was not JSON: {completed.stdout!r}\n{exc}")
        if success:
            self.assertEqual(
                completed.returncode,
                0,
                f"CLI failed for {args!r}: {packet!r}\nstderr:\n{completed.stderr}",
            )
        else:
            self.assertNotEqual(completed.returncode, 0, packet)
        self.assertIsInstance(packet, dict)
        return packet

    def fixture_paths(self, recipe: str) -> tuple[Path, Path, Path, Path]:
        request = EXAMPLES / f"{recipe}.request.txt"
        specification = PLANS / f"{recipe}.spec.json"
        plan = PLANS / f"{recipe}.plan.json"
        bindings = PLANS / f"{recipe}.bindings.json"
        for path in (request, specification, plan, bindings):
            self.assertTrue(path.is_file(), path)
        return request, specification, plan, bindings

    def accept_specification(
        self, packet: dict[str, Any], specification: dict[str, Any]
    ) -> dict[str, Any]:
        spec_file = Path(str(packet["spec_file"]))
        spec_file.parent.mkdir(parents=True, exist_ok=True)
        spec_file.write_text(json.dumps(specification), encoding="utf-8")
        callback = list(packet["next_argv"])
        self.assertEqual(packet["allowed_operations"]["accept_spec"], callback)
        self.assertEqual(callback[-2], "--spec")
        self.assertEqual(callback[-1], str(spec_file))
        completed = subprocess.run(
            [str(argument) for argument in callback],
            cwd=self.base,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        accepted = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0, accepted)
        self.assertIsInstance(accepted, dict)
        return accepted

    def init_prompt(self, recipe: str) -> tuple[dict[str, Any], Path, Path, Path, Path]:
        source_request, source_specification, source_plan, source_bindings = self.fixture_paths(recipe)
        request = self.base / f"{recipe}.request.txt"
        plan = self.base / f"{recipe}.plan.json"
        bindings = self.base / f"{recipe}.bindings.json"
        request.write_bytes(source_request.read_bytes())
        expected_request = request.read_bytes().decode("utf-8")
        authored_specification = json.loads(source_specification.read_text(encoding="utf-8"))
        authored_plan = json.loads(source_plan.read_text(encoding="utf-8"))
        authored_bindings = json.loads(source_bindings.read_text(encoding="utf-8"))
        self.assertEqual(authored_specification["goal"], expected_request)
        self.assertEqual(
            authored_plan["goal"],
            expected_request,
            "the authored Backchain plan must preserve the paired request verbatim",
        )
        for step in authored_plan["steps"]:
            self.assertIn("contract", authored_bindings[step["id"]])
        run_dir = self.base / f"{recipe}-run"
        specification_packet = self.call(
            "init",
            "--prompt-file",
            request,
            "--backchain-root",
            BACKCHAIN,
            "--repo",
            self.repo,
            "--run-dir",
            run_dir,
        )
        plan.write_text(json.dumps(authored_plan), encoding="utf-8")
        bindings.write_text(json.dumps(authored_bindings), encoding="utf-8")
        packet = self.accept_specification(
            specification_packet,
            authored_specification,
        )
        self.assertEqual(packet["kind"], "planning")
        self.assertEqual(packet["original_goal"], expected_request)
        return packet, run_dir, request, plan, bindings

    def accept(self, planning: dict[str, Any], run_dir: Path, plan: Path, bindings: Path) -> dict[str, Any]:
        self.assertEqual(planning["kind"], "planning")
        return self.call(
            "accept-plan",
            "--run-dir",
            run_dir,
            "--action",
            planning["action_id"],
            "--plan",
            plan,
            "--bindings",
            bindings,
        )

    def execute(self, packet: dict[str, Any], run_dir: Path) -> dict[str, Any]:
        self.assertEqual(packet["kind"], "command", packet)
        return self.call(
            "execute",
            "--run-dir",
            run_dir,
            "--action",
            packet["action_id"],
        )

    def result(self, name: str, *, summary: str) -> Path:
        path = self.base / name
        path.write_text(
            json.dumps({"status": "succeeded", "summary": summary}),
            encoding="utf-8",
        )
        return path

    def complete(self, packet: dict[str, Any], run_dir: Path, result: Path) -> dict[str, Any]:
        self.assertEqual(packet["kind"], "prompt", packet)
        return self.call(
            "complete",
            "--run-dir",
            run_dir,
            "--action",
            packet["action_id"],
            "--result",
            result,
        )

    def assert_direct_dependencies(self, packet: dict[str, Any], expected: list[str]) -> None:
        for field in ("dependencies", "direct_dependency_receipts"):
            dependencies = packet[field]
            self.assertEqual([item["step_id"] for item in dependencies], expected)
            for dependency in dependencies:
                receipt = Path(dependency["receipt_path"])
                self.assertTrue(receipt.is_file(), receipt)
                self.assertEqual(dependency["path"], str(receipt))

    def test_braid_prompt_packages_real_backchain_graph_and_executes_two_joins(self) -> None:
        """An authored prompt imports both fan-out/fan-in dependency boundaries."""
        planning, run_dir, _request, plan, bindings = self.init_prompt("braid")
        packet = self.accept(planning, run_dir, plan, bindings)

        expected_direct_dependencies = {
            "seed": [],
            "extract": ["seed"],
            "classify": ["seed"],
            "consolidate": ["extract", "classify"],
            "compose": ["consolidate"],
            "check": ["consolidate"],
            "publish": ["compose", "check"],
        }
        observed_steps: list[str] = []
        while packet["status"] != "complete":
            step_id = packet["step_id"]
            self.assertIn(step_id, expected_direct_dependencies)
            self.assert_direct_dependencies(packet, expected_direct_dependencies[step_id])
            observed_steps.append(step_id)
            packet = self.execute(packet, run_dir)

        self.assertEqual(
            observed_steps,
            ["seed", "extract", "classify", "consolidate", "compose", "check", "publish"],
        )
        self.assertEqual(packet["status"], "complete")
        self.assertEqual(
            (Path(packet["workspace"]) / "published.md").read_text(encoding="utf-8"),
            "# Draft\nalpha,beta / 2\nChecked: PASS\n",
        )
        self.assertEqual(self.call("next", "--run-dir", run_dir)["status"], "complete")

    def test_confetti_prompt_waits_for_the_withheld_terminal_callback(self) -> None:
        """A terminal fork completes only after both independently declared leaves succeed."""
        planning, run_dir, _request, plan, bindings = self.init_prompt("confetti")
        seed = self.accept(planning, run_dir, plan, bindings)
        left = self.execute(seed, run_dir)
        self.assertEqual(left["step_id"], "left-note")
        self.assert_direct_dependencies(left, ["seed"])

        workspace = Path(left["workspace"])
        (workspace / "left-note.txt").write_text("LEFT: clear audience\n", encoding="utf-8")
        right = self.complete(
            left,
            run_dir,
            self.result("left-result.json", summary="wrote the left terminal note"),
        )
        self.assertEqual(right["step_id"], "right-note")
        self.assertEqual(right["status"], "ready")
        self.assert_direct_dependencies(right, ["seed"])

        # The last branch has not supplied a receipt.  A cold reader may recover
        # its packet, but must not report this terminal fan-out as complete.
        withheld = self.call("next", "--run-dir", run_dir)
        self.assertEqual(withheld["action_id"], right["action_id"])
        self.assertEqual(withheld["step_id"], "right-note")
        self.assertNotEqual(withheld["status"], "complete")

        (workspace / "right-note.txt").write_text(
            "RIGHT: concrete next step\n", encoding="utf-8"
        )
        terminal = self.complete(
            right,
            run_dir,
            self.result("right-result.json", summary="wrote the right terminal note"),
        )
        self.assertEqual(terminal["status"], "complete")
        self.assertTrue((workspace / "left-note.txt").is_file())
        self.assertTrue((workspace / "right-note.txt").is_file())

    def test_rejects_a_complex_plan_with_a_missing_execution_binding_without_freezing_it(self) -> None:
        """Package validation gates graph activation before any step can run."""
        planning, run_dir, _request, plan, bindings = self.init_prompt("braid")
        broken = json.loads(bindings.read_text(encoding="utf-8"))
        del broken["check"]
        broken_bindings = self.base / "braid-missing-check.bindings.json"
        broken_bindings.write_text(json.dumps(broken), encoding="utf-8")

        failure = self.call(
            "accept-plan",
            "--run-dir",
            run_dir,
            "--action",
            planning["action_id"],
            "--plan",
            plan,
            "--bindings",
            broken_bindings,
            success=False,
        )
        self.assertIn("Backchain plan compilation failed", failure["error"])
        recovered = self.call("next", "--run-dir", run_dir)
        self.assertEqual(recovered["kind"], "planning")
        self.assertEqual(recovered["action_id"], planning["action_id"])
        self.assertFalse((self.repo / "seed.txt").exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
