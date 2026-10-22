# Worked example — a note editor screen

A complete screen in the MVI shape: load an existing note or start a new one, edit title and body,
save, and confirm before discarding unsaved changes. Package root `com.example.app`, feature
`notes`. Adapt names, packages, DI and components to the project (Step 0 in `SKILL.md`).

Placeholders used below — replace them with the project's own:

- `ApiResult<T>` — the project's result wrapper.
- `AppTheme.spacing.*` — the project's spacing tokens; `AppButton` — its primary button.
- `Res.string.*` — Compose Multiplatform string resources (`composeResources/values/strings.xml`).
- `MviViewModel` and `CollectEffects` — from `mvi-viewmodel-base.md`.

Contents

1. [File layout](#1-file-layout)
2. [Domain contract](#2-domain-contract)
3. [UiState, Action, Effect](#3-uistate-action-effect)
4. [ViewModel](#4-viewmodel)
5. [Screen, view and effect handler](#5-screen-view-and-effect-handler)
6. [TestTags](#6-testtags)
7. [Previews](#7-previews)
8. [Koin module and route](#8-koin-module-and-route)
9. [Fake repository](#9-fake-repository)
10. [ViewModel tests](#10-viewmodel-tests)

## 1. File layout

```
feature/notes/src/commonMain/kotlin/com/example/app/notes/
  domain/Note.kt  domain/NotesRepository.kt
  editor/NoteEditorUiState.kt  editor/NoteEditorAction.kt  editor/NoteEditorEffect.kt
  editor/NoteEditorViewModel.kt
  editor/NoteEditorScreen.kt   editor/NoteEditorTestTags.kt
  navigation/NotesRoutes.kt    di/NotesModule.kt
feature/notes/src/commonTest/kotlin/com/example/app/notes/
  editor/NoteEditorViewModelTest.kt  fakes/FakeNotesRepository.kt
```

If the project splits Compose-free logic from Compose UI into separate modules, the ViewModel and
contract files go in the logic module and the screen/tags in the UI module.

## 2. Domain contract

```kotlin
data class Note(val id: String, val title: String, val body: String)

interface NotesRepository {
    suspend fun getNote(id: String): ApiResult<Note>
    /** Creates when [id] is null, updates otherwise. Main-safe. */
    suspend fun saveNote(id: String?, title: String, body: String): ApiResult<Note>
}

// Only if the project has no wrapper yet.
sealed interface ApiResult<out T> {
    data class Success<T>(val data: T) : ApiResult<T>
    data class Failure(val message: String?, val cause: Throwable? = null) : ApiResult<Nothing>
}
```

## 3. UiState, Action, Effect

```kotlin
enum class NoteEditorError { LoadFailed, SaveFailed }

data class NoteEditorUiState(
    val title: String = "",
    val body: String = "",
    val savedTitle: String = "",
    val savedBody: String = "",
    val isLoading: Boolean = false,
    val isSaving: Boolean = false,
    val error: NoteEditorError? = null,
    val isDiscardDialogVisible: Boolean = false,
) {
    val hasUnsavedChanges: Boolean get() = title != savedTitle || body != savedBody
    val canSave: Boolean get() = !isLoading && !isSaving && title.isNotBlank() && hasUnsavedChanges
}

sealed interface NoteEditorAction {
    data class TitleChanged(val value: String) : NoteEditorAction
    data class BodyChanged(val value: String) : NoteEditorAction
    data object SaveClicked : NoteEditorAction
    data object BackClicked : NoteEditorAction
    data object DiscardConfirmed : NoteEditorAction
    data object DiscardDismissed : NoteEditorAction
    data object RetryLoadClicked : NoteEditorAction
}

sealed interface NoteEditorEffect {
    data object NavigateBack : NoteEditorEffect
    data class NoteSaved(val noteId: String) : NoteEditorEffect
}
```

The error is an enum, not a resolved string: the ViewModel stays locale-independent and tests do
not need resources. The view maps it to text.

## 4. ViewModel

```kotlin
class NoteEditorViewModel(
    private val noteId: String?,
    private val notesRepository: NotesRepository,
) : MviViewModel<NoteEditorUiState, NoteEditorEffect>(
    initialState = NoteEditorUiState(isLoading = noteId != null),
) {

    init {
        if (noteId != null) loadNote(noteId)
    }

    fun onAction(action: NoteEditorAction) {
        when (action) {
            is NoteEditorAction.TitleChanged -> updateState { copy(title = action.value) }
            is NoteEditorAction.BodyChanged -> updateState { copy(body = action.value) }
            NoteEditorAction.SaveClicked -> save()
            NoteEditorAction.BackClicked ->
                if (currentState.hasUnsavedChanges) {
                    updateState { copy(isDiscardDialogVisible = true) }
                } else {
                    sendEffect(NoteEditorEffect.NavigateBack)
                }
            NoteEditorAction.DiscardConfirmed -> {
                updateState { copy(isDiscardDialogVisible = false) }
                sendEffect(NoteEditorEffect.NavigateBack)
            }
            NoteEditorAction.DiscardDismissed -> updateState { copy(isDiscardDialogVisible = false) }
            NoteEditorAction.RetryLoadClicked -> noteId?.let(::loadNote)
        }
    }

    private fun loadNote(id: String) {
        updateState { copy(isLoading = true, error = null) }
        viewModelScope.launch {
            when (val result = notesRepository.getNote(id)) {
                is ApiResult.Success -> updateState {
                    copy(
                        title = result.data.title, body = result.data.body,
                        savedTitle = result.data.title, savedBody = result.data.body,
                        isLoading = false,
                    )
                }
                is ApiResult.Failure -> updateState { copy(isLoading = false, error = NoteEditorError.LoadFailed) }
            }
        }
    }

    private fun save() {
        val draft = currentState            // snapshot before suspending
        if (!draft.canSave) return
        updateState { copy(isSaving = true, error = null) }
        viewModelScope.launch {
            when (val result = notesRepository.saveNote(id = noteId, title = draft.title.trim(), body = draft.body)) {
                is ApiResult.Success -> {
                    updateState { copy(isSaving = false, savedTitle = draft.title, savedBody = draft.body) }
                    sendEffect(NoteEditorEffect.NoteSaved(noteId = result.data.id))
                }
                is ApiResult.Failure -> updateState { copy(isSaving = false, error = NoteEditorError.SaveFailed) }
            }
        }
    }
}
```

Imports needed: `androidx.lifecycle.viewModelScope`, `kotlinx.coroutines.launch`. No Compose imports.

## 5. Screen, view and effect handler

```kotlin
@Composable
fun NoteEditorScreen(
    onNavigateBack: () -> Unit,
    onNoteSaved: (noteId: String) -> Unit,
    viewModel: NoteEditorViewModel,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    NoteEditorView(state = state, onAction = viewModel::onAction)

    // The only place navigation callbacks are invoked.
    CollectEffects(viewModel.effects) { effect ->
        when (effect) {
            NoteEditorEffect.NavigateBack -> onNavigateBack()
            is NoteEditorEffect.NoteSaved -> onNoteSaved(effect.noteId)
        }
    }
    // System back / iOS swipe interception for unsaved changes: see the
    // compose-multiplatform-navigation skill (back handling) and send
    // NoteEditorAction.BackClicked from it.
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NoteEditorView(
    state: NoteEditorUiState,
    onAction: (NoteEditorAction) -> Unit,
    modifier: Modifier = Modifier,
) {
    Scaffold(
        modifier = modifier.testTag(NoteEditorTestTags.SCREEN),
        topBar = {
            TopAppBar(
                title = { Text(stringResource(Res.string.note_editor_title)) },
                navigationIcon = {
                    IconButton(
                        onClick = { onAction(NoteEditorAction.BackClicked) },
                        modifier = Modifier.testTag(NoteEditorTestTags.BACK_BUTTON),
                    ) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(Res.string.common_navigate_back),
                        )
                    }
                },
            )
        },
    ) { innerPadding ->
        when {
            state.isLoading -> Box(Modifier.fillMaxSize().padding(innerPadding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.testTag(NoteEditorTestTags.LOADING))
            }
            state.error == NoteEditorError.LoadFailed -> LoadError(
                onRetry = { onAction(NoteEditorAction.RetryLoadClicked) },
                modifier = Modifier.padding(innerPadding),
            )
            else -> Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding)
                    .padding(AppTheme.spacing.md),
                verticalArrangement = Arrangement.spacedBy(AppTheme.spacing.sm),
            ) {
                OutlinedTextField(
                    value = state.title,
                    onValueChange = { onAction(NoteEditorAction.TitleChanged(it)) },
                    label = { Text(stringResource(Res.string.note_editor_title_label)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().testTag(NoteEditorTestTags.TITLE_FIELD),
                )
                OutlinedTextField(
                    value = state.body,
                    onValueChange = { onAction(NoteEditorAction.BodyChanged(it)) },
                    label = { Text(stringResource(Res.string.note_editor_body_label)) },
                    modifier = Modifier.fillMaxWidth().weight(1f).testTag(NoteEditorTestTags.BODY_FIELD),
                )
                if (state.error == NoteEditorError.SaveFailed) {
                    Text(
                        text = stringResource(Res.string.note_editor_save_failed),
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.testTag(NoteEditorTestTags.SAVE_ERROR),
                    )
                }
                AppButton(
                    text = stringResource(Res.string.note_editor_save),
                    onClick = { onAction(NoteEditorAction.SaveClicked) },
                    enabled = state.canSave,
                    loading = state.isSaving,
                    modifier = Modifier.fillMaxWidth().testTag(NoteEditorTestTags.SAVE_BUTTON),
                )
            }
        }
    }

    if (state.isDiscardDialogVisible) {
        AlertDialog(
            onDismissRequest = { onAction(NoteEditorAction.DiscardDismissed) },
            title = { Text(stringResource(Res.string.note_editor_discard_title)) },
            confirmButton = {
                TextButton(
                    onClick = { onAction(NoteEditorAction.DiscardConfirmed) },
                    modifier = Modifier.testTag(NoteEditorTestTags.DISCARD_CONFIRM),
                ) { Text(stringResource(Res.string.note_editor_discard_confirm)) }
            },
            dismissButton = {
                TextButton(
                    onClick = { onAction(NoteEditorAction.DiscardDismissed) },
                    modifier = Modifier.testTag(NoteEditorTestTags.DISCARD_CANCEL),
                ) { Text(stringResource(Res.string.note_editor_discard_cancel)) }
            },
            modifier = Modifier.testTag(NoteEditorTestTags.DISCARD_DIALOG),
        )
    }
}
```

`LoadError` is a small private composable (message + retry button tagged
`NoteEditorTestTags.RETRY_BUTTON`). The dialog is driven by state, so it survives rotation.

## 6. TestTags

```kotlin
object NoteEditorTestTags {
    const val SCREEN = "note_editor_screen"
    const val BACK_BUTTON = "note_editor_back_button"
    const val LOADING = "note_editor_loading"
    const val RETRY_BUTTON = "note_editor_retry_button"
    const val TITLE_FIELD = "note_editor_title_field"
    const val BODY_FIELD = "note_editor_body_field"
    const val SAVE_BUTTON = "note_editor_save_button"
    const val SAVE_ERROR = "note_editor_save_error"
    const val DISCARD_DIALOG = "note_editor_discard_dialog"
    const val DISCARD_CONFIRM = "note_editor_discard_confirm"
    const val DISCARD_CANCEL = "note_editor_discard_cancel"
}
```

Tags are English-free locators and never change with copy. Spoken labels come from string
resources (`contentDescription`), separately.

## 7. Previews

```kotlin
import androidx.compose.ui.tooling.preview.Preview   // CMP 1.10+; older: org.jetbrains.compose.ui.tooling.preview.Preview

@Preview
@Composable
private fun NoteEditorEmptyPreview() {
    AppTheme { NoteEditorView(state = NoteEditorUiState(), onAction = {}) }
}

@Preview
@Composable
private fun NoteEditorSavingPreview() {
    AppTheme {
        NoteEditorView(
            state = NoteEditorUiState(title = "Groceries", body = "Milk, eggs", isSaving = true),
            onAction = {},
        )
    }
}

@Preview
@Composable
private fun NoteEditorDiscardDialogPreview() {
    AppTheme {
        NoteEditorView(
            state = NoteEditorUiState(title = "Draft", isDiscardDialogVisible = true),
            onAction = {},
        )
    }
}
```

Add a dark-theme variant by calling the theme with its dark flag (for example
`AppTheme(darkTheme = true)`), since Android `uiMode` constants are not available in `commonMain`.

## 8. Koin module and route

```kotlin
// navigation/NotesRoutes.kt
@Serializable
data class NoteEditorRoute(val noteId: String? = null)

// di/NotesModule.kt
val notesModule = module {
    viewModel { params ->
        NoteEditorViewModel(noteId = params.getOrNull<String>(), notesRepository = get())
    }
}

// navigation/NotesGraph.kt
fun NavGraphBuilder.noteEditorDestination(navController: NavController) {
    composable<NoteEditorRoute> { backStackEntry ->
        val route = backStackEntry.toRoute<NoteEditorRoute>()
        NoteEditorScreen(
            viewModel = koinViewModel(parameters = { parametersOf(route.noteId) }),
            onNavigateBack = { navController.popBackStack() },
            onNoteSaved = { navController.popBackStack() },
        )
    }
}
```

Imports: `org.koin.core.module.dsl.viewModel`, `org.koin.compose.viewmodel.koinViewModel`,
`org.koin.core.parameter.parametersOf`, `androidx.navigation.toRoute`,
`androidx.navigation.compose.composable`, `kotlinx.serialization.Serializable`.

Without Koin: `viewModel { NoteEditorViewModel(noteId = route.noteId, notesRepository = repository) }`
from `androidx.lifecycle.viewmodel.compose.viewModel`.

## 9. Fake repository

```kotlin
class FakeNotesRepository : NotesRepository {
    val notes = mutableMapOf<String, Note>()
    var nextResultFailure: String? = null
    val saveCalls = mutableListOf<Triple<String?, String, String>>()

    override suspend fun getNote(id: String): ApiResult<Note> =
        failureOrNull() ?: notes[id]?.let { ApiResult.Success(it) } ?: ApiResult.Failure("not found")

    override suspend fun saveNote(id: String?, title: String, body: String): ApiResult<Note> {
        saveCalls += Triple(id, title, body)
        failureOrNull()?.let { return it }
        val note = Note(id = id ?: "note-${notes.size + 1}", title = title, body = body)
        notes[note.id] = note
        return ApiResult.Success(note)
    }

    private fun failureOrNull(): ApiResult.Failure? =
        nextResultFailure?.let { message -> nextResultFailure = null; ApiResult.Failure(message) }
}
```

## 10. ViewModel tests

```kotlin
@OptIn(ExperimentalCoroutinesApi::class)
class NoteEditorViewModelTest {

    private val repository = FakeNotesRepository()

    @BeforeTest
    fun setUp() {
        Dispatchers.setMain(StandardTestDispatcher())
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun should_emitNoteSaved_and_markClean_when_saveSucceeds() = runTest {
        val viewModel = NoteEditorViewModel(noteId = null, notesRepository = repository)
        val effects = mutableListOf<NoteEditorEffect>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { viewModel.effects.toList(effects) }

        viewModel.onAction(NoteEditorAction.TitleChanged("Groceries"))
        viewModel.onAction(NoteEditorAction.SaveClicked)
        advanceUntilIdle()

        assertFalse(viewModel.state.value.isSaving)
        assertFalse(viewModel.state.value.hasUnsavedChanges)
        assertEquals(listOf<NoteEditorEffect>(NoteEditorEffect.NoteSaved(noteId = "note-1")), effects)
    }

    @Test
    fun should_showSaveError_and_emitNothing_when_saveFails() = runTest {
        repository.nextResultFailure = "offline"
        val viewModel = NoteEditorViewModel(noteId = null, notesRepository = repository)
        val effects = mutableListOf<NoteEditorEffect>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { viewModel.effects.toList(effects) }

        viewModel.onAction(NoteEditorAction.TitleChanged("Groceries"))
        viewModel.onAction(NoteEditorAction.SaveClicked)
        advanceUntilIdle()

        assertEquals(NoteEditorError.SaveFailed, viewModel.state.value.error)
        assertTrue(effects.isEmpty())
    }

    @Test
    fun should_saveSnapshot_when_textChangesWhileSaving() = runTest {
        val viewModel = NoteEditorViewModel(noteId = null, notesRepository = repository)

        viewModel.onAction(NoteEditorAction.TitleChanged("First"))
        viewModel.onAction(NoteEditorAction.SaveClicked)
        viewModel.onAction(NoteEditorAction.TitleChanged("First and more"))
        advanceUntilIdle()

        assertEquals("First", repository.saveCalls.single().second)
        assertTrue(viewModel.state.value.hasUnsavedChanges)
    }

    @Test
    fun should_showDiscardDialog_when_backClickedWithUnsavedChanges() = runTest {
        val viewModel = NoteEditorViewModel(noteId = null, notesRepository = repository)
        val effects = mutableListOf<NoteEditorEffect>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { viewModel.effects.toList(effects) }

        viewModel.onAction(NoteEditorAction.TitleChanged("Draft"))
        viewModel.onAction(NoteEditorAction.BackClicked)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.isDiscardDialogVisible)
        assertTrue(effects.isEmpty())
    }

    @Test
    fun should_populateFields_when_existingNoteLoads() = runTest {
        repository.notes["n-7"] = Note(id = "n-7", title = "Trip", body = "Pack")

        val viewModel = NoteEditorViewModel(noteId = "n-7", notesRepository = repository)
        advanceUntilIdle()

        val state = viewModel.state.value
        assertEquals("Trip", state.title)
        assertFalse(state.isLoading)
        assertFalse(state.hasUnsavedChanges)
    }
}
```

Imports: `kotlin.test.*`, `kotlinx.coroutines.Dispatchers`, `kotlinx.coroutines.ExperimentalCoroutinesApi`,
`kotlinx.coroutines.flow.toList`, `kotlinx.coroutines.launch`, `kotlinx.coroutines.test.*`.

Why it is deterministic:

- `Dispatchers.setMain(StandardTestDispatcher())` makes `viewModelScope` run on the test scheduler,
  and `runTest` picks up that scheduler from `Dispatchers.Main`.
- The effect collector starts first, on an unconfined test dispatcher, so it is subscribed before
  any action runs.
- `advanceUntilIdle()` drains all queued coroutines; no `delay` or real time is involved.

With Turbine, replace the manual collector with
`viewModel.effects.test { …act…; assertEquals(expected, awaitItem()) }`.
