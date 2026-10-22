"""Claim-support checks for tools/jev.py claims: is each cited claim on a wiki page supported by its raw file?

A cheap first pass in /lint and before a cross-model review (meta/Engine.md, "Jev"). Its findings are
leads to check, never verdicts.

How it works:
  1. Split the page body into claims: each run of text ending in a citation group "([[Source|...]], ...)" is one
     claim. Claims marked "*(inferred: ...)*" are skipped: they're the vault's own connections, by design.
  2. For each cited source page, find its raw file (the source page's `raw:` field).
  3. Numbers are checked in code: every multi-digit or decimal number in the claim must appear in at least one of
     its raw files. Jev is weak at numbers, and number errors are the most common kind reviews have caught.
  4. Meaning is checked by Jev: one request per set of cited raw files, their text as the state, one Choice per claim
     citing it (supports / contradicts / not addressed). A claim citing several sources is judged against
     all of them in one state, since each often supports only part of it.
"""
import json
import re
from pathlib import Path

import jevlib
import vaultlib

HERE = Path(__file__).resolve().parent
CITE_GROUP = re.compile(r"\(([^()]*?\[\[[^\]]+\]\][^()]*?)\)")
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
NUMBER = re.compile(r"(?<![\w.])\$?(\d[\d,]*(?:\.\d+)?)(?:x|%)?(?![\w])")


def config():
    return json.loads((HERE / "jev_questions.json").read_text(encoding="utf-8"))["claims"]


def source_raw_files():
    """{lowercased source page name or alias: raw file Path} for every source page with a `raw:` field."""
    out = {}
    for page in vaultlib.wiki_pages():
        raw = str(page.meta.get("raw", "")).strip()
        if page.type != "source" or not raw:
            continue
        for name in [page.name, *page.aliases]:
            out[name.lower()] = vaultlib.ROOT / raw
    return out


def display(text):
    """Claim text as a reader sees it: [[Target|shown]] -> shown, markup removed."""
    text = WIKILINK.sub(lambda m: m.group(1).split("|")[-1], text)
    text = re.sub(r"[*_`]+", "", text)
    return re.sub(r"\s+", " ", text).strip(" -;:,.")


def claims(body):
    """[(claim text, [cited link targets])] from a page body, in order."""
    out = []
    for block in re.split(r"\n(?=\s*[-*] |\s*\d+\. |#)|\n\s*\n", body):
        if block.lstrip().startswith("#"):
            continue
        start = 0
        for m in CITE_GROUP.finditer(block):
            targets = [vaultlib.link_target(t) for t in WIKILINK.findall(m.group(1))]
            text = block[start:m.start()]
            start = m.end()
            if "*(inferred" in text or "(inferred:" in text:
                continue
            text = re.sub(r"^\s*([-*]|\d+\.)\s+", "", text)
            # a relationship one-liner ("Used in [[X]]") is about the wiki's structure, not the source
            if len(re.findall(r"\w+", WIKILINK.sub(" ", text))) < 5:
                continue
            text = display(text)
            if len(text) >= 15 and targets:
                out.append((text, targets))
    return out


def numbers(text):
    """Multi-digit or decimal numbers, normalized (commas dropped). Single digits are too common to check."""
    found = set()
    for m in NUMBER.finditer(text):
        n = m.group(1).replace(",", "").rstrip(".")
        if len(n.replace(".", "")) >= 2 or "." in n:
            found.add(n)
    return found


def check(page_path, repeat=0):
    """{"page", "claims": [{text, sources, raws, numbers_missing, answers: {raw: answer}, verdict, flags}], usage}."""
    cfg = config()
    page = vaultlib.Page(Path(jevlib.check_sendable(page_path)))
    by_name = source_raw_files()
    rows = []
    for text, targets in claims(page.body):
        raws = sorted({str(by_name[t.lower()]) for t in targets if t.lower() in by_name})
        if not raws:
            continue  # cites only non-source pages
        rows.append({"text": text, "sources": targets, "raws": raws, "answers": {}, "flags": []})
    raw_text = {r: jevlib.read_sendable(r) for row in rows for r in row["raws"]}
    norm_raw = {r: t.replace(",", "") for r, t in raw_text.items()}
    for row in rows:
        row["numbers_missing"] = sorted(n for n in numbers(row["text"])
                                        if not any(n in norm_raw[r] for r in row["raws"]))
    usage = {"input_tokens": 0, "output_tokens": 0}
    q = cfg["question"]
    # One request per set of cited raw files: a claim citing two sources is judged against both at once, since
    # each often supports only part of it.
    for group in sorted({tuple(row["raws"]) for row in rows}):
        questions = {}
        for i, row in enumerate(rows):
            if tuple(row["raws"]) == group:
                instructions = dict(q["instructions"], claim=row["text"])
                questions[f"claim{i:03d}"] = {"type": "choice", "instructions": instructions, "criteria": q["criteria"]}
        if len(group) == 1:
            state = {"source_file": Path(group[0]).name, "source_text": raw_text[group[0]]}
        else:
            state = {"note": "The claim cites all of these sources together.",
                     "sources": [{"source_file": Path(r).name, "source_text": raw_text[r]} for r in group]}
        result = jevlib.system_one(state, questions, purpose="claims", repeat=repeat)
        for qid, answer in result["answers"].items():
            rows[int(qid[5:])]["answers"]["+".join(group)] = answer
        for k in usage:
            usage[k] += result["usage"][k]
    t = cfg["thresholds"]
    for row in rows:
        best = max(row["answers"].values(), key=lambda a: a["probabilities"].get("supports", 0), default=None)
        row["best"] = best
        if row["numbers_missing"]:
            row["flags"].append("numbers not in the source: " + ", ".join(row["numbers_missing"]))
        if best is None:
            continue
        p = best["probabilities"]
        if p.get("contradicts", 0) >= t["contradicts"]:
            row["flags"].append(f"Jev: contradicts (P={p['contradicts']:.2f})")
        elif p.get("not_addressed", 0) >= t["not_addressed"]:
            row["flags"].append(f"Jev: not addressed (P={p['not_addressed']:.2f})")
    return {"page": page.rel, "claims": rows, "usage": usage}


def report_lines(result):
    lines = []
    for row in result["claims"]:
        if row["flags"]:
            src = ", ".join(row["sources"])
            lines.append(f"{'; '.join(row['flags'])} | cites {src} | \"{row['text'][:200]}\"")
    return lines
