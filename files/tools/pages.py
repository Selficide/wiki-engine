"""List wiki pages compactly: one line per page with type, topics and aliases.

Replaces reading index.md plus many page files when checking what already exists
(the schema's "update before you create" rule). Read-only.

Usage:
  python tools/pages.py                    # every page, grouped by folder
  python tools/pages.py --topic qr-codes   # only pages in one topic
  python tools/pages.py --type concept     # only one page type
  python tools/pages.py --search "harness" # title/alias match (loose, any word order)
  python tools/pages.py --tags --dates     # add tags / created+updated columns
  python tools/pages.py --topic X --summary  # one topic's catalog, with each page's summary
  python tools/pages.py --sizes            # add each page's size; --sort-size lists largest first
"""
import argparse

from vaultlib import norm, utf8_stdout, wiki_pages


def matches(page, query):
    words = norm(query).split()
    haystack = " | ".join(norm(n) for n in [page.name, *page.aliases])
    return all(w in haystack for w in words)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--topic")
    ap.add_argument("--type")
    ap.add_argument("--search")
    ap.add_argument("--tags", action="store_true")
    ap.add_argument("--dates", action="store_true")
    ap.add_argument("--summary", action="store_true", help="add each page's summary: line")
    ap.add_argument("--sizes", action="store_true", help="add each page's size in KB")
    ap.add_argument("--sort-size", action="store_true", help="largest pages first (one flat list)")
    args = ap.parse_args()

    pages = wiki_pages()
    if args.topic:
        pages = [p for p in pages if args.topic in p.topics]
    if args.type:
        pages = [p for p in pages if p.type == args.type]
    if args.search:
        pages = [p for p in pages if matches(p, args.search)]

    if args.sort_size:
        pages = sorted(pages, key=lambda p: -len(p.text.encode("utf-8")))
    folder = None
    for p in pages:
        if p.folder != folder and not args.sort_size:
            folder = p.folder
            print(f"## {folder or 'wiki'}")
        kind = (p.type or "?") + (", hub" if p.hub else "")
        parts = [p.name, f"[{kind}]", "{" + ", ".join(p.topics) + "}"]
        if p.aliases:
            parts.append("aka: " + "; ".join(p.aliases))
        if args.tags and p.tags:
            parts.append("tags: " + ", ".join(p.tags))
        if args.summary and p.summary:
            parts.append("— " + p.summary)
        if args.sizes or args.sort_size:
            parts.append(f"{len(p.text.encode('utf-8')) / 1000:.1f}KB")
        if args.dates:
            parts.append(f"{p.meta.get('created', '?')}..{p.meta.get('updated', '?')}")
        print(" ".join(parts))
    print(f"({len(pages)} pages)")


if __name__ == "__main__":
    main()
