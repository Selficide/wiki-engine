"""Command line for the vault's Jev tools (TypeSafe's System One model). See tools/jevlib.py for setup.

Jev is optional. With no key configured, commands say so and exit with status 0, so a workflow step that uses
Jev can be skipped without failing (meta/Engine.md, "Jev").

Usage:
  python tools/jev.py status              # key found? (never printed), pinned model, cache size, spend so far
  python tools/jev.py usage               # calls and estimated cost from cache/jev/usage.jsonl
  python -I tools/jev.py screen FILE      # flag text addressed to an AI reader (advisory; see jev_screen.py)
  python -I tools/jev.py screen FILE --json   # every chunk with its scores, for evaluation
  python tools/jev.py claims PAGE         # check each cited claim on a wiki page against its raw file
  python tools/jev.py find "QUESTION"     # rank wiki pages likely to answer a question (/ask)

There is deliberately no command that sends an arbitrary request: every command decides what it sends, within jevlib's vault-only rule.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops tools/; add it back
import jevlib  # noqa: E402
import jev_claims  # noqa: E402
import jev_find  # noqa: E402
import jev_screen  # noqa: E402
from vaultlib import utf8_stdout  # noqa: E402


def claims(args):
    result = jev_claims.check(args.page, repeat=args.repeat)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return
    lines = jev_claims.report_lines(result)
    print(f"jev claims: {result['page']}: {len(result['claims'])} cited claims checked, "
          f"{result['usage']['input_tokens']} input tokens; " + (f"{len(lines)} flagged" if lines else "none flagged"))
    for line in lines:
        print("  - " + line)
    print("  (leads to check against the raw file, not verdicts)")


def find(args):
    result = jev_find.find(args.question, top=args.top)
    print(f"jev find: coverage P={result['coverage']:.2f}"
          + ("" if result["coverage"] >= 0.5 else " (the wiki may not cover this)"))
    for title, p in result["ranked"]:
        print(f"  {p:.2f}  {title}")


def screen(args):
    result = jev_screen.screen(args.file, repeat=args.repeat)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return
    lines = jev_screen.report_lines(result)
    n = len(result["chunks"])
    print(f"jev screen: {n} chunks, {result['usage']['input_tokens']} input tokens; "
          + (f"{len(lines)} signal(s)" if lines else "no signals"))
    for line in lines:
        print("  - " + line)
    print("  (advisory: a clean result doesn't make the page safe to obey)")


def status():
    name = jevlib.key_env()
    source = "tools/jev.local.json" if jevlib.LOCAL_CONFIG.exists() else "default"
    found = bool((os.environ.get(name) or "").strip())
    print(f"key variable: {name} ({source}); " + ("found" if found else "NOT found"))
    if not found:
        print(f"  set {name} as a user environment variable and restart the app; see tools/jevlib.py")
    print(f"model: {jevlib.MODEL} (pinned)")
    responses = jevlib.CACHE / "responses"
    print(f"cached responses: {len(list(responses.glob('*.json'))) if responses.exists() else 0}")
    usage()


def usage():
    s = jevlib.usage_summary()
    print(f"usage: {s['calls']} calls ({s['cached']} from cache), {s['input_tokens']} input tokens billed, "
          f"about ${s['cost_usd']:.4f}")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("usage")
    cp = sub.add_parser("claims")
    cp.add_argument("page")
    cp.add_argument("--json", action="store_true", help="print every claim with its answers")
    cp.add_argument("--repeat", type=int, default=0, help="repeat number, for repeatability tests")
    fp = sub.add_parser("find")
    fp.add_argument("question")
    fp.add_argument("--top", type=int, default=8)
    sp = sub.add_parser("screen")
    sp.add_argument("file")
    sp.add_argument("--json", action="store_true", help="print every chunk with its scores")
    sp.add_argument("--repeat", type=int, default=0, help="repeat number, for repeatability tests")
    args = ap.parse_args()
    try:
        if args.command == "screen":
            screen(args)
        elif args.command == "claims":
            claims(args)
        elif args.command == "find":
            find(args)
        else:
            {"status": status, "usage": usage}[args.command]()
    except jevlib.NoKey as e:
        print(f"Jev skipped: {e}")
    except jevlib.JevError as e:
        sys.exit(f"jev: {e}")


if __name__ == "__main__":
    main()
