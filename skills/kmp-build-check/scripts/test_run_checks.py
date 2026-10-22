#!/usr/bin/env python3
"""Tests for run_checks.py. Standard library only; needs git on PATH.

    python3 -m unittest discover -s skills/kmp-build-check/scripts -p "test_*.py"

Gradle is never started: run_gradle is replaced by a fake, except in PassOnlyOnExitZero,
which runs a tiny fake gradlew shell script to prove the PASS/FAIL mapping end to end.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_checks as rc  # noqa: E402

EXAMPLE = Path(__file__).resolve().parents[1] / "assets" / "kmp-build-check.example.json"


def sample_config(consumers=None) -> dict:
    return {"version": 1, "checks": [
        {"name": "KMP common compile", "platform": "any", "task": ":shared:compileCommonMainKotlinMetadata"},
        {"name": "Android assemble", "platform": "android", "task": ":composeApp:assembleDebug"},
        {"name": "Unit tests", "platform": "android", "task": ":shared:testAndroidHostTest"},
        {"name": "iOS framework link", "platform": "ios", "task": ":shared:linkDebugFrameworkIosSimulatorArm64"},
        {"name": "iOS tests", "platform": "ios", "task": ":shared:iosSimulatorArm64Test"},
    ], "consumers": consumers or []}


def make_project(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "gradlew").write_text("#!/bin/sh\nexit 0\n")
    return path


def fake_gradle(outcomes=None, log_text="BUILD SUCCESSFUL", calls=None):
    """A run_gradle stand-in. outcomes maps task -> True/False/None (default True)."""
    def run(directory, task, args, log, timeout_s):
        if calls is not None:
            calls.append((task, list(args)))
        log.parent.mkdir(parents=True, exist_ok=True)
        ok = (outcomes or {}).get(task, True)
        log.write_text(log_text if ok is not True else "BUILD SUCCESSFUL")
        return ok, 1.0
    return run


class ConfigValidation(unittest.TestCase):
    def test_should_accept_the_shipped_example_when_validated(self):
        cfg, errors = rc.load_config(EXAMPLE)
        self.assertEqual(errors, [])
        self.assertTrue(any(c["platform"] == "ios" for c in cfg["checks"]),
                        "an example without an iOS check would teach an Android-only habit")

    def test_should_report_each_problem_when_entries_are_malformed(self):
        cfg = {"version": 2, "checks": [{"name": "x", "platform": "web", "task": "not a task"},
                                         {"platform": "any", "task": ":a:b", "colour": "red"}],
               "consumers": [{"name": "c", "path": "../c", "task": ":a:b", "args": "-Pflag"}]}
        errors = "\n".join(rc.validate_config(cfg))
        for fragment in ("'version' must be 1", "platform 'web'", "not a Gradle task path",
                         "'name' must be a non-empty string", "unknown key(s) ['colour']", "'args' must be a list"):
            self.assertIn(fragment, errors)

    def test_should_reject_an_empty_plan_when_checks_are_missing(self):
        self.assertIn("config: 'checks' must be a non-empty list", rc.validate_config({"version": 1, "checks": []}))

    def test_should_ignore_underscore_keys_when_validating(self):
        cfg = sample_config()
        cfg["_comment"] = "hi"
        cfg["checks"][0]["_why"] = "explained"
        self.assertEqual(rc.validate_config(cfg), [])

    def test_should_reject_duplicate_names_when_two_checks_share_one(self):
        cfg = sample_config()
        cfg["checks"][1]["name"] = cfg["checks"][0]["name"]
        self.assertTrue(any("duplicate name" in e for e in rc.validate_config(cfg)))

    def test_should_return_an_error_not_an_empty_plan_when_the_file_is_missing(self):
        cfg, errors = rc.load_config(Path("/nonexistent/kmp-build-check.json"))
        self.assertIsNone(cfg)
        self.assertIn("--detect gradle --write", errors[0])

    def test_should_name_the_position_when_json_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.json"
            p.write_text('{"version": 1,,}')
            _, errors = rc.load_config(p)
        self.assertIn("line 1", errors[0])


class InferKind(unittest.TestCase):
    def test_should_classify_common_kmp_tasks_when_inferring(self):
        cases = {
            ":shared:compileCommonMainKotlinMetadata": "common",
            "compileIosMainKotlinMetadata": "ios_compile",
            ":composeApp:assembleDevDebug": "android_build",
            ":shared:compileAndroidMain": "android_build",
            ":shared:testAndroidHostTest": "unit_test",
            ":shared:testDebugUnitTest": "unit_test",
            "jvmTest": "unit_test",
            ":shared:linkDebugFrameworkIosSimulatorArm64": "ios_link",
            ":shared:assembleSharedDebugXCFramework": "ios_link",
            ":shared:compileKotlinIosSimulatorArm64": "ios_compile",
            ":shared:iosSimulatorArm64Test": "ios_test",
            "allTests": "other",
        }
        for task, kind in cases.items():
            self.assertEqual(rc.infer_kind(task), kind, task)

    def test_should_derive_the_compile_task_when_given_a_framework_link(self):
        self.assertEqual(rc.link_to_compile(":shared:linkDebugFrameworkIosSimulatorArm64"),
                         ":shared:compileKotlinIosSimulatorArm64")
        self.assertEqual(rc.link_to_compile("linkReleaseFrameworkIosArm64"), "compileKotlinIosArm64")
        self.assertIsNone(rc.link_to_compile(":shared:assembleXCFramework"))


class NeverTwoStates(unittest.TestCase):
    """A check that cannot execute is NOT RUN with a reason - never PASS."""

    def run_with(self, ios_reason="", sdk=True, wrapper=True, cfg=None):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            project = make_project(ws / "app") if wrapper else (ws / "app")
            project.mkdir(exist_ok=True)
            checks = rc.build_checks(cfg or sample_config(), project)
            with mock.patch.object(rc, "ios_unavailable_reason", return_value=ios_reason), \
                 mock.patch.object(rc, "android_sdk", return_value=ws if sdk else None), \
                 mock.patch.object(rc, "uninitialised_submodules", return_value=[]), \
                 mock.patch.object(rc, "run_gradle", side_effect=fake_gradle()):
                return rc.execute(checks, logs=ws / "logs")

    def test_should_not_run_ios_checks_when_xcode_is_missing(self):
        res = self.run_with(ios_reason="Xcode not installed or not selected")
        ios = [r for r in res if r.platform == "ios"]
        self.assertTrue(ios)
        self.assertTrue(all(r.state == "NOT RUN" and "Xcode" in r.reason for r in ios))
        self.assertTrue(all(r.state == "PASS" for r in res if r.platform != "ios"))

    def test_should_not_run_android_checks_when_no_sdk_is_configured(self):
        res = self.run_with(sdk=False)
        android = [r for r in res if r.platform == "android"]
        self.assertTrue(all(r.state == "NOT RUN" and "Android SDK" in r.reason for r in android))

    def test_should_not_run_anything_when_the_wrapper_is_missing(self):
        res = self.run_with(wrapper=False)
        self.assertTrue(all(r.state == "NOT RUN" and "gradlew" in r.reason for r in res))

    def test_should_give_a_reason_when_any_check_is_not_run(self):
        for r in self.run_with(ios_reason="no iOS simulator runtime installed", sdk=False):
            if r.state == "NOT RUN":
                self.assertTrue(r.reason)

    def test_should_not_run_ios_checks_when_the_host_is_not_macos(self):
        with mock.patch.object(rc.sys, "platform", "linux"):
            reason = rc.ios_unavailable_reason(needs_simulator=True)
        self.assertIn("need macOS", reason)

    def test_should_not_run_when_submodules_are_uninitialised(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp) / "app")
            checks = rc.build_checks(sample_config(), project)
            with mock.patch.object(rc, "uninitialised_submodules", return_value=["gradle/catalog"]), \
                 mock.patch.object(rc, "ios_unavailable_reason", return_value=""), \
                 mock.patch.object(rc, "android_sdk", return_value=Path(tmp)), \
                 mock.patch.object(rc, "run_gradle", side_effect=fake_gradle()) as run:
                res = rc.execute(checks, logs=Path(tmp) / "l")
        self.assertFalse(run.called)
        self.assertTrue(all(r.state == "NOT RUN" and "git submodule update --init" in r.reason for r in res))

    def test_should_run_nothing_and_say_so_when_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp) / "app")
            with mock.patch.object(rc, "run_gradle") as run:
                res = rc.execute(rc.build_checks(sample_config(), project), dry_run=True, logs=Path(tmp) / "l")
        self.assertFalse(run.called)
        self.assertTrue(all(r.state == "NOT RUN" and r.reason.startswith("dry run: would run ./gradlew") for r in res))

    def test_should_filter_by_platform_when_only_is_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp) / "app")
            res = rc.execute(rc.build_checks(sample_config(), project), dry_run=True, only="ios", logs=Path(tmp))
        android = [r for r in res if r.platform == "android"]
        self.assertTrue(all("filtered out by --only ios" in r.reason for r in android))
        self.assertTrue(any(r.platform == "any" and r.reason.startswith("dry run") for r in res))

    def test_should_count_states_separately_when_rendering(self):
        res = [rc.Result("a", "any", ":a:b", "PASS", seconds=1),
               rc.Result("b", "ios", ":a:c", "NOT RUN", reason="Xcode not installed")]
        text = rc.render(res)
        self.assertIn("1 PASS, 0 FAIL, 1 NOT RUN", text)
        self.assertIn("NOT RUN", text.splitlines()[1])


@unittest.skipIf(os.name == "nt", "the fake wrapper is a POSIX shell script")
class PassOnlyOnExitZero(unittest.TestCase):
    """End to end through subprocess: the state comes from the exit code, nothing else."""

    def run_real(self, script: str):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "app"
            project.mkdir()
            (project / "gradlew").write_text("#!/bin/sh\n" + script)
            checks = [rc.Check("compile", "any", ":shared:compileCommonMainKotlinMetadata", "common", project)]
            with mock.patch.object(rc, "uninitialised_submodules", return_value=[]):
                return rc.execute(checks, logs=Path(tmp) / "logs")[0]

    def test_should_pass_when_gradle_exits_zero(self):
        self.assertEqual(self.run_real("exit 0\n").state, "PASS")

    def test_should_fail_with_the_compiler_error_when_gradle_exits_non_zero(self):
        r = self.run_real("echo \"e: file:///w/My%20App/shared/src/commonMain/kotlin/Notes.kt:7:9 Unresolved reference 'id'.\"\n"
                          "echo 'BUILD SUCCESSFUL'\nexit 1\n")
        self.assertEqual(r.state, "FAIL", "output text must never override a non-zero exit")
        self.assertEqual(r.reason, "Notes.kt:7:9 Unresolved reference 'id'.")

    def test_should_not_pass_when_the_output_claims_success_but_exit_is_non_zero(self):
        self.assertEqual(self.run_real("echo 'BUILD SUCCESSFUL'\nexit 3\n").state, "FAIL")


class Environment(unittest.TestCase):
    """Environmental failures are NOT RUN, never FAIL - they test no code."""

    def test_should_find_the_sdk_when_local_properties_sets_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, sdk = Path(tmp) / "r", Path(tmp) / "sdk"
            repo.mkdir(); sdk.mkdir()
            (repo / "local.properties").write_text(f"sdk.dir={sdk}\n")
            with mock.patch.dict(os.environ, {"ANDROID_HOME": "", "ANDROID_SDK_ROOT": ""}):
                self.assertEqual(rc.android_sdk(repo), sdk)

    def test_should_prefer_the_env_var_when_both_are_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, a, b = Path(tmp) / "r", Path(tmp) / "a", Path(tmp) / "b"
            for d in (repo, a, b):
                d.mkdir()
            (repo / "local.properties").write_text(f"sdk.dir={b}\n")
            with mock.patch.dict(os.environ, {"ANDROID_HOME": str(a)}):
                self.assertEqual(rc.android_sdk(repo), a)

    def test_should_return_none_when_no_sdk_exists_anywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"ANDROID_HOME": "", "ANDROID_SDK_ROOT": ""}), \
                 mock.patch.object(rc, "DEFAULT_SDKS", [Path(tmp) / "nope"]):
                self.assertIsNone(rc.android_sdk(Path(tmp)))

    def test_should_not_run_when_gradle_reports_a_missing_sdk(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp) / "app")
            checks = [rc.Check("iOS link", "ios", ":shared:linkDebugFrameworkIosSimulatorArm64", "ios_link", project)]
            log = "* What went wrong:\nSDK location not found. Define a valid SDK location with an ANDROID_HOME"
            with mock.patch.object(rc, "ios_unavailable_reason", return_value=""), \
                 mock.patch.object(rc, "uninitialised_submodules", return_value=[]), \
                 mock.patch.object(rc, "run_gradle", side_effect=fake_gradle({checks[0].task: False}, log)):
                r = rc.execute(checks, logs=Path(tmp) / "l")[0]
        self.assertEqual(r.state, "NOT RUN")
        self.assertIn("Android SDK not found by Gradle", r.reason)


class Consumers(unittest.TestCase):
    """A consumer already broken without the local library must not be blamed on this change."""

    def run_consumer(self, with_args_ok, baseline_ok, make_consumer=True):
        calls = []

        def fake(directory, task, args, log, timeout_s):
            calls.append(list(args))
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("* What went wrong:\nCompilation finished with errors\n")
            return (with_args_ok if args else baseline_ok), 1.0
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            lib = make_project(ws / "notes-core")
            if make_consumer:
                make_project(ws / "notes-app")
            cfg = {"version": 1, "checks": [{"name": "compile", "platform": "any",
                                             "task": ":core:compileCommonMainKotlinMetadata"}],
                   "consumers": [{"name": "notes-app", "path": "../notes-app", "args": ["-Plocal.notes-core=true"],
                                  "task": ":shared:compileCommonMainKotlinMetadata"}]}
            with mock.patch.object(rc, "ios_unavailable_reason", return_value=""), \
                 mock.patch.object(rc, "android_sdk", return_value=ws), \
                 mock.patch.object(rc, "uninitialised_submodules", return_value=[]), \
                 mock.patch.object(rc, "run_gradle", side_effect=fake):
                res = rc.execute(rc.build_checks(cfg, lib), logs=ws / "l")
        return [r for r in res if r.consumer][0], calls

    def test_should_pass_the_substitution_args_when_running_a_consumer(self):
        r, calls = self.run_consumer(with_args_ok=True, baseline_ok=True)
        self.assertEqual(r.state, "PASS")
        self.assertIn(["-Plocal.notes-core=true"], calls)
        self.assertEqual(calls.count([]), 1, "a passing consumer must not pay for a baseline build")

    def test_should_not_run_when_the_consumer_was_already_broken(self):
        r, _ = self.run_consumer(with_args_ok=False, baseline_ok=False)
        self.assertEqual(r.state, "NOT RUN")
        self.assertIn("pre-existing", r.reason)

    def test_should_fail_when_only_the_local_library_breaks_the_consumer(self):
        r, _ = self.run_consumer(with_args_ok=False, baseline_ok=True)
        self.assertEqual(r.state, "FAIL")

    def test_should_not_run_when_the_consumer_is_not_checked_out(self):
        r, _ = self.run_consumer(with_args_ok=True, baseline_ok=True, make_consumer=False)
        self.assertEqual(r.state, "NOT RUN")
        self.assertIn("directory not found", r.reason)


def git(cwd: Path, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)


def init_repo(repo: Path):
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "commit.gpgsign", "false")


class CleanWorktree(unittest.TestCase):
    def test_should_keep_the_machine_sdk_config_when_building_a_clean_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            init_repo(repo)
            (repo / ".gitignore").write_text("local.properties\n")
            (repo / "app").mkdir()
            (repo / "app" / "A.kt").write_text("class A")
            git(repo, "add", "-A"); git(repo, "commit", "-qm", "base")
            sdk = Path(tmp) / "sdk"; sdk.mkdir()
            (repo / "app" / "local.properties").write_text(f"sdk.dir={sdk}\n")
            (repo / "app" / "Untracked.kt").write_text("class U")
            project = rc.clean_worktree(repo / "app", Path(tmp) / "clean")
            self.assertTrue((project / "A.kt").is_file())
            self.assertFalse((project / "Untracked.kt").exists(), "untracked files must not reach the clean build")
            with mock.patch.dict(os.environ, {"ANDROID_HOME": "", "ANDROID_SDK_ROOT": ""}):
                self.assertEqual(rc.android_sdk(project), sdk)
            git(repo, "worktree", "remove", "--force", str(Path(tmp) / "clean" / "worktree"))


class Classify(unittest.TestCase):
    def test_should_classify_paths_by_what_they_reach(self):
        cases = {
            "shared/build.gradle.kts": "build", "gradle/libs.versions.toml": "build", "settings.gradle.kts": "build",
            "gradle.properties": "build", "build-logic/convention/src/main/kotlin/A.kt": "build",
            "shared/src/nativeInterop/cinterop/sqlite.def": "build",
            "README.md": "neutral", ".github/workflows/ci.yml": "neutral", "docs/x.md": "neutral",
            "iosApp/iosApp/ContentView.swift": "ios-native", "iosApp/iosApp.xcodeproj/project.pbxproj": "ios-native",
            "shared/src/androidMain/kotlin/A.kt": "android", "composeApp/src/main/AndroidManifest.xml": "android",
            "shared/src/androidHostTest/kotlin/ATest.kt": "android",
            "shared/src/iosMain/kotlin/A.kt": "ios", "shared/src/appleMain/kotlin/A.kt": "ios",
            "shared/src/nativeInterop/cinterop/headers/x.h": "ios",
            "shared/src/commonMain/kotlin/A.kt": "shared", "shared/src/commonTest/kotlin/ATest.kt": "shared",
            "shared/src/commonMain/composeResources/drawable/logo.png": "shared",
            "shared/schemas/com.example.app.NotesDb/3.json": "shared",
        }
        for path, want in cases.items():
            self.assertEqual(rc.classify(path), want, path)


class Scoping(unittest.TestCase):
    """--base: run only what the diff can affect; every skip is NOT RUN with a reason."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.ws = Path(self._t.name)
        self.repo = self.ws / "notes"
        init_repo(self.repo)
        self.write("gradlew", "#!/bin/sh\nexit 0\n")
        self.write("settings.gradle.kts", 'include(":composeApp")\ninclude(":shared")\ninclude(":feature:notes")\n')
        for f in ("shared/src/commonMain/kotlin/A.kt", "shared/src/commonTest/kotlin/ATest.kt",
                  "shared/src/iosTest/kotlin/ITest.kt", "composeApp/src/androidMain/kotlin/App.kt",
                  "feature/notes/src/commonMain/kotlin/F.kt", "feature/notes/src/commonTest/kotlin/FTest.kt"):
            self.write(f, "x")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-qm", "base")
        origin = self.ws / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
        git(self.repo, "remote", "add", "origin", str(origin))
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "checkout", "-qb", "feature/x")

    def tearDown(self):
        self._t.cleanup()

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def run_scoped(self, *changed, log_text="BUILD SUCCESSFUL", cfg=None, commit=True):
        for f in changed:
            self.write(f, "changed")
        if commit:
            git(self.repo, "add", "-A"); git(self.repo, "commit", "-qm", "work")
        calls = []
        changes, _ = rc.changes_since(self.repo, branch="main")
        outcomes = {} if log_text == "BUILD SUCCESSFUL" else {t: False for t in self._all_tasks()}
        with mock.patch.object(rc, "ios_unavailable_reason", return_value=""), \
             mock.patch.object(rc, "android_sdk", return_value=self.ws), \
             mock.patch.object(rc, "uninitialised_submodules", return_value=[]), \
             mock.patch.object(rc, "run_gradle", side_effect=fake_gradle(outcomes, log_text, calls)):
            res = rc.execute(rc.build_checks(cfg or sample_config(), self.repo), logs=self.ws / "l", changes=changes)
        return {r.name: r for r in res}, [t for t, _ in calls]

    def _all_tasks(self):
        names = [":feature:notes:testAndroidHostTest", ":shared:testAndroidHostTest", ":composeApp:assembleDebug"]
        return names + [c["task"] for c in sample_config()["checks"]]

    def test_should_skip_ios_checks_when_only_android_code_changed(self):
        res, ran = self.run_scoped("shared/src/androidMain/kotlin/B.kt")
        self.assertEqual(res["iOS framework link"].state, "NOT RUN")
        self.assertIn("only Android code changed", res["iOS framework link"].reason)
        self.assertEqual(res["iOS tests"].state, "NOT RUN")
        self.assertIn(":composeApp:assembleDebug", ran)
        self.assertFalse(any("Ios" in t for t in ran))

    def test_should_skip_android_checks_and_keep_the_link_when_only_ios_kotlin_changed(self):
        res, ran = self.run_scoped("shared/src/iosMain/kotlin/B.kt")
        self.assertEqual(res["Android assemble"].state, "NOT RUN")
        self.assertIn("only iOS Kotlin changed", res["Android assemble"].reason)
        self.assertIn(":shared:linkDebugFrameworkIosSimulatorArm64", ran, "an iosMain change needs the real link")
        self.assertIn(":shared:iosSimulatorArm64Test", ran)

    def test_should_compile_for_ios_instead_of_linking_when_only_common_code_changed(self):
        _, ran = self.run_scoped("shared/src/commonMain/kotlin/A.kt")
        self.assertIn(":shared:compileKotlinIosSimulatorArm64", ran)
        self.assertNotIn(":shared:linkDebugFrameworkIosSimulatorArm64", ran)
        self.assertIn(":composeApp:assembleDebug", ran)

    def test_should_keep_the_link_and_every_test_when_a_build_file_changed(self):
        _, ran = self.run_scoped("shared/build.gradle.kts")
        self.assertIn(":shared:linkDebugFrameworkIosSimulatorArm64", ran)
        self.assertIn(":shared:testAndroidHostTest", ran)

    def test_should_run_tests_only_for_the_changed_module_when_tests_are_scoped(self):
        res, ran = self.run_scoped("feature/notes/src/commonMain/kotlin/F.kt")
        self.assertIn(":feature:notes:testAndroidHostTest", ran)
        self.assertNotIn(":shared:testAndroidHostTest", ran)
        self.assertIn("Unit tests - :feature:notes", res)

    def test_should_scope_unqualified_test_tasks_to_the_changed_module(self):
        cfg = sample_config()
        cfg["checks"][2]["task"] = "testAndroidHostTest"
        _, ran = self.run_scoped("feature/notes/src/commonMain/kotlin/F.kt", cfg=cfg)
        self.assertIn(":feature:notes:testAndroidHostTest", ran)

    def test_should_not_run_tests_when_the_changed_module_has_none(self):
        res, _ = self.run_scoped("composeApp/src/androidMain/kotlin/App.kt")
        self.assertEqual(res["Unit tests"].state, "NOT RUN")
        self.assertIn("no changed module has JVM/Android tests", res["Unit tests"].reason)

    def test_should_run_nothing_when_only_docs_changed(self):
        res, ran = self.run_scoped("README.md", "docs/x.md")
        self.assertEqual(ran, [])
        self.assertTrue(all(r.state == "NOT RUN" and "no build input changed" in r.reason for r in res.values()))

    def test_should_say_so_when_only_swift_changed(self):
        res, ran = self.run_scoped("iosApp/iosApp/ContentView.swift")
        self.assertEqual(ran, [])
        self.assertIn("only Swift / Xcode project files changed", next(iter(res.values())).reason)

    def test_should_count_uncommitted_and_untracked_files_when_scoping(self):
        res, ran = self.run_scoped("shared/src/iosMain/kotlin/New.kt", commit=False)
        self.assertEqual(res["Android assemble"].state, "NOT RUN")
        self.assertIn(":shared:linkDebugFrameworkIosSimulatorArm64", ran)

    def test_should_not_run_when_a_scoped_module_lacks_the_task(self):
        res, _ = self.run_scoped("feature/notes/src/commonMain/kotlin/F.kt",
                                 log_text="* What went wrong:\nTask 'testAndroidHostTest' not found in project ':feature:notes'.")
        r = res["Unit tests - :feature:notes"]
        self.assertEqual(r.state, "NOT RUN")
        self.assertIn("does not exist in this build", r.reason)

    def test_should_fail_when_a_configured_task_is_missing(self):
        res, _ = self.run_scoped("shared/build.gradle.kts",
                                 log_text="* What went wrong:\nTask 'assembleDebug' not found in project ':composeApp'.")
        self.assertEqual(res["Android assemble"].state, "FAIL")
        self.assertIn("configured task not found", res["Android assemble"].reason)

    def test_should_run_unscoped_when_there_is_no_merge_base(self):
        git(self.repo, "checkout", "-q", "--orphan", "unrelated")
        git(self.repo, "rm", "-rqf", ".")
        self.write("other.txt", "x"); git(self.repo, "add", "-A"); git(self.repo, "commit", "-qm", "unrelated")
        git(self.repo, "push", "-qf", "origin", "unrelated:main")
        git(self.repo, "checkout", "-q", "feature/x")
        changes, notes = rc.changes_since(self.repo, branch="main")
        self.assertIsNone(changes)
        self.assertIn("no merge-base", notes[-1])

    def test_should_not_narrow_tests_when_modules_cannot_be_read(self):
        self.write("settings.gradle.kts", 'rootDir.listFiles().forEach { include(":${it.name}") }\n')
        _, ran = self.run_scoped("feature/notes/src/commonMain/kotlin/F.kt")
        self.assertIn(":shared:testAndroidHostTest", ran, "unknown module layout -> the configured tests run")

    def test_should_read_groovy_style_includes_when_scoping(self):
        self.write("settings.gradle", "include ':shared', ':feature:notes'   // Groovy\n")
        (self.repo / "settings.gradle.kts").unlink()
        mods, known = rc.gradle_modules(self.repo)
        self.assertTrue(known)
        self.assertEqual(mods["feature/notes"], ":feature:notes")

    def test_should_not_narrow_tests_when_a_change_is_outside_every_module(self):
        _, ran = self.run_scoped("tools/src/commonMain/kotlin/Gen.kt")
        self.assertIn(":shared:testAndroidHostTest", ran)

    def test_should_scope_against_the_remote_branch_not_a_stale_local_one(self):
        # local main gains an unpushed iOS change that the branch merges; the branch's own work is Android-only
        git(self.repo, "checkout", "-q", "main"); self.write("shared/src/iosMain/kotlin/X.kt", "ios")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-qm", "unpushed local main")
        git(self.repo, "checkout", "-q", "feature/x"); git(self.repo, "merge", "-q", "--no-edit", "main")
        self.write("shared/src/androidMain/kotlin/A.kt", "android")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-qm", "branch work")
        changes, _ = rc.changes_since(self.repo, branch="main")
        self.assertIn("shared/src/iosMain/kotlin/X.kt", changes.kinds,
                      "against origin/main the merged-in iOS change belongs to this branch")
        self.assertFalse(changes.android_only)

    def test_should_use_an_exact_ref_without_fetching_when_base_ref_is_given(self):
        self.write("shared/src/androidMain/kotlin/B.kt", "x")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-qm", "work")
        with mock.patch.object(rc.subprocess, "run", wraps=subprocess.run) as run:
            changes, _ = rc.changes_since(self.repo, ref="HEAD~1")
        self.assertFalse(any("fetch" in call.args[0] for call in run.call_args_list))
        self.assertTrue(changes.android_only)

    def test_should_change_nothing_when_no_base_is_given(self):
        checks = rc.build_checks(sample_config(), self.repo)
        self.assertEqual(rc.scope(checks, None), checks)


class Timeouts(unittest.TestCase):
    """A hung Gradle proves nothing: NOT RUN with the reason, never PASS or FAIL."""

    def test_should_report_none_when_gradle_times_out(self):
        def hang(*a, **kw):
            raise subprocess.TimeoutExpired(a[0], kw.get("timeout"))
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp))
            with mock.patch.object(rc.subprocess, "run", hang), mock.patch.object(rc, "android_sdk", return_value=None):
                log = Path(tmp) / "g.log"
                ok, _ = rc.run_gradle(project, ":x:build", [], log, 60)
            self.assertIsNone(ok)
            self.assertIn("timed out", rc.incomplete_reason(log))

    def test_should_not_run_when_a_check_times_out(self):
        def fake(directory, task, args, log, timeout_s):
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(f"{rc.MARK} timed out after 45 min\n")
            return None, 2700.0
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp) / "app")
            with mock.patch.object(rc, "ios_unavailable_reason", return_value=""), \
                 mock.patch.object(rc, "android_sdk", return_value=Path(tmp)), \
                 mock.patch.object(rc, "uninitialised_submodules", return_value=[]), \
                 mock.patch.object(rc, "run_gradle", side_effect=fake):
                res = rc.execute(rc.build_checks(sample_config(), project), logs=Path(tmp) / "l")
        self.assertTrue(all(r.state == "NOT RUN" and "timed out" in r.reason for r in res))


class UntrackedSources(unittest.TestCase):
    def test_should_report_only_untracked_source_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "r"
            init_repo(repo)
            (repo / "Tracked.kt").write_text("class Tracked")
            git(repo, "add", "Tracked.kt"); git(repo, "commit", "-qm", "init")
            (repo / "SaveNoteUseCase.kt").write_text("class SaveNoteUseCase")
            (repo / "View.swift").write_text("struct V {}")
            (repo / "notes.md").write_text("# notes")
            self.assertEqual(set(rc.untracked_sources(repo)), {"SaveNoteUseCase.kt", "View.swift"})


class FailureReason(unittest.TestCase):
    def reason(self, text: str) -> str:
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "g.log"
            log.write_text(text)
            return rc.failure_tail(log)

    def test_should_use_the_first_compiler_error_when_there_is_one(self):
        log = ("> Task :shared:compileKotlinIosSimulatorArm64 FAILED\n"
               "e: file:///w/shared/src/iosMain/kotlin/Platform.ios.kt:5:23 Initializer type mismatch.\n"
               "e: file:///w/shared/src/iosMain/kotlin/Other.kt:9:1 Unresolved reference 'x'.\n"
               "* What went wrong:\nExecution failed for task ':shared:compileKotlinIosSimulatorArm64'.\n")
        self.assertEqual(self.reason(log), "Platform.ios.kt:5:23 Initializer type mismatch.")

    def test_should_handle_paths_with_spaces_when_parsing_compiler_errors(self):
        log = "e: file:///home/dev/My Projects/notes/shared/src/commonMain/kotlin/Note.kt:3:1 Expecting member.\n"
        self.assertEqual(self.reason(log), "Note.kt:3:1 Expecting member.")

    def test_should_name_the_failed_test_when_a_test_fails(self):
        log = ("> Task :shared:testAndroidHostTest\n"
               "NotesViewModelTest > should_showError_when_saveFails FAILED\n"
               "    java.lang.AssertionError at NotesViewModelTest.kt:42\n")
        self.assertEqual(self.reason(log), "NotesViewModelTest > should_showError_when_saveFails FAILED")

    def test_should_quote_what_went_wrong_when_there_is_no_compiler_error(self):
        log = "* What went wrong:\nTask 'nope' not found in project ':shared'.\n* Try:\n"
        self.assertIn("Task 'nope' not found", self.reason(log))


TASKS_OUTPUT = """
------------------------------------------------------------
Tasks runnable from root project 'notes'
------------------------------------------------------------

Build tasks
-----------
assemble - Assembles the outputs of this project.
composeApp:assembleDebug - Assembles main output for all 'debug' variants.
composeApp:assembleDevDebug - Assembles main output for the devDebug variant.
composeApp:assembleProdDebug - Assembles main output for the prodDebug variant.
composeApp:assembleDevDebugAndroidTest - Assembles the android (on device) tests.
composeApp:installDevDebug - Installs the DevDebug build.
shared:compileCommonMainKotlinMetadata
shared:compileAndroidMain
shared:testAndroidHostTest - Runs host tests.
shared:linkDebugFrameworkIosSimulatorArm64 - Links the debug framework.
shared:compileKotlinIosSimulatorArm64
shared:iosSimulatorArm64Test - Executes Kotlin/Native unit tests for target iosSimulatorArm64.
feature:notes:compileCommonMainKotlinMetadata

Rules
-----
Pattern: clean<TaskName>: Cleans the output files of a task.
"""


class Detect(unittest.TestCase):
    def test_should_parse_task_paths_when_reading_tasks_all_output(self):
        tasks = rc.parse_task_list(TASKS_OUTPUT)
        self.assertIn(":shared:iosSimulatorArm64Test", tasks)
        self.assertIn(":feature:notes:compileCommonMainKotlinMetadata", tasks)
        self.assertIn(":assemble", tasks)
        self.assertNotIn(":Rules", tasks)

    def test_should_propose_one_check_per_platform_when_detecting_from_tasks(self):
        cfg, warnings = rc.detect_from_tasks(rc.parse_task_list(TASKS_OUTPUT))
        self.assertEqual(rc.validate_config(cfg), [])
        tasks = [c["task"] for c in cfg["checks"]]
        self.assertEqual(tasks, ["compileCommonMainKotlinMetadata", ":composeApp:assembleDevDebug",
                                 "testAndroidHostTest", "linkDebugFrameworkIosSimulatorArm64",
                                 "iosSimulatorArm64Test"])
        self.assertTrue(any("product flavours" in w for w in warnings))

    def test_should_warn_when_no_ios_target_exists(self):
        cfg, warnings = rc.detect_from_tasks({":shared:compileCommonMainKotlinMetadata", ":shared:jvmTest"})
        self.assertTrue(any("nothing will check iosMain" in w for w in warnings))
        self.assertEqual([c["task"] for c in cfg["checks"]], ["compileCommonMainKotlinMetadata", "jvmTest"])

    def make_static_project(self, root: Path, host_tests=True):
        (root / "settings.gradle.kts").write_text('include(":composeApp")\ninclude(":shared")\n')
        # The root declares every plugin with `apply false`; it must not be read as an app module.
        (root / "build.gradle.kts").write_text(
            "plugins {\n  alias(libs.plugins.androidApplication) apply false\n"
            "  alias(libs.plugins.kotlinMultiplatform) apply false\n"
            "  alias(libs.plugins.androidKotlinMultiplatformLibrary) apply false\n}\n")
        (root / "composeApp").mkdir()
        (root / "composeApp" / "build.gradle.kts").write_text(
            "plugins {\n  alias(libs.plugins.kotlinMultiplatform)\n  alias(libs.plugins.androidApplication)\n}\n"
            "kotlin { androidTarget { } }\nandroid { productFlavors { create(\"dev\") } }\n")
        (root / "shared").mkdir()
        (root / "shared" / "build.gradle.kts").write_text(
            "plugins {\n  alias(libs.plugins.kotlinMultiplatform)\n  alias(libs.plugins.androidKotlinMultiplatformLibrary)\n}\n"
            "kotlin {\n  android {\n" + ("    withHostTest { }\n" if host_tests else "") + "  }\n"
            "  listOf(iosArm64(), iosSimulatorArm64()).forEach { it.binaries.framework { baseName = \"Shared\" } }\n"
            "  jvm()\n}\n")

    def test_should_propose_checks_from_build_files_when_detecting_statically(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_static_project(Path(tmp))
            cfg, warnings = rc.detect_static(Path(tmp))
        self.assertEqual(rc.validate_config(cfg), [])
        tasks = [c["task"] for c in cfg["checks"]]
        self.assertEqual(tasks, ["compileCommonMainKotlinMetadata", ":composeApp:assembleDebug", "testAndroidHostTest",
                                 "jvmTest", "linkDebugFrameworkIosSimulatorArm64", "iosSimulatorArm64Test"])
        self.assertTrue(any("productFlavors" in w for w in warnings))
        self.assertTrue(any("static detection guesses" in w for w in warnings))

    def test_should_warn_when_the_android_kmp_library_has_no_host_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_static_project(Path(tmp), host_tests=False)
            cfg, warnings = rc.detect_static(Path(tmp))
        self.assertNotIn("testAndroidHostTest", [c["task"] for c in cfg["checks"]])
        self.assertTrue(any("without withHostTest" in w for w in warnings))


class Cli(unittest.TestCase):
    def test_should_exit_zero_when_help_is_requested(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as e:
            rc.main(["--help"])
        self.assertEqual(e.exception.code, 0)
        self.assertIn("PASS", out.getvalue())

    def test_should_exit_two_when_the_config_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / rc.CONFIG_NAME).write_text('{"version": 1, "checks": []}')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(rc.main(["--project", tmp]), 2)

    def test_should_write_json_results_when_dry_run_with_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp) / "app")
            (project / rc.CONFIG_NAME).write_text(json.dumps(sample_config()))
            out = Path(tmp) / "out.json"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = rc.main(["--project", str(project), "--dry-run", "--json", str(out)])
            doc = json.loads(out.read_text())
        self.assertEqual(code, 0)
        self.assertEqual(doc["summary"], {"pass": 0, "fail": 0, "not_run": 5})
        self.assertEqual({r["state"] for r in doc["results"]}, {"NOT RUN"})

    def test_should_print_a_config_when_detecting_without_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            Detect().make_static_project(Path(tmp))
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
                code = rc.main(["--project", tmp, "--detect", "static"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["version"], 1)

    def test_should_refuse_to_overwrite_when_detect_write_finds_a_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            Detect().make_static_project(Path(tmp))
            (Path(tmp) / rc.CONFIG_NAME).write_text("{}")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(rc.main(["--project", tmp, "--detect", "static", "--write"]), 2)
            self.assertEqual((Path(tmp) / rc.CONFIG_NAME).read_text(), "{}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
