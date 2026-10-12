"""Shared helpers for vault tools. Read-only: nothing here writes to disk
(scripts that write, like sync_sources.py, do so themselves).

Frontmatter parsing covers the YAML subset the schema uses (scalars, inline
[a, b] lists, and "- item" block lists). It is not a full YAML parser.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
RAW = ROOT / "raw"

# Pages that are wiki infrastructure rather than knowledge pages.
SPECIAL = {"index", "log"}

# Page types every vault has; the engine's rules and scripts depend on them.
ENGINE_TYPES = ("source", "synthesis")


def load_config():
    """The vault's meta/vault.json: its name and page types (folder, index label, extra fields).

    Each extra field is {"required": bool, "values": [...], "format": "date" | "list", "pattern": regex},
    all optional. The order of "types" is the order of groups in the index.
    """
    path = ROOT / "meta" / "vault.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        sys.exit(f"{path.relative_to(ROOT).as_posix()} is missing; every vault needs one (see meta/Engine.md)")
    missing = [t for t in ENGINE_TYPES if t not in config.get("types", {})]
    if missing:
        sys.exit(f"meta/vault.json: types must include {', '.join(missing)}")
    return config


CONFIG = load_config()
TYPES = CONFIG["types"]
FOLDER_TYPE = {spec["folder"]: name for name, spec in TYPES.items()}

_LIST_ITEM = re.compile(r'\s*(?:"([^"]*)"|\'([^\']*)\'|([^,]+))')

WIKILINK = re.compile(r"!?\[\[([^\]\n]+?)\]\]")
FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")


def strip_code(text):
    return INLINE_CODE.sub("", FENCE.sub("", text))


def link_target(raw):
    target = re.split(r"\\?\|", raw, maxsplit=1)[0]  # \| appears inside tables
    target = target.split("#", 1)[0].strip()
    return target.rsplit("/", 1)[-1]  # Obsidian resolves by filename


def cited_sources(page, sources_by_lower):
    """Source page names cited in the page body, in order of first citation.

    sources_by_lower maps lower-cased source page names to their exact names.
    Frontmatter is excluded, so the result is what the text itself relies on.
    """
    seen = []
    for m in WIKILINK.finditer(strip_code(page.body)):
        name = sources_by_lower.get(link_target(m.group(1)).lower())
        if name and name not in seen:
            seen.append(name)
    return seen


def frontmatter_sources(page):
    """Names in the page's sources: list, with [[ ]] and any |alias removed."""
    names = []
    for s in as_list(page.meta.get("sources")):
        m = re.match(r"^\s*\[\[([^\]]+)\]\]\s*$", s)
        names.append(link_target(m.group(1)) if m else s.strip())
    return names


def utf8_stdout():
    """Windows consoles default to a legacy codepage; page names contain en dashes etc."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass


def _scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")  # YAML single quotes: '' is a literal '
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return re.sub(r'\\(["\\])', r"\1", value[1:-1])  # the escapes yaml_str writes
    return re.sub(r"\s+#.*$", "", value)  # trailing comment on an unquoted value


def yaml_str(s):
    """Quote a one-line string so both real YAML (Obsidian) and _scalar read it back unchanged."""
    s = re.sub(r"\s+", " ", s).strip()
    if '"' in s and "'" not in s:
        return "'" + s + "'"  # reads better than escaped double quotes
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _inline_list(value):
    inner = value.strip()[1:-1]
    items = []
    for m in _LIST_ITEM.finditer(inner):
        item = next(g for g in m.groups() if g is not None).strip()
        if item:
            items.append(item)
    return items


def split_frontmatter(text):
    """Return (frontmatter dict, body). Missing frontmatter gives ({}, text)."""
    if not text.startswith("---"):
        return {}, text
    end = re.search(r"^---\s*$", text[3:], re.MULTILINE)
    if not end:
        return {}, text
    block = text[3:3 + end.start()]
    body = text[3 + end.end():]
    meta, key = {}, None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        block_item = re.match(r"^\s*-\s+(.*)$", line)
        if block_item and key is not None:
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(_scalar(block_item.group(1)))
            continue
        kv = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not kv:
            continue
        key, value = kv.group(1), kv.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = _inline_list(value)
        elif value == "":
            meta[key] = ""
        else:
            meta[key] = _scalar(value)
    return meta, body


def as_list(value):
    if isinstance(value, list):
        return value
    return [value] if value else []


class Page:
    def __init__(self, path):
        self.path = path
        self.name = path.stem
        self.folder = path.parent.name if path.parent != WIKI else ""
        text = path.read_text(encoding="utf-8-sig")
        self.meta, self.body = split_frontmatter(text)
        self.text = text

    @property
    def rel(self):
        return self.path.relative_to(ROOT).as_posix()

    @property
    def type(self):
        return self.meta.get("type", "")

    @property
    def topics(self):
        return as_list(self.meta.get("topics"))

    @property
    def aliases(self):
        return as_list(self.meta.get("aliases"))

    @property
    def tags(self):
        return as_list(self.meta.get("tags"))

    @property
    def summary(self):
        return str(self.meta.get("summary", "")).strip()

    @property
    def hub(self):
        """True for a topic hub: the page that defines its topic."""
        return str(self.meta.get("hub", "")).strip().lower() == "true"

    @property
    def special(self):
        return self.folder == "" and self.name in SPECIAL


def wiki_pages(include_special=False):
    pages = [Page(p) for p in sorted(WIKI.rglob("*.md"))]
    return [p for p in pages if include_special or not p.special]


def raw_provenance(pages):
    """(referenced, superseded) sets of raw/ paths (posix, relative to the vault).

    referenced: raw files some source page points to with raw:.
    superseded: failed-fetch stubs whose URL now belongs to a referenced raw file (e.g. the owner
    supplied the article later). Stubs are immutable, so this is how they count as resolved.
    """
    referenced = {str(p.meta.get("raw", "")).replace("\\", "/") for p in pages if p.type == "source"}
    referenced.discard("")
    urls = set()
    for rel in referenced:
        f = ROOT / rel
        if f.is_file() and f.suffix == ".md":
            url = str(split_frontmatter(f.read_text(encoding="utf-8-sig"))[0].get("url", "")).strip()
            if url:
                urls.add(url)
    superseded = set()
    for f in RAW.rglob("*.md"):
        rel = f.relative_to(ROOT).as_posix()
        if rel in referenced or rel.startswith("raw/assets/"):
            continue
        meta, _ = split_frontmatter(f.read_text(encoding="utf-8-sig"))
        if meta.get("fetch_status") == "failed" and str(meta.get("url", "")).strip() in urls:
            superseded.add(rel)
    return referenced, superseded


def topic_registry(pages):
    """Topic slug -> hub pages declaring it. A topic exists when it has a hub page.

    Should map each slug to exactly one hub; frontmatter.py reports anything else.
    """
    registry = {}
    for p in pages:
        if p.hub:
            for t in p.topics:
                registry.setdefault(t, []).append(p)
    return registry


def norm(s):
    """Loose key for name matching: case-, dash- and punctuation-insensitive."""
    s = s.lower().replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()
