#!/usr/bin/env python3
"""Rank the classes in a Kover XML report by how much testing them would raise coverage.

Reads the JaCoCo-style XML that `./gradlew :<module>:koverXmlReport` writes (by default
<module>/build/reports/kover/report.xml) and prints JSON:

  totals      line / branch / instruction counters and percentages, straight from the report
  gap         how many more lines and branches must be covered to reach the targets
  candidates  testable classes, best target first (priority bucket, then missed lines)
  skipped     classes dropped by the exclusion file or as Compose UI, with the reason

Synthetic classes (Foo$bar$1 lambdas, Foo$Companion, Foo$WhenMappings) are merged into their
owner Foo: their lines are covered by testing Foo, so they count toward Foo's impact.

Examples:
  python3 kover_gaps.py shared/build/reports/kover/report.xml
  python3 kover_gaps.py report.xml --exclusions gradle/coverage-exclusions.txt --top 15
  python3 kover_gaps.py report.xml --previous /tmp/report-iter1.xml --format table
  python3 kover_gaps.py report.xml --source-root shared/src/commonMain/kotlin

Exit status: 0 ok, 2 bad input. Python 3.9+, standard library only. Reads files; writes nothing.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# (bucket, priority, test) - lower priority number = test first.
BUCKETS = (
    ("viewmodel", 1, lambda n, c: n.endswith("ViewModel")),
    ("usecase", 2, lambda n, c: n.endswith("UseCase")),
    ("state-machine", 3, lambda n, c: n.endswith(("StateMachine", "Reducer"))),
    ("validator", 4, lambda n, c: n.endswith(("Validator", "Gate", "Policy", "Guard"))),
    ("mapper", 5, lambda n, c: "Mapper" in n and c["branch_total"] > 0),
    ("repository", 6, lambda n, c: n.endswith(("RepositoryImpl", "Repository"))),
    ("top-level-functions", 7, lambda n, c: n.endswith("Kt")),
    ("factory", 8, lambda n, c: n.endswith("Factory")),
)
OTHER = ("other", 9)
PROMOTE_AT_MISSED_BRANCHES = 10


def glob_to_regex(pattern: str):
    """Kover class-filter syntax: * = any run of characters, ? = exactly one."""
    out = "".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in pattern.strip())
    return re.compile(f"^{out}$")


def load_exclusions(path) -> list:
    if path is None:
        return []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [(p.strip(), glob_to_regex(p)) for p in lines if p.strip() and not p.strip().startswith("#")]


def _counters(element) -> dict:
    out = {}
    for c in element.findall("counter"):
        out[c.get("type")] = (int(c.get("covered", "0")), int(c.get("missed", "0")))
    return out


def _pct(covered: int, missed: int):
    total = covered + missed
    return round(100.0 * covered / total, 2) if total else None


def totals(root) -> dict:
    out = {}
    for kind, (covered, missed) in _counters(root).items():
        out[kind.lower()] = {"covered": covered, "missed": missed, "pct": _pct(covered, missed)}
    return out


def parse_report(path):
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as e:
        raise ValueError(f"{path}: not valid XML ({e})")
    if root.tag != "report":
        raise ValueError(f"{path}: root element is <{root.tag}>, expected <report> (a Kover or JaCoCo XML report)")
    return root


def to_needed(t: dict, target: float) -> int:
    """Additional covered units needed so covered / total >= target %."""
    total = t["covered"] + t["missed"]
    return max(0, math.ceil(total * target / 100.0 - 1e-9) - t["covered"]) if total else 0


def classify(simple_name: str, counters: dict):
    for bucket, priority, test in BUCKETS:
        if test(simple_name, counters):
            return bucket, priority
    return OTHER


def find_source(roots: list, package_path: str, source_file: str):
    for root in roots:
        candidate = Path(root) / package_path / source_file
        if candidate.is_file():
            return candidate
    return None


def analyse(root, exclusions: list, source_roots: list) -> tuple:
    owners, skipped = {}, []
    for pkg in root.findall("package"):
        package_path = pkg.get("name", "")
        for cls in pkg.findall("class"):
            fqn = cls.get("name", "").replace("/", ".")
            hit = next((p for p, rx in exclusions if rx.match(fqn)), None)
            if hit:
                skipped.append({"class": fqn, "reason": f"excluded by {hit!r}"})
                continue
            owner = fqn.split("$", 1)[0]
            c = _counters(cls)
            lc, lm = c.get("LINE", (0, 0))
            bc, bm = c.get("BRANCH", (0, 0))
            o = owners.setdefault(owner, {"class": owner, "package_path": package_path,
                                          "source_file": cls.get("sourcefilename", ""), "covered_lines": 0,
                                          "missed_lines": 0, "covered_branches": 0, "missed_branches": 0,
                                          "merged_synthetic": 0})
            if fqn != owner:
                o["merged_synthetic"] += 1
            if not o["source_file"]:
                o["source_file"] = cls.get("sourcefilename", "")
            o["covered_lines"] += lc
            o["missed_lines"] += lm
            o["covered_branches"] += bc
            o["missed_branches"] += bm
    candidates = []
    for o in owners.values():
        if o["missed_lines"] == 0 and o["missed_branches"] == 0:
            continue
        simple = o["class"].rsplit(".", 1)[-1]
        if source_roots and simple.endswith("Kt") and o["source_file"]:
            src = find_source(source_roots, o["package_path"], o["source_file"])
            if src is not None and "@Composable" in src.read_text(encoding="utf-8", errors="replace"):
                skipped.append({"class": o["class"], "reason": f"Compose UI file ({src.name}) - not a unit-test target"})
                continue
        bucket, priority = classify(simple, {"branch_total": o["covered_branches"] + o["missed_branches"]})
        promoted = o["missed_branches"] >= PROMOTE_AT_MISSED_BRANCHES and priority > 1
        total_lines = o["covered_lines"] + o["missed_lines"]
        candidates.append({**{k: v for k, v in o.items() if k != "package_path"},
                           "bucket": bucket, "priority": priority - 1 if promoted else priority,
                           "promoted": promoted, "line_pct": _pct(o["covered_lines"], o["missed_lines"]),
                           "total_lines": total_lines})
    candidates.sort(key=lambda c: (c["priority"], -c["missed_lines"], -c["missed_branches"], c["class"]))
    for i, c in enumerate(candidates, 1):
        c["rank"] = i
    return candidates, skipped


def build(report_path: Path, exclusions_path=None, top: int = 30, line_target: float = 80.0,
          branch_target: float = 60.0, previous=None, source_roots=None) -> dict:
    root = parse_report(report_path)
    t = totals(root)
    line = t.get("line", {"covered": 0, "missed": 0, "pct": None})
    branch = t.get("branch", {"covered": 0, "missed": 0, "pct": None})
    candidates, skipped = analyse(root, load_exclusions(exclusions_path), source_roots or [])
    line_ok = line["pct"] is not None and line["pct"] >= line_target
    branch_ok = branch["pct"] is None or branch["pct"] >= branch_target   # no branches at all = nothing to miss
    doc = {
        "report": str(report_path),
        "report_name": root.get("name", ""),
        "totals": t,
        "targets": {"line": line_target, "branch": branch_target},
        "meets_targets": bool(line_ok and branch_ok),
        "gap": {"lines_to_cover": to_needed(line, line_target), "branches_to_cover": to_needed(branch, branch_target)},
        "candidate_count": len(candidates),
        "candidates": candidates[:top] if top > 0 else candidates,
        "skipped": skipped,
    }
    if previous is not None:
        before = totals(parse_report(previous))
        doc["delta"] = {k: (round(t[k]["pct"] - before[k]["pct"], 2)
                            if k in before and t[k]["pct"] is not None and before[k]["pct"] is not None else None)
                        for k in ("line", "branch") if k in t}
    return doc


def render_table(doc: dict) -> str:
    t = doc["totals"]

    def fmt(k):
        v = t.get(k, {})
        pct = v.get("pct")
        return f"{pct:.2f}% ({v.get('covered', 0)}/{v.get('covered', 0) + v.get('missed', 0)})" if pct is not None else "n/a"
    lines = [f"line {fmt('line')} target {doc['targets']['line']}% | branch {fmt('branch')} "
             f"target {doc['targets']['branch']}% | meets targets: {'yes' if doc['meets_targets'] else 'no'}",
             f"to reach targets: +{doc['gap']['lines_to_cover']} lines, +{doc['gap']['branches_to_cover']} branches"]
    if "delta" in doc:
        lines.append("delta vs previous: " + ", ".join(f"{k} {v:+.2f}%" for k, v in doc["delta"].items() if v is not None))
    lines.append("")
    lines.append(f"{'#':>3}  {'bucket':<20} {'missed L':>8} {'missed B':>8}  class")
    for c in doc["candidates"]:
        flag = " (promoted)" if c["promoted"] else ""
        lines.append(f"{c['rank']:>3}  {c['bucket']:<20} {c['missed_lines']:>8} {c['missed_branches']:>8}  {c['class']}{flag}")
    lines.append(f"\n{doc['candidate_count']} candidate(s), {len(doc['skipped'])} skipped")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kover_gaps.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", type=Path, help="Kover XML report (koverXmlReport output)")
    ap.add_argument("--exclusions", type=Path, help="exclusion globs, one per line (# comments allowed)")
    ap.add_argument("--top", type=int, default=30, help="candidates to list; 0 = all (default 30)")
    ap.add_argument("--line-target", type=float, default=80.0, help="line coverage target %% (default 80)")
    ap.add_argument("--branch-target", type=float, default=60.0, help="branch coverage target %% (default 60)")
    ap.add_argument("--previous", type=Path, help="an earlier report.xml, to print the coverage delta")
    ap.add_argument("--source-root", action="append", default=[], metavar="DIR",
                    help="source root (e.g. shared/src/commonMain/kotlin); skips *Kt files containing @Composable")
    ap.add_argument("--format", choices=["json", "table"], default="json")
    a = ap.parse_args(argv)
    for p in [a.report, a.previous, a.exclusions]:
        if p is not None and not p.is_file():
            print(f"not found: {p} - run ./gradlew :<module>:koverXmlReport first" if p != a.exclusions
                  else f"not found: {p}", file=sys.stderr)
            return 2
    try:
        doc = build(a.report, a.exclusions, a.top, a.line_target, a.branch_target, a.previous, a.source_root)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(render_table(doc) if a.format == "table" else json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
