"""Thin client for TypeSafe's Jev (POST /v1/systemone), shared by tools/jev.py. Standard library only.

Jev answers typed questions (Choice, Score, Noul) about one piece of text, the "state", with probabilities
(see wiki/syntheses/TypeSafe Jev.md). This module handles everything around the call so commands don't:
  - the API key, read from an environment variable, never stored or printed (see key_env());
  - a pinned model version, so tuned thresholds don't drift when TypeSafe moves its aliases;
  - which files may be sent: only files inside the vault, minus git internals and secret-looking files;
  - a request budget against Jev's context limits, splitting questions across requests when needed;
  - retries on rate limits (429) and overload (529);
  - a response cache and a usage log, both in cache/jev/ (gitignored).

Jev is optional: with no key configured, system_one() raises NoKey and callers skip their Jev step.
Its answers are leads for Claude and the owner, never sources for wiki/.

Key setup: set TYPESAFE_API_KEY as a user environment variable (the name TypeSafe's own docs use), then restart
the app that runs the tools. To use another variable name, create tools/jev.local.json (gitignored) containing
{"key_env": "YOUR_VARIABLE_NAME"}. It holds a variable name, never the key.
"""
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_CONFIG = ROOT / "tools" / "jev.local.json"
CACHE = ROOT / "cache" / "jev"
USAGE_LOG = CACHE / "usage.jsonl"

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"  # pinned so tuned thresholds don't drift; re-test before changing it
DEFAULT_KEY_ENV = "TYPESAFE_API_KEY"
PRICE_PER_MTOK = 0.042  # input tokens, USD, as of 2026-10-21; output tokens are free

# Context limits from TypeSafe's Models page, in tokens. We can't count Jev's tokens locally, so we estimate
# conservatively (CHARS_PER_TOKEN) and keep a safety margin under each limit.
PER_REQUEST_LIMIT, PER_QUESTION_LIMIT = 64_000, 32_000
SAFETY = 0.85
CHARS_PER_TOKEN = 3.0

RETRY_STATUSES = {429, 529}
MAX_RETRIES = 4
TIMEOUT = 60


class JevError(Exception):
    """The call failed: refused content, over the limits, or an API error after retries."""


class NoKey(JevError):
    """No key is configured; callers should skip their Jev step, not fail the workflow."""


# --- key -------------------------------------------------------------------------------------------------

def key_env():
    """The name of the environment variable holding the key: jev.local.json's key_env, else TYPESAFE_API_KEY."""
    if LOCAL_CONFIG.exists():
        try:
            name = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8-sig")).get("key_env")
        except (ValueError, AttributeError):
            raise JevError(f"{LOCAL_CONFIG.relative_to(ROOT).as_posix()} isn't valid JSON of the form "
                           '{"key_env": "NAME"}')
        if name:
            return name
    return DEFAULT_KEY_ENV


def api_key():
    name = key_env()
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise NoKey(f"no Jev key configured: set the {name} environment variable and restart the app "
                    "(see tools/jevlib.py for setup)")
    return value


# --- what may be sent ------------------------------------------------------------------------------------

# Secret-looking files, refused even inside the vault. Kept narrow on purpose: a broad "*key*" would also block
# ordinary sources such as raw/articles/...-keychain-data-protection.md.
SECRET_NAME = re.compile(r"(^\.env|\.env$|\.pem$|\.key$|^id_(rsa|ed25519|ecdsa)|secret|credential|"
                         r"(^|[._-])(api|private)[_-]?key)", re.I)
REFUSED_PARTS = {".git"}
REFUSED_FILES = {Path(".claude/settings.local.json")}


def check_sendable(path):
    """Resolve path and refuse it unless it's a file inside the vault that isn't git internals or a secret.

    This is enforced in code because the tool runs without a permission prompt, so a prompt injection
    that talks Claude into "screening" a private file must get an error, not an upload.
    """
    p = Path(path).resolve()
    try:
        rel = p.relative_to(ROOT)
    except ValueError:
        raise JevError(f"refused: {path} is outside the vault; only vault files may be sent to Jev")
    if not p.is_file():
        raise JevError(f"refused: {rel.as_posix()} is not a file")
    if REFUSED_PARTS & set(rel.parts) or rel in REFUSED_FILES or p == LOCAL_CONFIG:
        raise JevError(f"refused: {rel.as_posix()} is vault configuration, not content")
    if SECRET_NAME.search(p.name):
        raise JevError(f"refused: {rel.as_posix()} looks like a secret")
    if rel.parts[:2] == ("cache", "jev"):
        raise JevError(f"refused: {rel.as_posix()} is Jev's own cache")
    return p


def read_sendable(path):
    """The text of a file that may be sent (see check_sendable)."""
    return check_sendable(path).read_text(encoding="utf-8-sig", errors="replace")


# --- budget ----------------------------------------------------------------------------------------------

def estimate_tokens(obj):
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return int(len(text) / CHARS_PER_TOKEN) + 1


def plan_batches(state, questions):
    """Split {id: question} into batches that each fit the per-request limit with the same state.

    Raises JevError if the state plus any single question can't fit the per-question limit.
    """
    state_tokens = estimate_tokens(state)
    batches, current, used = [], {}, state_tokens
    for qid, question in questions.items():
        q_tokens = estimate_tokens({qid: question})
        if state_tokens + q_tokens > PER_QUESTION_LIMIT * SAFETY:
            raise JevError(f"state (~{state_tokens} tokens) plus question {qid!r} is over Jev's "
                           f"{PER_QUESTION_LIMIT}-token per-question limit; split the state first")
        if current and used + q_tokens > PER_REQUEST_LIMIT * SAFETY:
            batches.append(current)
            current, used = {}, state_tokens
        current[qid] = question
        used += q_tokens
    if current:
        batches.append(current)
    return batches


# --- cache and usage log ---------------------------------------------------------------------------------

def cache_path(model, state, questions, repeat):
    key = json.dumps({"model": model, "state": state, "questions": questions, "repeat": repeat},
                     sort_keys=True, ensure_ascii=False)
    return CACHE / "responses" / (hashlib.sha256(key.encode("utf-8")).hexdigest()[:32] + ".json")


_LOG_LOCK = threading.Lock()  # callers may run requests in threads (the eval does); keep log lines whole


def log_usage(purpose, model, usage, n_questions, cached):
    CACHE.mkdir(parents=True, exist_ok=True)
    line = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "purpose": purpose,
            "model": model, "questions": n_questions, "cached": cached,
            "input_tokens": (usage or {}).get("input_tokens"), "output_tokens": (usage or {}).get("output_tokens")}
    with _LOG_LOCK, USAGE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def usage_summary():
    """Totals from the usage log: calls, cached calls, input tokens billed, and estimated cost in USD."""
    calls = cached = tokens = damaged = 0
    if USAGE_LOG.exists():
        for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                damaged += 1  # e.g. lines interleaved by threads before the log had a lock
                continue
            calls += 1
            if entry.get("cached"):
                cached += 1
            elif entry.get("input_tokens"):
                tokens += entry["input_tokens"]
    return {"calls": calls, "cached": cached, "input_tokens": tokens, "damaged_lines": damaged,
            "cost_usd": round(tokens * PRICE_PER_MTOK / 1e6, 6)}


# --- the call --------------------------------------------------------------------------------------------

def _post(body, key):
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "Accept": "application/json", "User-Agent": "wiki-engine-jev/0.4"})
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            if e.code in RETRY_STATUSES and attempt < MAX_RETRIES:
                wait = float(e.headers.get("retry-after") or 2 ** attempt)
                time.sleep(min(wait, 30))
                continue
            raise JevError(f"Jev API returned {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise JevError(f"couldn't reach the Jev API: {e.reason}") from None


def system_one(state, questions, purpose, repeat=0, model=MODEL, use_cache=True):
    """Ask {id: question} about state; returns {"model", "answers": {id: answer}, "usage"}.

    Questions use the API's JSON shape, e.g. {"type": "noul", "instructions": "...", "criteria": {...}}.
    Over-budget question sets are split across requests and merged. `purpose` labels the usage log.
    `repeat` is part of the cache key, so repeatability tests (repeat=1, 2, ...) make fresh calls.
    """
    if not questions:
        raise JevError("no questions to ask")
    merged = {"model": model, "answers": {}, "usage": {"input_tokens": 0, "output_tokens": 0}}
    key = None
    for batch in plan_batches(state, questions):
        path = cache_path(model, state, batch, repeat)
        if use_cache and path.exists():
            result, cached = json.loads(path.read_text(encoding="utf-8")), True
        else:
            key = key or api_key()
            result, cached = _post({"model": model, "state": state, "questions": batch}, key), False
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        log_usage(purpose, result.get("model", model), result.get("usage"), len(batch), cached)
        merged["model"] = result.get("model", model)
        merged["answers"].update(result.get("answers", {}))
        for k in ("input_tokens", "output_tokens"):
            merged["usage"][k] += (result.get("usage") or {}).get(k) or 0
    return merged
