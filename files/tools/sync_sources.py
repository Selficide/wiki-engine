"""Regenerate each wiki page's `sources:` frontmatter from the citations in its body.

Body citations are the real record of what a page relies on; `sources:` is a generated
copy for Obsidian's Properties view and for scripts. Never edit it by hand.

Dry run by default: prints what would change. `--write` applies it.
Only the `sources:` line is rewritten; everything else in the file is left byte-for-byte.
Entries still cited keep their order; newly cited sources are appended in body order.
Writes only to wiki/ concept, entity and synthesis pages (source pages have no sources:).

Usage:
  python tools/sync_sources.py            # show changes
  python tools/sync_sources.py --write    # apply them
"""
import argparse
import re
import sys

from vaultlib import cited_sources, frontmatter_sources, utf8_stdout, wiki_pages

BOM = "﻿"
SOURCES_BLOCK = re.compile(r"^sources:[^\n]*\n(?:[ \t]+-[^\n]*\n)*", re.MULTILINE)


def merged(current, cited):
    keep = [s for s in current if s in cited]
    return keep + [s for s in cited if s not in keep]


def render(names):
    return "sources: [" + ", ".join(f'"[[{n}]]"' for n in names) + "]\n"


def rewrite(text, names):
    """Replace (or insert) the sources: line inside the frontmatter block of text.

    Works on LF or CRLF text and keeps its line endings.
    """
    crlf = "\r\n" in text
    if crlf:
        text = text.replace("\r\n", "\n")
    bom = text.startswith(BOM)
    body = text[1:] if bom else text
    end = re.search(r"^---[ \t]*$", body[3:], re.MULTILINE)
    if not body.startswith("---") or not end:
        raise ValueError("no frontmatter block")
    fm_end = 3 + end.start()
    fm, rest = body[:fm_end], body[fm_end:]
    line = render(names)
    if SOURCES_BLOCK.search(fm):
        fm = SOURCES_BLOCK.sub(lambda _: line, fm, count=1)
    else:  # insert where the schema puts it: before created:, else at the end
        created = re.search(r"^created:", fm, re.MULTILINE)
        pos = created.start() if created else len(fm)
        fm = fm[:pos] + line + fm[pos:]
    out = (BOM if bom else "") + fm + rest
    return out.replace("\n", "\r\n") if crlf else out


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="apply the changes")
    args = ap.parse_args()

    pages = wiki_pages()
    sources = {p.name.lower(): p.name for p in pages if p.type == "source"}
    changed = 0
    failed = 0
    for p in pages:
        if p.type == "source":
            continue
        current = frontmatter_sources(p)
        new = merged(current, cited_sources(p, sources))
        if new == current and "sources" in p.meta:
            continue
        changed += 1
        added = [s for s in new if s not in current]
        removed = [s for s in current if s not in new]
        print(f"{p.rel}")
        for s in added:
            print(f"  + {s}")
        for s in removed:
            print(f"  - {s}")
        if not added and not removed:
            print("  (sources: line missing; adding it)" if "sources" not in p.meta
                  else "  (order only)")
        if args.write:
            with open(p.path, encoding="utf-8", newline="") as f:
                text = f.read()
            # Build the new text before opening for writing, so a failure leaves the file untouched.
            try:
                new_text = rewrite(text, new)
            except ValueError as e:
                print(f"  ERROR: {e}; file left unchanged")
                failed += 1
                continue
            with open(p.path, "w", encoding="utf-8", newline="") as f:
                f.write(new_text)
    verb = "updated" if args.write else "would change (run with --write to apply)"
    print(f"{changed - failed} page(s) {verb}")
    if failed:
        print(f"{failed} page(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
