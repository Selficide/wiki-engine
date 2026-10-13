---
description: Create a new wiki vault from the wiki engine. Use only when the user runs it.
disable-model-invocation: true
argument-hint: <folder> "<Vault Name>"
---

Create a new LLM-maintained wiki vault.

1. Work out the target folder and the vault's display name from the arguments: $ARGUMENTS
   If either is missing, ask for it. The folder must not exist yet, or be empty.
2. Check that `python --version` (or `python3 --version`) reports 3.10 or newer, and that `git` is available.
   If not, stop and tell the user what to install.
3. Run:
   `python "${CLAUDE_PLUGIN_ROOT}/engine.py" init "<folder>" --name "<Vault Name>"`
   (use `python3` if that's the one available).
4. In the new folder, run `python tools/build_index.py --write`, then `git add -A` and commit with the message
   `Create vault from wiki engine <version>`, where the version is in its `meta/ENGINE` file.
5. Tell the user:
   - the vault is at `<folder>`; open that folder in Claude Code (`cd <folder>`, then `claude`) to work in it;
   - optionally, open it in Obsidian as a vault, or any Markdown editor that understands wikilinks;
   - start with `/ingest <url or file>`, then `/ask`, and `/lint` now and then;
   - the vault's own rules go in `meta/Schema.md`, and the shared rules are in `meta/Engine.md`;
   - after the plugin updates, `/wiki-engine:sync` brings a vault up to date.
