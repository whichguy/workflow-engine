# Planning Evidence Execution Notes

This note separates the work that has happened from the broader test and
experiment backlog in the hash-bound validation plan. It is intentionally not
included in the terminal companion's domain-evidence list: changing the
explanation after the terminal result must not rewrite what that result bound.

## Executed selection

The compatibility-native planning route was exercised for the frozen candidate
[`plan.json`](plan.json). The selected Backchain and Until Loop sources were
recorded with their resolved locations and byte digests, and the selected
package-relative Until Loop adapter returned a retained terminal packet with
`status: "complete"`. The companion identifies the same request, candidate,
source records, review reports, and terminal receipt:
[`compatibility-native.json`](compatibility-native.json).

That result is planning evidence only. It shows that this particular
compatibility-native planning record reached the selected adapter's terminal
state while its recorded candidate and source bytes matched. It does not prove
that the future test matrix has run, that a receipt is authentic, that the
reviews were semantically correct, or that the workflow kernel should require
Until Loop for every authored package.

## Future execution backlog

The graph-model breadth cases, lifecycle and recovery cases, resource and
concurrency probes, callback/retry cases, and compound fan-out/fan-in cases in
[`../validation-plan.md`](../validation-plan.md) are proposed work. Their
implementation and resulting test evidence remain pending unless separately
recorded in an execution-results artifact. In particular, the plan's bounded
experiments E1, E2, E3, and E5 are not represented as fresh completed runs by
this planning receipt.

The mechanical binding audit added alongside this note is a narrow companion
check: it can detect present-day record, path, and byte-digest disagreement.
It does not add a semantic convergence policy to `accept-plan`, create a new
review counter, or establish receipt authenticity.

## Frozen boundary

The candidate and terminal companion preserve the planning-time digests. If a
bound artifact changes later, the audit should report that drift rather than
silently refresh the prior evidence. A new planning run and new retained
receipt would be needed to bind a revised candidate.
