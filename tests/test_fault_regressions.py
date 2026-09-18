"""Adversarial black-box regressions for workflow recovery and evidence safety.

Every runtime interaction goes through a fresh CLI process.  The suite retains
the ``Popen`` objects for every CLI it starts and signals those objects directly.
Verifier children are released cooperatively through test-only files, which
avoids signalling a marker PID that might have been reused after a crash.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unicodedata
import unittest
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
CLI = Path(
    os.environ.get(
        "WEAVE_TEST_CLI", ROOT / "skills" / "workflow" / "scripts" / "workflow"
    )
).expanduser().resolve()
PYTHON = sys.executable


class FaultRegressionTests(unittest.TestCase):
    """Exercise recovery boundaries without importing workflow implementation code."""

    maxDiff = None

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-fault-test-")
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

    # ---- JSON-only CLI/process helpers ---------------------------------

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
        except json.JSONDecodeError as exc:  # pragma: no cover - diagnostics
            self.fail(f"stdout was not a JSON packet: {result.stdout!r}\n{exc}")
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
        """Start a CLI callback and retain its process identity for cleanup."""
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

    def kill_cli_owner(self, process: subprocess.Popen[str]) -> None:
        self.assertIsNone(process.poll(), "CLI ended before its verifier became live")
        process.kill()
        process.wait(timeout=5)
        self._close_cli_pipes(process)
        if process in self._owned_cli:
            self._owned_cli.remove(process)

    def wait_for_file(self, path: Path, *, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.is_file():
                return
            time.sleep(0.01)
        self.fail(f"timed out waiting for {path}")

    @staticmethod
    def _close_cli_pipes(process: subprocess.Popen[str]) -> None:
        for pipe in (process.stdout, process.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()

    def _cleanup_owned_processes(self) -> None:
        unreleased: list[Path] = []
        for release, done in self._owned_verifiers:
            if done.exists():
                continue
            try:
                release.touch(exist_ok=True)
            except OSError:
                pass
            deadline = time.monotonic() + 1
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not done.exists():
                unreleased.append(done)
        self._owned_verifiers.clear()

        # Let a verifier finish before reaping its complete command: a verifier
        # can inherit the CLI's captured pipes, so waiting on those pipes first
        # could turn cleanup itself into a deadlock.
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
            self._close_cli_pipes(process)
        self._owned_cli.clear()

        if unreleased:
            self.fail(
                "verifier child did not exit after its cooperative release: "
                + ", ".join(str(path) for path in unreleased)
            )

    # ---- Workflow fixtures ---------------------------------------------

    @staticmethod
    def document(steps: list[dict[str, Any]], *, name: str = "fault-regression") -> dict[str, Any]:
        return {
            "version": 1,
            "name": name,
            "goal": "Prove recovery and evidence transitions remain script-owned.",
            "steps": steps,
        }

    @staticmethod
    def host_step(
        step_id: str,
        output: str,
        verifier: list[str],
        *,
        kind: str = "prompt",
        needs: Iterable[str] = (),
    ) -> dict[str, Any]:
        return {
            "id": step_id,
            "kind": kind,
            "needs": list(needs),
            "prompt": f"Write only {output} for {step_id}.",
            "outputs": [output],
            "verify": [verifier],
            "timeout_seconds": 10,
        }

    @staticmethod
    def prompt_step(step_id: str, output: str, *, needs: Iterable[str] = ()) -> dict[str, Any]:
        return {
            "id": step_id,
            "kind": "prompt",
            "needs": list(needs),
            "prompt": f"Write only {output} for {step_id}.",
            "outputs": [output],
        }

    def write_workflow(self, document: dict[str, Any], *, name: str = "workflow.json") -> Path:
        path = self.base / name
        path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def init(
        self,
        document: dict[str, Any],
        *,
        run: Path | None = None,
        repo: Path | None = None,
        frontier: bool = False,
    ) -> dict[str, Any]:
        args: list[object] = [
            "init",
            "--workflow",
            self.write_workflow(document),
            "--run-dir",
            run or self.run,
            "--repo",
            repo or self.repo,
        ]
        if frontier:
            args.extend(["--max-active", 2, "--shared-workspace-disjoint"])
        return self.call(*args)

    def result_file(self, action_id: str, summary: str = "verified") -> Path:
        self.results.mkdir(exist_ok=True)
        path = self.results / f"{action_id}-{summary.replace(' ', '-')}.json"
        path.write_text(
            json.dumps({"status": "succeeded", "summary": summary}), encoding="utf-8"
        )
        return path

    def prepare_agent(self, packet: dict[str, Any]) -> None:
        action_id = packet["action_id"]
        self.call("prepare-dispatch", "--run-dir", self.run, "--action", action_id)
        self.call(
            "dispatch",
            "--run-dir",
            self.run,
            "--action",
            action_id,
            "--handle",
            f"fault-native-{action_id}",
        )

    def blocking_verifier(
        self, *, marker: str, release: str, effects: str, done: str
    ) -> list[str]:
        code = "\n".join(
            [
                "from pathlib import Path",
                "import os, time",
                f"marker = Path({marker!r})",
                f"release = Path({release!r})",
                f"effects = Path({effects!r})",
                f"done = Path({done!r})",
                "marker.write_text(str(os.getpid()), encoding='utf-8')",
                "while not release.exists():",
                "    time.sleep(0.01)",
                "effects.write_text(",
                "    (effects.read_text(encoding='utf-8') if effects.exists() else '') + 'effect\\n',",
                "    encoding='utf-8',",
                ")",
                "done.write_text('done', encoding='utf-8')",
            ]
        )
        return [PYTHON, "-c", code]

    def register_verifier(self, workspace: Path, marker: str, release: str, done: str) -> tuple[Path, Path, Path]:
        marker_path = workspace / marker
        release_path = workspace / release
        done_path = workspace / done
        self.wait_for_file(marker_path)
        self._owned_verifiers.append((release_path, done_path))
        return marker_path, release_path, done_path

    def read_state(self) -> dict[str, Any]:
        text = (self.run / "state.md").read_text(encoding="utf-8")
        opening = "```workflow-state\n"
        self.assertIn(opening, text)
        payload = text.split(opening, 1)[1].split("\n```", 1)[0]
        state = json.loads(payload)
        self.assertIsInstance(state, dict)
        return state

    def start_succeeded_complete(
        self, packet: dict[str, Any], *, summary: str = "verified"
    ) -> tuple[subprocess.Popen[str], Path]:
        workspace = Path(packet["workspace"])
        output = str(packet.get("declared_outputs", packet["outputs"])[0])
        (workspace / output).write_text("evidence", encoding="utf-8")
        if packet["kind"] == "agent":
            self.prepare_agent(packet)
        result = self.result_file(packet["action_id"], summary)
        return (
            self.start_cli(
                "complete",
                "--run-dir",
                self.run,
                "--action",
                packet["action_id"],
                "--result",
                result,
            ),
            result,
        )

    # ---- Verifier owner recovery --------------------------------------

    def _killed_verifier_recovers_once(self, kind: str) -> None:
        marker, release, effects, done = (
            f"{kind}-verify.started",
            f"{kind}-verify.release",
            f"{kind}-verify.effects",
            f"{kind}-verify.done",
        )
        first = self.init(
            self.document(
                [
                    self.host_step(
                        "review",
                        "result.txt",
                        self.blocking_verifier(
                            marker=marker, release=release, effects=effects, done=done
                        ),
                        kind=kind,
                    )
                ],
                name=f"killed-{kind}-verifier",
            )
        )
        complete, result = self.start_succeeded_complete(first)
        workspace = Path(first["workspace"])
        marker_path, release_path, done_path = self.register_verifier(
            workspace, marker, release, done
        )

        self.kill_cli_owner(complete)
        cold = self.call("next", "--run-dir", self.run, timeout=3)
        self.assertEqual(cold["status"], "in_doubt")
        self.assertEqual(cold["action_id"], first["action_id"])

        # The same callback is fenced while the first verifier is still the
        # only worker permitted to write its effect.
        replay = self.raw(
            "complete",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--result",
            result,
            timeout=3,
        )
        replay_packet = self.decode(replay)
        self.assertNotEqual(replay.returncode, 0, replay_packet)
        self.assertFalse((workspace / effects).exists())

        release_path.touch()
        self.wait_for_file(done_path)
        self.assertEqual((workspace / effects).read_text(encoding="utf-8"), "effect\n")
        self.assertEqual(marker_path.read_text(encoding="utf-8").count("\n"), 0)

        retried = self.call(
            "retry",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--reason",
            "the killed verifier owner and its child are confirmed stopped",
            "--confirmed-stopped",
        )
        self.assertNotEqual(retried["action_id"], first["action_id"])
        self.assertEqual(retried["step_id"], "review")

    def test_prompt_verifier_owner_kill_recovers_in_doubt_and_fences_replay(self) -> None:
        self._killed_verifier_recovers_once("prompt")

    def test_agent_verifier_owner_kill_recovers_in_doubt_and_fences_replay(self) -> None:
        self._killed_verifier_recovers_once("agent")

    def test_cold_next_during_live_verifier_returns_verifying_and_completion_survives(self) -> None:
        marker, release, effects, done = (
            "live.started",
            "live.release",
            "live.effects",
            "live.done",
        )
        first = self.init(
            self.document(
                [
                    self.host_step(
                        "review",
                        "result.txt",
                        self.blocking_verifier(
                            marker=marker, release=release, effects=effects, done=done
                        ),
                    )
                ],
                name="live-verifier-next",
            )
        )
        complete, _ = self.start_succeeded_complete(first)
        workspace = Path(first["workspace"])
        _, release_path, done_path = self.register_verifier(workspace, marker, release, done)

        cold = self.call("next", "--run-dir", self.run, timeout=3)
        self.assertEqual(cold["status"], "verifying")
        self.assertEqual(cold["action_id"], first["action_id"])

        release_path.touch()
        self.wait_for_file(done_path)
        result, terminal = self.collect_cli(complete)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(terminal["status"], "complete")
        self.assertEqual((workspace / effects).read_text(encoding="utf-8"), "effect\n")
        self.assertEqual(self.call("next", "--run-dir", self.run)["status"], "complete")

    # ---- Callback concurrency -----------------------------------------

    @staticmethod
    def counted_verifier(counter: str) -> list[str]:
        code = (
            "from pathlib import Path; import time; "
            f"counter=Path({counter!r}); "
            "counter.write_text((counter.read_text(encoding='utf-8') if counter.exists() else '') "
            "+ 'check\\n', encoding='utf-8'); "
            "time.sleep(0.25)"
        )
        return [PYTHON, "-c", code]

    def test_simultaneous_identical_complete_runs_verifier_once(self) -> None:
        first = self.init(
            self.document(
                [
                    self.host_step(
                        "review", "result.txt", self.counted_verifier("checks.txt")
                    )
                ],
                name="same-callback-once",
            )
        )
        workspace = Path(first["workspace"])
        output = workspace / "result.txt"
        output.write_text("evidence", encoding="utf-8")
        result = self.result_file(first["action_id"], "same-callback")
        arguments = (
            "complete",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--result",
            result,
        )
        left = self.start_cli(*arguments)
        right = self.start_cli(*arguments)
        responses = [self.collect_cli(process) for process in (left, right)]
        for completed, packet in responses:
            self.assertEqual(completed.returncode, 0, packet)
            self.assertEqual(packet["status"], "complete")
        self.assertEqual((workspace / "checks.txt").read_text(encoding="utf-8"), "check\n")
        self.assertEqual(len(self.read_state()["callbacks"]), 1)

    def test_conflicting_simultaneous_complete_accepts_at_most_one_callback(self) -> None:
        first = self.init(
            self.document(
                [
                    self.host_step(
                        "review", "result.txt", self.counted_verifier("checks.txt")
                    )
                ],
                name="conflicting-callbacks",
            )
        )
        workspace = Path(first["workspace"])
        (workspace / "result.txt").write_text("evidence", encoding="utf-8")
        winner = self.result_file(first["action_id"], "winner")
        loser = self.result_file(first["action_id"], "loser")
        left = self.start_cli(
            "complete", "--run-dir", self.run, "--action", first["action_id"], "--result", winner
        )
        right = self.start_cli(
            "complete", "--run-dir", self.run, "--action", first["action_id"], "--result", loser
        )
        responses = [self.collect_cli(process) for process in (left, right)]
        successes = [
            packet
            for completed, packet in responses
            if completed.returncode == 0 and packet.get("status") == "complete"
        ]
        failures = [packet for completed, packet in responses if completed.returncode != 0]
        self.assertEqual(len(successes), 1, responses)
        self.assertEqual(len(failures), 1, responses)
        self.assertEqual((workspace / "checks.txt").read_text(encoding="utf-8"), "check\n")
        self.assertEqual(len(self.read_state()["callbacks"]), 1)

    def test_dead_verifier_a_is_not_masked_by_a_live_independent_b(self) -> None:
        a_marker, a_release, a_effects, a_done = (
            "a.started",
            "a.release",
            "a.effects",
            "a.done",
        )
        b_marker, b_release, b_effects, b_done = (
            "b.started",
            "b.release",
            "b.effects",
            "b.done",
        )
        document = self.document(
            [
                self.host_step(
                    "A",
                    "a.txt",
                    self.blocking_verifier(
                        marker=a_marker, release=a_release, effects=a_effects, done=a_done
                    ),
                    kind="agent",
                ),
                self.host_step(
                    "B",
                    "b.txt",
                    self.blocking_verifier(
                        marker=b_marker, release=b_release, effects=b_effects, done=b_done
                    ),
                    kind="agent",
                ),
            ],
            name="dead-a-live-b",
        )
        self.init(document, frontier=True)
        claimed = self.call(
            "claim-ready", "--run-dir", self.run, "--limit", 2, "--request-id", "claim-a-b"
        )
        packets = {packet["step_id"]: packet for packet in claimed["claimed_packets"]}
        self.assertEqual(set(packets), {"A", "B"})
        a, b = packets["A"], packets["B"]

        a_cli, _ = self.start_succeeded_complete(a, summary="a")
        workspace = Path(a["workspace"])
        _, release_path, done_path = self.register_verifier(workspace, a_marker, a_release, a_done)
        self.kill_cli_owner(a_cli)

        b_cli, _ = self.start_succeeded_complete(b, summary="b")
        _, b_release_path, b_done_path = self.register_verifier(
            workspace, b_marker, b_release, b_done
        )

        # B owns a live verifier lock, but it cannot make killed A look live.
        # This is a fresh process, rather than an in-memory state inspection.
        cold_during_b = self.call("next", "--run-dir", self.run, timeout=3)
        self.assertIn(cold_during_b["status"], {"verifying", "in_doubt"})

        state = self.read_state()
        active = {action["id"]: action for action in state["active_actions"]}
        self.assertEqual(active[a["action_id"]]["status"], "in_doubt")
        self.assertEqual(active[b["action_id"]]["status"], "verifying")

        b_release_path.touch()
        self.wait_for_file(b_done_path)
        b_result, b_packet = self.collect_cli(b_cli)
        self.assertEqual(b_result.returncode, 0, b_packet)
        self.assertIn(b_packet["status"], {"ready", "in_doubt"})
        after_b = self.call("next", "--run-dir", self.run)
        self.assertEqual(after_b["status"], "in_doubt")
        self.assertIn("B", self.read_state()["completed"])
        release_path.touch()
        self.wait_for_file(done_path)

    # ---- Output-alias and initialisation preflight --------------------

    def alias_document(self, outputs: list[str]) -> dict[str, Any]:
        return self.document(
            [self.prompt_step(f"step-{index}", output) for index, output in enumerate(outputs)],
            name="output-aliases",
        )

    def assert_init_rejected_without_action(self, document: dict[str, Any], *, label: str) -> None:
        run = self.base / f"{label}-run"
        self.error(
            "init",
            "--workflow",
            self.write_workflow(document, name=f"{label}.json"),
            "--run-dir",
            run,
            "--repo",
            self.repo,
        )
        self.assertFalse((run / "state.md").exists(), "invalid input issued an action")

    def test_casefold_unicode_normalization_and_prefix_aliases_reject_before_claim(self) -> None:
        composed = "café.txt"
        decomposed = unicodedata.normalize("NFD", composed)
        self.assertNotEqual(composed, decomposed)
        cases = {
            "casefold": ["Readme.txt", "README.TXT"],
            "unicode-normalized": [composed, decomposed],
            "prefix": ["reports", "reports/final.txt"],
        }
        for label, outputs in cases.items():
            with self.subTest(label=label):
                self.assert_init_rejected_without_action(
                    self.alias_document(outputs), label=label
                )

    def test_symlink_parent_alias_and_hardlinked_outputs_reject_before_action(self) -> None:
        real = self.repo / "real"
        real.mkdir()
        alias = self.repo / "alias"
        try:
            alias.symlink_to(real, target_is_directory=True)
        except OSError as exc:  # pragma: no cover - platform/filesystem guard
            self.skipTest(f"symlinks unavailable: {exc}")
        self.assert_init_rejected_without_action(
            self.alias_document(["real/evidence.txt", "alias/evidence.txt"]),
            label="symlink-parent",
        )

        left, right = self.repo / "left.txt", self.repo / "right.txt"
        left.write_text("shared", encoding="utf-8")
        try:
            os.link(left, right)
        except OSError as exc:  # pragma: no cover - platform/filesystem guard
            self.skipTest(f"hard links unavailable: {exc}")
        self.assert_init_rejected_without_action(
            self.alias_document(["left.txt", "right.txt"]), label="hardlink"
        )

    def test_distinct_unicode_output_paths_remain_valid(self) -> None:
        greek_alpha = "α.txt"
        cyrillic_a = "а.txt"
        self.assertNotEqual(
            unicodedata.normalize("NFC", greek_alpha).casefold(),
            unicodedata.normalize("NFC", cyrillic_a).casefold(),
        )
        packet = self.init(self.alias_document([greek_alpha, cyrillic_a]))
        self.assertEqual(packet["status"], "ready")
        self.assertIn(packet["step_id"], {"step-0", "step-1"})

if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
