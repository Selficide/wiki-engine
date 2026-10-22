"""Page search for /ask, used by tools/jev.py find: which wiki pages most likely answer a question?

The first step of /ask (meta/Engine.md, "Jev"). It only narrows: Claude still reads the pages and writes the answer.

One Jev request: the state is the catalog of every non-source page (title, then its summary), the same for every
question; the questions are a Choice over all page titles, whose probabilities are the ranking, and a Noul for
"does any page here address this?", since Choice probabilities always sum to 1 and crown some page even when
nothing fits.
"""
import jevlib
import vaultlib

COVERAGE_CRITERIA = {
    "true": "At least one page in the catalog is about this question's subject and would help answer it.",
    "false": "No page in the catalog covers the question's subject; at most some pages share a word with it.",
}


def catalog():
    """[(title, summary)] for every non-source wiki page, sorted by title."""
    pages = [p for p in vaultlib.wiki_pages() if p.type != "source"]
    return sorted((p.name, p.summary) for p in pages)


def find(question, top=8, repeat=0):
    """{"question", "coverage": P(some page covers it), "ranked": [(title, p)], "usage"}."""
    cat = catalog()
    state = {"note": "A wiki's catalog: each line is a page title, then what the page covers.",
             "pages": [f"{title}: {summary}" for title, summary in cat]}
    questions = {
        "page": {"type": "choice",
                 "instructions": {"question": "Which page in `pages` would best help answer this question?",
                                  "user_question": question},
                 "criteria": {title: None for title, _ in cat}},
        "covered": {"type": "noul",
                    "instructions": {"question": "Does any page in `pages` address this question?",
                                     "user_question": question},
                    "criteria": COVERAGE_CRITERIA},
    }
    result = jevlib.system_one(state, questions, purpose="find", repeat=repeat)
    probs = result["answers"]["page"]["probabilities"]
    ranked = sorted(probs.items(), key=lambda kv: -kv[1])[:top]
    return {"question": question, "coverage": result["answers"]["covered"]["noul"], "ranked": ranked,
            "usage": result["usage"]}
