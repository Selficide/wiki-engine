"""Structural link and provenance checks for /lint and /ingest. Read-only.

Reports:
  - broken [[links]] (no file with that name anywhere in the vault)
  - links that only resolve via an alias (Obsidian does not resolve aliases;
    they should be written [[Page|alias]])
  - markdown links between vault pages (should be wikilinks)
  - orphans (no inbound links from other wiki pages; index-only counts as weak)
  - index drift (pages missing from wiki/index.md)
  - links between topics (count; list with --cross-topic)
  - provenance: source pages whose raw: file is missing, raw files no source page
    references (not yet ingested), raw files with fetch_status failed/partial

Usage:
  python tools/links.py
  python tools/links.py --topic qr-codes
  python tools/links.py --cross-topic
"""
import argparse
import re
from collections import defaultdict

from vaultlib import (RAW, ROOT, WIKILINK, link_target, raw_provenance, split_frontmatter, strip_code,
                      utf8_stdout, wiki_pages)

MDLINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(([^)\s]+)\)")
SKIP_DIRS = {".git", ".obsidian", ".claude", ".trash", ".venv", "__pycache__"}


def vault_files():
    """Lower-cased names Obsidian can resolve: .md by stem, other files by full name."""
    names = set()
    for p in ROOT.rglob("*"):
        if not p.is_file() or SKIP_DIRS & set(p.relative_to(ROOT).parts):
            continue
        names.add(p.name.lower())
        if p.suffix == ".md":
            names.add(p.stem.lower())
    return names


def section(title, rows):
    print(f"## {title}: {len(rows) if rows else 'OK'}")
    for r in rows:
        print(f"- {r}")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--topic", help="report only on pages in this topic")
    ap.add_argument("--cross-topic", action="store_true", help="list each cross-topic link")
    args = ap.parse_args()

    all_pages = wiki_pages(include_special=True)
    pages = [p for p in all_pages if not p.special]
    by_name = {p.name.lower(): p for p in pages}
    alias_of = {a.lower(): p.name for p in pages for a in p.aliases}
    files = vault_files()
    in_scope = (lambda p: args.topic in p.topics) if args.topic else (lambda p: True)

    broken, via_alias, md_links, cross = [], [], [], []
    inbound = defaultdict(set)  # target page name -> names of linking pages
    index_links = set()

    for page in all_pages:
        text = strip_code(page.text)
        for m in WIKILINK.finditer(text):
            target = link_target(m.group(1))
            key = target.lower()
            if not target:
                continue  # [[#heading]] within the same page
            if key in by_name:
                dest = by_name[key]
                if page.name == "index" and not page.folder:
                    index_links.add(dest.name)
                elif not page.special and dest.name != page.name:
                    inbound[dest.name].add(page.name)
                    if in_scope(page) and page.topics and dest.topics \
                            and not set(page.topics) & set(dest.topics):
                        cross.append(f"{page.name} {{{', '.join(page.topics)}}} -> "
                                     f"{dest.name} {{{', '.join(dest.topics)}}}")
            elif key in files:
                pass  # raw file, meta page, or asset
            elif not in_scope(page) and not page.special:
                pass
            elif key in alias_of:
                via_alias.append(f"{page.rel}: [[{target}]] -> use [[{alias_of[key]}|{target}]]")
            else:
                broken.append(f"{page.rel}: [[{target}]]")
        if in_scope(page):
            for m in MDLINK.finditer(text):
                href = m.group(1)
                if not re.match(r"^[a-z][a-z0-9+.-]*:|^#", href, re.IGNORECASE):
                    md_links.append(f"{page.rel}: ({href})")

    scoped = [p for p in pages if in_scope(p)]
    orphans = [p.rel for p in scoped if not inbound[p.name] and p.name not in index_links]
    index_only = [p.rel for p in scoped if not inbound[p.name] and p.name in index_links]
    not_indexed = [p.rel for p in scoped if p.name not in index_links]

    # Provenance
    referenced, superseded = raw_provenance(pages)
    missing_raw = []
    for p in pages:
        raw = p.meta.get("raw")
        if p.type != "source" or not raw:
            continue
        if in_scope(p) and not (ROOT / raw).is_file():
            missing_raw.append(f"{p.rel}: raw: {raw}")
    uningested, fetch_problems = [], []
    for f in sorted(RAW.rglob("*.md")):
        rel = f.relative_to(ROOT).as_posix()
        if rel.startswith("raw/assets/") or rel in superseded:
            continue
        if rel not in referenced:
            uningested.append(rel)
        meta, _ = split_frontmatter(f.read_text(encoding="utf-8-sig"))
        status = meta.get("fetch_status")
        if status in ("failed", "partial"):
            fetch_problems.append(f"{rel}: {status}")

    if args.topic:
        print(f"(scope: topic {args.topic}; links still resolve vault-wide)")
    section("Broken links", broken)
    section("Links resolving only via alias", via_alias)
    section("Markdown links to vault files", md_links)
    section("Orphans (no inbound links)", orphans)
    section("Linked only from index", index_only)
    section("Missing from index.md", not_indexed)
    if args.cross_topic:
        section("Cross-topic links", sorted(cross))
    else:
        print(f"## Cross-topic links: {len(cross)} (list with --cross-topic)")
    section("Source pages with missing raw file", missing_raw)
    section("Raw files not referenced by any source page", uningested)
    section("Raw files with failed/partial fetch", fetch_problems)
    print(f"## Failed stubs superseded by a later raw file: {len(superseded)}")
    for rel in sorted(superseded):
        print(f"- {rel}")


if __name__ == "__main__":
    main()
