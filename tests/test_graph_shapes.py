"""Runnable, black-box examples for serial DAG shapes.

The default executor deliberately runs one ready action at a time.  These tests
therefore prove durable topology and completion semantics, not concurrent worker
dispatch.  A separate opt-in concurrency mode needs its own scheduling tests.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from spec_fixtures import authored_specification


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "workflow" / "scripts" / "workflow"
PYTHON = sys.executable


class GraphShapeExamplesTests(unittest.TestCase):
    """Exercise the authored examples through the public CLI protocol."""

    maxDiff = None

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="workflow-graph-shapes-")
        self.addCleanup(self.tempdir.cleanup)
        self.base = Path(self.tempdir.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.run_dir = self.base / "run"

    def raw_cli(self, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [PYTHON, str(CLI), *(str(arg) for arg in args)],
            cwd=self.base,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )

    def cli_packet(self, *args: object) -> dict[str, Any]:
        completed = self.raw_cli(*args)
        self.assertTrue(
            completed.stdout.strip(),
            f"CLI emitted no packet for {args!r}; stderr:\n{completed.stderr}",
        )
        try:
            packet = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - assertion diagnostic
            self.fail(f"CLI stdout was not a JSON packet: {completed.stdout!r}\n{exc}")
        self.assertEqual(
            completed.returncode,
            0,
            f"CLI failed for {args!r}: {packet!r}\nstderr:\n{completed.stderr}",
        )
        self.assertIsInstance(packet, dict)
        return packet

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
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        accepted = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0, accepted)
        self.assertIsInstance(accepted, dict)
        return accepted

    def init_example(self, filename: str, *, copied: bool = False) -> tuple[dict[str, Any], Path]:
        source = ROOT / "examples" / filename
        self.assertTrue(source.is_file(), source)
        if copied:
            target = self.base / filename
            shutil.copyfile(source, target)
            source = target
        return (
            self.cli_packet(
                "init",
                "--workflow",
                source,
                "--run-dir",
                self.run_dir,
                "--repo",
                self.repo,
            ),
            source,
        )

    def execute(self, packet: dict[str, Any]) -> dict[str, Any]:
        self.assertEqual(packet["kind"], "command", packet)
        self.assertIsInstance(packet["action_id"], str)
        return self.cli_packet(
            "execute",
            "--run-dir",
            self.run_dir,
            "--action",
            packet["action_id"],
        )

    def write_result(self, name: str, *, status: str, summary: str) -> Path:
        result = self.base / name
        result.write_text(json.dumps({"status": status, "summary": summary}), encoding="utf-8")
        return result

    def complete(self, packet: dict[str, Any], result: Path) -> dict[str, Any]:
        self.assertIn(packet["kind"], {"prompt", "agent"}, packet)
        self.assertIsInstance(packet["action_id"], str)
        return self.cli_packet(
            "complete",
            "--run-dir",
            self.run_dir,
            "--action",
            packet["action_id"],
            "--result",
            result,
        )

    def read_state(self) -> dict[str, Any]:
        state_text = (self.run_dir / "state.md").read_text(encoding="utf-8")
        opening = "```workflow-state\n"
        self.assertIn(opening, state_text)
        payload = state_text.split(opening, 1)[1].split("\n```", 1)[0]
        state = json.loads(payload)
        self.assertIsInstance(state, dict)
        return state

    def assert_direct_receipts(
        self, packet: dict[str, Any], expected_step_ids: set[str]
    ) -> None:
        dependencies = packet["direct_dependency_receipts"]
        self.assertEqual({item["step_id"] for item in dependencies}, expected_step_ids)
        for dependency in dependencies:
            receipt_path = Path(dependency["receipt_path"])
            self.assertTrue(receipt_path.is_absolute())
            self.assertTrue(receipt_path.is_file(), receipt_path)
            self.assertEqual(
                dependency["sha256"],
                hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            )

    def test_braid_repeated_fanout_and_fanin_exposes_every_direct_receipt(self) -> None:
        """A Braid's two joins wait for their exact two direct suppliers."""
        packet, _ = self.init_example("braid.workflow.json")
        self.assertEqual(packet["step_id"], "seed")

        packet = self.execute(packet)
        self.assertEqual(packet["step_id"], "extract")
        packet = self.execute(packet)
        self.assertEqual(packet["step_id"], "classify")
        packet = self.execute(packet)
        self.assertEqual(packet["step_id"], "consolidate")
        self.assert_direct_receipts(packet, {"extract", "classify"})

        packet = self.execute(packet)
        self.assertEqual(packet["step_id"], "compose")
        packet = self.execute(packet)
        self.assertEqual(packet["step_id"], "check")
        packet = self.execute(packet)
        self.assertEqual(packet["step_id"], "publish")
        self.assert_direct_receipts(packet, {"compose", "check"})

        terminal = self.execute(packet)
        self.assertEqual(terminal["status"], "complete")
        self.assertEqual(
            (Path(terminal["workspace"]) / "published.md").read_text(encoding="utf-8"),
            "# Draft\nalpha,beta / 2\nChecked: PASS\n",
        )
        state = self.read_state()
        self.assertEqual(
            set(state["completed"]),
            {"seed", "extract", "classify", "consolidate", "compose", "check", "publish"},
        )

    def test_confetti_terminal_fork_waits_for_both_leaves_and_recovers_a_failed_leaf(self) -> None:
        """No synthetic join means terminal completion still requires both leaves."""
        packet, _ = self.init_example("confetti.workflow.json")
        left = self.execute(packet)
        self.assertEqual(left["step_id"], "left-note")
        self.assert_direct_receipts(left, {"seed"})

        workspace = Path(left["workspace"])
        (workspace / "left-note.txt").write_text("LEFT: clear audience\n", encoding="utf-8")
        right = self.complete(
            left,
            self.write_result("left-succeeded.json", status="succeeded", summary="wrote left note"),
        )
        self.assertEqual(right["step_id"], "right-note")
        self.assertEqual(right["status"], "ready")
        # The two leaves share the root but are not secretly serialized through
        # one another; the right leaf sees only its declared direct supplier.
        self.assert_direct_receipts(right, {"seed"})

        failed_action = right["action_id"]
        failed = self.complete(
            right,
            self.write_result("right-failed.json", status="failed", summary="reviewer stopped"),
        )
        self.assertEqual(failed["status"], "failed")
        self.assertNotEqual(failed["status"], "complete")
        state_after_failure = self.read_state()
        self.assertEqual(set(state_after_failure["completed"]), {"seed", "left-note"})
        self.assertEqual(state_after_failure["current_action"]["id"], failed_action)

        cold = self.cli_packet("next", "--run-dir", self.run_dir)
        self.assertEqual(cold["action_id"], failed_action)
        self.assertNotEqual(cold["status"], "complete")

        retry = self.cli_packet(
            "retry",
            "--run-dir",
            self.run_dir,
            "--action",
            failed_action,
            "--reason",
            "the former terminal reviewer is confirmed stopped",
            "--confirmed-stopped",
        )
        self.assertEqual(retry["step_id"], "right-note")
        self.assertNotEqual(retry["action_id"], failed_action)
        (workspace / "right-note.txt").write_text("RIGHT: concrete next step\n", encoding="utf-8")
        terminal = self.complete(
            retry,
            self.write_result("right-succeeded.json", status="succeeded", summary="wrote right note"),
        )
        self.assertEqual(terminal["status"], "complete")
        self.assertEqual(set(self.read_state()["completed"]), {"seed", "left-note", "right-note"})

    def test_tributaries_uses_dependency_order_not_declaration_order_or_branch_waves(self) -> None:
        """Multiple roots and uneven paths stay legal when listed in a confusing order."""
        packet, _ = self.init_example("tributaries.workflow.json")
        # join-all appears first in the source file, but it cannot run first.
        self.assertEqual(packet["step_id"], "independent-leaf")
        terminal = self.cli_packet("run", "--run-dir", self.run_dir)
        self.assertEqual(terminal["status"], "complete")

        workspace = Path(terminal["workspace"])
        self.assertEqual(
            (workspace / "schedule.log").read_text(encoding="utf-8").splitlines(),
            [
                "independent-leaf",
                "left-root",
                "left-leaf",
                "right-root",
                "right-middle",
                "right-final",
                "join-all",
            ],
        )
        self.assertEqual(
            (workspace / "joined.txt").read_text(encoding="utf-8"),
            "left-leaf + right-middle-final",
        )
        self.assertEqual(
            set(self.read_state()["completed"]),
            {
                "join-all",
                "right-final",
                "independent-leaf",
                "left-leaf",
                "right-middle",
                "left-root",
                "right-root",
            },
        )

    def test_example_definition_is_frozen_even_when_its_source_file_changes(self) -> None:
        """A run uses its frozen Braid, never a later edit to the authored file."""
        original_packet, source = self.init_example("braid.workflow.json", copied=True)
        original_bytes = source.read_bytes()
        source.write_text("this is no longer a valid workflow document\n", encoding="utf-8")

        terminal = self.cli_packet("run", "--run-dir", self.run_dir)
        self.assertEqual(terminal["status"], "complete")
        self.assertEqual(original_packet["step_id"], "seed")
        self.assertEqual(
            (Path(terminal["workspace"]) / "published.md").read_text(encoding="utf-8"),
            "# Draft\nalpha,beta / 2\nChecked: PASS\n",
        )
        state = self.read_state()
        self.assertEqual(state["request"]["source_sha256"], hashlib.sha256(original_bytes).hexdigest())
        self.assertEqual(state["definition"]["name"], "braid")
        self.assertEqual([step["id"] for step in state["definition"]["steps"]][-1], "publish")

    def test_authored_request_files_enter_as_verbatim_durable_planning_packets(self) -> None:
        """Each named recipe can begin with a prompt before a graph exists."""
        for filename in ("braid.request.txt", "confetti.request.txt", "tributaries.request.txt"):
            with self.subTest(filename=filename):
                original = ROOT / "examples" / filename
                request = self.base / filename
                shutil.copyfile(original, request)
                exact = request.read_text(encoding="utf-8")
                run_dir = self.base / f"{request.stem}-run"
                specification_packet = self.cli_packet(
                    "init",
                    "--prompt-file",
                    request,
                    "--backchain-root",
                    self.repo,
                    "--run-dir",
                    run_dir,
                    "--repo",
                    self.repo,
                )
                packet = self.accept_specification(
                    specification_packet,
                    authored_specification(exact),
                )
                self.assertEqual(packet["kind"], "planning")
                self.assertEqual(packet["status"], "planning")
                self.assertEqual(packet["original_goal"], exact)

                request.write_text("a changed request must not replace the run\n", encoding="utf-8")
                cold = self.cli_packet("next", "--run-dir", run_dir)
                self.assertEqual(cold["kind"], "planning")
                self.assertEqual(cold["action_id"], packet["action_id"])
                self.assertEqual(cold["original_goal"], exact)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
