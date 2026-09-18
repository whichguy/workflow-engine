"""Small, durable, file-backed workflow kernel.

The public surface lives in the sibling :mod:`workflow` CLI.  This module owns
the state transition rules; callers never select a successor themselves.  It is
serial by default, with an explicit bounded native-agent frontier, and uses only
the Python standard library.
"""

from __future__ import annotations

import contextlib
import datetime as _datetime
import fcntl
import hashlib
import json
import math
import os
import signal
import shutil
import stat
import subprocess
import unicodedata
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import store


class WorkflowError(RuntimeError):
    """A workflow input, state, or transition is invalid."""


RUN_SCHEMA = "workflow-run"
LEGACY_RUN_VERSION = 1
RUN_VERSION = 2
WORKFLOW_VERSION = 1
_WORKFLOW_KEYS = {"version", "name", "goal", "steps"}
_STEP_KEYS = {
    "id",
    "kind",
    "needs",
    "argv",
    "prompt",
    "outputs",
    "verify",
    "timeout_seconds",
    "produces",
}
_STEP_KINDS = {"command", "prompt", "agent"}
_ACTION_STATUSES = {
    "ready",
    "executing",
    "verifying",
    "in_doubt",
    "failed",
    "blocked",
    "dispatching",
    "dispatched",
}


def _now() -> str:
    return _datetime.datetime.now(tz=_datetime.timezone.utc).isoformat()


def _json_default_error(value: Any) -> None:
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Encode JSON deterministically, rejecting NaN and non-JSON values."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
            default=_json_default_error,
        )
    except (TypeError, ValueError) as exc:
        raise WorkflowError(f"value is not canonical JSON: {exc}") from exc


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_text(canonical_json(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise WorkflowError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _reject_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkflowError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise WorkflowError(f"nonstandard JSON constant: {value}")


def parse_json_text(text: str, *, label: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except WorkflowError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"invalid JSON in {label}: {exc}") from exc


def _absolute(path: Path, *, label: str, require_exists: bool = False) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=require_exists)
    except (OSError, RuntimeError) as exc:
        raise WorkflowError(f"cannot resolve {label} {path}: {exc}") from exc
    if require_exists and not resolved.exists():
        raise WorkflowError(f"{label} does not exist: {path}")
    return resolved


def _read_text(path: Path, *, label: str) -> str:
    try:
        if path.is_symlink() or not path.is_file():
            raise WorkflowError(f"{label} must be a regular file: {path}")
        # ``Path.read_text`` opens with universal-newline translation.  Request
        # files are evidence and planning goals, so preserve CRLF/LF and every
        # valid Unicode code point exactly as supplied before hashing/freezing.
        return path.read_bytes().decode("utf-8")
    except WorkflowError:
        raise
    except (OSError, UnicodeError) as exc:
        raise WorkflowError(f"cannot read {label} {path}: {exc}") from exc


def load_document(path: Path, *, label: str) -> Tuple[Any, str]:
    """Load raw JSON or a Markdown record with one workflow-state fence."""
    resolved = _absolute(path, label=label, require_exists=True)
    text = _read_text(resolved, label=label)
    stripped = text.lstrip("\ufeff\ufeff\n\r\t ")
    if stripped.startswith("{") or stripped.startswith("["):
        return parse_json_text(stripped, label=label), text
    try:
        return store.loads(text), text
    except store.StorageError as exc:
        raise WorkflowError(f"invalid Markdown {label}: {exc}") from exc


def _require_string(value: Any, *, label: str, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise WorkflowError(f"{label} must be a string")
    if nonempty and not value.strip():
        raise WorkflowError(f"{label} must be nonempty")
    return value


def _safe_relative_path(value: Any, *, label: str) -> str:
    path = _require_string(value, label=label)
    if "\x00" in path or "\\" in path:
        raise WorkflowError(f"{label} is not a safe relative path: {path!r}")
    if path.startswith("/"):
        raise WorkflowError(f"{label} must be relative: {path!r}")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise WorkflowError(f"{label} is not a safe relative path: {path!r}")
    # This also prevents platform-specific drive semantics from escaping when a
    # manifest is moved from POSIX to Windows.
    if PurePosixPath(path).is_absolute() or ":" in parts[0]:
        raise WorkflowError(f"{label} is not a safe relative path: {path!r}")
    return path


def _as_argv(value: Any, *, label: str) -> List[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, list) or not value:
        raise WorkflowError(f"{label} must be a nonempty argv array")
    argv: List[str] = []
    for index, item in enumerate(value):
        argv.append(_require_string(item, label=f"{label}[{index}]") )
    return argv


def _normalise_step(raw: Any, *, index: int, prior_id: Optional[str]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise WorkflowError(f"steps[{index}] must be an object")
    unknown = set(raw).difference(_STEP_KEYS)
    if unknown:
        raise WorkflowError(
            f"steps[{index}] contains unknown fields: {', '.join(sorted(unknown))}"
        )
    if "id" not in raw or "kind" not in raw:
        raise WorkflowError(f"steps[{index}] requires id and kind")
    step_id = _require_string(raw["id"], label=f"steps[{index}].id")
    kind = _require_string(raw["kind"], label=f"steps[{index}].kind")
    if kind not in _STEP_KINDS:
        raise WorkflowError(f"steps[{index}].kind is unsupported: {kind!r}")

    if "needs" in raw:
        needs_raw = raw["needs"]
        if isinstance(needs_raw, (str, bytes)) or not isinstance(needs_raw, list):
            raise WorkflowError(f"steps[{index}].needs must be an array")
        needs = [
            _require_string(item, label=f"steps[{index}].needs[{need_index}]")
            for need_index, item in enumerate(needs_raw)
        ]
        if len(set(needs)) != len(needs):
            raise WorkflowError(f"steps[{index}].needs contains duplicate IDs")
    else:
        needs = [] if prior_id is None else [prior_id]

    outputs_raw = raw.get("outputs", [])
    if isinstance(outputs_raw, (str, bytes)) or not isinstance(outputs_raw, list):
        raise WorkflowError(f"steps[{index}].outputs must be an array")
    outputs = [
        _safe_relative_path(item, label=f"steps[{index}].outputs[{output_index}]")
        for output_index, item in enumerate(outputs_raw)
    ]
    if len(set(outputs)) != len(outputs):
        raise WorkflowError(f"steps[{index}].outputs contains duplicate paths")

    verify_raw = raw.get("verify", [])
    if isinstance(verify_raw, (str, bytes)) or not isinstance(verify_raw, list):
        raise WorkflowError(f"steps[{index}].verify must be an array of argv arrays")
    verify = [
        _as_argv(item, label=f"steps[{index}].verify[{verify_index}]")
        for verify_index, item in enumerate(verify_raw)
    ]

    timeout = raw.get("timeout_seconds", 60)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise WorkflowError(f"steps[{index}].timeout_seconds must be a positive number")
    if not math.isfinite(float(timeout)) or timeout <= 0:
        raise WorkflowError(f"steps[{index}].timeout_seconds must be a positive finite number")

    produces_raw = raw.get("produces", [])
    if isinstance(produces_raw, (str, bytes)) or not isinstance(produces_raw, list):
        raise WorkflowError(f"steps[{index}].produces must be an array")
    produces = [
        _require_string(item, label=f"steps[{index}].produces[{produce_index}]")
        for produce_index, item in enumerate(produces_raw)
    ]

    step: Dict[str, Any] = {
        "id": step_id,
        "kind": kind,
        "needs": needs,
        "outputs": outputs,
        "verify": verify,
        "timeout_seconds": timeout,
        "produces": produces,
    }
    if kind == "command":
        if "argv" not in raw:
            raise WorkflowError(f"steps[{index}] command requires argv")
        if "prompt" in raw:
            raise WorkflowError(f"steps[{index}] command may not contain prompt")
        step["argv"] = _as_argv(raw["argv"], label=f"steps[{index}].argv")
    else:
        if "prompt" not in raw:
            raise WorkflowError(f"steps[{index}] {kind} requires prompt")
        if "argv" in raw:
            raise WorkflowError(f"steps[{index}] {kind} may not contain argv")
        step["prompt"] = _require_string(raw["prompt"], label=f"steps[{index}].prompt")
        # A host-only step with neither output nor an executable check has no
        # machine-verifiable completion boundary.
        if not outputs and not verify:
            raise WorkflowError(
                f"steps[{index}] {kind} requires outputs or verify for evidence"
            )
    return step


def _reject_overlapping_outputs(steps: Sequence[Mapping[str, Any]]) -> None:
    seen: List[Tuple[Tuple[str, ...], str, str]] = []
    for step in steps:
        step_id = str(step["id"])
        for output in step["outputs"]:
            # A manifest can move between file systems with different Unicode
            # normalization and case-folding rules.  Treat any portable alias
            # as an overlap before a host has a chance to create two evidence
            # files that name the same physical object.
            parts = tuple(
                unicodedata.normalize("NFC", component).casefold()
                for component in str(output).split("/")
            )
            for old_parts, old_path, old_step in seen:
                shortest = min(len(parts), len(old_parts))
                if parts[:shortest] == old_parts[:shortest]:
                    raise WorkflowError(
                        "declared outputs overlap: "
                        f"{step_id}:{output} conflicts with {old_step}:{old_path}"
                    )
            seen.append((parts, str(output), step_id))


def _topological_order(steps: Sequence[Mapping[str, Any]]) -> List[str]:
    index = {str(step["id"]): position for position, step in enumerate(steps)}
    remaining = {step_id: set(steps[position]["needs"]) for step_id, position in index.items()}
    result: List[str] = []
    while remaining:
        ready = [step_id for step_id in remaining if not remaining[step_id]]
        if not ready:
            raise WorkflowError("workflow dependency graph contains a cycle")
        ready.sort(key=index.__getitem__)
        step_id = ready[0]
        result.append(step_id)
        del remaining[step_id]
        for dependencies in remaining.values():
            dependencies.discard(step_id)
    return result


def normalise_workflow(raw: Any) -> Dict[str, Any]:
    """Validate and canonicalise frozen workflow document v1."""
    if not isinstance(raw, dict):
        raise WorkflowError("workflow must be a JSON object")
    unknown = set(raw).difference(_WORKFLOW_KEYS)
    missing = _WORKFLOW_KEYS.difference(raw)
    if unknown:
        raise WorkflowError(f"workflow contains unknown fields: {', '.join(sorted(unknown))}")
    if missing:
        raise WorkflowError(f"workflow is missing fields: {', '.join(sorted(missing))}")
    if raw["version"] != WORKFLOW_VERSION:
        raise WorkflowError(f"workflow version must be {WORKFLOW_VERSION}")
    name = _require_string(raw["name"], label="workflow.name")
    goal = _require_string(raw["goal"], label="workflow.goal")
    steps_raw = raw["steps"]
    if isinstance(steps_raw, (str, bytes)) or not isinstance(steps_raw, list) or not steps_raw:
        raise WorkflowError("workflow.steps must be a nonempty array")

    raw_ids: List[str] = []
    for index, step in enumerate(steps_raw):
        if not isinstance(step, dict) or "id" not in step:
            raise WorkflowError(f"steps[{index}] requires id")
        raw_ids.append(_require_string(step["id"], label=f"steps[{index}].id"))
    if len(set(raw_ids)) != len(raw_ids):
        raise WorkflowError("workflow has duplicate step IDs")

    steps = [
        _normalise_step(step, index=index, prior_id=None if index == 0 else raw_ids[index - 1])
        for index, step in enumerate(steps_raw)
    ]
    ids = {step["id"] for step in steps}
    for step in steps:
        missing_needs = set(step["needs"]).difference(ids)
        if missing_needs:
            raise WorkflowError(
                f"step {step['id']!r} needs missing IDs: {', '.join(sorted(missing_needs))}"
            )
        if step["id"] in step["needs"]:
            raise WorkflowError(f"step {step['id']!r} cannot need itself")
    _topological_order(steps)
    _reject_overlapping_outputs(steps)
    return {"version": WORKFLOW_VERSION, "name": name, "goal": goal, "steps": steps}


def _step_by_id(workflow: Mapping[str, Any], step_id: str) -> Mapping[str, Any]:
    for step in workflow["steps"]:
        if step["id"] == step_id:
            return step
    raise WorkflowError(f"state refers to unknown step: {step_id!r}")


def _execution_policy(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the persisted scheduling policy, defaulting old runs to v1."""
    version = state.get("version")
    raw = state.get("execution_policy")
    if version == LEGACY_RUN_VERSION:
        if raw is not None:
            raise WorkflowError("v1 state cannot contain an execution policy")
        return {
            "mode": "serial",
            "max_active": 1,
            "shared_workspace_disjoint": False,
        }
    if version != RUN_VERSION:
        raise WorkflowError("state.md has an unsupported schema")
    if raw is None:
        raise WorkflowError("v2 state requires an execution policy")
    if not isinstance(raw, dict) or set(raw) != {
        "mode", "max_active", "shared_workspace_disjoint"
    }:
        raise WorkflowError("state.execution_policy is invalid")
    mode = raw.get("mode")
    max_active = raw.get("max_active")
    disjoint = raw.get("shared_workspace_disjoint")
    if isinstance(max_active, bool) or not isinstance(max_active, int) or max_active < 1:
        raise WorkflowError("state.execution_policy.max_active is invalid")
    if not isinstance(disjoint, bool):
        raise WorkflowError("state.execution_policy.shared_workspace_disjoint is invalid")
    if mode == "shared-workspace-disjoint" and max_active > 1 and disjoint:
        return dict(raw)
    raise WorkflowError("state.execution_policy has an unsupported mode")


def _frontier_enabled(state: Mapping[str, Any]) -> bool:
    return _execution_policy(state)["mode"] == "shared-workspace-disjoint"


def _active_actions(state: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Return live actions without making callers care about the v1 cursor."""
    if _frontier_enabled(state):
        actions = state.get("active_actions", [])
        if not isinstance(actions, list):
            raise WorkflowError("state.active_actions must be an array")
        return actions
    action = state.get("current_action")
    return [action] if isinstance(action, dict) else []


def _find_active_action(state: Mapping[str, Any], action_id: str) -> Optional[Dict[str, Any]]:
    for action in _active_actions(state):
        if action.get("id") == action_id:
            return action
    return None


def _remove_active_action(state: Dict[str, Any], action_id: str) -> None:
    if _frontier_enabled(state):
        actions = _active_actions(state)
        retained = [action for action in actions if action.get("id") != action_id]
        if len(retained) == len(actions):
            raise WorkflowError("action identity is stale or does not belong to this run")
        state["active_actions"] = retained
        return
    action = state.get("current_action")
    if not isinstance(action, dict) or action.get("id") != action_id:
        raise WorkflowError("action identity is stale or does not belong to this run")
    state["current_action"] = None


def _add_active_action(state: Dict[str, Any], action: Dict[str, Any]) -> None:
    if _frontier_enabled(state):
        state.setdefault("active_actions", []).append(action)
    else:
        if state.get("current_action") is not None:
            raise WorkflowError("cannot select next action while one is active")
        state["current_action"] = action


def _make_execution_policy(
    *, max_active: int, shared_workspace_disjoint: bool
) -> Dict[str, Any]:
    if isinstance(max_active, bool) or not isinstance(max_active, int):
        raise WorkflowError("max_active must be an integer")
    if max_active == 1 and not shared_workspace_disjoint:
        return {
            "mode": "serial",
            "max_active": 1,
            "shared_workspace_disjoint": False,
        }
    if max_active <= 1 or not shared_workspace_disjoint:
        raise WorkflowError(
            "frontier execution requires --max-active greater than 1 and "
            "--shared-workspace-disjoint"
        )
    return {
        "mode": "shared-workspace-disjoint",
        "max_active": max_active,
        "shared_workspace_disjoint": True,
    }


def _validate_frontier_workflow(workflow: Mapping[str, Any]) -> None:
    """Require an explicit exclusive evidence lease for every agent step."""
    for step in workflow["steps"]:
        if step["kind"] == "agent" and not step["outputs"]:
            raise WorkflowError(
                "frontier agent steps require at least one declared output for an exclusive lease"
            )


def _state_without_hash(state: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in state.items() if key != "state_sha256"}


def seal_state(state: Dict[str, Any]) -> None:
    definition = state.get("definition")
    if definition is None:
        state["definition_sha256"] = None
    else:
        state["definition_sha256"] = sha256_value(definition)
    state["state_sha256"] = sha256_value(_state_without_hash(state))


def _validate_state(state: Any, run_dir: Path) -> Dict[str, Any]:
    if not isinstance(state, dict):
        raise WorkflowError("state.md must contain an object")
    if state.get("schema") != RUN_SCHEMA or state.get("version") not in {
        LEGACY_RUN_VERSION,
        RUN_VERSION,
    }:
        raise WorkflowError("state.md has an unsupported schema")
    claimed = state.get("state_sha256")
    if not isinstance(claimed, str) or claimed != sha256_value(_state_without_hash(state)):
        raise WorkflowError("state.md hash does not match its contents")
    if state.get("run_dir") != str(run_dir):
        raise WorkflowError("state.md belongs to a different run directory")
    _require_string(state.get("run_id"), label="state.run_id")
    _require_string(state.get("original_goal"), label="state.original_goal")
    if not isinstance(state.get("workspace"), str) or not Path(state["workspace"]).is_absolute():
        raise WorkflowError("state.workspace must be an absolute path")
    if state.get("status") not in {
        "planning",
        "ready",
        "executing",
        "verifying",
        "in_doubt",
        "failed",
        "blocked",
        "dispatching",
        "dispatched",
        "complete",
    }:
        raise WorkflowError("state.status is invalid")
    definition = state.get("definition")
    if definition is not None:
        normal = normalise_workflow(definition)
        if normal != definition:
            raise WorkflowError("state definition is not normalized")
        if state.get("definition_sha256") != sha256_value(normal):
            raise WorkflowError("frozen workflow digest does not match")
    elif state.get("definition_sha256") is not None:
        raise WorkflowError("state has a definition hash without a definition")
    if not isinstance(state.get("completed"), dict):
        raise WorkflowError("state.completed must be an object")
    if not isinstance(state.get("callbacks"), dict):
        raise WorkflowError("state.callbacks must be an object")
    policy = _execution_policy(state)
    action = state.get("current_action")
    if action is not None:
        if not isinstance(action, dict):
            raise WorkflowError("state.current_action must be an object or null")
        _require_string(action.get("id"), label="state.current_action.id")
        if action.get("status") not in _ACTION_STATUSES and action.get("kind") != "planning":
            raise WorkflowError("state.current_action.status is invalid")
        if action.get("kind") == "planning":
            if definition is not None:
                raise WorkflowError("planning action cannot have a frozen workflow")
        else:
            if definition is None:
                raise WorkflowError("execution action has no frozen workflow")
            _require_string(action.get("step_id"), label="state.current_action.step_id")
            _step_by_id(definition, action["step_id"])
            if policy["mode"] != "serial":
                raise WorkflowError("frontier execution actions must use state.active_actions")

    raw_active = state.get("active_actions", [])
    if policy["mode"] == "serial":
        if "active_actions" in state or "claim_requests" in state:
            raise WorkflowError("v1 state cannot retain frontier action state")
    else:
        if "active_actions" not in state or "claim_requests" not in state:
            raise WorkflowError("v2 state requires frontier action state")
        if not isinstance(raw_active, list):
            raise WorkflowError("state.active_actions must be an array")
        if len(raw_active) > policy["max_active"]:
            raise WorkflowError("state.active_actions exceeds max_active")
        if action is not None and raw_active:
            raise WorkflowError("frontier state cannot mix planning and execution actions")
        action_ids: set[str] = set()
        step_ids: set[str] = set()
        leased_paths: set[str] = set()
        for index, active in enumerate(raw_active):
            if not isinstance(active, dict):
                raise WorkflowError(f"state.active_actions[{index}] must be an object")
            action_id = _require_string(active.get("id"), label=f"state.active_actions[{index}].id")
            if action_id in action_ids:
                raise WorkflowError("state.active_actions contains duplicate action IDs")
            action_ids.add(action_id)
            if active.get("kind") not in _STEP_KINDS:
                raise WorkflowError("state.active_actions has an unsupported action kind")
            if active.get("status") not in _ACTION_STATUSES:
                raise WorkflowError("state.active_actions.status is invalid")
            if definition is None:
                raise WorkflowError("frontier execution action has no frozen workflow")
            step_id = _require_string(
                active.get("step_id"), label=f"state.active_actions[{index}].step_id"
            )
            if step_id in step_ids:
                raise WorkflowError("state.active_actions contains duplicate step IDs")
            step_ids.add(step_id)
            step = _step_by_id(definition, step_id)
            if active.get("kind") != step["kind"]:
                raise WorkflowError("frontier action kind does not match its frozen step")
            if step_id in state["completed"]:
                raise WorkflowError("completed step cannot remain active")
            if not all(need in state["completed"] for need in step["needs"]):
                raise WorkflowError("frontier action has unaccepted dependencies")
            if active.get("kind") == "agent":
                expected_paths = list(step["outputs"])
                lease = active.get("workspace_lease")
                if not expected_paths or not isinstance(lease, dict) or lease != {
                    "mode": "declared-output-exclusive",
                    "paths": expected_paths,
                }:
                    raise WorkflowError("frontier agent must retain its declared-output lease")
                overlap = leased_paths.intersection(expected_paths)
                if overlap:
                    raise WorkflowError("frontier agent output leases overlap")
                leased_paths.update(expected_paths)
        if len(raw_active) > 1 and any(active.get("kind") != "agent" for active in raw_active):
            raise WorkflowError("only agent actions may be concurrently active")
        claims = state.get("claim_requests", {})
        if not isinstance(claims, dict):
            raise WorkflowError("state.claim_requests must be an object")
        for request_id, claim in claims.items():
            _require_string(request_id, label="state.claim_requests key")
            if not isinstance(claim, dict):
                raise WorkflowError("state.claim_requests entry is invalid")
            if claim.get("request_id") != request_id:
                raise WorkflowError("state.claim_requests request ID is invalid")
            limit = claim.get("limit")
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= policy["max_active"]:
                raise WorkflowError("state.claim_requests limit is invalid")
            ids = claim.get("action_ids")
            if not isinstance(ids, list) or not all(isinstance(item, str) and item for item in ids):
                raise WorkflowError("state.claim_requests action_ids is invalid")
    if state["status"] == "complete":
        if action is not None:
            raise WorkflowError("complete state cannot retain a current action")
        if definition is None:
            raise WorkflowError("complete state has no frozen workflow")
        if raw_active:
            raise WorkflowError("complete state cannot retain active actions")
        if len(state["completed"]) != len(definition["steps"]):
            raise WorkflowError("complete state has unaccepted workflow steps")
    return state


@contextlib.contextmanager
def run_lock(run_dir: Path) -> Iterator[None]:
    """Take the single-host advisory lock required for state mutations."""
    lock_path = run_dir / ".workflow.lock"
    if lock_path.is_symlink():
        raise WorkflowError("run lock path may not be a symlink")
    try:
        descriptor = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise WorkflowError(f"cannot open run lock: {exc}") from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    except OSError as exc:
        raise WorkflowError(f"cannot lock run directory: {exc}") from exc
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _open_execution_lock(run_dir: Path) -> int:
    """Open the separate live-execution lock without following a symlink."""
    lock_path = run_dir / ".workflow.executing.lock"
    if lock_path.is_symlink():
        raise WorkflowError("execution lock path may not be a symlink")
    try:
        return os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise WorkflowError(f"cannot open execution lock: {exc}") from exc


def _write_execution_lock_owner(descriptor: int, action_id: str) -> None:
    """Publish the action protected by a held effect lock.

    The advisory flock establishes mutual exclusion; this tiny fsynced record
    lets a cold reader distinguish that owner from another stranded action
    while sibling completions serialize behind the same lock.
    """
    payload = canonical_json(
        {"action_id": action_id, "pid": os.getpid(), "written_at": _now()}
    ).encode("utf-8")
    try:
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short write to execution lock")
            offset += written
        os.fsync(descriptor)
    except OSError as exc:
        raise WorkflowError(f"cannot record live effect owner: {exc}") from exc


def _clear_execution_lock_owner(descriptor: int) -> None:
    try:
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)
    except OSError:
        # The flock still releases in the caller's finally block.  A stale
        # record is never trusted unless the flock itself is live.
        pass


def _execution_lock_owner(run_dir: Path) -> Optional[str]:
    """Read the current lock owner's action ID, if its record is intact."""
    descriptor = _open_execution_lock(run_dir)
    try:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            raw = os.read(descriptor, 16 * 1024)
            payload = parse_json_text(raw.decode("utf-8"), label="execution lock owner")
        except (OSError, UnicodeError, WorkflowError):
            return None
        if not isinstance(payload, dict):
            return None
        action_id = payload.get("action_id")
        return action_id if isinstance(action_id, str) and action_id else None
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def execution_lock(
    run_dir: Path,
    *,
    owner_action_id: str,
    blocking: bool = False,
) -> Iterator[None]:
    """Hold a process-lifetime flock while one command or verifier has effects.

    This lock is intentionally distinct from the short state transaction lock.
    A cold ``next`` can therefore distinguish a live local executor from a
    dead CLI that left a persisted command or verifier intent.  Completion
    callbacks choose ``blocking=True`` so independent native siblings serialize
    verifier effects instead of racing across the shared workspace.
    """
    _require_string(owner_action_id, label="effect owner action ID")
    descriptor = _open_execution_lock(run_dir)
    try:
        try:
            operation = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
            fcntl.flock(descriptor, operation)
        except BlockingIOError as exc:
            raise WorkflowError("a workflow effect is already executing") from exc
        except OSError as exc:
            raise WorkflowError(f"cannot lock live workflow effect: {exc}") from exc
        try:
            _write_execution_lock_owner(descriptor, owner_action_id)
            yield
        finally:
            _clear_execution_lock_owner(descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _execution_is_live(run_dir: Path) -> bool:
    """Probe the process-held effect flock without relying on PID liveness."""
    descriptor = _open_execution_lock(run_dir)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    except OSError as exc:
        raise WorkflowError(f"cannot probe live command execution: {exc}") from exc
    finally:
        os.close(descriptor)


def _relative_to(root: Path, path: Path, *, label: str) -> Path:
    try:
        return path.relative_to(root)
    except ValueError as exc:
        raise WorkflowError(f"{label} escapes its required root: {path}") from exc


def _safe_run_path(run_dir: Path, relative: str) -> Path:
    _safe_relative_path(relative, label="internal run path")
    candidate = run_dir / relative
    resolved = _absolute(candidate, label="internal run path", require_exists=False)
    _relative_to(run_dir, resolved, label="internal run path")
    return resolved


def _workspace_root(state: Mapping[str, Any]) -> Path:
    workspace = _absolute(Path(state["workspace"]), label="workspace", require_exists=True)
    if not workspace.is_dir():
        raise WorkflowError(f"workspace is not a directory: {workspace}")
    return workspace


def _preflight_output_path(workspace: Path, output: str) -> Path:
    """Reject extant physical aliases before an output is owned or checked.

    The manifest has already rejected lexical aliases.  This complementary
    check catches paths whose existing parent is a symlink and pre-existing
    files that are symlinks, nonregular objects, or hard links.  Missing
    parents remain valid: a step may create its own ordinary directories.
    """
    _safe_relative_path(output, label="declared output")
    components = output.split("/")
    parent = workspace
    for component in components[:-1]:
        parent = parent / component
        try:
            parent_stat = parent.lstat()
        except FileNotFoundError:
            # No deeper component can exist once a parent is absent.
            break
        except OSError as exc:
            raise WorkflowError(f"cannot inspect declared output parent {parent}: {exc}") from exc
        if stat.S_ISLNK(parent_stat.st_mode):
            raise WorkflowError(f"declared output parent may not be a symlink: {output}")
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise WorkflowError(f"declared output parent is not a directory: {output}")

    target = workspace / output
    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        return target
    except OSError as exc:
        raise WorkflowError(f"cannot inspect declared output {output}: {exc}") from exc
    if stat.S_ISLNK(target_stat.st_mode):
        raise WorkflowError(f"declared output may not be a symlink: {output}")
    if not stat.S_ISREG(target_stat.st_mode):
        raise WorkflowError(f"declared output must be a regular file when it exists: {output}")
    if target_stat.st_nlink > 1:
        raise WorkflowError(f"declared output may not have hard-link aliases: {output}")
    return target


def _preflight_declared_outputs(
    workspace: Path, steps: Sequence[Mapping[str, Any]]
) -> None:
    """Check every output's present filesystem identity without rewriting it."""
    for step in steps:
        for output in step["outputs"]:
            _preflight_output_path(workspace, str(output))


def _fingerprint_path(path: Path, workspace: Path) -> Dict[str, Any]:
    """Capture an output preimage without following an unsafe path."""
    try:
        item_stat = path.lstat()
    except FileNotFoundError:
        return {"exists": False}
    except OSError as exc:
        raise WorkflowError(f"cannot inspect declared output {path}: {exc}") from exc
    if stat.S_ISLNK(item_stat.st_mode):
        return {"exists": True, "type": "symlink", "lstat": _stat_fingerprint(item_stat)}
    if not stat.S_ISREG(item_stat.st_mode):
        return {"exists": True, "type": "nonregular", "lstat": _stat_fingerprint(item_stat)}
    resolved = _absolute(path, label="declared output", require_exists=True)
    _relative_to(workspace, resolved, label="declared output")
    return {
        "exists": True,
        "type": "file",
        "sha256": sha256_file(path),
        "stat": _stat_fingerprint(item_stat),
    }


def _stat_fingerprint(item_stat: os.stat_result) -> Dict[str, int]:
    return {
        "device": int(item_stat.st_dev),
        "inode": int(item_stat.st_ino),
        "size": int(item_stat.st_size),
        "mtime_ns": int(item_stat.st_mtime_ns),
        "ctime_ns": int(item_stat.st_ctime_ns),
    }


def _capture_preimages(workspace: Path, outputs: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    preimages: Dict[str, Dict[str, Any]] = {}
    for output in outputs:
        target = workspace / output
        preimages[output] = _fingerprint_path(target, workspace)
    return preimages


def _execution_argv(argv: Sequence[str], workspace: Path) -> List[str]:
    """Freeze the executable selected for an action as an absolute argv[0].

    Arguments after argv[0] remain authored data: turning every string that
    happens to resemble a path into an absolute path would change command
    semantics (notably ``-c`` programs and tools with path-like flags).
    """
    if not argv:
        raise WorkflowError("execution argv must be nonempty")
    executable = argv[0]
    candidate = Path(executable)
    if candidate.is_absolute():
        resolved = _absolute(candidate, label="command executable", require_exists=False)
    elif "/" in executable:
        resolved = _absolute(workspace / candidate, label="command executable", require_exists=False)
    else:
        discovered = shutil.which(executable)
        resolved = (
            _absolute(Path(discovered), label="command executable", require_exists=True)
            if discovered
            else _absolute(workspace / candidate, label="command executable", require_exists=False)
        )
    return [str(resolved), *argv[1:]]


def _verified_outputs(
    workspace: Path,
    outputs: Sequence[str],
    preimages: Mapping[str, Any],
    *,
    require_changed: bool,
) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    for output in outputs:
        target = _preflight_output_path(workspace, output)
        try:
            item_stat = target.lstat()
        except FileNotFoundError as exc:
            raise WorkflowError(f"declared output is missing: {output}") from exc
        except OSError as exc:
            raise WorkflowError(f"cannot inspect declared output {output}: {exc}") from exc
        if stat.S_ISLNK(item_stat.st_mode) or not stat.S_ISREG(item_stat.st_mode):
            raise WorkflowError(f"declared output must be a regular non-symlink file: {output}")
        if item_stat.st_nlink > 1:
            raise WorkflowError(f"declared output may not have hard-link aliases: {output}")
        resolved = _absolute(target, label="declared output", require_exists=True)
        _relative_to(workspace, resolved, label="declared output")
        current = {
            "exists": True,
            "type": "file",
            "sha256": sha256_file(target),
            "stat": _stat_fingerprint(item_stat),
        }
        before = preimages.get(output)
        if require_changed and before == current:
            raise WorkflowError(
                f"declared output was not newly created or changed for this attempt: {output}"
            )
        evidence.append(
            {
                "path": output,
                "sha256": current["sha256"],
                "size": current["stat"]["size"],
                "stat": current["stat"],
            }
        )
    return evidence


def _assert_accepted_evidence(state: Mapping[str, Any], run_dir: Path) -> None:
    """Accepted direct output hashes are immutable across every hydration."""
    workspace = _workspace_root(state)
    completed = state.get("completed", {})
    for step_id, completion in completed.items():
        if not isinstance(completion, dict):
            raise WorkflowError(f"completion record is invalid for {step_id}")
        for output in completion.get("outputs", []):
            if not isinstance(output, dict) or not isinstance(output.get("path"), str):
                raise WorkflowError(f"completion output record is invalid for {step_id}")
            path = output["path"]
            current = _verified_outputs(workspace, [path], {}, require_changed=False)[0]
            if current["sha256"] != output.get("sha256"):
                raise WorkflowError(
                    f"accepted evidence changed after completion: {step_id}:{path}"
                )
        receipt_path = completion.get("receipt_path")
        receipt_sha256 = completion.get("receipt_sha256")
        if not isinstance(receipt_path, str) or not isinstance(receipt_sha256, str):
            raise WorkflowError(f"completion receipt record is invalid for {step_id}")
        receipt = _safe_run_path(run_dir, receipt_path)
        if not receipt.exists() or receipt.is_symlink() or not receipt.is_file():
            raise WorkflowError(f"accepted receipt is missing: {receipt_path}")
        if sha256_file(receipt) != receipt_sha256:
            raise WorkflowError(f"accepted receipt changed after completion: {receipt_path}")
        try:
            receipt_payload = store.read_record(receipt)
        except store.StorageError as exc:
            raise WorkflowError(f"accepted receipt is unreadable: {receipt_path}: {exc}") from exc
        _assert_receipt_logs(run_dir, receipt_payload, receipt_path)


def _assert_receipt_logs(run_dir: Path, receipt: Any, receipt_path: str) -> None:
    """Verify immutable command/check log hashes claimed by an accepted receipt."""
    if not isinstance(receipt, dict):
        raise WorkflowError(f"accepted receipt is not an object: {receipt_path}")
    log_sets: List[Any] = []
    command = receipt.get("command")
    if isinstance(command, dict) and isinstance(command.get("logs"), dict):
        log_sets.append(command["logs"])
    checks = receipt.get("checks", [])
    if not isinstance(checks, list):
        raise WorkflowError(f"accepted receipt checks are invalid: {receipt_path}")
    log_sets.extend(checks)
    for logs in log_sets:
        if not isinstance(logs, dict):
            raise WorkflowError(f"accepted log record is invalid: {receipt_path}")
        for path_key, hash_key in (("stdout_path", "stdout_sha256"), ("stderr_path", "stderr_sha256")):
            # A receipt that does not claim a log pair does not get an invented
            # integrity promise; when it does claim one, both are mandatory.
            has_path = path_key in logs
            has_hash = hash_key in logs
            if not has_path and not has_hash:
                continue
            if not has_path or not has_hash:
                raise WorkflowError(f"accepted log record is incomplete: {receipt_path}")
            relative = logs[path_key]
            claimed = logs[hash_key]
            if not isinstance(relative, str) or not isinstance(claimed, str):
                raise WorkflowError(f"accepted log record is invalid: {receipt_path}")
            log_path = _safe_run_path(run_dir, relative)
            if not log_path.exists() or log_path.is_symlink() or not log_path.is_file():
                raise WorkflowError(f"accepted log is missing: {relative}")
            if sha256_file(log_path) != claimed:
                raise WorkflowError(f"accepted log changed after completion: {relative}")


def _git_identity(repo: Path) -> Dict[str, Any]:
    """Freeze lightweight repository identity without requiring Git for all runs."""
    identity: Dict[str, Any] = {"path": str(repo), "git_head": None}
    try:
        outcome = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return identity
    if outcome.returncode == 0:
        candidate = outcome.stdout.strip()
        if candidate:
            identity["git_head"] = candidate
    return identity


class WorkflowKernel:
    """Owns workflow transitions and derives packets from Markdown state."""

    def __init__(self, cli_path: Path):
        self.cli_path = _absolute(cli_path, label="workflow CLI", require_exists=True)

    # ----- initialization -------------------------------------------------

    def init_workflow(
        self,
        *,
        workflow_file: Path,
        run_dir: Path,
        repo: Path,
        isolate: bool = False,
        max_active: int = 1,
        shared_workspace_disjoint: bool = False,
    ) -> Dict[str, Any]:
        raw, source = load_document(workflow_file, label="workflow file")
        workflow = normalise_workflow(raw)
        policy = _make_execution_policy(
            max_active=max_active,
            shared_workspace_disjoint=shared_workspace_disjoint,
        )
        if policy["mode"] == "shared-workspace-disjoint":
            _validate_frontier_workflow(workflow)
        return self._init(
            run_dir=run_dir,
            repo=repo,
            isolate=isolate,
            original_goal=workflow["goal"],
            request={
                "mode": "workflow",
                "source_path": str(_absolute(workflow_file, label="workflow file", require_exists=True)),
                "source_sha256": sha256_text(source),
            },
            definition=workflow,
            planner=None,
            execution_policy=policy,
        )

    def init_prompt(
        self,
        *,
        prompt_file: Path,
        backchain_root: Path,
        run_dir: Path,
        repo: Path,
        isolate: bool = False,
        max_active: int = 1,
        shared_workspace_disjoint: bool = False,
    ) -> Dict[str, Any]:
        prompt_path = _absolute(prompt_file, label="prompt file", require_exists=True)
        prompt = _read_text(prompt_path, label="prompt file")
        if not prompt.strip():
            raise WorkflowError("prompt file must not be empty")
        root = _absolute(backchain_root, label="Backchain root", require_exists=True)
        if not root.is_dir():
            raise WorkflowError("Backchain root must be a directory")
        policy = _make_execution_policy(
            max_active=max_active,
            shared_workspace_disjoint=shared_workspace_disjoint,
        )
        return self._init(
            run_dir=run_dir,
            repo=repo,
            isolate=isolate,
            original_goal=prompt,
            request={
                "mode": "prompt",
                "prompt_path": str(prompt_path),
                "prompt_sha256": sha256_text(prompt),
                "prompt": prompt,
                "backchain_root": str(root),
            },
            definition=None,
            planner={"backchain_root": str(root)},
            execution_policy=policy,
        )

    def _init(
        self,
        *,
        run_dir: Path,
        repo: Path,
        isolate: bool,
        original_goal: str,
        request: Dict[str, Any],
        definition: Optional[Dict[str, Any]],
        planner: Optional[Dict[str, Any]],
        execution_policy: Dict[str, Any],
    ) -> Dict[str, Any]:
        target_run = _absolute(run_dir, label="run directory", require_exists=False)
        if target_run.exists() or target_run.is_symlink():
            raise WorkflowError(f"init never overwrites an existing run directory: {target_run}")
        source_repo = _absolute(repo, label="repository", require_exists=True)
        if not source_repo.is_dir():
            raise WorkflowError("repository must be a directory")
        # A non-isolated workflow can reject existing physical aliases before
        # allocating any run state.  Isolated setup must create the worktree
        # first, so its equivalent preflight occurs below against that workspace.
        if definition is not None and not isolate:
            _preflight_declared_outputs(source_repo, definition["steps"])
        try:
            target_run.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise WorkflowError(f"cannot create run directory {target_run}: {exc}") from exc

        workspace = source_repo
        isolation: Dict[str, Any] = {"mode": "none"}
        if isolate:
            adapter = self._adapters()
            try:
                workspace_info = adapter.create_workspace(source_repo, target_run)
            except Exception as exc:  # AdapterError remains deliberately adapter-owned.
                raise WorkflowError(f"cannot create isolated workspace: {exc}") from exc
            if not isinstance(workspace_info, dict) or not isinstance(workspace_info.get("workspace"), str):
                raise WorkflowError("workspace adapter returned no workspace path")
            workspace = _absolute(Path(workspace_info["workspace"]), label="isolated workspace", require_exists=True)
            if not workspace.is_dir():
                raise WorkflowError("workspace adapter returned a non-directory workspace")
            isolation = dict(workspace_info)

        if definition is not None:
            _preflight_declared_outputs(workspace, definition["steps"])

        state: Dict[str, Any] = {
            "schema": RUN_SCHEMA,
            "version": RUN_VERSION
            if execution_policy["mode"] == "shared-workspace-disjoint"
            else LEGACY_RUN_VERSION,
            "run_id": uuid.uuid4().hex,
            "created_at": _now(),
            "run_dir": str(target_run),
            "original_goal": original_goal,
            "request": request,
            "definition": definition,
            "definition_sha256": None,
            "repo": _git_identity(source_repo),
            "workspace": str(workspace),
            "isolation": isolation,
            "planner": planner,
            "status": "planning" if definition is None else "ready",
            "current_action": None,
            "completed": {},
            "callbacks": {},
            "attempts": [],
            "dispatch_history": [],
            "retry_history": [],
            "reconciliation": [],
        }
        if execution_policy["mode"] == "shared-workspace-disjoint":
            state.update(
                {
                    "execution_policy": execution_policy,
                    "active_actions": [],
                    "claim_requests": {},
                }
            )
        with run_lock(target_run):
            if definition is None:
                self._issue_planning_action(state)
            else:
                if _frontier_enabled(state):
                    self._refresh_frontier_state(state)
                else:
                    self._issue_next_action(state)
            return self._persist_locked(target_run, state)

    # ----- loading, storage, recovery -----------------------------------

    def _adapters(self) -> Any:
        try:
            import adapters  # Imported only for the adapter-owning operations.
        except ImportError as exc:
            raise WorkflowError(f"workflow adapters are unavailable: {exc}") from exc
        return adapters

    def _load_locked(
        self,
        run_dir: Path,
        *,
        reconcile: bool,
        live_execution: bool = False,
        live_action_id: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        try:
            store.recover(run_dir)
            state = store.read_record(run_dir / "state.md")
        except store.StorageError as exc:
            raise WorkflowError(f"cannot recover workflow state: {exc}") from exc
        state = _validate_state(state, run_dir)
        _assert_accepted_evidence(state, run_dir)
        changed = False
        effectful = [
            action
            for action in _active_actions(state)
            if action.get("status") in {"executing", "verifying"}
        ]
        protected_action_id: Optional[str] = None
        if live_execution:
            protected_action_id = live_action_id
        elif effectful and _execution_is_live(run_dir):
            # A live B callback must not accidentally bless a crashed A
            # verifier.  The holder writes its action ID while holding the
            # same flock, so only that precise action remains live.
            protected_action_id = _execution_lock_owner(run_dir)
        stranded = [
            action for action in effectful if action.get("id") != protected_action_id
        ]
        if reconcile and stranded:
            # An effect intent without its own process-held owner is an unknown
            # outcome.  We never infer that no child survived or replay it.
            for action in stranded:
                prior_status = action.get("status")
                action["status"] = "in_doubt"
                action["reconciled_at"] = _now()
                state["reconciliation"].append(
                    {
                        "at": _now(),
                        "action_id": action["id"],
                        "kind": "command" if prior_status == "executing" else "verification",
                        "outcome": "in_doubt",
                        "reason": (
                            "persisted command intent requires explicit reconciliation"
                            if prior_status == "executing"
                            else "persisted verifier intent requires explicit reconciliation"
                        ),
                    }
                )
            if _frontier_enabled(state):
                self._refresh_frontier_state(state)
            else:
                state["status"] = "in_doubt"
            changed = True
        return state, changed

    def _persist_locked(
        self,
        run_dir: Path,
        state: Dict[str, Any],
        *,
        extra_writes: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, Any]:
        seal_state(state)
        packet = self._packet(state, run_dir)
        writes: Dict[str, str] = {
            "state.md": store.dumps(state, title="Workflow run"),
            "packet.md": store.dumps(packet, title="Workflow packet"),
        }
        if extra_writes:
            for path, text in extra_writes.items():
                if path in writes:
                    raise WorkflowError(f"attempted to overwrite core record {path}")
                writes[path] = text
        try:
            store.transaction(run_dir, writes)
        except store.StorageError as exc:
            raise WorkflowError(f"cannot persist workflow state: {exc}") from exc
        return packet

    def next(self, *, run_dir: Path) -> Dict[str, Any]:
        target_run = _absolute(run_dir, label="run directory", require_exists=True)
        if not target_run.is_dir():
            raise WorkflowError("run directory must be a directory")
        with run_lock(target_run):
            state, changed = self._load_locked(target_run, reconcile=True)
            if changed:
                return self._persist_locked(target_run, state)
            return self._packet(state, target_run)

    # ----- packet rendering ----------------------------------------------

    def _cli(self, command: str, *arguments: str) -> List[str]:
        return [str(self.cli_path), command, *arguments]

    def _result_path(self, run_dir: Path, action_id: str) -> str:
        return str(run_dir / "results" / f"{action_id}.json")

    def _plan_paths(self, run_dir: Path, action_id: str) -> Tuple[str, str]:
        return (
            str(run_dir / "plans" / f"{action_id}.plan.json"),
            str(run_dir / "plans" / f"{action_id}.bindings.json"),
        )

    def _dependencies(self, state: Mapping[str, Any], run_dir: Path, step: Mapping[str, Any]) -> List[Dict[str, str]]:
        dependencies: List[Dict[str, str]] = []
        for dependency_id in step["needs"]:
            completion = state["completed"].get(dependency_id)
            if not isinstance(completion, dict):
                raise WorkflowError(f"ready step lacks completion receipt for dependency {dependency_id}")
            receipt_path = completion.get("receipt_path")
            receipt_hash = completion.get("receipt_sha256")
            if not isinstance(receipt_path, str) or not isinstance(receipt_hash, str):
                raise WorkflowError(f"dependency receipt is invalid for {dependency_id}")
            dependencies.append(
                {
                    "step_id": dependency_id,
                    "receipt_path": str(_safe_run_path(run_dir, receipt_path)),
                    "path": str(_safe_run_path(run_dir, receipt_path)),
                    "sha256": receipt_hash,
                }
            )
        return dependencies

    def _packet(self, state: Mapping[str, Any], run_dir: Path) -> Dict[str, Any]:
        if _frontier_enabled(state) and state.get("definition") is not None and state.get("current_action") is None:
            return self._frontier_packet(state, run_dir)
        return self._serial_packet(state, run_dir)

    def _serial_packet(self, state: Mapping[str, Any], run_dir: Path) -> Dict[str, Any]:
        action = state.get("current_action")
        recovery_argv = self._cli("next", "--run-dir", str(run_dir))
        packet: Dict[str, Any] = {
            "protocol": "workflow-packet-v1",
            "run_id": state["run_id"],
            "run_dir": str(run_dir),
            "goal": state["original_goal"],
            "original_goal": state["original_goal"],
            "status": state["status"],
            "action_id": None,
            "kind": None,
            "step_id": None,
            "workspace": state["workspace"],
            "prompt": None,
            "argv": None,
            "declared_outputs": [],
            "outputs": [],
            "direct_dependency_receipts": [],
            "dependencies": [],
            "next_argv": recovery_argv,
            "recovery_argv": recovery_argv,
            "allowed_operation_argv_templates": {
                "next": recovery_argv
            },
            "allowed_operations": {
                "next": recovery_argv
            },
        }
        if action is None:
            if state["status"] == "complete":
                packet["completion"] = "all declared steps have accepted verified receipts"
            elif state["status"] == "blocked":
                packet["blocked_reason"] = state.get("blocked_reason", "no ready step")
            return packet

        action_id = action["id"]
        packet.update(
            {
                "action_id": action_id,
                "kind": action["kind"],
                "step_id": action.get("step_id"),
                "attempt": action.get("attempt"),
            }
        )
        kind = action["kind"]
        if kind == "planning":
            plan_path, bindings_path = self._plan_paths(run_dir, action_id)
            packet["prompt"] = state["request"]["prompt"]
            backchain_root = state["request"].get("backchain_root")
            card = (
                str(Path(backchain_root) / "skills" / "backchain" / "SKILL.md")
                if isinstance(backchain_root, str)
                else "selected Backchain SKILL.md"
            )
            packet["planning_instruction"] = (
                f"Load the selected {card} fully and follow that skill's own technical lenses, "
                "convergence lifecycle, and terminal evidence requirements. Produce its plan "
                "schema and separate execution bindings, then invoke this exact accept-plan "
                "command. Package validation is structural only; it does not replace the "
                "selected skill's semantic convergence obligation."
            )
            accept = self._cli(
                "accept-plan",
                "--run-dir",
                str(run_dir),
                "--action",
                action_id,
                "--plan",
                plan_path,
                "--bindings",
                bindings_path,
            )
            packet["plan_file"] = plan_path
            packet["bindings_file"] = bindings_path
            packet["next_argv"] = accept
            packet["allowed_operation_argv_templates"] = {
                "accept_plan": accept,
            }
            packet["allowed_operations"] = packet["allowed_operation_argv_templates"]
            return packet

        definition = state.get("definition")
        if not isinstance(definition, dict):
            raise WorkflowError("execution packet has no frozen definition")
        step = _step_by_id(definition, action["step_id"])
        dependencies = self._dependencies(state, run_dir, step)
        packet["declared_outputs"] = list(step["outputs"])
        packet["outputs"] = list(step["outputs"])
        packet["direct_dependency_receipts"] = dependencies
        packet["dependencies"] = dependencies
        packet["timeout_seconds"] = step["timeout_seconds"]
        packet["produces"] = list(step["produces"])

        retry = self._cli(
            "retry",
            "--run-dir",
            str(run_dir),
            "--action",
            action_id,
            "--reason",
            "<reason>",
            "--confirmed-stopped",
        )
        if kind == "command":
            execution_argv = action.get("execution_argv")
            if not isinstance(execution_argv, list) or not all(
                isinstance(item, str) for item in execution_argv
            ):
                raise WorkflowError("command action has no frozen execution argv")
            packet["argv"] = list(execution_argv)
            execute = self._cli(
                "execute", "--run-dir", str(run_dir), "--action", action_id
            )
            if action["status"] == "ready":
                packet["next_argv"] = execute
                packet["allowed_operation_argv_templates"] = {
                    "execute": execute,
                    "retry": retry,
                }
            elif action["status"] in {"failed", "blocked", "in_doubt"}:
                packet["next_argv"] = self._cli("next", "--run-dir", str(run_dir))
                packet["allowed_operation_argv_templates"] = {"retry": retry}
            else:
                packet["next_argv"] = self._cli("next", "--run-dir", str(run_dir))
                packet["allowed_operation_argv_templates"] = {
                    "next": packet["next_argv"]
                }
            packet["allowed_operations"] = packet["allowed_operation_argv_templates"]
            return packet

        packet["prompt"] = step["prompt"]
        result_path = self._result_path(run_dir, action_id)
        complete = self._cli(
            "complete",
            "--run-dir",
            str(run_dir),
            "--action",
            action_id,
            "--result",
            result_path,
        )
        if kind == "prompt":
            packet["result_file"] = result_path
            if action["status"] == "ready":
                packet["next_argv"] = complete
                packet["allowed_operation_argv_templates"] = {
                    "complete": complete,
                    "retry": retry,
                }
            elif action["status"] == "verifying":
                packet["verification"] = {
                    "state": "live_or_reconcile",
                    "instruction": (
                        "A verifier owns this completion callback. Do not submit complete, "
                        "launch work, or retry while it is live. Use next only; if its owner "
                        "is gone, the script will park the action for explicit reconciliation."
                    ),
                }
                packet["next_argv"] = self._cli("next", "--run-dir", str(run_dir))
                packet["allowed_operation_argv_templates"] = {
                    "next": packet["next_argv"]
                }
            elif action["status"] in {"failed", "blocked", "in_doubt"}:
                packet["next_argv"] = self._cli("next", "--run-dir", str(run_dir))
                packet["allowed_operation_argv_templates"] = {"retry": retry}
            else:
                packet["next_argv"] = self._cli("next", "--run-dir", str(run_dir))
                packet["allowed_operation_argv_templates"] = {
                    "next": packet["next_argv"]
                }
            packet["allowed_operations"] = packet["allowed_operation_argv_templates"]
            return packet

        # Agent dispatch is explicitly host-owned.  The first transition only
        # reserves the action; it never launches a hidden worker.
        prepare = self._cli(
            "prepare-dispatch", "--run-dir", str(run_dir), "--action", action_id
        )
        dispatch = self._cli(
            "dispatch",
            "--run-dir",
            str(run_dir),
            "--action",
            action_id,
            "--handle",
            "<native-handle>",
        )
        block = self._cli(
            "block",
            "--run-dir",
            str(run_dir),
            "--action",
            action_id,
            "--reason",
            "<concrete capability or availability reason>",
        )
        packet["result_file"] = result_path
        if action["status"] == "ready":
            packet["native_dispatch"] = {
                "state": "unprepared",
                "instruction": (
                    "Run prepare-dispatch before any native fresh-context spawn. "
                    "The host must use the selected ask-agent route, keep this workspace "
                    "exclusive, forbid nested delegation, and attest the actual handle. "
                    "If no native delegate can be launched, use block with a concrete reason "
                    "before prepare-dispatch."
                ),
            }
            packet["next_argv"] = prepare
            packet["allowed_operation_argv_templates"] = {
                "prepare_dispatch": prepare,
                "block": block,
                "retry": retry,
            }
        elif action["status"] == "dispatching":
            packet["native_dispatch"] = {
                "state": "prepared_in_doubt",
                "instruction": (
                    "Do not launch a fresh agent from a resumed dispatching packet. "
                    "Reconcile whether the prepared host spawn occurred; record its handle "
                    "with dispatch, or fence this action with retry after confirmed stopped."
                ),
            }
            packet["next_argv"] = self._cli("next", "--run-dir", str(run_dir))
            packet["allowed_operation_argv_templates"] = {
                "dispatch": dispatch,
                "retry": retry,
            }
        elif action["status"] == "dispatched":
            packet["native_dispatch"] = {
                "state": "attested",
                "handle": action.get("dispatch", {}).get("handle"),
                "instruction": "Submit the worker result through the exact complete command.",
            }
            packet["next_argv"] = complete
            packet["allowed_operation_argv_templates"] = {
                "complete": complete,
                "retry": retry,
            }
        elif action["status"] == "verifying":
            packet["native_dispatch"] = {
                "state": "verifying",
                "handle": action.get("dispatch", {}).get("handle"),
                "instruction": (
                    "A verifier owns this completion callback. Do not submit complete, launch "
                    "a new worker, or retry while it is live. Use next only; a dead owner is "
                    "parked as in_doubt and requires retry after confirmed stopped."
                ),
            }
            packet["verification"] = {
                "state": "live_or_reconcile",
                "instruction": (
                    "The script owns the current verifier transition and its callback identity."
                ),
            }
            packet["next_argv"] = self._cli("next", "--run-dir", str(run_dir))
            packet["allowed_operation_argv_templates"] = {
                "next": packet["next_argv"]
            }
        elif action["status"] in {"failed", "blocked", "in_doubt"}:
            packet["next_argv"] = self._cli("next", "--run-dir", str(run_dir))
            packet["allowed_operation_argv_templates"] = {"retry": retry}
        else:
            packet["next_argv"] = self._cli("next", "--run-dir", str(run_dir))
            packet["allowed_operation_argv_templates"] = {
                "next": packet["next_argv"]
            }
        packet["allowed_operations"] = packet["allowed_operation_argv_templates"]
        return packet

    def _frontier_packet(self, state: Mapping[str, Any], run_dir: Path) -> Dict[str, Any]:
        """Render a v2 overview plus one ordinary packet per durable action."""
        policy = _execution_policy(state)
        overview_state = dict(state)
        overview_state["current_action"] = None
        packet = self._serial_packet(overview_state, run_dir)
        recovery = self._cli("next", "--run-dir", str(run_dir))
        ready_frontier: List[Dict[str, Any]] = []
        for step in self._ready_steps(state):
            dependencies = self._dependencies(state, run_dir, step)
            ready_frontier.append(
                {
                    "step_id": step["id"],
                    "kind": step["kind"],
                    "needs": list(step["needs"]),
                    "declared_outputs": list(step["outputs"]),
                    "outputs": list(step["outputs"]),
                    "direct_dependency_receipts": dependencies,
                    "dependencies": dependencies,
                }
            )
        active_packets: List[Dict[str, Any]] = []
        for action in _active_actions(state):
            action_state = dict(state)
            action_state["current_action"] = action
            action_state["status"] = action["status"]
            rendered = self._serial_packet(action_state, run_dir)
            rendered["protocol"] = "workflow-action-packet-v2"
            rendered["frontier_mode"] = policy["mode"]
            if action.get("kind") == "agent":
                rendered["workspace_lease"] = action["workspace_lease"]
                rendered["workspace_policy"] = {
                    "mode": "shared-workspace-disjoint",
                    "rule": (
                        "This agent owns only its declared output paths. Do not write "
                        "other workspace paths or delegate another agent."
                    ),
                }
                if isinstance(rendered.get("native_dispatch"), dict):
                    if action.get("status") == "dispatching":
                        rendered["native_dispatch"]["instruction"] = (
                            "Do not launch a fresh agent from this resumed dispatching "
                            "packet. Reconcile whether the prepared host spawn occurred; "
                            "record its handle with dispatch, or fence this action with "
                            "retry after confirmed stopped. Its declared-output lease remains "
                            "reserved while other disjoint agents may proceed."
                        )
                    elif action.get("status") == "dispatched":
                        rendered["native_dispatch"]["instruction"] = (
                            "Submit this worker's result through the exact complete command. "
                            "The worker owns only its declared-output lease and may not choose "
                            "a successor."
                        )
                    elif action.get("status") == "verifying":
                        rendered["native_dispatch"]["instruction"] = (
                            "A verifier owns this callback. Do not submit another complete, "
                            "launch a worker, or retry while it is live; use next only until "
                            "the script records an outcome or parks it for reconciliation."
                        )
                    else:
                        rendered["native_dispatch"]["instruction"] = (
                            "Use the selected ask-agent route with this action's exclusive "
                            "declared-output lease; do not write any other workspace path, "
                            "delegate further work, or choose a successor."
                        )
            active_packets.append(rendered)

        claim = self._cli(
            "claim-ready",
            "--run-dir",
            str(run_dir),
            "--limit",
            "<1..max-active>",
            "--request-id",
            "<opaque-idempotency-key>",
        )
        templates: Dict[str, List[str]] = {"next": recovery}
        if state["status"] != "complete":
            templates["claim_ready"] = claim
        packet.update(
            {
                "protocol": "workflow-frontier-v2",
                "action_id": None,
                "kind": None,
                "step_id": None,
                "next_argv": recovery,
                "recovery_argv": recovery,
                "frontier_mode": policy["mode"],
                "max_active": policy["max_active"],
                "shared_workspace_disjoint": True,
                "active_count": len(active_packets),
                "ready_frontier": ready_frontier,
                "active_packets": active_packets,
                "workspace_policy": {
                    "mode": "shared-workspace-disjoint",
                    "concurrent_kinds": ["agent"],
                    "global_exclusive_kinds": ["command", "prompt", "planning"],
                    "agent_lease": "declared-output-exclusive",
                },
                "claim_instruction": (
                    "The script selects dependency-ready steps. Supply a new opaque request "
                    "ID to claim-ready; never construct an action or successor yourself."
                ),
                "allowed_operation_argv_templates": templates,
                "allowed_operations": templates,
            }
        )
        return packet

    # ----- scheduler ------------------------------------------------------

    def _issue_planning_action(self, state: Dict[str, Any]) -> None:
        if state.get("definition") is not None:
            raise WorkflowError("cannot issue a planning action after definition freeze")
        if _active_actions(state):
            raise WorkflowError("cannot issue planning while execution actions are active")
        state["current_action"] = {
            "id": uuid.uuid4().hex,
            "kind": "planning",
            "step_id": None,
            "attempt": 1,
            "status": "ready",
            "issued_at": _now(),
        }
        state["status"] = "planning"

    def _ready_steps(self, state: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        workflow = state.get("definition")
        if not isinstance(workflow, dict):
            return []
        active_step_ids = {
            action.get("step_id")
            for action in _active_actions(state)
            if isinstance(action.get("step_id"), str)
        }
        ready: List[Mapping[str, Any]] = []
        for step_id in _topological_order(workflow["steps"]):
            if step_id in state["completed"] or step_id in active_step_ids:
                continue
            step = _step_by_id(workflow, step_id)
            if all(need in state["completed"] for need in step["needs"]):
                ready.append(step)
        return ready

    def _new_execution_action(
        self, state: Dict[str, Any], step: Mapping[str, Any]
    ) -> Dict[str, Any]:
        workspace = _workspace_root(state)
        _preflight_declared_outputs(workspace, [step])
        step_id = step["id"]
        prior_attempts = [
            item
            for item in state["attempts"]
            if isinstance(item, dict) and item.get("step_id") == step_id
        ]
        action: Dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "kind": step["kind"],
            "step_id": step_id,
            "attempt": len(prior_attempts) + 1,
            "status": "ready",
            "issued_at": _now(),
            "execution_argv": _execution_argv(step["argv"], workspace)
            if step["kind"] == "command"
            else None,
            "output_preimages": _capture_preimages(workspace, step["outputs"]),
        }
        if _frontier_enabled(state) and step["kind"] == "agent":
            action["workspace_lease"] = {
                "mode": "declared-output-exclusive",
                "paths": list(step["outputs"]),
            }
        state["attempts"].append(
            {
                "action_id": action["id"],
                "step_id": step_id,
                "kind": step["kind"],
                "attempt": action["attempt"],
                "issued_at": action["issued_at"],
                "status": "ready",
            }
        )
        return action

    def _refresh_frontier_state(self, state: Dict[str, Any]) -> None:
        """Derive aggregate state without claiming another branch."""
        if not _frontier_enabled(state):
            return
        active = _active_actions(state)
        if active:
            for candidate in ("in_doubt", "failed", "blocked", "dispatching", "dispatched", "verifying", "executing", "ready"):
                if any(action.get("status") == candidate for action in active):
                    state["status"] = candidate
                    break
            state.pop("blocked_reason", None)
            return
        workflow = state.get("definition")
        if not isinstance(workflow, dict):
            state["status"] = "planning" if state.get("current_action") is not None else "blocked"
            return
        if len(state["completed"]) == len(workflow["steps"]):
            state["status"] = "complete"
            state.pop("blocked_reason", None)
            return
        if self._ready_steps(state):
            state["status"] = "ready"
            state.pop("blocked_reason", None)
            return
        state["status"] = "blocked"
        state["blocked_reason"] = "no dependency-ready step exists"

    def _issue_next_action(self, state: Dict[str, Any]) -> None:
        if _frontier_enabled(state):
            self._refresh_frontier_state(state)
            return
        if state.get("current_action") is not None:
            raise WorkflowError("cannot select next action while one is active")
        workflow = state.get("definition")
        if not isinstance(workflow, dict):
            raise WorkflowError("cannot select execution action without frozen workflow")
        ready = self._ready_steps(state)
        if ready:
            _add_active_action(state, self._new_execution_action(state, ready[0]))
            state["status"] = "ready"
            state.pop("blocked_reason", None)
            return
        if len(state["completed"]) == len(workflow["steps"]):
            state["status"] = "complete"
            state["current_action"] = None
            state.pop("blocked_reason", None)
            return
        state["status"] = "blocked"
        state["blocked_reason"] = "no dependency-ready step exists"

    def claim_ready(
        self,
        *,
        run_dir: Path,
        limit: int,
        request_id: str,
    ) -> Dict[str, Any]:
        """Atomically lease ready v2 branches without choosing successors in a host."""
        target_run = _absolute(run_dir, label="run directory", require_exists=True)
        request_id = _require_string(request_id, label="claim request ID")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise WorkflowError("claim limit must be an integer")
        with run_lock(target_run):
            state, changed = self._load_locked(target_run, reconcile=True)
            if changed:
                self._persist_locked(target_run, state)
            if not _frontier_enabled(state):
                raise WorkflowError("claim-ready requires --max-active and --shared-workspace-disjoint at init")
            policy = _execution_policy(state)
            if not 1 <= limit <= policy["max_active"]:
                raise WorkflowError("claim limit must be between 1 and max_active")
            claims = state["claim_requests"]
            prior = claims.get(request_id)
            if isinstance(prior, dict):
                if prior.get("limit") != limit:
                    raise WorkflowError("claim request ID was already used with a different limit")
                packet = self._packet(state, target_run)
                return self._claim_response(packet, prior, replayed=True)

            active = _active_actions(state)
            claimed: List[Dict[str, Any]] = []
            capacity = max(0, policy["max_active"] - len(active))
            ready = self._ready_steps(state)
            candidates: List[Mapping[str, Any]] = []
            if capacity and ready:
                if active:
                    # A failed or uncertain agent retains its own output lease,
                    # but independent agents may still make bounded progress.
                    if all(action.get("kind") == "agent" for action in active):
                        candidates = [step for step in ready if step["kind"] == "agent"]
                elif ready[0]["kind"] == "agent":
                    candidates = [step for step in ready if step["kind"] == "agent"]
                else:
                    # Commands and prompts retain one global workspace owner.
                    candidates = [ready[0]]
            for step in candidates[: min(limit, capacity)]:
                action = self._new_execution_action(state, step)
                _add_active_action(state, action)
                claimed.append(action)

            record = {
                "request_id": request_id,
                "limit": limit,
                "action_ids": [action["id"] for action in claimed],
                "claimed_at": _now(),
            }
            claims[request_id] = record
            self._refresh_frontier_state(state)
            packet = self._persist_locked(target_run, state)
            return self._claim_response(packet, record, replayed=False)

    def _claim_response(
        self,
        packet: Dict[str, Any],
        record: Mapping[str, Any],
        *,
        replayed: bool,
    ) -> Dict[str, Any]:
        response = dict(packet)
        action_ids = list(record["action_ids"])
        response.update(
            {
                "claim_request_id": record["request_id"],
                "claim_replayed": replayed,
                "claimed_action_ids": action_ids,
                "claimed_packets": [
                    item
                    for item in response.get("active_packets", [])
                    if item.get("action_id") in action_ids
                ],
            }
        )
        return response

    def _require_current_action(
        self,
        state: Mapping[str, Any],
        action_id: str,
        *,
        kind: Optional[str] = None,
        statuses: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        action = _find_active_action(state, action_id)
        if action is None:
            current = state.get("current_action")
            if isinstance(current, dict) and current.get("id") == action_id:
                action = current
        if not isinstance(action, dict) or action.get("id") != action_id:
            raise WorkflowError("action identity is stale or does not belong to this run")
        if kind is not None and action.get("kind") != kind:
            raise WorkflowError(f"action {action_id} is not a {kind} action")
        if statuses is not None and action.get("status") not in set(statuses):
            raise WorkflowError(
                f"action {action_id} is {action.get('status')}, not one of {', '.join(statuses)}"
            )
        return action

    def _attempt(self, state: Dict[str, Any], action_id: str) -> Dict[str, Any]:
        for item in reversed(state["attempts"]):
            if isinstance(item, dict) and item.get("action_id") == action_id:
                return item
        raise WorkflowError(f"state has no attempt record for action {action_id}")

    # ----- planning -------------------------------------------------------

    def accept_plan(
        self,
        *,
        run_dir: Path,
        action_id: str,
        plan_file: Path,
        bindings_file: Path,
    ) -> Dict[str, Any]:
        target_run = _absolute(run_dir, label="run directory", require_exists=True)
        plan, plan_text = load_document(plan_file, label="Backchain plan")
        bindings, bindings_text = load_document(bindings_file, label="execution bindings")
        if not isinstance(plan, dict) or not isinstance(bindings, dict):
            raise WorkflowError("Backchain plan and execution bindings must be JSON objects")
        with run_lock(target_run):
            state, changed = self._load_locked(target_run, reconcile=True)
            if changed:
                self._persist_locked(target_run, state)
            action = self._require_current_action(
                state, action_id, kind="planning", statuses=("ready",)
            )
            if state["request"].get("mode") != "prompt":
                raise WorkflowError("accept-plan is only valid for prompt-initialized runs")
            if plan.get("goal") != state["original_goal"]:
                raise WorkflowError("Backchain plan goal does not match the frozen original request")
            backchain_root = state["request"].get("backchain_root")
            if not isinstance(backchain_root, str):
                raise WorkflowError("planning state has no selected Backchain root")
            staging = target_run / "planning" / f"staging-{action_id}"
            if staging.exists() or staging.is_symlink():
                raise WorkflowError("Backchain staging path already exists for this action")
            adapter = self._adapters()
            try:
                compiled, provenance = adapter.compile_backchain(
                    Path(backchain_root), plan, bindings, staging
                )
            except Exception as exc:
                raise WorkflowError(f"Backchain plan compilation failed: {exc}") from exc
            workflow = normalise_workflow(compiled)
            if workflow["goal"] != state["original_goal"]:
                raise WorkflowError("compiled workflow goal does not match the frozen original request")
            if _frontier_enabled(state):
                _validate_frontier_workflow(workflow)
            _preflight_declared_outputs(_workspace_root(state), workflow["steps"])
            # Ensure the adapter did not return a non-persistable provenance object.
            canonical_json(provenance)
            plan_relative = f"planning/{action_id}.plan.json"
            bindings_relative = f"planning/{action_id}.bindings.json"
            state["definition"] = workflow
            state["planner"] = {
                "action_id": action_id,
                "accepted_at": _now(),
                "plan_path": plan_relative,
                "plan_sha256": sha256_text(plan_text),
                "bindings_path": bindings_relative,
                "bindings_sha256": sha256_text(bindings_text),
                "provenance": provenance,
            }
            state["current_action"] = None
            state["status"] = "ready"
            if _frontier_enabled(state):
                self._refresh_frontier_state(state)
            else:
                self._issue_next_action(state)
            return self._persist_locked(
                target_run,
                state,
                extra_writes={plan_relative: plan_text, bindings_relative: bindings_text},
            )

    # ----- host dispatch and completion ----------------------------------

    def prepare_dispatch(self, *, run_dir: Path, action_id: str) -> Dict[str, Any]:
        target_run = _absolute(run_dir, label="run directory", require_exists=True)
        with run_lock(target_run):
            state, changed = self._load_locked(target_run, reconcile=True)
            if changed:
                self._persist_locked(target_run, state)
            action = self._require_current_action(
                state, action_id, kind="agent", statuses=("ready",)
            )
            action["status"] = "dispatching"
            action["dispatch"] = {
                "prepared_at": _now(),
                "attestation": "host-native spawn not yet attested",
            }
            if _frontier_enabled(state):
                self._refresh_frontier_state(state)
            else:
                state["status"] = "dispatching"
            self._attempt(state, action_id).update(
                {"status": "dispatching", "prepared_at": action["dispatch"]["prepared_at"]}
            )
            persisted = self._persist_locked(target_run, state)
            # ``packet.md`` stays the conservative recovered view: if the host
            # dies after this response, it must reconcile rather than spawn a
            # second worker.  This first direct response is the one-time launch
            # authorization for the host that just durably prepared the action.
            response = dict(persisted)
            dispatch = self._cli(
                "dispatch",
                "--run-dir",
                str(target_run),
                "--action",
                action_id,
                "--handle",
                "<native-handle>",
            )
            launch_once = {
                "state": "launch_once",
                "instruction": (
                    "Launch exactly one native fresh-context agent now using the selected "
                    "ask-agent route, explicit workspace ownership, and no nested delegation. "
                    "After confirmed launch, attest its real handle with the dispatch callback."
                ),
            }
            if _frontier_enabled(state):
                prepared = next(
                    item
                    for item in response.get("active_packets", [])
                    if item.get("action_id") == action_id
                )
                prepared = dict(prepared)
                prepared["native_dispatch"] = launch_once
                prepared["next_argv"] = dispatch
                prepared_templates = dict(prepared["allowed_operation_argv_templates"])
                prepared_templates["dispatch"] = dispatch
                prepared["allowed_operation_argv_templates"] = prepared_templates
                prepared["allowed_operations"] = prepared_templates
                response["prepared_action_id"] = action_id
                response["prepared_packet"] = prepared
                return response
            response["native_dispatch"] = launch_once
            response["next_argv"] = dispatch
            templates = dict(response["allowed_operation_argv_templates"])
            templates["dispatch"] = dispatch
            response["allowed_operation_argv_templates"] = templates
            response["allowed_operations"] = templates
            return response

    def dispatch(self, *, run_dir: Path, action_id: str, handle: str) -> Dict[str, Any]:
        target_run = _absolute(run_dir, label="run directory", require_exists=True)
        handle = _require_string(handle, label="native dispatch handle")
        with run_lock(target_run):
            state, changed = self._load_locked(target_run, reconcile=True)
            if changed:
                self._persist_locked(target_run, state)
            action = self._require_current_action(state, action_id, kind="agent")
            dispatch_info = action.get("dispatch") if isinstance(action.get("dispatch"), dict) else {}
            if action.get("status") == "dispatched":
                if dispatch_info.get("handle") == handle:
                    return self._packet(state, target_run)
                raise WorkflowError("native dispatch handle conflicts with the recorded receipt")
            if action.get("status") != "dispatching":
                raise WorkflowError("dispatch requires prepare-dispatch before host spawn")
            receipt = {
                "prepared_at": dispatch_info.get("prepared_at"),
                "received_at": _now(),
                "handle": handle,
                "attestation": "trusted host attestation; provider launch is not independently validated",
            }
            action["dispatch"] = receipt
            action["status"] = "dispatched"
            if _frontier_enabled(state):
                self._refresh_frontier_state(state)
            else:
                state["status"] = "dispatched"
            state["dispatch_history"].append({"action_id": action_id, **receipt})
            self._attempt(state, action_id).update(
                {"status": "dispatched", "dispatch": receipt}
            )
            return self._persist_locked(target_run, state)

    def block(self, *, run_dir: Path, action_id: str, reason: str) -> Dict[str, Any]:
        """Durably park an unavailable native delegate before any launch intent.

        This is deliberately narrower than ``complete``: only a currently
        ready agent can be blocked.  Once preparation has been persisted, the
        host must reconcile that possible launch through the existing dispatch
        and retry rules instead of claiming that no delegate existed.
        """
        target_run = _absolute(run_dir, label="run directory", require_exists=True)
        reason = _require_string(reason, label="block reason")
        result = {"status": "blocked", "summary": reason}
        result_digest = sha256_value(result)
        # This callback has no user-supplied result file.  Its canonical bytes
        # are nevertheless recorded separately so receipt identity remains
        # explicit and replay checks remain exact for this script-owned route.
        raw_result_digest = sha256_text(canonical_json(result))
        with run_lock(target_run):
            state, changed = self._load_locked(target_run, reconcile=True)
            if changed:
                self._persist_locked(target_run, state)
            action = _find_active_action(state, action_id)
            if isinstance(action, dict) and action.get("kind") == "agent" and action.get("status") == "blocked":
                prior_block = action.get("block")
                if isinstance(prior_block, dict) and prior_block.get("reason") == reason:
                    return self._packet(state, target_run)
                raise WorkflowError("block callback conflicts with the recorded blocked reason")
            if action is None:
                raise WorkflowError("block action identity is stale or does not belong to this run")
            action = self._require_current_action(
                state, action_id, kind="agent", statuses=("ready",)
            )
            if action.get("dispatch") is not None:
                raise WorkflowError("block is only valid before prepare-dispatch")
            block_record = {
                "at": _now(),
                "reason": reason,
                "source": "script-owned pre-dispatch capability block",
            }
            action["block"] = block_record
            self._attempt(state, action_id).update({"block": dict(block_record)})
            return self._accept_completion_locked(
                target_run,
                state,
                action,
                result=result,
                result_digest=result_digest,
                raw_result_digest=raw_result_digest,
                status="blocked",
                checks=[],
                output_evidence=[],
            )

    def complete(self, *, run_dir: Path, action_id: str, result_file: Path) -> Dict[str, Any]:
        target_run = _absolute(run_dir, label="run directory", require_exists=True)
        result, result_text = load_document(result_file, label="result file")
        if not isinstance(result, dict):
            raise WorkflowError("result file must contain an object")
        expected_result_keys = {"status", "summary"}
        if set(result) != expected_result_keys:
            raise WorkflowError("result file may contain only status and summary")
        status = result.get("status")
        if status not in {"succeeded", "failed", "blocked"}:
            raise WorkflowError("result status must be succeeded, failed, or blocked")
        _require_string(result.get("summary"), label="result.summary")
        result_digest = sha256_value(result)
        raw_result_digest = sha256_text(result_text)

        # A verifier can read or mutate the shared workspace.  Hold the same
        # effect lock used by commands for the entire callback lifecycle.  A
        # sibling callback waits rather than racing its verifier; once it owns
        # the lock it rehydrates the durable state and never replays an earlier
        # verifier intent.
        with execution_lock(target_run, owner_action_id=action_id, blocking=True):
            return self._complete_live(
                target_run,
                action_id,
                result,
                result_digest,
                raw_result_digest,
            )

    def _verification_record(
        self,
        action: Mapping[str, Any],
        result_digest: str,
        raw_result_digest: str,
    ) -> Dict[str, Any]:
        verification = action.get("verification")
        if not isinstance(verification, dict):
            raise WorkflowError("completion action has no durable verifier intent")
        callback = verification.get("callback")
        if not isinstance(callback, dict):
            raise WorkflowError("verifier intent has no callback identity")
        if callback.get("result_sha256") != result_digest:
            raise WorkflowError("callback conflicts with the durable verifier intent")
        if callback.get("result_raw_sha256") != raw_result_digest:
            raise WorkflowError("callback bytes conflict with the durable verifier intent")
        return verification

    def _completion_problem(
        self,
        run_dir: Path,
        state: Dict[str, Any],
        action: Dict[str, Any],
        *,
        status: str,
        reason: str,
        checks: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Persist a non-accepted completion without allowing a blind replay."""
        if status not in {"failed", "in_doubt"}:
            raise WorkflowError("completion problem has an invalid status")
        finished_at = _now()
        verification = action.get("verification")
        if isinstance(verification, dict):
            verification["phase"] = status
            verification["finished_at"] = finished_at
        action["status"] = status
        action["failure"] = {
            "at": finished_at,
            "reason": reason,
            "checks": [dict(check) for check in checks],
        }
        attempt = self._attempt(state, action["id"])
        attempt.update(
            {
                "status": status,
                "finished_at": finished_at,
                "reason": reason,
                "checks": [dict(check) for check in checks],
                "verification": verification,
            }
        )
        if _frontier_enabled(state):
            self._refresh_frontier_state(state)
        else:
            state["status"] = status
        return self._persist_locked(run_dir, state)

    def _accept_completion_locked(
        self,
        run_dir: Path,
        state: Dict[str, Any],
        action: Dict[str, Any],
        *,
        result: Mapping[str, Any],
        result_digest: str,
        raw_result_digest: str,
        status: str,
        checks: Sequence[Mapping[str, Any]],
        output_evidence: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Commit a receipt and its state transition in one durable transaction."""
        accepted_at = _now()
        receipt = {
            "schema": "workflow-receipt",
            "version": 1,
            "action_id": action["id"],
            "step_id": action["step_id"],
            "kind": action["kind"],
            "accepted_at": accepted_at,
            "result": dict(result),
            "result_sha256": result_digest,
            "result_raw_sha256": raw_result_digest,
            "outputs": [dict(item) for item in output_evidence],
            "checks": [dict(check) for check in checks],
            "dispatch": action.get("dispatch"),
        }
        if isinstance(action.get("block"), dict):
            receipt["block"] = dict(action["block"])
        receipt_relative = f"receipts/{action['id']}.md"
        receipt_text = store.dumps(receipt, title=f"Workflow receipt {action['step_id']}")
        receipt_hash = sha256_text(receipt_text)
        state["callbacks"][action["id"]] = {
            "result_sha256": result_digest,
            "result_raw_sha256": raw_result_digest,
            "receipt_path": receipt_relative,
            "receipt_sha256": receipt_hash,
            "status": status,
        }
        attempt = self._attempt(state, action["id"])
        attempt.update(
            {
                "status": status,
                "result_sha256": result_digest,
                "checks": [dict(check) for check in checks],
                "finished_at": accepted_at,
                "receipt_path": receipt_relative,
            }
        )
        if status == "succeeded":
            verification = action.get("verification")
            if isinstance(verification, dict):
                verification["phase"] = "accepted"
                verification["accepted_at"] = accepted_at
                attempt["verification"] = verification
            state["completed"][action["step_id"]] = {
                "action_id": action["id"],
                "receipt_path": receipt_relative,
                "receipt_sha256": receipt_hash,
                "outputs": [dict(item) for item in output_evidence],
                "completed_at": accepted_at,
            }
            _remove_active_action(state, action["id"])
            if _frontier_enabled(state):
                self._refresh_frontier_state(state)
            else:
                state["status"] = "ready"
                self._issue_next_action(state)
        else:
            action["status"] = status
            action["callback"] = {
                "receipt_path": receipt_relative,
                "receipt_sha256": receipt_hash,
            }
            if _frontier_enabled(state):
                self._refresh_frontier_state(state)
            else:
                state["status"] = status
        return self._persist_locked(
            run_dir, state, extra_writes={receipt_relative: receipt_text}
        )

    def _complete_live(
        self,
        target_run: Path,
        action_id: str,
        result: Dict[str, Any],
        result_digest: str,
        raw_result_digest: str,
    ) -> Dict[str, Any]:
        with run_lock(target_run):
            state, changed = self._load_locked(
                target_run,
                reconcile=True,
                live_execution=True,
                live_action_id=action_id,
            )
            if changed:
                self._persist_locked(target_run, state)
            prior_callback = state["callbacks"].get(action_id)
            if isinstance(prior_callback, dict):
                if prior_callback.get("result_sha256") != result_digest:
                    raise WorkflowError("callback replay conflicts with previously accepted result")
                return self._packet(state, target_run)

            action = self._require_current_action(state, action_id)
            if action.get("status") == "verifying":
                # We acquired the lock only after the former verifier owner
                # released it.  Its persisted intent is therefore ambiguous,
                # even when a duplicate callback carries the same result.
                self._completion_problem(
                    target_run,
                    state,
                    action,
                    status="in_doubt",
                    reason="verifier owner ended before its durable outcome was recorded",
                    checks=action.get("verification", {}).get("checks", [])
                    if isinstance(action.get("verification"), dict)
                    else [],
                )
                raise WorkflowError(
                    "completion has an unresolved verifier intent; use retry after confirmed stopped"
                )
            if action.get("kind") == "command":
                raise WorkflowError("a command action cannot use complete; use execute")
            if action.get("kind") not in {"prompt", "agent"}:
                raise WorkflowError("complete is not valid for this action kind")
            if action["kind"] == "agent":
                if action.get("status") != "dispatched" or not isinstance(
                    action.get("dispatch"), dict
                ) or not action["dispatch"].get("handle"):
                    raise WorkflowError("agent completion requires a recorded native dispatch handle")
            elif action.get("status") != "ready":
                raise WorkflowError("prompt action is not ready for completion")

            definition = state["definition"]
            step = _step_by_id(definition, action["step_id"])
            workspace = _workspace_root(state)
            if result["status"] != "succeeded":
                return self._accept_completion_locked(
                    target_run,
                    state,
                    action,
                    result=result,
                    result_digest=result_digest,
                    raw_result_digest=raw_result_digest,
                    status=result["status"],
                    checks=[],
                    output_evidence=[],
                )

            verification = {
                "phase": "intent",
                "intent_at": _now(),
                "owner": {
                    "lock_path": str(target_run / ".workflow.executing.lock"),
                    "pid": os.getpid(),
                    "action_id": action_id,
                },
                "callback": {
                    "result": dict(result),
                    "result_sha256": result_digest,
                    "result_raw_sha256": raw_result_digest,
                },
                "checks": [],
            }
            action["status"] = "verifying"
            action["verification"] = verification
            if _frontier_enabled(state):
                self._refresh_frontier_state(state)
            else:
                state["status"] = "verifying"
            self._attempt(state, action_id).update(
                {
                    "status": "verifying",
                    "verification": verification,
                }
            )
            # This transaction is deliberately before any verifier Popen.
            self._persist_locked(target_run, state)

        checks_result = self._run_completion_checks(
            target_run,
            action_id,
            step["verify"],
            workspace,
            float(step["timeout_seconds"]),
            result_digest,
            raw_result_digest,
        )
        checks = checks_result["entries"]
        with run_lock(target_run):
            state, _ = self._load_locked(
                target_run,
                reconcile=False,
                live_execution=True,
                live_action_id=action_id,
            )
            action = self._require_current_action(
                state, action_id, statuses=("verifying",)
            )
            self._verification_record(action, result_digest, raw_result_digest)
            if checks_result["in_doubt"]:
                return self._completion_problem(
                    target_run,
                    state,
                    action,
                    status="in_doubt",
                    reason="verification timeout; effects require explicit reconciliation",
                    checks=checks,
                )
            if not checks_result["ok"]:
                return self._completion_problem(
                    target_run,
                    state,
                    action,
                    status="failed",
                    reason="declared verification command failed",
                    checks=checks,
                )
            try:
                # Verifiers are executable trusted input.  They might mutate a
                # current output or an earlier accepted dependency, so evidence
                # is collected only after all checks and the ledger is checked
                # again immediately before accepting the callback.
                _assert_accepted_evidence(state, target_run)
                output_evidence = _verified_outputs(
                    workspace,
                    step["outputs"],
                    action.get("output_preimages", {}),
                    require_changed=True,
                )
            except WorkflowError as exc:
                return self._completion_problem(
                    target_run,
                    state,
                    action,
                    status="failed",
                    reason=str(exc),
                    checks=checks,
                )
            return self._accept_completion_locked(
                target_run,
                state,
                action,
                result=result,
                result_digest=result_digest,
                raw_result_digest=raw_result_digest,
                status="succeeded",
                checks=checks,
                output_evidence=output_evidence,
            )

    # ----- command execution --------------------------------------------

    def _log_paths(self, run_dir: Path, action_id: str, suffix: str) -> Tuple[Path, Path, str, str]:
        stdout_relative = f"logs/{action_id}.{suffix}.stdout.log"
        stderr_relative = f"logs/{action_id}.{suffix}.stderr.log"
        return (
            _safe_run_path(run_dir, stdout_relative),
            _safe_run_path(run_dir, stderr_relative),
            stdout_relative,
            stderr_relative,
        )

    def _run_process(
        self,
        *,
        argv: Sequence[str],
        cwd: Path,
        stdout_path: Path,
        stderr_path: Path,
    ) -> Tuple[Optional[subprocess.Popen[bytes]], Optional[str]]:
        try:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
                try:
                    process = subprocess.Popen(
                        list(argv),
                        cwd=str(cwd),
                        stdin=subprocess.DEVNULL,
                        stdout=stdout_handle,
                        stderr=stderr_handle,
                        start_new_session=True,
                    )
                except OSError as exc:
                    stderr_handle.write(f"workflow could not start process: {exc}\n".encode("utf-8"))
                    stderr_handle.flush()
                    os.fsync(stderr_handle.fileno())
                    return None, str(exc)
                return process, None
        except OSError as exc:
            raise WorkflowError(f"cannot create command log files: {exc}") from exc

    def _wait_process(self, process: subprocess.Popen[bytes], timeout: float) -> Dict[str, Any]:
        try:
            returncode = process.wait(timeout=float(timeout))
            return {"returncode": returncode, "timed_out": False}
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            return {"returncode": process.returncode, "timed_out": True}

    def _log_evidence(self, run_dir: Path, stdout_relative: str, stderr_relative: str) -> Dict[str, Any]:
        stdout_path = _safe_run_path(run_dir, stdout_relative)
        stderr_path = _safe_run_path(run_dir, stderr_relative)
        return {
            "stdout_path": stdout_relative,
            "stdout_sha256": sha256_file(stdout_path),
            "stderr_path": stderr_relative,
            "stderr_sha256": sha256_file(stderr_path),
        }

    def _run_checks(
        self,
        run_dir: Path,
        action_id: str,
        checks: Sequence[Sequence[str]],
        workspace: Path,
        timeout: float,
    ) -> Dict[str, Any]:
        entries: List[Dict[str, Any]] = []
        for index, argv in enumerate(checks):
            stdout_path, stderr_path, stdout_relative, stderr_relative = self._log_paths(
                run_dir, action_id, f"verify-{index}"
            )
            process, start_error = self._run_process(
                argv=argv,
                cwd=workspace,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            if process is None:
                evidence = self._log_evidence(run_dir, stdout_relative, stderr_relative)
                entry: Dict[str, Any] = {"argv": list(argv), **evidence}
                entry.update({"returncode": None, "start_error": start_error})
                entries.append(entry)
                return {"ok": False, "in_doubt": False, "entries": entries}
            outcome = self._wait_process(process, timeout)
            # The child owns these file descriptors.  Hash only after it exits,
            # otherwise a valid verifier can be recorded with hashes for empty
            # or partial logs.
            evidence = self._log_evidence(run_dir, stdout_relative, stderr_relative)
            entry = {"argv": list(argv), **evidence}
            entry.update(outcome)
            entries.append(entry)
            if outcome["timed_out"]:
                return {"ok": False, "in_doubt": True, "entries": entries}
            if outcome["returncode"] != 0:
                return {"ok": False, "in_doubt": False, "entries": entries}
        return {"ok": True, "in_doubt": False, "entries": entries}

    def _completion_check_entry(
        self,
        action: Dict[str, Any],
        *,
        index: int,
        result_digest: str,
        raw_result_digest: str,
    ) -> Dict[str, Any]:
        verification = self._verification_record(
            action, result_digest, raw_result_digest
        )
        checks = verification.get("checks")
        if not isinstance(checks, list) or len(checks) <= index:
            raise WorkflowError("verifier check record is missing")
        entry = checks[index]
        if not isinstance(entry, dict) or entry.get("index") != index:
            raise WorkflowError("verifier check record is invalid")
        return entry

    def _run_completion_checks(
        self,
        run_dir: Path,
        action_id: str,
        checks: Sequence[Sequence[str]],
        workspace: Path,
        timeout: float,
        result_digest: str,
        raw_result_digest: str,
    ) -> Dict[str, Any]:
        """Run verifier children through durable intent/spawn/finish records.

        The caller holds ``execution_lock`` for this entire method, while this
        method deliberately releases the short run lock around each child.
        A crash in any gap leaves ``verifying`` plus a callback/check identity,
        so cold recovery can park it instead of launching the same verifier.
        """
        entries: List[Dict[str, Any]] = []
        for index, argv in enumerate(checks):
            stdout_path, stderr_path, stdout_relative, stderr_relative = self._log_paths(
                run_dir, action_id, f"verify-{index}"
            )
            with run_lock(run_dir):
                state, _ = self._load_locked(
                    run_dir,
                    reconcile=False,
                    live_execution=True,
                    live_action_id=action_id,
                )
                action = self._require_current_action(
                    state, action_id, statuses=("verifying",)
                )
                verification = self._verification_record(
                    action, result_digest, raw_result_digest
                )
                stored_checks = verification.get("checks")
                if not isinstance(stored_checks, list) or len(stored_checks) != index:
                    raise WorkflowError("verifier check sequence is not append-only")
                entry: Dict[str, Any] = {
                    "index": index,
                    "argv": list(argv),
                    "phase": "intent",
                    "intent_at": _now(),
                    "stdout_path": stdout_relative,
                    "stderr_path": stderr_relative,
                    "log_identity": {
                        "stdout_path": stdout_relative,
                        "stderr_path": stderr_relative,
                    },
                }
                stored_checks.append(entry)
                self._attempt(state, action_id).update(
                    {
                        "status": "verifying",
                        "verification": verification,
                    }
                )
                self._persist_locked(run_dir, state)

            process, start_error = self._run_process(
                argv=argv,
                cwd=workspace,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            if process is None:
                with run_lock(run_dir):
                    state, _ = self._load_locked(
                        run_dir,
                        reconcile=False,
                        live_execution=True,
                        live_action_id=action_id,
                    )
                    action = self._require_current_action(
                        state, action_id, statuses=("verifying",)
                    )
                    entry = self._completion_check_entry(
                        action,
                        index=index,
                        result_digest=result_digest,
                        raw_result_digest=raw_result_digest,
                    )
                    entry.update(
                        {
                            "phase": "start_failed",
                            "finished_at": _now(),
                            "returncode": None,
                            "start_error": start_error,
                            **self._log_evidence(
                                run_dir, stdout_relative, stderr_relative
                            ),
                        }
                    )
                    self._attempt(state, action_id).update(
                        {"verification": action["verification"]}
                    )
                    self._persist_locked(run_dir, state)
                    entries.append(dict(entry))
                return {"ok": False, "in_doubt": False, "entries": entries}

            try:
                pgid = os.getpgid(process.pid)
            except OSError:
                pgid = process.pid
            with run_lock(run_dir):
                state, _ = self._load_locked(
                    run_dir,
                    reconcile=False,
                    live_execution=True,
                    live_action_id=action_id,
                )
                action = self._require_current_action(
                    state, action_id, statuses=("verifying",)
                )
                entry = self._completion_check_entry(
                    action,
                    index=index,
                    result_digest=result_digest,
                    raw_result_digest=raw_result_digest,
                )
                entry.update(
                    {
                        "phase": "spawned",
                        "started_at": _now(),
                        "pid": process.pid,
                        "pgid": pgid,
                    }
                )
                self._attempt(state, action_id).update(
                    {"verification": action["verification"]}
                )
                self._persist_locked(run_dir, state)

            outcome = self._wait_process(process, timeout)
            with run_lock(run_dir):
                state, _ = self._load_locked(
                    run_dir,
                    reconcile=False,
                    live_execution=True,
                    live_action_id=action_id,
                )
                action = self._require_current_action(
                    state, action_id, statuses=("verifying",)
                )
                entry = self._completion_check_entry(
                    action,
                    index=index,
                    result_digest=result_digest,
                    raw_result_digest=raw_result_digest,
                )
                # Hash only after the child has exited.  These hashes are
                # persisted before any receipt can claim them.
                entry.update(
                    {
                        "phase": "finished",
                        "finished_at": _now(),
                        **outcome,
                        **self._log_evidence(run_dir, stdout_relative, stderr_relative),
                    }
                )
                self._attempt(state, action_id).update(
                    {"verification": action["verification"]}
                )
                self._persist_locked(run_dir, state)
                entries.append(dict(entry))
            if outcome["timed_out"]:
                return {"ok": False, "in_doubt": True, "entries": entries}
            if outcome["returncode"] != 0:
                return {"ok": False, "in_doubt": False, "entries": entries}
        return {"ok": True, "in_doubt": False, "entries": entries}

    def _finish_command_problem(
        self,
        run_dir: Path,
        state: Dict[str, Any],
        action: Dict[str, Any],
        *,
        status: str,
        reason: str,
        logs: Dict[str, Any],
        checks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        action["status"] = status
        action["failure"] = {"at": _now(), "reason": reason, "logs": logs, "checks": checks or []}
        if _frontier_enabled(state):
            self._refresh_frontier_state(state)
        else:
            state["status"] = status
        attempt = self._attempt(state, action["id"])
        attempt.update(
            {
                "status": status,
                "finished_at": action["failure"]["at"],
                "reason": reason,
                "logs": logs,
                "checks": checks or [],
            }
        )
        return self._persist_locked(run_dir, state)

    def execute(self, *, run_dir: Path, action_id: str) -> Dict[str, Any]:
        target_run = _absolute(run_dir, label="run directory", require_exists=True)
        with execution_lock(target_run, owner_action_id=action_id):
            return self._execute_live(target_run, action_id)

    def _execute_live(self, target_run: Path, action_id: str) -> Dict[str, Any]:
        # Record an intent while the process-held execution flock is already
        # taken.  A concurrent next can now render a live executing packet
        # without mistaking this deliberate lock release for a crashed CLI.
        with run_lock(target_run):
            state, changed = self._load_locked(
                target_run, reconcile=True, live_execution=True, live_action_id=action_id
            )
            if changed:
                self._persist_locked(target_run, state)
            action = self._require_current_action(
                state, action_id, kind="command", statuses=("ready",)
            )
            step = _step_by_id(state["definition"], action["step_id"])
            workspace = _workspace_root(state)
            execution_argv = action.get("execution_argv")
            if not isinstance(execution_argv, list) or not all(
                isinstance(item, str) for item in execution_argv
            ):
                raise WorkflowError("command action has no frozen execution argv")
            action["status"] = "executing"
            action["launch"] = {
                "phase": "intent",
                "intent_at": _now(),
                "argv": list(execution_argv),
                "cwd": str(workspace),
            }
            if _frontier_enabled(state):
                self._refresh_frontier_state(state)
            else:
                state["status"] = "executing"
            self._attempt(state, action_id).update(
                {"status": "executing", "launch": dict(action["launch"])}
            )
            self._persist_locked(target_run, state)
            stdout_path, stderr_path, stdout_relative, stderr_relative = self._log_paths(
                target_run, action_id, "command"
            )

        process, start_error = self._run_process(
            argv=execution_argv,
            cwd=workspace,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        if process is None:
            with run_lock(target_run):
                state, _ = self._load_locked(
                    target_run, reconcile=False, live_execution=True, live_action_id=action_id
                )
                action = self._require_current_action(
                    state, action_id, kind="command", statuses=("executing",)
                )
                logs = self._log_evidence(target_run, stdout_relative, stderr_relative)
                return self._finish_command_problem(
                    target_run,
                    state,
                    action,
                    status="failed",
                    reason=f"command did not start: {start_error}",
                    logs=logs,
                )

        # Persist PID/PGID immediately after Popen so recovery has a concrete
        # launch identity.  The pre-Popen intent remains the conservative edge.
        try:
            pgid = os.getpgid(process.pid)
        except OSError:
            pgid = process.pid
        with run_lock(target_run):
            state, _ = self._load_locked(
                target_run, reconcile=False, live_execution=True, live_action_id=action_id
            )
            current = _find_active_action(state, action_id)
            if not isinstance(current, dict) or current.get("id") != action_id or current.get("status") != "executing":
                # Another caller reconciled the persisted intent.  Kill the
                # child rather than leave an untracked process writing files.
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except OSError:
                    pass
                return self._packet(state, target_run)
            launch = {
                "phase": "spawned",
                "intent_at": current["launch"]["intent_at"],
                "started_at": _now(),
                "pid": process.pid,
                "pgid": pgid,
                "argv": list(execution_argv),
                "cwd": str(workspace),
            }
            current["launch"] = launch
            self._attempt(state, action_id).update({"launch": dict(launch)})
            self._persist_locked(target_run, state)

        outcome = self._wait_process(process, float(step["timeout_seconds"]))
        with run_lock(target_run):
            state, _ = self._load_locked(
                target_run, reconcile=False, live_execution=True, live_action_id=action_id
            )
            action = self._require_current_action(
                state, action_id, kind="command", statuses=("executing",)
            )
            logs = self._log_evidence(target_run, stdout_relative, stderr_relative)
            if outcome["timed_out"]:
                return self._finish_command_problem(
                    target_run,
                    state,
                    action,
                    status="in_doubt",
                    reason="command timeout; effects require explicit reconciliation",
                    logs=logs,
                )
            if outcome["returncode"] != 0:
                return self._finish_command_problem(
                    target_run,
                    state,
                    action,
                    status="failed",
                    reason=f"command exited with status {outcome['returncode']}",
                    logs=logs,
                )
            checks_result = self._run_checks(
                target_run, action_id, step["verify"], workspace, step["timeout_seconds"]
            )
            checks = checks_result["entries"]
            if checks_result["in_doubt"]:
                return self._finish_command_problem(
                    target_run,
                    state,
                    action,
                    status="in_doubt",
                    reason="verification timeout; effects require explicit reconciliation",
                    logs=logs,
                    checks=checks,
                )
            if not checks_result["ok"]:
                return self._finish_command_problem(
                    target_run,
                    state,
                    action,
                    status="failed",
                    reason="declared verification command failed",
                    logs=logs,
                    checks=checks,
                )
            try:
                # Re-evaluate both old accepted outputs and this attempt's
                # declared files after arbitrary verifier commands finish.
                _assert_accepted_evidence(state, target_run)
                output_evidence = _verified_outputs(
                    workspace,
                    step["outputs"],
                    action.get("output_preimages", {}),
                    require_changed=True,
                )
            except WorkflowError as exc:
                return self._finish_command_problem(
                    target_run,
                    state,
                    action,
                    status="failed",
                    reason=str(exc),
                    logs=logs,
                    checks=checks,
                )
            receipt = {
                "schema": "workflow-receipt",
                "version": 1,
                "action_id": action_id,
                "step_id": action["step_id"],
                "kind": "command",
                "accepted_at": _now(),
                "command": {
                    "argv": list(execution_argv),
                    "returncode": outcome["returncode"],
                    "launch": action.get("launch"),
                    "logs": logs,
                },
                "outputs": output_evidence,
                "checks": checks,
            }
            receipt_relative = f"receipts/{action_id}.md"
            receipt_text = store.dumps(receipt, title=f"Workflow receipt {action['step_id']}")
            receipt_hash = sha256_text(receipt_text)
            state["completed"][action["step_id"]] = {
                "action_id": action_id,
                "receipt_path": receipt_relative,
                "receipt_sha256": receipt_hash,
                "outputs": output_evidence,
                "completed_at": receipt["accepted_at"],
            }
            state["callbacks"][action_id] = {
                "result_sha256": sha256_value({"status": "succeeded", "command": True}),
                "receipt_path": receipt_relative,
                "receipt_sha256": receipt_hash,
                "status": "succeeded",
            }
            self._attempt(state, action_id).update(
                {
                    "status": "succeeded",
                    "finished_at": receipt["accepted_at"],
                    "logs": logs,
                    "checks": checks,
                    "receipt_path": receipt_relative,
                }
            )
            _remove_active_action(state, action_id)
            if _frontier_enabled(state):
                self._refresh_frontier_state(state)
            else:
                state["status"] = "ready"
                self._issue_next_action(state)
            return self._persist_locked(
                target_run, state, extra_writes={receipt_relative: receipt_text}
            )

    def run(self, *, run_dir: Path) -> Dict[str, Any]:
        """Run only ready command steps; stop at every host-owned boundary."""
        target_run = _absolute(run_dir, label="run directory", require_exists=True)
        while True:
            with run_lock(target_run):
                state, changed = self._load_locked(target_run, reconcile=True)
                if changed:
                    packet = self._persist_locked(target_run, state)
                else:
                    packet = self._packet(state, target_run)
                actions = _active_actions(state)
                if _frontier_enabled(state) and not actions:
                    ready = self._ready_steps(state)
                    if (
                        state.get("status") == "ready"
                        and ready
                        and ready[0]["kind"] == "command"
                    ):
                        command = self._new_execution_action(state, ready[0])
                        _add_active_action(state, command)
                        self._refresh_frontier_state(state)
                        packet = self._persist_locked(target_run, state)
                        actions = [command]
                action = actions[0] if len(actions) == 1 else None
                should_execute = (
                    state.get("status") == "ready"
                    and isinstance(action, dict)
                    and action.get("kind") == "command"
                    and action.get("status") == "ready"
                )
                action_id = action["id"] if should_execute else None
            if not should_execute:
                return packet
            self.execute(run_dir=target_run, action_id=action_id)

    # ----- explicit reconciliation ---------------------------------------

    def retry(
        self,
        *,
        run_dir: Path,
        action_id: str,
        reason: str,
        confirmed_stopped: bool,
    ) -> Dict[str, Any]:
        target_run = _absolute(run_dir, label="run directory", require_exists=True)
        reason = _require_string(reason, label="retry reason")
        if not confirmed_stopped:
            raise WorkflowError("retry requires --confirmed-stopped caller attestation")
        with run_lock(target_run):
            state, changed = self._load_locked(target_run, reconcile=True)
            if changed:
                self._persist_locked(target_run, state)
            action = self._require_current_action(state, action_id)
            retryable = {"failed", "blocked", "in_doubt", "dispatching", "dispatched"}
            if action.get("status") not in retryable:
                raise WorkflowError("retry only reconciles failed, blocked, in-doubt, or dispatch actions")
            old_action = dict(action)
            state["retry_history"].append(
                {
                    "at": _now(),
                    "old_action_id": action_id,
                    "step_id": action.get("step_id"),
                    "reason": reason,
                    "confirmed_stopped": True,
                    "attestation": "caller attestation only; the engine cannot prove a worker stopped",
                    "preserved_artifacts": {
                        "launch": old_action.get("launch"),
                        "dispatch": old_action.get("dispatch"),
                        "block": old_action.get("block"),
                        "verification": old_action.get("verification"),
                        "failure": old_action.get("failure"),
                    },
                }
            )
            if action.get("kind") == "planning":
                state["current_action"] = None
                self._issue_planning_action(state)
                return self._persist_locked(target_run, state)
            # New action issuance records current output preimages, so retry
            # cannot silently accept artifacts left by the fenced attempt.
            if _frontier_enabled(state):
                step = _step_by_id(state["definition"], action["step_id"])
                _remove_active_action(state, action_id)
                _add_active_action(state, self._new_execution_action(state, step))
                self._refresh_frontier_state(state)
            else:
                state["current_action"] = None
                state["status"] = "ready"
                self._issue_next_action(state)
            return self._persist_locked(target_run, state)


__all__ = [
    "RUN_SCHEMA",
    "RUN_VERSION",
    "WorkflowError",
    "WorkflowKernel",
    "canonical_json",
    "load_document",
    "normalise_workflow",
    "parse_json_text",
    "sha256_file",
    "sha256_text",
    "sha256_value",
]
