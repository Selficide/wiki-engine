"""Extract compact markdown from a Sphinx-built HTML page (e.g. docs.python.org). Read-only.

Specialist for Sphinx's regular markup: section ids, `dl.py` API entries keyed by qualified name,
`highlight-<lang>` code blocks, admonitions and version notes. For news articles and blog posts
use extract_article.py instead. Cheapest modes first:

  python -I tools/extract_sphinx.py FILE                 # --toc: sections, sizes, API counts
  python -I tools/extract_sphinx.py FILE --list-api      # every documented name + first sentence
  python -I tools/extract_sphinx.py FILE --api pathlib.Path.glob
  python -I tools/extract_sphinx.py FILE --section basic-use
  python -I tools/extract_sphinx.py FILE --all           # the whole main content

--api shows nested entries of a class as a one-line list; add --deep for them in full.
Downloaded HTML is untrusted: run with -I. Reads local files only; never downloads.
"""
import argparse
import difflib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops tools/; add it back
from htmlmd import Node, Renderer, child_nodes, parse, utf8_stdout, wrap, ws  # noqa: E402

CODE_LANG = {"python3": "python", "python": "python", "pycon": "pycon", "default": "",
             "none": "", "text": "", "shell": "sh", "sh": "sh", "c": "c", "ini": "ini"}
SIG_PREFIXES = ("class", "classmethod", "staticmethod", "exception", "property", "async",
                "abstractmethod")


def is_api(node):
    return node.tag == "dl" and "py" in node.classes


def api_kind(dl):
    return " ".join(sorted(dl.classes - {"py"})) or "entry"


class SphinxRenderer(Renderer):
    def __init__(self, deep=True):
        super().__init__()
        self.deep = deep
        self.api_depth = 0

    def first_sentence(self, dd, limit=160):
        p = next((n for n in dd.iter() if n.tag == "p"), None)
        text = ws(self.plain(p)) if p else ""
        m = re.match(r"(.+?[.:])(\s|$)", text)
        text = m.group(1) if m else text
        return text if len(text) <= limit else text[:limit - 1] + "…"

    def block(self, n):
        cls = n.classes
        if n.tag == "p" and "admonition-title" in cls:
            return []
        if n.tag == "div":
            lang = next((c[len("highlight-"):] for c in cls if c.startswith("highlight-")), None)
            if lang is not None:
                pre = next((x for x in n.iter() if x.tag == "pre"), None)
                return [self.fence(pre, CODE_LANG.get(lang, lang))] if pre else []
            if "admonition" in cls:
                return [self.admonition(n)]
            if cls & {"versionadded", "versionchanged", "deprecated", "deprecated-removed"}:
                return [self.version_note(n)]
        if is_api(n):
            return self.api(n)
        return super().block(n)

    def admonition(self, n):
        title = next((ws(self.plain(c)) for c in child_nodes(n) if "admonition-title" in c.classes),
                     "Note")
        body = self.render(n).replace("\n\n", "\n")
        lines = body.splitlines() or [""]
        return "\n".join([f"> **{title}:** {lines[0]}"] + ["> " + line for line in lines[1:]])

    def version_note(self, n):
        label = next((x for x in n.iter() if "versionmodified" in x.classes), None)
        label_text = ws(self.plain(label)) if label else ""
        text = ws(self.inline(n))
        if label_text and text.startswith(label_text):
            return f"*{label_text}* {text[len(label_text):].strip()}"
        return f"*{text}*"

    def api(self, dl):
        kind = api_kind(dl)
        dts = child_nodes(dl, "dt")
        dd = next(iter(child_nodes(dl, "dd")), None)
        if self.api_depth > 0 and not self.deep:
            names = ", ".join(f"`{ws(self.plain(dt))}`" for dt in dts)
            return [f"- {kind} {names}: {self.first_sentence(dd) if dd else ''}"]
        sigs = [ws(self.plain(dt)) for dt in dts]
        # Sphinx already prefixes some signatures ("class ...", "classmethod ..."); don't repeat it
        out = [f"`{s}`" if s.split(" ", 1)[0] in (kind, *SIG_PREFIXES) else f"**{kind}** `{s}`"
               for s in sigs]
        if dd is not None:
            self.api_depth += 1
            body = self.blocks(dd)
            self.api_depth -= 1
            merged = []  # one-line nested summaries read better as a single list
            for b in body:
                if merged and b.startswith("- ") and merged[-1].startswith("- "):
                    merged[-1] += "\n" + b
                else:
                    merged.append(b)
            out.extend(merged)
        return out


def main_content(root):
    for n in root.iter():
        if n.attrs.get("role") == "main" or (n.tag == "div" and "body" in n.classes):
            return n
    return next((n for n in root.iter() if n.tag in ("main", "article")), None) or root


def heading_of(section):
    return next((c for c in child_nodes(section) if re.fullmatch(r"h[1-6]", c.tag)), None)


def toc(body):
    r = SphinxRenderer()

    def walk(node, depth):
        for c in child_nodes(node):
            if c.tag == "section":
                h = heading_of(c)
                title = ws(r.plain(h)) if h else ""
                size = len(SphinxRenderer().render(c))
                apis = sum(1 for x in c.iter() if x.tag == "dt" and x.attrs.get("id")
                           and x.parent is not None and is_api(x.parent))
                print(f"{'  ' * depth}{c.attrs.get('id', '?')}: {title} "
                      f"({size / 1000:.1f}k chars, {apis} api)")
                walk(c, depth + 1)
            else:
                walk(c, depth)
    walk(body, 0)


def api_ids(body):
    return [x for x in body.iter() if x.tag == "dt" and x.attrs.get("id")
            and x.parent is not None and is_api(x.parent)]


def not_found(kind, wanted, options):
    close = difflib.get_close_matches(wanted, options, n=8, cutoff=0.5)
    print(f"No {kind} with id {wanted!r}." + (" Close matches: " + ", ".join(close) if close else ""))
    sys.exit(1)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--toc", action="store_true", help="section outline (default)")
    mode.add_argument("--list-api", action="store_true")
    mode.add_argument("--api", metavar="ID")
    mode.add_argument("--section", metavar="ID")
    mode.add_argument("--all", action="store_true")
    ap.add_argument("--deep", action="store_true", help="with --api: nested entries in full")
    args = ap.parse_args()

    body = main_content(parse(args.file))

    if args.list_api:
        r = SphinxRenderer()
        for dt in api_ids(body):
            dd = next(iter(child_nodes(dt.parent, "dd")), None)
            print(f"{api_kind(dt.parent)} {dt.attrs['id']}: {r.first_sentence(dd) if dd else ''}")
        return
    if args.api:
        dts = api_ids(body)
        dt = next((d for d in dts if d.attrs["id"] == args.api), None)
        if dt is None:
            not_found("API entry", args.api, [d.attrs["id"] for d in dts])
        text = SphinxRenderer(deep=args.deep).render(wrap(dt.parent))
    elif args.section:
        sections = [n for n in body.iter() if n.tag == "section" and n.attrs.get("id")]
        sec = next((s for s in sections if s.attrs["id"] == args.section), None)
        if sec is None:
            not_found("section", args.section, [s.attrs["id"] for s in sections])
        text = SphinxRenderer().render(wrap(sec))
    elif args.all:
        text = SphinxRenderer().render(body)
    else:
        toc(body)
        return
    print(text)
    print(f"\n<!-- {len(text)} chars -->")


if __name__ == "__main__":
    main()
