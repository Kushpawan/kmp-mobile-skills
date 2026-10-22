---
name: kmp-flaky-test-triage
description: Use when a Kotlin Multiplatform test is flaky — passes and fails without code changes, fails only on CI, only on iOS or Kotlin/Native, only with the whole suite or in another order; runTest timeouts, Turbine "No value produced in", "Module with the Main dispatcher had failed to initialize", missed SharedFlow or StateFlow emissions, "A Koin Application has already been started", or results that depend on time zone, locale or the clock.
license: Apache-2.0
compatibility: Kotlin Multiplatform Gradle project. JVM / Android host tests run anywhere; iOS simulator tests need macOS with Xcode.
metadata:
  category: debug
  platforms: android, ios
---

# KMP flaky test triage

A flaky test depends on something it does not control: real time, a thread it did not choose,
state left by another test, the order of events, the machine's clock or locale. Find that input and
put it under the test's control. Retries, longer timeouts, `delay` and `@Ignore` hide the problem
and usually hide a real bug in production code too.

## When to use

- A test that passes and fails on the same code; "fails about one run in five on CI".
- A test that fails only on CI, only on the iOS simulator, only in the full suite, or only after
  another test.
- `runTest` timeouts, Turbine timeouts, `Dispatchers.Main` errors, missed or extra flow emissions.

## When not to use

- The test fails every time → it is a real failure; fix it with `mobile-bug-fix`.
- The code under test crashes the app → `kmp-crash-triage`.
- The test task does not compile or link → `kmp-build-failure-triage`.
- Setting up test infrastructure from scratch → the test setup guidance in
  [android/skills `testing/testing-setup`](https://github.com/android/skills/tree/main/testing/testing-setup)
  for the Android side; this skill is about making existing tests deterministic.

## Step 0 — Read the project first

1. **Test stack.** From `gradle/libs.versions.toml` and test sources: `kotlin.test`, JUnit 4 or 5 on
   the Android host, Kotest, `kotlinx-coroutines-test` (version), Turbine, MockK or hand-written
   fakes, Ktor `MockEngine`.
2. **Task names per target.** `./gradlew :shared:tasks --group verification` — e.g.
   `testDebugUnitTest` (androidTarget + `com.android.library`), `testAndroidHostTest` (KMP Android
   library plugin), `jvmTest`, `iosSimulatorArm64Test`, `allTests`.
3. **Dispatchers.** How production code gets dispatchers: an injected `DispatcherProvider` or
   `CoroutineDispatcher` parameter, or hard-coded `Dispatchers.IO` / `Dispatchers.Default`. How
   tests set `Dispatchers.Main`: a base class, a helper, a JUnit rule (Android host only).
4. **Shared state.** `object` singletons, top-level `val`s with caches, Koin started in tests
   (`startKoin`, `KoinTest`), databases or files used by tests, `NSUserDefaults` / preferences.
5. **Time.** Does production code call `Clock.System.now()`, `TimeZone.currentSystemDefault()`,
   `Random`, `UUID`/`Uuid.random()` directly, or receive them injected?
6. **CI.** Test retry plugins (`org.gradle.test-retry`) or `retry` wrappers that mask flakiness,
   `maxParallelForks`, build cache use, the machine type for iOS tests.

Follow the project's patterns for any fix: if it already has a `DispatcherProvider` or a
`MainDispatcherRule`, use it rather than adding a second mechanism.

## Workflow

### 1. Capture the failure

Record: the exact test (class and method), the target (Android host / JVM / iOS simulator), local
or CI, the assertion message and stack, how often it fails, and what changed recently. Pull CI's
JUnit XML from `build/test-results/<testTask>/` — it holds the full message and stdout.

Done when you know which target fails and have the failing assertion text.

### 2. Reproduce by repetition

Run the single test many times in **fresh processes**, then in the **same process**, then with the
**whole class / suite**. Each mode exposes a different cause.

```bash
# Android host / JVM: one test, 50 runs, each in a fresh test JVM. Stop at the first failure.
# --rerun forces the task to execute even when Gradle considers it up to date.
for i in $(seq 1 50); do
  ./gradlew :shared:testDebugUnitTest --tests 'com.example.app.notes.NotesViewModelTest' --rerun -q \
    || { echo "FAILED on run $i"; break; }
done

# iOS simulator through Gradle — same loop, iOS task (macOS only)
for i in $(seq 1 20); do
  ./gradlew :shared:iosSimulatorArm64Test --tests 'com.example.app.notes.NotesViewModelTest' --rerun -q \
    || { echo "FAILED on run $i"; break; }
done
```

`--rerun` (Gradle 7.6+) re-executes just that task; on older Gradle use `--rerun-tasks` (reruns
every task) or run `cleanTest<Task>` first. If the output says `FROM-CACHE`, add
`--no-build-cache`.

Repeat **inside one process** on Kotlin/Native — this surfaces state leaking between runs:

```bash
./gradlew :shared:linkDebugTestIosSimulatorArm64          # -> shared/build/bin/iosSimulatorArm64/debugTest/test.kexe
xcrun simctl boot "<an installed iPhone simulator>"        # once; list with: xcrun simctl list devices available
BIN=shared/build/bin/iosSimulatorArm64/debugTest/test.kexe
xcrun simctl spawn booted "$BIN" --ktest_list_tests | grep NotesViewModelTest   # exact test names
xcrun simctl spawn booted "$BIN" --ktest_filter='com.example.app.notes.NotesViewModelTest.*' --ktest_repeat=50
```

Then run the **whole class** and the **whole module suite** in the same loops. Passing alone but
failing in the suite means order dependence or shared state.

To check time-zone dependence quickly, run once with an extreme zone: `TZ=Pacific/Kiritimati
./gradlew --no-daemon …` for JVM tests, or `SIMCTL_CHILD_TZ=Pacific/Kiritimati xcrun simctl spawn
booted "$BIN" …` for the iOS binary (`simctl` passes `SIMCTL_CHILD_`-prefixed variables to the
child). Run the loop while the machine is busy (a second build) to approximate a loaded CI runner.

Done when you have a failure rate, e.g. "7 / 50 alone, 0 / 50 in-process, 10 / 10 after
`OrdersRepositoryTest`".

### 3. Isolate

Shrink to the smallest failing setup: one test alone; the test plus the one test that runs before
it; one target. To find a polluting test, bisect the list of tests that ran before the failure
(run the first half + the flaky test, then the second half). Note the target: iOS-only flakes are
usually threading, main-queue or GC-timing issues; JVM-only ones are often `Dispatchers.Main`,
`Looper` or file-system issues.

### 4. Classify

Match the evidence against the [causes table](#quick-reference--causes). Write the cause as one
sentence: *"The test asserts before the repository coroutine on `Dispatchers.IO` finishes, so it
passes only when the IO thread wins the race."* If no row fits, add temporary logging (thread name,
timestamps) through the project's logger and rerun the loop.

### 5. Fix the cause

Change the test, the production code, or both, so the uncontrolled input becomes controlled.
Patterns with code: [references/fix-patterns.md](references/fix-patterns.md). Common ones:

- Inject dispatchers into production code; in tests, build every dispatcher from the test's
  `testScheduler` so `runTest` controls all of them.
- Set `Dispatchers.Main` before each test and reset it after.
- Start collecting a `SharedFlow` **before** the action that emits (Turbine `test {}` or
  `backgroundScope.launch`), and never assert on a transient `StateFlow` value you did not control.
- Give each test fresh instances; stop Koin after each test or avoid the global context.
- Inject `Clock`, `TimeZone` and `Random`; use fixed values in tests.

Never: add `delay`/`Thread.sleep`, raise a timeout to make it pass, add a retry, or mark it ignored.
If production code has a real race, fix the production code — the flaky test found a bug.

### 6. Prove it is stable

Rerun the same loops from step 2 on **both** platforms and record the numbers:

```text
Before   NotesViewModelTest: 7/50 failed (Android host, fresh JVM), 3/50 (iOS, --ktest_repeat)
After    0/100 Android host, 0/100 iOS in-process, full module suite 10/10 on both
Cause    <one sentence>      Fix  <file:line, what changed>
```

A fix proven only on the platform where it flaked is not done: the same test runs on every target.

## Quick reference — causes

| Symptom | Cause | Fix |
|---|---|---|
| Passes locally, fails on slower CI | Real time: `delay`, `Thread.sleep`, `withTimeout` on a real dispatcher | Virtual time via `runTest` and injected dispatchers |
| `Module with the Main dispatcher had failed to initialize` or `…is missing` (JVM), or a hang on iOS | `Dispatchers.Main` used without `Dispatchers.setMain` | `setMain` in `@BeforeTest` |
| Next test behaves oddly after a failure | `Dispatchers.resetMain()` not called | `resetMain` in `@AfterTest` |
| Assertion sees old state, sometimes | Production code hard-codes `Dispatchers.IO` / `Default`; work races the assertion | Inject the dispatcher; use the test scheduler |
| State never updates in the test | `StandardTestDispatcher` queued the work; nothing advanced it | `advanceUntilIdle()` / `runCurrent()`, or `UnconfinedTestDispatcher` where eager is intended |
| Two schedulers: delays not skipped, odd ordering | A second `TestCoroutineScheduler` (new dispatcher not built from `testScheduler`) | Build every test dispatcher from `testScheduler` |
| One-shot event "sometimes missing" | `SharedFlow` (replay 0) emitted before collection started | Collect first: Turbine `test {}` or `backgroundScope` collector |
| `Loading` state "sometimes missing" | `StateFlow` conflates; fast updates skip intermediate values | Control the dispatcher and step with `runCurrent()`, or assert only the final state |
| Turbine `No value produced in 3s` on CI | Emission blocked by a dispatcher problem (Turbine's timeout is wall-clock, default 3 s) | Fix the dispatcher; do not just raise the timeout |
| `runTest` fails after 60 s | A coroutine never completes (infinite collector in the test scope) | Launch long-running collectors in `backgroundScope` |
| `A Koin Application has already been started` | Global Koin from a previous test still running | `stopKoin()` in `@AfterTest`, or an isolated `koinApplication {}` |
| Passes alone, fails in the suite | Shared mutable state: `object` caches, fakes reused across tests, DB files | Fresh instances per test; reset or avoid globals |
| Fails near midnight, month end, or on a UTC CI | `Clock.System.now()` / system time zone used directly | Inject `Clock` and `TimeZone`; fixed instants in tests |
| Fails on machines with another language | Locale-dependent formatting or parsing | Explicit locale/format in production code; fixed in tests |
| Different result per run with random data | Unseeded `Random`, random UUIDs in assertions | Inject a seeded `Random` / ID generator |
| Fails on one target only, collections involved | `HashMap` / `HashSet` iteration order is unspecified and can differ by platform | Assert on sorted lists or set equality |
| Fails only on iOS, involves `deinit` / weak refs | Swift/ObjC objects held by Kotlin are freed only after a Kotlin GC | Do not assert release timing; test the cleanup call instead |
| Fails only on iOS on the second run | Files or `NSUserDefaults` persisted in the simulator between runs | Unique temp directories; clean up in `@AfterTest` |
| Fails when tests run in parallel | Shared database file, port or temp path across test JVMs | In-memory DB or unique names per test |
| Network-dependent result | Real HTTP in a unit test | Ktor `MockEngine` or a fake data source |
| "Fixed" but the test did not run | Gradle up-to-date or build-cache hit | `--rerun`, `--no-build-cache`; check the test count in the report |

## Verify

Report each check as **PASS**, **FAIL** or **NOT RUN (reason)**, with run counts. Never report a check
as passed that you did not run.

```bash
# Single test, fresh processes, both platforms (counts in the report)
for i in $(seq 1 100); do ./gradlew :shared:testDebugUnitTest --tests '<Test>' --rerun -q || break; done
for i in $(seq 1 30);  do ./gradlew :shared:iosSimulatorArm64Test --tests '<Test>' --rerun -q || break; done
# Same process, iOS
xcrun simctl spawn booted shared/build/bin/iosSimulatorArm64/debugTest/test.kexe --ktest_filter='<Class>.*' --ktest_repeat=100
# Whole suite, every target, several times
for i in $(seq 1 5); do ./gradlew :shared:allTests --rerun-tasks -q || break; done
```

Also confirm in the test report that the test actually executed (count > 0), and that no retry
plugin reran it.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Adding `delay(100)` before the assertion | Wins the race on your laptop, loses on CI | Control the dispatcher; advance virtual time |
| Raising the Turbine or `runTest` timeout | The event still never arrives on slow runners | Find why it is not emitted |
| Enabling a test retry plugin | Flakiness — and the production race — ship anyway | Fix the cause; keep retries off for unit tests |
| Test dispatchers that do not share one scheduler (`setMain` inside the test body, a fresh `StandardTestDispatcher()` for an injected dispatcher) | Main, injected dispatchers and `runTest` run on different virtual clocks | `setMain` in `@BeforeTest` (then `runTest` adopts its scheduler); build injected dispatchers from `testScheduler` |
| Collecting a `SharedFlow` after calling the action | The emission is already gone | Start the collector first |
| Asserting every `StateFlow` value in order | Conflation drops values depending on timing | Assert what the UI needs: the settled state |
| Proving the fix only on the JVM | The same `commonTest` also runs on Kotlin/Native | Loop the iOS task and the in-process repeat too |
| Fixing only the test when production code races | Users hit the race the test found | Fix production code; keep the test |

## Related skills

- `mobile-bug-fix` — when the "flaky" test turns out to fail deterministically.
- `kmp-crash-triage` — when the code under test crashes on one platform.
- `kmp-ci-github-actions` — CI setup for running both platforms' tests.
- [cashapp/turbine](https://github.com/cashapp/turbine) — flow testing; read its notes on hot flows and timeouts.
- [kotlinx-coroutines-test](https://github.com/Kotlin/kotlinx.coroutines/blob/master/kotlinx-coroutines-test/README.md) — `runTest`, test dispatchers, `setMain`.
- [CharlesWiltgen/Axiom `axiom-analyze-test-failures`](https://github.com/CharlesWiltgen/Axiom/tree/main/axiom-codex/skills/axiom-analyze-test-failures) — flaky XCTest / Swift-side tests.
- [android/skills `testing/testing-setup`](https://github.com/android/skills/tree/main/testing/testing-setup) — Android test infrastructure.
