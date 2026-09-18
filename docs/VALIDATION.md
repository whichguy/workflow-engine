# Weave validation — 2026-09-18

Publication is complete: [DISTRIBUTION.md](DISTRIBUTION.md) records the tagged
release, merged source/catalog PRs, exact CI identities, fresh public-Git consumer
checks, normal-profile preservation and disposable-profile cleanup. Evidence below
retains the versions and scope of each earlier validation stage.

## Marketplace release candidate

**102 tests passed in 76.139 seconds, with zero failures or skips.** The full
suite used Python 3.14.7 on macOS with the separately selected Backchain available.
[Captured output](evidence/unittest-marketplace.txt) and
[tested-file hashes](evidence/tested-files-marketplace.json) record 57 runtime,
package, test, example and CI files; none changed during execution.

This adds five missing-delegation tests and six package tests to the adversarial
baseline. A ready agent can now durably block before launch without a fabricated
handle; cold recovery, same-reason replay, conflicting/stale callbacks, explicit
retry and independent frontier completion are checked. Dispatching, dispatched
and verifying actions cannot use that pre-launch path.

The package tests copy the plugin away from its source checkout, execute Braid,
follow installed-CLI prompt callbacks, recover without repeating effects, reject
missing Backchain and detect generated-view drift. Root/intermediate package
symlinks fail before any external writes. These are actual CLI behavior tests,
not a claim that a marketplace-hosted model performed the workflow. Public CI
does not have the private Backchain checkout; its integration cases report skips.
See [distribution qualification](DISTRIBUTION.md) for fresh host installation.

Published code candidate `219e290` passed four CI jobs across macOS/Linux and
Python 3.10/3.13. Each job passed 89 cases and explicitly skipped the 13 private
Backchain integration cases. Those cases passed in the full local 102-test run.

Fresh Codex and Claude installations each executed the authored Braid to terminal
completion with unchanged cold-recovery hashes. Six prompt-entry tests used the
installed Codex Weave/Backchain pair; the installed Claude pair also passed the
Braid prompt case. These fixture plans are authored, not model-generated.
The selected installed Until Loop ran its actual ephemeral lifecycle through
terminal completion and state deletion. [Consumer evidence](evidence/marketplace-candidate.json).

The installed Codex native smoke launched **Installed Alpha** and **Installed
Beta** with fresh `worker` contexts, no inherited history and no role substitution.
Both returned `SUCCEEDED`; the parent collected actual native completion notices,
checked their bytes, and submitted each callback. After Alpha acceptance, Beta
remained required and status was `dispatched`; only Beta acceptance produced
`complete`. Both are disposable-output tasks with no Git integration. Collection
had no rejected calls or remaining workers. This smoke used ask-agent source
`05c3329`; a subsequently updated card is identified separately in the dependency
audit. [Native receipt](evidence/installed-native-confetti.json).

A fresh **Installed Planner** worker subsequently followed the installed Backchain
0.3.4 and Until Loop 0.4.0-rc.2 procedure for a new prompt. It retained the actual
Until Loop terminal packet, two distinct domain reviews, exact source/candidate
hashes and explicit Python bindings. The parent collected its `SUCCEEDED` result,
checked the artifacts, submitted the issued `accept-plan` callback and executed
all eight commands. After S7's summary verification, S8's audit verification
remained ready; only S8 acceptance returned `complete`. Final file contents passed
independent checks, and a cold read preserved all run/output hashes and mtimes.
Native type: `worker`; no role substitution, collection error or outstanding worker.
[Retained prompt run](evidence/installed-native-prompt/result.json) and
[unaltered artifact manifest](evidence/installed-native-prompt/manifest.json).
This is one native planning case followed by serial command execution, not a
cross-host model-quality benchmark. Structural validation does not independently
prove the truth of semantic reviews.

The updated ask-agent card at `6a120ed` also received a fresh native execution.
**Current Ask Report** ran as `worker` with no inherited history or role
substitution, checked a script-produced input receipt, and wrote count `3` and
sum `10`. The parent collected its notification, independently checked the file,
and submitted the completion callback; the installed engine verified the result
and completed. Cold recovery preserved hashes. One probe-side result write first
needed its parent directory created; it failed before any callback was submitted.
No collection request was rejected and no worker remained pending.
[Current-card execution receipt](evidence/installed-current-ask-agent.json).

## Prior adversarial validation

**91 tests passed in 69.522 seconds, with zero failures or skips.** This adds 38
tests to the prior 53-test baseline. Command:
`python3 -m unittest discover -s tests -v`.
[Captured output](evidence/unittest-adversarial.txt) and
[tested-file hashes](evidence/tested-files-adversarial.json) identify the exact
local runtime, tests, examples, experiment helpers and driver guidance. The hash
guard found no changes during the run. The host used Python 3.14.7 on macOS; these
are local working-tree changes, not a committed or published release.

The [experiment report](experiments/RESULTS.md) records the assumption changes,
executed cases, counterexamples and deferred cases from the expanded pass.
The frozen [validation plan](experiments/validation-plan.md) is planning evidence;
it is not an assertion that every proposed experiment ran.

The extended graph corpus passed **22/22 cases: 176 accepted nodes and 912 CLI
transitions**, with capacities 2/3/5, unchanged runtime hashes and every temporary
case removed. Its three invalid-packet controls all failed the independent oracle
as intended; they are oracle self-tests, not runtime source mutants.
See [the retained graph report](evidence/graph-matrix.json).

The new fault regressions fail against the frozen baseline (five failures and
two errors in nine tests) and pass against the repaired runtime. They expose
interrupted-verifier replay, unavailable cold reads and accepted path aliases.
The current implementation records verification intent before effects, recovers
dead owners as `in_doubt`, and rejects portable output aliases.

The shared-file ownership probe **falsified writer provenance**: A's verifier can
produce B's file, and B's callback can then be accepted. This confirms the existing
trusted cooperative boundary; it is not presented as an isolation pass. See
[the counterexample](evidence/ownership-boundary.json).

An independent runtime review found no further concrete transition/alias defect.
It did identify a test-cleanup hazard from signalling retained raw process-group
IDs. That cleanup was changed to direct owned-process control and cooperative
verifier release; the reviewer confirmed the finding resolved.

The selected Backchain 0.3.4 planning route used the actual selected Until Loop
adapter and retained its terminal `complete` receipt. A separate mechanical audit
matches seven source records and six domain records to the exact request and
candidate; fifteen fixture tests cover mismatches and malformed evidence. The
audit is read-only, makes no authenticity/semantic-quality claim, and adds no
convergence policy to the generic kernel. [Audit result](evidence/planning-binding-audit.json).

Historical native v1/v2 runs were cold-read through the changed runtime and both
remained complete with unchanged files. [Recovery evidence](evidence/legacy-recovery-adversarial.json)
does not imply new native dispatch or reconnectability after host-session loss.

## Prior v2 regression evidence

**53 tests passed in 28.780 seconds; no failures or skips on this host.**
Command: `python3 -m unittest discover -s tests -v`.
[Captured output](evidence/unittest-v2.txt) and
[exact tested source/example hashes](evidence/tested-files-v2.json) are retained.
The capture checks that no listed file changed during the run.

The 21 added tests cover authored Braid/Confetti/Tributaries graphs, paired prompt
fixtures through real Backchain packaging, and the opt-in v2 native-agent frontier.

| Requirement | Evidence |
| --- | --- |
| Repeated fork → join → fork → join | Both supplier sets must be accepted; each join receives direct receipt hashes |
| Terminal fan-out without a join | Claimed, failed, blocked, prepared and still-unclaimed leaves prevent completion |
| Uneven paths and multiple roots | Dependency order survives scrambled declarations; agents use direct readiness without a global wave barrier |
| Concurrent claims | Competing real CLI processes cannot allocate two identities to one step; same claim request replays |
| Out-of-order completion | Independent callback processes preserve both receipts and release the join exactly through accepted dependencies |
| Per-action recovery | Cold prepared packets forbid fresh launch; stale retry callbacks fail while siblings survive |
| Cooperative ownership | Explicit policy and disjoint nonempty agent outputs required; command and prompt nodes remain exclusive |
| Version compatibility | Default state stays v1; frontier state uses v2; previous serial/native pilot runs still cold-recover |
| Prompt adapter | Real package-only validation preserves exact request, supplier edges and v2 execution policy; missing binding rejects activation |

Automated native handles are simulated deliberately. They prove the local protocol,
not host dispatch. Authored Backchain fixtures do not prove semantic planning.
See the live-pilot section below for native execution evidence.

Independent review found and corrected two issues: command-only `run` initially
failed to claim an unclaimed v2 command, and frontier rendering initially weakened
the recovered prepared-action instruction. The final implementation auto-claims
exclusive commands and explicitly forbids fresh launch on cold prepared recovery.
A further test now protects unclaimed terminal leaves. Final review reported no
additional material runtime defect within its scope.

The root `./weave` alias, YAML frontmatter and local documentation links were
checked. No dependencies, global aliases, skill installations or remote publishing
were performed. Existing v1 evidence is retained below as historical evidence.

## Live Native Braid v2 pilot

The actual authored recipe `examples/native-braid.workflow.json` ran through the
checkout `./weave` CLI in `.runs/native-braid-v2/run`, using a clean Git source and
one detached run worktree. The run used capacity two and explicit disjoint output
ownership. Four fresh native Codex workers executed the two fan-outs:

| Task | Status | Result | Native agent type | Role substitution |
| --- | --- | --- | --- | --- |
| B: Count | SUCCEEDED | Independently counted 3; verified A receipt and input hash | scoped-implementer | none |
| C: Sum | SUCCEEDED | Independently summed 10; verified A receipt and input hash | scoped-implementer | none |
| E: Check count | SUCCEEDED | Verified D receipt/hash; wrote exact count proof | scoped-implementer | none |
| F: Check sum | SUCCEEDED | Verified D receipt/hash; wrote exact sum proof | scoped-implementer | none |

Both B/C handles were persisted before collection; D was held. After B acceptance,
C still held D. Once both were accepted, D ran and released E/F. Both second-round
handles were persisted before collection; G stayed held after E acceptance. Only F
acceptance released G. The final command produced `terminal-proof.json` containing
`{"count":3,"sum":10,"status":"complete"}`. All A–G receipts were accepted, and
zero active claims remained.

Collection used actual native completion notifications. All four results were
collected in the same live session; there were no rejected collection calls and
no remaining native pilot workers. Parent work checked source/receipt/hold state
and ran the full regression suite while workers progressed.

A new-process terminal read and exact F callback replay returned complete without
changing any declared output's hash or modification time. The source checkout
remained clean at its pinned HEAD. A cold read of the original v1 native prompt
pilot also still returned `workflow-packet-v1` / `complete`.

[The tracked native pilot summary](evidence/native-braid-v2.json) includes the run
identity, tested runtime hash, all output fingerprints, source baseline and exact
observations. Raw packets, receipts and outputs remain in the ignored local run.
This run began from authored steps; current paired-prompt tests use authored plans
and real packaging. The original live native planning pilot is retained below.

## Current limits

This is a local macOS/Codex pilot with cooperative disjoint agent outputs. It does
not establish multi-host/network-filesystem locking, native handle reconnection
after session loss, per-agent worktree integration, concurrent command nodes,
exactly-once external effects, dynamic graph edits, ShipLoop lifecycle parity,
child-engine adapters, automatic merges or publication. The host still checks
Backchain's semantic companion; structural packaging cannot establish its quality.

---

# Initial v1 validation — historical baseline

This used Backchain 0.3.3 before the selected package changed. Its inline review
companion is historical evidence only; it does not prove the Until Loop binding
required by the now-selected Backchain 0.3.4.

**Outcome: the local prototype works for the tested scope.** All 32 combined tests
passed, both authored examples completed, and a real prompt-to-Backchain-to-native
agent-to-verification run completed in an isolated Git worktree.

## Automated checks

Command: `python3 -m unittest discover -s tests -v`

Result: **32 tests passed in 11.453 seconds; no skips or failures in this environment.**
See [the captured output](evidence/unittest.txt) and
[the tested source SHA-256 manifest](evidence/tested-files.json).

| Boundary | Evidence |
| --- | --- |
| Serial list and DAG join | Deterministic ordering and dependency receipts |
| Fresh-process recovery | Same active identity; terminal reads do not execute work |
| Live command status | Concurrent `next` preserves a live execution owner |
| Crashed/timed-out command | Unknown effects park the attempt; no blind replay |
| Retry | Old callback is fenced; stale artifacts cannot satisfy a fresh attempt |
| Native handoff | Preparation precedes spawn; handle required; cold preparation reconciles |
| Completion replay | Identical result is harmless; conflicting result is rejected |
| Verifiers | Failure cannot advance; prior evidence mutation cannot complete; final output hashes include verification changes |
| Evidence integrity | Accepted output, receipt and execution-log drift is detected |
| Frozen input | Source workflow edits cannot rewrite an active graph |
| Request identity | Exact multiline, CRLF and Unicode requests retained; changed goal rejected |
| Markdown transactions | Injected partial transaction recovers state and receipt together |
| Real Backchain packaging | Complete/incomplete graph, initial evidence, bindings, output safety and host evidence checks |
| Git isolation | Clean-root detached worktree; dirty/subdirectory/internal-run cases rejected |

The Backchain tests invoked the actual sibling checkout's package-only CLI. On
another machine these integration cases skip if that checkout is absent; set
`WORKFLOW_TEST_BACKCHAIN_ROOT` explicitly. They do not invoke a model or establish
the quality of native semantic planning.

The pre-existing Backchain graph navigator also passed **17 checks with 30 real
process race rounds**, including its negative controls. This supports the chosen
protocol's prior art; it is not proof of concurrent execution in this prototype.
See [the baseline result](evidence/backchain-navigator-baseline.json).

## Authored workflow examples

Both `examples/serial.workflow.json` and `examples/diamond.workflow.json` were
initialized and run using the public CLI. Both returned `status=complete`, and
new processes recovered them as complete. Their artifacts are retained locally
under `.runs/example-serial` and `.runs/example-diamond`.
See [the example results](evidence/authored-examples.json).

## Historical native prompt-entry pilot

The original request asked for three integers, a native-agent report, and a final
script verification. The actual sequence was:

1. `init --prompt-file ... --isolate` preserved the exact request, pinned source
   HEAD, created a detached worktree and persisted the planning packet.
2. A fresh native Backchain planner read that packet and the selected skill.
   It wrote a three-step plan and explicit execution bindings. Its companion
   records two distinct inline qualifying reviews and the loaded lens/source
   context. Those are native semantic-review attestations, not an independent
   model benchmark or a property proven by the packaging script.
   This historical inline-review record does not satisfy the current Backchain
   requirement for a retained selected Until Loop terminal receipt. The newer
   installed prompt run above exercises that current procedure explicitly.
3. The parent submitted the script's exact `accept-plan` argv. The runtime invoked
   real Backchain package-only validation and froze the resulting workflow.
4. The runtime executed S1 and wrote `numbers.csv` containing `2`, `3`, `5`.
5. The parent used the script's `prepare-dispatch` callback. Its immediate reply
   authorized one launch; a fresh `next` returned reconciliation-only state.
   Using the live launch reply, the parent spawned one fresh native agent and
   recorded its actual handle using the returned `dispatch` callback.
6. The agent verified the input receipt and data hash and wrote only `report.json`.
   While it worked, the parent independently confirmed the source checkout/HEAD
   were unchanged and S3 remained held behind S2.
7. After actual native completion, the parent submitted the result through the
   script's exact callback. Output/check validation released S3; its script wrote
   `verification.txt`, and the runtime returned `status=complete`.
8. A new-process terminal read and exact replay of the agent callback both stayed
   complete. All output hashes and modification times were unchanged by those
   recovery/replay operations; the original source checkout remained clean.

| Task | Status | Result | Native agent type | Role substitution |
| --- | --- | --- | --- | --- |
| Create report.json | SUCCEEDED | count 3, sum 10, verified against unchanged input | scoped-implementer | none |

Collection: native completion arrived after a bounded native join. No collection
errors occurred; no pilot agent remains running.

The full local run is `.runs/prompt-pilot/run`; it contains authoritative
`state.md`, derived `packet.md`, planner artifacts, receipts and command logs.
The native planning companion is `plans/convergence.json` inside that run.
[The tracked pilot summary](evidence/native-pilot.json) records run identity,
trace, output hashes, native result and recovery checks. Raw run state is ignored
by Git and retained locally for inspection.

## Independent review and limits

Independent contract/runtime review led to fixes for artifact freshness, prepared
launch recovery, live execution ownership, verification-time evidence changes,
tool provenance and adapter/core evidence requirements. The final regression
suite exercises the discovered runtime failures. Review is bounded and is not
a claim of exhaustive correctness.

At this historical stage the quick-validator's selected Python lacked PyYAML.
The skill frontmatter parsed and passed required-field validation
with the available Ruby YAML parser; no dependency was installed. Runtime tests
exercise the bundled scripts, not automatic skill discovery on every host.
The marketplace release later used `/usr/bin/python3`, which already has PyYAML,
to validate both generated manifests successfully.

This is one macOS/Codex native-agent pilot using local files and a clean Git
fixture. It does not establish Claude/Grok/Hermes execution, native-handle recovery
after an entire host-session restart, network-filesystem/multi-host locking,
exactly-once external effects, full ShipLoop lifecycle equivalence, dirty-source
capture/return, parallel DAG execution, automatic merge, or publication.
