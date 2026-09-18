# Specification-first prompt planning and Backchain

Load this reference for a `specification` or `planning` packet. The selected
Backchain source checkout owns its planning instructions. Load its
`skills/backchain/SKILL.md`, mandatory `references/convergence.md`, full
`references/technical-lenses.md`, and—when selected—the source-aware
`references/caller-contract.md`. Follow its generator, dependency review,
evidence resolution, and elaboration procedure. Do not copy an older review
counter, pass ceiling, or stopping procedure into Weave.

## First establish the governing specification

For a prompt-origin run, the script first issues a `specification` packet. Its
`prompt` is the exact original request and its `spec_file` is the only proposed
specification destination. Reconcile that request with relevant existing
specifications, NFRs, repository facts, accepted design decisions, and source
material before writing specification/v1 JSON. Preserve applicable existing
obligations and classify them as preserve, add, modify, or retire; do not blindly
regenerate a specification because a prompt is new.

The baseline must name coherent deliverables, functional requirements with
acceptance criteria, NFRs with concrete basis/operating conditions/measurable
criterion/verification surface, assumptions, out-of-scope decisions, and no
unresolved material questions. Carry relevant UI component, interaction, visual
system, state/data owner, invariant, authorized actor, and recovery premises into
the specification and later step criteria. This is reusable planning guidance,
not an import of ShipLoop's state machine, schemas, or convergence loop.

Submit the exact `accept-spec` callback only after this reconciliation. Weave
freezes `requirements/spec.md` and `requirements/nfrs.md` and binds their hashes
to future packets. A changed request/specification/NFR requires a new run. A
fresh `--spec-file` entry starts with the same frozen baseline; an old persisted
run keeps its issued legacy protocol.

The specification JSON allows only these top-level fields: required `version`,
`goal`, `deliverables`, `functional_requirements`, and `nfrs`; optional
`assumptions`, `out_of_scope`, and `unresolved`. Use this complete shape (replace
the illustrative IDs and wording; retain the exact prompt in `goal`):

```json
{
  "version": 1,
  "goal": "exact original request, including its trailing newline\n",
  "deliverables": [
    {"id": "D-note", "description": "a checked note", "requirements": ["FR-note"]}
  ],
  "functional_requirements": [
    {"id": "FR-note", "description": "the note contains checked facts", "acceptance": ["published.md contains those facts"]}
  ],
  "nfrs": [
    {"id": "NFR-evidence", "description": "evidence stays inspectable", "acceptance": ["each output has a separate receipt"], "scope": "all"}
  ],
  "assumptions": [],
  "out_of_scope": [],
  "unresolved": []
}
```

Each deliverable has exactly `id`, `description`, and nonempty `requirements`.
Each functional requirement has exactly `id`, `description`, and nonempty
`acceptance`. Each NFR has exactly `id`, `description`, nonempty `acceptance`,
and `scope` (`"all"` or a nonempty deliverable-ID array), with optional
`verification_stage` of `"outcome"` or `"readiness"`; omitting it means
`"outcome"`. IDs are unique across all three entity categories. Each functional
requirement belongs to exactly one deliverable. `unresolved` must be empty at
acceptance.

## Derive atomic, traceable steps

Keep the exact original request as `plan.goal`. For every new specification-based
run, use the frozen specification and NFRs as governing source clauses in the
selected `backchain-caller/v1` companion. Keep caller/source metadata,
requirement mapping, lens findings, selected source identities, input/output
candidate digests, actual Until Loop terminal receipt, and domain evidence in
that companion—not in Backchain's closed plan JSON.

Put exact commands, prompts, outputs, checks, and a `contract` in execution
bindings keyed by Backchain step ID. A deliverable implementation owns one
coherent, independently reviewable outcome, rather than a phase title, file
edit, or arbitrary model turn. Split a step when its preconditions, deliverable,
or done evidence diverge; do not split each assertion into its own node. Keep
actual supplier relationships: an edge names a real prerequisite, not just
declaration order or DAG depth.

Each binding contract declares:

- `role`: `deliverable`, `setup`, `integration`, `verification`, or `release`.
- scoped `deliverables`, owned functional `requirements` for a deliverable role,
  `verifies`, `ready_when`, and `done_when`.
- `shared_reason` for every non-deliverable role.

The binding's `contract` allows only `role`, `deliverables`, `requirements`,
`verifies`, `ready_when`, `done_when`, and optional `shared_reason`. For example:

```json
{
  "role": "deliverable",
  "deliverables": ["D-note"],
  "requirements": ["FR-note"],
  "verifies": [],
  "ready_when": ["accepted source evidence exists"],
  "done_when": ["draft.md contains the checked fact"]
}
```

Non-deliverable roles use an empty `requirements` array and a nonempty
`shared_reason`. A deliverable role names exactly one deliverable and at least
one of that deliverable's functional requirements. Every string array shown in a
contract must be explicit, even when empty.

Every functional requirement needs an implementation and a verifier at that
implementation or a descendant. Each applicable outcome NFR needs verification
coverage at or downstream of its scoped implementation. A NFR explicitly marked
`verification_stage: "readiness"` may be verified by a setup step only if that
setup is an ancestor of every scoped implementation. A normal outcome NFR cannot
be discharged by an early setup claim.

Model shared setup as one explicit evidence-producing supplier only when it
supplies the same actual state/layer to multiple consumers. Do not hoist it into
a global barrier. Model integration/release as an explicit scoped join after
every implementation it combines. A publish/deploy step can be a global release
when its scope and fan-in are explicit; target identity and post-release consumer
behavior are separate obligations and may be terminal leaves after release.

Preserve every terminal deliverable and verification sink. Completion waits for
all required leaves even when they never fan back in. `parallel_groups` is only
planning advice: it neither proves shared-write/resource safety nor authorizes
concurrent execution. Consumed initial facts need real evidence through
`_initial_evidence` bindings.

## Keep planning, convergence, and execution distinct

The selected Backchain card binds the selected actual Until Loop card and its
package-relative ephemeral adapter. That Until Loop owns recurrence, recovery,
budget/stop handling, and terminal status. If the binding cannot be resolved or
the exact terminal evidence is absent, report incomplete planning. Weave and
Backchain do not add a parallel counter, substitute scheduler, or synthetic
convergence receipt.

The host checks that the selected planning procedure completed and that its
receipt/evidence still belong to this candidate before invoking `accept-plan`.
Weave invokes Backchain's real package-only validator, validates bindings and
their requirement coverage, then freezes the execution graph. Packaging proves
structural acceptance; it does not prove semantic convergence, product behavior,
deployment success, or consumer outcome.

Keep structural artifacts, the source-aware companion, and execution receipts
distinct. A receipt hash binds bytes; it does not prove semantic review quality
or establish who performed an external action. The accepted execution graph is
frozen. Improve retains its separate lifecycle and is not part of this planning
binding.
