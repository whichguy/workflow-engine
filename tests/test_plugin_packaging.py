"""Behavioral checks for the generated, relocatable workflow plugin."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "sync-plugin-view.py"
PACKAGE = ROOT / "plugins" / "workflow"
PYTHON = sys.executable


class PluginPackagingTests(unittest.TestCase):
    """Exercise the generated package after it has left its source checkout."""

    maxDiff = None

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="workflow-plugin-packaging-")
        self.addCleanup(self.tempdir.cleanup)
        self.base = Path(self.tempdir.name)

    def invoke(
        self,
        argv: Sequence[object],
        *,
        cwd: Path,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(item) for item in argv],
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def packet(
        self,
        argv: Sequence[object],
        *,
        cwd: Path,
        success: bool = True,
    ) -> dict[str, Any]:
        completed = self.invoke(argv, cwd=cwd)
        self.assertTrue(
            completed.stdout.strip(),
            f"CLI emitted no JSON for {argv!r}; stderr:\n{completed.stderr}",
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - assertion diagnostic
            self.fail(f"CLI stdout was not JSON: {completed.stdout!r}\n{exc}")
        if success:
            self.assertEqual(
                completed.returncode,
                0,
                f"CLI failed for {argv!r}: {payload!r}\nstderr:\n{completed.stderr}",
            )
        else:
            self.assertNotEqual(completed.returncode, 0, payload)
        self.assertIsInstance(payload, dict)
        return payload

    def installed_package(self) -> Path:
        installed = self.base / "installed-workflow"
        shutil.copytree(PACKAGE, installed, symlinks=True)
        return installed

    @staticmethod
    def installed_cli(installed: Path) -> Path:
        cli = installed / "skills" / "workflow" / "scripts" / "workflow"
        if not cli.is_file():  # pragma: no cover - assertion diagnostic
            raise AssertionError(f"generated package has no bundled CLI: {cli}")
        return cli.resolve()

    def assert_packet_uses_installed_cli(self, packet: dict[str, Any], cli: Path) -> None:
        expected = str(cli)
        for label in ("next_argv", "recovery_argv"):
            callback = packet[label]
            self.assertIsInstance(callback, list, (label, packet))
            self.assertEqual(callback[0], expected, (label, callback))
        for operation, callback in packet["allowed_operations"].items():
            self.assertEqual(callback[0], expected, (operation, callback))

    def accept_specification(
        self,
        packet: dict[str, Any],
        specification: Path,
        *,
        cwd: Path,
    ) -> dict[str, Any]:
        """Copy an authored companion into the exact specification callback path."""
        spec_file = Path(str(packet["spec_file"]))
        spec_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(specification, spec_file)
        callback = list(packet["next_argv"])
        self.assertEqual(packet["allowed_operations"]["accept_spec"], callback)
        self.assertEqual(callback[-2], "--spec")
        self.assertEqual(callback[-1], str(spec_file))
        return self.packet(callback, cwd=cwd)

    @staticmethod
    def strings_in(value: Any) -> Iterable[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from PluginPackagingTests.strings_in(child)
        elif isinstance(value, list):
            for child in value:
                yield from PluginPackagingTests.strings_in(child)

    def mini_source_tree(self, name: str) -> Path:
        """Create a self-contained generator fixture whose ROOT resolves here."""
        root = self.base / name
        scripts = root / "scripts"
        source = root / "skills" / "workflow"
        scripts.mkdir(parents=True)
        source.mkdir(parents=True)
        shutil.copy2(GENERATOR, scripts / GENERATOR.name)
        (source / "SKILL.md").write_text(
            "---\nname: workflow\n"
            "description: Test-only materialized workflow card.\n"
            "version: 9.9.9\n---\n# Test workflow\n",
            encoding="utf-8",
        )
        (source / "scripts").mkdir()
        (source / "scripts" / "workflow").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        (root / "LICENSE").write_text("Test license\n", encoding="utf-8")
        return root

    def run_generator(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return self.invoke(
            [PYTHON, root / "scripts" / GENERATOR.name, *args],
            cwd=root,
        )

    def test_generator_check_matches_canonical_source_and_package_is_materialized(self) -> None:
        parity = self.invoke([PYTHON, GENERATOR, "--check"], cwd=ROOT)
        self.assertEqual(parity.returncode, 0, f"{parity.stdout}\n{parity.stderr}")

        installed = self.installed_package()
        for path in (installed, *installed.rglob("*")):
            self.assertFalse(path.is_symlink(), f"package must not contain a symlink: {path}")

        skill_roots = sorted(path.name for path in (installed / "skills").iterdir())
        self.assertEqual(skill_roots, ["workflow"])
        for dependency in ("backchain", "until-loop", "ask-agent", "shiploop", "improve"):
            self.assertFalse((installed / "skills" / dependency).exists(), dependency)

        runtime_files = [
            installed / ".claude-plugin" / "plugin.json",
            installed / ".codex-plugin" / "plugin.json",
            installed / "skills" / "workflow" / "SKILL.md",
            *(installed / "skills" / "workflow" / "scripts").iterdir(),
        ]
        for path in runtime_files:
            self.assertTrue(path.is_file(), path)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(str(ROOT), text, path)
            self.assertNotIn("/Users/", text, path)

        for manifest in runtime_files[:2]:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["name"], "workflow")
            for value in self.strings_in(data):
                self.assertFalse(value.startswith("/"), (manifest, value))
                self.assertNotIn(str(ROOT), value, (manifest, value))

    def test_copied_package_runs_braid_and_cold_recovery_does_not_repeat_effects(self) -> None:
        installed = self.installed_package()
        cli = self.installed_cli(installed)
        unrelated_cwd = self.base / "unrelated-cwd"
        unrelated_cwd.mkdir()
        fixture_dir = self.base / "copied-fixture"
        fixture_dir.mkdir()
        braid = fixture_dir / "braid.workflow.json"
        shutil.copy2(ROOT / "examples" / "braid.workflow.json", braid)
        workspace = self.base / "workspace"
        workspace.mkdir()
        run_dir = self.base / "run"

        help_result = self.invoke([cli, "--help"], cwd=unrelated_cwd)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("usage:", help_result.stdout.lower())

        initial = self.packet(
            [cli, "init", "--workflow", braid, "--repo", workspace, "--run-dir", run_dir],
            cwd=unrelated_cwd,
        )
        self.assertEqual(initial["step_id"], "seed")
        self.assert_packet_uses_installed_cli(initial, cli)

        # Execute the returned callback verbatim: it must stay inside the copied package.
        after_seed = self.packet(initial["next_argv"], cwd=unrelated_cwd)
        self.assertEqual(after_seed["step_id"], "extract")
        self.assert_packet_uses_installed_cli(after_seed, cli)

        terminal = self.packet([cli, "run", "--run-dir", run_dir], cwd=unrelated_cwd)
        self.assertEqual(terminal["status"], "complete")
        self.assert_packet_uses_installed_cli(terminal, cli)
        published = Path(terminal["workspace"]) / "published.md"
        self.assertEqual(
            published.read_text(encoding="utf-8"),
            "# Draft\nalpha,beta / 2\nChecked: PASS\n",
        )
        before_bytes = published.read_bytes()
        before_mtime = published.stat().st_mtime_ns

        cold = self.packet(terminal["recovery_argv"], cwd=unrelated_cwd)
        self.assertEqual(cold["status"], "complete")
        self.assert_packet_uses_installed_cli(cold, cli)
        self.assertEqual(published.read_bytes(), before_bytes)
        self.assertEqual(published.stat().st_mtime_ns, before_mtime)

    def test_copied_package_prompt_callbacks_use_the_installed_cli(self) -> None:
        installed = self.installed_package()
        cli = self.installed_cli(installed)
        unrelated_cwd = self.base / "unrelated-cwd"
        unrelated_cwd.mkdir()
        fixture_dir = self.base / "copied-fixture"
        fixture_dir.mkdir()
        confetti = fixture_dir / "confetti.workflow.json"
        shutil.copy2(ROOT / "examples" / "confetti.workflow.json", confetti)
        workspace = self.base / "workspace"
        workspace.mkdir()
        run_dir = self.base / "run"

        initial = self.packet(
            [cli, "init", "--workflow", confetti, "--repo", workspace, "--run-dir", run_dir],
            cwd=unrelated_cwd,
        )
        prompt = self.packet(initial["next_argv"], cwd=unrelated_cwd)
        for step_id, prefix in (("left-note", "LEFT:"), ("right-note", "RIGHT:")):
            self.assertEqual(prompt["kind"], "prompt")
            self.assertEqual(prompt["step_id"], step_id)
            self.assert_packet_uses_installed_cli(prompt, cli)
            output = Path(prompt["workspace"]) / prompt["declared_outputs"][0]
            output.write_text(f"{prefix} installed callback\n", encoding="utf-8")
            result = Path(prompt["result_file"])
            result.parent.mkdir(parents=True, exist_ok=True)
            result.write_text(
                json.dumps({"status": "succeeded", "summary": f"completed {step_id}"}),
                encoding="utf-8",
            )
            prompt = self.packet(prompt["next_argv"], cwd=unrelated_cwd)

        self.assertEqual(prompt["status"], "complete")
        self.assert_packet_uses_installed_cli(prompt, cli)

    def test_copied_package_prompt_specification_callback_uses_example_companion(self) -> None:
        installed = self.installed_package()
        cli = self.installed_cli(installed)
        unrelated_cwd = self.base / "unrelated-cwd"
        unrelated_cwd.mkdir()
        fixture_dir = self.base / "copied-fixture"
        fixture_dir.mkdir()
        request = fixture_dir / "braid.request.txt"
        specification = fixture_dir / "braid.spec.json"
        shutil.copy2(ROOT / "examples" / "braid.request.txt", request)
        shutil.copy2(ROOT / "examples" / "plans" / "braid.spec.json", specification)
        source_specification = json.loads(specification.read_text(encoding="utf-8"))
        self.assertEqual(source_specification["goal"], request.read_text(encoding="utf-8"))
        workspace = self.base / "workspace"
        workspace.mkdir()
        run_dir = self.base / "run"

        initial = self.packet(
            [
                cli,
                "init",
                "--prompt-file",
                request,
                "--backchain-root",
                workspace,
                "--repo",
                workspace,
                "--run-dir",
                run_dir,
            ],
            cwd=unrelated_cwd,
        )
        self.assertEqual(initial["kind"], "specification")
        self.assertEqual(initial["status"], "specification")
        self.assert_packet_uses_installed_cli(initial, cli)

        planning = self.accept_specification(initial, specification, cwd=unrelated_cwd)
        self.assertEqual(planning["kind"], "planning")
        self.assertEqual(planning["status"], "planning")
        self.assertEqual(planning["specification"], source_specification)
        self.assert_packet_uses_installed_cli(planning, cli)

    def test_copied_package_rejects_a_missing_selected_backchain_source(self) -> None:
        installed = self.installed_package()
        cli = self.installed_cli(installed)
        unrelated_cwd = self.base / "unrelated-cwd"
        unrelated_cwd.mkdir()
        request = self.base / "request.txt"
        shutil.copy2(ROOT / "examples" / "braid.request.txt", request)
        workspace = self.base / "workspace"
        workspace.mkdir()
        run_dir = self.base / "run"
        missing_backchain = self.base / "missing-backchain"

        error = self.packet(
            [
                cli,
                "init",
                "--prompt-file",
                request,
                "--backchain-root",
                missing_backchain,
                "--repo",
                workspace,
                "--run-dir",
                run_dir,
            ],
            cwd=unrelated_cwd,
            success=False,
        )
        self.assertEqual(error["status"], "error")
        self.assertIn("Backchain root", error["error"])
        self.assertFalse(run_dir.exists(), "a missing selected source must not create a run")

    def test_generator_refuses_linked_package_paths_without_writing_through_them(self) -> None:
        for name, linked_path in (
            ("linked-package-root", ("plugins", "workflow")),
            ("linked-intermediate", ("plugins", "workflow", "skills")),
        ):
            with self.subTest(name=name):
                root = self.mini_source_tree(name)
                outside = self.base / f"{name}-outside"
                outside.mkdir()
                sentinel = outside / "sentinel.txt"
                sentinel.write_text("outside stays unchanged\n", encoding="utf-8")
                target = root.joinpath(*linked_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(outside, target, target_is_directory=True)

                rejected = self.run_generator(root)
                self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
                self.assertIn("symlink", rejected.stderr.lower())
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside stays unchanged\n")
                self.assertEqual(
                    sorted(path.relative_to(outside) for path in outside.rglob("*")),
                    [Path("sentinel.txt")],
                )

    def test_disposable_generator_check_detects_drift_without_rewriting_it(self) -> None:
        root = self.mini_source_tree("generator-drift")
        generated = self.run_generator(root)
        self.assertEqual(generated.returncode, 0, f"{generated.stdout}\n{generated.stderr}")

        readme = root / "plugins" / "workflow" / "README.md"
        drifted = readme.read_text(encoding="utf-8") + "deliberate drift\n"
        readme.write_text(drifted, encoding="utf-8")
        checked = self.run_generator(root, "--check")
        self.assertEqual(checked.returncode, 1, f"{checked.stdout}\n{checked.stderr}")
        result = json.loads(checked.stdout)
        self.assertEqual(result["status"], "drift")
        self.assertIn("README.md", result["changed_or_missing"])
        self.assertEqual(readme.read_text(encoding="utf-8"), drifted)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
