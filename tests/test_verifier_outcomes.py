"""Black-box tests for durable prompt and agent verifier outcomes.

These cases deliberately exercise callback-owned verification through fresh CLI
processes.  Current-output fingerprints and mutation of already accepted output
are covered without duplication in ``tests/test_engine.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Sequence

from spec_fixtures import specified


ROOT = Path(__file__).resolve().parents[1]
CLI = Path(
    os.environ.get("WEAVE_TEST_CLI", ROOT / "skills" / "workflow" / "scripts" / "workflow")
).expanduser().resolve()
PYTHON = sys.executable


class VerifierOutcomeTests(unittest.TestCase):
    """Keep verifier failure, timeout, retry, and cleanup observable in files."""

    maxDiff = None

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="workflow-verifier-outcomes-")
        self.addCleanup(self.tempdir.cleanup)
        self.base = Path(self.tempdir.name)
        self._cooperative_releases: set[tuple[Path, Path]] = set()
        self.addCleanup(self._release_owned_verifiers)

    def _new_case(self, label: str) -> None:
        self.case = self.base / label
        self.case.mkdir()
        self.repo = self.case / "repo"
        self.repo.mkdir()
        self.run = self.case / "run"
        self.results = self.case / "results"
        self.workflow = self.case / "workflow.json"

    def raw(self, *args: object, timeout: float = 15) -> subprocess.CompletedProcess[str]:
        self.assertTrue(CLI.is_file(), f"workflow CLI not found: {CLI}")
        return subprocess.run(
            [PYTHON, str(CLI), *(str(arg) for arg in args)],
            cwd=self.case,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def decode(self, completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        self.assertTrue(
            completed.stdout.strip(),
            f"CLI emitted no JSON; stderr:\n{completed.stderr}",
        )
        try:
            packet = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - assertion diagnostic
            self.fail(f"CLI stdout was not JSON: {completed.stdout!r}\n{exc}")
        self.assertIsInstance(packet, dict)
        return packet

    def call(self, *args: object, timeout: float = 15) -> dict[str, Any]:
        completed = self.raw(*args, timeout=timeout)
        packet = self.decode(completed)
        self.assertEqual(
            completed.returncode,
            0,
            f"CLI failed for {args!r}: {packet!r}\nstderr:\n{completed.stderr}",
        )
        return packet

    def error(self, *args: object, timeout: float = 15) -> dict[str, Any]:
        completed = self.raw(*args, timeout=timeout)
        packet = self.decode(completed)
        self.assertNotEqual(completed.returncode, 0, packet)
        self.assertEqual(packet.get("status"), "error")
        return packet

    def read_state(self) -> dict[str, Any]:
        text = (self.run / "state.md").read_text(encoding="utf-8")
        opening = "```workflow-state\n"
        self.assertIn(opening, text)
        payload = text.split(opening, 1)[1].split("\n```", 1)[0]
        state = json.loads(payload)
        self.assertIsInstance(state, dict)
        return state

    def result_file(self, action_id: str) -> Path:
        self.results.mkdir(exist_ok=True)
        path = self.results / f"{action_id}.json"
        path.write_text(
            json.dumps({"status": "succeeded", "summary": "host supplied evidence"}),
            encoding="utf-8",
        )
        return path

    def start_host_step(
        self,
        *,
        label: str,
        kind: str,
        checks: Sequence[Sequence[str]],
        timeout_seconds: float = 10,
    ) -> tuple[dict[str, Any], Path]:
        self._new_case(label)
        self.workflow.write_text(
            json.dumps(
                specified(
                    {
                        "version": 1,
                        "name": label,
                        "goal": "Record verifier outcomes before advancing the workflow.",
                        "steps": [
                            {
                                "id": "review",
                                "kind": kind,
                                "needs": [],
                                "prompt": "Write only review.txt.",
                                "outputs": ["review.txt"],
                                "verify": [list(check) for check in checks],
                                "timeout_seconds": timeout_seconds,
                            }
                        ],
                    }
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        packet = self.call(
            "init",
            "--workflow",
            self.workflow,
            "--run-dir",
            self.run,
            "--repo",
            self.repo,
        )
        self.assertEqual(packet["kind"], kind)
        workspace = Path(packet["workspace"])
        (workspace / "review.txt").write_text("host evidence\n", encoding="utf-8")
        if kind == "agent":
            self.call("prepare-dispatch", "--run-dir", self.run, "--action", packet["action_id"])
            self.call(
                "dispatch",
                "--run-dir",
                self.run,
                "--action",
                packet["action_id"],
                "--handle",
                f"verifier-outcome-{packet['action_id']}",
            )
        return packet, self.result_file(packet["action_id"])

    def complete(self, packet: dict[str, Any], result: Path) -> dict[str, Any]:
        return self.call(
            "complete",
            "--run-dir",
            self.run,
            "--action",
            packet["action_id"],
            "--result",
            result,
        )

    def start_complete(self, packet: dict[str, Any], result: Path) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [
                PYTHON,
                str(CLI),
                "complete",
                "--run-dir",
                str(self.run),
                "--action",
                str(packet["action_id"]),
                "--result",
                str(result),
            ],
            cwd=self.case,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(self._stop_callback, process)
        return process

    @staticmethod
    def _stop_callback(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=2)

    def wait_for_file(self, path: Path, *, timeout: float = 3) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.is_file():
                return
            time.sleep(0.02)
        self.fail(f"timed out waiting for verifier setup file: {path}")

    @staticmethod
    def _group_gone(pgid: int, *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:  # pragma: no cover - a test-owned group should be signalable
                return False
            time.sleep(0.02)
        return False

    def _release_owned_verifiers(self) -> None:
        for release, marker in self._cooperative_releases:
            try:
                release.touch(exist_ok=True)
            except OSError:
                pass
            if not marker.is_file():
                continue
            try:
                pgid = json.loads(marker.read_text(encoding="utf-8"))["pgid"]
            except (OSError, ValueError, TypeError, KeyError):
                continue
            if isinstance(pgid, int) and not self._group_gone(pgid, timeout=2):
                self.fail("test-owned verifier ignored its cooperative release")
        self._cooperative_releases.clear()

    def assert_timeout_group_stopped(self, pgid: int, release: Path) -> None:
        if self._group_gone(pgid, timeout=2):
            return
        # This fixture's parent and child both poll this test-owned release file.
        # Never signal a marker-derived process group: its ID might be reused.
        release.touch(exist_ok=True)
        released = self._group_gone(pgid, timeout=2)
        self.fail(
            "verifier process group survived the engine timeout"
            + (" and required cooperative release" if released else " and ignored cooperative release")
        )

    @staticmethod
    def append_check(line: str, *, fail: bool = False) -> list[str]:
        code = (
            "from pathlib import Path; "
            "path = Path('check-order.txt'); "
            "path.write_text((path.read_text(encoding='utf-8') if path.exists() else '') "
            f"+ {line!r} + '\\n', encoding='utf-8'); "
            + ("raise SystemExit(19)" if fail else "")
        )
        return [PYTHON, "-c", code]

    def test_prompt_and_agent_multi_check_failure_persists_attempt_and_fences_replay(self) -> None:
        """The first success survives, the failed second check stops the third, and retry fences it."""
        checks = [
            self.append_check("first"),
            self.append_check("second", fail=True),
            [
                PYTHON,
                "-c",
                "from pathlib import Path; Path('third-ran.txt').write_text('third', encoding='utf-8')",
            ],
        ]
        for kind in ("prompt", "agent"):
            with self.subTest(kind=kind):
                packet, result = self.start_host_step(
                    label=f"multi-check-{kind}", kind=kind, checks=checks
                )
                failed = self.complete(packet, result)
                self.assertEqual(failed["status"], "failed")
                self.assertEqual(failed["action_id"], packet["action_id"])

                workspace = Path(packet["workspace"])
                order = workspace / "check-order.txt"
                self.assertEqual(order.read_text(encoding="utf-8"), "first\nsecond\n")
                self.assertFalse((workspace / "third-ran.txt").exists())

                state = self.read_state()
                action = state["current_action"]
                self.assertEqual(action["status"], "failed")
                verification = action["verification"]
                self.assertEqual(verification["phase"], "failed")
                entries = verification["checks"]
                self.assertEqual([entry["index"] for entry in entries], [0, 1])
                self.assertEqual([entry["phase"] for entry in entries], ["finished", "finished"])
                self.assertEqual(entries[0]["returncode"], 0)
                self.assertEqual(entries[1]["returncode"], 19)
                self.assertEqual(state["callbacks"], {})
                self.assertEqual(state["completed"], {})

                cold = self.call("next", "--run-dir", self.run)
                self.assertEqual(cold["status"], "failed")
                self.assertEqual(cold["action_id"], packet["action_id"])
                self.error(
                    "complete",
                    "--run-dir",
                    self.run,
                    "--action",
                    packet["action_id"],
                    "--result",
                    result,
                )
                self.assertEqual(order.read_text(encoding="utf-8"), "first\nsecond\n")

                self.error(
                    "retry",
                    "--run-dir",
                    self.run,
                    "--action",
                    packet["action_id"],
                    "--reason",
                    "the failed verifier has stopped",
                )
                retried = self.call(
                    "retry",
                    "--run-dir",
                    self.run,
                    "--action",
                    packet["action_id"],
                    "--reason",
                    "the failed verifier has stopped",
                    "--confirmed-stopped",
                )
                self.assertEqual(retried["step_id"], "review")
                self.assertNotEqual(retried["action_id"], packet["action_id"])
                self.assertEqual(retried["status"], "ready")

    def test_verifier_timeout_persists_logs_and_process_identity_without_blind_replay(self) -> None:
        """A timed-out verifier is in doubt, its process group is gone, and its callback cannot restart it."""
        child_code = "\n".join(
            [
                "from pathlib import Path",
                "import os, time",
                "release = Path('timeout-release')",
                "Path('timeout-child.pid').write_text(str(os.getpid()), encoding='utf-8')",
                "while not release.exists():",
                "    time.sleep(0.01)",
                "Path('timeout-child.done').write_text('done', encoding='utf-8')",
            ]
        )
        parent_code = "\n".join(
            [
                "from pathlib import Path",
                "import json, os, subprocess, sys, time",
                "release = Path('timeout-release')",
                f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}])",
                "while not Path('timeout-child.pid').exists():",
                "    time.sleep(0.01)",
                "runs = Path('timeout-runs.txt')",
                "runs.write_text((runs.read_text(encoding='utf-8') if runs.exists() else '') + 'run\\n', encoding='utf-8')",
                "Path('timeout-marker.json').write_text(json.dumps({'pid': os.getpid(), 'pgid': os.getpgrp(), 'child': child.pid}), encoding='utf-8')",
                "while not release.exists():",
                "    time.sleep(0.01)",
                "Path('timeout-parent.done').write_text('done', encoding='utf-8')",
            ]
        )
        timeout_check = [
            PYTHON,
            "-c",
            parent_code,
        ]
        packet, result = self.start_host_step(
            label="timeout", kind="prompt", checks=[timeout_check], timeout_seconds=1
        )
        workspace = Path(packet["workspace"])
        release = workspace / "timeout-release"
        marker_path = workspace / "timeout-marker.json"
        self._cooperative_releases.add((release, marker_path))
        callback = self.start_complete(packet, result)
        self.wait_for_file(marker_path, timeout=3)
        stdout, stderr = callback.communicate(timeout=6)
        completed = subprocess.CompletedProcess(
            callback.args, callback.returncode, stdout=stdout, stderr=stderr
        )
        parked = self.decode(completed)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(parked["status"], "in_doubt")
        self.assertEqual(parked["action_id"], packet["action_id"])

        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        state = self.read_state()
        action = state["current_action"]
        self.assertEqual(action["status"], "in_doubt")
        verification = action["verification"]
        self.assertEqual(verification["phase"], "in_doubt")
        self.assertEqual(verification["owner"]["action_id"], packet["action_id"])
        self.assertIsInstance(verification["owner"]["pid"], int)
        self.assertEqual(len(verification["checks"]), 1)
        check = verification["checks"][0]
        self.assertEqual(check["phase"], "finished")
        self.assertTrue(check["timed_out"])
        self.assertIsInstance(check["pid"], int)
        self.assertIsInstance(check["pgid"], int)
        self.assertEqual(check["pid"], marker["pid"])
        self.assertEqual(check["pgid"], marker["pgid"])
        for path_key, hash_key in (("stdout_path", "stdout_sha256"), ("stderr_path", "stderr_sha256")):
            log = self.run / check[path_key]
            self.assertTrue(log.is_file(), log)
            self.assertEqual(check[hash_key], hashlib.sha256(log.read_bytes()).hexdigest())

        cold = self.call("next", "--run-dir", self.run)
        self.assertEqual(cold["status"], "in_doubt")
        self.assertEqual(cold["action_id"], packet["action_id"])
        self.error(
            "complete",
            "--run-dir",
            self.run,
            "--action",
            packet["action_id"],
            "--result",
            result,
        )
        self.assertEqual((workspace / "timeout-runs.txt").read_text(encoding="utf-8"), "run\n")
        self.assertTrue((workspace / "timeout-child.pid").is_file())
        self.assertEqual(int((workspace / "timeout-child.pid").read_text()), marker["child"])
        self.assert_timeout_group_stopped(check["pgid"], release)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
