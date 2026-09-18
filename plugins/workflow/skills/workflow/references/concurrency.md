# Native-agent frontier

Load for `workflow-frontier-v2`. The script owns claims and dependency readiness.
It emits `ready_frontier` and `active_packets`; these are different sets.

1. Inspect existing active packets first. Reconcile saved dispatch handles/intents;
   do not interpret a recovery packet as fresh launch permission.
2. Claim ready work using `claim-ready --run-dir RUN --limit N --request-id ID`.
   Keep the request ID for retries of that same claim request. A lost response
   never justifies a different request ID to bypass old work. Claiming is durable
   scheduling only; it does not launch an agent.
3. For each returned agent action, first load the separately selected ask-agent
   card and confirm native fresh-context background dispatch and collection.
   If unavailable, submit its `block` callback with a concrete reason while it is
   still ready. Otherwise perform `prepare-dispatch`. Only the direct
   `launch_once` reply permits a new launch; in v2 use its targeted
   `prepared_packet`. Other active packets remain recovery views.
   Use native asynchronous delegation with fresh context, explicit workspace,
   dependency receipts, declared output ownership and no further delegation.
   Workers must not edit any shared source/resource outside their declared outputs.
4. Record the actual native handle with that action's `dispatch` callback. Start
   independent claimed work up to capacity before collecting it. Continue useful
   independent parent work; do not duplicate worker-owned work.
5. Collect actual native notifications/results. Native waits may return after one
   worker: keep the others pending. File existence is not a completion signal.
   After collection, submit that worker's exact completion callback and evidence.
6. Read the resulting frontier. Independent work can progress before an unrelated
   branch finishes. A join cannot progress until every direct supplier's receipt
   is accepted. Commands and prompt steps are exclusive and may wait for agents.
7. Finish only at script `status=complete`. Failed, blocked, unlaunched, uncertain
   or still-running terminal leaves keep the run incomplete, even without a join.

Every agent has a separate action ID, attempt, launch intent, handle and receipt.
Retry requires confirming that specific former worker stopped; it fences that
action's callbacks and preserves sibling claims. Tokens do not prevent an old
process from writing. Never reset a claim because of age alone.

`verifying` means the script owns an active completion check. Observe with `next`
and await its result; do not submit another callback to make it progress. Unknown
verifier effects become `in_doubt`, requiring the same stopped-writer reconciliation
as other uncertain effects. Check commands must obey their action's output ownership.

`--shared-workspace-disjoint` is trusted cooperative ownership, not an enforced
sandbox. Declared outputs must be unique, immutable evidence. Shared source edits,
external resources or same-file writes require serial execution or a separately
designed isolated-workspace/integration workflow. The current adapter does not
create per-agent worktrees or merge their changes.

Report Task, Status, Result, Native agent type and Role substitution for actual
delegated work, plus collection notes and any unfinished workers, following
ask-agent. A host without native fresh-context dispatch/collection cannot execute
these nodes by pretending a subprocess is a native agent.
