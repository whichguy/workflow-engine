# Dependency audit — 2026-09-18

This is a source and release-readiness audit for Weave. It separates the selected
local source, published source, installed-skill execution, and future adapter work.
It does not update historical provenance. Publication and consumer evidence are
tracked separately in [DISTRIBUTION.md](DISTRIBUTION.md).

## Release identities

| Item | Selected/local evidence | Published evidence | Disposition |
| --- | --- | --- | --- |
| Weave release | Prototype began at `66f06473d1e779b44f6a393a23ca37f3fc4761b8` | Public qualified code candidate `219e290b731a9bf48b807f7fcb239eb298bb5758`, version 0.2.0 | Release tags and marketplace pins are separate from a working-tree test. |
| skill-craft selected worktree | `004447fd395d1820332cf454c9f966c4c85f63fe`, with local ShipLoop changes | `origin/main` `5a073503bcfe35e620461498b3fa438afe94d0bc` | Published ShipLoop is newer than the selected worktree. |
| extracted store | `docs/PROVENANCE.json` pins source SHA-256 `1f099a8f4e900ad3fe69f26c879ef30b89237876f7432b5848a557f204c65f1c` | Published `shiploop_store.py` is byte-identical to that source snapshot | Already inherited, with only `ShipLoop` → `Workflow` names/fences/schema changed. |
| ask-agent | Initial v0.3.0 card SHA-256 `4ac0eb3f701f07d78d4bb2f96bd7a0fa7131cd48910582df3a6794befa6345ce`; re-audited update `cd3d4fc04cceef1c1364be99432ba2a66cdbf55a91583cc484d8162844793699` | Updated package published on source release branch `6a120ed28eda5a1c5df0ac557dcfe94b4996ad46` | Independently packaged dependency; see distribution record for catalog promotion and installation. |

`docs/PROVENANCE.json` is historical extraction evidence. It deliberately remains
unchanged: it records the selected dirty-source snapshot, not an assertion about
the later published ShipLoop head.

## Dependency boundary

| Dependency | Weave uses | What remains external |
| --- | --- | --- |
| ShipLoop | Durable Markdown records, transaction recovery, packet-oriented state authority | SDLC graph, delivery policy, Improve cadence, and source-return policy |
| Backchain | Explicit selected-source package validation, frozen dependency graph, technical lenses | Planning semantic convergence and its selected Until Loop child |
| Until Loop | Retained terminal planning evidence through Backchain | Recurrence, child state, review classification, and terminal policy |
| ask-agent | Host-facing route for fresh native workers and actual launch handles | Native spawning, collection, provider/session recovery, and host permissions |

The kernel owns only its frozen workflow state, action IDs, receipts, evidence
checks, and legal transitions. A skill reads the current packet and submits its
exact callback; it never chooses a successor or recreates state.

## Current source findings

### ShipLoop: already inherited

The generic durable store has no behavioral drift from either the selected source
or published `origin/main`. Its write-ahead transaction and deterministic recovery
remain Weave's durable-state basis. The kernel has additional effect guards: it
records command/verifier intent before effects, holds a separate live-effect lock,
and changes stranded effects to `in_doubt` rather than replaying them.

The relevant published ShipLoop child/workspace files are also the same in the
selected local source. ShipLoop resolves a child runtime from the selected card,
not `PATH` or an ambient skill; it requires retained raw terminal evidence and
does not infer completion from a missing ephemeral child state. These are sound
generic rules, but ShipLoop's two-review Improve threshold and receipt layout are
not Weave policy.

### Published-only ShipLoop context controller

Published ShipLoop contains a context-host controller absent from the selected
local worktree. It keeps navigator `state.md` as graph authority and stores a
separate host receipt. The useful general rules are: bind host/run/CLI/policy and
state digest, lock one controller, persist `running` before a host turn, allow one
durable owner transition, and stop uncertain runs instead of automatic replay.

It resets context only after an accepted work-item boundary, never merely because
a producer returned, a child is active, or a state file disappeared. The next
owner must rehydrate from the durable packet and records.

Published-only source citations: [context host controller](https://github.com/whichguy/skill-craft/blob/5a073503bcfe35e620461498b3fa438afe94d0bc/skills/shiploop/scripts/shiploop_context_host.py#L1-L3), [owner transition guard](https://github.com/whichguy/skill-craft/blob/5a073503bcfe35e620461498b3fa438afe94d0bc/skills/shiploop/scripts/shiploop_context_host.py#L105-L156), [uncertain-owner recovery](https://github.com/whichguy/skill-craft/blob/5a073503bcfe35e620461498b3fa438afe94d0bc/skills/shiploop/scripts/shiploop_context_host.py#L238-L280), and [accepted-boundary reset policy](https://github.com/whichguy/skill-craft/blob/5a073503bcfe35e620461498b3fa438afe94d0bc/skills/shiploop/references/context-reset.md#L37-L68).

**Disposition:** design an optional generic host-controller and selected-child
persistence adapter later. Do not claim it is implemented, add a large ShipLoop
driver to this release, or make it a marketplace prerequisite.

### Backchain and Until Loop

The current selected Backchain is clean at
`ea2d040f377c269af3412332f9793c2610a61a1d`; the historical planning companion
recorded `01d1c7db9fe4e78b962c028e508d37d7410d154a`. The historical and current
audits found the four bound Backchain source bytes unchanged; the newer head is a
test/docs commit, not a changed planning contract. This is historical byte-identity
evidence, not a live-HEAD check performed by every Weave run.

Backchain's selected convergence binding owns the selected Until Loop recurrence.
The selected Until Loop source is clean at
`d10d5f6a49c12dec8dfe436e26271d6e449a6366`; card, runtime reference, adapter,
and root/plugin copies were reported byte-identical. The observed ephemeral route
is start → cold `next` → honest trivial review unsatisfied → cold `next` → distinct
honest trivial review satisfied → complete, after which its state file is deleted
(mode `0600`). Therefore a parent must retain the exact terminal packet; deletion
is never completion evidence.

Weave's Backchain adapter validates structural package output and freezes explicit
execution bindings. It must not embed a duplicate Until Loop loop, counter, or
semantic convergence rule. Backchain owns that child relationship externally.

### ask-agent and public availability

ask-agent remains the ownership boundary for native dispatch: launch and collection
are host actions, and the kernel records only an actual handle plus subsequent
callback/evidence. A file appearing cannot prove worker completion; a saved handle
does not prove cross-session recovery. Do not duplicate its skill body or create a
hidden subprocess launcher in Weave.

The initially untracked v0.3.0 source needed its own publication. During this
release the canonical card changed again, adding broad general-purpose worker
selection, inherited capabilities, parent pending-job ownership and waiting-status
guidance. The update was re-audited and included in the separate source release;
the Git integration reference remained byte-identical. General defaults do not
override Weave's explicit per-action file ownership and no-nested-delegation
constraint. Pending-job notes are coordination, never a second scheduler or
completion signal.

The first installed native smoke used the original card and is identified by its
source commit. The updated card receives a separate fresh install/digest check;
do not quietly relabel historical execution evidence as a test of a newer prompt.
Marketplace discovery, installation and host execution remain distinct claims.

## Release disposition

1. **Already inherited:** durable store, script-owned state transitions, immutable
   callback identity, receipts, recovery, and effect locks.
2. **Retain external:** Backchain semantic convergence/Until Loop recurrence;
   ask-agent native dispatch; ShipLoop SDLC and delivery policy.
3. **Future adapter design:** generic selected-child receipt persistence and
   optional accepted-boundary host context controller. Both must fail closed on
   missing state/receipt or uncertain prior effects, without replay.
4. **Release qualification:** record exact Weave and dependency pins, verify the
   independently published ask-agent package and exercise installed consumer paths.

## Published ShipLoop follow-up — 2026-09-18

After this audit began, published `origin/main` advanced from
`5a073503bcfe35e620461498b3fa438afe94d0bc` to
`3d45d186e8caf605660e1f49efded1fb3d31dffa` through UI-allocation
(`be3ed4d`) and probe-experiment (`bf6fe17`) changes. The targeted comparison
changed only ShipLoop's behavioral-requirements reference and v3 prompt catalog;
the store, selected-child bridge, workspace helper, context-host controller, and
navigator runtime were unchanged. ShipLoop version is now `0.15.1`.

The new behavior routes a conditional UI-planning-ownership reference into
discovery, plan, prepare, and step-plan. It assigns shared UI premises and missing
capability readiness to global/preparation planning, confines an item to its own
interaction delta, and preserves a blocked/correction route for an externally
owned prerequisite. The existing Improve handoff reviews this material without a
second graph node, counter, or child campaign. [Published UI allocation
reference](https://github.com/whichguy/skill-craft/blob/3d45d186e8caf605660e1f49efded1fb3d31dffa/skills/shiploop/references/behavioral-requirements.md#L231-L273)
and [published v3 packet routing](https://github.com/whichguy/skill-craft/blob/3d45d186e8caf605660e1f49efded1fb3d31dffa/skills/shiploop/scripts/shiploop_navigator_v3_prompts.py#L71-L115)
establish that this is ShipLoop SDLC/prompt policy.

**Decision:** retain this externally. Weave's generic graph already permits an
authored dependency and blocked result; it must not add UI phases, UI-premise
schemas, or Improve behavior. A future ShipLoop profile may carry this reference
and its result contract. No generic storage/recovery test was rerun because none
of those runtime boundaries changed.
