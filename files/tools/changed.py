"""List wiki pages changed since the last lint, for incremental /lint. Read-only.

"Since the last lint" means since the newest commit whose message starts with "Lint:", plus any
uncommitted or untracked changes. /lint runs its judgment checks (duplicates, staleness, uncited
claims, evidence tiers) on these pages only; the scripted checks still cover the whole vault.
With no Lint: commit yet, every page counts as changed.

Usage:
  python tools/changed.py                # pages changed since the last Lint: commit
  python tools/changed.py --since <rev>  # since any git revision instead
  python tools/changed.py --topic <slug> # only pages in that topic
"""
import argparse
import subprocess

from vaultlib import ROOT, utf8_stdout, wiki_pages


def git(*args):
    result = subprocess.run(["git", "-c", "core.quotePath=false", *args],  # keep "–" etc. literal
                            cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", check=True)
    return result.stdout


def last_lint():
    out = git("log", "-1", "--format=%H %cs %s", "--grep=^Lint:", "--extended-regexp")
    return out.strip() or None


def changed_paths(since):
    paths = set(git("diff", "--name-only", since, "--", "wiki/").splitlines())
    for row in git("status", "--porcelain", "--untracked-files=all", "--", "wiki/").splitlines():
        path = row[3:].strip().strip('"')
        paths.add(path.split(" -> ")[-1])  # renames: keep the new name
    return paths


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", metavar="REV")
    ap.add_argument("--topic")
    args = ap.parse_args()

    pages = [p for p in wiki_pages() if not args.topic or args.topic in p.topics]
    if args.since:
        since, label = args.since, args.since
    else:
        lint = last_lint()
        if lint is None:
            print("No Lint: commit yet; every page counts as changed.")
            for p in pages:
                print(p.rel)
            return
        since, label = lint.split(" ", 1)[0], lint
    paths = changed_paths(since)
    changed = [p for p in pages if p.rel in paths]
    print(f"Since: {label}")
    for p in changed:
        print(p.rel)
    print(f"({len(changed)} of {len(pages)} pages changed)")


if __name__ == "__main__":
    main()
