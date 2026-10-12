# {{NAME}}

This folder is an Obsidian vault run as an LLM-maintained wiki, built on the wiki engine (Karpathy's "LLM Wiki"
pattern). The owner supplies sources and questions. Claude maintains the wiki.

- `raw/`: immutable source material. Never edit, rename, or delete anything here.
- `wiki/`: pages Claude maintains. The entry point is `wiki/index.md`.
- `meta/`: how the vault works. Before creating or editing anything in `wiki/` or `raw/`, read `meta/Engine.md`
  (shared engine rules), then `meta/Schema.md` (this vault's own rules, which win where they conflict).
  `meta/Rationale.md` and `meta/Decisions.md` explain why the rules exist. Read them only when changing a rule.
  `meta/Ideas.md` is a backlog of possible vault changes. Read it only when considering one.
- Workflows: `/ingest`, `/ask`, `/lint` (in `.claude/commands/`).
