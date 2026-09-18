# Workflow engine prototype

Files hold durable state. Scripts alone select and validate transitions. The skill
executes returned packets and submits evidence; it never chooses successors.

Python 3.10+ standard library; macOS/Linux. The source skill is self-contained in
`skills/workflow/`. No automatic installation or host configuration.
`plugins/workflow/` is generated: edit the canonical skill, then run
`python3 scripts/sync-plugin-view.py`; verify with `--check`. Dependencies remain
separately selected skills and are never copied into this package.
Run tests with `python3 -m unittest discover -s tests -v`.

Keep workflow policy out of the kernel. Serial execution remains the default.
The explicit v2 shared-workspace frontier requires both `--max-active N` where
`N > 1` and `--shared-workspace-disjoint`: only agent actions with exclusive,
declared output leases may coexist; command, prompt, and planning actions remain
globally exclusive. Native delegation uses host tools through ask-agent, never a
hidden model subprocess. Backchain planning is separate from execution success.
Unknown outcomes require reconciliation, not automatic replay. Do not auto-merge
or delete worktrees. Do not edit the sibling ShipLoop or Backchain repositories.
