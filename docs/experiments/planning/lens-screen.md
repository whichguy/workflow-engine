# Compatibility-native lens screen

This screen is attached to the planning candidate in this directory. It records
what was inspected for this bounded local validation expansion; it is not a claim
that the running environment satisfies every possible workflow concern.

| Lens | Disposition | Basis and planned consequence |
| --- | --- | --- |
| T01 requirements, scope, authority | applicable | Preserve the exact request, restrict edits to Weave tests/docs/helpers, and do not commit, publish, or alter sibling repositories. |
| T02 architecture and boundaries | applicable | Keep Backchain/Until Loop semantic convergence as a host obligation; `accept-plan` remains structural. |
| T03 repository/workspace integration | applicable | Use the frozen audit baseline, fresh temporary workspaces, and an ignored `.runs/` experiment area. |
| T04 toolchain and build setup | applicable | Exercise Python standard-library tests and selected Backchain/Until Loop source paths; no new dependency is assumed. |
| T05 configuration and policy | applicable | Verify v1/v2 policy selection, capacity, and the explicit shared-workspace attestation. |
| T06 setup and environment lifecycle | applicable | Create only isolated temporary fixtures; source checkout, user configuration, and host installation remain unchanged. |
| T07 state ownership and lifetime | applicable | Test script-owned Markdown state, active actions, receipt durability, and Until Loop's terminal-state deletion boundary. |
| T08 identity and revision | applicable | Bind run/action/attempt/candidate/source/receipt identities and test mismatches. |
| T09 schema and representation | applicable | Test JSON/Markdown parsing, canonical plan/companion shapes, duplicate-key and malformed-result paths. |
| T10 persistence and durability | applicable | Exercise transactions, receipts, hashes, cold reads, and torn-write recovery. |
| T11 migration/import/backfill | not applicable | No data migration or import is part of the local prototype validation scope. |
| T12 concurrency and liveness | applicable | Exercise direct readiness, capacity, claims, leases, callback races, and blocked/in-doubt ownership. |
| T13 atomicity and isolation | applicable | Test claim/receipt transaction cuts and document that cooperative leases are not filesystem isolation. |
| T14 replication/distributed consistency | unresolved future boundary | A single local POSIX host is the tested scope; multi-host and network filesystem behavior must not be inferred. |
| T15 events and acknowledgements | applicable | Treat native dispatch/complete callbacks as independently acknowledged events and test lost/replayed/conflicting callbacks. |
| T16 retry/idempotency/cancellation | applicable | Test request-id replay, stale attempt fencing, output freshness, and retry effects on siblings. |
| T17 time/deadlines | applicable | Test timeout/in-doubt behavior and bound crash-cut experiments without claiming exactly-once effects. |
| T18 caching/freshness | not applicable | The prototype does not use a cache or derived index; receipt/hash freshness remains covered under T10/T16. |
| T19 durable workflow/restart | applicable | Test fresh-process recovery, prepared-dispatch reconciliation, terminal reads, and preserved terminal evidence. |
| T20 command/error contracts | applicable | Test public JSON packets, exact callbacks, failure responses, and no successor selection by the host. |
| T21 operating-system/platform | applicable | Exercise POSIX flock, process groups, paths, symlink resistance, and macOS/Linux-only scope. |
| T22 networking/transport | not applicable | No network transport is introduced by the kernel or planned test harness. |
| T23 external providers/callbacks | applicable | Native host dispatch is an attestation boundary; the experiment distinguishes handle recording from provider verification. |
| T24 authentication/authorization | not applicable | No new account, identity provider, or authorization flow is in scope. |
| T25 user journeys/client reconciliation | not applicable | There is no product UI; packet recovery is covered as an operator protocol under T19/T20. |
| T26 visual rendering | not applicable | No rendered product surface is changed. |
| T27 accessibility/input modalities | not applicable | No user-facing interaction surface is changed. |
| T28 content/Unicode/numerical semantics | applicable | Retain CRLF and Unicode request identity cases and deterministic seed/report formats. |
| T29 trust boundaries/security | applicable | Treat workflow definitions as trusted executable input only; test unsafe paths, symlinks, and forged companion evidence. |
| T30 privacy/retention | not applicable | Fixtures contain synthetic data only; terminal receipts contain no credentials or personal data. |
| T31 failure isolation/resilience | applicable | Separate independent branch progress from blocked branches and document unrecoverable host/session limits. |
| T32 capacity/performance | applicable | Test `max_active` capacity and bounded deterministic runs; do not extrapolate performance from the pilot. |
| T33 diagnostics/audit | applicable | Retain command output, manifests, receipt identities, source hashes, experiment reports, and no-change scope. |
| T34 verification strategy | applicable | Use independent oracles, adversarial fixtures, real CLI processes, and bounded live/native evidence separately. |
| T35 fixture isolation/teardown | applicable | Use fresh temp roots and explicit cleanup checks; do not share mutable workspaces across tests. |
| T36 artifact provenance | applicable | Hash selected cards, candidate/receipt artifacts, test files, and baseline files. |
| T37 deployment/readiness | not applicable | No deployment or service registration occurs. |
| T38 rollout/rollback | not applicable | No product rollout is in scope; v1/v2 compatibility is covered under T41. |
| T39 backup/restore | not applicable | Transaction recovery is tested, but backup/restore policy is not implemented or claimed. |
| T40 human ownership/docs | applicable | Record the host's semantic-review obligation, user-authorized scope, and future decision gates. |
| T41 compatibility/version skew | applicable | Preserve v1 runs, bind exact selected-card versions/hashes, and make source drift a failed audit condition. |
| T42 dependency supply chain | applicable | Treat Backchain/Until Loop source selection as explicit, hash-bound evidence and do not infer behavior from a same-named installation. |

The unresolved T14 boundary is deliberately a decision gate: a green local suite
does not authorize multi-host execution, network filesystems, or a claim of
distributed exactly-once effects.
