# Workflow engine prototype

Files hold durable state. Scripts alone select and validate transitions. The skill
executes returned packets and submits evidence; it never chooses successors.

Python 3.10+ standard library; macOS/Linux. The source skill is self-contained in
`skills/workflow/`. No automatic installation, publication, or host configuration.
Run tests with `python3 -m unittest discover -s tests -v`.

Keep workflow policy out of the kernel. Serial execution is intentional for this
pilot. Native delegation uses host tools through ask-agent, never a hidden model
subprocess. Backchain planning is separate from execution success. Unknown
outcomes require reconciliation, not automatic replay. Do not auto-merge or delete
worktrees. Do not edit the sibling ShipLoop or Backchain repositories.
