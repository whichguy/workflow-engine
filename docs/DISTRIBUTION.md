# Standalone distribution

The public repository is `whichguy/workflow-engine`. The portable plugin and skill
identifier is `workflow`; the display name and checkout alias are Weave.

## Current release: 0.3.0

[workflow-v0.3.0](https://github.com/whichguy/workflow-engine/releases/tag/workflow-v0.3.0)
is published at `2754ab3c27204be1a25f8f4416098bb58096d3fa`. It adds mandatory
specification/NFR contracts for new inputs while preserving old persisted runs.
[Source PR 1](https://github.com/whichguy/workflow-engine/pull/1) and
[marketplace PR 3](https://github.com/whichguy/skill-craft-market/pull/3) are merged.
The marketplace promotion is `e29f5bb57b88af402ccf602e0b058b3288830851`.

All 133 local tests passed, including the selected real Backchain packager.
The source PR and merged-main CI passed all four macOS/Linux Python 3.10/3.13
jobs; public CI passed 119 cases and explicitly skipped 14 private Backchain
integration cases. Strict marketplace verification checked the changed entry's
complete payload and exact tag/commit binding with no failures or advisories;
53 marketplace unit tests and PR/main CI passed.

A fresh Claude Code profile installed 0.3.0 from the public Git catalog. All
13 package files matched the qualified payload. Its installed helper completed
Relay (`count: 3`, `sum: 10`) with three spec-linked receipts, and cold recovery
left state unchanged. The recorded normal-profile guard was unchanged. The
owned disposable profile was removed afterward; its path in the receipt is
historical, while workspace/output/run evidence remains. No model was called
by this installation check. This update did not repeat a fresh Codex CLI
installation; the common generated payload and relocated-package tests passed.

[Local suite hashes](evidence/specification-suite.json),
[publication receipt](evidence/specification-publication.json),
[public consumer receipt](evidence/specification-public-consumer.json), and
[specification validation](SPECIFICATION-VALIDATION.md) keep these claims
separate from model-generated planning evidence.

The separate [native prompt pilot](evidence/specification-native-pilot.json)
completed a model-generated specification and plan with actual selected Until
Loop convergence, real Backchain packaging, six accepted command receipts, and
two required terminal leaves. It used local sources and serial execution; its
receipt records the source changes during planning.

## Previous qualification: 0.2.0

`workflow-v0.2.0` is published at `eb8895589afdd177eb096cc18f2b543b030012a9`.
Its runtime and package bytes match the qualified `219e290` candidate. The
[GitHub release](https://github.com/whichguy/workflow-engine/releases/tag/workflow-v0.2.0)
and [marketplace PR 2](https://github.com/whichguy/skill-craft-market/pull/2) are
public; the catalog was promoted to `cdcfaeeec5144a40d46fddcb0ecb3dd7c5aec6ed`.

Fresh Codex 0.155.0 and Claude Code 2.1.276 profiles independently cloned that
public Git catalog and installed workflow 0.2.0, ask-agent 0.3.0, Backchain 0.3.4,
and Until Loop 0.4.0-rc.2 at their exact catalog pins. Both Weave payloads matched
all 12 package files and completed Braid with unchanged cold recovery. Private
Backchain used existing authenticated Git access. This consumer check made no
model calls; native Codex execution is recorded separately in VALIDATION.md.

The tagged Weave CI passed all four jobs. Ask-agent's full source PR CI passed
core, all three ShipLoop groups and the aggregate hermetic gate; its promoted
tree is identical to the tested tree. Marketplace PR and promoted-main CI both
passed. [Publication receipt and CI links](evidence/publication.json).

The existing normal Codex and Claude marketplace registrations were refreshed.
Both now expose the new packages. Before/after guards preserved recorded settings,
installed plugin records, skill symlinks and marketplace source bindings; only
Claude's target-marketplace update timestamp changed. No new package was installed
in those normal profiles. Owned disposable test profiles were removed after
retaining evidence. Their original absolute locators are historical run records,
not live installed paths; run state and outputs remain outside those profiles.

A later final observation found another Codex config digest change and removal
of the pre-existing experimental Grok ask-agent link. Their cause is not
established by these inventories; neither was restored or replaced by this task.
The immediate refresh guard above remains a separate, bounded observation.
The shared skill-craft checkout's status inventory also changed during work;
release mutations used isolated checkouts and did not reset that shared work.

## One source, generated package

`skills/workflow/` is authoritative. Run `python3 scripts/sync-plugin-view.py` to
materialize `plugins/workflow/`; `--check` rejects drift. That package contains
only Weave's card, references and Python scripts plus license, package README and
Claude/Codex manifests. No Backchain, Until Loop, ask-agent or Improve skill bodies
are copied. CI checks parity and the behavioral test suite on macOS/Linux.

The skill-craft-market entry uses a real `git-subdir` (`plugins/workflow`) with a
full immutable commit SHA. The canonical source path stays stable. Do not rename
`skills/workflow` to match a display name.

## Conditional dependencies

Install `workflow@skill-craft-market` in the host, then select the loaded card.
Authored command recipes require only Python 3.10+. Prompt steps use the current
host. Agent steps require the separately installed `ask-agent` skill plus native
fresh-context asynchronous launch and result collection. The script can durably
block a ready agent action when those capabilities are missing, before any launch
intent or fabricated handle exists.

Prompt-to-graph entry requires explicitly selected Backchain with its packaging
harness/schema, Bash and Node. Backchain selects Until Loop for convergence; the
actual Until Loop terminal receipt is retained in Backchain's companion. The
generic kernel does not implement a competing convergence counter. It validates
structural packaging, while the host retains responsibility for semantic planning
evidence. Backchain currently requires authenticated access; it is not required
for public command-only installation.

The marketplace exposes these packages separately. There is no unconditional
automatic dependency installer: making private planning prerequisites mandatory
would prevent independent command-only use, and cross-host dependency behavior
has not been qualified. Claude supports plugin dependencies; Weave deliberately
uses conditional selected-skill prerequisites. See
[Claude dependency semantics](https://code.claude.com/docs/en/plugin-dependencies)
and [Codex plugin packaging](https://developers.openai.com/plugins/build/plugins).

## Qualification boundaries

The release record below uses actual fresh-profile checks. A test of helper
behavior is not a model execution claim. A simulated agent callback is not proof
that a native worker ran. Historical native Codex pilots and the installed native
smoke are recorded in [VALIDATION.md](VALIDATION.md); these do not establish native
model execution in Claude, Grok, Hermes or Cursor. Host session resets and per-agent worktree
integration remain future adapters, described in [DEPENDENCY-AUDIT.md](DEPENDENCY-AUDIT.md).

| Claim | Release evidence |
| --- | --- |
| Generated payload | Claude/Codex manifests validated; generated view matches 12 files; full local suite 102/102 passed with unchanged tested files |
| Public source | `whichguy/workflow-engine`, qualified code candidate `219e290`; anonymous manifest fetch returned HTTP 200 |
| Fresh host installation | Codex and Claude installed the published source SHA through the isolated candidate catalog |
| Installed helper | Both installed packages completed Braid; cold recovery left file hashes unchanged |
| Installed prompt packaging | Codex Weave/Backchain: six prompt-entry checks passed; Claude installed pair: Braid prompt check passed; plans in these checks are authored fixtures |
| Separate dependencies | Backchain 0.3.4, Until Loop 0.4.0-rc.2 and ask-agent 0.3.0 installed separately in both disposable profiles; latest ask-agent card additionally checked after source drift |
| Source CI | Four macOS/Linux jobs passed on Python 3.10/3.13; each selected 102 tests, passed 89 and skipped 13 requiring private Backchain |
| Native Codex execution | Two fresh `worker` tasks wrote Alpha/Beta; actual notifications collected; first acceptance left the other required leaf pending; both accepted before completion |
| Native prompt planning | A fresh Codex worker used installed Backchain and Until Loop, retained the real terminal receipt, and produced eight explicit command steps; the parent accepted and executed all eight, including both verification leaves |
| Native execution in other hosts | Not exercised |

[Candidate evidence](evidence/marketplace-candidate.json) binds the installed
packages and scope. All 23 entries of the pre-drift candidate passed authenticated
full-payload verification with zero failures/advisories. That run used ask-agent
`05c3329`; its replacement `6a120ed` separately passed a focused payload check
with zero failures/advisories. An initial unauthenticated attempt could
not read private Backchain and hit GitHub's public API limit; the authenticated
rerun used the existing `gh` login without storing credentials. The final tagged
Weave substitution also passed a focused payload check. Public promotion is
independently verified above, not inferred from these candidate checks.

Validation uses disposable profiles and isolated release checkouts. It does not
replace normal installs or restore unrelated concurrent changes. The baseline
guard observed a changed normal Codex config and an added Grok experimental
ask-agent link while this task ran; both were left intact. The hash guard alone
does not attribute the config change. Distribution
reports distinguish discovery, installation, execution, authentication and public
availability.
