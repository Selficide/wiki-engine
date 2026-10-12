# Changelog

## 0.1.0 (2026-10-12)
Extracted from the Mind Palace vault (its decisions D-001 to D-027).
- Rules split: generic rules in `meta/Engine.md`; each vault's own rules in `meta/Schema.md`, which wins on conflict.
  Reasons moved from the dated decision log into `meta/Rationale.md`.
- Page types are configured per vault in `meta/vault.json` (folder, index label, extra fields with required /
  values / format / pattern). `frontmatter.py` and `build_index.py` read it; `source` and `synthesis` are built in.
- Commands read `Engine.md` then `Schema.md`, and no longer name concept or entity pages.
- `engine.py init` and `sync`, with a hash manifest in each vault's `meta/ENGINE`.
