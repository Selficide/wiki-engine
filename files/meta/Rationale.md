# Rationale

Why the rules in [[Engine]] are the way they are, under the same headings. Read this when considering a rule change,
not routinely. It describes the engine's current rules and changes with them (the engine's `CHANGELOG.md` records
when). A vault's own dated decisions are in its `meta/Decisions.md`.

## Rule changes
- **Rules live in `meta/`, not `CLAUDE.md`.** `CLAUDE.md` loads into every session, so it stays a short pointer.
  Commands load only when invoked, so the rules they read cost nothing until wiki work happens. `CLAUDE.md` names
  the rule files in plain text rather than importing them, because imports load eagerly.
- **Claude's own rule changes are applied but marked Proposed.** A reasonable rule change made mid-ingest otherwise
  leaves no trace that it wasn't ratified. The log should show who decided, not just what. Applying immediately (not
  blocking) keeps batch work moving, and git makes it reversible. Switch to blocking if Proposed entries pile up
  unreviewed or one causes damage before review.
- **Engine and vault are separate.** Rules, commands and scripts are shared by several vaults; topics, content and
  decision history belong to one. Mixing them means a vault can't be created or handed on without hand-scrubbing,
  and fixes to the system have to be repeated per vault.

## Layers
- **`raw/` is immutable.** Every wiki claim traces to a file that can't drift underneath it.
- **Fetched pages are stored as paraphrased extracts.** A fetch tool's output isn't a faithful copy, so "verbatim"
  would mislead, and whole copyrighted articles shouldn't be reproduced. An extract that keeps thesis, claims,
  numbers and names is enough, and the URL recovers the original. Owner-supplied text can be verbatim.
- **Failed fetches become stub raw files.** The URL isn't lost, and `/lint` keeps reminding the owner; a chat
  mention is forgotten. A later raw file with the same URL supersedes the stub, because stubs can't be edited.
- **`cache/` holds downloads and is not a source layer.** Documentation sets and saved pages are large, mostly unread,
  and re-downloadable. Committing them bloats git; treating them as sources would break "every raw file has a source
  page". Extracting the needed part keeps sources small. Downloaded files are untrusted, hence one folder each and
  `python -I`.
- **Owner-saved pages go through `cache/inbox/`.** A saved page is mostly styles and scripts; the converted `.md` is
  the durable record, and the HTML stays local.
- **Vault-design notes go in `meta/Ideas.md`.** Notes about maintaining the vault aren't knowledge from a source,
  and keeping them in one backlog makes them easy to act on.

## Topics
- **Several topics can share a vault.** For an LLM-maintained vault the real costs are per-command reading and
  duplicated rules. Topic hubs keep `/ask` reading only the relevant topic, and one rule set avoids drift.
  `topics:` makes a later split mechanical.
- **Hubs are the topic registry.** A separate list would record "this topic exists" twice, and it would put the
  owner's data inside the rules. Hubs already exist one per topic.
- **Tags are a per-topic vocabulary.** Free-form tags drift into synonyms and duplicate topics and fields.
- **Split triggers.** A privacy boundary, different templates or rules, temporary work, or answers bleeding across
  topics are concrete reasons to split. Splitting without one only duplicates cost.

## Naming
- **Domain-specific names carry their domain.** Page names are vault-wide keys (Obsidian links by filename), and
  generic names ("Security", "Testing") will be wanted by several topics. Qualifying early avoids renames later.
- **Renames go through `rename.py`.** A rename done by hand or by moving the file breaks every inbound link; Obsidian
  only fixes links for renames made inside the app.

## Raw file format
- `fetch_status` and `capture` are separate because reachability and what was kept vary independently.
- `supplied_by:` and `origin:` record where an owner-supplied document came from, including whether it was
  AI-generated, which bears on how far to trust it.

## Links
- **Links between pages need evidence, in three tiers.** Matching on abstractions connects almost anything, and
  links produced to support an argument inherit authority they didn't earn. Weak links also pollute the graph and
  send `/ask` down false trails. Tier 2 keeps mechanism-level insight no single source states, labeled so the owner
  can judge it. Tighten to tier 1 if tier-2 marks turn out to be mostly noise.
- **Anchors only for long sources.** Source pages have a fixed template, so an anchor only adds precision when the
  page mirrors the raw file's structure. Most raw files are small; anchors cost effort on every citation and break
  silently when headings change.

## Frontmatter
- **`sources:` is generated from body citations.** Two copies of one fact kept by hand drift, and drift grows with
  every ingest. Deriving the copy removes the failure instead of policing it, while keeping Obsidian's Properties view.
- **`summary:` feeds a generated index.** A hand-kept index is a third copy of facts already on pages.
- **Type-specific fields are declared in `vault.json`.** Scripts can then check them without the engine knowing any
  vault's page types.

## Page templates
- **Source pages are separate from the pages that combine sources.** It keeps disagreement visible instead of
  blending sources into one voice, makes claims traceable, and lets lint flag claims a newer source contradicts.

## Writing rules
- **Prefer primary sources.** Secondary write-ups drift from the original.
- **Dated prose, not freshness fields.** A `reviewed:` date per page would be a hand-kept judgment field. Decay is
  concentrated in a few topics, so a topic opts in with `stale_after:` and evidence age is computed from source
  dates. A date in the sentence costs nothing and tells a reader how far to trust it.
- **Split pages over 15 KB.** Pages that accumulate a bullet per source degrade into source-by-source lists.

## Domains
Drawn from how other systems group large collections (researched 2026-10-13):
- **A small, fixed top level.** Dewey's 10 classes and Johnny.Decimal's 10 areas keep the top level broad and filing
  decisions few.
- **Groups only when material exists.** This is the Library of Congress's "literary warrant", and why topics need
  hubs.
- **One home plus cross-lists.** arXiv's model: a primary category plus cross-listings.
- **Pages go in the most specific group, and groups form a strict tree.** Wikipedia's categories, which allow several
  parents, sprawl.
- **Cross-cutting aspects become facets, not branches.** ACM's 2012 classification, which stopped repeating testing
  and performance under every branch.
- **Search, not directories, at large scale.** The fate of Yahoo and DMOZ.

The domain lives only on hubs so a reorganization re-labels hubs, never pages.

## Tools
- **Scripts for mechanical checks.** Checks like broken links, orphans, and "does this page exist" otherwise mean
  reading dozens of pages each run, at a cost that grows with the vault. A script does it exactly and prints only
  results.
- **Tracked in git, allowlisted, stdlib only.** The owner can review every line, and the allowlist skips prompts only
  for reviewed code. No packages means nothing to install and no supply chain to trust.
- **Layout-specific HTML extractors.** Precise where markup is regular (Sphinx), with a generic article extractor
  for everything else. The injection check reports hidden or instruction-like text rather than keeping it silently.

## Jev (optional)
- **Why a second, small model at all.** Some checks are many narrow judgments over the same text: is this paragraph
  addressed to an AI reader, does this source support this claim, which page covers this question. A typed,
  probability-returning model does those in one cheap request, and its answers can be thresholded in code instead
  of parsed from prose.
- **What the evaluations showed** (in the vault where the tools were built, October 2026; vendor model, small test
  sets, partly tuned on the same data):
  - injection screen: 30 of 30 planted injections flagged at "possible" and 24 at "likely", against 2 for the
    extractor's regex, with "likely" false alarms on 2 of 81 clean pages. Most false alarms were prompts a page
    shows as examples, which a separate "is this framed as an example?" question tempers;
  - claim checks: all 58 planted errors flagged; on 249 claims a cross-model review had passed, 2 real miscitations
    found among 8 flags;
  - page search: a right page ranked first for 32 of 33 plain-language questions, against 15 for keyword search,
    and a coverage score that separated covered from uncovered questions (0.51 or more, against 0.02).
- **Why advisory everywhere.** TypeSafe's own documentation says adversarial content can move Jev's answers, and
  half the claim-check flags were leads or noise rather than errors. Every finding is checked by Claude or the
  owner before it changes anything.
- **Why the safeguards are in code.** The tool runs without a prompt and uploads files, so a successful prompt
  injection could try to use it as a channel. The vault-only path rule and the absence of a raw-request command
  turn that into an error rather than an upload.
- **Why optional, and why the key name is configurable.** It needs a paid account, it sends content off the
  machine, and people name their environment variables differently. Defaulting to the vendor's name and allowing a
  local override means no one inherits another person's setup.
- **Why claim checks before the cross-model review, but hidden from it.** They catch a different kind of mistake
  (claims cited to a source that doesn't state them) for a fraction of the cost, and keeping the reviewer blind to
  them keeps the review independent.

## File format
Treating the format, not the app, as the requirement keeps vaults readable anywhere: in GitHub, in a code
editor, or after Obsidian. Obsidian is closed-source; the files outlive it. Wikilinks by name stay, because
path-based Markdown links break whenever a file moves.

## Cross-model review
Reviews of ingests by a model from another family found real fidelity errors the writer missed: generalized claims,
dropped hedges, unsupported attributions, omissions. A same-family reviewer risks sharing the writer's blind spots and
preferring its own text. Reviewers miss copies of an error on pages they weren't given, hence the search step.
Reviewing only larger ingests saves quota. It's optional because it needs a second model the owner has access to;
the rest of the engine works without it. The reviewer is described in the owner's own instructions, not in the vault,
because it's a property of their machine: a vault that named it would break or mislead when copied or shared.

## Bookkeeping
- **Commit after every workflow.** Every AI change is diffable and reversible, and the git log is an audit trail
  next to `wiki/log.md`.
- **Incremental lint.** Judgment checks on pages changed since the last `Lint:` commit keep lint cost proportional
  to the work rather than to the vault; scripted checks are cheap enough to stay vault-wide.

## Ingest modes
Discussing each source builds real understanding; for bulk, related material, batch with diff review is enough.

## Engine updates
A committed copy of the engine in each vault keeps Obsidian, the permission allowlist and plain `python tools/...`
working unchanged, and every engine update arrives as a reviewable diff. The hash manifest catches edits made inside
a vault, which a sync would otherwise silently overwrite. A Claude Code plugin would avoid the copies, but its
interaction with project allowlists is unverified.
