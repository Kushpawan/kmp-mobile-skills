#!/usr/bin/env python3
"""Replace the `OWNER/kmp-mobile-skills` placeholder with your real GitHub `owner/repo`.

Run once after forking or before the first publish. It rewrites README, INSTALL, manifests and
docs. Safe to re-run: it only replaces the placeholder (or a previous value passed via --from).

Usage:
    python3 scripts/set_repo.py my-org/kmp-mobile-skills
    python3 scripts/set_repo.py my-org/kmp-mobile-skills --dry-run
    python3 scripts/set_repo.py new-org/kmp-mobile-skills --from my-org/kmp-mobile-skills
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "OWNER/kmp-mobile-skills"
SUFFIXES = {".md", ".json", ".yml", ".yaml", ".toml"}
SLUG_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("slug", help="GitHub owner/repo, e.g. my-org/kmp-mobile-skills")
    parser.add_argument("--from", dest="old", default=PLACEHOLDER, help=f"value to replace (default {PLACEHOLDER})")
    parser.add_argument("--dry-run", action="store_true", help="list files that would change")
    args = parser.parse_args(argv)

    if not SLUG_RE.match(args.slug):
        print(f"ERROR: {args.slug!r} is not a GitHub owner/repo slug")
        return 1

    changed = 0
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if ".git" in path.parts or "results" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if args.old not in text:
            continue
        changed += 1
        print(("would update " if args.dry_run else "updated ") + str(path.relative_to(REPO_ROOT)))
        if not args.dry_run:
            path.write_text(text.replace(args.old, args.slug), encoding="utf-8")
    print(f"{changed} file(s) {'would change' if args.dry_run else 'changed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
