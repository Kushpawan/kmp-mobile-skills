# Playbooks for hard coverage targets

- [A. Big ViewModels](#a-big-viewmodels)
- [B. Top-level `*Kt` files](#b-top-level-kt-files)
- [C. Repository with an API and a local store](#c-repository-with-an-api-and-a-local-store)
- [D. Small use cases](#d-small-use-cases)
- [E. Mappers with branches](#e-mappers-with-branches)
- [F. Classes with no seam](#f-classes-with-no-seam)

The examples use a notes domain and kotlin.test. Write them in the project's own idiom: its base
ViewModel, result type, fakes and assertion style.

## A. Big ViewModels

These are the classes a backfill most often skips: 200+ lines, five or more collaborators, work
launched from `init`. They usually hold the biggest single gap, so they are worth the effort.

1. **Pick the dispatcher on purpose.** `UnconfinedTestDispatcher` runs launched work eagerly, so
   `state.value` is settled when the action returns. That suits a ViewModel that loads in `init`.
   `StandardTestDispatcher` queues work until you call `runCurrent()` / `advanceUntilIdle()`, which lets
   you assert intermediate states. Install either with `Dispatchers.setMain(...)` in `@BeforeTest`,
   and remove it with `Dispatchers.resetMain()` in `@AfterTest`.
2. **One fake per collaborator, reused across files.** Search `commonTest` for `Fake<Type>` or
   `*Fakes.kt` before writing a new one. Production in-memory implementations
   (`InMemoryNotesStore`) are fakes too.
3. **Three phases per action:** seed the fakes, fire the action, then observe the state, the fake call
   counts and arguments, and every emitted effect.
4. **One test per `when` arm** of each reducer. Many missed branches usually means "source state x
   action" combinations: 3 actions x 4 states = 12 small tests.
5. **Ticker or polling loops** (`while (isActive) { delay(1_000) }`): advance virtual time with
   `advanceTimeBy(1_000)`, then `runCurrent()`, and assert one tick. Never call `advanceUntilIdle()`
   while such a loop runs: the loop always schedules the next tick, so the call never returns.
6. **Global singletons (analytics, logger).** If the singleton is a no-op until configured, leave it
   unconfigured in tests. If it is not, the class needs an injected interface (see F). Do not try to
   fake a Kotlin `object`.

```kotlin
@OptIn(ExperimentalCoroutinesApi::class)
class NotesViewModelLoadTest {
    private val repository = FakeNotesRepository()

    @BeforeTest fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher())
    @AfterTest fun tearDown() = Dispatchers.resetMain()

    @Test
    fun should_showEmptyState_when_repositoryReturnsNoNotes() = runTest {
        repository.notes = emptyList()

        val viewModel = NotesViewModel(repository)        // loads in init

        assertEquals(NotesUiState(isLoading = false, notes = emptyList(), isEmpty = true), viewModel.state.value)
        assertEquals(1, repository.loadCalls)
    }
}
```

## B. Top-level `*Kt` files

Kotlin compiles top-level functions in `NotesReducer.kt` into a class `NotesReducerKt`. These are
usually pure functions over data classes, so they are the cheapest coverage in the report.

- Put the test in the **same package**. `internal` functions are visible to `commonTest` of the same
  module.
- Write one tiny test per `when` arm or `if` branch. No fakes needed.

```kotlin
class NotesReducerTest {
    @Test
    fun should_removeNote_when_deleteConfirmed() {
        val before = NotesUiState(notes = listOf(note("1"), note("2")))
        val after = reduce(before, NotesEvent.DeleteConfirmed(id = "1"))
        assertEquals(listOf(note("2")), after.notes)
    }
}
```

## C. Repository with an API and a local store

1. **Fake the remote API** behind its interface, with a settable next result and call counters. When
   the repository talks to a Ktor `HttpClient` directly, build the client on a Ktor `MockEngine`
   instead.
2. **Use an in-memory store.** Reuse a production in-memory implementation if one exists; otherwise
   hand-write a fake DAO. A real Room in-memory database needs a per-platform builder (Android needs a
   `Context`), so in `commonTest` a fake DAO is usually simpler.
3. **Cover every arm of the result type** for each remote call: success, each error kind, and a thrown
   exception or timeout when the repository catches them.
4. **Assert the side effect on the store** by reading it back, not only the return value.

```kotlin
@Test
fun should_keepCachedNotes_when_refreshFails() = runTest {
    val store = InMemoryNotesStore().apply { replaceAll(listOf(note("1"))) }
    val api = FakeNotesApi().apply { nextResult = ApiResult.Failure(code = 503) }
    val repository = NotesRepositoryImpl(api, store)

    val result = repository.refresh()

    assertIs<RefreshResult.Offline>(result)
    assertEquals(listOf(note("1")), store.all())
}
```

## D. Small use cases

Pass-through use cases of 20 lines or fewer, with 0 or 1 branch, go into **one** grouped test file
(`SmallNoteUseCasesTest.kt`), with one or two tests each. Five near-empty files with identical
imports add noise and no extra safety.

## E. Mappers with branches

Mappers that resolve nullable DTO fields, unknown enum values or fallbacks hide many branches. Use a
table-driven test so every row is a visible case:

```kotlin
@Test
fun should_mapEveryPriorityValue_when_dtoHasRawString() {
    val cases = mapOf("high" to Priority.High, "LOW" to Priority.Low, "urgent!" to Priority.Normal, null to Priority.Normal)
    for ((raw, expected) in cases) {
        assertEquals(expected, NoteDto(id = "1", priority = raw).toDomain().priority, "raw=$raw")
    }
}
```

## F. Classes with no seam

Some classes cannot be tested without changing production code. Examples: a hard-coded
`Dispatchers.IO`, a direct `Clock.System.now()`, `Random`, a platform singleton, or an `object`
dependency. The fix is a seam: inject a `DispatcherProvider`, a `Clock`, or an interface. That is a
**production change**, so ask the user first. Without approval, defer the class with the reason
`needs-seam`, and name the seam it needs.
