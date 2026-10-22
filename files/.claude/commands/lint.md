---
description: Health check of the wiki; reports problems, fixes them after approval
argument-hint: "[--topic <slug>] [--full] [--fix]"
---
Read `meta/Engine.md`, then `meta/Schema.md` (the vault's own rules, which win where they conflict), and follow
them throughout.

Arguments: $ARGUMENTS

With `--topic <slug>`, check only pages carrying that slug in `topics:` (structural checks still resolve links
vault-wide).

**Scope.** The scripted checks always cover the whole vault (they're cheap). The judgment checks
(Content, plus the hand-checked Provenance items) cover only the pages from `python tools/changed.py`, which lists
pages changed since the last `Lint:` commit. With `--full`, they cover every page instead, one topic at a time.
Say in the report which scope was used.

## Checks
Start with `python tools/links.py --cross-topic`, `python tools/frontmatter.py`, and `python tools/build_index.py`
(add `--topic <slug>` to the first two if given). Between them they cover broken links, markdown links, orphans, index drift, links between topics, raw-file
provenance, failed or partial fetches, frontmatter fields and values, topic hubs, and alias collisions (a lead for the
duplicates check). Spot-check their findings before reporting them, and do the remaining checks by hand.

**Structural**
- Broken links: `[[targets]]` with no matching filename or alias in the vault.
- Orphans: wiki pages with no inbound links (`index.md` and `log.md` excepted; a link from the index alone is weak).
- Index drift: pages missing from `wiki/index.md`, or index entries pointing at missing pages.
- Frontmatter: missing required fields (including `topics:`), wrong `type` for the folder, `updated` older than `created`.
- Topics: slugs with no hub page, topics with more than one hub, hub fields (`parent:`, `status:`, `tag_vocab:`)
  invalid, tags outside their topic's `tag_vocab:`, hub or index sections out of sync.
- Links between topics: a link from one topic's page to another topic's page needs tier-1 or tier-2 evidence
  like any relationship. List all of them so the owner can see how much the topics actually connect.
- Markdown links used between vault pages (should be wikilinks).

**Provenance**
- Jev claim checks, if configured (`Engine.md`, "Jev"): run `python tools/jev.py claims <page>` on every
  non-source page in the judgment-check scope. Check each flag against the raw file and report only those that
  hold up, under claims without support, with what the raw file actually says, plus a count ("N flags checked,
  M confirmed"). Without a key, say "Jev claim check skipped".
- Raw files with no source page (not yet ingested).
- Source pages whose `raw:` points at a missing file.
- Raw files with `fetch_status: failed` or `partial` (list them so the owner can supply the content).
- Claims on pages other than source pages without a citation.
- Relationship claims that break the link evidence tiers:
  - neither cited (tier 1) nor marked `*(inferred: …)*` (tier 2);
  - marked inferred, but the sentence fails the substitution or usefulness test;
  - analogies (tier 3) outside a synthesis page's `## Speculative` section;
  - anything else `meta/Schema.md` rules out of `wiki/`.

**Content (judgment calls)**
- Likely duplicates: similar titles, overlapping aliases, or pages covering the same idea.
- Stale or contradicted claims: a newer source disagrees and the page hasn't recorded it.
- Thin pages: stubs that could be merged or need more sources.
- Rules in `meta/Schema.md` with no matching entry in `meta/Decisions.md`.
- Decisions with `**Status:** Proposed`. List each with its age and ask the owner to approve or reject it.
  If rejected, add a superseding entry and revert the rule in `meta/Schema.md`.

## Output
1. Report findings grouped by category, most important first, each with the file and a proposed fix.
2. Apply fixes only after the owner approves (or immediately with `--fix`, except merges and deletions, which
   always need approval).
3. Do the bookkeeping: log the lint run (even if clean) and commit, with a message starting `Lint:`. That commit
   marks where the next incremental lint starts, so commit even when only the log changed.
