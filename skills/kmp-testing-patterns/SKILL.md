---
name: kmp-testing-patterns
description: Use when writing or fixing unit tests in a Kotlin Multiplatform project - commonTest, kotlin.test, runTest, StandardTestDispatcher, Dispatchers.setMain, Turbine, testing a ViewModel's StateFlow and one-shot effects, fakes versus mocks (MockK fails on iOS), Ktor MockEngine, Koin test overrides, or making new tests run the same on the JVM and on iOS.
license: Apache-2.0
compatibility: Kotlin Multiplatform Gradle project with commonTest. Running iOS tests needs macOS with Xcode and an iOS simulator runtime.
metadata:
  category: testing
  platforms: android, ios
---

# KMP testing patterns

Business logic in `commonMain` is tested once, in `commonTest`, and runs on every target: JVM,
Android host and the iOS simulator. A reliable test controls time and threads with test dispatchers,
subscribes to effects before it acts, asserts both state and effects, and uses hand-written fakes
that run on every target.

## When to use

- Writing tests for a ViewModel, use case, repository, mapper, reducer or validator in a KMP module.
- A test you are writing hangs, misses an emission, or needs dispatcher control.
- Choosing between fakes and mocks, or setting up Turbine, `MockEngine` or Koin for tests.
- Deciding which Gradle task runs which tests.

## When not to use

- Raising a module's coverage number in a loop: use `kmp-test-coverage-backfill`, which applies
  these patterns.
- Checking that the whole repo builds and passes on both platforms: use `kmp-build-check`.
- Locators for UI or end-to-end tests: use `mobile-accessibility-test-ids`.
- Diagnosing an existing test that passes and fails without code changes, or fails only in CI or
  only on iOS: use `kmp-flaky-test-triage`.

## Step 0 - Read the project first

Before writing a test, read two or three existing tests and the class under test. Write in the
project's idiom, not this skill's defaults.

| Find out | Where to look | Follow it |
|---|---|---|
| Test names | existing `*Test.kt` | default `should_<expected>_when_<condition>`; keep the project's own scheme if it has one |
| Assertion library | imports | `kotlin.test`, AssertK, Kotest assertions: whichever is there |
| Flow testing | imports of `app.cash.turbine` | Turbine if present; otherwise manual collection |
| Fakes | `commonTest/**/Fake*.kt`, `*Fakes.kt`, `InMemory*` in `commonMain` | reuse before writing new ones |
| Mocking | `dev.mokkery`, `io.mockk` in the build files | do not add a mocking library that is not already there |
| Dispatchers | a `DispatcherProvider` (or similar) on constructors | inject a test dispatcher through it |
| ViewModel base | `ViewModel`, or a project base such as `MviViewModel<State, Effect>` | test through its public state/effect API |
| DI | Koin, kotlin-inject, Metro, manual | construct directly in unit tests; use DI only for wiring tests |
| Source sets / tasks | `build.gradle.kts`, `./gradlew :m:tasks --all` | see the Quick reference |
| Versions | `gradle/libs.versions.toml` | add test libraries there, never inline |

## Workflow

1. **Choose what to test.** Test everything that has behaviour:
   - ViewModels and state holders: every action, every resulting state, every emitted effect;
   - use cases;
   - repositories (mapping, caching, error handling);
   - mappers (nullable and unknown input);
   - reducers, validators and state machines.

   Do **not** unit-test Composables, generated code, DI modules or plain DTOs by default. Put UI
   behaviour in a small number of Compose UI tests (see
   [references/data-and-di-tests.md](references/data-and-di-tests.md)).
   *Done when* you have a list of behaviours, one test per behaviour.

2. **Put the test in the right source set.** `commonTest` for anything in `commonMain`. Use
   `androidHostTest` / `androidUnitTest` / `jvmTest` / `iosTest` only for `actual` implementations
   and platform code. Use the same package as the class under test, so `internal` members are visible.

3. **Build the test doubles.** Prefer hand-written fakes: an implementation of the interface with
   settable results, call counters and recorded arguments.
   - Fakes run on every target. MockK and Mockito need the JVM, so they fail iOS test compilation.
   - [Mokkery](https://mokkery.dev) is a KMP mocking compiler plugin. Use it only if the project
     already does.
   - Reuse in-memory production implementations as fakes.

4. **Control coroutines.**
   - Wrap every suspend test in `runTest { }`. Delays use virtual time, so a 30-second timeout
     finishes instantly.
   - Inject dispatchers through a `DispatcherProvider` and pass test dispatchers that share
     `testScheduler`. A `withContext(Dispatchers.IO)` hard-coded in production escapes the scheduler,
     so `advanceUntilIdle()` cannot drive it.
   - Anything on `viewModelScope` or `Dispatchers.Main` needs `Dispatchers.setMain(testDispatcher)` in
     `@BeforeTest` and `Dispatchers.resetMain()` in `@AfterTest`. JVM tests have no Main dispatcher.
     In an iOS test binary, work posted to the main queue may never run.
   - Pick the dispatcher on purpose:

     | Dispatcher | Behaviour | Use when |
     |---|---|---|
     | `StandardTestDispatcher` | queues work until `runCurrent()` / `advanceUntilIdle()` / `advanceTimeBy()` | you assert intermediate states or ordering |
     | `UnconfinedTestDispatcher` | runs launched work eagerly | the ViewModel loads in `init`, or for effect collectors |

   - Never wait with `delay()` in the test body, `Thread.sleep`, or real-time polling.

5. **Subscribe to effects before you act.** One-shot effects (navigate, toast, dialog) are lost or
   delayed when nobody is collecting. A `MutableSharedFlow(replay = 0)` drops an emission that has no
   subscriber. Start the collector first:

   ```kotlin
   val effects = mutableListOf<NotesEffect>()
   backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { viewModel.effects.toList(effects) }
   viewModel.onAction(NotesAction.Open(id = "42"))      // act AFTER subscribing
   advanceUntilIdle()
   ```

   Or, with Turbine: `turbineScope { val e = viewModel.effects.testIn(backgroundScope); ... }`.
   `backgroundScope` is cancelled when the test ends, so an endless collector does not hang `runTest`.

6. **Assert state and effects, every time.** Compare the whole `UiState` with `assertEquals`, so an
   unexpected field change fails the test. Assert the exact effect list, `emptyList()` included, so
   an extra navigation fails too. For an in-flight state (loading), hold the fake on a
   `CompletableDeferred` gate and call `runCurrent()`. `StateFlow` conflates, so without a gate a fast
   fake skips straight past loading.

7. **Keep each test independent.** Use Arrange-Act-Assert and one behaviour per test. Create fakes per
   test or in `@BeforeTest`. Reset every global in `@AfterTest`: `Dispatchers.resetMain()`,
   `stopKoin()`, and any singleton you configured. Tests must pass alone, in any order, and on every
   target.

8. **Run the tests on the JVM and on iOS** (Quick reference). A test that passes only on the JVM is
   not done.

A complete feature, with the ViewModel, fakes, dispatcher provider, seven tests and the Turbine
variants, is in [references/viewmodel-test-worked-example.md](references/viewmodel-test-worked-example.md).
`MockEngine`, repository, Koin, Mokkery and Compose UI test patterns are in
[references/data-and-di-tests.md](references/data-and-di-tests.md).

## Patterns at a glance

```kotlin
@OptIn(ExperimentalCoroutinesApi::class)
class NotesViewModelTest {
    private val testDispatcher = StandardTestDispatcher()
    private val notesRepository = FakeNotesRepository()

    @BeforeTest fun setUp() = Dispatchers.setMain(testDispatcher)
    @AfterTest fun tearDown() = Dispatchers.resetMain()

    @Test
    fun should_keepNoteAndShowMessage_when_deleteFails() = runTest {
        // Arrange
        notesRepository.notes = listOf(note("1"))
        notesRepository.deleteSucceeds = false
        val viewModel = NotesViewModel(notesRepository, TestDispatcherProvider(testDispatcher))
        viewModel.onAction(NotesAction.Refresh)
        advanceUntilIdle()
        val effects = mutableListOf<NotesEffect>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { viewModel.effects.toList(effects) }

        // Act
        viewModel.onAction(NotesAction.Delete(id = "1"))
        advanceUntilIdle()

        // Assert: state AND effects
        assertEquals(listOf(note("1")), viewModel.state.value.notes)
        assertEquals(listOf<NotesEffect>(NotesEffect.ShowMessage("Could not delete the note")), effects)
    }
}
```

## Quick reference

Which Gradle task runs which tests. Task names depend on the plugins, so confirm them with
`./gradlew :<module>:tasks --all`.

| Task | Runs | Notes |
|---|---|---|
| `:m:allTests` | every target's tests, plus an aggregated report | includes iOS simulator tests on macOS |
| `:m:testDebugUnitTest` | `commonTest` + `androidUnitTest` on the JVM | modules on `com.android.library` / `application` with `androidTarget()` |
| `:m:testAndroidHostTest` | `commonTest` + `androidHostTest` on the JVM | modules on `com.android.kotlin.multiplatform.library`. Exists only after `withHostTest {}` in its `android {}` block; host tests are off by default. |
| `:m:jvmTest` | `commonTest` + `jvmTest` | modules with a `jvm()` target |
| `:m:iosSimulatorArm64Test` | `commonTest` + `iosTest` on the iOS simulator | Apple-silicon Macs; `iosX64Test` on Intel. Device targets cannot run tests on the Mac. |
| `:m:connectedAndroidTest` (or `connectedDebugAndroidTest`) | device or emulator tests | needs a running emulator or device |

Run one class: `./gradlew :shared:jvmTest --tests "com.example.app.notes.NotesViewModelTest"`. The
same `--tests` filter works for the Android unit-test and iOS simulator test tasks.

| API | Use |
|---|---|
| `runTest { }` | every suspend test; virtual time |
| `testScheduler`, `backgroundScope` | inside `runTest`: share the scheduler; host endless collectors |
| `runCurrent()` / `advanceUntilIdle()` / `advanceTimeBy(ms)` | run due tasks / run everything / move virtual time. After `advanceTimeBy`, call `runCurrent()` for tasks due exactly then. |
| `Dispatchers.setMain(d)` / `Dispatchers.resetMain()` | replace Main for `viewModelScope` |
| Turbine `flow.test { awaitItem() }` | assert a sequence of emissions; 3 s wall-clock timeout by default |
| Turbine `turbineScope { flow.testIn(backgroundScope) }` | several flows at once (state plus effects) |
| Ktor `MockEngine { respond(...) }` + `engine.requestHistory` | API-layer tests without a network |
| `startKoin { modules(prod, testOverrides) }` / `stopKoin()` | wiring tests; the last module wins |

## Verify

```bash
./gradlew :shared:<jvm test task>              # testDebugUnitTest, testAndroidHostTest or jvmTest
./gradlew :shared:iosSimulatorArm64Test        # macOS with Xcode only
./gradlew :shared:allTests                     # everything this host can run
```

Report each task as **PASS** (exit 0), **FAIL** (quote the first failing test and its assertion) or
**NOT RUN**, with the reason: for example "iOS tests NOT RUN: no Xcode on this machine". Never call
new tests "passing" when only the JVM half ran.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| No `Dispatchers.setMain` for a ViewModel test | JVM: "Module with the Main dispatcher is missing" (Android: "Method getMainLooper in android.os.Looper not mocked"). iOS: work posted to Main may never run. | `setMain` in `@BeforeTest`, `resetMain` in `@AfterTest` |
| A new `StandardTestDispatcher()` per collaborator | Several schedulers; `advanceUntilIdle()` drives only one | One dispatcher, or `StandardTestDispatcher(testScheduler)` |
| `Dispatchers.IO` hard-coded in production | Work escapes virtual time; the test is flaky or slow | Inject a `DispatcherProvider` |
| Triggering the action, then collecting effects | The emission is gone (`SharedFlow`) or the test races (`Channel`) | Collect in `backgroundScope` first, or Turbine `testIn` |
| Asserting state only | A wrong navigation or toast goes unnoticed | Assert the exact effect list too |
| Asserting a loading state with a fast fake | `StateFlow` conflates; the loading state is never seen | Hold the fake on a `CompletableDeferred`, then `runCurrent()` |
| MockK or Mockito in `commonTest` | JVM-only; iOS test compilation fails | Hand-written fakes (or Mokkery if adopted) |
| `advanceUntilIdle()` with a ticker or polling loop | The loop reschedules forever; the test hangs | `advanceTimeBy(n)` then `runCurrent()` |
| Asserting `HashMap` / `HashSet` iteration order | The order is unspecified and differs between JVM and Native | Compare as sets or maps, or sort first |
| Tests that depend on the system time zone, locale or clock | Pass locally, fail in CI or on the simulator | Inject a clock; use fixed time zones |
| A test MockEngine client built by hand | It tests different plugins and config than production uses | Use the production client factory with the mock engine |
| Forgetting `stopKoin()` | The next `startKoin` throws; definitions leak between tests | `stopKoin()` in `@AfterTest` |
| Only JVM tests run in CI | iOS-only failures ship | Run `iosSimulatorArm64Test` on a macOS runner |

## Related skills

- `kmp-test-coverage-backfill`: apply these patterns in a measured loop to reach a coverage target.
- `kmp-build-check`: run the tests on both platforms, with PASS / FAIL / NOT RUN reporting.
- `mobile-accessibility-test-ids`: stable `testTag`s for Compose UI tests and end-to-end tests.
- `kmp-flaky-test-triage`: when an existing test is flaky or fails only on one platform.
- `compose-multiplatform-screen` and `kmp-data-layer`: the production shapes these tests target.
- [cashapp/turbine](https://github.com/cashapp/turbine): Flow testing library.
- [skydoves/android-testing-skills](https://github.com/skydoves/android-testing-skills): Android testing skills.
- [chrisbanes/skills](https://github.com/chrisbanes/skills): Kotlin coroutines/Flow and Compose skills, including Compose UI testing.
- [AvdLee/Swift-Testing-Agent-Skill](https://github.com/AvdLee/Swift-Testing-Agent-Skill): Swift Testing for the iOS side.
