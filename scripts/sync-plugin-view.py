#!/usr/bin/env python3
"""Generate/check the distributable view from the one canonical skill tree."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins" / "workflow"


def payload() -> dict[str, bytes]:
    source = ROOT / "skills" / "workflow"
    card = (source / "SKILL.md").read_text()
    version = re.search(r"^version: ([^\n]+)$", card, re.MULTILINE).group(1)
    description = re.search(r"^description: ([^\n]+)$", card, re.MULTILINE).group(1)
    files = {}
    for path in sorted(source.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError(f"Source must be materialized: {path}")
        if path.is_file():
            files["skills/workflow/" + path.relative_to(source).as_posix()] = path.read_bytes()
    common = {
        "name": "workflow", "version": version,
        "description": description,
        "author": {"name": "whichguy", "url": "https://github.com/whichguy"},
        "homepage": "https://github.com/whichguy/workflow-engine",
        "repository": "https://github.com/whichguy/workflow-engine",
        "license": "MIT", "keywords": ["workflow", "weave", "portable-skills", "script-backed"],
    }
    codex = dict(common, skills="./skills/", interface={
        "displayName": "Weave", "shortDescription": "Durable workflows controlled by scripts.",
        "longDescription": common["description"], "developerName": "whichguy",
        "category": "Productivity", "capabilities": ["Read", "Write"],
        "defaultPrompt": ["Use $workflow to execute this workflow or turn my prompt into a plan."],
    })
    for host, manifest in (("claude", common), ("codex", codex)):
        files[f".{host}-plugin/plugin.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    files["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    files["README.md"] = ("# Weave — workflow plugin\n\n"
        "Generated from `skills/workflow` in [workflow-engine](https://github.com/whichguy/workflow-engine). "
        "Edit the canonical source, then run `python3 scripts/sync-plugin-view.py`.\n\n"
        "Load [the workflow skill](skills/workflow/SKILL.md). Bind its bundled "
        "`scripts/workflow` by absolute path; Python 3.10+ on macOS/Linux is required. "
        "The skill follows script-issued packets until every required step has an accepted receipt.\n\n"
        "[Conditional dependencies](skills/workflow/references/dependencies.md) are separately selected: "
        "Backchain/Until Loop for planning and ask-agent for native delegation. "
        "They are reused, never copied into this plugin. Command-only recipes need none of them.\n\n"
        "[Examples and installation](https://github.com/whichguy/workflow-engine#install-from-skill-craft-market) "
        "are maintained in the standalone repository.\n").encode()
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    # Reject directory links before traversing or writing the generated tree.
    # Checking only leaf files would still allow writes through a linked parent.
    for path in (ROOT / "plugins", PACKAGE):
        if path.is_symlink():
            raise ValueError(f"Package directories must not be symlinks: {path}")
    for path in PACKAGE.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Package must be materialized, not a symlink: {path}")
    expected = payload()
    actual = {p.relative_to(PACKAGE).as_posix(): p for p in PACKAGE.rglob("*")
              if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    different = sorted(name for name in expected if name not in actual or
                       actual[name].is_symlink() or actual[name].read_bytes() != expected[name])
    extra = sorted(set(actual) - set(expected))
    if args.check:
        if different or extra:
            print(json.dumps({"status": "drift", "changed_or_missing": different, "extra": extra}))
            return 1
        print(f"PASS: generated workflow package matches {len(expected)} canonical files")
        return 0
    for name in extra:
        actual[name].unlink()
    for name, data in expected.items():
        target = PACKAGE / name
        if target.is_symlink():
            raise ValueError(f"Refusing to overwrite package symlink: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if name == "skills/workflow/scripts/workflow":
            target.chmod(0o755)
    print(f"Generated {len(expected)} files in {PACKAGE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
