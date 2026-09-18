#!/usr/bin/env python3
"""Run bounded, reproducible black-box frontier graph experiments.

The experiment records a seed, compact graph, public CLI trace, runtime hashes,
requirement-contract IDs, and observed latency/packet-size metrics. It uses
temporary workspaces per case and makes no claim that a synthetic oracle control
mutated the real engine.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.graph_oracle import (  # noqa: E402 - root must precede the import
    BlackBoxWorkflowRunner,
    OracleViolation,
    loom_workflow,
    oracle_negative_controls,
    redundant_transitive_workflow,
    runtime_hashes,
    seeded_workflow,
)


def _capacities(value: str) -> tuple[int, ...]:
    try:
        capacities = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("capacities must be comma-separated integers") from exc
    if not capacities or any(capacity < 2 for capacity in capacities):
        raise argparse.ArgumentTypeError("every capacity must be at least 2 for v2 frontier runs")
    return capacities


def _graph_view(document: dict[str, Any]) -> dict[str, Any]:
    steps = [
        {"id": step["id"], "kind": step["kind"], "needs": step["needs"]}
        for step in document["steps"]
    ]
    specification = document.get("specification")
    specification_view: dict[str, Any] | None = None
    if isinstance(specification, dict):
        specification_view = {
            "version": specification.get("version"),
            "deliverables": [
                item.get("id")
                for item in specification.get("deliverables", [])
                if isinstance(item, dict)
            ],
            "functional_requirements": [
                item.get("id")
                for item in specification.get("functional_requirements", [])
                if isinstance(item, dict)
            ],
            "nfrs": [
                item.get("id")
                for item in specification.get("nfrs", [])
                if isinstance(item, dict)
            ],
        }
    return {
        "workflow_version": document.get("version"),
        "name": document["name"],
        "nodes": len(steps),
        "edges": sum(len(step["needs"]) for step in steps),
        "steps": steps,
        "specification": specification_view,
    }


def _case(
    *,
    label: str,
    seed: int | None,
    document: dict[str, Any],
    max_active: int,
    wall_seconds: float,
    transition_budget: int,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "label": label,
        "seed": seed,
        "max_active": max_active,
        "graph": _graph_view(document),
        "passed": False,
        "temporary_run_cleaned": False,
    }
    runner: BlackBoxWorkflowRunner | None = None
    temporary_path: Path | None = None
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix=f"weave-matrix-{label}-") as temporary:
            temporary_path = Path(temporary)
            runner = BlackBoxWorkflowRunner(
                root=ROOT,
                base=Path(temporary),
                document=document,
                max_active=max_active,
                label=label,
            )
            result = runner.run_to_completion(
                max_turns=200,
                max_transitions=transition_budget,
                wall_seconds=wall_seconds,
            )
            record.update(
                {
                    "passed": result.status == "complete",
                    "status": result.status,
                    "completed_steps": list(result.completed_steps),
                    "trace": result.trace,
                    # Metrics are observations only; this experiment sets no
                    # performance pass/fail threshold from them.
                    "metrics": {
                        "elapsed_ms": result.elapsed_ms,
                        "max_packet_bytes": result.max_packet_bytes,
                        "transitions": result.transitions,
                    },
                }
            )
    except subprocess.TimeoutExpired as exc:
        record.update(
            {
                "disposition": "subprocess-timeout",
                "error": str(exc),
                "trace": runner.trace if runner is not None else [],
            }
        )
    except OracleViolation as exc:
        record.update(
            {
                "disposition": "black-box-contract-violation",
                "error": str(exc),
                "trace": runner.trace if runner is not None else [],
            }
        )
    except Exception as exc:  # Keep generic harness failures honestly distinct.
        record.update(
            {
                "disposition": "harness-error-not-a-property-specific-result",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "trace": runner.trace if runner is not None else [],
            }
        )
    finally:
        # The context manager has already exited on both success and failure.
        # A setup error before it opened remains clearly recorded as false;
        # a created path must be absent before this report claims cleanup.
        record["temporary_run_cleaned"] = (
            temporary_path is not None and not temporary_path.exists()
        )
        record.setdefault("metrics", {})["wall_elapsed_ms"] = round(
            (time.monotonic() - started) * 1000
        )
    return record


def _build_cases(
    seeds: Iterable[int], capacities: tuple[int, ...]
) -> list[tuple[str, int | None, dict[str, Any], int]]:
    cases: list[tuple[str, int | None, dict[str, Any], int]] = [
        ("loom", None, loom_workflow(), 3),
        ("redundant-transitive", None, redundant_transitive_workflow(), 5),
    ]
    for index, seed in enumerate(seeds):
        cases.append((f"seed-{seed}", seed, seeded_workflow(seed), capacities[index % len(capacities)]))
    return cases


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=20, help="number of deterministic generated DAGs")
    parser.add_argument("--seed-start", type=int, default=0, help="first generated graph seed")
    parser.add_argument(
        "--capacities",
        type=_capacities,
        default=(2, 3, 5),
        help="comma-separated v2 max-active values (default: 2,3,5)",
    )
    parser.add_argument(
        "--wall-seconds",
        type=float,
        default=45,
        help="per-graph wall-clock deadline; a metric boundary, not a performance target",
    )
    parser.add_argument(
        "--transition-budget",
        type=int,
        default=300,
        help="maximum public CLI transitions per graph",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runs/graph-matrix.json"),
        help="JSON report path, relative to this repository when not absolute",
    )
    arguments = parser.parse_args(argv)
    if arguments.seeds < 0:
        parser.error("--seeds must be nonnegative")
    if arguments.wall_seconds <= 0:
        parser.error("--wall-seconds must be positive")
    if arguments.transition_budget <= 0:
        parser.error("--transition-budget must be positive")
    return arguments


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    before_hashes = runtime_hashes(ROOT)
    cases = _build_cases(
        range(arguments.seed_start, arguments.seed_start + arguments.seeds), arguments.capacities
    )
    records = [
        _case(
            label=label,
            seed=seed,
            document=document,
            max_active=max_active,
            wall_seconds=arguments.wall_seconds,
            transition_budget=arguments.transition_budget,
        )
        for label, seed, document, max_active in cases
    ]
    after_hashes = runtime_hashes(ROOT)
    controls = oracle_negative_controls()
    controls_passed = bool(controls) and all(
        control.get("rejected") is True and control.get("runtime_mutated") is False
        for control in controls
    )
    source_unchanged = before_hashes == after_hashes
    passed = (
        all(record.get("passed") for record in records)
        and source_unchanged
        and controls_passed
    )
    report = {
        "schema": "weave-graph-matrix-v1",
        "runtime_hashes_before": before_hashes,
        "runtime_hashes_after": after_hashes,
        "runtime_unchanged_during_matrix": source_unchanged,
        "limits": {
            "per_graph_wall_seconds": arguments.wall_seconds,
            "per_graph_transition_budget": arguments.transition_budget,
            "subprocess_timeout_seconds": 15,
        },
        "seeds": {"start": arguments.seed_start, "count": arguments.seeds},
        "capacities": list(arguments.capacities),
        "negative_controls": controls,
        "negative_controls_passed": controls_passed,
        "cases": records,
        "passed": passed,
    }
    output = arguments.output if arguments.output.is_absolute() else ROOT / arguments.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "cases": len(records), "output": str(output)}))
    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
