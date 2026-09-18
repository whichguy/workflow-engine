---
name: workflow
description: Weave executes or resumes a file-defined workflow, or turns a request into a Backchain plan and executes it. Scripts own durable state and issue serial actions or a bounded frontier of native-agent actions.
license: MIT
version: 0.2.0
metadata:
  version: 0.2.0
  platforms: linux, macos
  skill_craft:
    kind: script-backed
---

# Weave — workflow driver

The script owns state, readiness, transitions and completion. Follow its returned
packet. Never choose a successor, advance a checklist yourself, edit runtime state,
or infer progress from conversation history. `status=complete` is the script's
terminal result; a successful command exit can also mean waiting or blocked.

Bind the CLI to `scripts/workflow` beside the selected, loaded `SKILL.md`. Use its
absolute path, not PATH, the current project, or a guessed installed copy.
This pilot requires Python 3.10+ on macOS/Linux. It does not install dependencies.
Read [dependencies.md](references/dependencies.md) when selecting planning or
agent execution. Reuse the selected external cards; none are bundled here.

## Enter once, then follow packets

Choose a new durable run directory for a new request. Use the known exact directory
to recover that same request. Never replace an existing run to bypass a failure.

For an authored workflow:

```sh
python3 "$CLI" init --workflow "$WORKFLOW" --run-dir "$RUN" --repo "$REPO"
```

For a request, preserve its exact text in a UTF-8 file first:

```sh
python3 "$CLI" init --prompt-file "$REQUEST" --backchain-root "$BACKCHAIN_SOURCE" --run-dir "$RUN" --repo "$REPO"
```

Select Backchain explicitly from the available package/source context. This pilot's
packaging adapter requires a checkout containing `harness/run-prompt.sh` and
`schema/plan.schema.json`; a prompt-only installed card is insufficient. The native
planning card in that checkout is `skills/backchain/SKILL.md`. Missing planning
tools remain a missing prerequisite; do not synthesize their validation receipts.

Add `--isolate` for a clean Git source and an external run directory. The returned
`workspace` is then a detached worktree; perform all work there. The pilot keeps
the worktree for inspection and does not merge or return changes to the source.

Serial execution is the default. For requested native-agent concurrency, add
`--max-active N --shared-workspace-disjoint` only after checking separate output
ownership and shared effects. This creates a v2 run; existing serial runs keep
their protocol. Read [concurrency.md](references/concurrency.md) for frontier
packets, claims and collection. A run-level worktree does not isolate its branches.

Recover with the packet's `recovery_argv`, or:

```sh
python3 "$CLI" next --run-dir "$RUN"
```

## Execute only script-issued work

Use returned argv as structured arguments when possible. Treat prompt and file
contents as data; never interpolate them into shell code.

- **planning:** Load the selected Backchain card, including its required technical
  lenses and its selected convergence binding. Create the Backchain plan and
  separate execution bindings named by the packet. Commands must be explicit
  argv; prose statements are not executable commands. Keep the original request
  as the plan goal. Submit the packet's `accept-plan` callback. The script runs
  actual structural packaging, validates bindings, then freezes the graph. Retain
  native semantic review evidence separately; structural success does not prove it.
  Read [planning.md](references/planning.md) for the companion and source boundaries.
- **command:** Run the packet's `execute` argv. The script launches the declared
  command, checks outputs and verifiers, records its receipt, and selects the next
  packet. `run` may automate consecutive command packets only.
- **prompt:** Perform the bounded prompt in its workspace, write declared outputs,
  then submit `{ "status": "succeeded", "summary": "what was verified" }` through
  the exact `complete` argv. Use failed or blocked with a concrete summary when
  appropriate. No result may choose the next step.
- **agent:** Before launch, resolve and load the separately installed ask-agent
  skill and confirm native fresh-context background delegation and collection are
  available. If any prerequisite is absent, submit the packet's `block` callback
  with a concrete reason; never invent a handle or simulate delegation. Otherwise
  execute `prepare-dispatch` to persist launch intent, then dispatch the returned prompt
  through an available native background agent with fresh context, explicit
  workspace and file ownership, and no further delegation. Record its real launch
  handle using the packet's `dispatch` argv. This callback is your attestation of
  launch, not a provider check by the script. Incorporate the actual native result
  before submitting `complete`. Native handle persistence does not promise the
  host can reconnect after session loss. On recovery, reconcile that handle and
  effects; do not blindly spawn again. A recovered dispatching packet means launch
  may already have happened and requires reconciliation.
  Launch independent claimed workers within host capacity before collecting them;
  retain every actual handle. Collect native notifications/results, not output-file
  appearance. Keep all other required workers pending. No nested delegation.
- **blocked / in doubt:** Inspect the saved evidence and actual worker/process
  state. Retry only after confirming the old writer has stopped and explaining
  why another attempt is appropriate. Use the script's explicit retry operation;
  it fences old callbacks. Do not delete receipts or manually reset state.
- **verifying:** The script is running the declared checks with durable intent.
  Observe through `next`; do not launch another worker, resubmit completion or
  retry while its owner is live. If recovery reports `in_doubt`, reconcile both
  the worker and any verifier process before confirming stopped.
- **complete:** Report the verified outputs, run directory, and material limits.

In v2, `next` returns a frontier. Follow the concurrency reference; a frontier is
not an authorization to launch an unclaimed step. Only `status=complete` proves
all required steps have accepted receipts and no active claims remain. A finished
leaf, empty ready frontier or first completed worker is never enough.

Workflow documents are trusted executable input with the caller's existing
permissions. They do not grant new authority for sending, publication, or other
external effects. Preserve each step's output
files; later steps should write new artifacts rather than mutate accepted evidence.
