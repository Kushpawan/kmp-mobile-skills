# Worked example: testing an MVI ViewModel in commonTest

- [The production code](#the-production-code)
- [Test doubles](#test-doubles)
- [The test class](#the-test-class)
- [The same assertions with Turbine](#the-same-assertions-with-turbine)
- [Why each choice](#why-each-choice)

One complete feature: a notes list that loads, deletes and opens notes. The ViewModel exposes
durable **state** (`StateFlow`) and one-shot **effects** (navigation, messages). Every test asserts
both. If the project has its own base class (an `MviViewModel<State, Effect>` with `updateState {}` /
`postEffect()`), keep the same structure and call its API instead.

## The production code

```kotlin
// commonMain - com/example/app/core/DispatcherProvider.kt
package com.example.app.core

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.IO

/** Injected instead of calling Dispatchers.IO directly, so tests can swap in a TestDispatcher. */
interface DispatcherProvider {
    val main: CoroutineDispatcher
    val io: CoroutineDispatcher
    val default: CoroutineDispatcher
}

object DefaultDispatcherProvider : DispatcherProvider {
    override val main: CoroutineDispatcher = Dispatchers.Main
    override val io: CoroutineDispatcher = Dispatchers.IO       // kotlinx.coroutines.IO import is needed in commonMain
    override val default: CoroutineDispatcher = Dispatchers.Default
}
```

```kotlin
// commonMain - com/example/app/notes/Notes.kt
package com.example.app.notes

data class Note(val id: String, val title: String)

sealed interface NotesResult {
    data class Success(val notes: List<Note>) : NotesResult
    data class Failure(val message: String) : NotesResult
}

interface NotesRepository {
    suspend fun loadNotes(): NotesResult
    suspend fun deleteNote(id: String): Boolean
}

data class NotesUiState(
    val isLoading: Boolean = false,
    val notes: List<Note> = emptyList(),
    val errorMessage: String? = null,
) {
    // Derived in the state, not in the Composable, so it is unit-testable.
    val isEmpty: Boolean get() = !isLoading && errorMessage == null && notes.isEmpty()
}

sealed interface NotesAction {
    data object Refresh : NotesAction
    data class Delete(val id: String) : NotesAction
    data class Open(val id: String) : NotesAction
}

sealed interface NotesEffect {
    data class NavigateToEditor(val noteId: String) : NotesEffect
    data class ShowMessage(val text: String) : NotesEffect
}
```

```kotlin
// commonMain - com/example/app/notes/NotesViewModel.kt
package com.example.app.notes

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.app.core.DispatcherProvider
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class NotesViewModel(
    private val notesRepository: NotesRepository,
    private val dispatchers: DispatcherProvider,
) : ViewModel() {

    private val _state = MutableStateFlow(NotesUiState())
    val state: StateFlow<NotesUiState> = _state.asStateFlow()

    private val _effects = Channel<NotesEffect>(Channel.BUFFERED)
    val effects: Flow<NotesEffect> = _effects.receiveAsFlow()

    fun onAction(action: NotesAction) {
        when (action) {
            NotesAction.Refresh -> refresh()
            is NotesAction.Delete -> delete(action.id)
            is NotesAction.Open -> viewModelScope.launch { _effects.send(NotesEffect.NavigateToEditor(action.id)) }
        }
    }

    private fun refresh() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, errorMessage = null) }
            val result = withContext(dispatchers.io) { notesRepository.loadNotes() }
            _state.update {
                when (result) {
                    is NotesResult.Success -> it.copy(isLoading = false, notes = result.notes)
                    is NotesResult.Failure -> it.copy(isLoading = false, errorMessage = result.message)
                }
            }
        }
    }

    private fun delete(id: String) {
        viewModelScope.launch {
            val deleted = withContext(dispatchers.io) { notesRepository.deleteNote(id) }
            if (deleted) {
                _state.update { s -> s.copy(notes = s.notes.filterNot { it.id == id }) }
            } else {
                _effects.send(NotesEffect.ShowMessage("Could not delete the note"))
            }
        }
    }
}
```

## Test doubles

```kotlin
// commonTest - com/example/app/core/TestDispatcherProvider.kt
package com.example.app.core

import kotlinx.coroutines.test.TestDispatcher

class TestDispatcherProvider(dispatcher: TestDispatcher) : DispatcherProvider {
    override val main = dispatcher
    override val io = dispatcher
    override val default = dispatcher
}
```

```kotlin
// commonTest - com/example/app/notes/FakeNotesRepository.kt
package com.example.app.notes

import kotlinx.coroutines.CompletableDeferred

/** Hand-written fake: settable results, call counters, recorded arguments. Runs on every target. */
class FakeNotesRepository : NotesRepository {
    var notes: List<Note> = emptyList()
    var loadResult: NotesResult? = null              // null -> Success(notes)
    var deleteSucceeds: Boolean = true
    var loadGate: CompletableDeferred<Unit>? = null  // set it to hold a load "in flight"

    var loadCalls = 0
        private set
    val deletedIds = mutableListOf<String>()

    override suspend fun loadNotes(): NotesResult {
        loadCalls++
        loadGate?.await()
        return loadResult ?: NotesResult.Success(notes)
    }

    override suspend fun deleteNote(id: String): Boolean {
        deletedIds += id
        return deleteSucceeds
    }
}

fun note(id: String) = Note(id = id, title = "Note $id")
```

## The test class

```kotlin
// commonTest - com/example/app/notes/NotesViewModelTest.kt
package com.example.app.notes

import com.example.app.core.TestDispatcherProvider
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class NotesViewModelTest {

    // One scheduler for everything: Main, the injected dispatchers, and runTest.
    private val testDispatcher = StandardTestDispatcher()
    private val notesRepository = FakeNotesRepository()

    @BeforeTest
    fun setUp() {
        // viewModelScope runs on Dispatchers.Main. JVM tests have no Main, and an iOS test
        // binary does not drain the main queue, so replace it in every test.
        Dispatchers.setMain(testDispatcher)
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createViewModel() = NotesViewModel(
        notesRepository = notesRepository,
        dispatchers = TestDispatcherProvider(testDispatcher),
    )

    /** Collects effects eagerly, BEFORE the action under test, and stops when the test ends. */
    private fun TestScope.collectEffects(viewModel: NotesViewModel): List<NotesEffect> {
        val effects = mutableListOf<NotesEffect>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { viewModel.effects.toList(effects) }
        return effects
    }

    @Test
    fun should_showNotes_when_refreshSucceeds() = runTest {
        // Arrange
        notesRepository.notes = listOf(note("1"), note("2"))
        val viewModel = createViewModel()
        val effects = collectEffects(viewModel)

        // Act
        viewModel.onAction(NotesAction.Refresh)
        advanceUntilIdle()

        // Assert - state AND effects
        assertEquals(NotesUiState(notes = listOf(note("1"), note("2"))), viewModel.state.value)
        assertEquals(emptyList(), effects)
        assertEquals(1, notesRepository.loadCalls)
    }

    @Test
    fun should_showLoading_when_refreshIsInFlight() = runTest {
        notesRepository.loadGate = CompletableDeferred()
        val viewModel = createViewModel()

        viewModel.onAction(NotesAction.Refresh)
        runCurrent()                                   // run what is ready; the load is parked on the gate

        assertTrue(viewModel.state.value.isLoading)

        notesRepository.loadGate?.complete(Unit)
        advanceUntilIdle()

        assertFalse(viewModel.state.value.isLoading)
    }

    @Test
    fun should_showErrorAndNoEffect_when_refreshFails() = runTest {
        notesRepository.loadResult = NotesResult.Failure(message = "offline")
        val viewModel = createViewModel()
        val effects = collectEffects(viewModel)

        viewModel.onAction(NotesAction.Refresh)
        advanceUntilIdle()

        assertEquals(NotesUiState(errorMessage = "offline"), viewModel.state.value)
        assertFalse(viewModel.state.value.isEmpty)
        assertEquals(emptyList(), effects)
    }

    @Test
    fun should_removeNote_when_deleteSucceeds() = runTest {
        notesRepository.notes = listOf(note("1"), note("2"))
        val viewModel = createViewModel()
        viewModel.onAction(NotesAction.Refresh)
        advanceUntilIdle()
        val effects = collectEffects(viewModel)

        viewModel.onAction(NotesAction.Delete(id = "1"))
        advanceUntilIdle()

        assertEquals(listOf(note("2")), viewModel.state.value.notes)
        assertEquals(listOf("1"), notesRepository.deletedIds)
        assertEquals(emptyList(), effects)
    }

    @Test
    fun should_keepNoteAndShowMessage_when_deleteFails() = runTest {
        notesRepository.notes = listOf(note("1"))
        notesRepository.deleteSucceeds = false
        val viewModel = createViewModel()
        viewModel.onAction(NotesAction.Refresh)
        advanceUntilIdle()
        val effects = collectEffects(viewModel)

        viewModel.onAction(NotesAction.Delete(id = "1"))
        advanceUntilIdle()

        assertEquals(listOf(note("1")), viewModel.state.value.notes)
        assertEquals(listOf<NotesEffect>(NotesEffect.ShowMessage("Could not delete the note")), effects)
    }

    @Test
    fun should_navigateToEditor_when_noteOpened() = runTest {
        val viewModel = createViewModel()
        val effects = collectEffects(viewModel)

        viewModel.onAction(NotesAction.Open(id = "42"))
        advanceUntilIdle()

        assertEquals(listOf<NotesEffect>(NotesEffect.NavigateToEditor(noteId = "42")), effects)
        assertEquals(NotesUiState(), viewModel.state.value)   // opening must not touch state
    }

    @Test
    fun should_reportEmpty_when_loadedListIsEmpty() = runTest {
        val viewModel = createViewModel()

        viewModel.onAction(NotesAction.Refresh)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.isEmpty)
    }
}
```

## The same assertions with Turbine

[Turbine](https://github.com/cashapp/turbine) collects a flow and lets you await each item. It times
out (3 s of wall-clock time by default) instead of hanging. Use it when the project already depends
on it.

```kotlin
// version catalog: turbine = { module = "app.cash.turbine:turbine", version.ref = "turbine" }
// commonTest.dependencies { implementation(libs.turbine) }
import app.cash.turbine.test
import app.cash.turbine.turbineScope

@Test
fun should_emitLoadingThenNotes_when_refreshed() = runTest {
    notesRepository.notes = listOf(note("1"))
    val viewModel = createViewModel()

    viewModel.state.test {
        assertEquals(NotesUiState(), awaitItem())
        viewModel.onAction(NotesAction.Refresh)
        assertEquals(NotesUiState(isLoading = true), awaitItem())
        assertEquals(NotesUiState(notes = listOf(note("1"))), awaitItem())
    }
}

@Test
fun should_emitMessage_when_deleteFails_turbine() = runTest {
    notesRepository.deleteSucceeds = false
    val viewModel = createViewModel()

    turbineScope {
        val effects = viewModel.effects.testIn(backgroundScope)   // subscribed before the action
        viewModel.onAction(NotesAction.Delete(id = "1"))
        assertEquals(NotesEffect.ShowMessage("Could not delete the note"), effects.awaitItem())
        effects.cancelAndIgnoreRemainingEvents()
    }
    assertEquals(NotesUiState(), viewModel.state.value)
}
```

`test {}` fails the test if events are left unconsumed at the end. Call
`cancelAndIgnoreRemainingEvents()` only when the leftovers really do not matter.

## Why each choice

| Choice | Reason |
|---|---|
| `Dispatchers.setMain` in `@BeforeTest`, `resetMain` in `@AfterTest` | `viewModelScope` uses `Dispatchers.Main`. JVM host tests fail with "Module with the Main dispatcher is missing" (or, on Android unit tests, "Method getMainLooper in android.os.Looper not mocked"). |
| One `StandardTestDispatcher` shared by Main, the injected provider and `runTest` | `runTest` picks up the scheduler of a `TestDispatcher` installed as Main. One scheduler means `advanceUntilIdle()` drives every coroutine, and `delay` uses virtual time. |
| `runCurrent()` versus `advanceUntilIdle()` | `runCurrent()` runs only the tasks that are due now, which is how you observe an in-flight state. `advanceUntilIdle()` runs everything, including virtual delays. |
| Effects collected in `backgroundScope` with `UnconfinedTestDispatcher(testScheduler)` | The collector is subscribed before the action and receives each effect immediately. `backgroundScope` is cancelled when the test ends, so the endless collection does not hang `runTest`. With a `MutableSharedFlow(replay = 0)`, an effect emitted before anyone collects is lost for good. |
| A `CompletableDeferred` gate in the fake | The only reliable way to assert a loading state. `StateFlow` conflates, so a fast fake can move from loading to loaded before anyone reads it. |
| Hand-written fake | Runs unchanged on JVM, Android and Kotlin/Native. JVM mocking libraries do not. |
| Equality on the whole `UiState` | One assertion catches unexpected changes to fields you did not think about. |
