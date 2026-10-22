#!/usr/bin/env python3
"""Run every Python test in the repository: repo scripts and scripts bundled inside skills.

Each directory that contains `test_*.py` files is discovered separately, because skill
directory names contain hyphens and cannot be imported as packages.

Usage:
    python3 scripts/run_tests.py
    python3 scripts/run_tests.py --list   # show the test directories without running them
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_dirs() -> list[Path]:
    dirs = {p.parent for p in REPO_ROOT.rglob("test_*.py") if ".git" not in p.parts}
    return sorted(dirs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="list test directories and exit")
    args = parser.parse_args(argv)

    dirs = test_dirs()
    if args.list:
        for d in dirs:
            print(d.relative_to(REPO_ROOT))
        return 0

    results = []
    for d in dirs:
        rel = d.relative_to(REPO_ROOT)
        print(f"== {rel}", flush=True)
        code = subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", str(d), "-p", "test_*.py", "-t", str(d)])
        results.append((rel, code))

    print()
    for rel, code in results:
        print(f"{'PASS' if code == 0 else 'FAIL'}  {rel}")
    failed = [r for r in results if r[1] != 0]
    print(f"{len(results) - len(failed)}/{len(results)} test directories passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
