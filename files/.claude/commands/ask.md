---
description: Answer a question from the wiki, and offer to file the answer back
argument-hint: "[--topic <slug>] <question>"
---
Read `meta/Engine.md`, then `meta/Schema.md` (the vault's own rules, which win where they conflict), and follow
them throughout.

Question: $ARGUMENTS

1. Work out which topic(s) the question belongs to: `--topic` if given, otherwise from the hubs
   (`python tools/pages.py --type synthesis --summary`). Read that topic's catalog with
   `python tools/pages.py --topic <slug> --summary` instead of `wiki/index.md`, and read its hub page.
   Then search `wiki/` (titles, aliases, body text), restricted to pages with that slug in
   `topics:`, and read the relevant ones. Follow links one hop out where useful. Only widen to other topics if the
   question genuinely spans them, and say so in the answer.
2. Answer, citing wiki pages inline as `[[Page]]`. Keep two things clearly separate:
   - what the wiki says, with citations;
   - anything from general knowledge, labeled as such and not cited.
   If the wiki can't answer the question, say so plainly, and suggest which sources would fill the gap.
3. If the answer adds something new (a comparison, a connection between pages, a resolved question), offer to file it:
   - a new synthesis page in `wiki/syntheses/`, or
   - an addition to an existing page, if that's where it belongs.
   Never file general-knowledge claims as cited facts.
4. If the owner accepts, write the page following the rules, then do the bookkeeping (index, log, commit).
