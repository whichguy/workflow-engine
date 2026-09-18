"""Tests for the narrow Backchain and Git adapter contracts."""

from __future__ import annotations

import copy
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from adapters import AdapterError, compile_backchain, create_workspace  # noqa: E402


def _backchain_root() -> Path | None:
    configured = os.environ.get("WORKFLOW_TEST_BACKCHAIN_ROOT")
    candidate = Path(configured) if configured else REPO_ROOT.parent / "backchain"
    if (
        candidate.is_dir()
        and (candidate / "harness" / "run-prompt.sh").is_file()
        and (candidate / "schema" / "plan.schema.json").is_file()
    ):
        return candidate.resolve()
    return None


def _plan(*, unresolved: bool = False) -> dict:
    plan = {
        "goal": "Compile a verified adapter workflow",
        "initial_state": ["The local adapter test fixture exists"],
        "steps": [
            {
                "id": "S1",
                "statement": "Describe the first action without supplying executable text",
                "produces": ["first artifact"],
                "inputs": [
                    {"need": "The local adapter test fixture exists", "from": None}
                ],
                "origin": "seed",
            },
            {
                "id": "S2",
                "statement": "Describe a dependent action without supplying executable text",
                "produces": ["second artifact"],
                "inputs": [{"need": "first artifact", "from": "S1"}],
                "origin": "seed",
            },
        ],
        "parallel_groups": [],
        "unresolved": [],
    }
    if unresolved:
        plan["unresolved"] = [
            {
                "step": "S2",
                "need": "external approval receipt",
                "reason": "residual-risk",
            }
        ]
    return plan


def _plan_without_initial_facts() -> dict:
    return {
        "goal": "Compile a workflow without initial facts",
        "initial_state": [],
        "steps": [
            {
                "id": "S1",
                "statement": "Describe a root action without executable text",
                "produces": ["root artifact"],
                "inputs": [],
                "origin": "seed",
            },
            {
                "id": "S2",
                "statement": "Describe a dependent action without executable text",
                "produces": ["dependent artifact"],
                "inputs": [{"need": "root artifact", "from": "S1"}],
                "origin": "seed",
            },
        ],
        "parallel_groups": [],
        "unresolved": [],
    }


def _bindings(evidence: Path, *, include_evidence: bool = True) -> dict:
    return {
        "S1": {
            "kind": "command",
            "argv": [sys.executable, "-c", "print('first')"],
            "outputs": ["first.txt"],
            "verify": [[sys.executable, "-c", "print('checked first')"]],
            "timeout_seconds": 30,
        },
        "S2": {
            "kind": "agent",
            "prompt": "Use the accepted first artifact and produce the second artifact.",
            "outputs": ["second.txt"],
            "verify": [[sys.executable, "-c", "print('checked second')"]],
            "timeout_seconds": 45,
        },
        "_initial_evidence": (
            {"The local adapter test fixture exists": str(evidence)}
            if include_evidence
            else {}
        ),
    }


class BackchainAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.backchain_root = _backchain_root()

    def setUp(self) -> None:
        if self.backchain_root is None:
            self.skipTest(
                "set WORKFLOW_TEST_BACKCHAIN_ROOT or place Backchain beside workflow-engine"
            )
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.evidence = self.root / "initial-evidence.txt"
        self.evidence.write_text("fixture attestation\n", encoding="utf-8")

    def tearDown(self) -> None:
        if hasattr(self, "tempdir"):
            self.tempdir.cleanup()

    def test_compiles_complete_plan_with_real_selected_package(self) -> None:
        plan = _plan()
        original = copy.deepcopy(plan)
        workflow, provenance = compile_backchain(
            self.backchain_root,
            plan,
            _bindings(self.evidence),
            self.root / "staging",
        )

        self.assertEqual(plan, original, "adapter must not mutate the submitted plan")
        self.assertEqual(workflow["version"], 1)
        self.assertEqual(workflow["goal"], plan["goal"])
        self.assertEqual([step["id"] for step in workflow["steps"]], ["S1", "S2"])
        self.assertEqual(workflow["steps"][0]["needs"], [])
        self.assertEqual(workflow["steps"][1]["needs"], ["S1"])
        self.assertEqual(workflow["steps"][0]["argv"], _bindings(self.evidence)["S1"]["argv"])
        self.assertNotIn("statement", workflow["steps"][0])

        self.assertEqual(provenance["backchain_root"], str(self.backchain_root))
        self.assertTrue(provenance["selected_tool_digest"])
        self.assertIsInstance(provenance["backchain_source"]["dirty"], bool)
        self.assertEqual(len(provenance["backchain_source"]["status_sha256"]), 64)
        self.assertEqual(provenance["validation"]["returncode"], 0)
        artifacts = provenance["validation"]["artifacts"]
        for name in ("packaged.json", "validation.json", "handoff.json", "run.json"):
            self.assertTrue(Path(artifacts[name]["path"]).is_file())
            self.assertEqual(len(artifacts[name]["sha256"]), 64)
        copied = provenance["initial_evidence"]["The local adapter test fixture exists"]
        self.assertEqual(Path(copied["source"]), self.evidence)
        self.assertTrue(Path(copied["copied"]).is_file())
        self.assertEqual(
            copied["sha256"],
            hashlib.sha256(self.evidence.read_bytes()).hexdigest(),
        )
        self.assertEqual(Path(copied["copied"]).read_text(encoding="utf-8"), "fixture attestation\n")

    def test_rejects_missing_evidence_for_consumed_initial_fact(self) -> None:
        with self.assertRaisesRegex(AdapterError, "missing attested initial evidence"):
            compile_backchain(
                self.backchain_root,
                _plan(),
                _bindings(self.evidence, include_evidence=False),
                self.root / "missing-evidence",
            )

    def test_rejects_structurally_valid_incomplete_backchain_plan(self) -> None:
        with self.assertRaisesRegex(AdapterError, "not complete"):
            compile_backchain(
                self.backchain_root,
                _plan(unresolved=True),
                _bindings(self.evidence),
                self.root / "unresolved",
            )

    def test_defaults_optional_binding_fields_without_initial_evidence(self) -> None:
        workflow, _provenance = compile_backchain(
            self.backchain_root,
            _plan_without_initial_facts(),
            {
                "S1": {"kind": "command", "argv": [sys.executable, "-c", "print('root')"]},
                "S2": {
                    "kind": "agent",
                    "prompt": "Produce the dependent artifact.",
                    "outputs": ["dependent.txt"],
                },
            },
            self.root / "defaults",
        )
        self.assertEqual(workflow["steps"][0]["outputs"], [])
        self.assertEqual(workflow["steps"][1]["outputs"], ["dependent.txt"])
        for step in workflow["steps"]:
            self.assertEqual(step["verify"], [])
            self.assertEqual(step["timeout_seconds"], 60)

    def test_rejects_host_binding_without_evidence_boundary(self) -> None:
        with self.assertRaisesRegex(AdapterError, "requires outputs or verify"):
            compile_backchain(
                self.backchain_root,
                _plan_without_initial_facts(),
                {
                    "S1": {"kind": "command", "argv": [sys.executable, "-c", "print('root')"]},
                    "S2": {"kind": "agent", "prompt": "Produce the dependent artifact."},
                },
                self.root / "missing-host-evidence",
            )

    def test_rejects_unsafe_and_colliding_declared_outputs(self) -> None:
        unsafe = _bindings(self.evidence)
        unsafe["S1"]["outputs"] = ["../outside.txt"]
        with self.assertRaisesRegex(AdapterError, "safe relative path"):
            compile_backchain(
                self.backchain_root,
                _plan(),
                unsafe,
                self.root / "unsafe-output",
            )

        colliding = _bindings(self.evidence)
        colliding["S1"]["outputs"] = ["shared.txt"]
        colliding["S2"]["outputs"] = ["shared.txt/nested.txt"]
        with self.assertRaisesRegex(AdapterError, "claimed more than once"):
            compile_backchain(
                self.backchain_root,
                _plan(),
                colliding,
                self.root / "colliding-output",
            )


class WorkspaceAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self._git("init")
        self._git("config", "user.email", "adapter@example.test")
        self._git("config", "user.name", "Workflow Adapter")
        (self.repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        self._git("add", "tracked.txt")
        self._git("commit", "-m", "base")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        git = shutil.which("git")
        if not git:
            self.skipTest("git is unavailable")
        result = subprocess.run(
            [git, "-C", str(self.repo), *args],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_creates_detached_workspace_from_clean_repository_root(self) -> None:
        result = create_workspace(self.repo, self.root / "run")
        workspace = Path(result["workspace"])
        self.assertEqual(result["source_repo"], str(self.repo.resolve()))
        self.assertEqual(result["isolation"], "git-worktree")
        self.assertTrue(workspace.is_dir())
        self.assertEqual(
            subprocess.run(
                [shutil.which("git"), "-C", str(workspace), "rev-parse", "HEAD"],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            ).stdout.strip(),
            result["base_commit"],
        )
        detached = subprocess.run(
            [shutil.which("git"), "-C", str(workspace), "symbolic-ref", "-q", "HEAD"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(detached.returncode, 1)

    def test_rejects_dirty_repository_and_run_inside_source(self) -> None:
        (self.repo / "untracked-input.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(AdapterError, "including untracked files"):
            create_workspace(self.repo, self.root / "run")

        (self.repo / "untracked-input.txt").unlink()
        with self.assertRaisesRegex(AdapterError, "outside the source repository"):
            create_workspace(self.repo, self.repo / "run")

    def test_rejects_repository_subdirectory(self) -> None:
        nested = self.repo / "nested"
        nested.mkdir()
        with self.assertRaisesRegex(AdapterError, "Git root"):
            create_workspace(nested, self.root / "run")


if __name__ == "__main__":
    unittest.main(verbosity=2)
