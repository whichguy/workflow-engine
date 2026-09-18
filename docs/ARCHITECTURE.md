# A generic workflow facility below ShipLoop

```mermaid
flowchart LR
  A[Request or workflow file] --> B[Script loads durable run]
  B --> C[Current action packet]
  C --> D[Thin skill and native agents]
  D --> E[Artifacts and callback]
  E --> F[Script verifies and commits]
  F --> B
  F --> G[Verified completion]
```

**Decision: pilot a small extracted runtime in a sibling repository.** The key
abstraction is a durable action protocol. An agent supplies judgment and work;
the script owns the authoritative cursor, action identity, readiness, acceptance
and next transition. A step file and a single prompt are two entry points to the
same runtime. The prompt entry first issues a planning action; it does not give
the driver skill a second orchestration loop.

## What is already present

The investigation used the current local worktrees on 2026-09-18. ShipLoop source
was dirty; `docs/PROVENANCE.json` records the exact extracted store bytes and Git
HEAD. These observations are not a release or installed-consumer claim.

| Component | Existing responsibility | Place in the generalized design |
| --- | --- | --- |
| ShipLoop store | Markdown records and crash-recoverable multi-file transactions | Reused directly, with generic names and recorded provenance |
| ShipLoop navigator | Action identity, cursor, callbacks, parked child ownership | Packet/state model; generic kernel implements a narrow serial contract |
| ShipLoop SDLC | Discovery, specification, testing, review, delivery and acceptance | Consumer workflow/profile, retained outside the kernel |
| Backchain | Forward draft, dependency discovery, backward chaining, semantic convergence, structural packaging | Planner produces an immutable candidate graph |
| Backchain graph-navigator experiment | Claims, direct-supplier readiness, token-bound receipts | Prior implementation evidence for dispatch and reconciliation rules |
| ask-agent | Native fresh-context delegation and result collection | Thin skill-level dispatch; not a subprocess launcher |
| Improve / Until Loop | Its own review iterations and convergence | Independently owned child engine; a future adapter parks the parent |

Decisive source locations:

- [shiploop_store.py - transaction and recover: reusable Markdown storage](/Users/dadleet/src/skill-craft/skills/shiploop/scripts/shiploop_store.py:419).
- [shiploop_navigator.py - cursor: one effective current action](/Users/dadleet/src/skill-craft/skills/shiploop/scripts/shiploop_navigator.py:218).
- [shiploop_navigator_v3_prompts.py - graph: domain-specific SDLC stages](/Users/dadleet/src/skill-craft/skills/shiploop/scripts/shiploop_navigator_v3_prompts.py:12).
- [graph-navigator README - CLI: claims, receipts and recovery boundary](/Users/dadleet/src/backchain/experiments/graph-navigator/README.md:40).
- [Backchain SKILL.md - native procedure: internal semantic convergence](/Users/dadleet/src/backchain/skills/backchain/SKILL.md:51).
- [run-prompt.sh - packaging: deterministic graph artifact bundle](/Users/dadleet/src/backchain/harness/run-prompt.sh:434).
- [ask-agent SKILL.md - delegation: native tools and no script launcher](/Users/dadleet/src/skill-craft/skills/ask-agent/SKILL.md:19).
- [backchain-planning.md - embedded ownership: current ShipLoop integration](/Users/dadleet/src/skill-craft/skills/shiploop/references/backchain-planning.md:5).

## Data and authority

The authored document contains intent, explicit dependencies, typed executors and
checks. It is frozen into `state.md` at initialization or plan acceptance. The
source document can later change without changing that run. A change to an active
graph needs a future explicit migration contract; editing the file cannot silently
rewrite running or completed work.

`state.md` is machine-readable Markdown with one JSON fence. It owns the workflow,
workspace, current attempt, native handle, receipts and outcomes. `packet.md` is a
derived handoff. The kernel uses a local run lock and ShipLoop's write-ahead
transaction store so state and its accompanying receipts recover together.

Each accepted step releases only dependants whose prerequisites are satisfied.
The initial pilot chooses one ready node deterministically, so an ordinary list
and a dependency DAG share the same executor. Backchain's parallel groups describe
dependencies; they do not establish safe shared-resource concurrency.

Commands are argv arrays. Prompt steps run in the current host; agent steps use
the host's native delegation tools through ask-agent. A successful result is a
candidate receipt: the script still checks declared output files and verifiers.
Hashes prove artifact identity, not that an essay or code change is good. Semantic
review belongs in explicit prompt/review steps with suitable acceptance evidence.
For coding workflows, declare an immutable result report, test log or source
snapshot as the output evidence. The working source may evolve in later steps;
declaring that mutable source file itself as immutable evidence would deliberately
make a later edit invalidate the earlier receipt.

The kernel stores command intent before process launch. If an effect could have
happened before its completion receipt was committed, recovery does not claim
exactly-once execution. It parks the action for reconciliation. A retry uses a new
attempt identity after the caller confirms that the old writer is stopped.

## Concrete trace

For a workflow that generates numbers, asks a native agent to summarize them, and
verifies the summary, initialization freezes three nodes and issues the generate
action. `execute` writes the numbers and commits its receipt. The script then
issues the summarize packet. The skill dispatches that prompt and records the real
native handle. A successful callback with a missing summary file does not release
verification. Once the output and checks pass, the script persists the receipt and
issues the verify command. Only its success makes the run complete.

This works after a fresh process because the cursor, prompt, workspace and evidence
are files. The conversation supplies no hidden execution state. The important
boundary is a native launch before its handle was recorded: the host must reconcile
the original task rather than interpret the unchanged packet as permission to
launch another writer.

## Why not adopt a broader engine immediately?

| Candidate | Benefit and fit | Cost and contrary evidence | Decision |
| --- | --- | --- | --- |
| Extracted local packet runtime | Preserves Markdown recovery, native skills and script-owned transitions | Maintains a small runtime; must prove effect/replay boundaries | Pilot |
| Existing local resumable-script | Already has journals, routing, child frames, in-doubt effects | Broader interpreter and model-caller ownership differ from this host-driven protocol; no Backchain/worktree adapter | Reuse concepts; defer importing its engine |
| LangGraph | Established checkpointed graph execution | New framework/model integration and persistence choice; migration still must resolve native task and external-effect recovery | Defer |
| Temporal | Durable execution, history and activity boundaries | Service/SDK deployment and a different programming model exceed this local pilot | Defer |
| Serverless Workflow DSL | Declarative sequences, forks and routing | Broad specification/runtime adds machinery without proving this packet protocol | Use as comparative prior art |

Primary-source research supports the persistence and effect boundaries, not a
claim that one framework automatically solves this workspace's problem:
[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence),
[Temporal architecture](https://github.com/temporalio/temporal/blob/main/docs/architecture/README.md),
and [Serverless Workflow task flow](https://serverlessworkflow-specification.mintlify.app/core/task-flow).
Temporal's separation of deterministic workflow code from idempotent or non-retryable
activities is particularly relevant to uncertain callbacks. The local
[resumable-script SKILL.md - replay: journal and in-doubt execution](/Users/dadleet/src/nbq-gated-eval/skills/resumable-script/SKILL.md:45)
offers concrete related implementation evidence.

## ShipLoop extraction sequence

1. **This pilot:** generic list/DAG, Markdown state, exact packets, commands, prompt
   work, native dispatch receipts, real Backchain packaging, and optional clean
   Git run isolation. Exercise non-SDLC workflows to show useful generality.
2. **Consumer adapter:** have ShipLoop supply graph policy, prompts and acceptance
   callbacks through a versioned adapter. First compare an independently specified
   full 34-stage v3 trace, including every parked Improve child, against current
   ShipLoop. Do not copy its 7k-line protocol module into the kernel.
3. **Child contract:** add explicit start/resume/terminal-proof/import operations.
   Parent and child each own their own state; only a validated child terminal
   receipt advances the parent. Keep Improve's convergence policy in Improve.
4. **Workspace return:** extract ShipLoop's dirty-baseline capture and guarded
   return with caller-supplied path/retention policy. Prove original index/content
   preservation, source drift rejection, and idempotent return.
5. **Concurrent dispatch if justified:** claims, native launch receipts, explicit
   resources, separate workspaces/ownership, integration nodes and host recovery
   tests. A lease expiry cannot prove the old agent stopped writing.
6. **Adopt for new ShipLoop runs only after parity:** version-pin adapter/runtime;
   existing runs retain their original protocol and selected engine. Test a fresh
   packaged consumer on each claimed host before publication.

The pilot does not migrate ShipLoop, implement child loops or arbitrary branching,
run DAG branches concurrently, capture dirty source baselines, or merge changes.
Those are explicit next extraction gates, not hidden claims of this prototype.
