"""Black-box contracts for the opt-in concurrent agent frontier.

The frontier is deliberately narrow: files remain the durable source of truth;
the CLI alone claims and transitions actions; tests simulate native agents by
writing only their declared evidence and recording an explicit native handle.
Nothing here imports the runtime, so each assertion also exercises cold recovery.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "workflow" / "scripts" / "workflow"
PYTHON = sys.executable
BACKCHAIN = Path(os.environ.get("WORKFLOW_TEST_BACKCHAIN_ROOT", ROOT.parent / "backchain"))


class FrontierCliTest(unittest.TestCase):
    """Exercise the public v2 packet protocol from fresh CLI processes."""

    maxDiff = None

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-frontier-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "workspace"
        self.repo.mkdir()
        self.run = self.base / "run"
        self.workflow = self.base / "workflow.json"
        self.results = self.base / "results"

    # ---- JSON-only public CLI helpers ---------------------------------

    def raw(self, *args: object, timeout: float = 15) -> subprocess.CompletedProcess[str]:
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
        except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic path
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

    def write_workflow(self, document: dict[str, Any]) -> Path:
        self.workflow.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        return self.workflow

    @staticmethod
    def document(steps: list[dict[str, Any]], name: str = "frontier-test") -> dict[str, Any]:
        return {
            "version": 1,
            "name": name,
            "goal": "Prove durable dependency-aware frontier execution.",
            "steps": steps,
        }

    @staticmethod
    def agent(
        step_id: str,
        output: str,
        *,
        needs: Iterable[str] = (),
    ) -> dict[str, Any]:
        return {
            "id": step_id,
            "kind": "agent",
            "needs": list(needs),
            "prompt": f"Write only {output} for step {step_id}.",
            "outputs": [output],
        }

    @staticmethod
    def command(
        step_id: str,
        output: str,
        *,
        needs: Iterable[str] = (),
    ) -> dict[str, Any]:
        return {
            "id": step_id,
            "kind": "command",
            "needs": list(needs),
            "argv": [
                PYTHON,
                "-c",
                (
                    "from pathlib import Path; "
                    f"Path({output!r}).write_text({step_id!r} + '\\n', encoding='utf-8')"
                ),
            ],
            "outputs": [output],
        }

    @staticmethod
    def prompt(
        step_id: str,
        output: str,
        *,
        needs: Iterable[str] = (),
    ) -> dict[str, Any]:
        return {
            "id": step_id,
            "kind": "prompt",
            "needs": list(needs),
            "prompt": f"Write only {output} for prompt step {step_id}.",
            "outputs": [output],
        }

    def init(self, document: dict[str, Any], *, frontier: bool = True, max_active: int = 3) -> dict[str, Any]:
        workflow = self.write_workflow(document)
        args: list[object] = [
            "init",
            "--workflow",
            workflow,
            "--repo",
            self.repo,
            "--run-dir",
            self.run,
        ]
        if frontier:
            args.extend(["--max-active", max_active, "--shared-workspace-disjoint"])
        return self.call(*args)

    def frontier(self) -> dict[str, Any]:
        packet = self.call("next", "--run-dir", self.run)
        self.assertEqual(packet.get("protocol"), "workflow-frontier-v2")
        self.assertIsNone(packet.get("action_id"))
        self.assertIsInstance(packet.get("ready_frontier"), list)
        self.assertIsInstance(packet.get("active_packets"), list)
        self.assertIsInstance(packet.get("max_active"), int)
        self.assertIsInstance(packet.get("active_count"), int)
        return packet

    def claim(self, request_id: str, *, limit: int = 3) -> dict[str, Any]:
        packet = self.call(
            "claim-ready",
            "--run-dir",
            self.run,
            "--limit",
            limit,
            "--request-id",
            request_id,
        )
        self.assertEqual(packet.get("claim_request_id"), request_id)
        self.assertIsInstance(packet.get("claimed_action_ids"), list)
        self.assertIsInstance(packet.get("claimed_packets"), list)
        self.assertEqual(
            packet["claimed_action_ids"],
            [item["action_id"] for item in packet["claimed_packets"]],
        )
        return packet

    @staticmethod
    def packet_by_step(packets: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {str(packet["step_id"]): packet for packet in packets}

    def active_by_step(self, packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return self.packet_by_step(packet["active_packets"])

    def write_outputs(self, packet: dict[str, Any], *, marker: str | None = None) -> None:
        workspace = Path(str(packet["workspace"]))
        outputs = packet.get("declared_outputs", packet.get("outputs", []))
        self.assertTrue(outputs, f"agent packet has no declared outputs: {packet!r}")
        for index, declared in enumerate(outputs):
            relative = Path(str(declared))
            self.assertFalse(relative.is_absolute(), f"output escaped workspace: {declared!r}")
            self.assertNotIn("..", relative.parts, f"output escaped workspace: {declared!r}")
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                marker or f"{packet['step_id']}:{packet['action_id']}:{index}\\n",
                encoding="utf-8",
            )

    def result_file(self, packet: dict[str, Any], status: str = "succeeded") -> Path:
        self.results.mkdir(exist_ok=True)
        path = self.results / f"{packet['action_id']}-{status}.json"
        path.write_text(
            json.dumps({"status": status, "summary": f"{packet['step_id']} {status}"}),
            encoding="utf-8",
        )
        return path

    def prepare_and_dispatch(self, packet: dict[str, Any]) -> None:
        action_id = packet["action_id"]
        self.call("prepare-dispatch", "--run-dir", self.run, "--action", action_id)
        self.call(
            "dispatch",
            "--run-dir",
            self.run,
            "--action",
            action_id,
            "--handle",
            f"test-native-{action_id}",
        )

    def complete_agent(
        self,
        packet: dict[str, Any],
        *,
        status: str = "succeeded",
        already_dispatched: bool = False,
        marker: str | None = None,
    ) -> dict[str, Any]:
        if not already_dispatched:
            self.prepare_and_dispatch(packet)
        if status == "succeeded":
            self.write_outputs(packet, marker=marker)
        return self.call(
            "complete",
            "--run-dir",
            self.run,
            "--action",
            packet["action_id"],
            "--result",
            self.result_file(packet, status),
        )

    def complete_prompt(self, packet: dict[str, Any]) -> dict[str, Any]:
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

    def read_state(self) -> dict[str, Any]:
        text = (self.run / "state.md").read_text(encoding="utf-8")
        opening = "```workflow-state\n"
        self.assertIn(opening, text)
        payload = text.split(opening, 1)[1].split("\n```", 1)[0]
        state = json.loads(payload)
        self.assertIsInstance(state, dict)
        return state

    def assert_receipts_for(self, packets: Iterable[dict[str, Any]]) -> None:
        state = self.read_state()
        for packet in packets:
            step_id = packet["step_id"]
            completion = state["completed"][step_id]
            self.assertEqual(completion["action_id"], packet["action_id"])
            receipt = self.run / completion["receipt_path"]
            self.assertTrue(receipt.is_file(), f"missing receipt for {step_id}")
            self.assertIn(packet["action_id"], receipt.read_text(encoding="utf-8"))

    # ---- Compatibility and declaration policy -------------------------

    def test_v1_without_frontier_options_keeps_the_single_packet_contract(self) -> None:
        """The opt-in frontier never changes an existing serial run."""
        initial = self.init(
            self.document(
                [
                    self.command("A", "a.txt"),
                    self.command("B", "b.txt", needs=["A"]),
                ],
                name="v1-compatible",
            ),
            frontier=False,
        )
        self.assertEqual(initial.get("protocol"), "workflow-packet-v1")
        self.assertIsInstance(initial.get("action_id"), str)
        self.assertNotIn("ready_frontier", initial)
        legacy_state = self.read_state()
        self.assertEqual(legacy_state["schema"], "workflow-run")
        self.assertEqual(legacy_state["version"], 1)
        self.assertNotIn("execution_policy", legacy_state)
        terminal = self.call("run", "--run-dir", self.run)
        self.assertEqual(terminal.get("status"), "complete")
        self.assertEqual(self.call("next", "--run-dir", self.run).get("status"), "complete")

    def test_frontier_requires_explicit_shared_workspace_policy_and_disjoint_agent_outputs(self) -> None:
        document = self.document([self.agent("A", "a.txt")])
        workflow = self.write_workflow(document)
        self.error(
            "init", "--workflow", workflow, "--repo", self.repo,
            "--run-dir", self.base / "missing-policy", "--max-active", 2,
        )
        self.error(
            "init", "--workflow", workflow, "--repo", self.repo,
            "--run-dir", self.base / "missing-limit", "--shared-workspace-disjoint",
        )
        self.error(
            "init", "--workflow", workflow, "--repo", self.repo,
            "--run-dir", self.base / "single-slot", "--max-active", 1,
            "--shared-workspace-disjoint",
        )

        no_evidence = self.document(
            [
                {
                    "id": "A",
                    "kind": "agent",
                    "needs": [],
                    "prompt": "Do work without evidence.",
                    "outputs": [],
                }
            ]
        )
        workflow = self.write_workflow(no_evidence)
        self.error(
            "init", "--workflow", workflow, "--repo", self.repo,
            "--run-dir", self.base / "agent-without-evidence", "--max-active", 2,
            "--shared-workspace-disjoint",
        )

        colliding = self.document(
            [self.agent("A", "shared.txt"), self.agent("B", "shared.txt")]
        )
        workflow = self.write_workflow(colliding)
        self.error(
            "init", "--workflow", workflow, "--repo", self.repo,
            "--run-dir", self.base / "colliding-evidence", "--max-active", 2,
            "--shared-workspace-disjoint",
        )

    @unittest.skipUnless(
        (BACKCHAIN / "harness" / "run-prompt.sh").is_file(),
        "Backchain source checkout unavailable",
    )
    def test_prompt_planning_preserves_frontier_policy_through_real_backchain_packaging(self) -> None:
        """Prompt entry freezes a v2 command braid only after package validation."""
        request = "Build a four-step command braid from this exact request.\n"
        request_file = self.base / "frontier-request.txt"
        request_file.write_text(request, encoding="utf-8")
        planning = self.call(
            "init", "--prompt-file", request_file, "--backchain-root", BACKCHAIN,
            "--repo", self.repo, "--run-dir", self.run, "--max-active", 2,
            "--shared-workspace-disjoint",
        )
        self.assertEqual(planning["original_goal"], request)
        planning_action = planning["action_id"]
        before = self.read_state()
        expected_policy = {
            "mode": "shared-workspace-disjoint",
            "max_active": 2,
            "shared_workspace_disjoint": True,
        }
        self.assertEqual(before["execution_policy"], expected_policy)

        plan = {
            "goal": request,
            "initial_state": [],
            "steps": [
                {
                    "id": "S1",
                    "statement": "Write a durable seed artifact.",
                    "produces": ["seed artifact"],
                    "inputs": [],
                    "origin": "seed",
                },
                {
                    "id": "S2",
                    "statement": "Write the left result from the seed artifact.",
                    "produces": ["left artifact"],
                    "inputs": [{"need": "seed artifact", "from": "S1"}],
                    "origin": "seed",
                },
                {
                    "id": "S3",
                    "statement": "Write the right result from the seed artifact.",
                    "produces": ["right artifact"],
                    "inputs": [{"need": "seed artifact", "from": "S1"}],
                    "origin": "seed",
                },
                {
                    "id": "S4",
                    "statement": "Join the left and right artifacts.",
                    "produces": ["joined artifact"],
                    "inputs": [
                        {"need": "left artifact", "from": "S2"},
                        {"need": "right artifact", "from": "S3"},
                    ],
                    "origin": "seed",
                },
            ],
            "parallel_groups": [["S2", "S3"]],
            "unresolved": [],
            "goal_needs": ["joined artifact"],
        }
        bindings = {
            "S1": {
                "kind": "command",
                "argv": [
                    PYTHON,
                    "-c",
                    "from pathlib import Path; Path('seed.txt').write_text('seed\\n', encoding='utf-8')",
                ],
                "outputs": ["seed.txt"],
            },
            "S2": {
                "kind": "command",
                "argv": [
                    PYTHON,
                    "-c",
                    "from pathlib import Path; Path('left.txt').write_text(Path('seed.txt').read_text(encoding='utf-8') + 'left\\n', encoding='utf-8')",
                ],
                "outputs": ["left.txt"],
            },
            "S3": {
                "kind": "command",
                "argv": [
                    PYTHON,
                    "-c",
                    "from pathlib import Path; Path('right.txt').write_text(Path('seed.txt').read_text(encoding='utf-8') + 'right\\n', encoding='utf-8')",
                ],
                "outputs": ["right.txt"],
            },
            "S4": {
                "kind": "command",
                "argv": [
                    PYTHON,
                    "-c",
                    "from pathlib import Path; Path('joined.txt').write_text(Path('left.txt').read_text(encoding='utf-8') + Path('right.txt').read_text(encoding='utf-8'), encoding='utf-8')",
                ],
                "outputs": ["joined.txt"],
            },
        }
        plan_file = self.base / "frontier-plan.json"
        bindings_file = self.base / "frontier-bindings.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        bindings_file.write_text(json.dumps(bindings), encoding="utf-8")
        accepted = self.call(
            "accept-plan", "--run-dir", self.run, "--action", planning_action,
            "--plan", plan_file, "--bindings", bindings_file, timeout=90,
        )
        self.assertEqual(accepted["protocol"], "workflow-frontier-v2")
        self.assertEqual(accepted["max_active"], 2)
        self.assertEqual(self.read_state()["execution_policy"], expected_policy)

        # Frontier scheduling remains explicit and globally serial for these
        # commands, even though the accepted Backchain graph has a fork.
        for request_id, step_id in (
            ("backchain-s1", "S1"),
            ("backchain-s2", "S2"),
            ("backchain-s3", "S3"),
            ("backchain-s4", "S4"),
        ):
            claim = self.claim(request_id, limit=2)
            self.assertEqual(len(claim["claimed_packets"]), 1)
            action = claim["claimed_packets"][0]
            self.assertEqual((action["step_id"], action["kind"]), (step_id, "command"))
            self.call("execute", "--run-dir", self.run, "--action", action["action_id"])

        self.assertEqual(self.frontier()["status"], "complete")
        self.assertEqual(
            (self.repo / "joined.txt").read_text(encoding="utf-8"),
            "seed\nleft\nseed\nright\n",
        )

    # ---- Claim identity and race behavior ------------------------------

    def test_claim_request_is_idempotent_and_rejects_a_conflicting_limit(self) -> None:
        self.init(self.document([self.agent("A", "a.txt")]))
        first = self.claim("same-request", limit=1)
        self.assertFalse(first["claim_replayed"])
        self.assertEqual([item["step_id"] for item in first["claimed_packets"]], ["A"])
        replay = self.claim("same-request", limit=1)
        self.assertTrue(replay["claim_replayed"])
        self.assertEqual(replay["claimed_action_ids"], first["claimed_action_ids"])
        self.error(
            "claim-ready", "--run-dir", self.run, "--limit", 2,
            "--request-id", "same-request",
        )

    def test_three_independent_terminal_agents_stay_ready_until_the_last_accepted_receipt(self) -> None:
        """A caller may deliberately claim one terminal leaf at a time."""
        self.init(
            self.document(
                [
                    self.agent("A", "a.txt"),
                    self.agent("B", "b.txt"),
                    self.agent("C", "c.txt"),
                ],
                name="independent-terminal-leaves",
            ),
            max_active=3,
        )
        state = self.read_state()
        self.assertEqual(state["schema"], "workflow-run")
        self.assertEqual(state["version"], 2)
        self.assertEqual(
            state["execution_policy"],
            {
                "mode": "shared-workspace-disjoint",
                "max_active": 3,
                "shared_workspace_disjoint": True,
            },
        )

        a = self.claim("one-a", limit=1)["claimed_packets"]
        self.assertEqual([packet["step_id"] for packet in a], ["A"])
        self.complete_agent(a[0])
        after_a = self.frontier()  # Fresh CLI recovery, not an in-memory scheduler view.
        self.assertEqual(after_a["status"], "ready")
        self.assertEqual(after_a["active_count"], 0)
        self.assertEqual(
            {step["step_id"] for step in after_a["ready_frontier"]}, {"B", "C"}
        )
        self.assertEqual(set(self.read_state()["completed"]), {"A"})

        b = self.claim("one-b", limit=1)["claimed_packets"]
        self.assertEqual([packet["step_id"] for packet in b], ["B"])
        self.complete_agent(b[0])
        after_b = self.frontier()  # A second cold process must retain C as unclaimed.
        self.assertEqual(after_b["status"], "ready")
        self.assertEqual(after_b["active_count"], 0)
        self.assertEqual([step["step_id"] for step in after_b["ready_frontier"]], ["C"])
        self.assertEqual(set(self.read_state()["completed"]), {"A", "B"})

        c = self.claim("one-c", limit=1)["claimed_packets"]
        self.assertEqual([packet["step_id"] for packet in c], ["C"])
        self.complete_agent(c[0])
        terminal = self.frontier()
        self.assertEqual(terminal["status"], "complete")
        self.assertEqual(terminal["active_count"], 0)
        self.assertEqual(terminal["ready_frontier"], [])
        self.assert_receipts_for((a[0], b[0], c[0]))

    def test_simultaneous_claimers_receive_unique_action_identities(self) -> None:
        self.init(
            self.document(
                [
                    self.agent("A", "a.txt"),
                    self.agent("B", "b.txt"),
                    self.agent("C", "c.txt"),
                ]
            ),
            max_active=3,
        )

        def claim_once(index: int) -> subprocess.CompletedProcess[str]:
            return self.raw(
                "claim-ready", "--run-dir", self.run, "--limit", 1,
                "--request-id", f"race-{index}",
            )

        with ThreadPoolExecutor(max_workers=3) as workers:
            responses = list(workers.map(claim_once, range(3)))
        packets = [self.decode(response) for response in responses]
        for response, packet in zip(responses, packets):
            self.assertEqual(response.returncode, 0, packet)
            self.assertLessEqual(len(packet["claimed_packets"]), 1)

        claimed = [
            action
            for packet in packets
            for action in packet["claimed_packets"]
        ]
        self.assertEqual({action["step_id"] for action in claimed}, {"A", "B", "C"})
        action_ids = [action["action_id"] for action in claimed]
        self.assertEqual(len(set(action_ids)), 3)
        state = self.read_state()
        self.assertEqual(set(state["claim_requests"]), {"race-0", "race-1", "race-2"})
        self.assertEqual(
            {action["id"] for action in state["active_actions"]}, set(action_ids)
        )

    # ---- Fan-out, joins, and terminal evidence -------------------------

    def test_repeated_fork_join_fork_join_waits_for_every_leaf_and_writes_receipts(self) -> None:
        """A -> {B,C} -> D -> {E,F} -> G is a durable native-agent braid."""
        self.init(
            self.document(
                [
                    self.agent("A", "a.txt"),
                    self.agent("B", "b.txt", needs=["A"]),
                    self.agent("C", "c.txt", needs=["A"]),
                    self.agent("D", "d.txt", needs=["B", "C"]),
                    self.agent("E", "e.txt", needs=["D"]),
                    self.agent("F", "f.txt", needs=["D"]),
                    self.agent("G", "g.txt", needs=["E", "F"]),
                ],
                name="repeated-braid",
            ),
            max_active=3,
        )

        first = self.claim("claim-a", limit=3)
        a = self.packet_by_step(first["claimed_packets"])["A"]
        self.complete_agent(a)

        fork_one = self.claim("claim-bc", limit=3)
        by_step = self.packet_by_step(fork_one["claimed_packets"])
        self.assertEqual(set(by_step), {"B", "C"})
        b, c = by_step["B"], by_step["C"]
        for packet in (b, c):
            self.assertEqual(packet["workspace_lease"]["mode"], "declared-output-exclusive")
            self.assertEqual(packet["workspace_lease"]["paths"], packet["declared_outputs"])
        self.assertTrue(
            set(b["workspace_lease"]["paths"]).isdisjoint(c["workspace_lease"]["paths"])
        )

        # Two real CLI processes complete the independent leaves.  They are
        # intentionally prepared first, so the only concurrent operation is the
        # durable callback transition under the runtime's lock.
        for packet in (b, c):
            self.prepare_and_dispatch(packet)
            self.write_outputs(packet)

        def complete_from_process(packet: dict[str, Any]) -> subprocess.CompletedProcess[str]:
            return self.raw(
                "complete", "--run-dir", self.run, "--action", packet["action_id"],
                "--result", self.result_file(packet),
            )

        # Reverse submission order to prove the join is based on receipts, not
        # declaration order.  Each worker launches a separate CLI process.
        with ThreadPoolExecutor(max_workers=2) as workers:
            completed = list(workers.map(complete_from_process, (c, b)))
        for response in completed:
            packet = self.decode(response)
            self.assertEqual(response.returncode, 0, packet)

        join_one = self.claim("claim-d", limit=3)
        d = self.packet_by_step(join_one["claimed_packets"])["D"]
        self.assertEqual({item["step_id"] for item in d["dependencies"]}, {"B", "C"})
        self.complete_agent(d)

        fork_two = self.claim("claim-ef", limit=3)
        by_step = self.packet_by_step(fork_two["claimed_packets"])
        self.assertEqual(set(by_step), {"E", "F"})
        e, f = by_step["E"], by_step["F"]
        self.complete_agent(e)
        held = self.frontier()
        self.assertNotEqual(held["status"], "complete")
        self.assertIn("F", self.active_by_step(held))
        self.assertNotIn("G", {item["step_id"] for item in held["ready_frontier"]})
        self.complete_agent(f)

        final_claim = self.claim("claim-g", limit=3)
        g = self.packet_by_step(final_claim["claimed_packets"])["G"]
        self.complete_agent(g)
        terminal = self.frontier()
        self.assertEqual(terminal["status"], "complete")
        self.assertEqual(terminal["active_count"], 0)
        self.assertEqual(terminal["ready_frontier"], [])
        self.assert_receipts_for((a, b, c, d, e, f, g))

    def test_native_braid_example_executes_its_two_fan_outs_with_simulated_native_receipts(self) -> None:
        """The documented A -> {B,C} -> D -> {E,F} -> G example is runnable."""
        example = ROOT / "examples" / "native-braid.workflow.json"
        self.assertTrue(example.is_file())
        self.call(
            "init", "--workflow", example, "--repo", self.repo,
            "--run-dir", self.run, "--max-active", 3,
            "--shared-workspace-disjoint",
        )

        a = self.claim("example-a", limit=3)["claimed_packets"][0]
        self.assertEqual((a["step_id"], a["kind"]), ("A", "command"))
        self.call("execute", "--run-dir", self.run, "--action", a["action_id"])
        self.assertEqual(
            json.loads((self.repo / "brief.json").read_text(encoding="utf-8")),
            {"numbers": [2, 3, 5]},
        )

        first_fork = self.packet_by_step(self.claim("example-bc", limit=3)["claimed_packets"])
        self.assertEqual(set(first_fork), {"B", "C"})
        self.complete_agent(first_fork["B"], marker='{"count": 3}\n')
        self.complete_agent(first_fork["C"], marker='{"sum": 10}\n')

        d = self.claim("example-d", limit=3)["claimed_packets"][0]
        self.assertEqual((d["step_id"], d["kind"]), ("D", "command"))
        self.call("execute", "--run-dir", self.run, "--action", d["action_id"])
        self.assertEqual(
            json.loads((self.repo / "joined.json").read_text(encoding="utf-8")),
            {"count": 3, "sum": 10},
        )

        second_fork = self.packet_by_step(self.claim("example-ef", limit=3)["claimed_packets"])
        self.assertEqual(set(second_fork), {"E", "F"})
        self.complete_agent(second_fork["E"], marker="count=3\n")
        self.complete_agent(second_fork["F"], marker="sum=10\n")

        g = self.claim("example-g", limit=3)["claimed_packets"][0]
        self.assertEqual((g["step_id"], g["kind"]), ("G", "command"))
        self.call("execute", "--run-dir", self.run, "--action", g["action_id"])
        self.assertEqual(
            json.loads((self.repo / "terminal-proof.json").read_text(encoding="utf-8")),
            {"count": 3, "status": "complete", "sum": 10},
        )
        self.assertEqual(self.frontier()["status"], "complete")

    def test_direct_dependency_can_fan_out_before_an_unrelated_sibling_finishes(self) -> None:
        """Once B completes, D may start while independent C remains active."""
        self.init(
            self.document(
                [
                    self.agent("A", "a.txt"),
                    self.agent("B", "b.txt", needs=["A"]),
                    self.agent("C", "c.txt", needs=["A"]),
                    self.agent("D", "d.txt", needs=["B"]),
                    self.agent("G", "g.txt", needs=["C", "D"]),
                ]
            ),
            max_active=3,
        )
        a = self.packet_by_step(self.claim("a", limit=3)["claimed_packets"])["A"]
        self.complete_agent(a)
        first_fork = self.packet_by_step(self.claim("bc", limit=3)["claimed_packets"])
        b, c = first_fork["B"], first_fork["C"]
        self.prepare_and_dispatch(b)
        self.prepare_and_dispatch(c)
        self.complete_agent(b, already_dispatched=True)

        waiting = self.frontier()
        self.assertIn("C", self.active_by_step(waiting))
        self.assertIn("D", {item["step_id"] for item in waiting["ready_frontier"]})
        d = self.packet_by_step(self.claim("d-while-c-active", limit=1)["claimed_packets"])["D"]
        self.assertEqual([item["step_id"] for item in d["dependencies"]], ["B"])

        self.complete_agent(d)
        self.complete_agent(c, already_dispatched=True)
        g = self.packet_by_step(self.claim("g", limit=3)["claimed_packets"])["G"]
        self.complete_agent(g)
        self.assertEqual(self.frontier()["status"], "complete")

    # ---- Unresolved effects, retries, and global exclusivity -----------

    def _unresolved_leaf_case(self, status: str) -> None:
        self.init(
            self.document(
                [
                    self.agent("B", "b.txt"),
                    self.agent("C", "c.txt"),
                    self.agent("D", "d.txt"),
                ]
            ),
            max_active=2,
        )
        first = self.packet_by_step(self.claim(f"claim-{status}", limit=2)["claimed_packets"])
        b, c = first["B"], first["C"]
        self.prepare_and_dispatch(b)
        self.prepare_and_dispatch(c)
        self.complete_agent(b, status=status, already_dispatched=True)
        parked = self.frontier()
        self.assertEqual(parked["status"], status)
        self.assertIn("C", self.active_by_step(parked))

        # The independently dispatched sibling can still return evidence, and
        # a third disjoint leaf can start.  The unresolved B leaf nevertheless
        # keeps the workflow from claiming completion.
        self.complete_agent(c, already_dispatched=True)
        after_c = self.frontier()
        self.assertEqual(after_c["status"], status)
        self.assertNotEqual(after_c["status"], "complete")
        d = self.packet_by_step(
            self.claim(f"independent-{status}", limit=1)["claimed_packets"]
        )["D"]
        self.complete_agent(d)
        self.assertEqual(self.frontier()["status"], status)

        retried = self.call(
            "retry", "--run-dir", self.run, "--action", b["action_id"],
            "--reason", f"reconcile {status} worker", "--confirmed-stopped",
        )
        retry_frontier = retried if retried.get("protocol") == "workflow-frontier-v2" else self.frontier()
        retry_b = self.active_by_step(retry_frontier).get("B")
        self.assertIsNotNone(retry_b, "retry must immediately replace its fenced sibling")
        assert retry_b is not None
        self.assertNotEqual(retry_b["action_id"], b["action_id"])
        self.complete_agent(retry_b)
        self.assertEqual(self.frontier()["status"], "complete")

    def test_failed_leaf_holds_completion_until_it_is_retried(self) -> None:
        self._unresolved_leaf_case("failed")

    def test_blocked_leaf_holds_completion_until_it_is_retried(self) -> None:
        self._unresolved_leaf_case("blocked")

    def test_prepared_leaf_fences_old_callbacks_then_accepts_one_exact_replay(self) -> None:
        self.init(
            self.document([self.agent("A", "a.txt"), self.agent("B", "b.txt")]),
            max_active=2,
        )
        first = self.packet_by_step(self.claim("claim-ab", limit=2)["claimed_packets"])
        a, b = first["A"], first["B"]
        self.prepare_and_dispatch(a)
        self.call("prepare-dispatch", "--run-dir", self.run, "--action", b["action_id"])
        self.complete_agent(a, already_dispatched=True)

        held = self.frontier()
        self.assertNotEqual(held["status"], "complete")
        held_b = self.active_by_step(held)["B"]
        self.assertEqual(held_b["native_dispatch"]["state"], "prepared_in_doubt")
        instruction = held_b["native_dispatch"]["instruction"].lower()
        self.assertIn("fresh", instruction)
        self.assertIn("reconcil", instruction)

        retried = self.call(
            "retry", "--run-dir", self.run, "--action", b["action_id"],
            "--reason", "prepared host did not return a handle", "--confirmed-stopped",
        )
        retry_frontier = retried if retried.get("protocol") == "workflow-frontier-v2" else self.frontier()
        retry_b = self.active_by_step(retry_frontier).get("B")
        self.assertIsNotNone(retry_b, "retry must immediately replace its fenced sibling")
        assert retry_b is not None
        self.assertNotEqual(retry_b["action_id"], b["action_id"])
        self.error(
            "dispatch", "--run-dir", self.run, "--action", b["action_id"],
            "--handle", "stale-native-handle",
        )

        self.prepare_and_dispatch(retry_b)
        self.write_outputs(retry_b)
        result = self.result_file(retry_b)
        terminal = self.call(
            "complete", "--run-dir", self.run, "--action", retry_b["action_id"],
            "--result", result,
        )
        self.assertEqual(terminal["status"], "complete")
        replay = self.call(
            "complete", "--run-dir", self.run, "--action", retry_b["action_id"],
            "--result", result,
        )
        self.assertEqual(replay["status"], "complete")
        self.assertEqual(self.frontier()["status"], "complete")

    def test_command_and_prompt_claims_are_globally_exclusive(self) -> None:
        """Non-agent packets never join an active agent batch in v2."""
        self.init(
            self.document(
                [
                    self.command("C", "command.txt"),
                    self.prompt("P", "prompt.txt"),
                    self.agent("A", "agent.txt"),
                ]
            ),
            max_active=3,
        )
        command_claim = self.claim("claim-command", limit=3)
        self.assertEqual([packet["kind"] for packet in command_claim["claimed_packets"]], ["command"])
        command_packet = command_claim["claimed_packets"][0]
        self.call("execute", "--run-dir", self.run, "--action", command_packet["action_id"])

        prompt_claim = self.claim("claim-prompt", limit=3)
        self.assertEqual([packet["kind"] for packet in prompt_claim["claimed_packets"]], ["prompt"])
        self.complete_prompt(prompt_claim["claimed_packets"][0])

        agent_claim = self.claim("claim-agent", limit=3)
        self.assertEqual([packet["kind"] for packet in agent_claim["claimed_packets"]], ["agent"])
        self.complete_agent(agent_claim["claimed_packets"][0])
        self.assertEqual(self.frontier()["status"], "complete")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
