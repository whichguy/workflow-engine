"""Focused behavior tests for the host-side planning binding companion audit.

Synthetic mutation fixtures below exercise record disagreement only. They do
not attempt to establish or defeat receipt authenticity.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from experiments.planning_binding_audit import audit_companion, sha256_file, sha256_text


ROOT = Path(__file__).resolve().parents[1]
REAL_TERMINAL_FIXTURE = (
    ROOT / "docs/experiments/planning/until-loop-terminal-receipt.json"
)
REAL_CANDIDATE_FIXTURE = ROOT / "docs/experiments/planning/plan.json"
AUDIT_SCRIPT = ROOT / "experiments/planning_binding_audit.py"


class PlanningBindingAuditTests(unittest.TestCase):
    """Build disposable records around the retained terminal packet's real shape."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source_root = self.root / "selected-source-root"
        self.source_root.mkdir()
        self.source = self.source_root / "selected-card.md"
        self.source.write_text("selected source bytes\n", encoding="utf-8")

        self.draft = self.root / "draft.json"
        self.draft.write_text('{"draft": true}\n', encoding="utf-8")
        self.domain_evidence = self.root / "evidence.md"
        self.domain_evidence.write_text("evidence bytes\n", encoding="utf-8")
        self.candidate = self.root / "plan.json"
        shutil.copyfile(REAL_CANDIDATE_FIXTURE, self.candidate)
        self.receipt = self.root / "terminal-receipt.json"
        # This is a copy of the real retained packet, not an invented receipt.
        shutil.copyfile(REAL_TERMINAL_FIXTURE, self.receipt)
        self.real_terminal = json.loads(self.receipt.read_text(encoding="utf-8"))

        self.binding_id = "weave-validation-20260918-90716ff3"
        self.binding_marker = f"Backchain standalone Until Loop binding: {self.binding_id}"
        self.assertIn(self.binding_marker, self.real_terminal["work"])
        self.request = self.real_terminal["context"]["request"]
        self.request_digest = sha256_text(self.request)
        self.candidate_digest = sha256_file(self.candidate)
        scope_text = self.real_terminal["context"]["scope"]
        self.scope_locator = scope_text.split(" under ", 1)[1].split(". Product", 1)[0]
        self.assertTrue(Path(self.scope_locator).is_absolute())

        self.expected_path = self.root / "expected-bindings.json"
        self.companion_path = self.root / "compatibility-native.json"
        self._write_records()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _source_record(self) -> dict[str, str]:
        return {
            "purpose": "selected-card",
            "selected_locator": str(self.source),
            "resolved_locator": str(self.source.resolve()),
            "source_root": str(self.source_root.resolve()),
            "git_commit": "fixture-commit",
            "sha256": sha256_file(self.source),
        }

    def _domain_records(self) -> list[dict[str, str]]:
        return [
            {
                "purpose": "generator-draft",
                "locator": str(self.draft),
                "sha256": sha256_file(self.draft),
            },
            {
                "purpose": "validation-evidence",
                "locator": str(self.domain_evidence),
                "sha256": sha256_file(self.domain_evidence),
            },
        ]

    def _write_records(self) -> None:
        source = self._source_record()
        domain_evidence = self._domain_records()
        expected = {
            "schema": "weave-planning-binding/v1",
            "binding_id": self.binding_id,
            "mode": "native",
            "route": "compatibility-native",
            "request_sha256": self.request_digest,
            "candidate": {
                "locator": str(self.candidate),
                "sha256": self.candidate_digest,
            },
            "scope_locator": self.scope_locator,
            "sources": [copy.deepcopy(source)],
            "domain_evidence": copy.deepcopy(domain_evidence),
        }
        companion = {
            "schema": "weave-compatibility-native-companion/v1",
            "binding_id": self.binding_id,
            "mode": "native",
            "route": "compatibility-native",
            "original_request": {
                "text": self.request,
                "utf8_sha256": self.request_digest,
            },
            "candidate": {
                "input": {
                    "locator": str(self.draft),
                    "sha256": sha256_file(self.draft),
                },
                "final": {
                    "locator": str(self.candidate),
                    "sha256": self.candidate_digest,
                },
            },
            "structural_plan_status": "unknown",
            "selected_sources": [copy.deepcopy(source)],
            "terminal_receipt": {
                "locator": str(self.receipt),
                "sha256": sha256_file(self.receipt),
                "required_status": "complete",
                "binding_marker": self.binding_marker,
                "candidate_sha256": self.candidate_digest,
                "request_sha256": self.request_digest,
            },
            "domain_evidence": copy.deepcopy(domain_evidence),
            "planning_gaps": [],
            "execution_blockers": [],
            "kernel_boundary": "Mechanical companion only; no generic kernel policy.",
        }
        self._save_json(self.expected_path, expected)
        self._save_json(self.companion_path, companion)

    @staticmethod
    def _save_json(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _load_json(path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _summary(self) -> dict[str, object]:
        return audit_companion(self.companion_path, self.expected_path)

    def _update_terminal_receipt_digest(self) -> None:
        companion = self._load_json(self.companion_path)
        terminal = companion["terminal_receipt"]
        assert isinstance(terminal, dict)
        terminal["sha256"] = sha256_file(self.receipt)
        self._save_json(self.companion_path, companion)

    def _mutate_terminal(self, mutate: object) -> None:
        terminal = self._load_json(self.receipt)
        assert callable(mutate)
        mutate(terminal)
        self._save_json(self.receipt, terminal)
        self._update_terminal_receipt_digest()

    def test_real_terminal_packet_shape_is_consistent_with_disposable_bindings(self) -> None:
        summary = self._summary()

        self.assertEqual("consistent", summary["status"])
        self.assertEqual([], summary["failure_codes"])
        self.assertEqual(1, summary["checked"]["source_records"])
        self.assertEqual(2, summary["checked"]["domain_evidence_records"])

    def test_changed_candidate_bytes_are_detected(self) -> None:
        self.candidate.write_bytes(self.candidate.read_bytes() + b"\nchanged")

        self.assertIn("candidate_digest_mismatch", self._summary()["failure_codes"])

    def test_relative_locators_are_rejected_without_cwd_dependency(self) -> None:
        expected = self._load_json(self.expected_path)
        companion = self._load_json(self.companion_path)
        expected["candidate"]["locator"] = "plan.json"
        companion["candidate"]["final"]["locator"] = "plan.json"
        self._save_json(self.expected_path, expected)
        self._save_json(self.companion_path, companion)

        self.assertIn("relative_locator", self._summary()["failure_codes"])

    def test_stopped_and_blocked_terminal_statuses_are_detected(self) -> None:
        for status in ("stopped", "blocked"):
            with self.subTest(status=status):
                self._write_records()
                self._mutate_terminal(lambda terminal: terminal.__setitem__("status", status))

                self.assertIn("terminal_status_mismatch", self._summary()["failure_codes"])
                shutil.copyfile(REAL_TERMINAL_FIXTURE, self.receipt)

    def test_missing_terminal_receipt_is_detected(self) -> None:
        self.receipt.unlink()

        self.assertIn("terminal_receipt_missing", self._summary()["failure_codes"])

    def test_selected_root_and_source_hash_disagreement_are_detected(self) -> None:
        expected = self._load_json(self.expected_path)
        companion = self._load_json(self.companion_path)
        wrong_resolved = str(self.root / "other-source-root" / "selected-card.md")
        for record in (expected["sources"][0], companion["selected_sources"][0]):
            record["resolved_locator"] = wrong_resolved
        self._save_json(self.expected_path, expected)
        self._save_json(self.companion_path, companion)

        self.assertIn("source_selected_root_mismatch", self._summary()["failure_codes"])

        self._write_records()
        self.source.write_text("different selected source bytes\n", encoding="utf-8")
        self.assertIn("source_digest_mismatch", self._summary()["failure_codes"])

    def test_directory_source_locator_and_non_directory_root_are_detected(self) -> None:
        expected = self._load_json(self.expected_path)
        companion = self._load_json(self.companion_path)
        for record in (expected["sources"][0], companion["selected_sources"][0]):
            record["selected_locator"] = str(self.source_root)
            record["resolved_locator"] = str(self.source_root)
        self._save_json(self.expected_path, expected)
        self._save_json(self.companion_path, companion)
        self.assertIn("source_selected_not_file", self._summary()["failure_codes"])

        self._write_records()
        expected = self._load_json(self.expected_path)
        companion = self._load_json(self.companion_path)
        for record in (expected["sources"][0], companion["selected_sources"][0]):
            record["source_root"] = str(self.source)
        self._save_json(self.expected_path, expected)
        self._save_json(self.companion_path, companion)
        self.assertIn("source_root_not_directory", self._summary()["failure_codes"])

    def test_mismatched_binding_identifier_and_scope_are_detected(self) -> None:
        companion = self._load_json(self.companion_path)
        companion["binding_id"] = "different-binding-id"
        self._save_json(self.companion_path, companion)
        self.assertIn("binding_id_mismatch", self._summary()["failure_codes"])

        self._write_records()
        self._mutate_terminal(
            lambda terminal: terminal["context"].__setitem__("scope", "unrelated scope")
        )
        self.assertIn("terminal_scope_mismatch", self._summary()["failure_codes"])

    def test_mismatched_terminal_binding_marker_is_detected(self) -> None:
        self._mutate_terminal(
            lambda terminal: terminal.__setitem__("work", "a different binding record")
        )

        self.assertIn("terminal_binding_mismatch", self._summary()["failure_codes"])

    def test_mismatched_terminal_request_is_detected(self) -> None:
        self._mutate_terminal(
            lambda terminal: terminal["context"].__setitem__("request", "different request")
        )

        self.assertIn("terminal_request_mismatch", self._summary()["failure_codes"])

    def test_candidate_input_must_match_an_expected_domain_record(self) -> None:
        unrelated = self.root / "unrelated-input.json"
        unrelated.write_text('{"unrelated": true}\n', encoding="utf-8")
        companion = self._load_json(self.companion_path)
        companion["candidate"]["input"] = {
            "locator": str(unrelated),
            "sha256": sha256_file(unrelated),
        }
        self._save_json(self.companion_path, companion)

        self.assertIn("candidate_input_domain_mismatch", self._summary()["failure_codes"])

    def test_domain_evidence_drift_and_planning_gaps_are_detected(self) -> None:
        self.domain_evidence.write_text("changed evidence bytes\n", encoding="utf-8")
        self.assertIn("domain_evidence_digest_mismatch", self._summary()["failure_codes"])

        self._write_records()
        companion = self._load_json(self.companion_path)
        companion["planning_gaps"] = ["synthetic pending gap"]
        self._save_json(self.companion_path, companion)
        self.assertIn("planning_gaps_present", self._summary()["failure_codes"])

    def test_empty_source_and_domain_evidence_sets_are_rejected(self) -> None:
        expected = self._load_json(self.expected_path)
        companion = self._load_json(self.companion_path)
        expected["sources"] = []
        companion["selected_sources"] = []
        self._save_json(self.expected_path, expected)
        self._save_json(self.companion_path, companion)
        summary = self._summary()
        self.assertIn("expected_bindings_schema_invalid", summary["failure_codes"])
        self.assertIn("companion_schema_invalid", summary["failure_codes"])

        self._write_records()
        expected = self._load_json(self.expected_path)
        companion = self._load_json(self.companion_path)
        expected["domain_evidence"] = []
        companion["domain_evidence"] = []
        self._save_json(self.expected_path, expected)
        self._save_json(self.companion_path, companion)
        summary = self._summary()
        self.assertIn("expected_bindings_schema_invalid", summary["failure_codes"])
        self.assertIn("companion_schema_invalid", summary["failure_codes"])

    def test_malformed_companion_is_reported_without_a_crash(self) -> None:
        self.companion_path.write_text("[]\n", encoding="utf-8")

        summary = self._summary()
        self.assertEqual("incomplete", summary["status"])
        self.assertIn("companion_schema_invalid", summary["failure_codes"])

    def test_cli_emits_machine_readable_summary_and_exit_status(self) -> None:
        command = [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--companion",
            str(self.companion_path),
            "--expected-bindings",
            str(self.expected_path),
        ]
        good = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(0, good.returncode, good.stderr)
        self.assertEqual("consistent", json.loads(good.stdout)["status"])

        self.candidate.write_bytes(self.candidate.read_bytes() + b"\nchanged")
        bad = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(1, bad.returncode, bad.stderr)
        self.assertIn("candidate_digest_mismatch", json.loads(bad.stdout)["failure_codes"])


if __name__ == "__main__":
    unittest.main()
