"""Shared helpers for the repository scripts: skill discovery and frontmatter parsing.

The frontmatter parser understands the restricted YAML subset this repository allows
(see docs/skill-authoring-guide.md): scalar `key: value` pairs, quoted scalars, folded (`>`)
and literal (`|`) block scalars, inline `[a, b]` lists, and one level of nested mappings
(used by `metadata`). Standard library only, so contributors need no installs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
AGENTS_DIR = REPO_ROOT / "agents"
EVALS_DIR = REPO_ROOT / "evals"


class FrontmatterError(ValueError):
    """Raised when a file's frontmatter is missing or outside the supported subset."""


@dataclass
class Document:
    path: Path
    frontmatter: dict
    body: str
    body_start_line: int = 0
    raw_frontmatter: str = field(default="", repr=False)

    @property
    def body_line_count(self) -> int:
        return len(self.body.splitlines())


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        if value[0] == "'":
            return inner.replace("''", "'")
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return value


def _parse_scalar(value: str):
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        items = [item.strip() for item in value[1:-1].split(",")]
        return [_unquote(item) for item in items if item]
    return _unquote(value)


_KEY_RE = re.compile(r"^([A-Za-z0-9_.-]+):(?:\s+(.*))?$")


def parse_frontmatter_block(text: str) -> dict:
    """Parse the text between the `---` fences."""
    lines = text.splitlines()
    result: dict = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line[0].isspace():
            raise FrontmatterError(f"unexpected indentation at frontmatter line {i + 1}: {line!r}")
        match = _KEY_RE.match(line.rstrip())
        if not match:
            raise FrontmatterError(f"cannot parse frontmatter line {i + 1}: {line!r}")
        key, value = match.group(1), (match.group(2) or "").strip()
        if key in result:
            raise FrontmatterError(f"duplicate key {key!r}")
        i += 1
        if value in (">", "|", ">-", "|-", ">+", "|+"):
            block: list[str] = []
            while i < len(lines) and (not lines[i].strip() or lines[i][0].isspace()):
                block.append(lines[i].strip())
                i += 1
            if value.startswith(">"):
                paragraphs = " ".join(part if part else "\n" for part in block)
                result[key] = re.sub(r" ?\n ?", "\n", paragraphs).strip()
            else:
                result[key] = "\n".join(block).strip()
        elif value == "":
            nested: dict = {}
            while i < len(lines) and (not lines[i].strip() or lines[i][0].isspace()):
                sub = lines[i].strip()
                i += 1
                if not sub or sub.startswith("#"):
                    continue
                sub_match = _KEY_RE.match(sub)
                if not sub_match:
                    raise FrontmatterError(f"cannot parse nested line under {key!r}: {sub!r}")
                nested[sub_match.group(1)] = _parse_scalar(sub_match.group(2) or "")
            result[key] = nested
        else:
            result[key] = _parse_scalar(value)
    return result


def read_document(path: Path) -> Document:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise FrontmatterError("file does not start with a '---' frontmatter fence")
    lines = text.splitlines(keepends=True)
    end = None
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == "---":
            end = index
            break
    if end is None:
        raise FrontmatterError("frontmatter has no closing '---' fence")
    raw = "".join(lines[1:end])
    body = "".join(lines[end + 1 :])
    return Document(
        path=path,
        frontmatter=parse_frontmatter_block(raw),
        body=body,
        body_start_line=end + 2,
        raw_frontmatter=raw,
    )


def skill_dirs(skills_dir: Path = SKILLS_DIR) -> list[Path]:
    if not skills_dir.is_dir():
        return []
    return sorted(p for p in skills_dir.iterdir() if p.is_dir() and not p.name.startswith("."))


def agent_files(agents_dir: Path = AGENTS_DIR) -> list[Path]:
    if not agents_dir.is_dir():
        return []
    return sorted(agents_dir.glob("*.md"))
