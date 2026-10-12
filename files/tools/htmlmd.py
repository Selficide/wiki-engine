"""Shared HTML -> markdown building blocks for the extract_* tools. Read-only, stdlib only.

The parser only builds a tree from the markup: nothing in a page is executed or fetched.
Scripts that import this run with `python -I`, which keeps tools/ off sys.path, so each one adds
its own directory back explicitly (tools/ holds only reviewed code; the downloaded file's folder
stays off the path, which is what -I protects).
"""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "source", "track", "wbr"}
SKIP = {"script", "style", "template", "noscript", "svg", "canvas", "iframe", "object", "button",
        "select", "textarea"}
INLINE = {"a", "span", "code", "em", "strong", "abbr", "img", "b", "i", "kbd", "samp", "br", "cite",
          "sub", "sup", "small", "mark", "time", "u", "s", "del", "ins", "q", "dfn", "var", "tt"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs or {}), [], parent

    @property
    def classes(self):
        return set((self.attrs.get("class") or "").split())

    def iter(self):
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.iter()

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, [(k, v or "") for k, v in attrs], self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, [(k, v or "") for k, v in attrs], self.stack[-1]))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):  # tolerate unclosed tags
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def decode(data):
    """Bytes -> str using a BOM or <meta charset>, falling back to UTF-8 with replacement."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    m = re.search(rb"""<meta[^>]+charset=["']?([A-Za-z0-9_-]+)""", data[:4096], re.I)
    enc = m.group(1).decode("ascii").lower() if m else "utf-8"
    try:
        return data.decode(enc, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def parse_text(text):
    builder = TreeBuilder()
    builder.feed(text)
    builder.close()
    return builder.root


def parse(path):
    with open(path, "rb") as f:
        return parse_text(decode(f.read()))


def ws(s):
    return re.sub(r"\s+", " ", s).strip()


def child_nodes(node, tag=None):
    return [c for c in node.children if isinstance(c, Node) and (tag is None or c.tag == tag)]


def is_hidden(node):
    """Hidden from readers: hidden attribute, aria-hidden, or inline display:none / visibility:hidden."""
    a = node.attrs
    style = a.get("style", "").replace(" ", "").lower()
    return ("hidden" in a or a.get("aria-hidden", "").lower() == "true"
            or "display:none" in style or "visibility:hidden" in style)


class Renderer:
    """Generic HTML -> markdown. Subclasses override skip() and block() for site-specific markup."""

    def __init__(self, links=False, base_url=""):
        self.links, self.base_url = links, base_url

    # --- hooks -------------------------------------------------------------------------------
    def skip(self, node):
        return node.tag in SKIP or "headerlink" in node.classes or is_hidden(node)

    # --- text ----------------------------------------------------------------------------------
    def raw_text(self, node):
        """Text with whitespace preserved (for <pre>)."""
        if isinstance(node, str):
            return node
        if node.tag in SKIP:
            return ""
        if node.tag == "br":
            return "\n"
        return "".join(self.raw_text(c) for c in node.children)

    def plain(self, node):
        if isinstance(node, str):
            return node
        if self.skip(node):
            return ""
        return "".join(self.plain(c) for c in node.children)

    def inline(self, node):
        if isinstance(node, str):
            return node
        if self.skip(node):
            return ""
        tag, cls = node.tag, node.classes
        if tag in ("code", "kbd", "samp", "tt"):
            text = ws(self.plain(node))
            return f"`{text}`" if text else ""
        if tag == "img":
            alt = ws(node.attrs.get("alt", ""))
            return f"[image: {alt}]" if alt else ""
        if tag == "br":
            return " "
        inner = "".join(self.inline(c) for c in node.children)
        if tag in ("em", "i") and "sig-param" not in cls and inner.strip():
            return f"*{inner.strip()}*"
        if tag in ("strong", "b") and inner.strip():
            return f"**{inner.strip()}**"
        if tag == "a" and self.links and inner.strip():
            href = node.attrs.get("href", "").strip()
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                return f"[{inner.strip()}]({urljoin(self.base_url, href)})"
        return inner

    # --- blocks --------------------------------------------------------------------------------
    def render(self, node):
        return "\n\n".join(b for b in self.blocks(node) if b.strip())

    def blocks(self, node):
        out, para = [], []

        def flush():
            text = ws("".join(para))
            if text:
                out.append(text)
            para.clear()

        for c in node.children:
            if isinstance(c, str) or c.tag in INLINE:
                para.append(self.inline(c))
                continue
            flush()
            out.extend(self.block(c))
        flush()
        return out

    def block(self, n):
        tag = n.tag
        if self.skip(n):
            return []
        if re.fullmatch(r"h[1-6]", tag):
            text = ws(self.inline(n))
            return ["#" * int(tag[1]) + " " + text] if text else []
        if tag == "p":
            return [ws(self.inline(n))]
        if tag == "pre":
            return [self.fence(n, self.code_lang(n))]
        if tag in ("ul", "ol"):
            return [self.listing(n, ordered=tag == "ol")]
        if tag == "dl":
            return self.deflist(n)
        if tag == "table":
            return [self.table(n)]
        if tag == "blockquote":
            return ["\n".join("> " + line if line else ">" for line in self.render(n).splitlines())]
        if tag == "hr":
            return ["---"]
        if tag == "figcaption":
            text = ws(self.inline(n))
            return [f"*{text}*"] if text else []
        return self.blocks(n)  # div, section, article, figure, etc.

    def code_lang(self, pre):
        for n in [pre, *pre.iter()]:
            for c in n.classes:
                m = re.match(r"(?:language|lang)-([\w+#-]+)$", c)
                if m:
                    return m.group(1)
        return ""

    def fence(self, pre, lang):
        code = self.raw_text(pre).strip("\n")
        return f"```{lang}\n{code}\n```"

    def listing(self, n, ordered):
        items = []
        for i, li in enumerate(child_nodes(n, "li"), 1):
            body = self.render(li).replace("\n\n", "\n")
            lines = body.splitlines() or [""]
            marker = f"{i}. " if ordered else "- "
            items.append(marker + lines[0] + "".join("\n  " + line for line in lines[1:]))
        return "\n".join(items)

    def deflist(self, n):
        out = []
        for c in child_nodes(n):
            if c.tag == "dt":
                out.append(f"**{ws(self.inline(c))}**")
            elif c.tag == "dd":
                out.extend(self.blocks(c))
        return out

    def table(self, n):
        rows = []
        for tr in (x for x in n.iter() if x.tag == "tr"):
            cells = [ws(self.inline(c)).replace("|", "\\|") for c in child_nodes(tr)
                     if c.tag in ("th", "td")]
            if cells:
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(lines)


def wrap(node):
    """Render a single node as a block by giving it a throwaway parent."""
    wrapper = Node("#wrap")
    wrapper.children.append(node)
    return wrapper


def utf8_stdout():
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
