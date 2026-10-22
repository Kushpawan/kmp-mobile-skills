#!/usr/bin/env python3
"""Tests for kover_gaps.py. Standard library only.

    python3 -m unittest discover -s skills/kmp-test-coverage-backfill/scripts -p "test_*.py"
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kover_gaps as kg  # noqa: E402


def cls(name, source, line, branch=(0, 0)):
    """line/branch = (covered, missed)."""
    return (f'<class name="{name}" sourcefilename="{source}">'
            f'<counter type="INSTRUCTION" missed="1" covered="1"/>'
            f'<counter type="BRANCH" missed="{branch[1]}" covered="{branch[0]}"/>'
            f'<counter type="LINE" missed="{line[1]}" covered="{line[0]}"/></class>')


REPORT = f"""<?xml version="1.0" ?>
<report name="Kover Gradle Plugin XML report for :shared">
<package name="com/example/app/notes">
{cls("com/example/app/notes/NotesViewModel", "NotesViewModel.kt", (10, 20), (2, 4))}
{cls("com/example/app/notes/NotesViewModel$load$1", "NotesViewModel.kt", (0, 15), (0, 8))}
{cls("com/example/app/notes/SaveNoteUseCase", "SaveNoteUseCase.kt", (0, 40))}
{cls("com/example/app/notes/NoteMapper", "NoteMapper.kt", (5, 30), (0, 12))}
{cls("com/example/app/notes/PlainMapper", "PlainMapper.kt", (0, 50))}
{cls("com/example/app/notes/NotesRepositoryImpl", "NotesRepositoryImpl.kt", (0, 60), (0, 2))}
{cls("com/example/app/notes/NotesScreenKt", "NotesScreen.kt", (0, 90))}
{cls("com/example/app/notes/NoteDto$$serializer", "NoteDto.kt", (0, 70))}
{cls("com/example/app/notes/FullyCovered", "FullyCovered.kt", (9, 0))}
</package>
<counter type="INSTRUCTION" missed="400" covered="100"/>
<counter type="BRANCH" missed="26" covered="2"/>
<counter type="LINE" missed="375" covered="24"/>
</report>
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.dir = Path(self._t.name)
        self.report = self.dir / "report.xml"
        self.report.write_text(REPORT)
        self.exclusions = self.dir / "coverage-exclusions.txt"
        self.exclusions.write_text("# generated\n*$$serializer\n\n# ui\n*.notes.*ScreenKt\n")

    def tearDown(self):
        self._t.cleanup()

    def build(self, **kw):
        return kg.build(self.report, **kw)


class Totals(Fixture):
    def test_should_read_totals_from_the_report_when_parsing(self):
        doc = self.build()
        self.assertEqual(doc["totals"]["line"], {"covered": 24, "missed": 375, "pct": round(2400 / 399, 2)})
        self.assertEqual(doc["totals"]["branch"]["missed"], 26)
        self.assertFalse(doc["meets_targets"])

    def test_should_compute_the_exact_gap_when_below_target(self):
        doc = self.build(line_target=80, branch_target=60)
        self.assertEqual(doc["gap"]["lines_to_cover"], 320 - 24)      # ceil(399 * 0.8) = 320
        self.assertEqual(doc["gap"]["branches_to_cover"], 17 - 2)     # ceil(28 * 0.6) = 17

    def test_should_report_zero_gap_when_already_above_target(self):
        doc = self.build(line_target=5, branch_target=5)
        self.assertEqual(doc["gap"], {"lines_to_cover": 0, "branches_to_cover": 0})
        self.assertTrue(doc["meets_targets"])

    def test_should_report_the_delta_when_given_a_previous_report(self):
        previous = self.dir / "before.xml"
        previous.write_text(REPORT.replace('<counter type="LINE" missed="375" covered="24"/>\n</report>',
                                           '<counter type="LINE" missed="389" covered="10"/>\n</report>'))
        doc = self.build(previous=previous)
        self.assertAlmostEqual(doc["delta"]["line"], round(round(2400 / 399, 2) - round(1000 / 399, 2), 2))
        self.assertEqual(doc["delta"]["branch"], 0.0)


class Ranking(Fixture):
    def ranked(self, **kw):
        return [c["class"].rsplit(".", 1)[-1] for c in self.build(top=0, **kw)["candidates"]]

    def test_should_merge_synthetic_classes_into_their_owner(self):
        vm = next(c for c in self.build()["candidates"] if c["class"].endswith("NotesViewModel"))
        self.assertEqual(vm["missed_lines"], 35)
        self.assertEqual(vm["missed_branches"], 12)
        self.assertEqual(vm["merged_synthetic"], 1)
        self.assertFalse(any("$" in c["class"] for c in self.build(top=0)["candidates"]))

    def test_should_order_by_bucket_then_missed_lines(self):
        order = self.ranked(exclusions_path=self.exclusions)
        self.assertEqual(order, ["NotesViewModel", "SaveNoteUseCase", "NoteMapper", "NotesRepositoryImpl", "PlainMapper"])

    def test_should_promote_a_class_one_bucket_when_it_misses_many_branches(self):
        mapper = next(c for c in self.build()["candidates"] if c["class"].endswith("NoteMapper"))
        self.assertEqual(mapper["bucket"], "mapper")
        self.assertTrue(mapper["promoted"])
        self.assertEqual(mapper["priority"], 4)

    def test_should_treat_a_mapper_without_branches_as_other(self):
        plain = next(c for c in self.build()["candidates"] if c["class"].endswith("PlainMapper"))
        self.assertEqual(plain["bucket"], "other")

    def test_should_drop_fully_covered_classes(self):
        self.assertNotIn("FullyCovered", self.ranked())

    def test_should_limit_the_list_when_top_is_given(self):
        doc = self.build(top=2)
        self.assertEqual(len(doc["candidates"]), 2)
        self.assertEqual(doc["candidate_count"], 7)


class Exclusions(Fixture):
    def test_should_skip_classes_matching_the_exclusion_globs(self):
        doc = self.build(exclusions_path=self.exclusions, top=0)
        names = [c["class"] for c in doc["candidates"]]
        self.assertNotIn("com.example.app.notes.NotesScreenKt", names)
        self.assertNotIn("com.example.app.notes.NoteDto", names)
        reasons = {s["class"]: s["reason"] for s in doc["skipped"]}
        self.assertIn("'*$$serializer'", reasons["com.example.app.notes.NoteDto$$serializer"])

    def test_should_match_kover_glob_syntax(self):
        self.assertTrue(kg.glob_to_regex("*.ui.*Screen").match("com.example.app.ui.notes.NotesScreen"))
        self.assertTrue(kg.glob_to_regex("com.example.?pp.*").match("com.example.app.Foo"))
        self.assertFalse(kg.glob_to_regex("*.ui.*Screen").match("com.example.app.ui.NotesScreenKt"))
        self.assertTrue(kg.glob_to_regex("*$$serializer").match("a.B$$serializer"))

    def test_should_skip_compose_files_when_a_source_root_is_given(self):
        src = self.dir / "src" / "com" / "example" / "app" / "notes"
        src.mkdir(parents=True)
        (src / "NotesScreen.kt").write_text("@Composable\nfun NotesScreen() {}\n")
        doc = self.build(source_roots=[str(self.dir / "src")], top=0)
        self.assertNotIn("com.example.app.notes.NotesScreenKt", [c["class"] for c in doc["candidates"]])
        self.assertTrue(any("Compose UI file" in s["reason"] for s in doc["skipped"]))


class Cli(Fixture):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = kg.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_should_print_json_by_default(self):
        code, out, _ = self.run_cli(str(self.report), "--exclusions", str(self.exclusions))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["candidates"][0]["rank"], 1)

    def test_should_print_a_table_when_asked(self):
        code, out, _ = self.run_cli(str(self.report), "--format", "table")
        self.assertEqual(code, 0)
        self.assertIn("meets targets: no", out)
        self.assertIn("NotesViewModel", out)

    def test_should_exit_two_when_the_report_is_missing(self):
        code, _, err = self.run_cli(str(self.dir / "nope.xml"))
        self.assertEqual(code, 2)
        self.assertIn("koverXmlReport", err)

    def test_should_exit_two_when_the_report_is_not_xml(self):
        bad = self.dir / "bad.xml"
        bad.write_text("<report><package>")
        code, _, err = self.run_cli(str(bad))
        self.assertEqual(code, 2)
        self.assertIn("not valid XML", err)

    def test_should_exit_two_when_the_root_is_not_a_report(self):
        other = self.dir / "other.xml"
        other.write_text("<testsuite/>")
        self.assertEqual(self.run_cli(str(other))[0], 2)

    def test_should_exit_zero_when_help_is_requested(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as e:
            kg.main(["--help"])
        self.assertEqual(e.exception.code, 0)
        self.assertIn("koverXmlReport", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
