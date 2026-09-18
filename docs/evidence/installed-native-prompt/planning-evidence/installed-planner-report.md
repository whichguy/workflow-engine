# Installed planner report

Status: SUCCEEDED

## Outcome

The compatibility-native Backchain candidate and its explicit bindings are present at the packet-selected paths:

- run/plans/29b0bed0a7754f26815befb8dd498c00.plan.json
- run/plans/29b0bed0a7754f26815befb8dd498c00.bindings.json

The plan preserves the required dependency shape. S1 fans out to S2 and S3; S2 and S3 join at S4; S4 fans out to S5 and S6; S7 verifies summary from S5 and S4; S8 verifies audit from S6 and S4. S7 and S8 remain separate terminal leaves, so later workflow completion must wait for both. All eight bindings use explicit python3 -c argv, declare unique immutable outputs, and carry deterministic checks. No initial fact is consumed, so there is no unbacked initial-evidence assertion.

The installed Backchain package-only validation completed with exit code zero. Its receipt says validateStructure.ok=true, completionStatus=complete, forward_fidelity.ok=true, and no semantic warnings. It did not execute the planned graph.

The selected Until Loop procedure completed with terminal status complete and a 2/2 trivial-review streak. Cycle 1 performed a full backward and forward graph review; cycle 2 independently checked candidate-to-receipt correspondence and binding read/write carriers. Neither found a material gap or changed the candidate.

## Evidence

- Candidate companion: backchain-convergence-companion.json
- Raw selected Until Loop terminal stdout: packets/terminal.json, SHA-256 c6b797bdcbc338fce4ef1b02aea5b97289fca1570cc773799ccbd93e7854babd
- Domain reviews: reviews/cycle-1.md, reviews/cycle-1.static-check.json, reviews/cycle-2.md, and reviews/cycle-2.static-check.json
- Structural package artifacts: structural-package/validation.json, structural-package/handoff.json, structural-package/compact-report.md, and structural-package/full-report.txt
- Selected source identities and candidate digests: source-identities.sha256
- Final artifact-integrity check: final-validation.json

The Until Loop ephemeral state file was confirmed absent after terminal completion. The retained terminal receipt is therefore the recovery authority for this planning loop.

## Selected source identities

- Backchain 0.3.4 card: SHA-256 a92e5c85c92ac6e4eed5bda1d5ff552603366858eda83f536d70f3e2cf6a9a36
- Backchain convergence binding: SHA-256 23e2cfb0655cd8cd77562ab97368926879b0f4807f2fc02d2ad202603b396854
- Until Loop 0.4.0-rc.2 card: SHA-256 609959649f69f3ee5408bedbd6331806799495a8f59418e8d097c3d9f3c08028
- Until Loop ephemeral adapter: SHA-256 6a4131f8a70b56a361556fbc61e924f060ebf1ba5d5f1387a6d6d735e89b4212
- Weave 0.2.0 planning reference: SHA-256 411779b3f975d1a097d6b7d1aa869c57563b33177068acf6e88efabbb6545ee6

The full per-file record is in source-identities.sha256.

## Remaining limits and next action

This establishes planning convergence only. The plan has not been accepted, graph effects have not been run, no output files exist in the workspace, and no execution receipts exist. The parent should inspect the companion and terminal receipt, use the exact accept-plan argv in planning-packet.json, and then execute the installed CLI.
