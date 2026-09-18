"""Black-box regressions for durable pre-dispatch delegation blocks.

An unavailable ask-agent/native dispatch capability is a host limitation, not a
reason for the host to invent a dispatch handle.  These tests ensure the script
records that boundary before launch and keeps recovery under its own callbacks.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLI = Path(
    os.environ.get(
        "WEAVE_TEST_CLI", ROOT / "skills" / "workflow" / "scripts" / "workflow"
    )
).expanduser().resolve()
PYTHON = sys.executable


class MissingDelegationTests(unittest.TestCase):
    """Exercise the public capability-block callback through fresh CLI processes."""

    maxDiff = None

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-missing-delegation-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.run = self.base / "run"
        self.workflow = self.base / "workflow.json"
        self.results = self.base / "results"
        self._owned_cli: list[subprocess.Popen[str]] = []
        self._owned_verifiers: list[tuple[Path, Path]] = []
        self.addCleanup(self._cleanup_owned_processes)

    # ---- Public CLI and durable-file helpers --------------------------

    def raw(self, *args: object, timeout: float = 15) -> subprocess.CompletedProcess[str]:
        self.assertTrue(CLI.is_file(), f"workflow CLI not found: {CLI}")
        return subprocess.run(
            [PYTHON, str(CLI), *(str(arg) for arg in args)],
            cwd=self.base,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def decode(self, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        self.assertTrue(
            result.stdout.strip(),
            f"CLI must emit one JSON packet\nstderr:\n{result.stderr}",
        )
        try:
            packet = json.loads(result.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic only
            self.fail(f"CLI stdout was not a JSON packet: {result.stdout!r}\n{exc}")
        self.assertIsInstance(packet, dict)
        return packet

    def call(self, *args: object, timeout: float = 15) -> dict[str, Any]:
        result = self.raw(*args, timeout=timeout)
        packet = self.decode(result)
        self.assertEqual(
            result.returncode,
            0,
            f"CLI failed for {args!r}: {packet!r}\nstderr:\n{result.stderr}",
        )
        return packet

    def error(self, *args: object, timeout: float = 15) -> dict[str, Any]:
        result = self.raw(*args, timeout=timeout)
        packet = self.decode(result)
        self.assertNotEqual(result.returncode, 0, f"expected failure: {packet!r}")
        self.assertEqual(packet.get("status"), "error")
        return packet

    def start_cli(self, *args: object) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [PYTHON, str(CLI), *(str(arg) for arg in args)],
            cwd=self.base,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self._owned_cli.append(process)
        return process

    def collect_cli(
        self, process: subprocess.Popen[str], *, timeout: float = 10
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
        stdout, stderr = process.communicate(timeout=timeout)
        if process in self._owned_cli:
            self._owned_cli.remove(process)
        result = subprocess.CompletedProcess(
            process.args, process.returncode, stdout=stdout, stderr=stderr
        )
        return result, self.decode(result)

    @staticmethod
    def _close_pipes(process: subprocess.Popen[str]) -> None:
        for pipe in (process.stdout, process.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()

    def _cleanup_owned_processes(self) -> None:
        unreleased: list[Path] = []
        for release, done in self._owned_verifiers:
            if done.exists():
                continue
            release.touch(exist_ok=True)
            deadline = time.monotonic() + 1
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not done.exists():
                unreleased.append(done)
        self._owned_verifiers.clear()

        for process in list(self._owned_cli):
            if process.poll() is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=2)
            self._close_pipes(process)
        self._owned_cli.clear()

        if unreleased:
            self.fail(
                "verifier child did not exit after cooperative release: "
                + ", ".join(str(path) for path in unreleased)
            )

    def read_state(self) -> dict[str, Any]:
        text = (self.run / "state.md").read_text(encoding="utf-8")
        opening = "```workflow-state\n"
        self.assertIn(opening, text)
        payload = text.split(opening, 1)[1].split("\n```", 1)[0]
        state = json.loads(payload)
        self.assertIsInstance(state, dict)
        return state

    def receipt_payload(self, relative_path: str) -> dict[str, Any]:
        text = (self.run / relative_path).read_text(encoding="utf-8")
        opening = text.find("```")
        self.assertGreaterEqual(opening, 0, f"receipt lacks a JSON fence: {relative_path}")
        content_start = text.find("\n", opening)
        content_end = text.find("\n```", content_start)
        self.assertGreater(content_start, opening)
        self.assertGreater(content_end, content_start)
        payload = json.loads(text[content_start + 1 : content_end])
        self.assertIsInstance(payload, dict)
        return payload

    @staticmethod
    def document(steps: list[dict[str, Any]], *, name: str) -> dict[str, Any]:
        return {
            "version": 1,
            "name": name,
            "goal": "Keep unavailable native delegation as durable script-owned state.",
            "steps": steps,
        }

    @staticmethod
    def agent(
        step_id: str,
        output: str,
        *,
        needs: Iterable[str] = (),
        verify: list[str] | None = None,
    ) -> dict[str, Any]:
        step: dict[str, Any] = {
            "id": step_id,
            "kind": "agent",
            "needs": list(needs),
            "prompt": f"Write only {output} for {step_id}.",
            "outputs": [output],
            "timeout_seconds": 10,
        }
        if verify is not None:
            step["verify"] = [verify]
        return step

    def init(self, document: dict[str, Any], *, frontier: bool = False) -> dict[str, Any]:
        self.workflow.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        args: list[object] = [
            "init",
            "--workflow",
            self.workflow,
            "--run-dir",
            self.run,
            "--repo",
            self.repo,
        ]
        if frontier:
            args.extend(["--max-active", 2, "--shared-workspace-disjoint"])
        return self.call(*args)

    def claim(self, request_id: str, *, limit: int = 2) -> dict[str, Any]:
        return self.call(
            "claim-ready",
            "--run-dir",
            self.run,
            "--limit",
            limit,
            "--request-id",
            request_id,
        )

    def block(self, action_id: str, reason: str) -> dict[str, Any]:
        return self.call(
            "block",
            "--run-dir",
            self.run,
            "--action",
            action_id,
            "--reason",
            reason,
        )

    def assert_block_template(self, packet: dict[str, Any]) -> None:
        templates = packet.get("allowed_operations")
        self.assertIsInstance(templates, dict)
        assert isinstance(templates, dict)
        argv = templates.get("block")
        self.assertIsInstance(argv, list, packet)
        assert isinstance(argv, list)
        self.assertGreaterEqual(len(argv), 8, argv)
        self.assertEqual(argv[:2], [str(CLI), "block"])
        self.assertEqual(argv[argv.index("--run-dir") + 1], str(self.run.resolve()))
        self.assertEqual(argv[argv.index("--action") + 1], packet["action_id"])
        reason_index = argv.index("--reason")
        self.assertIsInstance(argv[reason_index + 1], str)
        self.assertTrue(argv[reason_index + 1])

    def write_outputs(self, packet: dict[str, Any]) -> None:
        workspace = Path(str(packet["workspace"]))
        outputs = packet.get("declared_outputs", packet.get("outputs", []))
        self.assertTrue(outputs, packet)
        for output in outputs:
            target = workspace / str(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"{packet['step_id']} evidence\n", encoding="utf-8")

    def result_file(self, packet: dict[str, Any]) -> Path:
        self.results.mkdir(exist_ok=True)
        path = self.results / f"{packet['action_id']}.json"
        path.write_text(
            json.dumps({"status": "succeeded", "summary": "native capability restored"}),
            encoding="utf-8",
        )
        return path

    def prepare_and_dispatch(self, packet: dict[str, Any]) -> None:
        self.call("prepare-dispatch", "--run-dir", self.run, "--action", packet["action_id"])
        self.call(
            "dispatch",
            "--run-dir",
            self.run,
            "--action",
            packet["action_id"],
            "--handle",
            f"delegation-test-{packet['action_id']}",
        )

    def complete_agent(self, packet: dict[str, Any]) -> dict[str, Any]:
        self.prepare_and_dispatch(packet)
        self.write_outputs(packet)
        return self.call(
            "complete",
            "--run-dir",
            self.run,
            "--action",
            packet["action_id"],
            "--result",
            self.result_file(packet),
        )

    @staticmethod
    def action_from_state(state: dict[str, Any], action_id: str) -> dict[str, Any]:
        current = state.get("current_action")
        if isinstance(current, dict) and current.get("id") == action_id:
            return current
        active = state.get("active_actions", [])
        if isinstance(active, list):
            for action in active:
                if isinstance(action, dict) and action.get("id") == action_id:
                    return action
        raise AssertionError(f"active action not found: {action_id}")

    @staticmethod
    def packets_by_step(packets: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {str(packet["step_id"]): packet for packet in packets}

    def wait_for_file(self, path: Path, *, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.is_file():
                return
            time.sleep(0.01)
        self.fail(f"timed out waiting for {path}")

    def blocking_verifier(self, marker: Path, release: Path, done: Path) -> list[str]:
        code = "\n".join(
            [
                "from pathlib import Path",
                "import time",
                f"marker = Path({str(marker)!r})",
                f"release = Path({str(release)!r})",
                f"done = Path({str(done)!r})",
                "marker.write_text('started', encoding='utf-8')",
                "while not release.exists():",
                "    time.sleep(0.01)",
                "done.write_text('done', encoding='utf-8')",
            ]
        )
        return [PYTHON, "-c", code]

    # ---- Ready-agent capability blocks --------------------------------

    def test_serial_block_is_durable_without_handle_and_retry_recovers(self) -> None:
        first = self.init(
            self.document([self.agent("review", "review.txt")], name="serial-capability-gap")
        )
        self.assertEqual(first["status"], "ready")
        self.assertEqual(first["kind"], "agent")
        self.assert_block_template(first)

        unavailable = "ask-agent native dispatch is unavailable on this host"
        blocked = self.block(first["action_id"], unavailable)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["action_id"], first["action_id"])
        self.assertEqual(blocked["kind"], "agent")

        state = self.read_state()
        action = self.action_from_state(state, first["action_id"])
        self.assertEqual(action["status"], "blocked")
        self.assertNotIn("dispatch", action, "capability block must not invent a native handle")
        callback = state["callbacks"][first["action_id"]]
        self.assertEqual(callback["status"], "blocked")
        receipt = self.receipt_payload(callback["receipt_path"])
        self.assertEqual(receipt["result"], {"status": "blocked", "summary": unavailable})

        cold = self.call("next", "--run-dir", self.run)
        self.assertEqual(cold["status"], "blocked")
        self.assertEqual(cold["action_id"], first["action_id"])
        self.error(
            "dispatch",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--handle",
            "invented-after-block",
        )
        self.error(
            "retry",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--reason",
            "capability restored",
        )

        retry = self.call(
            "retry",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--reason",
            "ask-agent capability restored and former worker is absent",
            "--confirmed-stopped",
        )
        self.assertEqual(retry["status"], "ready")
        self.assertNotEqual(retry["action_id"], first["action_id"])
        self.assert_block_template(retry)

        terminal = self.complete_agent(retry)
        self.assertEqual(terminal["status"], "complete")

    def test_identical_block_replays_but_conflicting_and_stale_blocks_are_fenced(self) -> None:
        first = self.init(
            self.document([self.agent("review", "review.txt")], name="block-idempotency")
        )
        reason = "selected ask-agent route is not installed"
        blocked = self.block(first["action_id"], reason)
        before = self.read_state()["callbacks"][first["action_id"]]

        replay = self.block(first["action_id"], reason)
        self.assertEqual(replay["status"], "blocked")
        self.assertEqual(replay["action_id"], first["action_id"])
        after_state = self.read_state()
        self.assertEqual(after_state["callbacks"][first["action_id"]], before)
        self.assertEqual(len(after_state["callbacks"]), 1)

        self.error(
            "block",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--reason",
            "different host explanation",
        )
        retry = self.call(
            "retry",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--reason",
            "native delegation was restored",
            "--confirmed-stopped",
        )
        self.assertNotEqual(retry["action_id"], first["action_id"])
        self.error(
            "block",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--reason",
            reason,
        )
        self.assertEqual(self.read_state()["callbacks"][first["action_id"]], before)

    def test_block_rejects_dispatching_and_dispatched_actions(self) -> None:
        first = self.init(
            self.document([self.agent("review", "review.txt")], name="block-dispatch-states")
        )
        self.call("prepare-dispatch", "--run-dir", self.run, "--action", first["action_id"])
        self.error(
            "block",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--reason",
            "late capability report",
        )
        self.assertEqual(self.call("next", "--run-dir", self.run)["status"], "dispatching")

        self.call(
            "dispatch",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--handle",
            "actual-native-handle",
        )
        self.error(
            "block",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--reason",
            "late capability report",
        )
        self.assertEqual(self.call("next", "--run-dir", self.run)["status"], "dispatched")

    def test_block_rejects_a_live_verifying_callback(self) -> None:
        marker = self.repo / "verify.started"
        release = self.repo / "verify.release"
        done = self.repo / "verify.done"
        first = self.init(
            self.document(
                [
                    self.agent(
                        "review",
                        "review.txt",
                        verify=self.blocking_verifier(marker, release, done),
                    )
                ],
                name="block-verifying",
            )
        )
        self.prepare_and_dispatch(first)
        self.write_outputs(first)
        complete = self.start_cli(
            "complete",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--result",
            self.result_file(first),
        )
        self.wait_for_file(marker)
        self._owned_verifiers.append((release, done))
        self.assertEqual(self.call("next", "--run-dir", self.run, timeout=3)["status"], "verifying")

        self.error(
            "block",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--reason",
            "late capability report",
            timeout=3,
        )
        release.touch()
        self.wait_for_file(done)
        completed, terminal = self.collect_cli(complete)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(terminal["status"], "complete")

    def test_frontier_block_keeps_aggregate_incomplete_while_sibling_finishes(self) -> None:
        initial = self.init(
            self.document(
                [self.agent("A", "a.txt"), self.agent("B", "b.txt")],
                name="frontier-capability-gap",
            ),
            frontier=True,
        )
        self.assertEqual(initial["protocol"], "workflow-frontier-v2")
        claimed = self.claim("claim-independent-agents")
        packets = self.packets_by_step(claimed["claimed_packets"])
        self.assertEqual(set(packets), {"A", "B"})
        self.assert_block_template(packets["A"])
        self.assert_block_template(packets["B"])

        blocked = self.block(packets["A"]["action_id"], "ask-agent unavailable for A")
        self.assertEqual(blocked["protocol"], "workflow-frontier-v2")
        self.assertIsNone(blocked["action_id"])
        blocked_a = self.packets_by_step(blocked["active_packets"])["A"]
        self.assertEqual(blocked_a["action_id"], packets["A"]["action_id"])
        self.assertEqual(blocked_a["kind"], "agent")
        self.assertEqual(blocked_a["status"], "blocked")
        self.assertIn("retry", blocked_a["allowed_operations"])
        self.assertEqual(blocked["status"], "blocked")

        sibling_result = self.complete_agent(packets["B"])
        self.assertNotEqual(sibling_result["status"], "complete")
        parked = self.call("next", "--run-dir", self.run)
        self.assertEqual(parked["protocol"], "workflow-frontier-v2")
        self.assertEqual(parked["status"], "blocked")
        self.assertNotEqual(parked["status"], "complete")

        state = self.read_state()
        self.assertEqual(state["completed"]["B"]["action_id"], packets["B"]["action_id"])
        a_action = self.action_from_state(state, packets["A"]["action_id"])
        self.assertEqual(a_action["status"], "blocked")
        self.assertNotIn("dispatch", a_action)

        self.call(
            "retry",
            "--run-dir",
            self.run,
            "--action",
            packets["A"]["action_id"],
            "--reason",
            "ask-agent capability restored for A",
            "--confirmed-stopped",
        )
        recovered = self.call("next", "--run-dir", self.run)
        retry_a = self.packets_by_step(recovered["active_packets"])["A"]
        self.assertNotEqual(retry_a["action_id"], packets["A"]["action_id"])
        self.assertEqual(retry_a["status"], "ready")
        self.complete_agent(retry_a)
        self.assertEqual(self.call("next", "--run-dir", self.run)["status"], "complete")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
