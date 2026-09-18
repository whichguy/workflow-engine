"""Black-box contracts for the specification-first Workflow entry paths.

These tests keep specification drafting, frozen artifacts, and requirement-aware
execution observable through the public CLI.  The transaction interruption case
uses the same kernel in a disposable process boundary solely to inject a durable
store cut; recovery itself returns through the CLI.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from typing import Any, Mapping

from spec_fixtures import authored_specification, planning_fixture, specified


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "workflow" / "scripts"
CLI = SCRIPTS / "workflow"
PYTHON = sys.executable

# The one deliberate white-box seam: deterministic transaction interruption.
# All ordinary protocol assertions below start a fresh public CLI process.
sys.path.insert(0, str(SCRIPTS))
import store  # noqa: E402
from workflow_core import WorkflowKernel  # noqa: E402


class _InjectedTransactionCrash(RuntimeError):
    """Stop one disposable transaction after a selected durable target."""


class SpecificationEntryTests(unittest.TestCase):
    """Exercise the durable spec gate without invoking a model or packager."""

    maxDiff = None

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="workflow-spec-entry-")
        self.addCleanup(self.tempdir.cleanup)
        self.base = Path(self.tempdir.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        # Specification drafting only needs a selected root.  Packaging is not
        # reached in this module, so a disposable directory keeps every test
        # non-skipped and independent of a sibling Backchain checkout.
        self.backchain = self.base / "selected-backchain"
        self.backchain.mkdir()
        self.run = self.base / "run"
        self.goal = "Create one traceable, dependency-aware deliverable.\n"

    # ---- public CLI helpers ------------------------------------------

    def raw(self, *args: object, timeout: float = 20) -> subprocess.CompletedProcess[str]:
        self.assertTrue(CLI.is_file(), f"workflow CLI is missing: {CLI}")
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
            f"workflow CLI emitted no JSON packet\nstderr:\n{result.stderr}",
        )
        try:
            packet = json.loads(result.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - assertion diagnostic
            self.fail(f"workflow CLI emitted invalid JSON: {result.stdout!r}\n{exc}")
        self.assertIsInstance(packet, dict)
        return packet

    def call(self, *args: object, timeout: float = 20) -> dict[str, Any]:
        result = self.raw(*args, timeout=timeout)
        packet = self.decode(result)
        self.assertEqual(
            result.returncode,
            0,
            f"workflow CLI failed for {args!r}: {packet!r}\nstderr:\n{result.stderr}",
        )
        return packet

    def error(self, *args: object, timeout: float = 20) -> dict[str, Any]:
        result = self.raw(*args, timeout=timeout)
        packet = self.decode(result)
        self.assertNotEqual(result.returncode, 0, f"expected error: {packet!r}")
        self.assertEqual(packet.get("status"), "error")
        return packet

    # ---- durable fixture helpers -------------------------------------

    def write_json(self, name: str, value: Any) -> Path:
        path = self.base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def read_state(self, run: Path | None = None) -> dict[str, Any]:
        path = (run or self.run) / "state.md"
        text = path.read_text(encoding="utf-8")
        opening = "```workflow-state\n"
        self.assertIn(opening, text, path)
        payload = text.split(opening, 1)[1].split("\n```", 1)[0]
        state = json.loads(payload)
        self.assertIsInstance(state, dict)
        return state

    @staticmethod
    def _seal(state: dict[str, Any]) -> dict[str, Any]:
        """Reseal a deliberately modified durable record for adversarial input."""
        if state.get("definition") is None:
            state["definition_sha256"] = None
        else:
            state["definition_sha256"] = hashlib.sha256(
                json.dumps(
                    state["definition"],
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        unsealed = {key: value for key, value in state.items() if key != "state_sha256"}
        state["state_sha256"] = hashlib.sha256(
            json.dumps(
                unsealed,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return state

    @staticmethod
    def _state_record(state: Mapping[str, Any]) -> str:
        return (
            "# Workflow run\n\n```workflow-state\n"
            + json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n```\n"
        )

    def write_state(self, state: Mapping[str, Any], run: Path | None = None) -> None:
        target = (run or self.run) / "state.md"
        target.write_text(self._state_record(state), encoding="utf-8")

    def prompt_entry(
        self,
        *,
        run: Path | None = None,
        goal: str | None = None,
    ) -> dict[str, Any]:
        target_run = run or self.run
        request = self.base / f"{target_run.name}.request.txt"
        request.write_text(goal if goal is not None else self.goal, encoding="utf-8")
        return self.call(
            "init",
            "--prompt-file",
            request,
            "--backchain-root",
            self.backchain,
            "--run-dir",
            target_run,
            "--repo",
            self.repo,
        )

    def write_packet_spec(
        self,
        packet: Mapping[str, Any],
        spec: Mapping[str, Any],
    ) -> Path:
        self.assertIn("spec_file", packet, packet)
        target = Path(str(packet["spec_file"]))
        self.assertTrue(target.is_absolute(), target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
        return target

    def accept_spec(
        self,
        packet: Mapping[str, Any],
        spec: Mapping[str, Any],
        *,
        run: Path | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        target_run = run or self.run
        source = self.write_packet_spec(packet, spec)
        accepted = self.call(
            "accept-spec",
            "--run-dir",
            target_run,
            "--action",
            packet["action_id"],
            "--spec",
            source,
        )
        return source, accepted

    @staticmethod
    def argv_value(argv: list[Any], flag: str) -> Any:
        index = argv.index(flag)
        return argv[index + 1]

    def assert_frozen_specification(
        self,
        state: Mapping[str, Any],
        spec: Mapping[str, Any],
        *,
        run: Path | None = None,
    ) -> None:
        target_run = run or self.run
        self.assertEqual(state.get("specification_policy"), "required-v1")
        self.assertEqual(state.get("request", {}).get("specification_policy"), "required-v1")
        self.assertEqual(state.get("specification"), spec)
        digest = state.get("specification_sha256")
        self.assertIsInstance(digest, str)
        self.assertEqual(len(digest), 64)
        artifacts = state.get("specification_artifacts")
        self.assertIsInstance(artifacts, dict)
        self.assertEqual(set(artifacts), {"requirements/spec.md", "requirements/nfrs.md"})
        for relative, expected_digest in artifacts.items():
            self.assertIsInstance(expected_digest, str)
            artifact = target_run / relative
            self.assertTrue(artifact.is_file(), artifact)
            self.assertFalse(artifact.is_symlink(), artifact)
            self.assertEqual(
                hashlib.sha256(artifact.read_bytes()).hexdigest(),
                expected_digest,
            )

    # ---- prompt and standalone-spec entry paths ----------------------

    def test_prompt_entry_issues_a_script_owned_specification_callback(self) -> None:
        packet = self.prompt_entry()

        self.assertEqual(packet["kind"], "specification")
        self.assertEqual(packet["status"], "specification")
        self.assertEqual(packet["original_goal"], self.goal)
        self.assertIn("specification_instruction", packet)
        self.assertNotIn("plan_file", packet)
        self.assertNotIn("bindings_file", packet)
        self.assertIn("spec_file", packet)
        argv = packet["next_argv"]
        self.assertEqual(Path(str(argv[0])).resolve(), CLI.resolve())
        self.assertEqual(argv[1], "accept-spec")
        self.assertEqual(self.argv_value(argv, "--run-dir"), str(self.run.resolve()))
        self.assertEqual(self.argv_value(argv, "--action"), packet["action_id"])
        self.assertEqual(self.argv_value(argv, "--spec"), packet["spec_file"])

        state = self.read_state()
        self.assertEqual(state["status"], "specification")
        self.assertEqual(state["current_action"]["id"], packet["action_id"])
        self.assertEqual(state["current_action"]["kind"], "specification")
        self.assertEqual(state["specification_policy"], "required-v1")
        self.assertNotIn("specification", state)

    def test_accept_spec_validates_freezes_replays_and_rejects_conflicts(self) -> None:
        first = self.prompt_entry()
        spec = authored_specification(self.goal)
        invalid = json.loads(json.dumps(spec))
        invalid["unresolved"] = ["A material decision remains open"]
        source = self.write_packet_spec(first, invalid)

        self.error(
            "accept-spec",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--spec",
            source,
        )
        still_drafting = self.call("next", "--run-dir", self.run)
        self.assertEqual(still_drafting["action_id"], first["action_id"])
        self.assertEqual(still_drafting["kind"], "specification")

        source.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
        accepted = self.call(
            "accept-spec",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--spec",
            source,
        )
        self.assertEqual(accepted["kind"], "planning")
        self.assertEqual(accepted["status"], "planning")
        self.assertEqual(accepted["original_goal"], self.goal)
        self.assertEqual(accepted["specification"], spec)
        state = self.read_state()
        self.assert_frozen_specification(state, spec)
        self.assertEqual(accepted["specification_sha256"], state["specification_sha256"])
        self.assertEqual(accepted["specification_artifacts"], state["specification_artifacts"])

        # A lost response is safe to replay only with precisely the same source
        # bytes and normalized specification.
        replay = self.call(
            "accept-spec",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--spec",
            source,
        )
        self.assertEqual(replay["kind"], "planning")
        self.assertEqual(replay["action_id"], accepted["action_id"])
        self.assertEqual(replay["specification_sha256"], accepted["specification_sha256"])

        conflicting = json.loads(json.dumps(spec))
        conflicting["assumptions"] = ["A changed source must not replace the freeze"]
        source.write_text(json.dumps(conflicting, indent=2, sort_keys=True), encoding="utf-8")
        self.error(
            "accept-spec",
            "--run-dir",
            self.run,
            "--action",
            first["action_id"],
            "--spec",
            source,
        )
        current = self.call("next", "--run-dir", self.run)
        self.assertEqual(current["kind"], "planning")
        self.assertEqual(current["action_id"], accepted["action_id"])
        self.assertEqual(self.read_state()["specification"], spec)

    def test_spec_file_starts_planning_directly_and_is_exclusive(self) -> None:
        spec = authored_specification(self.goal)
        source = self.write_json("standalone-spec.json", spec)
        without_root = self.base / "without-root"
        self.error(
            "init",
            "--spec-file",
            source,
            "--run-dir",
            without_root,
            "--repo",
            self.repo,
        )
        self.assertFalse(without_root.exists())

        packet = self.call(
            "init",
            "--spec-file",
            source,
            "--backchain-root",
            self.backchain,
            "--run-dir",
            self.run,
            "--repo",
            self.repo,
        )
        self.assertEqual(packet["kind"], "planning")
        self.assertEqual(packet["status"], "planning")
        self.assertEqual(packet["original_goal"], self.goal)
        self.assertEqual(packet["specification"], spec)
        self.assertEqual(packet["next_argv"][1], "accept-plan")
        self.assert_frozen_specification(self.read_state(), spec)

        workflow = self.write_json("a-workflow.json", self.authored_command_workflow())
        for name, arguments in {
            "workflow-and-spec": ("--workflow", workflow, "--spec-file", source),
            "prompt-and-spec": ("--prompt-file", self.write_prompt(), "--spec-file", source),
        }.items():
            with self.subTest(name=name):
                collision_run = self.base / f"{name}-run"
                self.error(
                    "init",
                    *arguments,
                    "--backchain-root",
                    self.backchain,
                    "--run-dir",
                    collision_run,
                    "--repo",
                    self.repo,
                )
                self.assertFalse(collision_run.exists())

    def write_prompt(self) -> Path:
        path = self.base / "prompt.txt"
        path.write_text(self.goal, encoding="utf-8")
        return path

    def authored_command_workflow(self) -> dict[str, Any]:
        return specified(
            {
                "version": 1,
                "name": "specified-command",
                "goal": self.goal,
                "steps": [
                    {
                        "id": "deliver",
                        "kind": "command",
                        "needs": [],
                        "argv": [PYTHON, "-c", "from pathlib import Path; Path('out.txt').write_text('ok')"],
                        "outputs": ["out.txt"],
                    }
                ],
            }
        )

    def compound_workflow(self) -> dict[str, Any]:
        """One setup, two independent outcomes, a release join, and a leaf check."""
        spec = authored_specification(self.goal, step_count=2)

        def contract(
            role: str,
            deliverables: list[str],
            requirements: list[str],
            verifies: list[str],
            *,
            shared_reason: str | None = None,
        ) -> dict[str, Any]:
            value: dict[str, Any] = {
                "role": role,
                "deliverables": deliverables,
                "requirements": requirements,
                "verifies": verifies,
                "ready_when": ["all declared suppliers have accepted receipts"],
                "done_when": ["the declared output and check evidence exist"],
            }
            if shared_reason is not None:
                value["shared_reason"] = shared_reason
            return value

        return {
            "version": 2,
            "name": "setup-fanout-release-postcheck",
            "goal": self.goal,
            "specification": spec,
            "steps": [
                {
                    "id": "setup",
                    "kind": "command",
                    "needs": [],
                    "argv": [
                        PYTHON,
                        "-c",
                        (
                            "from pathlib import Path; "
                            "Path('state').mkdir(); "
                            "Path('state/setup.txt').write_text('ready\\n', encoding='utf-8')"
                        ),
                    ],
                    "outputs": ["state/setup.txt"],
                    "contract": contract(
                        "setup",
                        ["D1", "D2"],
                        [],
                        [],
                        shared_reason="one shared workspace baseline serves both deliverables",
                    ),
                },
                {
                    "id": "feature-a",
                    "kind": "command",
                    "needs": ["setup"],
                    "argv": [
                        PYTHON,
                        "-c",
                        (
                            "from pathlib import Path; "
                            "assert Path('state/setup.txt').read_text(encoding='utf-8') == 'ready\\n'; "
                            "Path('features').mkdir(exist_ok=True); "
                            "Path('features/a.txt').write_text('A\\n', encoding='utf-8')"
                        ),
                    ],
                    "outputs": ["features/a.txt"],
                    "contract": contract("deliverable", ["D1"], ["FR1"], ["FR1"]),
                },
                {
                    "id": "feature-b",
                    "kind": "command",
                    "needs": ["setup"],
                    "argv": [
                        PYTHON,
                        "-c",
                        (
                            "from pathlib import Path; "
                            "assert Path('state/setup.txt').read_text(encoding='utf-8') == 'ready\\n'; "
                            "Path('features').mkdir(exist_ok=True); "
                            "Path('features/b.txt').write_text('B\\n', encoding='utf-8')"
                        ),
                    ],
                    "outputs": ["features/b.txt"],
                    "contract": contract("deliverable", ["D2"], ["FR2"], ["FR2"]),
                },
                {
                    "id": "release",
                    "kind": "command",
                    "needs": ["feature-a", "feature-b"],
                    "argv": [
                        PYTHON,
                        "-c",
                        (
                            "from pathlib import Path; "
                            "assert Path('features/a.txt').read_text(encoding='utf-8') == 'A\\n'; "
                            "assert Path('features/b.txt').read_text(encoding='utf-8') == 'B\\n'; "
                            "Path('release').mkdir(); "
                            "Path('release/target.txt').write_text('A+B\\n', encoding='utf-8')"
                        ),
                    ],
                    "outputs": ["release/target.txt"],
                    "contract": contract(
                        "release",
                        ["D1", "D2"],
                        [],
                        [],
                        shared_reason="one target release combines the two independently produced outcomes",
                    ),
                },
                {
                    "id": "postrelease-check",
                    "kind": "command",
                    "needs": ["release"],
                    "argv": [
                        PYTHON,
                        "-c",
                        (
                            "from pathlib import Path; "
                            "assert Path('release/target.txt').read_text(encoding='utf-8') == 'A+B\\n'; "
                            "Path('evidence').mkdir(); "
                            "Path('evidence/consumer.txt').write_text('observed\\n', encoding='utf-8')"
                        ),
                    ],
                    "outputs": ["evidence/consumer.txt"],
                    "contract": contract(
                        "verification",
                        ["D1", "D2"],
                        [],
                        ["NFR1"],
                        shared_reason="one post-release consumer observation covers the global quality constraint",
                    ),
                },
            ],
        }

    def execute(self, packet: Mapping[str, Any]) -> dict[str, Any]:
        self.assertEqual(packet.get("kind"), "command", packet)
        return self.call(
            "execute",
            "--run-dir",
            self.run,
            "--action",
            packet["action_id"],
        )

    def test_setup_fanout_release_join_and_postrelease_leaf_keep_traceability(self) -> None:
        workflow = self.compound_workflow()
        source = self.write_json("compound.workflow.json", workflow)
        setup = self.call(
            "init",
            "--workflow",
            source,
            "--run-dir",
            self.run,
            "--repo",
            self.repo,
        )

        self.assertEqual(setup["step_id"], "setup")
        setup_context = setup["specification_context"]
        self.assertEqual(setup_context["role"], "setup")
        self.assertEqual({item["id"] for item in setup_context["deliverables"]}, {"D1", "D2"})
        self.assertEqual(
            {item["id"] for item in setup_context["functional_requirements"]},
            {"FR1", "FR2"},
        )
        self.assertEqual({item["id"] for item in setup_context["nfrs"]}, {"NFR1"})
        self.assertEqual(setup_context["requirements"], [])
        self.assertEqual(setup_context["verifies"], [])

        feature_a = self.execute(setup)
        self.assertEqual(feature_a["step_id"], "feature-a")
        self.assertEqual(len(feature_a["dependencies"]), 1)
        self.assertEqual(feature_a["dependencies"][0]["step_id"], "setup")
        self.assertEqual(feature_a["specification_context"]["role"], "deliverable")
        self.assertEqual(feature_a["specification_context"]["requirements"], ["FR1"])
        self.assertEqual({item["id"] for item in feature_a["specification_context"]["nfrs"]}, {"NFR1"})

        feature_b = self.execute(feature_a)
        self.assertEqual(feature_b["step_id"], "feature-b")
        # Serial execution selected A first, but B only receives its declared
        # shared setup receipt: the graph itself preserves the independent fan-out.
        self.assertEqual([item["step_id"] for item in feature_b["dependencies"]], ["setup"])
        self.assertEqual(feature_b["specification_context"]["requirements"], ["FR2"])

        release = self.execute(feature_b)
        self.assertEqual(release["step_id"], "release")
        self.assertEqual(
            {item["step_id"] for item in release["dependencies"]},
            {"feature-a", "feature-b"},
        )
        self.assertEqual(release["specification_context"]["role"], "release")
        self.assertEqual({item["id"] for item in release["specification_context"]["nfrs"]}, {"NFR1"})

        postrelease = self.execute(release)
        self.assertEqual(postrelease["step_id"], "postrelease-check")
        self.assertEqual([item["step_id"] for item in postrelease["dependencies"]], ["release"])
        self.assertEqual(postrelease["specification_context"]["role"], "verification")
        self.assertEqual(postrelease["specification_context"]["verifies"], ["NFR1"])

        terminal = self.execute(postrelease)
        self.assertEqual(terminal["status"], "complete")
        workspace = Path(str(terminal["workspace"]))
        self.assertEqual((workspace / "state/setup.txt").read_text(encoding="utf-8"), "ready\n")
        self.assertEqual((workspace / "features/a.txt").read_text(encoding="utf-8"), "A\n")
        self.assertEqual((workspace / "features/b.txt").read_text(encoding="utf-8"), "B\n")
        self.assertEqual((workspace / "release/target.txt").read_text(encoding="utf-8"), "A+B\n")
        self.assertEqual((workspace / "evidence/consumer.txt").read_text(encoding="utf-8"), "observed\n")

        state = self.read_state()
        self.assertEqual(
            set(state["completed"]),
            {"setup", "feature-a", "feature-b", "release", "postrelease-check"},
        )
        coverage = state["requirement_coverage"]
        self.assertEqual(coverage["FR1"]["implemented_by"], ["feature-a"])
        self.assertEqual(coverage["FR2"]["implemented_by"], ["feature-b"])
        self.assertEqual(coverage["NFR1"]["verified_by"], {"D1": ["postrelease-check"], "D2": ["postrelease-check"]})
        for completion in state["completed"].values():
            receipt_path = self.run / completion["receipt_path"]
            receipt = store.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["specification_sha256"], state["specification_sha256"])
            self.assertEqual(receipt["specification_artifacts"], state["specification_artifacts"])
            self.assertIn("specification_context", receipt)

    def test_new_authored_inputs_reject_missing_or_invalid_traceability_before_isolation(self) -> None:
        valid = self.authored_command_workflow()
        cases: dict[str, dict[str, Any]] = {}

        missing_spec = json.loads(json.dumps(valid))
        missing_spec.pop("specification")
        cases["missing-specification"] = missing_spec

        invalid_spec = json.loads(json.dumps(valid))
        invalid_spec["specification"]["unresolved"] = ["unresolved material ambiguity"]
        cases["invalid-specification"] = invalid_spec

        missing_contract = json.loads(json.dumps(valid))
        missing_contract["steps"][0].pop("contract")
        cases["missing-contract"] = missing_contract

        invalid_contract = json.loads(json.dumps(valid))
        invalid_contract["steps"][0]["contract"]["requirements"] = ["unknown-requirement"]
        cases["invalid-contract"] = invalid_contract

        for label, document in cases.items():
            with self.subTest(label=label):
                run = self.base / f"{label}-run"
                source = self.write_json(f"{label}.json", document)
                self.error(
                    "init",
                    "--workflow",
                    source,
                    "--run-dir",
                    run,
                    "--repo",
                    self.repo,
                    "--isolate",
                )
                self.assertFalse(run.exists(), "invalid input must not create a run or worktree")

    def test_spec_file_plan_acceptance_keeps_contracts_and_replays_without_repackaging(self) -> None:
        """The pre-authored spec governs a later packaged graph and receipt chain."""
        spec = authored_specification(self.goal)
        spec_source = self.write_json("planned-spec.json", spec)
        planning = self.call(
            "init",
            "--spec-file",
            spec_source,
            "--backchain-root",
            self.backchain,
            "--run-dir",
            self.run,
            "--repo",
            self.repo,
        )
        plan = {
            "goal": self.goal,
            "initial_state": [],
            "steps": [
                {
                    "id": "S1",
                    "statement": "The requested atom has been delivered",
                    "produces": ["atom delivered"],
                    "inputs": [],
                    "origin": "fixture",
                }
            ],
            "parallel_groups": [],
            "unresolved": [],
            "goal_needs": ["atom delivered"],
        }
        raw_bindings: dict[str, Any] = {
            "S1": {
                "kind": "command",
                "argv": [
                    PYTHON,
                    "-c",
                    "from pathlib import Path; Path('atom.txt').write_text('done\\n', encoding='utf-8')",
                ],
                "outputs": ["atom.txt"],
            }
        }
        expected_spec, bindings = planning_fixture(plan, raw_bindings)
        self.assertEqual(expected_spec, spec)
        plan_source = self.write_json("plan.json", plan)
        bindings_source = self.write_json("bindings.json", bindings)

        class FakeBackchainAdapter:
            calls = 0

            def compile_backchain(
                self,
                root: Path,
                submitted_plan: dict[str, Any],
                submitted_bindings: dict[str, Any],
                staging: Path,
            ) -> tuple[dict[str, Any], dict[str, Any]]:
                self.calls += 1
                self_outer.assertEqual(root, self_outer.backchain.resolve())
                self_outer.assertEqual(submitted_plan, plan)
                self_outer.assertEqual(submitted_bindings, bindings)
                staging.parent.mkdir(parents=True, exist_ok=True)
                return (
                    {
                        "version": 1,
                        "name": "fake-packaged-plan",
                        "goal": self_outer.goal,
                        "steps": [
                            {
                                "id": "S1",
                                "kind": "command",
                                "needs": [],
                                "argv": list(submitted_bindings["S1"]["argv"]),
                                "outputs": list(submitted_bindings["S1"]["outputs"]),
                                "produces": ["atom delivered"],
                                "contract": dict(submitted_bindings["S1"]["contract"]),
                            }
                        ],
                    },
                    {"adapter": "test-only-fake", "staging": str(staging)},
                )

        self_outer = self
        adapter = FakeBackchainAdapter()
        kernel = WorkflowKernel(CLI)
        with mock.patch.object(kernel, "_adapters", return_value=adapter):
            accepted = kernel.accept_plan(
                run_dir=self.run,
                action_id=planning["action_id"],
                plan_file=plan_source,
                bindings_file=bindings_source,
            )
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(accepted["kind"], "command")
        self.assertEqual(accepted["step_id"], "S1")
        self.assertEqual(accepted["specification_context"]["requirements"], ["FR1"])

        state = self.read_state()
        self.assert_frozen_specification(state, spec)
        self.assertEqual(state["definition"]["version"], 2)
        self.assertEqual(state["definition"]["specification"], spec)
        self.assertEqual(state["definition"]["steps"][0]["contract"]["requirements"], ["FR1"])

        # The replay branch checks accepted hashes before it reaches the
        # adapter, so a fresh CLI can safely return the existing packet.
        replay = self.call(
            "accept-plan",
            "--run-dir",
            self.run,
            "--action",
            planning["action_id"],
            "--plan",
            plan_source,
            "--bindings",
            bindings_source,
        )
        self.assertEqual(replay["action_id"], accepted["action_id"])
        changed_bindings = json.loads(json.dumps(bindings))
        changed_bindings["S1"]["argv"][-1] += " # conflict"
        bindings_source.write_text(
            json.dumps(changed_bindings, indent=2, sort_keys=True), encoding="utf-8"
        )
        self.error(
            "accept-plan",
            "--run-dir",
            self.run,
            "--action",
            planning["action_id"],
            "--plan",
            plan_source,
            "--bindings",
            bindings_source,
        )

        terminal = self.call("run", "--run-dir", self.run)
        self.assertEqual(terminal["status"], "complete")
        completed_state = self.read_state()
        receipt = store.loads(
            (self.run / completed_state["completed"]["S1"]["receipt_path"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(receipt["specification_sha256"], completed_state["specification_sha256"])

    def test_frozen_specification_artifacts_reject_deletion_tampering_and_aliases(self) -> None:
        scenarios = (
            ("deleted", "requirements/spec.md"),
            ("tampered", "requirements/nfrs.md"),
            ("symlink", "requirements/spec.md"),
            ("hardlink", "requirements/nfrs.md"),
        )
        for label, relative in scenarios:
            with self.subTest(label=label):
                run = self.base / f"artifact-{label}"
                first = self.prompt_entry(run=run)
                spec = authored_specification(self.goal)
                self.accept_spec(first, spec, run=run)
                artifact = run / relative
                original = artifact.read_bytes()
                if label == "deleted":
                    artifact.unlink()
                elif label == "tampered":
                    artifact.write_bytes(original + b"\nchanged")
                elif label == "symlink":
                    outside = self.base / f"{label}-outside.md"
                    outside.write_bytes(original)
                    artifact.unlink()
                    try:
                        artifact.symlink_to(outside)
                    except OSError as exc:  # pragma: no cover - unsupported host is a failed contract
                        self.fail(f"test host cannot create required symlink fixture: {exc}")
                else:
                    alias = self.base / f"{label}-alias.md"
                    try:
                        os.link(artifact, alias)
                    except OSError as exc:  # pragma: no cover - unsupported host is a failed contract
                        self.fail(f"test host cannot create required hard-link fixture: {exc}")
                    self.assertGreater(artifact.stat().st_nlink, 1)

                self.error("next", "--run-dir", run)

    def test_legacy_no_policy_record_recovers_while_new_policy_without_spec_is_rejected(self) -> None:
        legacy_run = self.base / "legacy-run"
        legacy_run.mkdir()
        legacy_goal = "Preserve the prior planning callback."
        legacy_state: dict[str, Any] = {
            "schema": "workflow-run",
            "version": 1,
            "run_id": "legacy-planning-run",
            "created_at": "2026-01-01T00:00:00+00:00",
            "run_dir": str(legacy_run.resolve()),
            "original_goal": legacy_goal,
            "request": {
                "mode": "prompt",
                "prompt": legacy_goal,
                "backchain_root": str(self.backchain.resolve()),
            },
            "definition": None,
            "definition_sha256": None,
            "repo": {"path": str(self.repo.resolve()), "git_head": None},
            "workspace": str(self.repo.resolve()),
            "isolation": {"mode": "none"},
            "planner": {"backchain_root": str(self.backchain.resolve())},
            "status": "planning",
            "current_action": {
                "id": "legacy-plan-action",
                "kind": "planning",
                "step_id": None,
                "attempt": 1,
                "status": "ready",
                "issued_at": "2026-01-01T00:00:00+00:00",
            },
            "completed": {},
            "callbacks": {},
            "attempts": [],
            "dispatch_history": [],
            "retry_history": [],
            "reconciliation": [],
        }
        self.write_state(self._seal(legacy_state), legacy_run)
        recovered = self.call("next", "--run-dir", legacy_run)
        self.assertEqual(recovered["kind"], "planning")
        self.assertEqual(recovered["action_id"], "legacy-plan-action")
        self.assertNotIn("specification_sha256", recovered)

        first = self.prompt_entry()
        state = self.read_state()
        state["status"] = "planning"
        state["current_action"]["kind"] = "planning"
        self.write_state(self._seal(state))
        self.error("next", "--run-dir", self.run)
        self.assertEqual(first["kind"], "specification")

    def legacy_frontier_state(self, run: Path) -> dict[str, Any]:
        """A genuine pre-spec frontier state with one previously leased agent."""
        goal = "Preserve an old frontier claim while the other leaf can continue."
        definition = {
            "version": 1,
            "name": "legacy-frontier-v2-runtime",
            "goal": goal,
            "steps": [
                {
                    "id": "A",
                    "kind": "agent",
                    "needs": [],
                    "prompt": "Write a.txt only.",
                    "outputs": ["a.txt"],
                    "verify": [],
                    "timeout_seconds": 60,
                    "produces": [],
                },
                {
                    "id": "B",
                    "kind": "agent",
                    "needs": [],
                    "prompt": "Write b.txt only.",
                    "outputs": ["b.txt"],
                    "verify": [],
                    "timeout_seconds": 60,
                    "produces": [],
                },
            ],
        }
        active_id = "legacy-active-a"
        issued_at = "2026-01-01T00:00:00+00:00"
        return self._seal(
            {
                "schema": "workflow-run",
                "version": 2,
                "run_id": "legacy-frontier-run",
                "created_at": issued_at,
                "run_dir": str(run.resolve()),
                "original_goal": goal,
                # No specification policy or specification fields are present:
                # runtime v2 here means only the old frontier scheduling format.
                "request": {
                    "mode": "workflow",
                    "source_path": str(self.base / "legacy.workflow.json"),
                    "source_sha256": "legacy-source-digest",
                },
                "definition": definition,
                "definition_sha256": None,
                "repo": {"path": str(self.repo.resolve()), "git_head": None},
                "workspace": str(self.repo.resolve()),
                "isolation": {"mode": "none"},
                "planner": None,
                "status": "ready",
                "current_action": None,
                "completed": {},
                "callbacks": {},
                "attempts": [
                    {
                        "action_id": active_id,
                        "step_id": "A",
                        "kind": "agent",
                        "attempt": 1,
                        "issued_at": issued_at,
                        "status": "ready",
                    }
                ],
                "dispatch_history": [],
                "retry_history": [],
                "reconciliation": [],
                "execution_policy": {
                    "mode": "shared-workspace-disjoint",
                    "max_active": 2,
                    "shared_workspace_disjoint": True,
                },
                "active_actions": [
                    {
                        "id": active_id,
                        "kind": "agent",
                        "step_id": "A",
                        "attempt": 1,
                        "status": "ready",
                        "issued_at": issued_at,
                        "execution_argv": None,
                        "output_preimages": {"a.txt": {"exists": False}},
                        "workspace_lease": {
                            "mode": "declared-output-exclusive",
                            "paths": ["a.txt"],
                        },
                    }
                ],
                "claim_requests": {
                    "legacy-a-request": {
                        "request_id": "legacy-a-request",
                        "limit": 1,
                        "action_ids": [active_id],
                        "claimed_at": issued_at,
                    }
                },
            }
        )

    def complete_legacy_agent(
        self,
        run: Path,
        packet: Mapping[str, Any],
        *,
        marker: str,
    ) -> tuple[Path, dict[str, Any]]:
        """Exercise the durable host dispatch and callback protocol from a legacy state."""
        action_id = str(packet["action_id"])
        self.call("prepare-dispatch", "--run-dir", run, "--action", action_id)
        self.call(
            "dispatch",
            "--run-dir",
            run,
            "--action",
            action_id,
            "--handle",
            f"legacy-host-{action_id}",
        )
        output = self.repo / str(packet["outputs"][0])
        output.write_text(marker, encoding="utf-8")
        result = self.base / f"{action_id}.result.json"
        result.write_text(
            json.dumps({"status": "succeeded", "summary": f"accepted {packet['step_id']}"}),
            encoding="utf-8",
        )
        return result, self.call(
            "complete",
            "--run-dir",
            run,
            "--action",
            action_id,
            "--result",
            result,
        )

    def test_legacy_frontier_runtime_v2_definition_v1_recovers_claims_and_completes(self) -> None:
        """A pre-spec v2 runtime retains its active lease and callback identities."""
        run = self.base / "legacy-frontier-run"
        run.mkdir()
        legacy = self.legacy_frontier_state(run)
        self.assertNotIn("specification_policy", legacy)
        self.assertEqual(legacy["definition"]["version"], 1)
        self.write_state(legacy, run)

        cold = self.call("next", "--run-dir", run)
        self.assertEqual(cold["protocol"], "workflow-frontier-v2")
        self.assertEqual(cold["active_count"], 1)
        active_a = cold["active_packets"][0]
        self.assertEqual(active_a["step_id"], "A")
        self.assertEqual(active_a["action_id"], "legacy-active-a")
        self.assertEqual({item["step_id"] for item in cold["ready_frontier"]}, {"B"})
        self.assertNotIn("specification_sha256", cold)

        # The caller that held A's old idempotency key receives that exact
        # existing action, rather than a synthetic successor.
        replayed_a = self.call(
            "claim-ready",
            "--run-dir",
            run,
            "--limit",
            1,
            "--request-id",
            "legacy-a-request",
        )
        self.assertTrue(replayed_a["claim_replayed"])
        self.assertEqual(replayed_a["claimed_action_ids"], ["legacy-active-a"])
        self.assertEqual(replayed_a["claimed_packets"][0]["action_id"], "legacy-active-a")

        newly_claimed_b = self.call(
            "claim-ready",
            "--run-dir",
            run,
            "--limit",
            1,
            "--request-id",
            "legacy-b-request",
        )
        self.assertFalse(newly_claimed_b["claim_replayed"])
        self.assertEqual([item["step_id"] for item in newly_claimed_b["claimed_packets"]], ["B"])
        active_b = newly_claimed_b["claimed_packets"][0]
        self.assertNotEqual(active_b["action_id"], active_a["action_id"])

        result_a, after_a = self.complete_legacy_agent(run, active_a, marker="A\n")
        self.assertEqual(after_a["active_count"], 1)
        self.assertEqual(after_a["active_packets"][0]["action_id"], active_b["action_id"])
        # A cold replay of the accepted callback preserves B rather than
        # recreating it, which is the recovery edge a real interrupted caller sees.
        replay_after_a = self.call(
            "complete",
            "--run-dir",
            run,
            "--action",
            active_a["action_id"],
            "--result",
            result_a,
        )
        self.assertEqual(replay_after_a["active_packets"][0]["action_id"], active_b["action_id"])

        _, terminal = self.complete_legacy_agent(run, active_b, marker="B\n")
        self.assertEqual(terminal["status"], "complete")
        final_state = self.read_state(run)
        self.assertEqual(set(final_state["completed"]), {"A", "B"})
        self.assertFalse(final_state["active_actions"])
        self.assertNotIn("specification_policy", final_state)
        self.assertEqual((self.repo / "a.txt").read_text(encoding="utf-8"), "A\n")
        self.assertEqual((self.repo / "b.txt").read_text(encoding="utf-8"), "B\n")

    def test_accept_spec_transaction_cuts_recover_all_artifacts_and_replay(self) -> None:
        for cut in range(1, 5):
            with self.subTest(cut=cut):
                run = self.base / f"transaction-cut-{cut}"
                first = self.prompt_entry(run=run)
                spec = authored_specification(self.goal)
                source = self.write_packet_spec(first, spec)
                real_transaction = store.transaction

                def interrupted_transaction(
                    root: Any,
                    writes: Mapping[str, str],
                    deletes: Any = None,
                    **kwargs: Any,
                ) -> None:
                    self.assertEqual(
                        set(writes),
                        {
                            "state.md",
                            "packet.md",
                            "requirements/spec.md",
                            "requirements/nfrs.md",
                        },
                    )

                    def fault(point: str, index: int) -> None:
                        self.assertEqual(point, "after-target")
                        if index == cut:
                            raise _InjectedTransactionCrash(f"cut {cut}")

                    self.assertNotIn("fault", kwargs)
                    real_transaction(root, writes, deletes, fault=fault)

                with mock.patch.object(store, "transaction", side_effect=interrupted_transaction):
                    with self.assertRaises(_InjectedTransactionCrash):
                        WorkflowKernel(CLI).accept_spec(
                            run_dir=run,
                            action_id=first["action_id"],
                            spec_file=source,
                        )

                self.assertTrue((run / "transaction.md").is_file())
                recovered = self.call("next", "--run-dir", run)
                self.assertEqual(recovered["kind"], "planning")
                self.assertFalse((run / "transaction.md").exists())
                state = self.read_state(run)
                self.assert_frozen_specification(state, spec, run=run)

                replay = self.call(
                    "accept-spec",
                    "--run-dir",
                    run,
                    "--action",
                    first["action_id"],
                    "--spec",
                    source,
                )
                self.assertEqual(replay["kind"], "planning")
                self.assertEqual(replay["action_id"], recovered["action_id"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
