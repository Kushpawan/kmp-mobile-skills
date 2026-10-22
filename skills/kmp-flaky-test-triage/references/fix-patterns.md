# Fix patterns for flaky KMP tests

Contents

1. Inject dispatchers; share one test scheduler
2. `Dispatchers.Main` in tests
3. One-shot events: collect before you act
4. `StateFlow`: control intermediate states instead of racing them
5. Time, time zones and locales
6. Koin and other global state
7. Randomness and generated IDs
8. iOS / Kotlin/Native specifics
9. Finding the test that pollutes another

Examples use the notes domain and `kotlin.test` + `kotlinx-coroutines-test` + Turbine. Adapt names
and helpers to the project — if it already has a `DispatcherProvider` or a main-dispatcher helper,
use that.

## 1. Inject dispatchers; share one test scheduler

Production code that hard-codes `Dispatchers.IO` or `Dispatchers.Default` runs on real threads in
tests: `runTest` cannot skip its delays or wait for it, so assertions race it.

```kotlin
// commonMain
interface DispatcherProvider {
    val main: CoroutineDispatcher
    val io: CoroutineDispatcher
    val default: CoroutineDispatcher
}

class DefaultDispatcherProvider : DispatcherProvider {
    override val main: CoroutineDispatcher = Dispatchers.Main
    // In commonMain, Dispatchers.IO needs `import kotlinx.coroutines.IO` and resolves only when
    // every target is JVM/Android or Native.
    override val io: CoroutineDispatcher = Dispatchers.IO
    override val default: CoroutineDispatcher = Dispatchers.Default
}

class NotesRepositoryImpl(
    private val api: NotesApi,
    private val dao: NotesDao,
    private val dispatchers: DispatcherProvider,
) : NotesRepository {
    override suspend fun refresh() = withContext(dispatchers.io) {
        dao.replaceAll(api.fetchNotes().map { it.toEntity() })
    }
}
```

```kotlin
// commonTest — every dispatcher comes from the test's scheduler, so runTest controls all of them.
class TestDispatcherProvider(scheduler: TestCoroutineScheduler) : DispatcherProvider {
    private val dispatcher = StandardTestDispatcher(scheduler)
    override val main: CoroutineDispatcher = dispatcher
    override val io: CoroutineDispatcher = dispatcher
    override val default: CoroutineDispatcher = dispatcher
}
```

Rules:

- Build every test dispatcher from `testScheduler`. A `StandardTestDispatcher()` without an
  argument, created inside the test body, may start its own scheduler — two virtual clocks, and
  delays on one are not skipped by the other.
- `StandardTestDispatcher` queues work until the test advances it: call `runCurrent()` to run what
  is due now, `advanceUntilIdle()` to run everything, `advanceTimeBy(…)` for time-based logic.
- `UnconfinedTestDispatcher` runs launched coroutines eagerly. Use it where eager is the intent
  (simple collectors), not to make ordering problems disappear.

## 2. `Dispatchers.Main` in tests

`viewModelScope` and most UI-facing code use `Dispatchers.Main`. Without a replacement:

- On the JVM / Android host the test fails with *"Module with the Main dispatcher had failed to
  initialize. For tests Dispatchers.setMain from kotlinx-coroutines-test module can be used"* or
  *"Module with the Main dispatcher is missing"*.
- On iOS the main queue is real; work posted to it can wait indefinitely while the test runs, so
  the test hangs or hits the `runTest` timeout.

```kotlin
@OptIn(ExperimentalCoroutinesApi::class)
class NotesViewModelTest {

    @BeforeTest
    fun setUp() {
        // Set before runTest: runTest then adopts this dispatcher's scheduler as its own.
        Dispatchers.setMain(StandardTestDispatcher())
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()   // otherwise the next test inherits this dispatcher
    }

    @Test
    fun should_showNotes_when_loadSucceeds() = runTest {
        val repository = FakeNotesRepository(notes = listOf(Note(id = "n1", title = "Groceries")))
        val viewModel = NotesViewModel(repository, TestDispatcherProvider(testScheduler))

        viewModel.onAction(NotesAction.Load)
        advanceUntilIdle()

        assertEquals(listOf("Groceries"), viewModel.state.value.notes.map { it.title })
    }
}
```

On the Android host you can wrap this in a JUnit rule; in `commonTest` there are no rules, so use
`@BeforeTest` / `@AfterTest` in each class or the project's existing helper.

## 3. One-shot events: collect before you act

A `MutableSharedFlow` with `replay = 0` drops emissions that happen while nobody is collecting. If
the test starts collecting after calling the action, it passes only when the collector happens to
start first.

With Turbine — `test {}` starts collecting (up to the first suspension) before running the block:

```kotlin
@Test
fun should_navigateBack_when_saveSucceeds() = runTest {
    val viewModel = EditNoteViewModel(FakeNotesRepository(), TestDispatcherProvider(testScheduler))

    viewModel.effects.test {
        viewModel.onAction(EditNoteAction.Save)              // act inside the collector
        assertEquals(EditNoteEffect.NavigateBack, awaitItem())
        cancelAndIgnoreRemainingEvents()
    }
}
```

Without Turbine — an eager collector in `backgroundScope`, which `runTest` cancels at the end:

```kotlin
@Test
fun should_navigateBack_when_saveSucceeds() = runTest {
    val viewModel = EditNoteViewModel(FakeNotesRepository(), TestDispatcherProvider(testScheduler))
    val effects = mutableListOf<EditNoteEffect>()
    backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { viewModel.effects.toList(effects) }

    viewModel.onAction(EditNoteAction.Save)
    advanceUntilIdle()

    assertEquals(listOf(EditNoteEffect.NavigateBack), effects)
}
```

Turbine's waits use a **wall-clock** timeout (default 3 seconds) that ignores virtual time. A
`No value produced in …` failure on CI means the emission did not happen in time — usually a
dispatcher outside the test scheduler — not that the timeout is too short.

Long-running collectors launched directly in the test body keep `runTest` from finishing until its
own timeout (60 seconds by default). Put them in `backgroundScope`.

## 4. `StateFlow`: control intermediate states instead of racing them

`StateFlow` keeps only the latest value and skips equal ones. A test that expects to observe
`Loading` before `Loaded` passes only when the collector runs between the two updates. Make the
intermediate state observable on purpose by holding the dependency:

```kotlin
class FakeNotesRepository(
    private val notes: List<Note> = emptyList(),
    val gate: CompletableDeferred<Unit>? = null,
) : NotesRepository {
    override suspend fun load(): List<Note> {
        gate?.await()          // the test decides when loading finishes
        return notes
    }
}

@Test
fun should_showLoading_when_loadIsInProgress() = runTest {
    val repository = FakeNotesRepository(gate = CompletableDeferred())
    val viewModel = NotesViewModel(repository, TestDispatcherProvider(testScheduler))

    viewModel.onAction(NotesAction.Load)
    runCurrent()
    assertTrue(viewModel.state.value.isLoading)

    repository.gate!!.complete(Unit)
    advanceUntilIdle()
    assertFalse(viewModel.state.value.isLoading)
}
```

If the screen only needs the settled state, assert only that.

## 5. Time, time zones and locales

Code that reads the system clock or time zone gives different answers on CI (often UTC), near
midnight, at month or year boundaries, and across daylight-saving changes. Inject them:

```kotlin
// commonMain — Clock is kotlin.time.Clock (Kotlin 2.1.20+, @ExperimentalTime) or, with
// kotlinx-datetime before 0.7, kotlinx.datetime.Clock. Use whichever the project already uses.
class NoteFactory(
    private val clock: Clock,
    private val timeZone: TimeZone,
) {
    fun create(title: String): Note =
        Note(title = title, createdOn = clock.now().toLocalDateTime(timeZone).date)
}

// commonTest
private class FixedClock(private val instant: Instant) : Clock {
    override fun now(): Instant = instant
}

@Test
fun should_useLocalDate_when_utcIsAlreadyTomorrow() {
    val factory = NoteFactory(
        clock = FixedClock(Instant.parse("2025-03-01T02:30:00Z")),
        timeZone = TimeZone.of("America/New_York"),
    )

    assertEquals(LocalDate(2025, 2, 28), factory.create("Groceries").createdOn)
}
```

- For durations inside coroutines, `runTest` provides virtual time; `TestScope.testTimeSource`
  measures it.
- Format and parse with an explicit locale or a fixed pattern in production code, so a device or
  CI machine in another language cannot change the result.

## 6. Koin and other global state

`startKoin` registers a global instance. A test that starts it without stopping it breaks the next
test with *"A Koin Application has already been started"*, or leaks definitions into it.

```kotlin
class NotesModuleTest {
    @AfterTest
    fun tearDown() = stopKoin()

    @Test
    fun should_resolveRepository_when_notesModuleLoaded() {
        val koin = startKoin { modules(notesModule, testOverridesModule) }.koin
        assertNotNull(koin.get<NotesRepository>())
    }
}

// Or avoid the global context entirely:
val koin = koinApplication { modules(notesModule, testOverridesModule) }.koin
```

Unit tests of a ViewModel or repository rarely need DI at all — construct the object with fakes.

The same applies to anything global: `object` caches, top-level `var`s, a fake stored in a
companion object, a database file with a fixed name. Create fresh instances per test, or reset
them in `@AfterTest`. As a quick diagnostic on the JVM, running each test class in its own JVM
(`tasks.withType<Test>().configureEach { forkEvery = 1 }`, temporarily) makes a shared-state
flake disappear — which confirms the class of bug, not the fix.

## 7. Randomness and generated IDs

```kotlin
class NoteIdGenerator(private val random: Random) {
    fun next(): String = "note-" + random.nextLong().toULong().toString(16)
}

// test: deterministic
val ids = NoteIdGenerator(Random(seed = 42))
```

Assert on behaviour (uniqueness, format) or on values produced by the seeded generator — never on
`Random.Default` output.

## 8. iOS / Kotlin/Native specifics

- **Same tests, different runtime.** `commonTest` runs on Kotlin/Native for iOS targets: real
  threads, a different GC, and a real main queue. A test that is stable on the JVM can still flake
  there — always loop the iOS task too.
- **In-process repetition.** The test binary accepts `--ktest_repeat=N` and `--ktest_filter=…`
  (see `--help`), which repeats tests in one process. Use it to expose state that leaks between
  runs; Gradle loops start a fresh process each time and hide that.
- **Release timing of Swift/ObjC objects.** Objects that crossed into Kotlin are freed only after a
  Kotlin GC, and their `deinit` runs after that cycle. Do not assert that something was released
  "by now"; assert that the cleanup method was called.
- **Simulator state persists.** Files and `NSUserDefaults` written by one run can still be there in
  the next run on the same simulator. Use a unique directory or defaults suite per test and delete
  it in `@AfterTest`.
- **Environment.** Variables prefixed `SIMCTL_CHILD_` are passed to the process started by
  `xcrun simctl spawn`, e.g. `SIMCTL_CHILD_TZ=Asia/Tokyo` to try another time zone.

## 9. Finding the test that pollutes another

1. Get the order tests ran in from the failing CI run (JUnit XML timestamps or the log).
2. Run the flaky test together with the first half of the tests that ran before it. Fails → the
   polluter is in that half; passes → the other half.
3. Repeat until one test remains. Look at what it leaves behind: `Dispatchers.Main`, Koin, an
   `object`, a file, a static fake.

```bash
./gradlew :shared:testDebugUnitTest \
  --tests 'com.example.app.orders.OrdersRepositoryTest' \
  --tests 'com.example.app.notes.NotesViewModelTest' --rerun
```

Fix the polluter (it should clean up) **and** make the victim independent of it.
