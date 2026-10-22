---
name: kmp-build-check
description: Use when you need to know whether a Kotlin Multiplatform change still builds and passes tests on both Android and iOS - "did I break iOS?", before pushing or opening a PR, after editing commonMain, iosMain, expect/actual, Gradle files or the version catalog, when a library change may break the apps that consume it, or when CI fails only on the iOS framework link or the iOS simulator tests.
license: Apache-2.0
compatibility: Kotlin Multiplatform Gradle project with a Gradle wrapper. Python 3.9+ (standard library only) and git. iOS checks need macOS with Xcode and an iOS simulator runtime. Runs Gradle, which may download dependencies; --base also runs git fetch (turn off with --no-fetch).
metadata:
  category: testing
  platforms: android, ios
---

# KMP build check

A green Android build proves nothing about iOS. `iosMain`, `actual` declarations, cinterop and the
framework link are compiled only by Kotlin/Native tasks, so an Android-only build passes while the
iOS half is broken. This skill runs each check as its own Gradle invocation and reports every one as
**PASS** (Gradle exited 0), **FAIL** (Gradle exited non-zero) or **NOT RUN** (with the reason).

## When to use

- Before pushing or opening a pull request on a KMP repository.
- After a change to `commonMain`, `iosMain`, `expect`/`actual`, a `build.gradle.kts`, `settings.gradle.kts`
  or `gradle/libs.versions.toml`.
- In a library repository: to rebuild the apps that consume the library against your local checkout.
- When the user asks "does it still build on iOS?" or "did I break anything?".

## When not to use

- Writing or fixing tests: use `kmp-testing-patterns`.
- Raising Kover coverage: use `kmp-test-coverage-backfill`.
- UI-test locators and accessibility IDs: use `mobile-accessibility-test-ids`.
- Running the app on a device or simulator to see a change: this skill only builds and tests.
- Diagnosing *why* a build fails (linker, KSP, Xcode errors): use `kmp-build-failure-triage`. This skill
  reports which check failed and its first error.
- Setting up CI: use `kmp-ci-github-actions`. Reviewing the code itself: use `kmp-code-review`.

## Step 0 - Read the project first

1. **Find the Gradle root**: the directory with `gradlew` and `settings.gradle(.kts)`. A monorepo with
   several Gradle roots gets one run per root.
2. **Look for `kmp-build-check.json`** at that root. If it exists, it is the source of truth. Never
   replace its tasks with task names from memory.
3. **No config yet?** Propose one (see Workflow step 1). Show it to the user before writing it into
   their repository.
4. **Read the CI configuration** (`.github/workflows/`, `.gitlab-ci.yml`, and so on). Prefer the tasks CI
   already runs, so that a local PASS predicts a CI pass.
5. **Note which Android plugin each module uses.** It decides the unit-test task name:

   | Module setup | Android/JVM unit-test task |
   |---|---|
   | `com.android.library` + `androidTarget()` | `testDebugUnitTest` |
   | `com.android.kotlin.multiplatform.library` | `testAndroidHostTest`, and only if `withHostTest {}` is configured. Host tests are off by default. |
   | `jvm()` target | `jvmTest` (`<name>Test` for `jvm("<name>")`) |

6. **Check the host.** On macOS run `xcrun simctl list runtimes`. Without Xcode the iOS checks are
   NOT RUN. Say so up front, so nobody reads a partial run as a full one.

## Workflow

`<skill-dir>` below is the directory that contains this `SKILL.md`. Run the commands from the Gradle root.

1. **Get a config.**

   ```bash
   python3 <skill-dir>/scripts/run_checks.py --detect gradle          # reads ./gradlew tasks --all
   python3 <skill-dir>/scripts/run_checks.py --detect static          # reads build files only
   ```

   Both modes print a proposal and never overwrite a file. Add `--write` to save it as
   `kmp-build-check.json`. The two modes trade accuracy for speed:

   | Mode | Strength | Weakness |
   |---|---|---|
   | `gradle` | Real task names, including those made by convention plugins, flavours and the AGP KMP plugin | Configures the whole build (seconds to minutes). Needs the Android SDK and dependency resolution to succeed. |
   | `static` | Instant and offline | Guesses. Blind to convention plugins in `build-logic/`, to flavour names and to CocoaPods task names. |

   Review the proposal: pick one flavour's `assemble<Flavour>Debug`, and delete checks CI does not need.
   Copy `assets/kmp-build-check.example.json` when you want to write the file by hand. The schema and
   the consumer setup are in [references/configuration.md](references/configuration.md).
   *Done when* `run_checks.py --validate` prints `valid`.

2. **Dry-run the plan.**

   ```bash
   python3 <skill-dir>/scripts/run_checks.py --dry-run
   ```

   *Done when* every check reads `dry run: would run ./gradlew ...`, or shows a NOT RUN reason that you
   understand (no wrapper, consumer not checked out).

3. **Run.** Use a full run before a release or a tag. For day-to-day work, scope the run to the diff:

   ```bash
   python3 <skill-dir>/scripts/run_checks.py                    # every check
   python3 <skill-dir>/scripts/run_checks.py --base main        # only what the diff vs origin/main can affect
   python3 <skill-dir>/scripts/run_checks.py --json build/kmp-build-check/result.json
   ```

   Checks run one after another. Never start two Gradle builds in the same project at once: they
   fight over the same locks and both slow down or time out.
   *Done when* the summary line `N PASS, N FAIL, N NOT RUN` is printed.

4. **Read every FAIL.** The table shows the first compiler error (`File.kt:line:col message`), the
   first failed test, or Gradle's "What went wrong" text. The full log path is in the JSON `log` field.
   Quote that line. Do not paste the whole log.
   *Done when* each FAIL has a one-line cause.

5. **Fix only when asked.** This skill reports. If the user asks for a fix, make it, run the failing
   task directly (`./gradlew <task>`) until it passes, then run the tool again so the final report
   comes from one complete run.

6. **Report.** Give the table, the summary line, and for each NOT RUN its reason and who can close it.
   Example: "iOS checks NOT RUN: this machine has no Xcode. CI's macOS job will run them."

### What `--base` skips

`--base <branch>` fetches `<remote>/<branch>` and diffs against the merge-base with it. It never uses
the local branch, because a stale or unpushed local `main` changes the diff. Use `--base-ref <ref>`
to diff against an exact ref with no fetch. The diff counts committed, uncommitted and untracked files.

| What changed | Effect |
|---|---|
| Only Android source sets (`androidMain`, `src/main`, `androidHostTest` ...) | iOS checks: NOT RUN |
| Only Kotlin Apple source sets (`iosMain`, `appleMain`, `nativeMain` ...) | Android build and unit tests: NOT RUN |
| Only platform source sets | `compileCommonMainKotlinMetadata`: NOT RUN |
| No build file, dependency, cinterop `.def` or Apple source set | the framework link becomes `compileKotlin<Target>` (faster; it does not link) |
| No build file changed, module layout readable | test tasks run only in the changed modules that have test sources |
| Only docs, CI, scripts, or only Swift / Xcode files | every check: NOT RUN, with that reason |

When the merge-base, the remote branch or the module layout cannot be found or read, the tool runs the
unscoped plan and prints a warning. It never fails open into skipping checks.

## Quick reference

| Flag | Effect |
|---|---|
| `--dry-run` | Print the plan; run nothing |
| `--only android` / `--only ios` | One platform's checks, plus the `any` ones |
| `--base BRANCH` / `--base-ref REF` | Scope the run to the diff (see above) |
| `--json PATH` | Write results as JSON; `-` sends JSON to stdout and the table to stderr |
| `--clean` | Build a temporary git worktree of `HEAD`: committed code only |
| `--init-submodules` | Run `git submodule update --init --recursive` when a submodule is missing |
| `--no-consumers` | Skip the consumer checks |
| `--timeout-minutes N` | Per Gradle run (default 45). A timeout is NOT RUN, never PASS. |
| `--validate` | Check `kmp-build-check.json` and exit |
| `--detect gradle\|static` (+ `--write`, `--force`) | Propose a config |

| Check kind | Typical task | Catches |
|---|---|---|
| common | `compileCommonMainKotlinMetadata` | `commonMain` compile errors, `expect` without `actual` |
| android_build | `:composeApp:assembleDebug`, `compileAndroidMain` | `androidMain`, Android resources, manifest merge |
| unit_test | `testDebugUnitTest`, `testAndroidHostTest`, `jvmTest` | `commonTest` on the JVM, plus Android or JVM test sets |
| ios_link | `linkDebugFrameworkIosSimulatorArm64` | `iosMain`, `actual`s, cinterop, linker flags, exported API |
| ios_test | `iosSimulatorArm64Test` | `commonTest` and `iosTest` on Kotlin/Native |

Exit status: `0` no FAIL, `1` at least one FAIL, `2` bad usage or config. Exit 0 with NOT RUN checks
is not "all green".

## Verify

```bash
python3 <skill-dir>/scripts/run_checks.py --validate
python3 <skill-dir>/scripts/run_checks.py --json -
python3 -m unittest discover -s <skill-dir>/scripts -p "test_*.py"     # the tool's own tests
```

Reporting rules:

- A check is **PASS** only when its Gradle process exited 0. The tool never reads log text to decide
  a pass.
- Every **NOT RUN** carries its reason. Some reasons are about the environment: no Xcode, not macOS,
  no simulator runtime, no Android SDK, an uninitialised submodule, a timeout, or a consumer that is
  not checked out. Others are about scope: the diff does not reach the check, or `--only` filtered it.
- Quote the summary line verbatim. Never say "everything passes" while any check is NOT RUN. Name the
  checks that did not run.
- If CI runs the iOS half on macOS runners, say that CI can close the gap. Do not imply it has.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Treating `assembleDebug` as "it builds" | Kotlin/Native never compiled `iosMain` or linked the framework | Keep an iOS link check in every config |
| Task names from memory | A missing task FAILs and looks like a real break (`testAndroidHostTest` vs `testDebugUnitTest`) | `--detect gradle`, or `./gradlew <module>:tasks --all` |
| Diffing against a local `main` | Unpushed or stale commits hide or add changes | `--base main` always uses the fetched `origin/main` |
| Untracked `.kt` files in the working tree | The build passes locally; the commit does not compile in CI | Commit them, or run with `--clean` |
| Reporting NOT RUN as passed | The iOS half was never compiled | Name every NOT RUN and its reason |
| Using `--base` right before a release | The link is downgraded to a compile for common-only diffs | Run unscoped before tagging |
| Checking a library change by building the app normally | The app resolves the *published* artifact, not your edit | Add a consumer with a substitution property ([references/configuration.md](references/configuration.md)) |
| AGP KMP library plugin without `withHostTest {}` | `commonTest` never runs on the JVM side, so no unit-test task exists | Add `withHostTest {}` in the module's `android {}` block |
| `iosArm64Test` as the iOS test task | Device-target test binaries cannot run on the Mac | Use `iosSimulatorArm64Test`, or `iosX64Test` on an Intel Mac |
| Two builds in one project at once | Gradle lock contention; one build waits, then times out | Run checks sequentially (the tool does) |

## Related skills

- `kmp-testing-patterns`: write the tests these checks run.
- `kmp-test-coverage-backfill`: raise coverage after the build is green.
- `mobile-accessibility-test-ids`: stable locators for UI and end-to-end tests.
- `kmp-build-failure-triage`: diagnose a FAIL this skill reports.
- `kmp-ci-github-actions`: run the same checks on CI runners, including macOS for iOS.
- [android/skills](https://github.com/android/skills): official Android agent skills.
- [skydoves/android-testing-skills](https://github.com/skydoves/android-testing-skills): Android testing skills.
