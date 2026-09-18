#!/usr/bin/env python3
"""Explicit adapters for Backchain packaging and optional Git isolation.

The Backchain adapter deliberately invokes the selected source checkout's
``harness/run-prompt.sh --package-only`` entry point.  It does not infer an
executable action from a Backchain statement: callers must provide a complete
binding for every accepted Backchain step.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import signal
import stat
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


class AdapterError(RuntimeError):
    """Raised when an external adapter cannot produce a safe durable result."""


_BACKCHAIN_RUNNER = Path("harness/run-prompt.sh")
_BACKCHAIN_SCHEMA = Path("schema/plan.schema.json")
_TOOL_FILES = (
    Path("harness/run-prompt.sh"),
    Path("harness/run-prompt-lib.js"),
    Path("harness/lib.js"),
    Path("harness/bench-lib.js"),
    Path("schema/plan.schema.json"),
)
_PACKAGE_ARTIFACTS = (
    "packaged.json",
    "validation.json",
    "handoff.json",
    "run.json",
)
__all__ = ["AdapterError", "compile_backchain", "create_workspace"]


def _as_path(value: Any, label: str) -> Path:
    if isinstance(value, (str, os.PathLike)):
        return Path(value)
    raise AdapterError(f"{label} must be a filesystem path")


def _resolve_directory(value: Any, label: str) -> Path:
    candidate = _as_path(value, label)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AdapterError(f"{label} does not resolve: {candidate}: {exc}") from exc
    if not resolved.is_dir():
        raise AdapterError(f"{label} is not a directory: {candidate}")
    return resolved


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _regular_file(path: Path, label: str) -> None:
    try:
        details = path.lstat()
    except OSError as exc:
        raise AdapterError(f"{label} is unavailable: {path}: {exc}") from exc
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise AdapterError(f"{label} must be a regular file: {path}")


def _sha256_file(path: Path, label: str) -> str:
    _regular_file(path, label)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AdapterError(f"cannot hash {label}: {path}: {exc}") from exc
    return digest.hexdigest()


def _write_text(path: Path, text: str, label: str) -> None:
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise AdapterError(f"cannot write {label}: {path}: {exc}") from exc


def _run_package_validator(command: Sequence[str], root: Path) -> subprocess.CompletedProcess[str]:
    """Run Backchain in its own process group and leave no timed-out children alive."""
    try:
        process = subprocess.Popen(
            command,
            cwd=str(root),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise AdapterError(f"cannot run selected Backchain package validator: {exc}") from exc
    try:
        stdout, stderr = process.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
        raise AdapterError("Backchain package-only validation timed out after 60 seconds")
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _read_json_object(path: Path, label: str) -> Dict[str, Any]:
    _regular_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"cannot parse {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AdapterError(f"{label} must contain a JSON object: {path}")
    return value


def _git_executable() -> str:
    executable = shutil.which("git")
    if not executable:
        raise AdapterError("git is required for workspace isolation")
    return executable


def _run_git(
    git: str, repo: Path, args: Sequence[str], label: str
) -> subprocess.CompletedProcess[str]:
    command = [git, "-C", str(repo), *args]
    try:
        result = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise AdapterError(f"cannot run git for {label}: {exc}") from exc
    return result


def _git_value(git: str, repo: Path, args: Sequence[str], label: str) -> str:
    result = _run_git(git, repo, args, label)
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise AdapterError(f"git could not determine {label} for {repo}")
    return value


def _selected_backchain(backchain_root: Path) -> Tuple[Path, Path, Path, str]:
    root = _resolve_directory(backchain_root, "Backchain root")
    runner = root / _BACKCHAIN_RUNNER
    schema = root / _BACKCHAIN_SCHEMA
    _regular_file(runner, "selected Backchain runner")
    _regular_file(schema, "selected Backchain schema")

    git = _git_executable()
    git_root = Path(
        _git_value(git, root, ["rev-parse", "--show-toplevel"], "Backchain source root")
    ).resolve()
    if git_root != root:
        raise AdapterError(
            "Backchain root must be the selected source checkout root, "
            f"not a subdirectory: {root}"
        )
    source_commit = _git_value(git, root, ["rev-parse", "--verify", "HEAD"], "Backchain source commit")
    return root, runner, schema, source_commit


def _backchain_source_state(root: Path, source_commit: str) -> Dict[str, Any]:
    git = _git_executable()
    status = _run_git(
        git,
        root,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        "Backchain source status",
    )
    if status.returncode != 0:
        raise AdapterError(f"git could not inspect Backchain source status: {root}")
    return {
        "commit": source_commit,
        "dirty": bool(status.stdout),
        "status_sha256": hashlib.sha256(status.stdout.encode("utf-8")).hexdigest(),
    }


def _assert_backchain_source_unchanged(
    root: Path, expected: Mapping[str, Any], expected_tool_hashes: Mapping[str, Any]
) -> None:
    current_commit = _git_value(
        _git_executable(), root, ["rev-parse", "--verify", "HEAD"], "Backchain source commit"
    )
    if current_commit != expected["commit"]:
        raise AdapterError("selected Backchain source HEAD changed during package-only validation")
    current_state = _backchain_source_state(root, current_commit)
    if current_state != dict(expected):
        raise AdapterError("selected Backchain source changed during package-only validation")
    current_tool_hashes = _artifact_provenance(
        (str(relative), root / relative) for relative in _TOOL_FILES
    )
    if current_tool_hashes != dict(expected_tool_hashes):
        raise AdapterError("selected Backchain tool files changed during package-only validation")


def _prepare_staging(staging: Path, protected_root: Path) -> Path:
    candidate = _as_path(staging, "staging directory")
    try:
        prospective = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise AdapterError(f"staging directory does not resolve: {candidate}: {exc}") from exc
    if _is_within(prospective, protected_root):
        raise AdapterError(
            "staging directory must be outside the selected Backchain source checkout"
        )
    try:
        if candidate.exists() or candidate.is_symlink():
            if candidate.is_symlink() or not candidate.is_dir():
                raise AdapterError(f"staging path is not a directory: {candidate}")
            if any(candidate.iterdir()):
                raise AdapterError(f"staging directory must be fresh and empty: {candidate}")
        else:
            candidate.mkdir(parents=True, exist_ok=False)
        resolved = candidate.resolve(strict=True)
    except AdapterError:
        raise
    except (OSError, RuntimeError) as exc:
        raise AdapterError(f"cannot prepare staging directory {candidate}: {exc}") from exc
    if not resolved.is_dir():
        raise AdapterError(f"staging path is not a directory: {candidate}")
    return resolved


def _normalise_fact(value: str) -> str:
    return " ".join(value.split())


def _compiled_step_ids(plan: Mapping[str, Any]) -> List[str]:
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise AdapterError("Backchain packaged plan has no steps")
    step_ids: List[str] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise AdapterError(f"Backchain packaged step {index} must be an object")
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id:
            raise AdapterError(f"Backchain packaged step {index} has no valid id")
        step_ids.append(step_id)
    if len(set(step_ids)) != len(step_ids):
        raise AdapterError("Backchain packaged plan has duplicate step ids")
    return step_ids


def _validate_package_outputs(
    submitted: Mapping[str, Any], package_dir: Path, runner_returncode: int
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    artifacts = {
        name: _read_json_object(package_dir / name, f"Backchain {name}")
        for name in _PACKAGE_ARTIFACTS
    }
    packaged = artifacts["packaged.json"]
    validation = artifacts["validation.json"]
    handoff = artifacts["handoff.json"]
    run = artifacts["run.json"]

    structure = validation.get("validateStructure")
    completion = validation.get("completionStatus")
    if runner_returncode != 0:
        status = completion.get("status") if isinstance(completion, dict) else "unknown"
        raise AdapterError(
            "Backchain package-only validation failed "
            f"(exit {runner_returncode}, completionStatus={status}); "
            f"inspect {package_dir / 'validation.json'}"
        )
    if not isinstance(structure, dict) or structure.get("ok") is not True:
        raise AdapterError("Backchain package-only output is not structurally valid")
    if (
        not isinstance(completion, dict)
        or completion.get("status") != "complete"
        or completion.get("complete") is not True
    ):
        raise AdapterError(
            "Backchain plan is not complete; unresolved prerequisites or open goal needs remain"
        )
    if validation.get("packaged") != packaged:
        raise AdapterError("Backchain packaged.json does not match validation.json")
    if not isinstance(submitted.get("goal"), str) or not submitted["goal"].strip():
        raise AdapterError("Backchain plan goal must be a nonempty string")
    if packaged.get("goal") != submitted["goal"]:
        raise AdapterError("Backchain package changed the submitted goal")
    if packaged.get("initial_state") != submitted.get("initial_state"):
        raise AdapterError("Backchain package changed the submitted initial_state")
    if not isinstance(handoff, dict) or handoff.get("goal") != submitted["goal"]:
        raise AdapterError("Backchain handoff does not match the submitted goal")
    if run.get("mode") != "package-only" or run.get("exit_code") != 0:
        raise AdapterError("Backchain run manifest does not attest a successful package-only run")
    try:
        reported_out = Path(run["out_dir"]).resolve(strict=True)
    except (KeyError, TypeError, OSError, RuntimeError) as exc:
        raise AdapterError("Backchain run manifest has no valid output directory") from exc
    if reported_out != package_dir:
        raise AdapterError("Backchain run manifest points to a different output directory")

    submitted_ids = _compiled_step_ids(submitted)
    packaged_ids = _compiled_step_ids(packaged)
    if packaged_ids != submitted_ids:
        raise AdapterError("Backchain package did not preserve submitted step ids")
    for submitted_step, packaged_step in zip(submitted["steps"], packaged["steps"]):
        if (
            packaged_step.get("inputs") != submitted_step.get("inputs")
            or packaged_step.get("produces") != submitted_step.get("produces")
        ):
            raise AdapterError(
                f"Backchain package changed inputs or produces for step {packaged_step['id']}"
            )
    handoff_steps = handoff.get("steps")
    if (
        not isinstance(handoff_steps, list)
        or not all(isinstance(step, dict) for step in handoff_steps)
        or [step.get("id") for step in handoff_steps] != packaged_ids
    ):
        raise AdapterError("Backchain handoff does not preserve packaged step ids")
    return packaged, validation, handoff, run


def _validate_command(value: Any, label: str) -> List[str]:
    if not isinstance(value, list) or not value:
        raise AdapterError(f"{label} must be a nonempty argv array")
    if any(not isinstance(item, str) or not item for item in value):
        raise AdapterError(f"{label} argv entries must be nonempty strings")
    return list(value)


def _validate_binding(step_id: str, binding: Any) -> Dict[str, Any]:
    if not isinstance(binding, Mapping):
        raise AdapterError(f"binding for {step_id} must be an object")
    keys = set(binding)
    kind = binding.get("kind")
    optional = {"outputs", "verify", "timeout_seconds"}
    if kind == "command":
        required = {"kind", "argv"}
    elif kind in {"prompt", "agent"}:
        required = {"kind", "prompt"}
    else:
        raise AdapterError(f"binding for {step_id} has unsupported kind: {kind!r}")
    missing = required - keys
    unexpected = keys - required - optional
    if missing or unexpected:
        details: List[str] = []
        if missing:
            details.append(f"missing {sorted(missing)}")
        if unexpected:
            details.append(f"unexpected {sorted(unexpected)}")
        raise AdapterError(
            f"binding for {step_id} must contain {sorted(required)} and only optional "
            f"{sorted(optional)} besides them: {'; '.join(details)}"
        )

    outputs = binding.get("outputs", [])
    if not isinstance(outputs, list) or any(
        not isinstance(item, str) or not item for item in outputs
    ):
        raise AdapterError(f"binding outputs for {step_id} must be an array of nonempty strings")
    verify_raw = binding.get("verify", [])
    if not isinstance(verify_raw, list):
        raise AdapterError(f"binding verify for {step_id} must be an array of argv arrays")
    verify = [
        _validate_command(command, f"binding verify for {step_id}")
        for command in verify_raw
    ]
    timeout = binding.get("timeout_seconds", 60)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise AdapterError(
            f"binding timeout_seconds for {step_id} must be a finite positive number"
        )

    compiled: Dict[str, Any] = {
        "kind": kind,
        "outputs": list(outputs),
        "verify": verify,
        "timeout_seconds": timeout,
    }
    if kind == "command":
        compiled["argv"] = _validate_command(binding.get("argv"), f"binding argv for {step_id}")
    else:
        prompt = binding.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise AdapterError(f"binding prompt for {step_id} must be a nonempty string")
        if not outputs and not verify:
            raise AdapterError(
                f"binding for {step_id} requires outputs or verify for host evidence"
            )
        compiled["prompt"] = prompt
    return compiled


def _validate_bindings(
    packaged: Mapping[str, Any], bindings: Any
) -> Tuple[Dict[str, Dict[str, Any]], Mapping[str, Any]]:
    if not isinstance(bindings, Mapping):
        raise AdapterError("Backchain bindings must be an object")
    step_ids = _compiled_step_ids(packaged)
    binding_keys = set(bindings)
    if any(not isinstance(key, str) for key in binding_keys):
        raise AdapterError("Backchain binding keys must be strings")
    expected = set(step_ids)
    allowed = expected | {"_initial_evidence"}
    if not expected.issubset(binding_keys) or not binding_keys.issubset(allowed):
        missing = sorted(expected - binding_keys)
        extra = sorted(binding_keys - allowed)
        details: List[str] = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unexpected {extra}")
        raise AdapterError("Backchain bindings do not match packaged steps: " + "; ".join(details))
    evidence = bindings.get("_initial_evidence", {})
    if not isinstance(evidence, Mapping):
        raise AdapterError("_initial_evidence must be a mapping of initial fact to evidence file")
    return {step_id: _validate_binding(step_id, bindings[step_id]) for step_id in step_ids}, evidence


def _copy_initial_evidence(
    packaged: Mapping[str, Any], evidence: Mapping[str, Any], staging: Path
) -> Dict[str, Dict[str, Any]]:
    initial_state = packaged.get("initial_state")
    if not isinstance(initial_state, list) or any(
        not isinstance(fact, str) or not fact for fact in initial_state
    ):
        raise AdapterError("Backchain packaged plan has invalid initial_state")
    canonical_by_normalized: Dict[str, str] = {}
    for fact in initial_state:
        normalised = _normalise_fact(fact)
        if normalised in canonical_by_normalized and canonical_by_normalized[normalised] != fact:
            raise AdapterError("Backchain initial_state has ambiguous equivalent facts")
        canonical_by_normalized[normalised] = fact

    for fact, source in evidence.items():
        if not isinstance(fact, str) or fact not in initial_state:
            raise AdapterError("_initial_evidence keys must exactly name declared initial facts")
        if not isinstance(source, str):
            raise AdapterError(f"initial evidence for {fact!r} must be an absolute file path")
        source_path = Path(source)
        if not source_path.is_absolute():
            raise AdapterError(f"initial evidence for {fact!r} must be an absolute file path")
        _regular_file(source_path, f"initial evidence for {fact!r}")

    consumed: List[str] = []
    for step in packaged.get("steps", []):
        if not isinstance(step, dict):
            raise AdapterError("Backchain packaged plan has an invalid step")
        inputs = step.get("inputs")
        if not isinstance(inputs, list):
            raise AdapterError(f"Backchain step {step.get('id')!r} has invalid inputs")
        for input_item in inputs:
            if not isinstance(input_item, dict):
                raise AdapterError(f"Backchain step {step.get('id')!r} has invalid input")
            if input_item.get("from") is None:
                need = input_item.get("need")
                if not isinstance(need, str):
                    raise AdapterError(f"Backchain step {step.get('id')!r} has invalid initial need")
                canonical = canonical_by_normalized.get(_normalise_fact(need))
                if canonical is None:
                    raise AdapterError(f"Backchain initial need is not declared: {need!r}")
                if canonical not in consumed:
                    consumed.append(canonical)
    missing = [fact for fact in consumed if fact not in evidence]
    if missing:
        raise AdapterError(
            "missing attested initial evidence for consumed facts: " + ", ".join(repr(fact) for fact in missing)
        )

    evidence_dir = staging / "initial-evidence"
    try:
        evidence_dir.mkdir(exist_ok=False)
    except OSError as exc:
        raise AdapterError(f"cannot create initial evidence directory: {evidence_dir}: {exc}") from exc

    provenance: Dict[str, Dict[str, Any]] = {}
    for index, fact in enumerate(sorted(evidence)):
        source = Path(evidence[fact])
        destination = evidence_dir / (
            f"{index:04d}-{hashlib.sha256(fact.encode('utf-8')).hexdigest()}.evidence"
        )
        try:
            shutil.copyfile(source, destination)
        except OSError as exc:
            raise AdapterError(f"cannot copy initial evidence for {fact!r}: {exc}") from exc
        source_digest = _sha256_file(source, f"initial evidence for {fact!r}")
        copied_digest = _sha256_file(destination, f"copied initial evidence for {fact!r}")
        if source_digest != copied_digest:
            raise AdapterError(f"initial evidence changed while copying: {source}")
        try:
            size = destination.stat().st_size
        except OSError as exc:
            raise AdapterError(f"cannot stat copied initial evidence for {fact!r}: {exc}") from exc
        provenance[fact] = {
            "source": str(source),
            "copied": str(destination.resolve()),
            "sha256": copied_digest,
            "size": size,
        }
    return provenance


def _validate_output_paths(
    step_id: str, outputs: Sequence[str], claimed: List[str]
) -> List[str]:
    checked: List[str] = []
    for output in outputs:
        if "\x00" in output or "\\" in output or output.startswith("/"):
            raise AdapterError(f"binding output for {step_id} is not a safe relative path: {output!r}")
        parts = output.split("/")
        if any(part in {"", ".", ".."} for part in parts) or ":" in parts[0]:
            raise AdapterError(f"binding output for {step_id} is not a safe relative path: {output!r}")
        output_parts = tuple(parts)
        for existing in claimed:
            existing_parts = tuple(existing.split("/"))
            shortest = min(len(output_parts), len(existing_parts))
            if output_parts[:shortest] == existing_parts[:shortest]:
                raise AdapterError(
                    f"binding output path is claimed more than once: {output!r}"
                )
        claimed.append(output)
        checked.append(output)
    return checked


def _compile_workflow(
    packaged: Mapping[str, Any], bindings: Mapping[str, Mapping[str, Any]]
) -> Dict[str, Any]:
    goal = packaged.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise AdapterError("Backchain packaged plan has no valid goal")
    compiled_steps: List[Dict[str, Any]] = []
    claimed_outputs: List[str] = []
    for step in packaged.get("steps", []):
        assert isinstance(step, dict)  # checked by _compiled_step_ids
        step_id = step["id"]
        needs: List[str] = []
        for input_item in step["inputs"]:
            supplier = input_item["from"]
            if supplier is not None and supplier not in needs:
                needs.append(supplier)
        produces = step.get("produces")
        if not isinstance(produces, list) or any(
            not isinstance(item, str) for item in produces
        ):
            raise AdapterError(f"Backchain step {step_id} has invalid produces")
        binding = dict(bindings[step_id])
        binding["outputs"] = _validate_output_paths(
            step_id, binding["outputs"], claimed_outputs
        )
        compiled = {
            "id": step_id,
            "needs": needs,
            "produces": list(produces),
            **binding,
        }
        compiled_steps.append(compiled)
    return {
        "version": 1,
        "name": "backchain-compiled",
        "goal": goal,
        "steps": compiled_steps,
    }


def _artifact_provenance(paths: Iterable[Tuple[str, Path]]) -> Dict[str, Dict[str, str]]:
    provenance: Dict[str, Dict[str, str]] = {}
    for name, path in paths:
        provenance[name] = {
            "path": str(path.resolve()),
            "sha256": _sha256_file(path, name),
        }
    return provenance


def compile_backchain(
    backchain_root: Path, plan: dict, bindings: dict, staging: Path
) -> Tuple[dict, dict]:
    """Compile a complete, package-validated Backchain graph into workflow v1.

    ``backchain_root`` must name the root of a selected Backchain source checkout;
    installed skills and ambient PATH entries are intentionally not consulted.
    ``staging`` must be fresh and lies outside that checkout so the adapter never
    modifies the source package.
    """
    root, runner, _schema, source_commit = _selected_backchain(backchain_root)
    source_state = _backchain_source_state(root, source_commit)
    tool_hashes = _artifact_provenance(
        (str(relative), root / relative) for relative in _TOOL_FILES
    )
    tool_digest = hashlib.sha256(
        json.dumps(tool_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    staging_root = _prepare_staging(staging, root)
    if not isinstance(plan, dict):
        raise AdapterError("Backchain plan must be a JSON object")
    try:
        submitted_text = json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        submitted = json.loads(submitted_text)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AdapterError(f"Backchain plan is not JSON serializable: {exc}") from exc
    submitted_path = staging_root / "submitted-plan.json"
    _write_text(submitted_path, submitted_text, "submitted Backchain plan")

    package_dir = staging_root / "package"
    command = [
        "/bin/bash",
        str(runner),
        "--package-only",
        str(submitted_path),
        "--quiet",
        "--out-dir",
        str(package_dir),
    ]
    runner_result = _run_package_validator(command, root)
    stdout_path = staging_root / "backchain.stdout.log"
    stderr_path = staging_root / "backchain.stderr.log"
    _write_text(stdout_path, runner_result.stdout, "Backchain stdout log")
    _write_text(stderr_path, runner_result.stderr, "Backchain stderr log")
    _assert_backchain_source_unchanged(root, source_state, tool_hashes)

    packaged, _validation, _handoff, _run = _validate_package_outputs(
        submitted, package_dir, runner_result.returncode
    )
    compiled_bindings, evidence = _validate_bindings(packaged, bindings)
    initial_evidence = _copy_initial_evidence(packaged, evidence, staging_root)
    workflow = _compile_workflow(packaged, compiled_bindings)

    artifacts = _artifact_provenance(
        [("submitted-plan.json", submitted_path), ("stdout", stdout_path), ("stderr", stderr_path)]
        + [(name, package_dir / name) for name in _PACKAGE_ARTIFACTS]
    )
    provenance = {
        "adapter": "backchain-package-only/v1",
        "backchain_root": str(root),
        "backchain_commit": source_commit,
        "backchain_source": source_state,
        "selected_tool_digest": tool_digest,
        "selected_tool_files": tool_hashes,
        "validation": {
            "command": command,
            "returncode": runner_result.returncode,
            "artifacts": artifacts,
        },
        "initial_evidence": initial_evidence,
    }
    return workflow, provenance


def create_workspace(repo: Path, run_dir: Path) -> dict:
    """Create one detached worktree from a clean, exact Git repository root."""
    source_repo = _resolve_directory(repo, "repository")
    git = _git_executable()
    git_root = Path(
        _git_value(git, source_repo, ["rev-parse", "--show-toplevel"], "repository root")
    ).resolve()
    if git_root != source_repo:
        raise AdapterError(
            f"repository must be the Git root, not a subdirectory: {source_repo}"
        )
    if _git_value(git, source_repo, ["rev-parse", "--is-inside-work-tree"], "work tree state") != "true":
        raise AdapterError(f"repository is not a non-bare work tree: {source_repo}")

    status = _run_git(
        git,
        source_repo,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        "repository cleanliness",
    )
    if status.returncode != 0:
        raise AdapterError(f"git could not inspect repository cleanliness: {source_repo}")
    if status.stdout:
        raise AdapterError(
            "repository must be clean before isolated execution, including untracked files"
        )
    base_commit = _git_value(git, source_repo, ["rev-parse", "--verify", "HEAD"], "HEAD commit")

    requested_run = _as_path(run_dir, "run directory")
    if requested_run.is_symlink():
        raise AdapterError(f"run directory must not be a symlink: {requested_run}")
    try:
        resolved_run = requested_run.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise AdapterError(f"run directory does not resolve: {requested_run}: {exc}") from exc
    if _is_within(resolved_run, source_repo):
        raise AdapterError("run directory must be outside the source repository")
    workspace = resolved_run / "workspace"
    if workspace.exists() or workspace.is_symlink():
        raise AdapterError(f"workspace path already exists: {workspace}")

    try:
        resolved_run.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AdapterError(f"cannot create run directory {resolved_run}: {exc}") from exc
    if not resolved_run.is_dir():
        raise AdapterError(f"run directory is not a directory: {resolved_run}")

    # Recheck immediately before mutation so a concurrently dirtied source is rejected.
    final_status = _run_git(
        git,
        source_repo,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        "repository cleanliness",
    )
    if final_status.returncode != 0 or final_status.stdout:
        raise AdapterError(
            "repository changed while preparing isolation; it must be clean including untracked files"
        )
    if _git_value(
        git, source_repo, ["rev-parse", "--verify", "HEAD"], "HEAD commit"
    ) != base_commit:
        raise AdapterError("repository HEAD changed while preparing isolation")
    result = _run_git(
        git,
        source_repo,
        ["worktree", "add", "--detach", str(workspace), base_commit],
        "detached workspace creation",
    )
    if result.returncode != 0:
        raise AdapterError(f"git could not create detached workspace at {workspace}")

    resolved_workspace = _resolve_directory(workspace, "created workspace")
    workspace_root = Path(
        _git_value(git, resolved_workspace, ["rev-parse", "--show-toplevel"], "workspace root")
    ).resolve()
    if workspace_root != resolved_workspace:
        raise AdapterError(f"created workspace is not its Git root: {resolved_workspace}")
    if _git_value(git, resolved_workspace, ["rev-parse", "--verify", "HEAD"], "workspace HEAD") != base_commit:
        raise AdapterError("created workspace does not match the pinned source HEAD")
    branch = _run_git(git, resolved_workspace, ["symbolic-ref", "-q", "HEAD"], "workspace HEAD mode")
    if branch.returncode == 0:
        raise AdapterError("created workspace is attached to a branch instead of detached")
    if branch.returncode != 1:
        raise AdapterError("git could not verify detached workspace HEAD")
    return {
        "source_repo": str(source_repo),
        "workspace": str(resolved_workspace),
        "base_commit": base_commit,
        "isolation": "git-worktree",
    }
