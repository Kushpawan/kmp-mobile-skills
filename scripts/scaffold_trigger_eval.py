#!/usr/bin/env python3
"""Create or complete the trigger eval for one or more skills.

A trigger eval is one `claude plugin eval` case that checks a realistic user prompt makes the
agent load the skill. For each skill it ensures:

  evals/<skill>-trigger/prompt.md            frontmatter (run limits) + the user prompt
  evals/<skill>-trigger/graders/skill-fired.md  passes when the Skill tool loads <skill>

An existing prompt body is kept; only missing frontmatter or graders are added.

Usage:
    python3 scripts/scaffold_trigger_eval.py kmp-crash-triage
    python3 scripts/scaffold_trigger_eval.py --all
    python3 scripts/scaffold_trigger_eval.py --all --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skilllib import EVALS_DIR, SKILLS_DIR, skill_dirs  # noqa: E402

PROMPT_FRONTMATTER = """---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

"""
PLACEHOLDER_BODY = "TODO: write the request a developer would type that should load this skill, without naming it.\n"
GRADER = """---
type: tool_used
tool: Skill
input_match: '"skill"\\s*:\\s*"(?:[\\w-]+:)?{name}"'
---
"""


def scaffold(name: str, dry_run: bool) -> list[str]:
    actions = []
    case_dir = EVALS_DIR / f"{name}-trigger"
    prompt = case_dir / "prompt.md"
    grader = case_dir / "graders" / "skill-fired.md"

    if not prompt.exists():
        actions.append(f"create {prompt.relative_to(EVALS_DIR.parent)} (placeholder prompt — edit it)")
        if not dry_run:
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text(PROMPT_FRONTMATTER + PLACEHOLDER_BODY, encoding="utf-8")
    else:
        text = prompt.read_text(encoding="utf-8")
        if not text.startswith("---"):
            actions.append(f"add frontmatter to {prompt.relative_to(EVALS_DIR.parent)}")
            if not dry_run:
                prompt.write_text(PROMPT_FRONTMATTER + text.lstrip(), encoding="utf-8")

    if not grader.exists():
        actions.append(f"create {grader.relative_to(EVALS_DIR.parent)}")
        if not dry_run:
            grader.parent.mkdir(parents=True, exist_ok=True)
            grader.write_text(GRADER.format(name=name), encoding="utf-8")
    return actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("skills", nargs="*", help="skill names (directory names under skills/)")
    parser.add_argument("--all", action="store_true", help="process every skill")
    parser.add_argument("--dry-run", action="store_true", help="print what would change without writing")
    args = parser.parse_args(argv)

    names = [d.name for d in skill_dirs(SKILLS_DIR)] if args.all else args.skills
    if not names:
        parser.error("name at least one skill, or pass --all")
    unknown = [n for n in names if not (SKILLS_DIR / n / "SKILL.md").is_file()]
    if unknown:
        print(f"ERROR: unknown skill(s): {', '.join(unknown)}")
        return 1

    total = 0
    for name in names:
        for action in scaffold(name, args.dry_run):
            print(("would " if args.dry_run else "") + action)
            total += 1
    print(f"{total} change(s){' planned' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
