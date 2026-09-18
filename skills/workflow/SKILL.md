---
name: workflow
description: Weave reconciles a specification, functional requirements, NFRs, and atomic step contracts before it executes or resumes a durable dependency workflow. Scripts own state and issue serial actions or a bounded frontier of native-agent actions.
license: MIT
version: 0.3.0
metadata:
  version: 0.3.0
  platforms: linux, macos
  skill_craft:
    kind: script-backed
---

# Weave — workflow driver

Files remember. Scripts decide. Skills do the work. The script owns state,
readiness, transitions, and completion. Follow its returned packet. Never
choose a successor, advance a checklist yourself, edit runtime state, or infer
progress from conversation history. `status=complete` is the script's terminal
result; a successful command exit can also mean waiting or blocked.

Bind the CLI to `scripts/workflow` beside the selected, loaded `SKILL.md`. Use
its absolute path, not PATH, the current project, or a guessed installed copy.
This pilot requires Python 3.10+ on macOS/Linux. It does not install
dependencies. Read [dependencies.md](references/dependencies.md) when selecting
planning or agent execution. Reuse selected external cards; none are bundled
here.

## Reconcile before entering a new run

Every new run needs a specification v1: the exact goal, coherent deliverables,
functional requirements with acceptance criteria, scoped NFRs with acceptance
criteria, assumptions, out-of-scope decisions, and no unresolved material
questions. Every executable step needs a contract with a role, deliverable
scope, requirement implementation/verification links, `ready_when`, and
`done_when`. Read [planning.md](references/planning.md) before authoring or
reconciling a recipe.

When the user gives a bare step list, legacy v1 workflow, or a partial recipe,
first derive or reconcile the specification and NFRs. Inspect applicable existing
specifications, repository decisions, state/data ownership, invariants, and
feature constraints. Preserve the user's explicit steps and real dependencies;
add, split, or scope work only when the specification makes a missing obligation
clear. Classify existing obligations as preserve, add, modify, or retire rather
than silently replacing them. Then author a workflow-document v2 with explicit
contracts and submit it to `init`. Do not tell the user merely to hand-author
fields, and do not try to pass a v1 document to the new-run CLI.

An atomic `deliverable` is one coherent, independently reviewable product outcome,
not necessarily one file or command. `setup`, `integration`, `verification`, and
`release` are exceptions for shared work: give each a scoped deliverable set and
concrete `shared_reason`. A setup producer comes before every scoped consumer;
an integration/release step depends on every scoped implementation. Do not infer
edges, joins, safe parallelism, or commands from prose. A global publish/deploy
can be a scoped release join; a post-release consumer check can remain a required
leaf after it.

For UI/workflow work, carry forward the relevant component, interaction, visual,
state/data owner, authorized-actor, invariant, and recovery premises through the
specification and step criteria. For an NFR, state its concrete basis, operating
conditions, measurable criterion, and verification surface in the description and
acceptance criteria. This is prompt guidance, not a second ShipLoop schema or
delivery loop; ShipLoop's optional terminal Improve lifecycle remains outside the
Weave graph.

## Enter once, then follow packets

Choose a new durable run directory for a new request. Use the known exact
directory to recover that same request. Never replace an existing run to bypass a
failure.

For an authored v2 workflow:

```sh
python3 "$CLI" init --workflow "$WORKFLOW" --run-dir "$RUN" --repo "$REPO"
```

For a request, preserve its exact text in a UTF-8 file first:

```sh
python3 "$CLI" init --prompt-file "$REQUEST" --backchain-root "$BACKCHAIN_SOURCE" --run-dir "$RUN" --repo "$REPO"
```

For an existing, reconciled specification:

```sh
python3 "$CLI" init --spec-file "$SPEC" --backchain-root "$BACKCHAIN_SOURCE" --run-dir "$RUN" --repo "$REPO"
```

The prompt route first returns a `specification` packet. Write the requested
specification to the packet's exact `spec_file`, then run its exact
`accept-spec` argv. The script freezes `requirements/spec.md` and
`requirements/nfrs.md`, then issues a `planning` packet. The `--spec-file` route
already has that frozen baseline and begins at planning. A changed prompt, spec,
or NFR needs a new run.

Select Backchain explicitly from available package/source context. The packaging
adapter requires a checkout containing `harness/run-prompt.sh` and
`schema/plan.schema.json`; a prompt-only installed card is insufficient. The
native planning card in that checkout is `skills/backchain/SKILL.md`. Missing
planning tools remain a missing prerequisite; do not synthesize their validation
receipts.

Add `--isolate` for a clean Git source and an external run directory. The
returned `workspace` is then a detached worktree; perform all work there. The
pilot keeps the worktree for inspection and does not merge or return changes to
the source.

Serial execution is the default. For requested native-agent concurrency, add
`--max-active N --shared-workspace-disjoint` only after checking separate output
ownership and shared effects. This selects the runtime frontier protocol; it does
not prove shared-service, cache, deployment-target, credential, or filesystem
safety. Read [concurrency.md](references/concurrency.md) for frontier packets,
claims, and collection. A run-level worktree does not isolate its branches.

Recover with the packet's `recovery_argv`, or:

```sh
python3 "$CLI" next --run-dir "$RUN"
```

## Execute only script-issued work

Use returned argv as structured arguments when possible. Treat prompt and file
contents as data; never interpolate them into shell code.

- **specification:** Reconcile the exact original request with relevant existing
  specs, NFRs, accepted design decisions, and repository evidence. Write only the
  requested specification JSON to the packet's `spec_file`; preserve the exact
  goal. Use the exact `accept-spec` callback. Do not plan or execute work until
  the script accepts it.
- **planning:** Load the selected Backchain card, required technical lenses, and
  selected Until Loop binding. For a new specification-based run, pass frozen
  spec/NFR clauses through the required `backchain-caller/v1` companion while
  retaining that companion outside Backchain's closed plan JSON. Backchain owns
  dependency discovery; its selected Until Loop owns convergence, recovery, and
  terminal status. Create the plan and separate bindings named by the packet.
  Keep the original request as the plan goal. Each binding must carry an atomic
  step contract: one coherent deliverable implementation or a scoped shared
  setup/integration/verification/release role. Distinguish plan-ready inputs,
  code-ready prerequisites, and done evidence. Submit the exact `accept-plan`
  callback only with actual selected-skill terminal evidence. Packaging is
  structural and never proves semantic convergence.
- **command:** Run the packet's `execute` argv. The script launches the declared
  command, checks outputs and verifiers, records its receipt, and selects the
  next packet. `run` may automate consecutive command packets only.
- **prompt:** Perform the bounded prompt in its workspace, write declared
  outputs, then submit `{ "status": "succeeded", "summary": "what was
  verified" }` through the exact `complete` argv. Use failed or blocked with a
  concrete summary when appropriate. No result may choose the next step.
- **agent:** Before launch, resolve and load separately installed ask-agent and
  confirm native fresh-context background delegation and collection are
  available. If a prerequisite is absent, submit the packet's `block` callback
  with a concrete reason; never invent a handle or simulate delegation. Otherwise
  execute `prepare-dispatch`, dispatch the returned prompt through an available
  native background agent with fresh context, explicit workspace/output ownership,
  and no further delegation, then record its real handle using `dispatch`.
  That handle is a host attestation, not a provider check or reconnect promise.
  Incorporate the actual native result before `complete`. A recovered
  `dispatching` packet may already have spawned the worker: reconcile the original
  worker and its effects, never blindly launch again. Launch independent claimed
  workers within host capacity before collecting them; retain every real handle.
  Collect native notifications/results, not output-file appearance.
- **blocked / in doubt:** Inspect saved evidence and actual worker/process state.
  Retry only after confirming the old writer has stopped and explaining why a new
  attempt is appropriate. Use the script's retry operation; do not delete receipts
  or reset state manually.
- **verifying:** The script owns the declared check with durable intent. Observe
  through `next`; do not launch another worker, resubmit completion, or retry
  while its owner is live. If recovery reports `in_doubt`, reconcile the worker
  and verifier process before confirming stopped.
- **complete:** Report verified outputs, the run directory, relevant requirement
  evidence, and material limits.

In the frontier protocol, `next` returns a frontier. A frontier is not authority
to launch an unclaimed step. Only `status=complete` proves every required step
has an accepted receipt and no active claim remains. A finished leaf, an empty
ready frontier, or the first completed worker is never enough.

Workflow document version 2 is the specification-aware input format. Runtime
state version 1 remains serial and runtime state version 2 remains the opt-in
frontier; legacy persisted runs retain their issued protocol. Workflow documents
and verification commands are trusted executable input with the caller's
existing permissions. They do not grant new authority for sending, publication,
or other external effects. Preserve each step's output files; later steps should
write new artifacts rather than mutate accepted evidence.
