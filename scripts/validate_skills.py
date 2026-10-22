#!/usr/bin/env python3
"""Validate every skill, agent and trigger eval against docs/skill-authoring-guide.md.

Usage:
    python3 scripts/validate_skills.py            # human-readable report
    python3 scripts/validate_skills.py --strict   # also fail on warnings (CI)
    python3 scripts/validate_skills.py --json     # machine-readable report

Exit code 0 when no errors (and, with --strict, no warnings); 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skilllib import (  # noqa: E402
    AGENTS_DIR,
    EVALS_DIR,
    REPO_ROOT,
    SKILLS_DIR,
    FrontmatterError,
    agent_files,
    read_document,
    skill_dirs,
)

ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
REQUIRED_KEYS = {"name", "description", "license", "metadata"}
CATEGORIES = {
    "build", "ui", "data", "ios-interop", "testing", "debug", "performance",
    "review", "workflow", "release", "migration", "tooling",
}
PLATFORM_VALUES = {"android", "ios"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
XML_TAG_RE = re.compile(r"<[A-Za-z/!][^>]*>")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
PLACEHOLDER = "OWNER/kmp-mobile-skills"
MAX_BODY_LINES = 500
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500


class Report:
    def __init__(self) -> None:
        self.errors: list[dict] = []
        self.warnings: list[dict] = []

    def error(self, path: Path, message: str) -> None:
        self.errors.append({"path": _rel(path), "message": message})

    def warn(self, path: Path, message: str) -> None:
        self.warnings.append({"path": _rel(path), "message": message})


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _strip_code(text: str) -> str:
    """Drop fenced and inline code so example links inside code are not checked."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", text)


def check_links(skill_dir: Path, markdown_file: Path, report: Report) -> None:
    text = _strip_code(markdown_file.read_text(encoding="utf-8"))
    for target in LINK_RE.findall(text):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        target_path = target.split("#", 1)[0]
        if not target_path:
            continue
        resolved = (markdown_file.parent / target_path).resolve()
        try:
            resolved.relative_to(skill_dir.resolve())
        except ValueError:
            report.error(markdown_file, f"link escapes the skill directory: {target}")
            continue
        if not resolved.exists():
            report.error(markdown_file, f"broken relative link: {target}")


def check_skill(skill_dir: Path, report: Report) -> dict | None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        report.error(skill_dir, "missing SKILL.md")
        return None
    try:
        doc = read_document(skill_md)
    except FrontmatterError as exc:
        report.error(skill_md, f"frontmatter: {exc}")
        return None
    fm = doc.frontmatter

    for key in sorted(set(fm) - ALLOWED_KEYS):
        report.error(skill_md, f"non-portable frontmatter key {key!r} (allowed: {', '.join(sorted(ALLOWED_KEYS))})")
    for key in sorted(REQUIRED_KEYS - set(fm)):
        report.error(skill_md, f"missing required frontmatter key {key!r}")

    name = fm.get("name", "")
    if not isinstance(name, str) or not NAME_RE.match(name) or len(name) > 64:
        report.error(skill_md, f"invalid name {name!r}: 1-64 chars of a-z, 0-9 and single hyphens")
    if isinstance(name, str) and name != skill_dir.name:
        report.error(skill_md, f"name {name!r} does not match directory {skill_dir.name!r}")
    if isinstance(name, str) and re.search(r"claude|anthropic", name):
        report.error(skill_md, "name must not contain 'claude' or 'anthropic'")

    description = fm.get("description", "")
    if not isinstance(description, str) or not description.strip():
        report.error(skill_md, "description is empty")
    else:
        if len(description) > MAX_DESCRIPTION:
            report.error(skill_md, f"description is {len(description)} chars (max {MAX_DESCRIPTION})")
        elif len(description) > 600:
            report.warn(skill_md, f"description is {len(description)} chars; aim for under 600")
        if XML_TAG_RE.search(description):
            report.error(skill_md, "description must not contain XML/HTML tags")
        if not description.startswith("Use when"):
            report.error(skill_md, "description must start with 'Use when'")

    compatibility = fm.get("compatibility")
    if compatibility is not None and (not isinstance(compatibility, str) or len(compatibility) > MAX_COMPATIBILITY):
        report.error(skill_md, f"compatibility must be a string of at most {MAX_COMPATIBILITY} chars")

    if "allowed-tools" in fm:
        report.warn(skill_md, "allowed-tools is discouraged (see guide section 2)")

    license_id = fm.get("license")
    if license_id is not None and not isinstance(license_id, str):
        report.error(skill_md, "license must be a string")

    metadata = fm.get("metadata", {})
    if not isinstance(metadata, dict):
        report.error(skill_md, "metadata must be a mapping of string to string")
        metadata = {}
    for key, value in metadata.items():
        if not isinstance(value, str):
            report.error(skill_md, f"metadata.{key} must be a string")
    category = metadata.get("category")
    if category not in CATEGORIES:
        report.error(skill_md, f"metadata.category {category!r} not in {sorted(CATEGORIES)}")
    platforms = metadata.get("platforms", "")
    platform_set = {p.strip() for p in str(platforms).split(",") if p.strip()}
    if not platform_set or not platform_set <= PLATFORM_VALUES:
        report.error(skill_md, f"metadata.platforms {platforms!r} must list android and/or ios")

    if doc.body_line_count > MAX_BODY_LINES:
        report.error(skill_md, f"body is {doc.body_line_count} lines (max {MAX_BODY_LINES}); move detail to references/")
    if not doc.body.lstrip().startswith("# "):
        report.warn(skill_md, "body should start with a '# Title' heading")

    for markdown_file in sorted(skill_dir.rglob("*.md")):
        check_links(skill_dir, markdown_file, report)
        text = _strip_code(markdown_file.read_text(encoding="utf-8"))
        if re.search(r"\bTODO\b", text):
            report.warn(markdown_file, "contains TODO")

    for script in sorted(skill_dir.rglob("*")):
        if script.is_file() and script.suffix in {".sh", ".py"} and script.stat().st_size == 0:
            report.error(script, "empty script")

    check_trigger_eval(skill_dir.name, report)
    return {
        "name": name,
        "category": category,
        "platforms": sorted(platform_set),
        "description": description,
        "body_lines": doc.body_line_count,
    }


def check_trigger_eval(skill_name: str, report: Report) -> None:
    case_dir = EVALS_DIR / f"{skill_name}-trigger"
    prompt = case_dir / "prompt.md"
    grader = case_dir / "graders" / "skill-fired.md"
    if not prompt.is_file():
        report.error(case_dir, "missing trigger eval prompt.md (run scripts/scaffold_trigger_eval.py)")
        return
    try:
        doc = read_document(prompt)
        if not doc.body.strip() or "TODO" in doc.body:
            report.error(prompt, "trigger eval prompt is empty or still a TODO")
    except FrontmatterError as exc:
        report.error(prompt, f"frontmatter: {exc} (run scripts/scaffold_trigger_eval.py)")
    if not grader.is_file():
        report.error(case_dir, "missing graders/skill-fired.md (run scripts/scaffold_trigger_eval.py)")
    elif skill_name not in grader.read_text(encoding="utf-8"):
        report.error(grader, f"grader does not reference skill {skill_name!r}")


def check_orphan_evals(skill_names: set[str], report: Report) -> None:
    if not EVALS_DIR.is_dir():
        return
    for case_dir in sorted(p for p in EVALS_DIR.iterdir() if p.is_dir()):
        if case_dir.name == "results":
            continue
        if case_dir.name.endswith("-trigger") and case_dir.name[: -len("-trigger")] not in skill_names:
            report.error(case_dir, "trigger eval for a skill that does not exist")


def check_agents(report: Report) -> None:
    for agent in agent_files(AGENTS_DIR):
        try:
            doc = read_document(agent)
        except FrontmatterError as exc:
            report.error(agent, f"frontmatter: {exc}")
            continue
        for key in ("name", "description"):
            if not doc.frontmatter.get(key):
                report.error(agent, f"agent frontmatter missing {key!r}")
        if doc.frontmatter.get("name") and doc.frontmatter["name"] != agent.stem:
            report.error(agent, "agent name must match file name")


def check_placeholder(report: Report) -> None:
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file() or ".git" in path.parts or "results" in path.parts:
            continue
        if path.suffix not in {".md", ".json", ".yml", ".yaml"}:
            continue
        if PLACEHOLDER in path.read_text(encoding="utf-8", errors="ignore"):
            report.warn(path, f"still contains the placeholder {PLACEHOLDER!r}; run scripts/set_repo.py <owner>/<repo>")
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    args = parser.parse_args(argv)

    report = Report()
    skills = [info for d in skill_dirs(SKILLS_DIR) if (info := check_skill(d, report))]
    check_orphan_evals({s["name"] for s in skills}, report)
    check_agents(report)
    check_placeholder(report)

    failed = bool(report.errors) or (args.strict and bool(report.warnings))
    if args.json:
        print(json.dumps({"skills": skills, "errors": report.errors, "warnings": report.warnings, "ok": not failed}, indent=2))
    else:
        for item in report.errors:
            print(f"ERROR   {item['path']}: {item['message']}")
        for item in report.warnings:
            print(f"WARNING {item['path']}: {item['message']}")
        print(f"{len(skills)} skills, {len(agent_files(AGENTS_DIR))} agents, "
              f"{len(report.errors)} errors, {len(report.warnings)} warnings -> {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
