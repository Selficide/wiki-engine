# Wiki engine

Rules, Claude Code commands and Python scripts for running a personal wiki that an LLM maintains, following Andrej
Karpathy's "LLM Wiki" pattern. You drop in sources (articles, papers, notes) and ask questions; Claude reads the
sources, writes and links the wiki pages, cites every claim, and keeps the whole thing consistent.

## What you get
- **Rules** (`meta/Engine.md`) for how the wiki is organized and written: immutable raw sources, cited claims,
  evidence tiers for links between pages, topics grouped into domains, page-size limits. Each rule's reason is in
  `meta/Rationale.md`.
- **Workflows** for Claude Code: `/ingest` (sources into pages), `/ask` (answer from the wiki, optionally file the
  answer back), `/lint` (health check).
- **Scripts** (`tools/`, Python standard library only):
  - link checking, frontmatter validation and index generation;
  - safe renames and source bookkeeping;
  - HTML-to-Markdown extraction for fetched articles.
- **A vault template**: a new vault starts with the folders, a schema file for its own rules, and a decision log.

## Requirements
- [Claude Code](https://claude.com/claude-code).
- Python 3.10+ on your PATH as `python`. On macOS and Linux, if only `python3` exists, add an alias.
- git.
- A Markdown viewer that understands wikilinks (see below).

## File format and viewers
A vault is a folder of plain Markdown files using:
- YAML frontmatter;
- `[[wikilinks]]` resolved by file name;
- callouts (`> [!note]`).

Nothing in the engine requires a particular app: the scripts and Claude do all the work.

- **Recommended:** [Obsidian](https://obsidian.md) (free, closed-source). The template includes a minimal `.obsidian/` config.
- **Also works:**
  - VS Code with the Foam extension;
  - Zettlr;
  - Logseq (partly);
  - [Quartz](https://quartz.jzhao.xyz) to publish a vault as a website.
- **Plain viewers** (GitHub, any editor) show wikilinks as bracketed text. Callouts appear as ordinary quote blocks.

The engine's rules require any non-standard syntax to stay readable as plain Markdown, so a vault never depends on one app.

## Quick start
```
git clone <this repo> wiki-engine
python wiki-engine/engine.py init my-wiki --name "My Wiki"
cd my-wiki
claude
```
Then:
- add a source by giving `/ingest` a URL or a file in `raw/`;
- ask questions with `/ask`;
- run `/lint` now and then.

The first ingest on a new subject creates its topic, and Claude will ask how you want it organized.

Your vault's own rules go in `meta/Schema.md`. That includes page types beyond the built-in source and synthesis pages, declared in `meta/vault.json`. Where `Schema.md` disagrees with `Engine.md`, `Schema.md` wins.

## Updating a vault
Each vault keeps a committed copy of the engine files. `meta/ENGINE` records the version and a hash of each file.
```
python wiki-engine/engine.py sync my-wiki            # dry run: what would change
python wiki-engine/engine.py sync my-wiki --write    # apply; then commit in the vault
```
If you edited an engine file inside your vault, `sync` refuses to overwrite it. Move that change into `Schema.md`, or pass `--force` to discard it.

## Optional: cross-model review
Ingests can be checked by a model from a different family, which catches claims the writer generalized or invented.
This needs a tool that sends a read-only review request to the other model, such as an MCP server. Describe it in
your own Claude Code instructions (`~/.claude/CLAUDE.md`), not in a vault: which tool to call, and how to check quota
and record outcomes if it supports that. Without one, the step is skipped and the log says so.

## Changing the engine
1. Edit under `files/` and test against your vaults (sync, then run each vault's tools).
2. Bump `ENGINE_VERSION`, add a `CHANGELOG.md` entry, and update `files/meta/Rationale.md` if a rule's reason changed.
3. Commit here, then sync each vault and commit there.

## Layout
- `files/`: engine-owned files, at the paths they take inside a vault:
  - `meta/Engine.md`
  - `meta/Rationale.md`
  - `.claude/commands/`
  - `tools/`
  - `.gitattributes`
- `template/`: what `init` writes once into a new vault, which then owns it. It includes:
  - `CLAUDE.md`
  - `meta/Schema.md`, `meta/vault.json`, `meta/Decisions.md` and `meta/Ideas.md`
  - `wiki/log.md`
  - permission settings and Obsidian config
- `engine.py`: `init` and `sync`.
- `ENGINE_VERSION`, `CHANGELOG.md`.
