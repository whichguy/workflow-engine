# Prototype implementation contract

Working name: Weave; repository: workflow-engine. This is a local extraction pilot, not a migrated
ShipLoop release. Files are authoritative; scripts control every transition.

This document specifies the original serial v1 execution contract. It remains
the default and applies to existing runs. Opt-in concurrent native-agent execution
uses the separate [v2 contract](CONCURRENCY.md); the frozen workflow document
format remains version 1. The checkout shorthand `./weave` forwards to the CLI.

## Shared source layout and ownership

- `skills/workflow/scripts/workflow`: Python CLI (core implementer).
- `workflow_core.py`: kernel (core implementer).
- `store.py`: extracted ShipLoop durable Markdown store (parent).
- `adapters.py`: Backchain compilation and Git worktree creation (adapter implementer).
- `tests/test_engine.py`: CLI behavior tests (test implementer).
- `tests/test_adapters.py`: adapter tests (adapter implementer).
- README, skill, examples, evidence, architecture: parent.

All runtime modules are package-local siblings. Use standard-library Python 3.10+.
All CLI commands emit one JSON packet to stdout. Errors emit JSON and nonzero exit.
Run directory paths and packet argv are absolute. CLI flags follow the command.

## Frozen workflow document v1

JSON or Markdown with exactly one `workflow-state` JSON fence:

```json
{"version":1,"name":"example","goal":"Make a verified report","steps":[
 {"id":"write","kind":"command","needs":[],"argv":["python3","-c","from pathlib import Path; Path('report.txt').write_text('ready')"],"outputs":["report.txt"]},
 {"id":"review","kind":"agent","needs":["write"],"prompt":"Review report.txt; write review.txt.","outputs":["review.txt"],"verify":[["python3","-c","from pathlib import Path; assert Path('review.txt').read_text().strip()"]]}
]}
```

Required: version=1, name, goal, nonempty steps; each step id, kind. Optional
needs defaults to the prior step for serialized lists; explicit [] permits a DAG
root. Kinds: command (nonempty argv), prompt (prompt), agent (prompt).
Optional outputs (relative regular-file paths), verify (list of argv arrays),
timeout_seconds (positive number, finite; default 60), produces (string array).
Strict unknown-field rejection. Reject cycles, missing/duplicate IDs, unsafe
output paths and duplicate/nested output producers. Accepted outputs are immutable
evidence files. Prompt/agent steps require at least one output or verifier.
Output component comparisons use NFC normalization and case folding; existing
symlink components, nonregular targets and hardlinked targets fail preflight.
Commands may use their real exit status and captured log as minimum evidence.
Steps execute in deterministic topological order, one at a time.
No shell interpolation; explicit shell invocation is an authored trusted command.
Workflow files are executable input, not a sandbox.

## CLI surface

- `init --workflow FILE --run-dir DIR --repo DIR [--isolate]`: freeze validated
  definition and repo identity; issue first packet. Init never overwrites a run.
- `init --prompt-file FILE --backchain-root DIR --run-dir DIR --repo DIR [--isolate]`:
  preserve exact request, persist planning action, issue planner packet.
- `next --run-dir DIR`: rehydrate and render same action; never advance work.
- `accept-plan --run-dir DIR --action ID --plan FILE --bindings FILE`:
  call selected Backchain's real package-only validator; freeze compiled workflow
  and planner provenance; commit execution cursor. Reject stale action/mismatched
  goal/unresolved or incompatible plans. Original prompt is retained separately.
- `execute --run-dir DIR --action ID`: execute current command in recorded
  workspace; persist intent before launch; capture log; verify outputs/checks;
  accept receipt and select next packet only after success.
- `run --run-dir DIR`: execute ready command steps until complete or a non-command
  packet/block is reached. Never invoke a model or automatically retry.
- `prepare-dispatch --run-dir DIR --action ID`: durably mark launch intent before
  native spawning. Recovery of this intent requires reconciliation, not relaunch.
- `block --run-dir DIR --action ID --reason TEXT`: record a missing capability
  for a ready, undispatched agent without inventing a handle. Same-reason replay
  is harmless; launch intent already persisted requires reconciliation instead.
- `dispatch --run-dir DIR --action ID --handle TEXT`: persist native launch
  receipt for agent action after host-native spawn confirms launch; repeat same
  handle is harmless; conflicting handle fails. Does not launch the agent.
  This is a trusted-host attestation, not a provider-verifiable launch check.
- `complete --run-dir DIR --action ID --result FILE`: accept result object
  `{status:"succeeded",summary:"..."}` (or failed/blocked with summary); no claimed
  next-step field is allowed. For agent, require recorded handle. Kernel verifies
  declared output files and check commands. Hash/store receipt and evidence;
  identical callback replay is harmless, conflicting replay fails. A command
  cannot use complete to skip execution. Failed/blocked results park the action.
- `retry --run-dir DIR --action ID --reason TEXT --confirmed-stopped`:
  explicit reconciliation for failed/blocked/interrupted/dispatched action;
  record reason, fence old action, preserve artifacts, issue new action identity.
  Cannot prove a native worker stopped; flag is caller attestation, never timeout.
  Capture output preimages at issuance; accepting a declared output requires new
  or changed file identity/content/mtime relative to that attempt. Old files alone
  cannot satisfy a new attempt. This does not replace semantic verification.

Every packet includes run_id, run_dir, original goal, status, action_id (if active),
kind, step_id, workspace, prompt/argv, declared outputs, direct dependency receipt
paths and hashes, `recovery_argv` for read-only `next`, and exact `next_argv` for
the current recommended action plus allowed operation argv templates.
Agent packet tells host to use selected ask-agent with native fresh-context spawn,
explicit workspace/ownership, no nested delegation, then record actual handle.
Planning packet instructs loading the selected Backchain skill, producing its
plan schema and separate execution bindings, then invoking exact accept-plan.

## File authority and recovery

`state.md` is the single authoritative execution record, using extracted store.py
`workflow-state` fences. It includes frozen normalized workflow, digest, request,
repo/workspace binding, current action, completions, attempts, dispatch and retry
history. Receipt Markdown files and `packet.md` are written in the same durable
store transaction. Packet is a derived view, never a second authority.
Hold a local advisory `fcntl.flock` for mutations and recovery; never hold only an
age-based claim. All state and definition hashes are checked when loading.
Persist command intent before launch, then save PID/PGID, launch time and argv/cwd
identity after Popen for diagnosis. A process crash or uncertain timeout leaves
an in-doubt action and never automatically reruns it. Kernel and verification
commands run in process groups, with bounded timeouts and stdout/stderr to files.
Successful prompt/agent callbacks persist `verifying`, callback identity and
per-check intent before launching verifiers. A separate execution lock binds its
owner action while the run lock remains available to cold reads. An interrupted
owner parks that action `in_doubt`; a nonzero verifier parks it `failed`. Callback
replay cannot restart uncertain checks. This hardening also applies to v1 runs.
Accepted evidence is immutable: detect changed direct output hashes on hydration.
This is local single-host trusted-user storage, not a hostile multi-user sandbox.

## Adapter function contract

`compile_backchain(backchain_root: Path, plan: dict, bindings: dict,
                   staging: Path) -> tuple[dict, dict]`

Backchain root is an explicit selected package/source location with
`harness/run-prompt.sh` and `schema/plan.schema.json` available (source checkout
requirement must be documented). Run real package-only CLI into a fresh staging
directory, parse validation/handoff/packaged outputs, reject unresolved plans and
completionStatus != complete. Bindings map every plan step ID to `{kind, argv or
prompt, outputs, verify, timeout_seconds}`. Preserve Backchain step ID, derives
needs from input supplier IDs, carries produces, uses plan.goal as workflow goal.
No executable text inferred from statements. Initial facts require attestation
bindings at reserved key `_initial_evidence`, a mapping initial fact to absolute
regular evidence file; copy/hash into staging and record provenance. Missing
consumed initial facts block compilation. Returns workflow version/name/goal/steps
plus provenance (selected tool digest, actual validation artifacts/digests,
initial evidence). Do not modify input plan or source checkout.

`create_workspace(repo: Path, run_dir: Path) -> dict`

Optional clean-Git pilot only: verify repo is actual Git root, clean (including
untracked inputs), has HEAD, and run_dir is outside repo; create detached worktree
at run_dir/workspace from pinned HEAD. Return source_repo, workspace, base_commit,
isolation="git-worktree". Fail on dirty source; preserve all existing paths and
worktrees. No merge, source-return, cleanup, or per-step branch concurrency.

## Exit and validation boundaries

Successful JSON packet emission exits 0 including waiting/blocked packets;
protocol/validation errors exit nonzero. Completion is status=complete, not exit 0.
Only all accepted and verified steps complete a run. No parallel execution,
dynamic graph mutation, nested child execution, automated merges, or whole-ShipLoop
adoption is claimed by this pilot. Those require the extraction plan and parity
gates. The durable store is genuinely extracted; the kernel is a narrow new
implementation of the observed packet contract.
