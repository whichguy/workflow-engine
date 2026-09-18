#!/usr/bin/env python3
"""Demonstrate the limits of cooperative shared-workspace evidence.

The simulated host records handles; no model or external service is launched.
A succeeds after its verifier writes B's file. B's host then reports success
without B writing. File hashes cannot identify the actual producer. The v2
specification makes that limitation an explicit scoped NFR instead of hiding it
behind a generic two-step fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLI = ROOT / "skills/workflow/scripts/workflow"


def _definition() -> dict[str, Any]:
    goal = "Test whether evidence can prove which worker wrote a file"
    return {
        "version": 2,
        "name": "ownership-counterexample",
        "goal": goal,
        "specification": {
            "version": 1,
            "goal": goal,
            "deliverables": [
                {
                    "id": "D-A",
                    "description": "The A worker output.",
                    "requirements": ["FR-A"],
                },
                {
                    "id": "D-B",
                    "description": "The B worker output.",
                    "requirements": ["FR-B"],
                },
            ],
            "functional_requirements": [
                {
                    "id": "FR-A",
                    "description": "A produces a.txt.",
                    "acceptance": ["a.txt exists after A is accepted"],
                },
                {
                    "id": "FR-B",
                    "description": "B produces b.txt.",
                    "acceptance": ["b.txt exists after B is accepted"],
                },
            ],
            "nfrs": [
                {
                    "id": "NFR-provenance-boundary",
                    "description": "Output evidence alone must not be claimed as writer provenance.",
                    "acceptance": ["the boundary observation records whether B's file existed before B completed"],
                    "scope": "all",
                }
            ],
            "assumptions": [],
            "out_of_scope": ["OS-level write isolation or worker identity attestation."],
            "unresolved": [],
        },
        "steps": [
            {
                "id": "A",
                "kind": "agent",
                "needs": [],
                "prompt": "Write a.txt only",
                "outputs": ["a.txt"],
                "verify": [
                    [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; Path('b.txt').write_text('written-by-A-verifier')",
                    ]
                ],
                "contract": {
                    "role": "deliverable",
                    "deliverables": ["D-A"],
                    "requirements": ["FR-A"],
                    "verifies": ["FR-A"],
                    "ready_when": ["no prerequisite evidence is required"],
                    "done_when": ["a.txt is accepted as A's declared output"],
                },
            },
            {
                "id": "B",
                "kind": "agent",
                "needs": [],
                "prompt": "Write b.txt only",
                "outputs": ["b.txt"],
                "contract": {
                    "role": "deliverable",
                    "deliverables": ["D-B"],
                    "requirements": ["FR-B"],
                    "verifies": ["FR-B"],
                    "ready_when": ["no prerequisite evidence is required"],
                    "done_when": ["b.txt is accepted as B's declared output"],
                },
            },
            {
                "id": "verify-boundary",
                "kind": "command",
                "needs": ["A", "B"],
                "argv": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; assert Path('a.txt').is_file() and Path('b.txt').is_file(); Path('ownership-boundary.txt').write_text('observed\\n')",
                ],
                "outputs": ["ownership-boundary.txt"],
                "contract": {
                    "role": "verification",
                    "deliverables": ["D-A", "D-B"],
                    "requirements": [],
                    "verifies": ["NFR-provenance-boundary"],
                    "ready_when": ["both accepted worker outputs are available"],
                    "done_when": ["ownership-boundary.txt records the boundary observation"],
                    "shared_reason": "The limitation concerns the relationship between both claimed worker outputs.",
                },
            },
        ],
    }


def probe(cli: Path = DEFAULT_CLI) -> dict[str, Any]:
    cli = Path(cli).resolve()
    with tempfile.TemporaryDirectory(prefix="weave-ownership-probe-") as temporary:
        base = Path(temporary)
        workspace = base / "workspace"
        workspace.mkdir()
        run = base / "run"
        workflow = base / "workflow.json"
        workflow.write_text(json.dumps(_definition()), encoding="utf-8")
        trace: list[dict[str, Any]] = []

        def call(*arguments: object) -> dict[str, Any]:
            completed = subprocess.run(
                [sys.executable, str(cli), *(str(argument) for argument in arguments)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            packet = json.loads(completed.stdout)
            trace.append(
                {
                    "operation": str(arguments[0]),
                    "exit_code": completed.returncode,
                    "status": packet.get("status"),
                }
            )
            if completed.returncode:
                raise RuntimeError(packet)
            return packet

        call(
            "init",
            "--workflow",
            workflow,
            "--repo",
            workspace,
            "--run-dir",
            run,
            "--max-active",
            2,
            "--shared-workspace-disjoint",
        )
        claim = call("claim-ready", "--run-dir", run, "--limit", 2, "--request-id", "both")
        actions = {packet["step_id"]: packet for packet in claim["claimed_packets"]}
        for step, packet in actions.items():
            call("prepare-dispatch", "--run-dir", run, "--action", packet["action_id"])
            call(
                "dispatch",
                "--run-dir",
                run,
                "--action",
                packet["action_id"],
                "--handle",
                "SIMULATED-" + step,
            )
        (workspace / "a.txt").write_text("written-by-simulated-A")
        assert not (workspace / "b.txt").exists()
        response: dict[str, Any] | None = None
        for step in ("A", "B"):
            result = base / f"{step}-result.json"
            result.write_text(
                json.dumps({"status": "succeeded", "summary": "Simulated host success attestation"})
            )
            response = call(
                "complete", "--run-dir", run, "--action", actions[step]["action_id"], "--result", result
            )
        assert response is not None
        boundary_claim = call(
            "claim-ready", "--run-dir", run, "--limit", 1, "--request-id", "boundary"
        )
        boundary_packets = boundary_claim["claimed_packets"]
        assert len(boundary_packets) == 1 and boundary_packets[0]["step_id"] == "verify-boundary"
        terminal = call(
            "execute", "--run-dir", run, "--action", boundary_packets[0]["action_id"]
        )
        content = (workspace / "b.txt").read_text()
        return {
            "experiment": "shared-workspace-writer-identity",
            "assumption": "Disjoint declared paths and accepted receipts prove which native worker wrote each output.",
            "assumption_supported": False
            if terminal["status"] == "complete" and content == "written-by-A-verifier"
            else None,
            "observation": {
                "workflow_status": terminal["status"],
                "b_contents": content,
                "b_worker_wrote_output": False,
                "boundary_receipt": "ownership-boundary.txt",
            },
            "disposition": "Cooperative ownership only. Do not claim sandboxing or writer provenance; evaluate isolated per-agent workspaces before stronger claims.",
            "native_handles": "simulated explicitly; no native agents launched",
            "cleanup": "temporary workspace and run removed after observation",
            "runtime_sha256": hashlib.sha256((cli.parent / "workflow_core.py").read_bytes()).hexdigest(),
            "trace": trace,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, default=DEFAULT_CLI)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    value = probe(arguments.cli)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "experiment": value["experiment"],
                "assumption_supported": value["assumption_supported"],
                "output": str(arguments.output.resolve()),
            }
        )
    )


if __name__ == "__main__":
    main()
