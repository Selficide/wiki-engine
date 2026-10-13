# Changelog

## 0.2.0 (2026-10-13)
- **Domains:** an optional `"domains"` list in `meta/vault.json`, and `domain:` on top-level hubs (sub-topics
  inherit it). `frontmatter.py` checks them.
- **Index:**
  - `index.md` opens with a map grouped by domain.
  - Each topic's page list is a collapsed Obsidian callout under its domain's heading.
  - Vaults without domains get one group.
- **Rules:**
  - A page's first topic is its home.
  - Sub-topics go at most one level deep.
  - Index scale triggers: per-domain index files at about 100 KB, local search at about 1,000 pages.

## 0.1.1 (2026-10-12)
- `build_index.py` skips dotfiles (e.g. `.gitkeep`) in `raw/`, so a new vault's empty folders don't show up as assets.

## 0.1.0 (2026-10-12)
Extracted from the Mind Palace vault (its decisions D-001 to D-027).
- Rules split: generic rules in `meta/Engine.md`; each vault's own rules in `meta/Schema.md`, which wins on conflict.
  Reasons moved from the dated decision log into `meta/Rationale.md`.
- Page types are configured per vault in `meta/vault.json` (folder, index label, extra fields with required /
  values / format / pattern). `frontmatter.py` and `build_index.py` read it; `source` and `synthesis` are built in.
- Commands read `Engine.md` then `Schema.md`, and no longer name concept or entity pages.
- `engine.py init` and `sync`, with a hash manifest in each vault's `meta/ENGINE`.
