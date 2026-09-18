# Standalone distribution

The public repository is `whichguy/workflow-engine`. The portable plugin and skill
identifier is `workflow`; the display name and checkout alias are Weave.

## One source, generated package

`skills/workflow/` is authoritative. Run `python3 scripts/sync-plugin-view.py` to
materialize `plugins/workflow/`; `--check` rejects drift. That package contains
only Weave's card, references and Python scripts plus license, package README and
Claude/Codex manifests. No Backchain, Until Loop, ask-agent or Improve skill bodies
are copied. CI checks parity and the behavioral test suite on macOS/Linux.

The skill-craft-market entry uses a real `git-subdir` (`plugins/workflow`) with a
full immutable commit SHA. Existing source paths and historical run callbacks
remain valid. Do not rename `skills/workflow` to match a display name.

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

The release record below is filled from actual fresh-profile checks. A test of
helper behavior is not a model execution claim. A simulated agent callback is not
proof that a native worker ran. Historical native Codex pilots are recorded in
[VALIDATION.md](VALIDATION.md); this packaging release does not extend them to
Claude, Grok, Hermes or Cursor. Host session resets and per-agent worktree
integration remain future adapters, described in [DEPENDENCY-AUDIT.md](DEPENDENCY-AUDIT.md).

| Claim | Release evidence |
| --- | --- |
| Generated payload | Claude/Codex manifests validated; generated view matches 12 files; full local suite 102/102 passed with unchanged tested files |
| Public source and immutable pin | Pending publication |
| Fresh Codex catalog discovery and install | Pending disposable-profile check |
| Installed helper and complete authored recipe | Pending disposable-profile check |
| Separate dependency availability | Pending ask-agent publication and catalog pin |
| CI | Pending published source and catalog checks |
| Native model execution from installed package | Not exercised by packaging tests |

Normal user profiles, existing skill links and unrelated dirty source/catalog
checkouts are preserved; validation uses disposable profiles and isolated release
checkouts. Distribution reports distinguish discovery, installation, execution,
authentication requirements and public availability.
