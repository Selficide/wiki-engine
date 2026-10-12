# Wiki engine

The shared rules, commands and scripts behind LLM-maintained Obsidian wikis (Karpathy's "LLM Wiki" pattern).
Each vault keeps a committed copy of the engine files, so Obsidian, the `python tools/*` permission allowlist,
and plain `python tools/...` calls work unchanged inside it.

Local only: no remote.

## Layout
- `files/`: engine-owned files, at the paths they take inside a vault:
  `meta/Engine.md` (the rules), `meta/Rationale.md` (why), `.claude/commands/`, `tools/`, `.gitattributes`.
- `template/`: what `init` writes once into a new vault, which then owns it: `CLAUDE.md`, `meta/Schema.md`,
  `meta/vault.json`, `meta/Decisions.md`, `meta/Ideas.md`, `wiki/log.md`, settings and Obsidian config.
- `engine.py`: `init` and `sync`.
- `ENGINE_VERSION`, `CHANGELOG.md`.

## Use
```
python engine.py init D:\Dev\new-vault --name "New Vault"
python engine.py sync D:\Dev\mind-palace            # dry run
python engine.py sync D:\Dev\mind-palace --write    # apply; commit in the vault as "Engine: sync to <version>"
```

## Changing the engine
1. Edit under `files/` and test against each vault (sync, then run its tools).
2. Bump `ENGINE_VERSION`, add a `CHANGELOG.md` entry, and update `files/meta/Rationale.md` if a rule's reason changed.
3. Commit here, then sync each vault and commit there.

A vault's page types live in its `meta/vault.json`, so engine scripts never name vault-specific types. Only
`source` and `synthesis` are built in.

## Vaults on this machine
- `D:\Dev\mind-palace`: research and reading.
- `D:\Dev\home-palace`: house, appliances, maintenance.
