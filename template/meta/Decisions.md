# Decisions

Why this vault's own rules (in [[Schema]]) are the way they are. The engine's rules are explained in [[Rationale]].
Append-only: to reverse a decision, add a new entry that supersedes the old one rather than editing it.
Read this when considering a rule change, not routinely.

Format: `## D-NNN: Title (date)`, then **Decision**, **Why**, **Alternatives**, **Revisit if**, optionally
**Supersedes**, then **Status** (`Proposed` or `Approved by owner (date)`). The only allowed edit to an existing
entry is updating its Status line.

---

## D-001: Vault created from wiki engine {{VERSION}} ({{DATE}})
**Decision:** This vault follows the wiki engine's rules (`meta/Engine.md`), with its own rules in `meta/Schema.md`.
**Why:** Shared rules, commands and scripts, maintained in one place and synced into each vault.
**Alternatives:** A hand copy of another vault's rules (drifts, and carries that vault's data along).
**Revisit if:** This vault's rules diverge so far from the engine that overrides outnumber shared rules.
**Status:** Approved by owner ({{DATE}}).
