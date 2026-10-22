"""Tests for the repository maintenance scripts (stdlib unittest)."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import scaffold_trigger_eval  # noqa: E402
import skilllib  # noqa: E402
import sync_manifests  # noqa: E402
import validate_skills  # noqa: E402

GOOD_SKILL = textwrap.dedent(
    """\
    ---
    name: demo-skill
    description: Use when testing the validator with a well-formed skill.
    license: Apache-2.0
    compatibility: Any project.
    metadata:
      category: testing
      platforms: android, ios
    ---

    # Demo skill

    See [the reference](references/detail.md).
    """
)


class FakeRepo:
    """A throwaway repository layout with patched module paths."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for sub in ("skills", "agents", "evals"):
            (self.root / sub).mkdir()
        self._patches = []
        for module in (skilllib, validate_skills, sync_manifests, scaffold_trigger_eval):
            for attr, value in (
                ("REPO_ROOT", self.root),
                ("SKILLS_DIR", self.root / "skills"),
                ("AGENTS_DIR", self.root / "agents"),
                ("EVALS_DIR", self.root / "evals"),
            ):
                if hasattr(module, attr):
                    patcher = mock.patch.object(module, attr, value)
                    patcher.start()
                    self._patches.append(patcher)

    def add_skill(self, name: str, content: str, with_eval: bool = True) -> Path:
        skill = self.root / "skills" / name
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text(content, encoding="utf-8")
        (skill / "references" / "detail.md").write_text("# Detail\n", encoding="utf-8")
        if with_eval:
            case = self.root / "evals" / f"{name}-trigger"
            case.mkdir()
            (case / "prompt.md").write_text("My app needs this.\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                scaffold_trigger_eval.scaffold(name, dry_run=False)
        return skill

    def close(self) -> None:
        for patcher in self._patches:
            patcher.stop()
        self._tmp.cleanup()


def run_validator(*args: str) -> tuple[int, dict]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = validate_skills.main(["--json", *args])
    return code, json.loads(buffer.getvalue())


class FrontmatterParserTest(unittest.TestCase):
    def test_should_parse_nested_metadata_and_block_scalars(self) -> None:
        parsed = skilllib.parse_frontmatter_block(
            "name: x\ndescription: >\n  Use when one\n  and two.\nmetadata:\n  category: ui\n  platforms: ios\n"
        )
        self.assertEqual(parsed["description"], "Use when one and two.")
        self.assertEqual(parsed["metadata"], {"category": "ui", "platforms": "ios"})

    def test_should_keep_non_ascii_text_when_double_quoted(self) -> None:
        parsed = skilllib.parse_frontmatter_block('description: "Use when — crash on iOS"\n')
        self.assertEqual(parsed["description"], "Use when — crash on iOS")

    def test_should_reject_duplicate_keys(self) -> None:
        with self.assertRaises(skilllib.FrontmatterError):
            skilllib.parse_frontmatter_block("name: a\nname: b\n")



class ValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = FakeRepo()

    def tearDown(self) -> None:
        self.repo.close()

    def test_should_pass_when_skill_is_well_formed(self) -> None:
        self.repo.add_skill("demo-skill", GOOD_SKILL)
        code, report = run_validator()
        self.assertEqual(code, 0, report["errors"])

    def test_should_fail_when_name_does_not_match_directory(self) -> None:
        self.repo.add_skill("other-name", GOOD_SKILL)
        code, report = run_validator()
        self.assertEqual(code, 1)
        self.assertTrue(any("does not match directory" in e["message"] for e in report["errors"]))

    def test_should_fail_when_frontmatter_has_non_portable_key(self) -> None:
        self.repo.add_skill("demo-skill", GOOD_SKILL.replace("license:", "user-invocable: true\nlicense:"))
        code, report = run_validator()
        self.assertEqual(code, 1)
        self.assertTrue(any("non-portable" in e["message"] for e in report["errors"]))

    def test_should_fail_when_description_does_not_start_with_use_when(self) -> None:
        self.repo.add_skill("demo-skill", GOOD_SKILL.replace("Use when testing", "Tests"))
        code, _ = run_validator()
        self.assertEqual(code, 1)

    def test_should_fail_when_relative_link_is_broken(self) -> None:
        self.repo.add_skill("demo-skill", GOOD_SKILL.replace("references/detail.md", "references/missing.md"))
        code, report = run_validator()
        self.assertEqual(code, 1)
        self.assertTrue(any("broken relative link" in e["message"] for e in report["errors"]))

    def test_should_fail_when_trigger_eval_is_missing(self) -> None:
        self.repo.add_skill("demo-skill", GOOD_SKILL, with_eval=False)
        code, report = run_validator()
        self.assertEqual(code, 1)
        self.assertTrue(any("trigger eval" in e["message"] for e in report["errors"]))

    def test_should_fail_when_body_exceeds_line_limit(self) -> None:
        self.repo.add_skill("demo-skill", GOOD_SKILL + "line\n" * 501)
        code, report = run_validator()
        self.assertEqual(code, 1)
        self.assertTrue(any("max 500" in e["message"] for e in report["errors"]))



class SyncManifestsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = FakeRepo()
        self.repo.add_skill("demo-skill", GOOD_SKILL)
        (self.repo.root / ".codex-plugin").mkdir()
        (self.repo.root / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "x", "version": "0.1.0", "skills": []}, indent=2) + "\n", encoding="utf-8"
        )
        (self.repo.root / "README.md").write_text(
            "# X\n\n<!-- catalog:start -->\nold\n<!-- catalog:end -->\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.repo.close()

    def test_should_report_out_of_date_then_pass_after_sync(self) -> None:
        with redirect_stdout(io.StringIO()):
            self.assertEqual(sync_manifests.main(["--check"]), 1)
            self.assertEqual(sync_manifests.main([]), 0)
            self.assertEqual(sync_manifests.main(["--check"]), 0)
        manifest = json.loads((self.repo.root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["skills"], ["./skills/demo-skill"])
        readme = (self.repo.root / "README.md").read_text(encoding="utf-8")
        self.assertIn("[`demo-skill`](skills/demo-skill/SKILL.md)", readme)

    def test_should_reject_non_semver_version(self) -> None:
        with redirect_stdout(io.StringIO()):
            self.assertEqual(sync_manifests.main(["--version", "v1"]), 1)



if __name__ == "__main__":
    unittest.main()
