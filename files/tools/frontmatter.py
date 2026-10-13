"""Frontmatter checks against meta/Engine.md and the vault's page types (meta/vault.json) for /lint. Read-only.

Wiki pages:
  - required fields present (sources: only on non-source pages; source-page extras)
  - type valid and matching its folder
  - topics non-empty, and each one defined by a hub page (hub: true)
  - hubs: synthesis, one topic, valid status/parent/tag_vocab; exactly one hub per topic
  - domains: each top-level hub names a domain from vault.json (when it declares any); sub-topic hubs inherit theirs
  - tags drawn from the tag_vocab of the page's topics
  - fields vault.json declares for the page's type: required, allowed values, format; not on other types
  - page size: pages over 15 KB (split candidates)
  - evidence age: in topics whose hub sets stale_after: (months), pages whose newest cited source is older
  - created/updated are real YYYY-MM-DD dates, updated >= created, not in the future
  - sources: entries are [[links]] to existing source pages
  - summary: present, one line (<= 200 chars); kind / fetch_status values; unexpected fields
  - alias collisions (an alias equal to another page's name or alias)
Raw articles (raw/articles/):
  - filename YYYY-MM-DD-slug.md; required fields; fetch_status / capture / origin values
  - owner-supplied files (added:) carry supplied_by: and origin:

Usage:
  python tools/frontmatter.py
  python tools/frontmatter.py --topic qr-codes   # wiki checks for one topic (raw checks skipped)
"""
import argparse
import re
from collections import defaultdict
from datetime import date

from vaultlib import (DOMAINS, FOLDER_TYPE, RAW, ROOT, TYPES, as_list, cited_sources, frontmatter_sources, norm,
                      split_frontmatter, topic_registry, utf8_stdout, wiki_pages)

COMMON = ["type", "summary", "aliases", "topics", "tags", "created", "updated"]
SUMMARY_MAX = 200  # one index line
PAGE_SIZE_MAX = 15_000  # bytes; past this a page should be split
SOURCE_EXTRA = ["raw", "url", "author", "published", "kind", "fetch_status"]
LIST_FIELDS = {"aliases", "topics", "tags", "sources"}
RAW_REQUIRED = ["url", "title", "author", "published", "fetch_status", "capture"]
FETCH_STATUS = {"full", "partial", "failed"}
CAPTURE = {"extract", "verbatim", "none"}
ORIGIN = {"human", "ai-generated", "unknown"}
KIND = {"primary", "secondary"}
# published: is "YYYY-MM-DD if known"; pages add notes like "unknown (v2.1)" or "2025-12-28 (last updated)".
# Accept a leading ISO date (possibly partial) or a word; flag dates written any other way (10/08/2026, 2026.10).
LOOSE_DATE = re.compile(r"^(\d{4}(-\d{2}(-\d{2})?)?\b(?![./-]\d)|[A-Za-z]|$)")
WIKILINK = re.compile(r"^\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]$")
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HUB_FIELDS = {"hub", "parent", "status", "tag_vocab", "stale_after", "domain"}
LEADING_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")
TOPIC_STATUS = {"active", "dormant"}


def parse_date(value):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def check_dates(meta, fields, today, problems):
    parsed = {}
    for f in fields:
        if f not in meta:
            continue
        d = parse_date(meta[f])
        if d is None:
            problems.append(f"{f}: not a YYYY-MM-DD date ({meta[f]!r})")
        elif d > today:
            problems.append(f"{f}: in the future ({d})")
        parsed[f] = d
    return parsed


def type_fields(name):
    return TYPES.get(name, {}).get("fields", {})


def check_type_fields(p, probs):
    """Fields vault.json declares per type: present when required, valid, and only on types that declare them."""
    m, own = p.meta, type_fields(p.type)
    for f, spec in own.items():
        value = m.get(f)
        if value in (None, "", []):
            if spec.get("required"):
                probs.append(f"missing {f}:")
            continue
        if spec.get("format") == "list" and not isinstance(value, list):
            probs.append(f"{f}: should be a list, got {value!r}")
        values, pattern = spec.get("values"), spec.get("pattern")
        for item in as_list(value):
            if values and item not in values:
                probs.append(f"{f}: {item!r} is not {'|'.join(sorted(values))}")
            if spec.get("format") == "date" and parse_date(item) is None:
                probs.append(f"{f}: not a YYYY-MM-DD date ({item!r})")
            if pattern and not re.fullmatch(pattern, str(item)):
                probs.append(f"{f}: {item!r} does not match {pattern}")
    for f in sorted(m.keys() - own.keys()):
        owners = [t for t in TYPES if f in type_fields(t)]
        if owners:
            probs.append(f"{f}: only {'|'.join(owners)} pages carry it")


def check_wiki(pages, scope, topics_known, today):
    out = defaultdict(list)  # page rel -> problems
    by_name = {p.name.lower(): p for p in pages}
    source_names = {p.name.lower(): p.name for p in pages if p.type == "source"}
    for p in pages:
        if not scope(p):
            continue
        m, probs = p.meta, out[p.rel]
        if not m:
            probs.append("no frontmatter")
            continue
        is_source = p.type == "source"
        required = COMMON + (SOURCE_EXTRA if is_source else ["sources"])
        probs += [f"missing {f}:" for f in required if f not in m]

        expected = FOLDER_TYPE.get(p.folder)
        if p.type not in FOLDER_TYPE.values():
            probs.append(f"type: {p.type!r} is not {'|'.join(TYPES)}")
        elif expected and p.type != expected:
            probs.append(f"type: {p.type} but folder is {p.folder}/ (expects {expected})")

        for f in LIST_FIELDS & m.keys():
            if m[f] and not isinstance(m[f], list):
                probs.append(f"{f}: should be a list, got {m[f]!r}")
        if "summary" in m:
            if not p.summary:
                probs.append("summary: empty")
            elif len(p.summary) > SUMMARY_MAX:
                probs.append(f"summary: {len(p.summary)} chars; keep it to one line (<= {SUMMARY_MAX})")
        if "topics" in m and not p.topics:
            probs.append("topics: empty")
        for t in p.topics:
            if not KEBAB.match(t):
                probs.append(f"topics: {t!r} is not kebab-case")
            elif t not in topics_known:
                probs.append(f"topics: {t!r} has no hub page (hub: true) defining it")

        vocab = set()
        for t in p.topics:
            for hub in topics_known.get(t, []):
                vocab |= set(as_list(hub.meta.get("tag_vocab")))
        stray = [t for t in p.tags if t not in vocab]
        if stray and any(t in topics_known for t in p.topics):
            probs.append(f"tags: {', '.join(stray)} not in the tag_vocab of {', '.join(p.topics)}")

        check_type_fields(p, probs)
        if not p.hub and HUB_FIELDS & (m.keys() - {"hub"}):
            probs.append("hub-only fields on a non-hub page: "
                         + ", ".join(sorted(HUB_FIELDS & (m.keys() - {"hub"}))))

        d = check_dates(m, ["created", "updated"], today, probs)
        if d.get("created") and d.get("updated") and d["updated"] < d["created"]:
            probs.append(f"updated {d['updated']} is before created {d['created']}")

        if is_source:
            if "sources" in m:
                probs.append("sources: should be omitted on source pages")
            if "kind" in m and m["kind"] not in KIND:
                probs.append(f"kind: {m.get('kind')!r} is not primary|secondary")
            if "fetch_status" in m and m["fetch_status"] not in FETCH_STATUS:
                probs.append(f"fetch_status: {m.get('fetch_status')!r} is not full|partial|failed")
            if not LOOSE_DATE.match(str(m.get("published", ""))):
                probs.append(f"published: {m.get('published')!r} is not YYYY[-MM[-DD]] or unknown")
        for s in as_list(m.get("sources")):
            link = WIKILINK.match(s.strip())
            if not link:
                probs.append(f"sources: {s!r} is not a [[link]]")
                continue
            target = by_name.get(link.group(1).strip().lower())
            if target is None:
                probs.append(f"sources: [[{link.group(1)}]] has no page")
            elif target.type != "source":
                probs.append(f"sources: [[{target.name}]] is a {target.type}, not a source page")
        if not is_source and "sources" in m:
            cited = cited_sources(p, source_names)
            listed = frontmatter_sources(p)
            add = [s for s in cited if s not in listed]
            drop = [s for s in listed if s in source_names.values() and s not in cited]
            if add or drop:
                probs.append(f"sources: out of sync with body citations ({len(add)} uncited in "
                             f"frontmatter, {len(drop)} listed but not cited); "
                             "run python tools/sync_sources.py")

        # supplied_by/origin: carried over from owner-supplied raw files (not yet in the schema's source fields)
        allowed = (set(COMMON) | set(SOURCE_EXTRA) | HUB_FIELDS | {"sources", "supplied_by", "origin"}
                   | {f for t in TYPES for f in type_fields(t)})  # misplaced type fields are reported above
        extra = sorted(set(m) - allowed)
        if extra:
            probs.append("unexpected fields: " + ", ".join(extra))
    return {k: v for k, v in out.items() if v}


def check_hubs(pages, registry):
    rows = []
    used = {t for p in pages for t in p.topics}
    for t in sorted(used | set(registry)):
        hubs = registry.get(t, [])
        if len(hubs) != 1:
            names = f" ({', '.join(h.name for h in hubs)})" if hubs else ""
            rows.append(f"{t}: {len(hubs)} hubs{names}; need exactly one")
    for p in pages:
        if not p.hub:
            continue
        m = p.meta
        if p.type != "synthesis":
            rows.append(f"{p.name}: hub is a {p.type}, should be a synthesis")
        if len(p.topics) != 1:
            rows.append(f"{p.name}: a hub defines exactly one topic, has {len(p.topics)}")
        if m.get("status") not in TOPIC_STATUS:
            rows.append(f"{p.name}: status: {m.get('status')!r} is not active|dormant")
        parent = m.get("parent", "")
        if "parent" not in m:
            rows.append(f"{p.name}: missing parent: (leave empty for a top-level topic)")
        elif parent and (parent not in registry or parent in p.topics):
            rows.append(f"{p.name}: parent: {parent!r} is not another topic")
        domain = str(m.get("domain", "")).strip()
        if not DOMAINS:
            if domain:
                rows.append(f"{p.name}: domain: {domain!r} set, but meta/vault.json declares no domains")
        elif parent:
            if domain:
                rows.append(f"{p.name}: sub-topic hubs inherit their parent's domain; remove domain:")
        elif not domain:
            rows.append(f"{p.name}: missing domain: (one of {', '.join(DOMAINS)})")
        elif domain not in DOMAINS:
            rows.append(f"{p.name}: domain: {domain!r} is not declared in meta/vault.json")
        sa = m.get("stale_after")
        if sa not in (None, "") and not (str(sa).isdigit() and int(sa) > 0):
            rows.append(f"{p.name}: stale_after: {sa!r} should be a whole number of months, or omitted")
        if "tag_vocab" not in m:
            rows.append(f"{p.name}: missing tag_vocab: (may be [])")
        elif m["tag_vocab"] and not isinstance(m["tag_vocab"], list):
            rows.append(f"{p.name}: tag_vocab: should be a list")
        else:
            bad = [t for t in as_list(m.get("tag_vocab")) if not KEBAB.match(t)]
            if bad:
                rows.append(f"{p.name}: tag_vocab entries not kebab-case: {', '.join(bad)}")
    return rows


def evidence_date(source):
    """Best date for a source page: its published: (a partial date counts from the period's start),
    else its raw file's fetched:/added: (later than publication, so it understates age)."""
    m = LEADING_DATE.match(str(source.meta.get("published", "")).strip())
    if m:
        return date(int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)), "published"
    raw = ROOT / str(source.meta.get("raw", ""))
    if raw.is_file():
        meta, _ = split_frontmatter(raw.read_text(encoding="utf-8-sig"))
        for field in ("fetched", "added"):
            d = parse_date(meta.get(field, ""))
            if d:
                return d, field
    return None, None


def check_evidence_age(pages, registry, scope, today):
    """Flag pages in opted-in topics (hub stale_after:) whose newest cited source is too old."""
    limits = {}
    for slug, hubs in registry.items():
        sa = str(hubs[0].meta.get("stale_after", "")).strip()
        if sa.isdigit() and int(sa) > 0:
            limits[slug] = int(sa)
    sources = {p.name: p for p in pages if p.type == "source"}
    rows = []
    for p in pages:
        if p.type == "source" or not scope(p):
            continue
        months = [limits[t] for t in p.topics if t in limits]
        if not months:
            continue
        dated = [evidence_date(sources[s]) + (s,) for s in frontmatter_sources(p) if s in sources]
        dated = [d for d in dated if d[0]]
        if not dated:
            rows.append(f"{p.name}: no dated sources to judge evidence age by")
            continue
        newest, how, name = max(dated)
        age = (today.year - newest.year) * 12 + today.month - newest.month
        if age > min(months):
            rows.append(f"{p.name}: newest source is {age} months old ({name}, {how} {newest}); "
                        f"topic limit {min(months)}")
    return rows


def check_sizes(pages, scope):
    rows = []
    for p in sorted(pages, key=lambda p: -len(p.text.encode("utf-8"))):
        size = len(p.text.encode("utf-8"))
        if scope(p) and size > PAGE_SIZE_MAX:
            rows.append(f"{p.name}: {size / 1000:.1f} KB (limit {PAGE_SIZE_MAX / 1000:.0f} KB); "
                        "split per the schema's split pattern")
    return rows


def check_aliases(pages, scope):
    owners = defaultdict(set)  # normalized name/alias -> page names using it
    exact = defaultdict(set)   # lower-cased name/alias -> page names using it
    for p in pages:
        for n in [p.name, *p.aliases]:
            owners[norm(n)].add(p.name)
            exact[n.lower()].add(p.name)
    rows = []
    for p in pages:
        if not scope(p):
            continue
        for a in p.aliases:
            others = owners[norm(a)] - {p.name}
            if others:
                how = "" if exact[a.lower()] - {p.name} else " (loose match: differs in punctuation)"
                rows.append(f"{p.name}: alias {a!r} also names {', '.join(sorted(others))}{how}")
    return rows


def check_raw(today):
    out = {}
    for f in sorted((RAW / "articles").glob("*.md")):
        probs = []
        if not re.match(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$", f.name):
            probs.append("filename is not YYYY-MM-DD-slug.md")
        m, _ = split_frontmatter(f.read_text(encoding="utf-8-sig"))
        if not m:
            out[f.relative_to(ROOT).as_posix()] = ["no frontmatter"]
            continue
        probs += [f"missing {k}:" for k in RAW_REQUIRED if k not in m]
        if "fetched" not in m and "added" not in m:
            probs.append("missing fetched: (or added: for owner-supplied)")
        if "added" in m:
            probs += [f"owner-supplied but missing {k}:" for k in ("supplied_by", "origin") if k not in m]
            if "origin" in m and m["origin"] not in ORIGIN:
                probs.append(f"origin: {m['origin']!r} is not human|ai-generated|unknown")
        if "fetch_status" in m and m["fetch_status"] not in FETCH_STATUS:
            probs.append(f"fetch_status: {m['fetch_status']!r} is not full|partial|failed")
        if "capture" in m and m["capture"] not in CAPTURE:
            probs.append(f"capture: {m['capture']!r} is not extract|verbatim|none")
        if not LOOSE_DATE.match(str(m.get("published", ""))):
            probs.append(f"published: {m.get('published')!r} is not YYYY[-MM[-DD]] or unknown")
        check_dates(m, ["fetched", "added"], today, probs)
        if probs:
            out[f.relative_to(ROOT).as_posix()] = probs
    return out


def section(title, rows):
    print(f"## {title}: {len(rows) if rows else 'OK'}")
    for r in rows:
        print(f"- {r}")


def grouped(title, problems):
    print(f"## {title}: {sum(map(len, problems.values())) if problems else 'OK'}")
    for rel, probs in problems.items():
        print(f"- {rel}")
        for pr in probs:
            print(f"  - {pr}")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--topic", help="check only wiki pages in this topic")
    args = ap.parse_args()

    today = date.today()
    pages = wiki_pages()
    registry = topic_registry(pages)
    scope = (lambda p: args.topic in p.topics) if args.topic else (lambda p: True)

    if not registry:
        print("WARNING: no hub pages (hub: true) found, so no topics are defined")
    grouped("Wiki page frontmatter", check_wiki(pages, scope, registry, today))
    section("Topic hubs", check_hubs(pages, registry))
    section("Alias collisions", check_aliases(pages, scope))
    section("Page size", check_sizes(pages, scope))
    section("Evidence age (topics with stale_after:)", check_evidence_age(pages, registry, scope, today))
    if not args.topic:
        grouped("Raw article frontmatter", check_raw(today))


if __name__ == "__main__":
    main()
