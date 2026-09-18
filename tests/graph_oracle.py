"""Independent black-box oracle and driver for Weave frontier graphs.

This module deliberately does not import ``workflow_core`` or any runtime
module.  It models only the public graph and frontier contract, then interacts
with the executable CLI through JSON packets.  Its negative controls exercise
the oracle against synthetic packets; they never edit or mutate the runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping, Sequence

from spec_fixtures import specified


class OracleViolation(AssertionError):
    """The observed public packet violates the independently modeled contract."""


@dataclass(frozen=True)
class GraphStep:
    """The subset of a frozen workflow needed to reason about graph progress."""

    step_id: str
    kind: str
    needs: tuple[str, ...]
    outputs: tuple[str, ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise OracleViolation(message)


class GraphOracle:
    """A small, independent state model for the all-required frontier protocol."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        raw_steps = document.get("steps")
        _require(isinstance(raw_steps, list) and raw_steps, "oracle requires nonempty steps")
        self.steps: dict[str, GraphStep] = {}
        self.declaration_order: list[str] = []
        for raw in raw_steps:
            _require(isinstance(raw, Mapping), "oracle workflow step must be an object")
            step_id = raw.get("id")
            kind = raw.get("kind")
            needs = raw.get("needs")
            outputs = raw.get("outputs")
            _require(isinstance(step_id, str) and step_id, "oracle step id is invalid")
            _require(step_id not in self.steps, f"oracle duplicate step {step_id!r}")
            _require(kind in {"command", "prompt", "agent"}, f"oracle kind is invalid for {step_id}")
            _require(isinstance(needs, list), f"oracle needs must be explicit for {step_id}")
            _require(isinstance(outputs, list), f"oracle outputs must be explicit for {step_id}")
            _require(
                all(isinstance(value, str) and value for value in needs),
                f"oracle needs are invalid for {step_id}",
            )
            _require(
                all(isinstance(value, str) and value for value in outputs),
                f"oracle outputs are invalid for {step_id}",
            )
            self.steps[step_id] = GraphStep(step_id, str(kind), tuple(needs), tuple(outputs))
            self.declaration_order.append(step_id)
        for step in self.steps.values():
            _require(
                len(set(step.needs)) == len(step.needs),
                f"oracle duplicate dependency for {step.step_id}",
            )
            _require(
                set(step.needs).issubset(self.steps),
                f"oracle missing dependency for {step.step_id}",
            )
        self.topology = self._topological_order()
        self.completed: set[str] = set()
        self.active: dict[str, str] = {}

    def _topological_order(self) -> tuple[str, ...]:
        """Kahn ordering with declared order as the only tie breaker."""
        position = {step_id: index for index, step_id in enumerate(self.declaration_order)}
        remaining = {step_id: set(step.needs) for step_id, step in self.steps.items()}
        ordered: list[str] = []
        while remaining:
            ready = sorted(
                (step_id for step_id, needs in remaining.items() if not needs),
                key=position.__getitem__,
            )
            _require(bool(ready), "oracle graph contains a cycle")
            selected = ready[0]
            ordered.append(selected)
            del remaining[selected]
            for needs in remaining.values():
                needs.discard(selected)
        return tuple(ordered)

    def ready_steps(self) -> tuple[str, ...]:
        active_steps = set(self.active.values())
        return tuple(
            step_id
            for step_id in self.topology
            if step_id not in self.completed
            and step_id not in active_steps
            and all(need in self.completed for need in self.steps[step_id].needs)
        )

    def expected_claim(self, *, limit: int, max_active: int) -> tuple[str, ...]:
        """Model the documented bounded, exclusive selection policy."""
        _require(1 <= limit <= max_active, "oracle claim limit is out of range")
        capacity = max(0, max_active - len(self.active))
        ready = self.ready_steps()
        if not capacity or not ready:
            return ()
        active_kinds = [self.steps[step_id].kind for step_id in self.active.values()]
        if active_kinds:
            candidates = (
                tuple(step_id for step_id in ready if self.steps[step_id].kind == "agent")
                if all(kind == "agent" for kind in active_kinds)
                else ()
            )
        elif self.steps[ready[0]].kind == "agent":
            candidates = tuple(step_id for step_id in ready if self.steps[step_id].kind == "agent")
        else:
            candidates = (ready[0],)
        return candidates[: min(limit, capacity)]

    def all_required_complete(self) -> bool:
        return not self.active and self.completed == set(self.steps)

    def _check_receipts(self, packet: Mapping[str, Any], step: GraphStep) -> None:
        for field in ("direct_dependency_receipts", "dependencies"):
            receipts = packet.get(field)
            _require(isinstance(receipts, list), f"{step.step_id} packet lacks {field}")
            actual = tuple(item.get("step_id") for item in receipts if isinstance(item, Mapping))
            _require(
                len(actual) == len(receipts) and actual == step.needs,
                f"{step.step_id} {field} must be exactly its direct needs {step.needs}, got {actual}",
            )
            _require(
                len(set(actual)) == len(actual),
                f"{step.step_id} {field} repeats a receipt",
            )
            for receipt in receipts:
                assert isinstance(receipt, Mapping)  # established above for type checkers
                dependency = str(receipt["step_id"])
                _require(
                    dependency in self.completed,
                    f"{step.step_id} exposes unaccepted dependency receipt {dependency}",
                )
                path = receipt.get("receipt_path", receipt.get("path"))
                digest = receipt.get("sha256")
                _require(
                    isinstance(path, str) and Path(path).is_absolute(),
                    f"{step.step_id} receipt path for {dependency} is not absolute",
                )
                _require(
                    isinstance(digest, str) and len(digest) == 64 and all(
                        character in "0123456789abcdef" for character in digest
                    ),
                    f"{step.step_id} receipt hash for {dependency} is invalid",
                )

    def assert_action_packet(self, packet: Mapping[str, Any]) -> None:
        step_id = packet.get("step_id")
        _require(isinstance(step_id, str) and step_id in self.steps, "action packet names an unknown step")
        step = self.steps[step_id]
        _require(packet.get("kind") == step.kind, f"{step_id} action kind disagrees with workflow")
        _require(
            tuple(packet.get("declared_outputs", ())) == step.outputs,
            f"{step_id} action outputs disagree with workflow",
        )
        self._check_receipts(packet, step)
        _require(
            all(need in self.completed for need in step.needs),
            f"{step_id} was exposed before every direct dependency completed",
        )

    def _assert_active_constraints(
        self, packets: Sequence[Mapping[str, Any]], *, max_active: int
    ) -> None:
        _require(len(packets) <= max_active, "frontier exceeds its configured claim capacity")
        kinds = [packet.get("kind") for packet in packets]
        _require(
            len(packets) <= 1 or all(kind == "agent" for kind in kinds),
            "commands, prompts, and planning actions must remain globally exclusive",
        )
        leased: set[str] = set()
        for packet in packets:
            self.assert_action_packet(packet)
            if packet.get("kind") != "agent":
                continue
            step = self.steps[str(packet["step_id"])]
            lease = packet.get("workspace_lease")
            _require(isinstance(lease, Mapping), f"{step.step_id} agent lacks an output lease")
            _require(
                lease.get("mode") == "declared-output-exclusive"
                and tuple(lease.get("paths", ())) == step.outputs,
                f"{step.step_id} agent lease does not match its declared outputs",
            )
            overlap = leased.intersection(step.outputs)
            _require(not overlap, f"active agents have overlapping output leases: {sorted(overlap)}")
            leased.update(step.outputs)

    def assert_overview(self, packet: Mapping[str, Any]) -> None:
        _require(packet.get("protocol") == "workflow-frontier-v2", "expected a v2 frontier packet")
        max_active = packet.get("max_active")
        _require(isinstance(max_active, int) and max_active > 1, "frontier max_active is invalid")
        _require(packet.get("shared_workspace_disjoint") is True, "frontier disjoint policy is absent")
        ready = packet.get("ready_frontier")
        active = packet.get("active_packets")
        _require(isinstance(ready, list) and isinstance(active, list), "frontier lists are invalid")
        actual_ready = tuple(item.get("step_id") for item in ready if isinstance(item, Mapping))
        _require(
            len(actual_ready) == len(ready) and actual_ready == self.ready_steps(),
            f"ready frontier mismatch: expected {self.ready_steps()}, got {actual_ready}",
        )
        for preview in ready:
            assert isinstance(preview, Mapping)
            self.assert_action_packet(preview)
        active_pairs: list[tuple[str, str]] = []
        for item in active:
            _require(isinstance(item, Mapping), "active packet must be an object")
            action_id = item.get("action_id")
            step_id = item.get("step_id")
            _require(
                isinstance(action_id, str) and action_id and isinstance(step_id, str) and step_id,
                "active action identity is invalid",
            )
            active_pairs.append((action_id, step_id))
        _require(
            len({action_id for action_id, _ in active_pairs}) == len(active_pairs),
            "frontier has duplicate active action identities",
        )
        _require(
            len({step_id for _, step_id in active_pairs}) == len(active_pairs),
            "frontier has duplicate active step identities",
        )
        _require(
            dict(active_pairs) == self.active,
            f"active frontier mismatch: expected {self.active}, got {dict(active_pairs)}",
        )
        _require(packet.get("active_count") == len(active), "active_count disagrees with active packets")
        self._assert_active_constraints(active, max_active=max_active)
        self.assert_terminal(packet)

    def assert_terminal(self, packet: Mapping[str, Any]) -> None:
        terminal = self.all_required_complete()
        actual = packet.get("status") == "complete"
        _require(
            actual == terminal,
            "terminal status must be true exactly when every required step has an accepted receipt and no claim remains",
        )

    def observe_claim(self, response: Mapping[str, Any], *, limit: int) -> tuple[str, ...]:
        max_active = response.get("max_active")
        _require(isinstance(max_active, int), "claim response has no max_active")
        expected = self.expected_claim(limit=limit, max_active=max_active)
        packets = response.get("claimed_packets")
        action_ids = response.get("claimed_action_ids")
        _require(isinstance(packets, list) and isinstance(action_ids, list), "claim response is invalid")
        actual = tuple(item.get("step_id") for item in packets if isinstance(item, Mapping))
        _require(
            len(actual) == len(packets) and actual == expected,
            f"claim selection mismatch: expected {expected}, got {actual}",
        )
        _require(
            action_ids == [item.get("action_id") for item in packets],
            "claim action IDs do not match claimed packets",
        )
        for item in packets:
            assert isinstance(item, Mapping)
            self.assert_action_packet(item)
            action_id = item.get("action_id")
            step_id = item.get("step_id")
            _require(
                isinstance(action_id, str) and action_id not in self.active,
                "claim reused an active action identity",
            )
            _require(
                isinstance(step_id, str) and step_id not in self.active.values(),
                "claim reused an active step",
            )
            self.active[action_id] = step_id
        self.assert_overview(response)
        return actual

    def mark_completed(self, packet: Mapping[str, Any]) -> None:
        action_id = packet.get("action_id")
        step_id = packet.get("step_id")
        _require(
            isinstance(action_id, str) and self.active.get(action_id) == step_id,
            "completion does not belong to an active claim",
        )
        assert isinstance(step_id, str)
        del self.active[action_id]
        _require(step_id not in self.completed, f"step {step_id} completed twice")
        self.completed.add(step_id)


def _command_argv(output: str, marker: str) -> list[str]:
    code = (
        "from pathlib import Path; "
        f"path = Path({output!r}); path.parent.mkdir(parents=True, exist_ok=True); "
        f"path.write_text({marker!r} + '\\n', encoding='utf-8')"
    )
    return [sys.executable, "-c", code]


def _step(step_id: str, kind: str, needs: Sequence[str]) -> dict[str, Any]:
    output = f"evidence/{step_id}.txt"
    base: dict[str, Any] = {
        "id": step_id,
        "kind": kind,
        "needs": list(needs),
        "outputs": [output],
    }
    if kind == "command":
        base["argv"] = _command_argv(output, step_id)
    else:
        base["prompt"] = f"Write only {output} for {step_id}; do not choose a successor."
    return base


def seeded_workflow(seed: int, *, node_count: int | None = None) -> dict[str, Any]:
    """Make a small shuffled DAG with roots, joins, and a transitive direct edge."""
    random_source = random.Random(seed)
    count = node_count if node_count is not None else 7 + seed % 3
    _require(count >= 7, "seeded graph needs at least seven nodes")
    ids = [f"S{index:02d}" for index in range(count)]
    kind_pattern = ["agent", "agent", "prompt", "agent", "command", "agent", "agent", "command", "prompt"]
    kinds = [kind_pattern[(index + seed) % len(kind_pattern)] for index in range(count)]
    needs: list[list[str]] = [[], [], []]
    needs.append([ids[random_source.choice((0, 1))]])
    needs.append([ids[1 - int(needs[3][0] == ids[1])]])
    # S05 is a join. S06 intentionally keeps a redundant transitive direct
    # edge so receipt rendering must not collapse the declared dependency set.
    needs.append([ids[3], ids[4]])
    needs.append([ids[0], ids[3], ids[5]])
    for index in range(7, count):
        candidates = list(range(index))
        chosen = sorted(random_source.sample(candidates, k=1 + random_source.randrange(2)))
        if index > 7 and index - 1 not in chosen:
            chosen.append(index - 1)
        needs.append([ids[parent] for parent in sorted(set(chosen))])
    steps = [_step(ids[index], kinds[index], needs[index]) for index in range(count)]
    random_source.shuffle(steps)
    return specified(
        {
            "version": 1,
            "name": f"seeded-graph-{seed}",
            "goal": "Exercise a durable, declared dependency graph from a deterministic seed.",
            "steps": steps,
        }
    )


def redundant_transitive_workflow() -> dict[str, Any]:
    """A minimal explicit A -> B -> C plus A -> C receipt-set contract."""
    return specified(
        {
            "version": 1,
            "name": "redundant-transitive",
            "goal": "Keep every declared direct dependency receipt, including a transitive edge.",
            "steps": [
                _step("A", "agent", []),
                _step("B", "agent", ["A"]),
                _step("C", "agent", ["A", "B"]),
                _step("D", "prompt", ["C"]),
            ],
        }
    )


def loom_workflow() -> dict[str, Any]:
    """The compound Loom shape used by examples and black-box test coverage."""
    kinds = {
        "A": "command",
        "B": "agent",
        "C": "agent",
        "D": "command",
        "E": "agent",
        "F": "agent",
        "G": "agent",
        "H": "agent",
        "I": "agent",
        "J": "command",
        "K": "agent",
        "L": "agent",
        "M": "prompt",
    }
    needs = {
        "A": [],
        "B": ["A"],
        "C": ["A"],
        "D": ["B", "C"],
        "E": ["D"],
        "F": ["D"],
        "G": ["D"],
        "H": ["E", "F"],
        "I": ["F", "G"],
        "J": ["H", "I"],
        "K": ["J"],
        "L": ["J"],
        "M": [],
    }
    return specified(
        {
            "version": 1,
            "name": "loom",
            "goal": "Run repeated joins, overlapping diamonds, and all required terminal leaves.",
            "steps": [_step(step_id, kinds[step_id], needs[step_id]) for step_id in kinds],
        }
    )


@dataclass
class ExerciseResult:
    """Machine-readable result returned by the reusable CLI exercise harness."""

    status: str
    completed_steps: tuple[str, ...]
    trace: list[dict[str, Any]]
    elapsed_ms: int
    transitions: int
    max_packet_bytes: int
    final_packet: dict[str, Any]


class BlackBoxWorkflowRunner:
    """Drive a temporary v2 run with public commands and simulated native handles."""

    def __init__(
        self,
        *,
        root: Path,
        base: Path,
        document: Mapping[str, Any],
        max_active: int,
        label: str,
    ) -> None:
        self.root = root.resolve()
        self.cli = self.root / "skills" / "workflow" / "scripts" / "workflow"
        _require(self.cli.is_file(), f"workflow CLI is unavailable at {self.cli}")
        self.base = base.resolve()
        self.base.mkdir(parents=True, exist_ok=True)
        self.document = dict(document)
        self.max_active = max_active
        self.label = label
        self.repo = self.base / "workspace"
        self.run_dir = self.base / "run"
        self.workflow_path = self.base / "workflow.json"
        self.results = self.base / "results"
        self.oracle = GraphOracle(self.document)
        self.trace: list[dict[str, Any]] = []
        self.max_packet_bytes = 0
        self.transition_count = 0
        self._request_number = 0
        self._turn = 0
        self._deadline: float | None = None
        self._max_transitions: int | None = None

    def _record(self, operation: str, packet: Mapping[str, Any]) -> None:
        encoded = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.max_packet_bytes = max(self.max_packet_bytes, len(encoded.encode("utf-8")))
        self.trace.append(
            {
                "operation": operation,
                "status": packet.get("status"),
                "ready": [item.get("step_id") for item in packet.get("ready_frontier", [])],
                "active": [item.get("step_id") for item in packet.get("active_packets", [])],
                "claimed": [item.get("step_id") for item in packet.get("claimed_packets", [])],
            }
        )

    def _call(self, *arguments: object, timeout: float = 15) -> dict[str, Any]:
        if self._deadline is not None and time.monotonic() > self._deadline:
            raise OracleViolation("graph exercise exceeded its wall-clock deadline")
        if self._max_transitions is not None and self.transition_count >= self._max_transitions:
            raise OracleViolation("graph exercise exceeded its transition budget")
        self.transition_count += 1
        completed = subprocess.run(
            [sys.executable, str(self.cli), *(str(argument) for argument in arguments)],
            cwd=self.base,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        try:
            packet = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise OracleViolation(
                f"CLI did not produce one JSON packet for {arguments!r}: {completed.stdout!r}; {exc}"
            ) from exc
        _require(isinstance(packet, dict), f"CLI packet for {arguments!r} is not an object")
        _require(
            completed.returncode == 0,
            f"CLI failed for {arguments!r}: {packet!r}; stderr={completed.stderr!r}",
        )
        return packet

    def start(self) -> dict[str, Any]:
        self.repo.mkdir(exist_ok=True)
        self.workflow_path.write_text(
            json.dumps(self.document, sort_keys=True, indent=2), encoding="utf-8"
        )
        packet = self._call(
            "init",
            "--workflow",
            self.workflow_path,
            "--repo",
            self.repo,
            "--run-dir",
            self.run_dir,
            "--max-active",
            self.max_active,
            "--shared-workspace-disjoint",
        )
        self.oracle.assert_overview(packet)
        self.oracle.assert_terminal(packet)
        self._record("init", packet)
        return packet

    def cold_next(self) -> dict[str, Any]:
        """Assert a stable read-only packet does not acquire claims or rewrite state."""
        paths = [self.run_dir / "state.md", self.run_dir / "packet.md"]
        before = {path: path.read_bytes() for path in paths}
        packet = self._call("next", "--run-dir", self.run_dir)
        after = {path: path.read_bytes() for path in paths}
        _require(before == after, "read-only next rewrote durable state or packet")
        self.oracle.assert_overview(packet)
        self.oracle.assert_terminal(packet)
        self._record("next", packet)
        return packet

    def claim(self, limit: int) -> dict[str, Any]:
        request_id = f"{self.label}-claim-{self._request_number}"
        self._request_number += 1
        response = self._call(
            "claim-ready",
            "--run-dir",
            self.run_dir,
            "--limit",
            limit,
            "--request-id",
            request_id,
        )
        self.oracle.observe_claim(response, limit=limit)
        self.oracle.assert_terminal(response)
        self._record("claim-ready", response)
        return response

    def _write_outputs(self, packet: Mapping[str, Any]) -> None:
        workspace = Path(str(packet["workspace"]))
        for index, output in enumerate(packet["declared_outputs"]):
            target = workspace / str(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                f"{packet['step_id']}:{packet['action_id']}:{index}\n", encoding="utf-8"
            )

    def _result_file(self, packet: Mapping[str, Any]) -> Path:
        self.results.mkdir(exist_ok=True)
        target = self.results / f"{packet['action_id']}.json"
        target.write_text(
            json.dumps(
                {"status": "succeeded", "summary": f"simulated {packet['step_id']} success"},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return target

    def _complete_one(self, packet: Mapping[str, Any]) -> dict[str, Any]:
        self.oracle.assert_action_packet(packet)
        action_id = str(packet["action_id"])
        kind = str(packet["kind"])
        if kind == "command":
            response = self._call("execute", "--run-dir", self.run_dir, "--action", action_id)
            operation = "execute"
        elif kind == "prompt":
            self._write_outputs(packet)
            response = self._call(
                "complete",
                "--run-dir",
                self.run_dir,
                "--action",
                action_id,
                "--result",
                self._result_file(packet),
            )
            operation = "complete-prompt"
        else:
            prepared = self._call(
                "prepare-dispatch", "--run-dir", self.run_dir, "--action", action_id
            )
            self.oracle.assert_overview(prepared)
            prepared_packet = prepared.get("prepared_packet")
            _require(isinstance(prepared_packet, Mapping), "agent preparation lacks prepared packet")
            self.oracle.assert_action_packet(prepared_packet)
            _require(
                prepared_packet.get("native_dispatch", {}).get("state") == "launch_once",
                "only the direct prepare response may authorize one simulated launch",
            )
            self._record("prepare-dispatch", prepared)
            dispatched = self._call(
                "dispatch",
                "--run-dir",
                self.run_dir,
                "--action",
                action_id,
                "--handle",
                f"oracle-native-{action_id}",
            )
            self.oracle.assert_overview(dispatched)
            self._record("dispatch", dispatched)
            self._write_outputs(packet)
            response = self._call(
                "complete",
                "--run-dir",
                self.run_dir,
                "--action",
                action_id,
                "--result",
                self._result_file(packet),
            )
            operation = "complete-agent"
        self.oracle.mark_completed(packet)
        self.oracle.assert_overview(response)
        self.oracle.assert_terminal(response)
        self._record(operation, response)
        return response

    def _choose_active(self, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        active = packet.get("active_packets")
        _require(isinstance(active, list) and active, "no active packet is available to complete")
        # Reverse declaration order forces a different completion order from
        # the normal claim order without guessing a successor.
        rank = {step_id: index for index, step_id in enumerate(self.oracle.topology)}
        return max(active, key=lambda item: rank[str(item["step_id"])])

    def run_to_completion(
        self,
        *,
        max_turns: int = 200,
        max_transitions: int = 300,
        wall_seconds: float = 45,
    ) -> ExerciseResult:
        _require(max_turns > 0, "graph exercise turn budget must be positive")
        _require(max_transitions > 0, "graph exercise transition budget must be positive")
        _require(wall_seconds > 0, "graph exercise wall-clock deadline must be positive")
        started = time.monotonic()
        self._deadline = started + wall_seconds
        self._max_transitions = max_transitions
        packet = self.start()
        for _ in range(max_turns):
            packet = self.cold_next()
            if self.oracle.all_required_complete():
                _require(packet.get("status") == "complete", "completed graph did not become terminal")
                return ExerciseResult(
                    status="complete",
                    completed_steps=tuple(sorted(self.oracle.completed)),
                    trace=self.trace,
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                    transitions=self.transition_count,
                    max_packet_bytes=self.max_packet_bytes,
                    final_packet=packet,
                )

            active_packets = packet["active_packets"]
            # Vary limits across calls.  A claimed agent batch is intentionally
            # kept alive for one extra cold read/claim opportunity, which
            # exercises capacity filling and partial claims.
            limit_options = (1, min(2, self.max_active), self.max_active)
            limit = limit_options[self._turn % len(limit_options)]
            self._turn += 1
            response = self.claim(limit)
            newly_claimed = response["claimed_packets"]
            active_packets = response["active_packets"]
            if (
                newly_claimed
                and len(active_packets) < self.max_active
                and all(item.get("kind") == "agent" for item in active_packets)
            ):
                # Do not accept a first branch before the script has a chance
                # to fill a bounded disjoint frontier.
                continue
            if not active_packets:
                raise OracleViolation("workflow is nonterminal but no action can be claimed")
            self._complete_one(self._choose_active(response))
        raise OracleViolation(f"workflow did not reach terminal completion in {max_turns} turns")


def oracle_negative_controls() -> list[dict[str, Any]]:
    """Prove this oracle rejects three synthetic bad contracts without a runtime edit."""
    results: list[dict[str, Any]] = []

    def rejected(case: str, callback: Any) -> None:
        try:
            callback()
        except OracleViolation as exc:
            results.append(
                {
                    "case": case,
                    "kind": "oracle-self-test",
                    "runtime_mutated": False,
                    "rejected": True,
                    "message": str(exc),
                }
            )
        else:  # pragma: no cover - guard against a weakened oracle
            raise OracleViolation(f"negative control unexpectedly passed: {case}")

    premature = GraphOracle(redundant_transitive_workflow())
    rejected(
        "premature-terminal",
        lambda: premature.assert_terminal(
            {"status": "complete", "active_packets": [], "ready_frontier": []}
        ),
    )

    missing = GraphOracle(redundant_transitive_workflow())
    missing.completed.update({"A", "B"})
    rejected(
        "missing-direct-dependency-receipt",
        lambda: missing.assert_action_packet(
            {
                "step_id": "C",
                "kind": "agent",
                "declared_outputs": ["evidence/C.txt"],
                "direct_dependency_receipts": [
                    {"step_id": "A", "receipt_path": "/tmp/a.md", "sha256": "a" * 64}
                ],
                "dependencies": [
                    {"step_id": "A", "receipt_path": "/tmp/a.md", "sha256": "a" * 64}
                ],
            }
        ),
    )

    over_capacity = GraphOracle(loom_workflow())
    over_capacity.completed.add("A")
    rejected(
        "over-capacity",
        lambda: over_capacity._assert_active_constraints(
            [
                {
                    "action_id": "one",
                    "step_id": "B",
                    "kind": "agent",
                    "declared_outputs": ["evidence/B.txt"],
                    "direct_dependency_receipts": [
                        {"step_id": "A", "receipt_path": "/tmp/a.md", "sha256": "a" * 64}
                    ],
                    "dependencies": [
                        {"step_id": "A", "receipt_path": "/tmp/a.md", "sha256": "a" * 64}
                    ],
                    "workspace_lease": {"mode": "declared-output-exclusive", "paths": ["evidence/B.txt"]},
                },
                {
                    "action_id": "two",
                    "step_id": "C",
                    "kind": "agent",
                    "declared_outputs": ["evidence/C.txt"],
                    "direct_dependency_receipts": [
                        {"step_id": "A", "receipt_path": "/tmp/a.md", "sha256": "a" * 64}
                    ],
                    "dependencies": [
                        {"step_id": "A", "receipt_path": "/tmp/a.md", "sha256": "a" * 64}
                    ],
                    "workspace_lease": {"mode": "declared-output-exclusive", "paths": ["evidence/C.txt"]},
                },
                {
                    "action_id": "three",
                    "step_id": "M",
                    "kind": "agent",
                    "declared_outputs": ["evidence/M.txt"],
                    "direct_dependency_receipts": [],
                    "dependencies": [],
                    "workspace_lease": {"mode": "declared-output-exclusive", "paths": ["evidence/M.txt"]},
                },
            ],
            max_active=2,
        ),
    )
    return results


def runtime_hashes(root: Path) -> dict[str, str]:
    """Hash the executable surfaces tested by the matrix without importing them."""
    root = root.resolve()
    paths = {
        "cli": root / "skills" / "workflow" / "scripts" / "workflow",
        "core": root / "skills" / "workflow" / "scripts" / "workflow_core.py",
        "store": root / "skills" / "workflow" / "scripts" / "store.py",
    }
    return {
        label: hashlib.sha256(path.read_bytes()).hexdigest()
        for label, path in paths.items()
    }
