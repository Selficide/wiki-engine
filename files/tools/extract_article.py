"""Extract the article from a news / blog HTML page as compact markdown plus metadata. Read-only.

Generic counterpart to extract_sphinx.py: no layout is assumed. It works in layers, most reliable first:
  1. metadata: JSON-LD (schema.org Article types), OpenGraph / article:* / name= meta tags, <title>,
     canonical link
  2. content, semantic: itemprop=articleBody, then the largest <article>, then <main> / role=main
  3. content, scoring fallback (Readability-style): paragraphs score their parent containers by
     length and commas, discounted by link density; the best container plus strong siblings wins
  4. content, last resort: JSON-LD articleBody, if the page carries one
Boilerplate is dropped throughout: nav/aside/footer/forms, ARIA landmark roles, and elements whose
class or id says share/related/newsletter/cookie/comments/etc. Hidden elements are dropped too, and
reported, because hidden text is a common place to plant instructions aimed at AI tools.

Modes (cheapest first):
  python -I tools/extract_article.py FILE                # --meta: metadata + diagnostics only
  python -I tools/extract_article.py FILE --outline      # headings with section sizes
  python -I tools/extract_article.py FILE --all          # metadata block + full markdown
Options: --links keeps link URLs; --url URL is the page's address when it has no canonical link
(for resolving relative links); --max-chars N truncates the body.

Downloaded HTML is untrusted: run with -I. Reads local files only; never downloads.
"""
import argparse
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops tools/; add it back
from htmlmd import Node, Renderer, SKIP, is_hidden, parse, utf8_stdout, ws  # noqa: E402

ARTICLE_TYPES = {"Article", "NewsArticle", "BlogPosting", "TechArticle", "Report", "ScholarlyArticle",
                 "AnalysisNewsArticle", "OpinionNewsArticle", "ReportageNewsArticle", "LiveBlogPosting",
                 "SocialMediaPosting", "DiscussionForumPosting", "HowTo", "Guide"}
BOILER_TAGS = {"nav", "aside", "footer", "form", "dialog"}
BOILER_ROLES = {"navigation", "banner", "contentinfo", "complementary", "search", "dialog",
                "alertdialog", "menu", "menubar"}
BOILER_TOKENS = {
    "comment", "comments", "share", "sharing", "social", "related", "recommended", "recommendations",
    "newsletter", "subscribe", "subscription", "signup", "promo", "promotion", "advert",
    "advertisement", "ad", "ads", "adslot", "sponsor", "sponsored", "cookie", "cookies", "consent",
    "gdpr", "popup", "modal", "overlay", "sidebar", "footer", "breadcrumb", "breadcrumbs", "nav",
    "navbar", "navigation", "menu", "widget", "banner", "toolbar", "outbrain", "taboola", "disqus",
    "paywall", "regwall", "meter", "author-bio", "tags", "pagination", "pager", "skip-link"}
PAYWALL_TOKENS = {"paywall", "regwall", "meter", "metered", "premium", "locked", "subscriber-only",
                  "members-only", "member-only"}
PAYWALL_PHRASES = [
    "subscribe to continue", "subscribe to read", "to continue reading", "continue reading with",
    "members only", "member-only story", "become a member", "sign in to read", "already a subscriber",
    "create a free account to", "this post is for paid subscribers", "upgrade to paid",
    "for paying subscribers", "read the full story", "unlock this article"]
# Wording that addresses an AI reader. Topic words alone ("system prompt") are normal in AI articles.
INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts?)|"
    r"(you are|act as) (an? |the )?(ai|assistant|language model|llm|chatbot)\b|"
    r"(reveal|print|repeat|output|show) (me )?(your|the) (system prompt|instructions)|"
    r"(instructions?|message|note) (to|for) (the )?(ai|llm|assistant|chatgpt|claude|gpt|model)\b|"
    r"\b(as an ai|ai (agents?|assistants?|models?|crawlers?)[,:]? (must|should|please))|"
    r"do not (tell|reveal|mention) (this|the user)", re.I)
MIN_ARTICLE_CHARS = 400
# Readability's guard: a class that also names content is not boilerplate ("post-share" is, "post" isn't)
CONTENT_TOKENS = {"article", "body", "column", "content", "main", "post", "entry", "story", "text", "prose",
                  "hentry", "blog"}
STRUCTURAL = {"html", "body", "main", "article"}
# CMS taxonomy classes describe the post, not the element ("category-social-media", "tag-cookies")
TAXONOMY = re.compile(r"^(category|tag|postid|post|page-id|author|format|type|status|term|topic)-")
CHALLENGE = re.compile(r"cf_chl_opt|challenge-platform|cf-browser-verification|_cf_chl|"
                       r"Attention Required! \| Cloudflare|Just a moment\.\.\.|Checking your browser", re.I)


def tokens(node):
    names = [c for c in f"{node.attrs.get('class', '')} {node.attrs.get('id', '')}".lower().split()
             if not TAXONOMY.match(c)]
    parts = {p for c in names for p in re.split(r"[_-]+", c)} - {""}
    return parts | set(names)


# --- metadata ----------------------------------------------------------------------------------

def jsonld_objects(root):
    for n in root.iter():
        if n.tag == "script" and "ld+json" in n.attrs.get("type", "").lower():
            text = "".join(c for c in n.children if isinstance(c, str)).strip()
            try:
                data = json.loads(text, strict=False)
            except ValueError:
                continue
            stack = [data]
            while stack:
                item = stack.pop()
                if isinstance(item, list):
                    stack.extend(item)
                elif isinstance(item, dict):
                    if "@graph" in item:
                        stack.extend(item["@graph"] if isinstance(item["@graph"], list) else [item["@graph"]])
                    yield item


def ld_types(obj):
    t = obj.get("@type", [])
    return set(t if isinstance(t, list) else [t])


def ld_text(value):
    """A JSON-LD value as display text: strings as-is, objects by name, lists joined."""
    if isinstance(value, str):
        return ws(html.unescape(value))  # CMSs often entity-encode JSON-LD strings
    if isinstance(value, dict):
        return ld_text(value.get("name") or value.get("@id") or "")
    if isinstance(value, list):
        return ", ".join(t for t in (ld_text(v) for v in value) if t)
    return ""


def iso_date(value):
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})", str(value or ""))
    return m.group(1) if m else ws(str(value or ""))


def collect_meta(root, url_hint):
    meta, page_title, canonical, lang = {}, "", "", ""
    for n in root.iter():
        if n.tag == "meta":
            key = (n.attrs.get("property") or n.attrs.get("name") or n.attrs.get("itemprop") or "").lower()
            if key and n.attrs.get("content") and key not in meta:
                meta[key] = ws(n.attrs["content"])
        elif n.tag == "title" and not page_title:
            page_title = ws("".join(c for c in n.children if isinstance(c, str)))
        elif n.tag == "link" and "canonical" in n.attrs.get("rel", "").lower().split():
            canonical = canonical or n.attrs.get("href", "")
        elif n.tag == "html":
            lang = n.attrs.get("lang", "")
    objs = list(jsonld_objects(root))
    art = next((o for o in objs if ld_types(o) & ARTICLE_TYPES), None)
    art = art or next((o for o in objs if ld_types(o) & {"WebPage"}), None) or {}

    author = ld_text(art.get("author"))
    if not author:
        for key in ("author", "article:author", "dc.creator", "parsely-author", "sailthru.author"):
            if meta.get(key) and not meta[key].startswith("http"):
                author = meta[key]
                break
    if not author:
        byline = next((n for n in root.iter() if n.attrs.get("rel") == "author"
                       or (tokens(n) & {"byline", "author-name"} and n.tag not in SKIP)), None)
        if byline is not None:
            text = ws(Renderer().plain(byline))
            author = re.sub(r"^(by|written by)\s+", "", text, flags=re.I) if 0 < len(text) < 80 else ""
    first_time = next((n.attrs["datetime"] for n in root.iter() if n.tag == "time" and n.attrs.get("datetime")),
                      "")
    published = (art.get("datePublished") or meta.get("article:published_time") or meta.get("date")
                 or meta.get("pubdate") or meta.get("dc.date") or meta.get("citation_publication_date")
                 or first_time)
    main_entity = art.get("mainEntityOfPage")
    free = art.get("isAccessibleForFree", "")
    return {
        "url": canonical or meta.get("og:url") or ld_text(art.get("url")) or
               (main_entity.get("@id", "") if isinstance(main_entity, dict) else ld_text(main_entity))
               or url_hint,
        "title": ld_text(art.get("headline")) or meta.get("og:title") or meta.get("twitter:title")
                 or page_title,
        "author": author,
        "published": iso_date(published),
        "modified": iso_date(art.get("dateModified") or meta.get("article:modified_time")),
        "site": meta.get("og:site_name") or ld_text(art.get("publisher")),
        "language": ld_text(art.get("inLanguage")) or lang,
        "description": ld_text(art.get("description")) or meta.get("og:description")
                       or meta.get("description"),
        "_free": str(free).strip().lower() if free != "" else "",
        "_body": art.get("articleBody", "") if isinstance(art.get("articleBody"), str) else "",
    }


# --- content -----------------------------------------------------------------------------------

class ArticleRenderer(Renderer):
    def __init__(self, protected, links=False, base_url=""):
        super().__init__(links=links, base_url=base_url)
        self.protected = protected

    def boiler(self, n):
        if id(n) in self.protected or any(a.tag in ("pre", "code") for a in n.ancestors()):
            return False  # highlighters use classes like "comment" inside code
        role = n.attrs.get("role", "").lower()
        if n.tag in BOILER_TAGS or role in BOILER_ROLES:
            return True
        if n.tag == "header" and any(x.tag == "nav" for x in n.iter()):
            return True
        if n.tag in STRUCTURAL:
            return False
        tok = tokens(n)
        return bool(tok & BOILER_TOKENS) and not tok & CONTENT_TOKENS

    def skip(self, n):
        return super().skip(n) or self.boiler(n)

    def render(self, node):
        """Like Renderer.render, minus repeated headings and trailing headings left empty by boilerplate removal.

        Only trailing empty headings go: a heading followed directly by another ("Part 1" then its first
        section) is normal structure, so empty headings mid-article are kept.
        """
        blocks = [b for b in self.blocks(node) if b.strip()]
        is_heading = lambda b: bool(re.match(r"#{1,6} ", b))  # noqa: E731
        out = []
        for b in blocks:
            if is_heading(b) and out and is_heading(out[-1]) and bare(out[-1]) == bare(b):
                continue  # the same heading twice in a row
            out.append(b)
        while out and is_heading(out[-1]):
            out.pop()  # headings with nothing after them (e.g. a removed share bar's "SHARE THIS STORY")
        return "\n\n".join(out)


def bare(s):
    return ws(re.sub(r"[`*_#]", "", s)).lower()


def semantic_nodes(root):
    found = {"articleBody": [], "article": [], "main": []}
    for n in root.iter():
        if "articlebody" in n.attrs.get("itemprop", "").lower():
            found["articleBody"].append(n)
        elif n.tag == "article":
            found["article"].append(n)
        elif n.tag == "main" or n.attrs.get("role", "").lower() == "main":
            found["main"].append(n)
    return found


def protect(nodes):
    keep = set()
    for n in nodes:
        keep.add(id(n))
        keep.update(id(a) for a in n.ancestors())
    return keep


def text_stats(r, node):
    """(text chars, link chars) of what the renderer would keep."""
    text = ws(r.plain(node))
    links = sum(len(ws(r.plain(a))) for a in node.iter() if a.tag == "a" and not r.skip(a))
    return len(text), min(links, len(text))


def score_containers(r, body):
    scores = {}
    nodes = {}
    for p in body.iter():
        if p.tag not in ("p", "pre", "blockquote", "td") or any(r.skip(a) for a in [p, *p.ancestors()]):
            continue
        text = ws(r.plain(p))
        if len(text) < 25:
            continue
        s = 1 + text.count(",") + min(len(text) // 100, 3)
        for weight, anc in zip((1, 0.5), p.ancestors()):
            if anc.tag in ("#root", "html"):
                break
            scores[id(anc)] = scores.get(id(anc), 0) + s * weight
            nodes[id(anc)] = anc
    final = {}
    for key, s in scores.items():
        total, linked = text_stats(r, nodes[key])
        final[key] = s * (1 - (linked / total if total else 0))
    return final, nodes


def pick_content(root, links, base_url):
    sem = semantic_nodes(root)
    protected = protect(sem["articleBody"] + sem["article"] + sem["main"])
    r = ArticleRenderer(protected, links, base_url)

    def size(n):
        return text_stats(r, n)[0]

    for layer in ("articleBody", "article", "main"):
        cands = sorted(sem[layer], key=size, reverse=True)
        if cands and size(cands[0]) >= MIN_ARTICLE_CHARS:
            label = {"articleBody": "itemprop=articleBody", "article": "<article>",
                     "main": "<main>/role=main"}[layer]
            return cands[0], f"semantic ({label})", r

    body = next((n for n in root.iter() if n.tag == "body"), root)
    scores, nodes = score_containers(r, body)
    if scores:
        top_key = max(scores, key=scores.get)
        top, top_score = nodes[top_key], scores[top_key]
        wrapper = Node("#wrap")
        siblings = [c for c in (top.parent.children if top.parent else [top]) if isinstance(c, Node)]
        for sib in siblings:
            keep = sib is top or scores.get(id(sib), 0) >= max(10, 0.2 * top_score)
            if not keep and sib.tag == "p":
                total, linked = text_stats(r, sib)
                keep = total > 80 and linked / total < 0.25
            if keep:
                wrapper.children.append(sib)
        if size(wrapper) >= MIN_ARTICLE_CHARS / 2:
            return wrapper, "scored (Readability-style)", r
    return body, "whole page (no article container found)", r


# --- diagnostics -------------------------------------------------------------------------------

def hidden_text(root):
    found = []
    for n in root.iter():
        if n.tag in SKIP or not is_hidden(n) or any(is_hidden(a) for a in n.ancestors()):
            continue
        text = ws(Renderer().raw_text(n))
        if len(text) >= 30:
            found.append(text)
    return found


def signals(root, meta, content_text, page_text, hidden, html_chars):
    out = []
    challenge = next((n for n in root.iter() if n.tag in ("title", "script")
                      and CHALLENGE.search("".join(c for c in n.children if isinstance(c, str)))), None)
    if challenge is not None and html_chars < MIN_ARTICLE_CHARS:
        out.append("blocked: this is a bot-protection challenge page (e.g. Cloudflare), not the article; "
                   "the content has to come another way (owner clips or pastes it)")
    if meta["_free"] in ("false", "0", "no"):
        out.append("paywall marker: JSON-LD says isAccessibleForFree = false")
    tok = next((t for n in root.iter() for t in tokens(n) & PAYWALL_TOKENS), None)
    if tok:
        out.append(f"paywall marker: an element is marked '{tok}'")
    low = page_text.lower()
    phrase = next((p for p in PAYWALL_PHRASES if p in low), None)
    if phrase:
        out.append(f"paywall marker: page says \"{phrase}\"")
    if any(s.startswith("paywall marker") for s in out):
        out.append(f"paywall check: {html_chars} chars of article text extracted; if that's the whole article "
                   "(e.g. the page was saved while signed in), it's complete; otherwise fetch_status: partial")
    if meta["_body"] and len(ws(meta["_body"])) > 1.3 * len(content_text) + 200:
        out.append(f"incomplete: JSON-LD articleBody has {len(ws(meta['_body']))} chars, "
                   f"extracted text {len(content_text)}")
    if hidden:
        total = sum(len(h) for h in hidden)
        out.append(f"hidden text dropped: {len(hidden)} element(s), {total} chars")
        for h in hidden:
            if INJECTION.search(h):
                out.append(f"POSSIBLE INSTRUCTIONS TO AI in hidden text: \"{h[:160]}\"")
    for m in INJECTION.finditer(content_text):
        start = max(0, m.start() - 60)
        out.append(f"POSSIBLE INSTRUCTIONS TO AI in visible text: \"…{content_text[start:m.end() + 60]}…\"")
    if html_chars < MIN_ARTICLE_CHARS:
        out.append(f"short: only {html_chars} chars of article text in the HTML (blocked page, paywall, "
                   "or content loaded by JavaScript?)")
    return out


def yaml_line(key, value):
    value = ws(str(value or ""))
    if re.search(r"[:#\[\]{}\"',&*!|>%@`]", value) or value[:1] in "-?":
        value = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"{key}: {value}"


def outline(markdown):
    sections, current, size, fenced = [], "(intro)", 0, False
    for line in markdown.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        m = None if fenced else re.match(r"^(#{1,6}) (.+)$", line)
        if m:
            sections.append((current, size))
            current, size = "  " * (len(m.group(1)) - 1) + m.group(2), 0
        else:
            size += len(line) + 1
    sections.append((current, size))
    return [f"{title} ({n / 1000:.1f}k chars)" for title, n in sections if title != "(intro)" or n >= 50]


def main():
    utf8_stdout()
    sys.setrecursionlimit(20000)  # deeply nested pages
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--meta", action="store_true", help="metadata and diagnostics (default)")
    mode.add_argument("--outline", action="store_true")
    mode.add_argument("--all", action="store_true")
    ap.add_argument("--links", action="store_true", help="keep link URLs as [text](url)")
    ap.add_argument("--url", default="", help="page address, if the page has no canonical link")
    ap.add_argument("--max-chars", type=int, default=0)
    args = ap.parse_args()

    root = parse(args.file)
    meta = collect_meta(root, args.url)
    content, layer, r = pick_content(root, args.links, meta["url"] or args.url)
    markdown = r.render(content)
    html_chars = len(ws(r.plain(content)))
    if len(markdown) < MIN_ARTICLE_CHARS and len(ws(meta["_body"])) > len(markdown):
        markdown, layer = meta["_body"].strip(), "JSON-LD articleBody (no usable HTML content)"
    title = meta["title"]
    early_headings = [line for line in markdown.splitlines() if re.match(r"#{1,6} ", line)][:3]
    if title and not any(bare(h) == bare(title) for h in early_headings):
        markdown = f"# {title}\n\n{markdown}"

    body = next((n for n in root.iter() if n.tag == "body"), root)
    page_text = ws(Renderer().plain(body))
    content_text = ws(r.plain(content)) if layer.startswith(("semantic", "scored", "whole")) else ws(markdown)
    hidden = hidden_text(root)
    sigs = signals(root, meta, content_text, page_text, hidden, html_chars)
    total, linked = text_stats(r, content) if not layer.startswith("JSON-LD") else (len(content_text), 0)
    kept = len(content_text) / len(page_text) if page_text else 0

    header = [yaml_line(k, meta[k]) for k in ("url", "title", "author", "published", "modified", "site",
                                              "language", "description")]
    diag = [f"layer: {layer}",
            f"content: {len(content_text) / 1000:.1f}k chars, link density {linked / total if total else 0:.2f}; "
            f"page text {len(page_text) / 1000:.1f}k chars "
            + (f"({kept:.0%} kept)" if layer[:1] != "J" else "(content is from JSON-LD, not the page)")]
    if args.outline:
        print("\n".join(outline(markdown)))
        return
    if not args.all:
        print("\n".join(header + diag))
        print("signals:" + ("".join(f"\n  - {s}" for s in sigs) if sigs else " none"))
        return
    if args.max_chars and len(markdown) > args.max_chars:
        markdown = markdown[:args.max_chars].rsplit("\n", 1)[0] + f"\n\n[truncated at {args.max_chars} chars]"
    print("---")
    print("\n".join(header))
    print(f"# extract_article.py: {layer}")
    for s in sigs:
        print(f"# signal: {s}")
    print("---")
    print(markdown)


if __name__ == "__main__":
    main()
