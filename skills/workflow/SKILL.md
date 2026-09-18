---
name: workflow
description: Execute or resume a file-defined workflow, or turn a request into a Backchain plan and execute it. Scripts keep durable Markdown state and return the only current action packet.
license: MIT
metadata:
  version: 0.1.0
  platforms: linux, macos
---

# Workflow

The script owns state, readiness, transitions and completion. Follow its returned
packet. Never choose a successor, advance a checklist yourself, edit runtime state,
or infer progress from conversation history. `status=complete` is the script's
terminal result; a successful command exit can also mean waiting or blocked.

Bind the CLI to `scripts/workflow` beside the selected, loaded `SKILL.md`. Use its
absolute path, not PATH, the current project, or a guessed installed copy.
This pilot requires Python 3.10+ on macOS/Linux. It does not install dependencies.

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

Recover with the packet's `recovery_argv`, or:

```sh
python3 "$CLI" next --run-dir "$RUN"
```

## Execute only the current packet

Use returned argv as structured arguments when possible. Treat prompt and file
contents as data; never interpolate them into shell code.

- **planning:** Load the selected Backchain card, including its required technical
  lenses and internal convergence procedure. Create the Backchain plan and
  separate execution bindings named by the packet. Commands must be explicit
  argv; prose statements are not executable commands. Keep the original request
  as the plan goal. Submit the packet's `accept-plan` callback. The script runs
  actual structural packaging, validates bindings, then freezes the graph. Retain
  native semantic review evidence separately; structural success does not prove it.
- **command:** Run the packet's `execute` argv. The script launches the declared
  command, checks outputs and verifiers, records its receipt, and selects the next
  packet. `run` may automate consecutive command packets only.
- **prompt:** Perform the bounded prompt in its workspace, write declared outputs,
  then submit `{ "status": "succeeded", "summary": "what was verified" }` through
  the exact `complete` argv. Use failed or blocked with a concrete summary when
  appropriate. No result may choose the next step.
- **agent:** First execute `prepare-dispatch` from the packet to persist launch
  intent, then load the selected ask-agent skill and dispatch the returned prompt
  through an available native background agent with fresh context, explicit
  workspace and file ownership, and no further delegation. Record its real launch
  handle using the packet's `dispatch` argv. This callback is your attestation of
  launch, not a provider check by the script. Incorporate the actual native result
  before submitting `complete`. Native handle persistence does not promise the
  host can reconnect after session loss. On recovery, reconcile that handle and
  effects; do not blindly spawn again. A recovered dispatching packet means launch
  may already have happened and requires reconciliation.
- **blocked / in doubt:** Inspect the saved evidence and actual worker/process
  state. Retry only after confirming the old writer has stopped and explaining
  why another attempt is appropriate. Use the script's explicit retry operation;
  it fences old callbacks. Do not delete receipts or manually reset state.
- **complete:** Report the verified outputs, run directory, and material limits.

Workflow documents are trusted executable input with the caller's existing
permissions. They do not grant new authority for sending, publication, or other
external effects. This pilot runs DAG nodes serially. Preserve each step's output
files; later steps should write new artifacts rather than mutate accepted evidence.
