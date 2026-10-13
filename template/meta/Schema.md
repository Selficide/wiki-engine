# {{NAME}} Schema

This vault's own rules. Read `meta/Engine.md` first; where this file conflicts with it, this file wins.
Reasons for the rules here are in [[Decisions]].

## Page types
Declared in `meta/vault.json` (folder, index label, extra frontmatter fields). Every vault has source and synthesis
pages (templates in `Engine.md`). Add the vault's other types here, each with its folder, purpose, extra fields,
and template.

## Vault-specific rules
None yet.

## Cross-model reviewer
None configured, so ingests skip cross-model review (`Engine.md`, "Cross-model review"). To enable it, name the tool
here: how to send a review request, and how to check quota and label runs if it supports them.

## Vault tools
None yet. Scripts added to `tools/` that aren't engine-owned (see `meta/ENGINE`) are listed here.
