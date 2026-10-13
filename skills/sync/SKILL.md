---
description: Update a wiki vault's engine files to the installed wiki engine version. Use only when the user runs it.
disable-model-invocation: true
argument-hint: [vault folder, default: current folder]
---

Bring a wiki vault's engine files (rules, workflows, tools) up to the version in this plugin.

1. The vault is $ARGUMENTS, or the current folder if no argument was given. It must contain `meta/ENGINE`; if it
   doesn't, it isn't an engine vault, so stop and say so.
2. Dry run first: `python "${CLAUDE_PLUGIN_ROOT}/engine.py" sync "<vault>"` (or `python3`). Show the user the
   version change and the files it lists.
3. If it reports files edited inside the vault, stop. Explain that those local edits would be overwritten, and
   suggest moving each change into `meta/Schema.md`. Only pass `--force` if the user explicitly says to discard them.
4. Otherwise apply with `--write`. Then in the vault run `python tools/frontmatter.py`, `python tools/links.py`, and
   `python tools/build_index.py --write`, and report anything new they flag.
5. Show the diff summary (`git status --short`) and commit as `Engine: sync to <version>` unless the user would
   rather review it first. Point them to the plugin's `CHANGELOG.md` entries between the old and new versions.
