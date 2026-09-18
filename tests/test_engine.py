"""Black-box contract tests for the durable workflow CLI.

The tests intentionally invoke the installed-in-source CLI in fresh subprocesses.
They exercise the packet protocol and durable run directory rather than importing
the kernel, so a cold recovery is the same path a skill host uses.
"""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from spec_fixtures import specified


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "workflow" / "scripts" / "workflow"
PYTHON = sys.executable


class WorkflowCliTest(unittest.TestCase):
    """Exercise only the documented command-line packet contract."""

    maxDiff = None

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="workflow-engine-test-")
        self.base = Path(self.tempdir.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.run_dir = self.base / "run"
        self.workflow_path = self.base / "workflow.json"
        self.goal = "Exercise the durable workflow kernel"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def raw_cli(self, *args: object, timeout: float = 15) -> subprocess.CompletedProcess[str]:
        self.assertTrue(CLI.is_file(), f"missing workflow CLI: {CLI}")
        return subprocess.run(
            [PYTHON, str(CLI), *(str(arg) for arg in args)],
            cwd=self.base,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def parse_packet(self, completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        self.assertTrue(
            completed.stdout.strip(),
            "every CLI response must emit its one JSON packet on stdout\n"
            f"stderr:\n{completed.stderr}",
        )
        try:
            packet = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - assertion diagnostic
            self.fail(
                "CLI stdout was not one JSON packet: "
                f"{completed.stdout!r}\nstderr:\n{completed.stderr}\n{exc}"
            )
        self.assertIsInstance(packet, dict)
        return packet

    def cli_packet(self, *args: object, timeout: float = 15) -> dict[str, Any]:
        completed = self.raw_cli(*args, timeout=timeout)
        packet = self.parse_packet(completed)
        self.assertEqual(
            completed.returncode,
            0,
            f"CLI failed for {args!r}: {packet!r}\nstderr:\n{completed.stderr}",
        )
        return packet

    def cli_error(self, *args: object, timeout: float = 15) -> dict[str, Any]:
        completed = self.raw_cli(*args, timeout=timeout)
        packet = self.parse_packet(completed)
        self.assertNotEqual(
            completed.returncode,
            0,
            f"expected protocol/validation failure for {args!r}, got {packet!r}",
        )
        return packet

    def cli_failure_or_parked(
        self, *args: object, timeout: float = 15
    ) -> dict[str, Any]:
        """Accept either a JSON protocol error or a documented parked packet.

        A bad external result may be rejected before state changes (nonzero) or may
        be recorded as blocked/in-doubt (a normal zero-exit packet).  Both outcomes
        must leave the old action unable to advance automatically.
        """
        completed = self.raw_cli(*args, timeout=timeout)
        packet = self.parse_packet(completed)
        if completed.returncode == 0:
            self.assertNotEqual(
                packet.get("status"),
                "complete",
                f"failure unexpectedly completed the workflow: {packet!r}",
            )
        return packet

    def write_workflow(self, document: dict[str, Any]) -> Path:
        self.workflow_path.write_text(
            json.dumps(document, indent=2, sort_keys=True), encoding="utf-8"
        )
        return self.workflow_path

    def init_workflow(self, document: dict[str, Any]) -> dict[str, Any]:
        self.goal = document["goal"]
        workflow = self.write_workflow(document)
        return self.cli_packet(
            "init",
            "--workflow",
            workflow,
            "--run-dir",
            self.run_dir,
            "--repo",
            self.repo,
        )

    def simple_document(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        return specified(
            {
                "version": 1,
                "name": "test-workflow",
                "goal": self.goal,
                "steps": steps,
            }
        )

    @staticmethod
    def command_step(
        step_id: str,
        code: str,
        outputs: list[str],
        *,
        needs: list[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        step: dict[str, Any] = {
            "id": step_id,
            "kind": "command",
            "argv": [PYTHON, "-c", code],
            "outputs": outputs,
        }
        if needs is not None:
            step["needs"] = needs
        if timeout_seconds is not None:
            step["timeout_seconds"] = timeout_seconds
        return step

    @staticmethod
    def prompt_step(
        step_id: str,
        *,
        outputs: list[str],
        verify: list[list[str]] | None = None,
        kind: str = "prompt",
    ) -> dict[str, Any]:
        step: dict[str, Any] = {
            "id": step_id,
            "kind": kind,
            "prompt": f"Write the declared output for {step_id}.",
            "outputs": outputs,
        }
        if verify is not None:
            step["verify"] = verify
        return step

    def assert_packet(
        self, packet: Mapping[str, Any], *, active: bool = True
    ) -> None:
        """Assert fields every public packet is required to expose."""
        required = {
            "run_id",
            "run_dir",
            "goal",
            "status",
            "action_id",
            "kind",
            "step_id",
            "workspace",
            "outputs",
            "dependencies",
            "next_argv",
            "allowed_operations",
        }
        self.assertFalse(required.difference(packet), f"packet missing fields: {packet!r}")
        self.assertIsInstance(packet["run_id"], str)
        self.assertEqual(packet["run_dir"], str(self.run_dir.resolve()))
        self.assertEqual(packet["goal"], self.goal)
        self.assertTrue(Path(packet["run_dir"]).is_absolute())
        self.assertTrue(Path(packet["workspace"]).is_absolute())
        self.assertIsInstance(packet["outputs"], list)
        self.assertIsInstance(packet["dependencies"], list)
        self.assertIsInstance(packet["next_argv"], list)
        self.assertTrue(packet["next_argv"])
        self.assertTrue(Path(packet["next_argv"][0]).is_absolute())
        self.assertIsInstance(packet["allowed_operations"], (list, dict))
        if active:
            self.assertIsInstance(packet["action_id"], str)
            self.assertTrue(packet["action_id"])
            self.assertIsInstance(packet["kind"], str)
            self.assertIsInstance(packet["step_id"], str)

    def write_result(self, name: str, status: str, summary: str) -> Path:
        result = self.base / name
        result.write_text(
            json.dumps({"status": status, "summary": summary}), encoding="utf-8"
        )
        return result

    def read_state(self) -> dict[str, Any]:
        """Read the documented single state fence without importing the kernel."""
        text = (self.run_dir / "state.md").read_text(encoding="utf-8")
        opening = "```workflow-state\n"
        self.assertIn(opening, text)
        payload = text.split(opening, 1)[1].split("\n```", 1)[0]
        state = json.loads(payload)
        self.assertIsInstance(state, dict)
        return state

    def complete(
        self, action_id: str, result: Path, *, tolerate_failure: bool = False
    ) -> dict[str, Any]:
        args = (
            "complete",
            "--run-dir",
            self.run_dir,
            "--action",
            action_id,
            "--result",
            result,
        )
        if tolerate_failure:
            return self.cli_failure_or_parked(*args)
        return self.cli_packet(*args)

    def test_serial_diamond_runs_in_deterministic_topological_order_with_receipts(self) -> None:
        """``run`` performs a serial, reproducible walk of a diamond DAG."""
        def code(letter: str, output: str) -> str:
            return (
                "from pathlib import Path; "
                f"Path({output!r}).write_text({letter!r}); "
                f"Path('order.txt').open('a', encoding='utf-8').write({letter!r})"
            )

        packet = self.init_workflow(
            self.simple_document(
                [
                    self.command_step("a", code("a", "a.txt"), ["a.txt"], needs=[]),
                    self.command_step("b", code("b", "b.txt"), ["b.txt"], needs=["a"]),
                    self.command_step("c", code("c", "c.txt"), ["c.txt"], needs=["a"]),
                    self.command_step(
                        "d", code("d", "d.txt"), ["d.txt"], needs=["b", "c"]
                    ),
                ]
            )
        )
        self.assert_packet(packet)
        terminal = self.cli_packet("run", "--run-dir", self.run_dir)
        self.assert_packet(terminal, active=False)
        self.assertEqual(terminal["status"], "complete")

        workspace = Path(terminal["workspace"])
        self.assertEqual((workspace / "order.txt").read_text(encoding="utf-8"), "abcd")
        for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
            self.assertTrue((workspace / name).is_file(), name)

        # State and the derived packet are durable Markdown records, while each
        # accepted command has a separate receipt artifact.
        self.assertTrue((self.run_dir / "state.md").is_file())
        self.assertTrue((self.run_dir / "packet.md").is_file())
        receipts = [
            path
            for path in self.run_dir.rglob("*.md")
            if path.name not in {"state.md", "packet.md", "transaction.md"}
        ]
        self.assertGreaterEqual(len(receipts), 4)

    def test_cold_next_process_keeps_the_same_action_identity_and_packet_contract(self) -> None:
        first = self.init_workflow(
            self.simple_document([self.prompt_step("write", outputs=["answer.txt"])])
        )
        self.assert_packet(first)

        # A separate subprocess is the cold-restart path, not an in-process cache.
        second = self.cli_packet("next", "--run-dir", self.run_dir)
        self.assert_packet(second)
        self.assertEqual(second["run_id"], first["run_id"])
        self.assertEqual(second["action_id"], first["action_id"])
        self.assertEqual(second["step_id"], first["step_id"])
        self.assertEqual(second["kind"], first["kind"])
        self.assertEqual(second["next_argv"], first["next_argv"])

    def test_execute_moves_the_cursor_and_persists_command_artifacts(self) -> None:
        first = self.init_workflow(
            self.simple_document(
                [
                    self.command_step(
                        "write",
                        "from pathlib import Path; Path('artifact.txt').write_text('first')",
                        ["artifact.txt"],
                        needs=[],
                    ),
                    self.command_step(
                        "finish",
                        "from pathlib import Path; Path('finished.txt').write_text('done')",
                        ["finished.txt"],
                    ),
                ]
            )
        )
        self.assert_packet(first)
        second = self.cli_packet(
            "execute", "--run-dir", self.run_dir, "--action", first["action_id"]
        )
        self.assert_packet(second)
        self.assertEqual(second["step_id"], "finish")
        self.assertEqual(
            (Path(second["workspace"]) / "artifact.txt").read_text(encoding="utf-8"),
            "first",
        )
        self.assertEqual(len(second["dependencies"]), 1)
        dependency = second["dependencies"][0]
        self.assertIsInstance(dependency, dict)
        self.assertTrue(dependency.get("path"))
        self.assertTrue(dependency.get("sha256"))

        terminal = self.cli_packet(
            "execute", "--run-dir", self.run_dir, "--action", second["action_id"]
        )
        self.assertEqual(terminal["status"], "complete")

    def test_prompt_verifier_failure_never_advances_the_action(self) -> None:
        verifier = [
            PYTHON,
            "-c",
            "from pathlib import Path; assert Path('answer.txt').read_text() == 'good'",
        ]
        first = self.init_workflow(
            self.simple_document(
                [self.prompt_step("review", outputs=["answer.txt"], verify=[verifier])]
            )
        )
        self.assert_packet(first)
        (Path(first["workspace"]) / "answer.txt").write_text("bad", encoding="utf-8")
        result = self.write_result("prompt-result.json", "succeeded", "reviewed answer")
        self.complete(first["action_id"], result, tolerate_failure=True)

        recovered = self.cli_packet("next", "--run-dir", self.run_dir)
        self.assertNotEqual(recovered["status"], "complete")
        self.assertEqual(recovered["action_id"], first["action_id"])
        self.assertEqual(recovered["step_id"], "review")

    def test_agent_requires_prepared_native_dispatch_and_parks_after_bad_verifier(self) -> None:
        verifier = [
            PYTHON,
            "-c",
            "from pathlib import Path; assert Path('review.txt').read_text() == 'good'",
        ]
        first = self.init_workflow(
            self.simple_document(
                [
                    self.prompt_step(
                        "agent-review",
                        kind="agent",
                        outputs=["review.txt"],
                        verify=[verifier],
                    )
                ]
            )
        )
        self.assert_packet(first)

        # A host cannot record a native handle until it has durably recorded that
        # it is about to launch; this prevents a crash from triggering blind spawn.
        self.cli_error(
            "dispatch",
            "--run-dir",
            self.run_dir,
            "--action",
            first["action_id"],
            "--handle",
            "native-1",
        )
        preparing = self.cli_packet(
            "prepare-dispatch",
            "--run-dir",
            self.run_dir,
            "--action",
            first["action_id"],
        )
        self.assertEqual(preparing["action_id"], first["action_id"])
        self.assertEqual(preparing["status"], "dispatching")
        recovered = self.cli_packet("next", "--run-dir", self.run_dir)
        self.assertEqual(recovered["status"], "dispatching")
        self.assertEqual(recovered["action_id"], first["action_id"])

        dispatched = self.cli_packet(
            "dispatch",
            "--run-dir",
            self.run_dir,
            "--action",
            first["action_id"],
            "--handle",
            "native-1",
        )
        self.assertEqual(dispatched["action_id"], first["action_id"])
        (Path(first["workspace"]) / "review.txt").write_text("bad", encoding="utf-8")
        result = self.write_result("agent-result.json", "succeeded", "agent reviewed")
        self.complete(first["action_id"], result, tolerate_failure=True)
        parked = self.cli_packet("next", "--run-dir", self.run_dir)
        self.assertNotEqual(parked["status"], "complete")
        self.assertEqual(parked["action_id"], first["action_id"])

    def test_identical_completion_replays_but_conflicting_completion_fails(self) -> None:
        verifier = [
            PYTHON,
            "-c",
            "from pathlib import Path; assert Path('answer.txt').read_text() == 'good'",
        ]
        first = self.init_workflow(
            self.simple_document(
                [self.prompt_step("answer", outputs=["answer.txt"], verify=[verifier])]
            )
        )
        (Path(first["workspace"]) / "answer.txt").write_text("good", encoding="utf-8")
        accepted = self.write_result("accepted.json", "succeeded", "answer verified")
        terminal = self.complete(first["action_id"], accepted)
        self.assertEqual(terminal["status"], "complete")

        replay = self.complete(first["action_id"], accepted)
        self.assertEqual(replay["status"], "complete")
        conflicting = self.write_result("conflict.json", "failed", "different outcome")
        self.cli_error(
            "complete",
            "--run-dir",
            self.run_dir,
            "--action",
            first["action_id"],
            "--result",
            conflicting,
        )

    def test_retry_fences_old_action_and_rejects_its_callback(self) -> None:
        first = self.init_workflow(
            self.simple_document([self.prompt_step("retryable", outputs=["retry.txt"])])
        )
        failed = self.write_result("failed.json", "failed", "writer stopped")
        parked = self.complete(first["action_id"], failed)
        self.assertNotEqual(parked["status"], "complete")

        retried = self.cli_packet(
            "retry",
            "--run-dir",
            self.run_dir,
            "--action",
            first["action_id"],
            "--reason",
            "the failed writer is confirmed stopped",
            "--confirmed-stopped",
        )
        self.assert_packet(retried)
        self.assertNotEqual(retried["action_id"], first["action_id"])
        stale = self.write_result("stale.json", "succeeded", "late callback")
        self.cli_error(
            "complete",
            "--run-dir",
            self.run_dir,
            "--action",
            first["action_id"],
            "--result",
            stale,
        )

    def test_retry_rejects_output_that_was_not_changed_by_the_new_attempt(self) -> None:
        verifier = [
            PYTHON,
            "-c",
            "from pathlib import Path; assert Path('retry.txt').read_text() == 'good'",
        ]
        first = self.init_workflow(
            self.simple_document(
                [self.prompt_step("retryable", outputs=["retry.txt"], verify=[verifier])]
            )
        )
        output = Path(first["workspace"]) / "retry.txt"
        output.write_text("good", encoding="utf-8")
        failed = self.write_result("first-failure.json", "failed", "worker failed after write")
        self.complete(first["action_id"], failed)
        retried = self.cli_packet(
            "retry",
            "--run-dir",
            self.run_dir,
            "--action",
            first["action_id"],
            "--reason",
            "old writer stopped after its failed attempt",
            "--confirmed-stopped",
        )
        self.assertNotEqual(retried["action_id"], first["action_id"])

        stale_success = self.write_result("stale-success.json", "succeeded", "reused old file")
        self.complete(retried["action_id"], stale_success, tolerate_failure=True)
        recovered = self.cli_packet("next", "--run-dir", self.run_dir)
        self.assertNotEqual(recovered["status"], "complete")
        self.assertEqual(recovered["action_id"], retried["action_id"])

    def test_invalid_graph_unsafe_outputs_and_unknown_fields_are_rejected(self) -> None:
        base_step = self.command_step(
            "a", "from pathlib import Path; Path('a.txt').write_text('a')", ["a.txt"], needs=[]
        )
        invalid_documents = [
            self.simple_document(
                [
                    {**base_step, "needs": ["b"]},
                    self.command_step(
                        "b",
                        "from pathlib import Path; Path('b.txt').write_text('b')",
                        ["b.txt"],
                        needs=["a"],
                    ),
                ]
            ),
            self.simple_document([base_step, {**base_step}]),
            self.simple_document([{**base_step, "outputs": ["../escape.txt"]}]),
            self.simple_document(
                [
                    {**base_step, "outputs": ["artifact", "artifact/child.txt"]},
                ]
            ),
            {**self.simple_document([base_step]), "unexpected": True},
            self.simple_document([{**base_step, "unexpected": True}]),
        ]

        for index, document in enumerate(invalid_documents):
            with self.subTest(index=index):
                workflow = self.base / f"invalid-{index}.json"
                workflow.write_text(json.dumps(document), encoding="utf-8")
                run_dir = self.base / f"invalid-run-{index}"
                self.cli_error(
                    "init",
                    "--workflow",
                    workflow,
                    "--run-dir",
                    run_dir,
                    "--repo",
                    self.repo,
                )

    def test_crashed_or_timed_out_command_is_never_blindly_rerun(self) -> None:
        cases = {
            "crash": (
                "from pathlib import Path; p=Path('count.txt'); "
                "p.write_text((p.read_text() if p.exists() else '') + 'x'); raise SystemExit(7)",
                None,
            ),
            "timeout": (
                "from pathlib import Path; import time; p=Path('count.txt'); "
                "p.write_text((p.read_text() if p.exists() else '') + 'x'); time.sleep(2)",
                0.1,
            ),
        }
        for name, (code, timeout_seconds) in cases.items():
            with self.subTest(case=name):
                # Each case must use a fresh workspace: both commands append to
                # the same deliberately observable output to expose a blind rerun.
                self.repo = self.base / f"{name}-repo"
                self.repo.mkdir()
                self.run_dir = self.base / f"{name}-run"
                first = self.init_workflow(
                    self.simple_document(
                        [
                            self.command_step(
                                "unsafe",
                                code,
                                ["count.txt"],
                                needs=[],
                                timeout_seconds=timeout_seconds,
                            )
                        ]
                    )
                )
                self.cli_failure_or_parked(
                    "execute", "--run-dir", self.run_dir, "--action", first["action_id"], timeout=10
                )
                count = Path(first["workspace"]) / "count.txt"
                self.assertEqual(count.read_text(encoding="utf-8"), "x")
                recovered = self.cli_packet("next", "--run-dir", self.run_dir)
                self.assertNotEqual(recovered["status"], "complete")
                self.assertEqual(recovered["action_id"], first["action_id"])
                self.cli_failure_or_parked(
                    "execute", "--run-dir", self.run_dir, "--action", first["action_id"], timeout=10
                )
                self.assertEqual(count.read_text(encoding="utf-8"), "x")

    def test_init_freezes_definition_instead_of_reloading_changed_source_file(self) -> None:
        original = self.simple_document(
            [
                self.command_step(
                    "frozen",
                    "from pathlib import Path; Path('frozen.txt').write_text('original')",
                    ["frozen.txt"],
                    needs=[],
                )
            ]
        )
        first = self.init_workflow(original)
        changed = self.simple_document(
            [
                self.command_step(
                    "frozen",
                    "from pathlib import Path; Path('changed.txt').write_text('changed')",
                    ["changed.txt"],
                    needs=[],
                )
            ]
        )
        self.write_workflow(changed)

        terminal = self.cli_packet(
            "execute", "--run-dir", self.run_dir, "--action", first["action_id"]
        )
        workspace = Path(terminal["workspace"])
        self.assertEqual((workspace / "frozen.txt").read_text(encoding="utf-8"), "original")
        self.assertFalse((workspace / "changed.txt").exists())

    def test_changed_accepted_evidence_is_detected_on_cold_hydration(self) -> None:
        first = self.init_workflow(
            self.simple_document(
                [
                    self.command_step(
                        "write",
                        "from pathlib import Path; Path('evidence.txt').write_text('accepted')",
                        ["evidence.txt"],
                        needs=[],
                    )
                ]
            )
        )
        terminal = self.cli_packet(
            "execute", "--run-dir", self.run_dir, "--action", first["action_id"]
        )
        self.assertEqual(terminal["status"], "complete")
        (Path(terminal["workspace"]) / "evidence.txt").write_text("mutated", encoding="utf-8")

        completed = self.raw_cli("next", "--run-dir", self.run_dir)
        packet = self.parse_packet(completed)
        self.assertFalse(
            completed.returncode == 0 and packet.get("status") == "complete",
            f"changed accepted evidence was silently accepted: {packet!r}",
        )

    def test_live_execute_is_not_reconciled_as_in_doubt_by_concurrent_next(self) -> None:
        """A live command owner survives a concurrent recovery request."""
        first = self.init_workflow(
            self.simple_document(
                [
                    self.command_step(
                        "slow-write",
                        "from pathlib import Path; import time; "
                        "Path('started.txt').write_text('started'); time.sleep(0.5); "
                        "Path('output.txt').write_text('done')",
                        ["output.txt"],
                        needs=[],
                        timeout_seconds=5,
                    )
                ]
            )
        )
        execute_args = [
            PYTHON,
            str(CLI),
            "execute",
            "--run-dir",
            str(self.run_dir),
            "--action",
            first["action_id"],
        ]
        executing = subprocess.Popen(
            execute_args,
            cwd=self.base,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            started = Path(first["workspace"]) / "started.txt"
            deadline = time.monotonic() + 5
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(started.is_file(), "the command never reached its live phase")

            during = self.cli_packet("next", "--run-dir", self.run_dir)
            self.assertEqual(during["status"], "executing")
            self.assertEqual(during["action_id"], first["action_id"])

            stdout, stderr = executing.communicate(timeout=10)
        except BaseException:
            if executing.poll() is None:
                executing.terminate()
                executing.communicate(timeout=10)
            raise
        result = subprocess.CompletedProcess(
            execute_args, executing.returncode, stdout=stdout, stderr=stderr
        )
        terminal = self.parse_packet(result)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(terminal["status"], "complete")
        self.assertEqual((Path(terminal["workspace"]) / "output.txt").read_text(), "done")

    def test_command_verifier_cannot_mutate_accepted_dependency_and_complete(self) -> None:
        mutates_prior = [
            PYTHON,
            "-c",
            "from pathlib import Path; Path('a.txt').write_text('mutated')",
        ]
        first = self.init_workflow(
            self.simple_document(
                [
                    self.command_step(
                        "a",
                        "from pathlib import Path; Path('a.txt').write_text('accepted')",
                        ["a.txt"],
                        needs=[],
                    ),
                    {
                        **self.command_step(
                            "b",
                            "from pathlib import Path; Path('b.txt').write_text('candidate')",
                            ["b.txt"],
                            needs=["a"],
                        ),
                        "verify": [mutates_prior],
                    },
                ]
            )
        )
        second = self.cli_packet(
            "execute", "--run-dir", self.run_dir, "--action", first["action_id"]
        )
        outcome = self.cli_failure_or_parked(
            "execute", "--run-dir", self.run_dir, "--action", second["action_id"]
        )
        self.assertNotEqual(outcome.get("status"), "complete")

    def test_prompt_verifier_cannot_mutate_accepted_dependency_and_complete(self) -> None:
        mutates_prior = [
            PYTHON,
            "-c",
            "from pathlib import Path; Path('a.txt').write_text('mutated')",
        ]
        first = self.init_workflow(
            self.simple_document(
                [
                    self.command_step(
                        "a",
                        "from pathlib import Path; Path('a.txt').write_text('accepted')",
                        ["a.txt"],
                        needs=[],
                    ),
                    {
                        **self.prompt_step("b", outputs=["b.txt"]),
                        "needs": ["a"],
                        "verify": [mutates_prior],
                    },
                ]
            )
        )
        prompt = self.cli_packet(
            "execute", "--run-dir", self.run_dir, "--action", first["action_id"]
        )
        (Path(prompt["workspace"]) / "b.txt").write_text("candidate", encoding="utf-8")
        result = self.write_result("prompt-mutates-prior.json", "succeeded", "wrote candidate")
        outcome = self.complete(prompt["action_id"], result, tolerate_failure=True)
        self.assertNotEqual(outcome.get("status"), "complete")

    def test_verifier_hashes_current_output_after_it_changes_the_output(self) -> None:
        rewrite_current = [
            PYTHON,
            "-c",
            "from pathlib import Path; Path('current.txt').write_text('final')",
        ]
        for kind in ("command", "prompt"):
            with self.subTest(kind=kind):
                self.repo = self.base / f"{kind}-repo"
                self.repo.mkdir()
                self.run_dir = self.base / f"{kind}-run"
                if kind == "command":
                    step = self.command_step(
                        "current",
                        "from pathlib import Path; Path('current.txt').write_text('initial')",
                        ["current.txt"],
                        needs=[],
                    )
                else:
                    step = self.prompt_step("current", outputs=["current.txt"])
                    step["needs"] = []
                step["verify"] = [rewrite_current]
                first = self.init_workflow(self.simple_document([step]))
                if kind == "command":
                    terminal = self.cli_packet(
                        "execute", "--run-dir", self.run_dir, "--action", first["action_id"]
                    )
                else:
                    (Path(first["workspace"]) / "current.txt").write_text(
                        "initial", encoding="utf-8"
                    )
                    result = self.write_result(
                        f"{kind}-current.json", "succeeded", "wrote current output"
                    )
                    terminal = self.complete(first["action_id"], result)
                self.assertEqual(terminal["status"], "complete")
                current = Path(terminal["workspace"]) / "current.txt"
                self.assertEqual(current.read_text(encoding="utf-8"), "final")
                state = self.read_state()
                evidence = state["completed"]["current"]["outputs"][0]
                self.assertEqual(
                    evidence["sha256"], hashlib.sha256(b"final").hexdigest()
                )
                cold = self.cli_packet("next", "--run-dir", self.run_dir)
                self.assertEqual(cold["status"], "complete")

    def test_tampering_with_an_accepted_execution_log_is_detected(self) -> None:
        first = self.init_workflow(
            self.simple_document(
                [
                    self.command_step(
                        "logged",
                        "from pathlib import Path; print('recorded log'); "
                        "Path('artifact.txt').write_text('accepted')",
                        ["artifact.txt"],
                        needs=[],
                    )
                ]
            )
        )
        terminal = self.cli_packet(
            "execute", "--run-dir", self.run_dir, "--action", first["action_id"]
        )
        self.assertEqual(terminal["status"], "complete")
        logs = list((self.run_dir / "logs").glob("*.stdout.log"))
        self.assertEqual(len(logs), 1)
        logs[0].write_text("tampered log", encoding="utf-8")
        tampered = self.raw_cli("next", "--run-dir", self.run_dir)
        packet = self.parse_packet(tampered)
        self.assertFalse(
            tampered.returncode == 0 and packet.get("status") == "complete",
            f"tampered accepted command log was silently accepted: {packet!r}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
