"""Tests for catalog_drift.py. Run: python3 -m unittest discover -s scripts/tests (from the skill dir)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "catalog_drift.py"
spec = importlib.util.spec_from_file_location("catalog_drift", SCRIPT)
catalog_drift = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog_drift)

APP = """
[versions]
kotlin = "2.1.0"
ktor = "3.0.0"
coroutines = { strictly = "[1.9, 2.0[", prefer = "1.9.0" }

[libraries]
ktor-client-core = { module = "io.ktor:ktor-client-core", version.ref = "ktor" }
coroutines-core = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-core", version.ref = "coroutines" }
turbine = "app.cash.turbine:turbine:1.1.0"
firebase-crashlytics = { module = "com.google.firebase:firebase-crashlytics" }

[plugins]
kotlinMultiplatform = { id = "org.jetbrains.kotlin.multiplatform", version.ref = "kotlin" }
"""

SDK = """
[versions]
kotlin = "2.2.0"
ktor = "3.0.0"
coroutines = { prefer = "1.9.0", strictly = "[1.9, 2.0[" }
onlyInSdk = "1.0"

[libraries]
ktor-client-core = { module = "io.ktor:ktor-client-core", version.ref = "ktor" }
coroutines-core = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-core", version.ref = "coroutines" }
turbine = { module = "app.cash.turbine:turbine", version = "1.2.0" }
firebase-crashlytics = { module = "com.google.firebase:firebase-crashlytics" }

[plugins]
kotlinMultiplatform = { id = "org.jetbrains.kotlin.multiplatform", version.ref = "kotlin" }
"""


class CatalogDriftTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = self.write("app/libs.versions.toml", APP)
        self.sdk = self.write("sdk/libs.versions.toml", SDK)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, relative: str, content: str) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        return str(path)

    def run_main(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = catalog_drift.main(list(argv))
        return code, out.getvalue()

    def report(self, *extra: str) -> dict:
        code, out = self.run_main(f"app={self.app}", f"sdk={self.sdk}", "--format", "json", *extra)
        self.assertEqual(0, code)
        return json.loads(out)

    def drift_keys(self, report: dict, section: str) -> dict[str, str]:
        return {item["key"]: item["status"] for item in report["drift"][section]}

    def test_should_reportDifferingVersion_when_kotlinValuesDiffer(self) -> None:
        report = self.report()
        entry = next(i for i in report["drift"]["versions"] if i["key"] == "kotlin")
        self.assertEqual({"app": "2.1.0", "sdk": "2.2.0"}, entry["values"])
        self.assertEqual("differs", entry["status"])

    def test_should_treatRichVersionsAsEqual_when_onlyKeyOrderDiffers(self) -> None:
        self.assertNotIn("coroutines", self.drift_keys(self.report(), "versions"))

    def test_should_reportMissingKey_when_absentFromOneCatalog(self) -> None:
        self.assertEqual("missing", self.drift_keys(self.report(), "versions")["onlyInSdk"])

    def test_should_hideMissingKeys_when_onlyDiffersIsSet(self) -> None:
        self.assertNotIn("onlyInSdk", self.drift_keys(self.report("--only-differs"), "versions"))

    def test_should_reportLibraryDrift_when_resolvedVersionsDiffer(self) -> None:
        libraries = self.drift_keys(self.report(), "libraries")
        self.assertEqual("differs", libraries["turbine"])
        self.assertNotIn("ktor-client-core", libraries)
        self.assertNotIn("firebase-crashlytics", libraries)

    def test_should_reportPluginDrift_when_versionRefResolvesDifferently(self) -> None:
        self.assertIn("kotlinMultiplatform", self.drift_keys(self.report(), "plugins"))

    def test_should_listInlineVersions_when_entriesSkipVersionRef(self) -> None:
        inline = {(i["catalog"], i["alias"]) for i in self.report()["inline"]}
        self.assertEqual({("app", "turbine"), ("sdk", "turbine")}, inline)

    def test_should_flagMissingVersionRef_when_refIsUndefined(self) -> None:
        broken = self.write("broken/libs.versions.toml", """
            [versions]
            [libraries]
            ktor = { module = "io.ktor:ktor-client-core", version.ref = "ktor" }
        """)
        code, out = self.run_main(broken, "--format", "json")
        self.assertEqual(0, code)
        self.assertEqual([], json.loads(out)["drift"]["libraries"])
        described = catalog_drift.describe(catalog_drift.load_catalog(broken))
        self.assertIn("missing version.ref 'ktor'", described["libraries"]["ktor"])

    def test_should_findHardcodedVersions_when_scanningBuildScripts(self) -> None:
        self.write("project/feature/build.gradle.kts", """
            plugins {
                id("com.example.convention") version "1.0.0"
                kotlin("multiplatform") version "2.1.0"
            }
            dependencies {
                implementation("io.ktor:ktor-client-core:3.0.0")
                // implementation("io.ktor:ktor-client-mock:3.0.0")
                implementation(libs.koin.core)
            }
        """)
        self.write("project/feature/build/generated.gradle.kts", 'implementation("a:b:1.0")\n')
        report = self.report("--scan-gradle", str(self.root / "project"))
        texts = sorted(hit["text"] for hit in report["hardcoded"])
        self.assertEqual(
            ["com.example.convention version 1.0.0", "io.ktor:ktor-client-core:3.0.0",
             "kotlin(multiplatform) version 2.1.0"],
            texts,
        )

    def test_should_exitOne_when_driftAndFailOnDrift(self) -> None:
        code, _ = self.run_main(self.app, self.sdk, "--fail-on-drift")
        self.assertEqual(1, code)

    def test_should_exitZero_when_catalogsMatchAndFailOnDrift(self) -> None:
        code, out = self.run_main(f"a={self.app}", f"b={self.app}", "--fail-on-drift")
        self.assertEqual(0, code)
        self.assertIn("versions_drift=0", out)

    def test_should_exitTwo_when_tomlIsInvalid(self) -> None:
        bad = self.write("bad/libs.versions.toml", "[versions\nkotlin = ")
        code, _ = self.run_main(bad)
        self.assertEqual(2, code)

    def test_should_exitTwo_when_fileIsMissing(self) -> None:
        code, _ = self.run_main(str(self.root / "nope.toml"))
        self.assertEqual(2, code)

    def test_should_disambiguateLabels_when_sameLabelGivenTwice(self) -> None:
        pairs = catalog_drift.parse_catalog_args(["x=a.toml", "x=b.toml", "dir/c=d.toml"])
        self.assertEqual([("x", "a.toml"), ("x#2", "b.toml"), ("dir/c=d.toml", "dir/c=d.toml")], pairs)

    def test_should_printHelp_when_helpFlagGiven(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as raised:
            catalog_drift.main(["--help"])
        self.assertEqual(0, raised.exception.code)
        self.assertIn("--fail-on-drift", out.getvalue())


if __name__ == "__main__":
    unittest.main()
