# Weave — workflow plugin

Generated from `skills/workflow` in [workflow-engine](https://github.com/whichguy/workflow-engine). Edit the canonical source, then run `python3 scripts/sync-plugin-view.py`.

Load [the workflow skill](skills/workflow/SKILL.md). Bind its bundled `scripts/workflow` by absolute path; Python 3.10+ on macOS/Linux is required. The skill follows script-issued packets until every required step has an accepted receipt.

[Conditional dependencies](skills/workflow/references/dependencies.md) are separately selected: Backchain/Until Loop for planning and ask-agent for native delegation. They are reused, never copied into this plugin. Command-only recipes need none of them.

[Examples and installation](https://github.com/whichguy/workflow-engine#install-from-skill-craft-market) are maintained in the standalone repository.
