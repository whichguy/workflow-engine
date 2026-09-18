# Technical-lens applicability screen

Candidate scope: the exact request in ../request.txt is a local, eight-step file-production graph for the supplied empty workspace. This planning pass does not execute the graph, accept a plan, edit Weave state, or make source-control changes.

| Lens | Disposition | Inspected basis and resulting planning consequence |
| --- | --- | --- |
| T01 | Applicable | The request is the only normative requirement. Its two forks, report join, independent final artifacts, explicit Python-only commands, and two verification outcomes become direct graph obligations. |
| T02 | Not applicable | No multi-module architecture or reusable component is requested. |
| T03 | Applicable | The packet names one existing consumer workspace and owner boundaries. All outputs are local relative paths; no repository integration, generated files, merge, or source-tree edit is planned. |
| T04 | Applicable | Each binding uses the packet-authorized python3 executable and no package dependency. The plan does not treat Python availability as an unevidenced initial state; the executor will report an unavailable command if it occurs. |
| T05 | Not applicable | The request has no configuration, secrets, flags, endpoint, or policy input. |
| T06 | Not applicable | No service, account, or bootstrap target is needed beyond the existing workspace supplied by the packet. |
| T07 | Applicable | The plan distinguishes planned, accepted, and verified file states. The parent workflow owns acceptance and post-acceptance immutability; no step claims acceptance before its receipt exists. |
| T08 | Not applicable | No entity, tenant, instance, or revision lookup is part of the local file task. |
| T09 | Applicable | Bindings specify exact UTF-8 text, line order, case, and numerical representation so each consumer reads the producer's declared representation. |
| T10 | Applicable | The only persistence boundary is each local file write. Each producer has a readback verification command; no database or durable remote-store claim is made. |
| T11 | Not applicable | There is no legacy data or migration. |
| T12 | Applicable | S2 and S3 consume the same immutable seed and write distinct paths. S5 and S6 consume the report and write distinct paths. Equal dependency depth does not claim scheduler safety beyond this path partitioning. |
| T13 | Not applicable | No cross-file atomic invariant or transaction is requested. |
| T14 | Not applicable | There are no replicas or distributed readers. |
| T15 | Not applicable | There are no events, queues, or acknowledgements. |
| T16 | Not applicable | The request has no retry or compensation behavior. |
| T17 | Not applicable | No timing, expiry, or deadline condition appears in the request. |
| T18 | Not applicable | There is no cache, materialized view, or freshness contract. |
| T19 | Not applicable | The task graph has no user-requested restart/replay behavior. The selected Until Loop's ephemeral receipt preservation is handled by the planning companion, outside the execution graph. |
| T20 | Applicable | Every execution and verification binding is a structured python3 -c argv with ordinary nonzero-exit failure behavior. |
| T21 | Applicable | The graph is limited to local filesystem operations using safe, fixed relative names in the supplied workspace. |
| T22 | Not applicable | There is no network or connection lifecycle. |
| T23 | Not applicable | There is no external provider or callback. |
| T24 | Not applicable | There is no authentication or authorization flow. |
| T25 | Not applicable | There is no UI or client-state flow. |
| T26 | Not applicable | There is no rendering or visual component. |
| T27 | Not applicable | There is no human input modality or accessibility surface. |
| T28 | Not applicable | The literal English words and integer 2 have no locale or unit ambiguity. |
| T29 | Not applicable | No trust-boundary or untrusted input is introduced by the request. |
| T30 | Not applicable | The task contains no personal or regulated data. |
| T31 | Not applicable | No graceful-degradation promise is requested; a failed file operation is a failed step. |
| T32 | Not applicable | The small fixed files have no capacity or cost constraint. |
| T33 | Not applicable | Operational telemetry is outside the local request; explicit verification receipts provide task-level evidence. |
| T34 | Applicable | S7 and S8 are separate terminal verification sinks with deterministic readback checks, preventing a successful producer command from substituting for evidence. |
| T35 | Applicable | Verification is isolated to the packet workspace. This planning pass does not create the graph's files, so no test fixture or cleanup is needed now. |
| T36 | Applicable | The companion records the exact request, candidate and receipt digests, and identities of the installed Backchain, Until Loop, and Weave packages. |
| T37 | Not applicable | There is no deployment, activation, or external consumer route. |
| T38 | Not applicable | There is no rollout, promotion, rollback, or retirement. |
| T39 | Not applicable | The request has no backup or recovery objective. |
| T40 | Applicable | The parent owns plan acceptance and later graph execution. This task owns planning artifacts only; no external approval is treated as completed. |
| T41 | Not applicable | No independently versioned producer/consumer protocol exists. |
| T42 | Applicable | The selected installed packages are recorded by resolved path and digest; the graph itself adds no third-party dependency. |

## Cross-lens interactions

No interaction row introduces a new graph requirement. The only consequential interaction is fixture × concurrency × cleanup: the two requested fan-outs use read-only upstream files and non-overlapping declared outputs, so their ordering derives only from direct data suppliers. The runtime cycle × implementation DAG row is not activated: parent acceptance, Until Loop planning convergence, and later workflow execution are separate lifecycle stages, not execution-step dependencies.

## Cards and references actually read

The review loaded the installed index and the applicable cards T01, T03, T07, T09, T10, T12, T20, T21, T34, T35, T36, T40, and T42; it also read the installed cross-lens interaction reference. Inapplicable categories were screened against the exact request rather than assumed absent.
