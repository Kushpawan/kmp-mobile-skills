"""Tests for l10n_check.py. Run: python3 -m unittest discover -s scripts/tests -v"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import l10n_check  # noqa: E402

DEFAULT_XML = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name" translatable="false">Notes</string>
    <string name="greeting">Hello, %1$s!</string>
    <string name="notes_count_label">You have %1$d notes in %2$s</string>
    <string name="discount">50% off</string>
    <string name="multiline">First\\nSecond</string>
    <plurals name="notes_selected">
        <item quantity="one">%1$d note selected</item>
        <item quantity="other">%1$d notes selected</item>
    </plurals>
    <string-array name="sort_options">
        <item>Newest</item>
        <item>Oldest</item>
    </string-array>
</resources>
"""

FRENCH_XML = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="greeting">Bonjour, %s !</string>
    <string name="notes_count_label">Vous avez %1$d notes</string>
    <string name="only_in_french">Seulement ici</string>
    <plurals name="notes_selected">
        <item quantity="one">%1$d note sélectionnée</item>
    </plurals>
    <string-array name="sort_options">
        <item>Plus récentes</item>
    </string-array>
</resources>
"""


def write_resources(root: Path, files: dict[str, str]) -> Path:
    resources = root / "composeResources"
    for directory, content in files.items():
        (resources / directory).mkdir(parents=True, exist_ok=True)
        (resources / directory / "strings.xml").write_text(content, encoding="utf-8")
    return resources


class CheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.resources = write_resources(Path(self.temp.name), {"values": DEFAULT_XML, "values-fr": FRENCH_XML})
        self.findings = l10n_check.check(self.resources)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def codes_for(self, key: str) -> set[str]:
        return {f.code for f in self.findings if f.key == key and f.locale == "values-fr"}

    def test_should_reportUnsupportedPlaceholder_when_nonPositionalPercentS(self) -> None:
        self.assertIn("unsupported-placeholder", self.codes_for("greeting"))

    def test_should_reportPlaceholderMismatch_when_translationDropsArgument(self) -> None:
        self.assertIn("placeholder-mismatch", self.codes_for("notes_count_label"))

    def test_should_reportMissingDefault_when_keyOnlyInTranslation(self) -> None:
        self.assertIn("missing-default", self.codes_for("only_in_french"))

    def test_should_reportPluralMissingOther_when_otherAbsent(self) -> None:
        self.assertIn("plural-missing-other", self.codes_for("notes_selected"))

    def test_should_reportArraySizeMismatch_when_itemCountDiffers(self) -> None:
        self.assertIn("array-size-mismatch", self.codes_for("sort_options"))

    def test_should_warnMissingTranslation_when_keyAbsentInLocale(self) -> None:
        self.assertIn("missing-translation", self.codes_for("multiline"))

    def test_should_skipUntranslatable_when_translatableFalse(self) -> None:
        self.assertEqual(set(), self.codes_for("app_name"))

    def test_should_notReportLiteralPercent_when_followedBySpace(self) -> None:
        discount = [f for f in self.findings if f.key == "discount" and f.code == "unsupported-placeholder"]
        self.assertEqual([], discount)

    def test_should_returnExitCodeOne_when_errorsFound(self) -> None:
        with redirect_stdout(io.StringIO()) as output:
            code = l10n_check.main(["check", str(self.resources)])
        self.assertEqual(1, code)
        self.assertGreater(json.loads(output.getvalue())["errors"], 0)

    def test_should_returnExitCodeZero_when_onlyDefaultLocale(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            clean = write_resources(Path(other), {"values": DEFAULT_XML})
            with redirect_stdout(io.StringIO()):
                self.assertEqual(0, l10n_check.main(["check", str(clean)]))


class PseudoTest(unittest.TestCase):
    def test_should_preservePlaceholdersAndEscapes_when_pseudolocalising(self) -> None:
        text = l10n_check.pseudo_text("Hello, %1$s!\\nBye \\u2605", expand=0.4)
        self.assertIn("%1$s", text)
        self.assertIn("\\n", text)
        self.assertIn("\\u2605", text)
        self.assertTrue(text.startswith("[") and text.endswith("]"))
        self.assertNotIn("Hello", text)

    def test_should_writeNothing_when_dryRun(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            resources = write_resources(Path(temp), {"values": DEFAULT_XML})
            report = l10n_check.pseudo(resources, expand=0.4, dry_run=True)
            self.assertTrue(report["dry_run"])
            self.assertFalse((resources / l10n_check.PSEUDO_DIR).exists())

    def test_should_writeAllResourceKinds_when_notDryRun(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            resources = write_resources(Path(temp), {"values": DEFAULT_XML})
            report = l10n_check.pseudo(resources, expand=0.4, dry_run=False)
            root = ET.parse(report["target"]).getroot()
            names = {element.get("name") for element in root}
            self.assertNotIn("app_name", names)  # translatable="false" is skipped
            self.assertIn("notes_selected", names)
            self.assertIn("sort_options", names)
            self.assertEqual([], [f for f in l10n_check.check(resources) if f.severity == "error"])


if __name__ == "__main__":
    unittest.main()
