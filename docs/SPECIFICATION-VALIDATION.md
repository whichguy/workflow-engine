# Specification contract validation — 2026-09-18

## Decisions tested

Every new entry path has a requirement baseline. A prompt first receives a
script-issued specification action; an existing specification enters planning;
an authored workflow v2 contains the equivalent spec, NFRs, and step contracts.
The skill enriches bare steps before initialization. It does not delegate
scheduling to the host or silently turn arbitrary prose into commands.

The atomic unit is one coherent deliverable with observable acceptance criteria.
Shared setup, integration, verification, and release have explicit scopes and
reasons. Independent work retains its real dependency edges. There is no forced
final join: every declared terminal leaf still needs acceptance.

The first review found that allowing setup to verify any NFR could count a
runtime quality claim before the runtime existed. NFRs now default to outcome
verification; setup can verify only an explicitly declared readiness NFR. The
regression test rejects the former shortcut and accepts the explicit readiness
case. This classification does not prove that the author chose an honest label.

The other recovery decisions are separate from planning semantics:

- Specification v1 and workflow document v2 are independent of runtime state
  v1 (serial) and v2 (frontier). Old no-policy records keep their original
  definition and callback contract.
- Spec acceptance freezes canonical spec/NFR Markdown and state in one journaled
  transaction. Hydration checks their hashes and rejects aliases or missing files.
- Plan acceptance binds its spec, contracts, coverage, and exact plan/binding
  bytes. An identical accepted callback returns current state without packaging
  or executing again; conflicting bytes fail.
- Failed structural packaging retains its attempt directory. A corrected
  callback uses a fresh directory rather than becoming stranded behind it.

## Test layers

| Layer | Cases and evidence boundary |
| --- | --- |
| Specification contracts | Strict IDs/types, FR ownership, scoped/global NFR coverage, atomic roles, incomplete setup/release joins, early verification, repeated joins, terminal leaves, readiness/outcome distinction, packet criteria propagation |
| Entry and recovery | Prompt/spec/authored input paths; invalid authored input before run/worktree creation; byte-exact goal; callback replay/conflict; artifact change/delete/symlink/hardlink; legacy serial and frontier recovery |
| Transaction faults | Interrupt spec and plan acceptance after each of four persisted target writes, recover in a fresh load, then replay without a new effect |
| Planning callbacks | Failed package then correction, replay before and after completion, conflicting payload, mutated frozen bindings, staging-parent aliases before packager effects, selected real Backchain packaging from `--spec-file` |
| Existing execution suite | Serial and concurrent graph cases, Braid, Confetti, Loom, generated DAG oracle cases, reverse completion, failed leaves, stale callbacks, verifier uncertainty, output/receipt integrity, relocated package execution |
| Cooperative ownership probe | Deliberately simulates the wrong writer; confirms accepted file evidence cannot prove native worker identity or OS isolation |

The callback fault tests use a labeled adapter double for mechanical failure
injection. Separate tests use the actual selected Backchain packager. Authored
plan fixtures and simulated native handles are not model-generated planning or
native-agent execution evidence.

The full local suite passed **133/133 tests**, with no skips, in 67.832 seconds
on macOS/Python 3.14.7. The regenerated plugin matched all 13 canonical payload
files. [Qualification receipt](evidence/specification-suite.json) binds the file
hashes. The second independent review found no further lifecycle, legacy, NFR,
or packet-integrity defect; its remaining materialization drift was corrected
before this passing suite. The initial implementation review's findings and
resulting regression cases are described above.

A separate live prompt/specification/Backchain/Until Loop pilot is recorded
independently from the hermetic and authored-fixture claims.

## Reference re-audit

The selected Backchain checkout remained at `ea2d040`; its skill, caller contract,
and convergence reference had no drift. Its actual Until Loop binding remains
the convergence authority. The spec and NFRs enter the source-aware caller
companion; execution contracts stay outside Backchain's closed plan JSON.

The current local ShipLoop source was a dirty partial 0.16 draft, not a strict
superset of the published snapshot. Its baseline reconciliation, preserved
behavior, NFR operating conditions, UI premises, state/data invariants, and
bounded work-item guidance informed the planning reference. Removed draft
convergence safeguards were not copied. The independently selected Backchain
and Until Loop contracts still govern their own lifecycle. No sibling source
was edited and no dependent skill body was duplicated.

Stable IDs and source-to-check traceability are consistent with NASA's
[requirements verification matrix](https://www.nasa.gov/reference/appendix-d-requirements-verification-matrix/).
A coherent, independently testable increment is consistent with
[Agile Alliance's user-story guidance](https://agilealliance.org/glossary/user-stories/).
These are supporting principles; Weave does not import either organization's
project-management process into its scheduler.

## Remaining boundaries

The validator proves declared coverage and ordering, not semantic completeness,
source currentness, good feature decomposition, adequate tests, or the truth of
host attestations. The host must fulfill the selected Backchain/Until Loop
contract before submitting `accept-plan`; the kernel does not inspect its opaque
semantic companion. Shared workspace leases remain cooperative. Commands remain
exclusive, and each required leaf must finish before the script reports complete.
