# Validation evidence — 2026-09-18

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

## Native prompt-entry pilot

The original request asked for three integers, a native-agent report, and a final
script verification. The actual sequence was:

1. `init --prompt-file ... --isolate` preserved the exact request, pinned source
   HEAD, created a detached worktree and persisted the planning packet.
2. A fresh native Backchain planner read that packet and the selected skill.
   It wrote a three-step plan and explicit execution bindings. Its companion
   records two distinct inline qualifying reviews and the loaded lens/source
   context. Those are native semantic-review attestations, not an independent
   model benchmark or a property proven by the packaging script.
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

The standard skill quick-validator could not start because the system Python
lacks PyYAML. The skill frontmatter parsed and passed required-field validation
with the available Ruby YAML parser; no dependency was installed. Runtime tests
exercise the bundled scripts, not automatic skill discovery on every host.

This is one macOS/Codex native-agent pilot using local files and a clean Git
fixture. It does not establish Claude/Grok/Hermes execution, native-handle recovery
after an entire host-session restart, network-filesystem/multi-host locking,
exactly-once external effects, full ShipLoop lifecycle equivalence, dirty-source
capture/return, parallel DAG execution, automatic merge, or publication.
