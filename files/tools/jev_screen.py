"""Prompt-injection screening for tools/jev.py screen: flag text in a fetched page that addresses an AI reader.

An advisory tripwire, not a gate (meta/Engine.md, "Jev"). A low score never means a
page is safe: adversarial text can move Jev's answers, so the vault's instruction-source rules apply regardless.

How it works:
  1. Load the page. HTML goes through extract_article.py's own functions (used as they are), which give the
     article markdown and the full text of every hidden element; other files are read as text.
  2. Split into chunks (paragraphs, list blocks, fenced code), each tagged with an ID: C001... for visible text,
     H001... for hidden elements.
  3. Group chunks into windows of a few thousand tokens. Per window, one Jev request whose state is the tagged
     window plus the page title, asking the battery in tools/jev_questions.json about each chunk by ID.
  4. Report each chunk whose highest score reaches the "possible" threshold, alongside the extractor's regex.
"""
import json
import re
import sys
from pathlib import Path

import jevlib

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "jev_questions.json"
HTML_SUFFIXES = {".html", ".htm"}


def config():
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))["screen"]


# --- loading and chunking --------------------------------------------------------------------------------

def load(path):
    """(title, url, markdown, hidden fragments) for a sendable file."""
    p = jevlib.check_sendable(path)
    if p.suffix.lower() not in HTML_SUFFIXES:
        return p.stem, "", jevlib.read_sendable(p), []
    import extract_article as ea  # tools/ is on sys.path (jev.py puts it there)
    sys.setrecursionlimit(20000)
    root = ea.parse(str(p))
    meta = ea.collect_meta(root, "")
    content, _layer, r = ea.pick_content(root, False, meta["url"])
    markdown = r.render(content)
    if len(markdown) < ea.MIN_ARTICLE_CHARS and len(ea.ws(meta["_body"])) > len(markdown):
        markdown = meta["_body"].strip()
    return meta["title"] or p.parent.name, meta["url"], markdown, ea.hidden_text(root)


def chunks(markdown, max_chars):
    """Split markdown into blocks at blank lines, keeping fenced code whole and headings with what follows."""
    blocks, current, fenced = [], [], False
    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
        if not fenced and not line.strip():
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    merged = []
    for b in blocks:
        if merged and re.match(r"#{1,6} ", merged[-1]) and "\n" not in merged[-1]:
            merged[-1] += "\n" + b  # a lone heading joins the block under it
        else:
            merged.append(b)
    out = []
    for b in merged:
        while len(b) > max_chars:  # split very long blocks at a line or sentence boundary
            cut = max(b.rfind("\n", 0, max_chars), b.rfind(". ", 0, max_chars))
            cut = cut + 1 if cut > max_chars // 3 else max_chars
            out.append(b[:cut].strip())
            b = b[cut:].strip()
        if b:
            out.append(b)
    return out


def tagged(markdown, hidden, max_chars):
    """[(id, text)]: C### for visible chunks, H### for hidden elements (long ones split, not truncated)."""
    items = [(f"C{i:03d}", t) for i, t in enumerate(chunks(markdown, max_chars), 1)]
    hidden_parts = [part for h in hidden for part in chunks(h, max_chars)]
    items += [(f"H{i:03d}", t) for i, t in enumerate(hidden_parts, 1)]
    return items


def kind(cid, text):
    """The chunk's block type as code sees it, given to Jev as context: quotes and code are often examples."""
    if cid.startswith("H"):
        return "hidden element"
    first = text.lstrip()
    if first.startswith("```"):
        return "code block"
    if first.startswith(">"):
        return "quotation"
    if re.match(r"([-*+]|\d+\.) ", first):
        return "list"
    if re.match(r"#{1,6} ", first):
        return "heading and text"
    return "paragraph"


def windows(items, window_tokens):
    """Group chunks into windows of about window_tokens, overlapping by one chunk."""
    out, current, size = [], [], 0
    for item in items:
        t = jevlib.estimate_tokens(item[1])
        if current and size + t > window_tokens:
            out.append(current)
            current, size = [current[-1]], jevlib.estimate_tokens(current[-1][1])
        current.append(item)
        size += t
    if current and (not out or current != out[-1][-1:]):
        out.append(current)
    return out


# --- screening -------------------------------------------------------------------------------------------

def screen(path, repeat=0):
    """{"title", "url", "chunks": [{id, text, hidden, scores: {question: p}, max, regex}], "usage"}."""
    import extract_article as ea
    cfg = config()
    title, url, markdown, hidden = load(path)
    items = tagged(markdown, hidden, cfg["chunk_max_chars"])
    scores = {cid: {} for cid, _ in items}
    usage = {"input_tokens": 0, "output_tokens": 0}
    for window in windows(items, cfg["window_tokens"]):
        state = {"page": {"title": title, "url": url},
                 "note": "C chunks are visible page text; H chunks are text the page hides from human readers.",
                 "chunks": [f"{cid} [{kind(cid, text)}]| {text}" for cid, text in window]}
        battery = dict(cfg["questions"], framing=cfg["framing"])
        questions = {f"{cid}::{name}": {"type": "noul",
                                        "instructions": q["instructions"].replace("{chunk}", f"`{cid}`"),
                                        "criteria": q["criteria"]}
                     for cid, _ in window for name, q in battery.items()}
        result = jevlib.system_one(state, questions, purpose="screen", repeat=repeat)
        for qid, answer in result["answers"].items():
            cid, name = qid.split("::")
            scores[cid][name] = max(scores[cid].get(name, 0.0), answer.get("noul", 0.0))  # overlap: keep the max
        for k in usage:
            usage[k] += result["usage"][k]
    rows = []
    hazards = list(cfg["questions"])
    for cid, text in items:
        s = scores[cid]
        hazard = {k: v for k, v in s.items() if k in hazards}
        rows.append({"id": cid, "text": text, "hidden": cid.startswith("H"), "kind": kind(cid, text),
                     "scores": s, "max": max(hazard.values()) if hazard else 0.0,
                     "framing": s.get("framing", 0.0), "regex": bool(ea.INJECTION.search(text))})
    return {"title": title, "url": url, "chunks": rows, "usage": usage}


def level(row, t):
    """none / possible / likely. A chunk framed as an example or quotation is capped at "possible": that's where
    documentation shows prompts, but an attacker can dress an injection up the same way, so it's never dropped.
    Hidden text is never capped."""
    if row["max"] < t["possible"]:
        return "none"
    if row["max"] >= t["likely"] and (row["hidden"] or row.get("framing", 0.0) < t["framed"]):
        return "likely"
    return "possible"


def report_lines(result):
    """Signal lines for chunks at or above the "possible" threshold, plus regex-only hits.

    Visible "possible" chunks that Jev judges to be framed as examples (prompts a page shows, quoted attacks) are
    summarized in one line instead of one each: on pages about prompting there can be dozens.
    """
    t = config()["thresholds"]
    lines, shown_as_examples = [], []
    for row in result["chunks"]:
        lv = level(row, t)
        if lv == "none" and not row["regex"]:
            continue
        if (lv == "possible" and not row["hidden"] and not row["regex"]
                and row.get("framing", 0) >= t["framed"]):
            shown_as_examples.append(row)
            continue
        hazards = {k: v for k, v in row["scores"].items() if k != "framing"}
        top = max(hazards, key=hazards.get) if hazards else "-"
        where = "HIDDEN text" if row["hidden"] else f"visible {row['kind']}"
        framed = f", framed as example {row['framing']:.2f}" if row.get("framing", 0) >= t["framed"] else ""
        excerpt = re.sub(r"\s+", " ", row["text"])[:160]
        regex = ", regex: yes" if row["regex"] else ""
        lines.append(f"jev {lv}: P={row['max']:.2f} {top} at {row['id']} ({where}{framed}{regex}): \"{excerpt}\"")
    if shown_as_examples:
        top = max(r["max"] for r in shown_as_examples)
        ids = ", ".join(r["id"] for r in shown_as_examples[:12]) + (", ..." if len(shown_as_examples) > 12 else "")
        lines.append(f"jev possible, framed as examples: {len(shown_as_examples)} chunk(s) (prompts or attacks the page shows), "
                     f"P up to {top:.2f}: {ids}")
    return lines
