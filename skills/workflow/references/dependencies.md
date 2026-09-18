# Selected dependencies

Weave owns graph state and transitions. Reused skills own their respective
procedures. Install them separately, then resolve the actual selected `SKILL.md`
from the host's available skill context. Never guess an author's checkout, search
PATH for a similarly named runtime, or use a bundled replacement.

| Entry / action | Required capability | Audited contract |
| --- | --- | --- |
| Authored command or prompt steps | Python 3.10+ and the host doing prompt work | No external skill required |
| Prompt to graph | Explicit Backchain package root with `skills/backchain/SKILL.md`, `harness/run-prompt.sh`, `schema/plan.schema.json`, Bash and Node | Backchain 0.3.4; selected Until Loop owns convergence |
| Backchain convergence | Separately selected Until Loop card and its declared package-relative adapter | Until Loop 0.4.0-rc.2; preserve actual terminal stdout before ephemeral state disappears |
| Agent step | Separately installed ask-agent and host native fresh-context asynchronous dispatch plus collection | ask-agent 0.3.0; parent accepts actual returned results |

The versions identify this release's audit, not permission to skip reading a newer
selected card. Planning persists the explicitly selected Backchain root. Follow
its selected Until Loop binding and retain source identities in the companion.
Agent dispatch is host-owned; a stored handle is a host attestation, not proof
that Weave authenticated a provider or can reconnect in another session.

Use `block` before preparing an agent launch when prerequisites are missing.
Once launch intent exists, the worker may already exist: use reconciliation and
the script's confirmed-stop retry, never the pre-launch unavailable path.

Backchain, Until Loop and ask-agent are independently distributed in
`skill-craft-market`. Backchain may require authenticated repository access.
For prompt entry, the selected Backchain package must include the complete
packaging harness/schema; a copied card alone is insufficient. Weave has no
automatic dependency installer. Command-only use does not require access to
Backchain. Improve and ShipLoop remain separate applications, not dependencies
automatically invoked for every node.
