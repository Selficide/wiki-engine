"""Rename a wiki page and rewrite every link to it. All renames go through this script.

Dry run by default: shows the file move and every link it would rewrite. `--write` applies it.

What it does on --write:
  - moves wiki/<folder>/<Old>.md to wiki/<folder>/<New>.md (same folder)
  - rewrites links in wiki/ and meta/: [[Old]], [[Old|x]], [[Old#h]], [[Old#h|x]], ![[Old]],
    [[Old\\|x]] (tables), case variants, and path forms; sources: entries are links too
  - adds the old name to the page's aliases: (unless --no-alias), so searches still find it
  - regenerates wiki/index.md and runs tools/links.py to confirm nothing is broken
Links inside raw/ are reported, never edited (raw files are immutable).
Bare [[Old]] links become [[New]], like Obsidian's own rename; links with display text keep it.
Content dates (updated:) are not bumped: a rename isn't a content change.

Usage:
  python tools/rename.py "Old Name" "New Name"
  python tools/rename.py "Old Name" "New Name" --write
"""
import argparse
import re
import subprocess
import sys

from vaultlib import RAW, ROOT, WIKI, utf8_stdout, wiki_pages, yaml_str

FORBIDDEN = set('\\/:*?"<>|#^[]')  # Windows filenames plus Obsidian's link syntax
LINK = re.compile(r"(!?\[\[)([^\]\n]+?)(\]\])")


def target_parts(inner):
    """Split link contents into (path prefix, name, rest) where rest is #heading and/or |alias."""
    m = re.match(r"^([^|#\\]*?)((?:\\?\||#).*)?$", inner)
    target, rest = m.group(1), m.group(2) or ""
    prefix, _, name = target.rpartition("/")
    return (prefix + "/" if prefix else ""), name, rest


def rewrite_links(text, old, new):
    count = 0

    def repl(m):
        nonlocal count
        prefix, name, rest = target_parts(m.group(2))
        if name.strip().lower() != old.lower():
            return m.group(0)
        count += 1
        return f"{m.group(1)}{prefix}{new}{rest}{m.group(3)}"
    return LINK.sub(repl, text), count


def add_alias(text, alias):
    """Add alias to an inline aliases: [...] list (or create one) inside the frontmatter."""
    end = text.find("\n---", 3)
    fm, rest = text[:end + 1], text[end + 1:]
    m = re.search(r"^aliases:[ \t]*\[(.*)\][ \t]*$", fm, re.M)
    if m:
        items = m.group(1).strip()
        quoted = yaml_str(alias) if re.search(r"[,:#\[\]{}\"']", alias) else alias
        new_line = f"aliases: [{items + ', ' if items else ''}{quoted}]"
        fm = fm[:m.start()] + new_line + fm[m.end():]
    elif not re.search(r"^aliases:", fm, re.M):
        fm = re.sub(r"^(type:[^\n]*\n)", lambda x: x.group(1) + f"aliases: [{alias}]\n", fm, count=1,
                    flags=re.M)
    else:
        return text, False  # block-style aliases list: leave it to a human
    return fm + rest, True


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--no-alias", action="store_true", help="don't keep the old name as an alias")
    args = ap.parse_args()
    old, new = args.old.strip(), args.new.strip()

    pages = wiki_pages()
    page = next((p for p in pages if p.name == old), None)
    if page is None:
        close = [p.name for p in pages if p.name.lower() == old.lower()]
        sys.exit(f"No wiki page named {old!r}." + (f" Did you mean {close[0]!r}?" if close else ""))
    bad = sorted(FORBIDDEN & set(new))
    if not new or bad:
        sys.exit(f"Invalid new name {new!r}: contains {' '.join(bad)}")
    if new == old:
        sys.exit("New name is the same as the old one.")
    taken = {p.stem.lower() for p in ROOT.rglob("*.md") if ".git" not in p.parts}
    if new.lower() in taken and new.lower() != old.lower():
        sys.exit(f"A file named {new!r} already exists in the vault; page names must be unique.")
    alias_owner = next((p.name for p in pages if new.lower() in (a.lower() for a in p.aliases)
                        and p.name != old), None)
    if alias_owner:
        print(f"Warning: {new!r} is an alias of {alias_owner!r}; consider removing it there.")

    dest = page.path.with_name(new + ".md")
    print(f"Move: {page.rel} -> {dest.relative_to(ROOT).as_posix()}")
    edits = []
    for f in sorted(list(WIKI.rglob("*.md")) + list((ROOT / "meta").rglob("*.md"))):
        if f == WIKI / "index.md":
            continue  # regenerated afterwards
        with open(f, encoding="utf-8", newline="") as fh:
            text = fh.read()
        new_text, n = rewrite_links(text, old, new)
        if n:
            edits.append((f, new_text, n))
            print(f"  {n} link(s) in {f.relative_to(ROOT).as_posix()}")
    raw_hits = []
    for f in sorted(RAW.rglob("*.md")):
        _, n = rewrite_links(f.read_text(encoding="utf-8-sig"), old, new)
        if n:
            raw_hits.append(f.relative_to(ROOT).as_posix())
    if raw_hits:
        print("Links in raw/ (immutable; left as they are, and they'll show as unresolved):")
        for r in raw_hits:
            print(f"  {r}")
    total = sum(n for _, _, n in edits)
    if not args.write:
        print(f"{total} link(s) in {len(edits)} file(s) would be rewritten (run with --write to apply)")
        return

    for f, text, _ in edits:
        with open(f, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    with open(page.path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    if not args.no_alias:
        text, added = add_alias(text, old)
        if not added:
            print("Note: aliases: is a block list; add the old name to it by hand.")
    with open(page.path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    page.path.rename(dest)
    print(f"Renamed; {total} link(s) rewritten in {len(edits)} file(s).")
    for script in ("build_index.py", "links.py"):
        result = subprocess.run([sys.executable, str(ROOT / "tools" / script)] +
                                (["--write"] if script == "build_index.py" else []),
                                capture_output=True, text=True, encoding="utf-8")
        lines = result.stdout.splitlines()
        print(lines[0] if script == "build_index.py" else "\n".join(lines[:2]))


if __name__ == "__main__":
    main()
