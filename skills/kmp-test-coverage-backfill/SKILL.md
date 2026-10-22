---
name: kmp-test-coverage-backfill
description: Use when Kotlin Multiplatform unit-test coverage must go up - a Kover report (koverXmlReport, report.xml) below target, koverVerify failing the build, "backfill tests", "get this module to 80% coverage", a module drifting below its threshold, or untested ViewModels, use cases, mappers and repositories in commonMain.
license: Apache-2.0
compatibility: Kotlin Multiplatform Gradle module with the Kover Gradle plugin 0.9.x (or ready to add it) and commonTest. Python 3.9+ (standard library only) for the report parser. iOS test verification needs macOS with Xcode.
metadata:
  category: testing
  platforms: android, ios
---

# KMP test coverage backfill

Raise one module's Kover line and branch coverage with `commonTest` unit tests, in a measured loop:
measure, rank the gaps, test the highest-value classes, measure again. Every number you report comes
from a Kover report produced in this session. Never estimate a number.

| Parameter | Default | Meaning |
|---|---|---|
| module | required | Gradle path, e.g. `:shared` |
| line target | 80 | Line coverage %, from the report's `LINE` counter |
| branch target | 60 | Branch coverage %, from the `BRANCH` counter |
| max iterations | 5 | Generate, run and re-measure loops before stopping |
| batch | 10 | Candidates attempted per iteration |
| fast | off | Inner loop runs only JVM tests; iOS tests run once, at the end |

## When to use

- `koverVerify` fails, or a module is below its coverage threshold.
- The user asks to backfill tests or reach a coverage percentage.
- Kover was just added and the baseline is low.

## When not to use

- Writing tests for a new feature as you build it: use `kmp-testing-patterns`.
- Checking that a change builds and passes on both platforms: use `kmp-build-check`.
- UI, screenshot or end-to-end tests: Composables are excluded here; see `mobile-accessibility-test-ids`
  for locators.

## Step 0 - Read the project first

1. **Kover present?** Run `./gradlew :<module>:tasks --all | grep -i kover`. If there is no Kover task,
   propose the setup in [references/kover-setup.md](references/kover-setup.md) and wait for a yes.
   Adding a build plugin is the user's call.
2. **Find the exclusion list.** Ideally it is one file (for example `gradle/coverage-exclusions.txt`)
   that the build loads. It may instead be inline in a `kover { reports { filters { } } }` block. Read
   it either way. Without one, propose `assets/coverage-exclusions.txt`.
3. **Read the current thresholds** in `kover { reports { verify { } } }` and in `gradle.properties`.
4. **Learn the test idiom from 2-3 existing tests:**
   - test naming (default `should_<expected>_when_<condition>`);
   - assertion library;
   - Turbine or not;
   - where fakes live (`Fake*`, `*Fakes.kt`);
   - in-memory production implementations;
   - how dispatchers are injected (`DispatcherProvider` or similar);
   - the ViewModel base class and its state/effect API.
5. **Find the test tasks.** The JVM-side task is `testDebugUnitTest`, `testAndroidHostTest` or
   `jvmTest`. The iOS task is `iosSimulatorArm64Test`. Confirm both with `tasks --all`.
6. **Remember what Kover counts.** Only JVM-target tests feed it. `iosMain` never appears, and iOS test
   runs never move the number. They still have to pass.

## Workflow

`<skill-dir>` is the directory holding this `SKILL.md`. Paths assume module `:shared` in directory
`shared/`. Adjust them to the project.

1. **Baseline.**

   ```bash
   ./gradlew :shared:koverXmlReport
   cp shared/build/reports/kover/report.xml build/coverage-iter0.xml
   python3 <skill-dir>/scripts/kover_gaps.py shared/build/reports/kover/report.xml \
     --exclusions gradle/coverage-exclusions.txt --line-target 80 --branch-target 60 \
     --source-root shared/src/commonMain/kotlin --format table
   ```

   The script prints totals and the exact gap (`+N lines, +N branches` to reach the targets). It
   lists candidates ranked by bucket: ViewModels, use cases, state machines/reducers,
   validators/gates, mappers with branches, repositories, top-level `*Kt` files, factories, then
   everything else. Within a bucket, classes with the most missed lines come first. A class missing
   10 or more branches moves up one bucket. Synthetic classes (`Foo$load$1`, `Foo$Companion`) are
   merged into `Foo`, because testing `Foo` covers them.
   If a test fails, `koverXmlReport` fails and writes no XML. Fix or report that first; nothing can
   be measured past a red suite.
   *Done when* you hold the baseline line % and branch % and the ranked list (use `--format json` to
   parse it).

2. **Pick the batch.** Take the top `batch` candidates in rank order. Never skip the first candidate
   because it is big: [references/playbooks.md](references/playbooks.md) covers big ViewModels,
   `*Kt` reducer files, repositories, small use cases, mappers and classes with no seam.

3. **Write the tests, one candidate at a time.**
   1. Read the source file (`source_file` in the JSON) and list its constructor dependencies.
   2. For each dependency, reuse an existing fake or in-memory implementation. Create
      `Fake<Type>` next to the tests only when none exists. A fake has settable results, call
      counters and the last arguments it received. Do not add a mocking library.
   3. Write `<ClassName>Test.kt` in the same package under `commonTest`. Cover the happy path, one
      test per branch in the source, and one boundary case per numeric or collection input. Group
      trivial same-shaped classes in one file.
   4. Every test asserts behaviour: state, return value, store contents, or effects. A test that only
      calls code to colour lines green is not allowed.
   5. Derive expectations from the source's real branches, not from the class name. Equality edges
      catch people: with `if (x <= prior) prior else x`, the call with `x == prior` returns `prior`.
   *Done when* each candidate has a test file, or a deferral reason.

4. **Compile-and-run gate.** Run the module's JVM test task (with `fast`) or `allTests`. For each
   failure, read the error and fix the test, **at most 3 attempts** per candidate. Then:
   - The test still does not compile: delete the test file you created, and mark the candidate
     `deferred: compile`.
   - A test still fails at runtime: delete that one `@Test` and mark it `deferred: runtime`. If the
     test looks right and the production code looks wrong, keep the evidence and mark it
     `deferred: suspected-bug`. Report it; do not bend the test to match the bug.
   - The class cannot be tested without a production change: mark it `deferred: needs-seam` and
     name the seam.
   *Done when* the suite is green.

5. **Re-measure and print progress.**

   ```bash
   ./gradlew :shared:koverXmlReport
   python3 <skill-dir>/scripts/kover_gaps.py shared/build/reports/kover/report.xml \
     --exclusions gradle/coverage-exclusions.txt --previous build/coverage-iter0.xml --format table
   cp shared/build/reports/kover/report.xml build/coverage-iter1.xml
   ```

   Print one line per iteration:
   `iter N - line X.X% (+Y.Y) / branch X.X% (+Y.Y) | tests added N | deferred N`.
   Stop when both targets are met, or when `max iterations` is used up.

6. **Stuck detection.** If two iterations in a row raise line coverage by less than 1 point, stop.
   List the top 5 blockers: class, missed lines, missed branches, and why each was deferred. More
   iterations on a wedged run waste time. The user decides: add guidance, approve a seam, or accept
   the gap.

7. **Final verification**, always, including after a `fast` loop:

   ```bash
   ./gradlew :shared:allTests                 # JVM and iOS simulator tests
   ./gradlew :shared:koverXmlReport :shared:koverHtmlReport :shared:koverVerify
   ```

   Check that the HTML headline (`shared/build/reports/kover/html/index.html`) agrees with the XML
   totals.

8. **Report** in this shape:

   ```markdown
   ## Coverage backfill - :shared
   - Line: 41.2% -> 78.9% (target 80%)  GAP        <- from report.xml, iteration 0 vs final
   - Branch: 33.0% -> 61.4% (target 60%) MET
   - Iterations: 4/5 (stopped: max iterations)
   | Iter | Line % | Branch % | Tests added | Deferred |
   - Tests added: <paths> - Fakes added: <paths> - Fakes reused: <n>
   | Deferred class | Reason (compile / runtime / suspected-bug / needs-seam / out-of-iterations / stuck) |
   - Next: one line per deferred class on how to unblock it.
   - Threshold: suggest raising koverVerify to <final - 1>; do not edit it yourself.
   ```

## Rules

1. **Evidence only.** Quote the command and the totals from the report. "Should be around 80%" is a
   failure.
2. **Never edit the exclusion list or the `koverVerify` thresholds** without the user's explicit yes.
   Excluding a class to hit a number hides code. Propose it instead.
3. **Stay on the project's test stack.** No new mocking, Robolectric or test-runner dependencies during
   a backfill. With no precedent, use `kotlin.test`, `kotlinx-coroutines-test` and hand-written fakes.
4. **Do not test** `@Composable` functions, `@Serializable` DTOs, DI modules, generated code, Room DAO
   interfaces or platform entry points. They belong in the exclusion list or in UI tests.
5. **Complexity is not a deferral reason.** Only `compile`, `runtime`, `suspected-bug`, `needs-seam`,
   `out-of-iterations` and `stuck` are.
6. **Stop at `max iterations`** even below target, and report the gap honestly.
7. **Do not commit.** Leave that to the user.

## Quick reference

| Command | Purpose |
|---|---|
| `./gradlew :m:koverXmlReport` | Run JVM tests, write `m/build/reports/kover/report.xml` |
| `./gradlew :m:koverHtmlReport` | Browse uncovered lines: `m/build/reports/kover/html/index.html` |
| `./gradlew :m:koverVerify` | Enforce the thresholds |
| `./gradlew :m:koverLog` | Print coverage in the console |
| `./gradlew :m:koverXmlReportDebug` | One Android variant only (faster, when variants exist) |
| `kover_gaps.py REPORT --exclusions F` | Rank candidates (JSON) |
| `... --format table` | Human-readable ranking |
| `... --previous OLD.xml` | Coverage delta since an earlier report |
| `... --source-root DIR` | Also skip `*Kt` files that contain `@Composable` |
| `... --top 0` | List every candidate |

## Verify

Report each item as PASS, FAIL or NOT RUN, with the reason for NOT RUN:

| Check | Command | PASS means |
|---|---|---|
| JVM tests | `./gradlew :m:<jvm test task>` | exit 0 |
| iOS tests | `./gradlew :m:iosSimulatorArm64Test` | exit 0. NOT RUN off macOS or without a simulator runtime. |
| Coverage threshold | `./gradlew :m:koverVerify` | exit 0 against the **existing** thresholds |
| Target reached | `kover_gaps.py ... --line-target L --branch-target B` | `"meets_targets": true` |
| Script self-test | `python3 -m unittest discover -s <skill-dir>/scripts -p "test_*.py"` | OK |

Never claim the target is met without the script output, or the XML totals, from the final run.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Expecting iOS tests to raise coverage | Kover instruments JVM targets only | Measure with JVM tests; run iOS tests for correctness |
| Writing tests for `Foo$bar$1` lambda classes | They are compiler-generated parts of `Foo` | Test `Foo`; the script merges them |
| Skipping the biggest ViewModel | It usually holds the largest single gap | Follow Playbook A |
| Calling `advanceUntilIdle()` with a ticker running | The loop reschedules forever; the test hangs | `advanceTimeBy(...)` then `runCurrent()` |
| Coverage-only tests with no assertions | The number rises; nothing is protected | Assert state, effects or store contents |
| Excluding classes to reach the target | The number lies about what is tested | Propose exclusions; the user decides |
| Asserting what the code "should" do from its name | Tests fail, or encode a misread | Read the branches; flag real bugs as `suspected-bug` |
| Reading `report.xml` after a failed test run | The file is stale, left over from an earlier run | Check the Gradle exit code first |
| Adding MockK in `commonTest` | MockK runs on the JVM only; iOS test compilation fails | Hand-written fakes |

## Related skills

- `kmp-testing-patterns`: how to write each test (dispatchers, effects, fakes, MockEngine).
- `kmp-build-check`: confirm both platforms build and pass after the backfill.
- `kmp-flaky-test-triage`: when a new or existing test passes and fails between runs.
- [Kotlin/kotlinx-kover](https://github.com/Kotlin/kotlinx-kover): Kover docs and releases.
- [skydoves/android-testing-skills](https://github.com/skydoves/android-testing-skills): Android testing skills.
