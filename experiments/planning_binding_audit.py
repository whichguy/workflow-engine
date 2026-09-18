#!/usr/bin/env python3
"""Mechanically compare a compatibility-native planning companion to its bindings.

The audit intentionally validates local records, paths, and SHA-256 digests. It
does not authenticate a retained receipt, assess the semantic quality of a
review, or impose Until Loop policy on the generic workflow kernel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


COMPANION_SCHEMA = "weave-compatibility-native-companion/v1"
EXPECTED_BINDINGS_SCHEMA = "weave-planning-binding/v1"
LIMITATIONS = (
    "This is a local mechanical consistency check. It does not authenticate a "
    "receipt, prove semantic review truth, or change generic kernel policy."
)


class DuplicateKeyError(ValueError):
    """Raised when a JSON object contains two records for one key."""


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of *path* without treating its text as JSON."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, missing_code: str, invalid_code: str, failures: list[str]) -> Any | None:
    if not path.is_file():
        _add_failure(failures, missing_code)
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=_no_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateKeyError):
        _add_failure(failures, invalid_code)
        return None


def _add_failure(failures: list[str], code: str) -> None:
    if code not in failures:
        failures.append(code)


def _string(record: Any, field: str, invalid_code: str, failures: list[str]) -> str | None:
    if not isinstance(record, dict):
        _add_failure(failures, invalid_code)
        return None
    value = record.get(field)
    if not isinstance(value, str) or not value:
        _add_failure(failures, invalid_code)
        return None
    return value


def _absolute_path(value: str, failures: list[str]) -> Path | None:
    """Accept only absolute locators so the audit has no caller-CWD dependency."""

    path = Path(value)
    if not path.is_absolute():
        _add_failure(failures, "relative_locator")
        return None
    return path


def _record_map(
    records: Any,
    invalid_code: str,
    failures: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list):
        _add_failure(failures, invalid_code)
        return {}

    mapped: dict[str, dict[str, Any]] = {}
    for record in records:
        purpose = _string(record, "purpose", invalid_code, failures)
        if purpose is None or not isinstance(record, dict):
            continue
        if purpose in mapped:
            _add_failure(failures, invalid_code)
            continue
        mapped[purpose] = record
    return mapped


def _compare_text_fields(
    expected: dict[str, Any],
    companion: dict[str, Any],
    fields: tuple[str, ...],
    invalid_code: str,
    mismatch_code: str,
    failures: list[str],
) -> None:
    for field in fields:
        expected_value = _string(expected, field, invalid_code, failures)
        companion_value = _string(companion, field, invalid_code, failures)
        if expected_value is not None and companion_value is not None and expected_value != companion_value:
            _add_failure(failures, mismatch_code)


def _audit_sources(expected: dict[str, Any], companion: dict[str, Any], failures: list[str]) -> int:
    expected_sources = _record_map(
        expected.get("sources"), "expected_bindings_schema_invalid", failures
    )
    companion_sources = _record_map(
        companion.get("selected_sources"), "companion_schema_invalid", failures
    )
    if not expected_sources:
        _add_failure(failures, "expected_bindings_schema_invalid")
    if not companion_sources:
        _add_failure(failures, "companion_schema_invalid")
    if set(expected_sources) != set(companion_sources):
        _add_failure(failures, "source_binding_set_mismatch")

    for purpose in sorted(set(expected_sources) & set(companion_sources)):
        expected_record = expected_sources[purpose]
        companion_record = companion_sources[purpose]
        _compare_text_fields(
            expected_record,
            companion_record,
            (
                "selected_locator",
                "resolved_locator",
                "source_root",
                "git_commit",
                "sha256",
            ),
            "source_binding_malformed",
            "source_binding_mismatch",
            failures,
        )

        selected_locator = _string(
            expected_record, "selected_locator", "source_binding_malformed", failures
        )
        expected_resolved = _string(
            expected_record, "resolved_locator", "source_binding_malformed", failures
        )
        source_root = _string(
            expected_record, "source_root", "source_binding_malformed", failures
        )
        expected_digest = _string(expected_record, "sha256", "source_binding_malformed", failures)
        companion_digest = _string(companion_record, "sha256", "source_binding_malformed", failures)
        if None in (selected_locator, expected_resolved, source_root, expected_digest, companion_digest):
            continue

        selected_path = _absolute_path(selected_locator, failures)
        resolved_path = _absolute_path(expected_resolved, failures)
        source_root_path = _absolute_path(source_root, failures)
        if None in (selected_path, resolved_path, source_root_path):
            continue
        try:
            resolved_selected = selected_path.resolve(strict=True)
        except OSError:
            _add_failure(failures, "source_missing")
            continue
        if not resolved_selected.is_file():
            _add_failure(failures, "source_selected_not_file")
            continue
        if str(resolved_selected) != str(resolved_path):
            _add_failure(failures, "source_selected_root_mismatch")

        try:
            resolved_root = source_root_path.resolve(strict=True)
        except OSError:
            _add_failure(failures, "source_root_missing")
        else:
            if not resolved_root.is_dir():
                _add_failure(failures, "source_root_not_directory")
            else:
                try:
                    resolved_selected.relative_to(resolved_root)
                except ValueError:
                    _add_failure(failures, "source_outside_root")

        if expected_digest != companion_digest:
            _add_failure(failures, "source_hash_binding_mismatch")
        try:
            actual_digest = sha256_file(resolved_selected)
        except OSError:
            _add_failure(failures, "source_unreadable")
            continue
        if actual_digest != expected_digest:
            _add_failure(failures, "source_digest_mismatch")

    return len(expected_sources)


def _audit_domain_evidence(expected: dict[str, Any], companion: dict[str, Any], failures: list[str]) -> int:
    expected_records = _record_map(
        expected.get("domain_evidence"), "expected_bindings_schema_invalid", failures
    )
    companion_records = _record_map(
        companion.get("domain_evidence"), "companion_schema_invalid", failures
    )
    if not expected_records:
        _add_failure(failures, "expected_bindings_schema_invalid")
    if not companion_records:
        _add_failure(failures, "companion_schema_invalid")
    if set(expected_records) != set(companion_records):
        _add_failure(failures, "domain_evidence_set_mismatch")

    for purpose in sorted(set(expected_records) & set(companion_records)):
        expected_record = expected_records[purpose]
        companion_record = companion_records[purpose]
        _compare_text_fields(
            expected_record,
            companion_record,
            ("locator", "sha256"),
            "domain_evidence_malformed",
            "domain_evidence_binding_mismatch",
            failures,
        )
        locator = _string(expected_record, "locator", "domain_evidence_malformed", failures)
        expected_digest = _string(expected_record, "sha256", "domain_evidence_malformed", failures)
        if locator is None or expected_digest is None:
            continue
        evidence_path = _absolute_path(locator, failures)
        if evidence_path is None:
            continue
        if not evidence_path.is_file():
            _add_failure(failures, "domain_evidence_missing")
        else:
            try:
                actual_digest = sha256_file(evidence_path)
            except OSError:
                _add_failure(failures, "domain_evidence_unreadable")
            else:
                if actual_digest != expected_digest:
                    _add_failure(failures, "domain_evidence_digest_mismatch")

    return len(expected_records)


def _audit_candidate(expected: dict[str, Any], companion: dict[str, Any], failures: list[str]) -> None:
    expected_candidate = expected.get("candidate")
    companion_candidate = companion.get("candidate")
    if not isinstance(expected_candidate, dict) or not isinstance(companion_candidate, dict):
        _add_failure(failures, "candidate_binding_malformed")
        return
    companion_final = companion_candidate.get("final")
    if not isinstance(companion_final, dict):
        _add_failure(failures, "candidate_binding_malformed")
        return
    _compare_text_fields(
        expected_candidate,
        companion_final,
        ("locator", "sha256"),
        "candidate_binding_malformed",
        "candidate_binding_mismatch",
        failures,
    )
    locator = _string(expected_candidate, "locator", "candidate_binding_malformed", failures)
    expected_digest = _string(expected_candidate, "sha256", "candidate_binding_malformed", failures)
    if locator is not None and expected_digest is not None:
        candidate_path = _absolute_path(locator, failures)
        if candidate_path is None:
            return
        if not candidate_path.is_file():
            _add_failure(failures, "candidate_missing")
        else:
            try:
                actual_digest = sha256_file(candidate_path)
            except OSError:
                _add_failure(failures, "candidate_unreadable")
            else:
                if actual_digest != expected_digest:
                    _add_failure(failures, "candidate_digest_mismatch")

    companion_input = companion_candidate.get("input")
    if not isinstance(companion_input, dict):
        _add_failure(failures, "candidate_input_malformed")
        return
    input_locator = _string(companion_input, "locator", "candidate_input_malformed", failures)
    input_digest = _string(companion_input, "sha256", "candidate_input_malformed", failures)
    if input_locator is None or input_digest is None:
        return
    input_path = _absolute_path(input_locator, failures)
    if input_path is None:
        return
    if not input_path.is_file():
        _add_failure(failures, "candidate_input_missing")
    else:
        try:
            actual_digest = sha256_file(input_path)
        except OSError:
            _add_failure(failures, "candidate_input_unreadable")
        else:
            if actual_digest != input_digest:
                _add_failure(failures, "candidate_input_digest_mismatch")

    # The native companion declares the input as one of the expected domain
    # records. This binds it to an upstream artifact without requiring a fixed
    # record count or purpose vocabulary.
    expected_domain = _record_map(
        expected.get("domain_evidence"), "expected_bindings_schema_invalid", failures
    )
    matches_input = False
    for evidence in expected_domain.values():
        evidence_locator = _string(
            evidence, "locator", "expected_bindings_schema_invalid", failures
        )
        evidence_digest = _string(
            evidence, "sha256", "expected_bindings_schema_invalid", failures
        )
        if evidence_locator == input_locator and evidence_digest == input_digest:
            matches_input = True
    if not matches_input:
        _add_failure(failures, "candidate_input_domain_mismatch")


def _audit_terminal(expected: dict[str, Any], companion: dict[str, Any], failures: list[str]) -> None:
    terminal = companion.get("terminal_receipt")
    if not isinstance(terminal, dict):
        _add_failure(failures, "terminal_receipt_malformed")
        return
    locator = _string(terminal, "locator", "terminal_receipt_malformed", failures)
    receipt_digest = _string(terminal, "sha256", "terminal_receipt_malformed", failures)
    required_status = _string(terminal, "required_status", "terminal_receipt_malformed", failures)
    binding_marker = _string(terminal, "binding_marker", "terminal_receipt_malformed", failures)
    candidate_digest = _string(terminal, "candidate_sha256", "terminal_receipt_malformed", failures)
    request_digest = _string(terminal, "request_sha256", "terminal_receipt_malformed", failures)
    if None in (locator, receipt_digest, required_status, binding_marker, candidate_digest, request_digest):
        return
    if required_status != "complete":
        _add_failure(failures, "terminal_required_status_invalid")

    binding_id = _string(companion, "binding_id", "companion_schema_invalid", failures)
    expected_request_digest = _string(
        expected, "request_sha256", "expected_bindings_schema_invalid", failures
    )
    expected_candidate = expected.get("candidate")
    expected_candidate_digest = _string(
        expected_candidate, "sha256", "expected_bindings_schema_invalid", failures
    )
    expected_scope = _string(
        expected, "scope_locator", "expected_bindings_schema_invalid", failures
    )
    if expected_scope is not None and _absolute_path(expected_scope, failures) is None:
        expected_scope = None
    if binding_id is not None and binding_id not in binding_marker:
        _add_failure(failures, "terminal_binding_descriptor_mismatch")
    if expected_request_digest is not None and request_digest != expected_request_digest:
        _add_failure(failures, "terminal_request_binding_mismatch")
    if expected_candidate_digest is not None and candidate_digest != expected_candidate_digest:
        _add_failure(failures, "terminal_candidate_binding_mismatch")

    receipt_path = _absolute_path(locator, failures)
    if receipt_path is None:
        return
    if not receipt_path.is_file():
        _add_failure(failures, "terminal_receipt_missing")
        return
    try:
        actual_receipt_digest = sha256_file(receipt_path)
    except OSError:
        _add_failure(failures, "terminal_receipt_unreadable")
        return
    if actual_receipt_digest != receipt_digest:
        _add_failure(failures, "terminal_receipt_digest_mismatch")
        return
    receipt = _load_json(
        receipt_path, "terminal_receipt_missing", "terminal_receipt_invalid_json", failures
    )
    if not isinstance(receipt, dict):
        if receipt is not None:
            _add_failure(failures, "terminal_receipt_invalid_json")
        return

    status = _string(receipt, "status", "terminal_receipt_invalid_json", failures)
    if status is not None and status != required_status:
        _add_failure(failures, "terminal_status_mismatch")
    work = _string(receipt, "work", "terminal_receipt_invalid_json", failures)
    if work is not None and binding_marker not in work:
        _add_failure(failures, "terminal_binding_mismatch")

    context = receipt.get("context")
    context_request = _string(context, "request", "terminal_receipt_invalid_json", failures)
    context_scope = _string(context, "scope", "terminal_receipt_invalid_json", failures)
    if context_request is not None and sha256_text(context_request) != request_digest:
        _add_failure(failures, "terminal_request_mismatch")
    if (
        context_request is not None
        and expected_request_digest is not None
        and sha256_text(context_request) != expected_request_digest
    ):
        _add_failure(failures, "terminal_request_mismatch")
    if context_scope is not None and expected_scope is not None and expected_scope not in context_scope:
        _add_failure(failures, "terminal_scope_mismatch")

    conditions = receipt.get("conditions")
    exit_condition = _string(conditions, "exit", "terminal_receipt_invalid_json", failures)
    if exit_condition is not None and candidate_digest not in exit_condition:
        _add_failure(failures, "terminal_candidate_scope_mismatch")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def audit_companion(companion_path: Path, expected_bindings_path: Path) -> dict[str, Any]:
    """Return a stable summary of mechanical binding checks for two JSON records."""

    failures: list[str] = []
    companion_path = Path(companion_path)
    expected_bindings_path = Path(expected_bindings_path)
    expected = _load_json(
        expected_bindings_path,
        "expected_bindings_missing",
        "expected_bindings_invalid_json",
        failures,
    )
    companion = _load_json(
        companion_path,
        "companion_missing",
        "companion_invalid_json",
        failures,
    )

    checked = {
        "source_records": 0,
        "domain_evidence_records": 0,
        "terminal_fields": ["status", "work.binding", "context.request", "context.scope", "conditions.exit"],
    }
    if not isinstance(expected, dict):
        if expected is not None:
            _add_failure(failures, "expected_bindings_schema_invalid")
    if not isinstance(companion, dict):
        if companion is not None:
            _add_failure(failures, "companion_schema_invalid")
    if not isinstance(expected, dict) or not isinstance(companion, dict):
        return _summary(failures, checked)

    if expected.get("schema") != EXPECTED_BINDINGS_SCHEMA:
        _add_failure(failures, "expected_bindings_schema_invalid")
    if companion.get("schema") != COMPANION_SCHEMA:
        _add_failure(failures, "companion_schema_invalid")
    if failures:
        return _summary(failures, checked)

    _compare_text_fields(
        expected,
        companion,
        ("binding_id", "mode", "route"),
        "companion_schema_invalid",
        "binding_id_mismatch",
        failures,
    )
    expected_request_digest = _string(
        expected, "request_sha256", "expected_bindings_schema_invalid", failures
    )
    original_request = companion.get("original_request")
    request_text = _string(original_request, "text", "companion_schema_invalid", failures)
    request_digest = _string(original_request, "utf8_sha256", "companion_schema_invalid", failures)
    if request_text is not None and request_digest is not None and sha256_text(request_text) != request_digest:
        _add_failure(failures, "request_digest_mismatch")
    if request_digest is not None and expected_request_digest is not None and request_digest != expected_request_digest:
        _add_failure(failures, "request_binding_mismatch")

    _audit_candidate(expected, companion, failures)
    checked["source_records"] = _audit_sources(expected, companion, failures)
    checked["domain_evidence_records"] = _audit_domain_evidence(expected, companion, failures)
    _audit_terminal(expected, companion, failures)

    planning_gaps = companion.get("planning_gaps")
    if not isinstance(planning_gaps, list):
        _add_failure(failures, "companion_schema_invalid")
    elif planning_gaps:
        _add_failure(failures, "planning_gaps_present")
    if not isinstance(companion.get("structural_plan_status"), str):
        _add_failure(failures, "companion_schema_invalid")
    if not isinstance(companion.get("execution_blockers"), list):
        _add_failure(failures, "companion_schema_invalid")
    if not isinstance(companion.get("kernel_boundary"), str) or not companion["kernel_boundary"]:
        _add_failure(failures, "companion_schema_invalid")

    return _summary(failures, checked)


def _summary(failures: list[str], checked: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "consistent" if not failures else "incomplete",
        "failure_codes": failures,
        "checked": checked,
        "limitations": LIMITATIONS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companion", type=Path, required=True)
    parser.add_argument("--expected-bindings", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = audit_companion(args.companion, args.expected_bindings)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "consistent" else 1


if __name__ == "__main__":
    sys.exit(main())
