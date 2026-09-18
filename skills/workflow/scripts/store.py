#!/usr/bin/env python3
"""Markdown-authoritative, crash-recoverable storage for Workflow.

There is deliberately no locking here: callers must hold the run lock while
calling :func:`transaction` or :func:`recover`.  A test-only ``fault`` callback
may be supplied to ``transaction``; it is called as ``fault("after-target",
index)`` immediately after each persisted write or delete.  If it raises, the
write-ahead Markdown journal remains for ``recover`` to replay.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union


class StorageError(RuntimeError):
    """Raised when a record, manifest, or storage location is unsafe or invalid."""


RecordPath = Union[str, os.PathLike[str]]
FaultCallback = Callable[[str, int], None]

JOURNAL_NAME = "transaction.md"
JOURNAL_SCHEMA = "workflow-transaction"
JOURNAL_VERSION = 1
_OPEN_FENCE = re.compile(r"^```workflow-state[ \t]*$")
_OPEN_FENCE_PREFIX = re.compile(r"^```workflow-state(?:\b|[ \t])")
_CLOSE_FENCE = re.compile(r"^```[ \t]*$")

__all__ = [
    "StorageError",
    "atomic_write_text",
    "dumps",
    "loads",
    "read_record",
    "recover",
    "transaction",
    "write_record",
]


def _require_title(title: str) -> str:
    if not isinstance(title, str) or not title.strip():
        raise StorageError("record title must be a nonempty string")
    if "\n" in title or "\r" in title:
        raise StorageError("record title must be one line")
    return title.strip()


def dumps(obj: Any, title: str = "Workflow record") -> str:
    """Render one human-readable Markdown record with one state JSON fence."""
    heading = _require_title(title)
    try:
        payload = json.dumps(
            obj,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise StorageError(f"record is not JSON serializable: {exc}") from exc
    return f"# {heading}\n\n```workflow-state\n{payload}\n```\n"


def _reject_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StorageError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise StorageError(f"nonstandard JSON constant: {value}")


def loads(text: str) -> Any:
    """Read exactly one ``workflow-state`` JSON fence from a Markdown record."""
    if not isinstance(text, str):
        raise StorageError("record text must be a string")

    lines = text.splitlines()
    openings: List[int] = []
    for index, line in enumerate(lines):
        if _OPEN_FENCE.match(line):
            openings.append(index)
        elif _OPEN_FENCE_PREFIX.match(line):
            raise StorageError("malformed workflow-state fence")
    if len(openings) != 1:
        raise StorageError("record must contain exactly one workflow-state fence")

    opening = openings[0]
    closing: Optional[int] = None
    for index in range(opening + 1, len(lines)):
        if _CLOSE_FENCE.match(lines[index]):
            closing = index
            break
    if closing is None:
        raise StorageError("unterminated workflow-state fence")

    payload = "\n".join(lines[opening + 1 : closing])
    try:
        return json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except StorageError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise StorageError(f"invalid workflow-state JSON: {exc}") from exc


def _as_path(path: RecordPath, *, label: str) -> Path:
    try:
        return Path(path)
    except TypeError as exc:
        raise StorageError(f"{label} must be a filesystem path") from exc


def _fsync_directory(directory: Path) -> None:
    """Persist a directory-entry change after an atomic rename or unlink."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError as exc:
        raise StorageError(
            f"cannot open directory for fsync: {directory}: {exc}"
        ) from exc
    try:
        os.fsync(fd)
    except OSError as exc:
        raise StorageError(f"cannot fsync directory: {directory}: {exc}") from exc
    finally:
        os.close(fd)


def atomic_write_text(path: RecordPath, text: str) -> None:
    """Write UTF-8 text through a unique, fsynced sibling temp file and replace."""
    if not isinstance(text, str):
        raise StorageError("atomic text payload must be a string")
    target = _as_path(path, label="target path")
    parent = target.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        if not parent.is_dir():
            raise StorageError(f"target parent is not a directory: {parent}")
        if target.exists() and not target.is_symlink() and target.is_dir():
            raise StorageError(f"refusing to replace directory: {target}")
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(parent)
        )
    except StorageError:
        raise
    except OSError as exc:
        raise StorageError(f"cannot create atomic temp for {target}: {exc}") from exc

    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
        _fsync_directory(parent)
    except StorageError:
        raise
    except OSError as exc:
        raise StorageError(f"cannot atomically write {target}: {exc}") from exc
    finally:
        try:
            if temp.exists() or temp.is_symlink():
                temp.unlink()
        except OSError:
            pass


def read_record(path: RecordPath) -> Any:
    """Read a Markdown record; raw JSON is intentionally not accepted."""
    target = _as_path(path, label="record path")
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise StorageError(f"cannot read record {target}: {exc}") from exc
    return loads(text)


def write_record(path: RecordPath, obj: Any, title: str = "Workflow record") -> None:
    """Atomically persist ``obj`` as a Markdown-authoritative record."""
    atomic_write_text(path, dumps(obj, title=title))


def _resolve_root(root: RecordPath) -> Path:
    candidate = _as_path(root, label="transaction root")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise StorageError(
            f"transaction root does not resolve: {candidate}: {exc}"
        ) from exc
    if not resolved.is_dir():
        raise StorageError(f"transaction root is not a directory: {candidate}")
    return resolved


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _relative_parts(
    relative_path: str, *, allow_journal: bool = False
) -> Tuple[str, ...]:
    if not isinstance(relative_path, str) or not relative_path:
        raise StorageError("transaction paths must be nonempty strings")
    if "\x00" in relative_path or "\\" in relative_path:
        raise StorageError(f"unsafe transaction path: {relative_path!r}")
    if relative_path.startswith("/"):
        raise StorageError(f"transaction paths must be relative: {relative_path!r}")
    parts = tuple(relative_path.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise StorageError(f"unsafe transaction path: {relative_path!r}")
    if not allow_journal and parts and parts[0] == JOURNAL_NAME:
        raise StorageError("transaction manifests may not edit transaction.md")
    return parts


def _resolve_checked(path: Path, root: Path, *, label: str) -> Path:
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise StorageError(f"cannot resolve {label}: {path}: {exc}") from exc
    if not _is_within(resolved, root):
        raise StorageError(f"{label} escapes transaction root: {path}")
    return resolved


def _checked_target(
    root: Path, relative_path: str, *, allow_journal: bool = False
) -> Path:
    """Validate a lexical relative path and all current symlink components."""
    parts = _relative_parts(relative_path, allow_journal=allow_journal)
    current = root
    for offset, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            _resolve_checked(current, root, label="transaction symlink")
        elif current.exists():
            if offset < len(parts) - 1 and not current.is_dir():
                raise StorageError(f"transaction parent is not a directory: {current}")
            if offset == len(parts) - 1 and current.is_dir():
                raise StorageError(f"transaction target is a directory: {current}")
    _resolve_checked(current, root, label="transaction target")
    return current


def _ensure_safe_parent(root: Path, target: Path) -> None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageError(
            f"cannot create transaction parent {target.parent}: {exc}"
        ) from exc
    if not target.parent.is_dir():
        raise StorageError(f"transaction parent is not a directory: {target.parent}")
    _resolve_checked(target.parent, root, label="transaction parent")


Manifest = Tuple[Tuple[Tuple[str, str], ...], Tuple[str, ...]]


def _validated_manifest(
    root: Path,
    writes: Mapping[str, str],
    deletes: Sequence[str],
) -> Manifest:
    if not isinstance(writes, Mapping):
        raise StorageError("transaction writes must be a mapping")
    if isinstance(deletes, (str, bytes)) or not isinstance(deletes, Sequence):
        raise StorageError("transaction deletes must be a sequence of paths")

    write_paths = list(writes.keys())
    if any(not isinstance(path, str) for path in write_paths):
        raise StorageError("transaction write paths must be strings")
    if any(not isinstance(text, str) for text in writes.values()):
        raise StorageError("transaction write values must be strings")
    if any(not isinstance(path, str) for path in deletes):
        raise StorageError("transaction delete paths must be strings")
    if len(set(deletes)) != len(deletes):
        raise StorageError("transaction deletes contain duplicate paths")

    ordered_writes = tuple((path, writes[path]) for path in sorted(write_paths))
    ordered_deletes = tuple(sorted(deletes))
    write_set = {path for path, _ in ordered_writes}
    if write_set.intersection(ordered_deletes):
        raise StorageError("transaction cannot write and delete the same path")

    # Validate *all* destinations before a journal or a target is written.
    for path, _ in ordered_writes:
        _checked_target(root, path)
    for path in ordered_deletes:
        _checked_target(root, path)
    return ordered_writes, ordered_deletes


def _journal_path(root: Path) -> Path:
    return root / JOURNAL_NAME


def _assert_safe_journal(root: Path) -> Path:
    journal = _journal_path(root)
    if journal.is_symlink():
        raise StorageError("transaction.md must not be a symlink")
    if journal.exists() and journal.is_dir():
        raise StorageError("transaction.md must not be a directory")
    _resolve_checked(journal, root, label="transaction journal")
    return journal


def _journal_payload(manifest: Manifest) -> Dict[str, Any]:
    writes, deletes = manifest
    return {
        "schema": JOURNAL_SCHEMA,
        "transaction_id": uuid.uuid4().hex,
        "version": JOURNAL_VERSION,
        "writes": [{"path": path, "text": text} for path, text in writes],
        "deletes": list(deletes),
    }


def _manifest_from_journal(root: Path, payload: Any) -> Manifest:
    if not isinstance(payload, dict):
        raise StorageError("transaction journal must contain a JSON object")
    expected_keys = {"schema", "transaction_id", "version", "writes", "deletes"}
    if set(payload) != expected_keys:
        raise StorageError("transaction journal has an unexpected schema")
    if payload["schema"] != JOURNAL_SCHEMA or payload["version"] != JOURNAL_VERSION:
        raise StorageError("transaction journal has an unsupported schema")
    if not isinstance(payload["transaction_id"], str) or not payload["transaction_id"]:
        raise StorageError("transaction journal has no transaction id")
    raw_writes = payload["writes"]
    if not isinstance(raw_writes, list):
        raise StorageError("transaction journal writes must be a list")
    writes: Dict[str, str] = {}
    for item in raw_writes:
        if not isinstance(item, dict) or set(item) != {"path", "text"}:
            raise StorageError("transaction journal write entry is invalid")
        path = item["path"]
        text = item["text"]
        if not isinstance(path, str) or not isinstance(text, str):
            raise StorageError("transaction journal write entry is invalid")
        if path in writes:
            raise StorageError("transaction journal has duplicate write paths")
        writes[path] = text
    raw_deletes = payload["deletes"]
    if not isinstance(raw_deletes, list):
        raise StorageError("transaction journal deletes must be a list")
    return _validated_manifest(root, writes, raw_deletes)


def _write_target(root: Path, relative_path: str, text: str) -> None:
    target = _checked_target(root, relative_path)
    _ensure_safe_parent(root, target)
    # Check again after mkdir so a newly-created or raced component cannot escape.
    target = _checked_target(root, relative_path)
    atomic_write_text(target, text)


def _delete_target(root: Path, relative_path: str) -> None:
    target = _checked_target(root, relative_path)
    try:
        if target.exists() or target.is_symlink():
            target.unlink()
            _fsync_directory(target.parent)
    except OSError as exc:
        raise StorageError(f"cannot delete transaction target {target}: {exc}") from exc


def _roll_forward(
    root: Path,
    manifest: Manifest,
    *,
    fault: Optional[FaultCallback] = None,
) -> None:
    writes, deletes = manifest
    index = 0
    for relative_path, text in writes:
        _write_target(root, relative_path, text)
        index += 1
        if fault is not None:
            fault("after-target", index)
    for relative_path in deletes:
        _delete_target(root, relative_path)
        index += 1
        if fault is not None:
            fault("after-target", index)


def _remove_journal(root: Path) -> None:
    journal = _assert_safe_journal(root)
    try:
        if journal.exists():
            journal.unlink()
            _fsync_directory(root)
    except OSError as exc:
        raise StorageError(f"cannot remove transaction journal: {exc}") from exc


def recover(root: RecordPath) -> bool:
    """Idempotently roll a pending Markdown transaction forward, if one exists."""
    resolved_root = _resolve_root(root)
    journal = _assert_safe_journal(resolved_root)
    if not journal.exists():
        return False
    manifest = _manifest_from_journal(resolved_root, read_record(journal))
    _roll_forward(resolved_root, manifest)
    _remove_journal(resolved_root)
    return True


def transaction(
    root: RecordPath,
    writes: Mapping[str, str],
    deletes: Optional[Sequence[str]] = None,
    *,
    fault: Optional[FaultCallback] = None,
) -> None:
    """Durably journal, then deterministically apply validated writes and deletes.

    ``fault`` is only for deterministic crash tests.  It receives
    ``("after-target", index)`` after each completed target operation; an
    exception intentionally leaves ``transaction.md`` in place for ``recover``.
    """
    if fault is not None and not callable(fault):
        raise StorageError("transaction fault callback must be callable")
    requested_deletes: Sequence[str] = () if deletes is None else deletes
    resolved_root = _resolve_root(root)

    # Validate the new manifest before writing anything for it, then finish any
    # older journal while the caller's run lock is held.
    manifest = _validated_manifest(resolved_root, writes, requested_deletes)
    recover(resolved_root)
    manifest = _validated_manifest(resolved_root, writes, requested_deletes)

    journal = _assert_safe_journal(resolved_root)
    atomic_write_text(
        journal, dumps(_journal_payload(manifest), title="Workflow transaction")
    )
    _roll_forward(resolved_root, manifest, fault=fault)
    _remove_journal(resolved_root)
