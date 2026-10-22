---
name: compose-multiplatform-screen
description: Use when adding or extending a Compose Multiplatform screen in commonMain — a new screen, ViewModel, UiState, actions/intents, one-shot side effects (navigate, snackbar), MVI or MVVM presentation, collectAsStateWithLifecycle, koinViewModel, testTag objects, @Preview of screen states, or ViewModel unit tests. Also for effects lost or delivered twice, state not updating, or navigation fired from a ViewModel.
license: Apache-2.0
compatibility: Kotlin Multiplatform project with Compose Multiplatform 1.8+ and the multiplatform lifecycle-viewmodel / lifecycle-runtime-compose libraries. Commands assume Gradle with Android and iOS targets.
metadata:
  category: ui
  platforms: android, ios
---

# Compose Multiplatform screen

Build every screen as three parts: a **stateful entry** that collects state, a **pure view** that
renders `UiState` and emits actions, and an **effect handler** that is the only place one-shot
events (navigation, snackbars) are executed. The ViewModel owns state and never touches
navigation, `Context` or Compose types.

## When to use

- Adding a new screen to a Compose Multiplatform app (`commonMain`).
- Adding state, actions or side effects to an existing screen.
- Writing or fixing ViewModel tests for a screen.
- Symptoms: a navigation event fires twice or never, state "resets" after rotation, a snackbar is
  lost when the app is backgrounded, a ViewModel holds a `NavController`.

## When not to use

- Graph structure, routes, tabs, deep links, auth gates → `compose-multiplatform-navigation`.
- A reusable button/input/card for the design system → `compose-design-system-component`.
- Implementing a screen from a Figma frame → `figma-to-mobile-ui` (then come back here for the
  ViewModel and tests).
- SwiftUI screens over shared logic → that is iOS-native UI; see Related skills.

## Step 0 — Read the project first

Do not write code until you can answer each question from the repository itself.

1. **Nearest neighbour.** Open the most similar existing screen. A real neighbour beats this
   template; copy its file layout, naming and package structure.
2. **Presentation pattern.** Search for the ViewModel base class
   (`grep -rn "abstract class .*ViewModel" --include=*.kt`). Is there an MVI base
   (state + effect, with helpers such as `setState {}`, `reduce {}` or `postSideEffect()`), a plain `ViewModel` with
   `MutableStateFlow`, or several generations side by side?
3. **Effect idiom.** `Channel(...).receiveAsFlow()`, `MutableSharedFlow`, or events-as-state?
4. **DI.** Koin (`koinViewModel()`), Kodein, manual factories, or `viewModel { }` initializers.
5. **Navigation.** navigation-compose (`NavHostController`), Voyager, Decompose, Navigation 3.
6. **Design system.** Theme object (`AppTheme`, `MaterialTheme` extensions), component prefix,
   token names for colours/spacing/typography.
7. **Tags and tests.** Existing `*TestTags` objects and their string format; test libraries
   (`kotlin.test`, `kotlinx-coroutines-test`, Turbine); test naming convention.
8. **Versions.** `gradle/libs.versions.toml`: Compose Multiplatform version decides the preview
   import (see Quick reference).

**Rules that follow from Step 0**

- **Extending an existing screen: stay in its idiom.** A half-migrated ViewModel (some state in an
  MVI reducer, some in loose `MutableStateFlow`s; some events in a `Channel`, some in a
  `SharedFlow`) is worse than either pattern. Migrate a screen only as its own, reviewed change.
- **New screen:** use the project's newest pattern. With no precedent, use the MVI shape below
  and the small base class in [references/mvi-viewmodel-base.md](references/mvi-viewmodel-base.md).
- Never add a second DI framework, navigation library or effect mechanism.

## Workflow

### 1. Define the contract (UiState, Action, Effect)

```kotlin
data class NoteEditorUiState(
    val title: String = "",
    val body: String = "",
    val isSaving: Boolean = false,
    val error: NoteEditorError? = null,
) {
    // Derived flags live in state, not in the composable: one place to test them.
    val canSave: Boolean get() = !isSaving && title.isNotBlank()
}

sealed interface NoteEditorAction {
    data class TitleChanged(val value: String) : NoteEditorAction
    data object SaveClicked : NoteEditorAction
}

sealed interface NoteEditorEffect {          // one-shot only; durable things belong in state
    data class NoteSaved(val noteId: String) : NoteEditorEffect
}
```

Done when: every value the view renders is a `UiState` property; every user gesture is an
`Action`; every effect is something that must happen **once** (navigate, show a transient message).
Dialog visibility, errors and loading are **state**, not effects — they must survive rotation.

### 2. Write the ViewModel

- Extend the project's base, or `MviViewModel<State, Effect>` from the reference.
- One public entry point: `fun onAction(action: XAction)`.
- Update state atomically (`MutableStateFlow.update { }`), never `value = value.copy(...)` from
  concurrent coroutines.
- Capture the state you need **before** launching a coroutine (`val draft = currentState`);
  reading it after a suspension point may see newer input.
- Repositories/use cases are constructor-injected and main-safe. Inject a dispatcher only where
  this class itself switches context.
- No `NavController`, no `Context`, no `@Composable`, no `androidx.compose.*` imports.

Done when the ViewModel compiles in `commonMain` with zero Compose imports.

### 3. Write the screen (entry + view + effect handler)

```kotlin
@Composable
fun NoteEditorScreen(
    onNoteSaved: (noteId: String) -> Unit,
    viewModel: NoteEditorViewModel = koinViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    NoteEditorView(state = state, onAction = viewModel::onAction)
    CollectEffects(viewModel.effects) { effect ->
        when (effect) {
            is NoteEditorEffect.NoteSaved -> onNoteSaved(effect.noteId)
        }
    }
}
```

- `NoteEditorView(state, onAction, modifier)` is **pure**: no ViewModel, no `koinInject`, no
  `LaunchedEffect` that navigates. Only view-local state (`LazyListState`, focus, scroll) may be
  `remember`ed there.
- `CollectEffects` (in the reference) collects with the lifecycle at `STARTED` on
  `Dispatchers.Main.immediate`. It is the **only** place a navigation callback is invoked.
- Navigation is passed in as lambdas (or the project's navigator). The nav graph owns the
  `NavController`; the screen does not.
- Use `collectAsStateWithLifecycle()` (lifecycle-runtime-compose), not `collectAsState()`: it
  stops collecting while the host is below `STARTED`.

Done when the view can be called from a preview with a literal `UiState` and a no-op lambda.

### 4. Add TestTags and semantics

```kotlin
object NoteEditorTestTags {
    const val SCREEN = "note_editor_screen"
    const val TITLE_FIELD = "note_editor_title_field"
    const val SAVE_BUTTON = "note_editor_save_button"
    fun tagChip(tagId: String) = "note_editor_tag_chip_$tagId"   // stable backend id, never an index
}
```

- Tag the screen root and every interactive element, loader, error and empty state.
- `testTag` is a locator; `contentDescription` is spoken prose. Never reuse one string for both.
- Compose Multiplatform maps `testTag` to the iOS `accessibilityIdentifier`, so XCUITest/Appium
  can use the same tags. On Android, UiAutomator/Appium additionally need
  `Modifier.semantics { testTagsAsResourceId = true }` near the root (Android source set).
- Follow the project's existing tag format if one exists.

### 5. Add previews

- One preview per meaningful state: empty, filled, saving, error. Preview the **view**, never the
  stateful entry (Koin is not running in previews).
- Wrap in the app theme (`AppTheme { }`), not a bare `MaterialTheme`, so tokens resolve.
- Previews in `commonMain` need an Android target; they render in Android Studio / IntelliJ with
  the Kotlin Multiplatform plugin.

### 6. Register DI and the route

- Koin: `viewModel { params -> NoteEditorViewModel(noteId = params.getOrNull(), notesRepository = get()) }`
  (or `viewModelOf(::NoteEditorViewModel)` when there are no runtime parameters).
- Pass route arguments with `koinViewModel(parameters = { parametersOf(route.noteId) })`.
- Inside a `NavHost`, `koinViewModel()` is scoped to the current back-stack entry: each visit to the
  destination gets its own ViewModel, cleared when the entry is popped.
- Route definition and graph wiring → `compose-multiplatform-navigation`.

### 7. Write ViewModel tests (commonTest)

- `Dispatchers.setMain(StandardTestDispatcher())` in `@BeforeTest`, `resetMain()` in `@AfterTest`
  (`viewModelScope` runs on `Dispatchers.Main.immediate`).
- Hand-written fakes for repositories; no mocking framework needed.
- **Start collecting effects before triggering the action** (an eager collector in
  `backgroundScope` on `UnconfinedTestDispatcher(testScheduler)`, or Turbine's `test { }`).
- One behaviour per test; assert **both** the final state and the emitted effects.
- Do not test composables here; tests cover reducer, state derivation and effects.

Full code for every step — base class, screen, previews, Koin module, fake, tests — is in
[references/worked-example-note-editor.md](references/worked-example-note-editor.md).

## Quick reference

| Need | API (multiplatform) |
|---|---|
| Collect state | `androidx.lifecycle.compose.collectAsStateWithLifecycle` |
| Lifecycle-aware effect collection | `LocalLifecycleOwner` (`androidx.lifecycle.compose`) + `repeatOnLifecycle(Lifecycle.State.STARTED)` |
| ViewModel (Koin 4) | `org.koin.compose.viewmodel.koinViewModel`; module DSL `org.koin.core.module.dsl.viewModel` / `viewModelOf` |
| ViewModel (no DI) | `androidx.lifecycle.viewmodel.compose.viewModel { NoteEditorViewModel(...) }` |
| Preview annotation, CMP 1.10+ | `androidx.compose.ui.tooling.preview.Preview` (artifact `org.jetbrains.compose.ui:ui-tooling-preview`) |
| Preview annotation, CMP < 1.10 | `org.jetbrains.compose.ui.tooling.preview.Preview` (deprecated from 1.10) |
| Intercept back (unsaved changes) | see `compose-multiplatform-navigation` → back handling |
| Test main dispatcher | `kotlinx.coroutines.test.setMain` / `resetMain` |

| Effect transport | Delivery | Use when |
|---|---|---|
| `Channel(BUFFERED).receiveAsFlow()` | Exactly one collector; buffered while nobody collects | Default for navigation/snackbar effects |
| `MutableSharedFlow()` (replay 0) | Dropped if no subscriber at emit time (init, rotation, background) | Avoid for effects |
| `MutableSharedFlow(replay = 1)` | Re-delivered to every new subscriber | Avoid: double navigation after rotation |
| Event in `UiState` + "consumed" action | Survives anything; needs an explicit ack | Must-not-lose events (payment result, irreversible action) |

## Verify

Run what applies and report each check as **PASS**, **FAIL** or **NOT RUN (reason)**. Never report a
check as passed that you did not run. Replace `:shared` with the module that holds the screen.

```bash
./gradlew :shared:compileKotlinMetadata            # common code compiles (no Android/iOS-only APIs)
./gradlew :shared:testAndroidHostTest              # JVM tests (task name with the KMP Android library plugin)
./gradlew :shared:testDebugUnitTest                # JVM tests (task name with com.android.library + androidTarget)
./gradlew :shared:iosSimulatorArm64Test            # same tests on iOS (macOS only)
./gradlew :composeApp:assembleDebug                # Android app still builds
```

Use `./gradlew :shared:tasks --all | grep -i test` if the task names differ. Also check:

- `grep -rn "androidx.compose" <logic package>` returns nothing for the ViewModel files.
- Every interactive element in the new view has a `testTag` from the screen's `TestTags` object.
- Previews render (open the file in the IDE) — report NOT RUN if no IDE is available.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Navigating inside the ViewModel or holding a `NavController` there | Leaks the back-stack owner, breaks tests and iOS reuse | Emit an effect; navigate in the effect handler |
| Navigation in a stray `LaunchedEffect(state.saved)` | Fires again on recomposition/rotation when the flag is still true | Use an effect, or reset the flag with an explicit action |
| Effects in `MutableSharedFlow()` with no replay | Effects emitted in `init` or during rotation are silently dropped | `Channel(Channel.BUFFERED).receiveAsFlow()` |
| Collecting effects with plain `LaunchedEffect { flow.collect }` | Keeps collecting while stopped; events consumed off-screen | `repeatOnLifecycle(STARTED)` + `Dispatchers.Main.immediate` |
| `collectAsState()` for ViewModel state | Keeps collecting in background on Android | `collectAsStateWithLifecycle()` |
| `_state.value = _state.value.copy(...)` from several coroutines | Lost updates under concurrency | `_state.update { it.copy(...) }` |
| Reading `state.value` after a `suspend` call in a save flow | Saves text typed after the click | Snapshot the draft before launching |
| Base class calls an abstract `initialState()` from its constructor | Subclass fields are not initialised yet: wrong or null defaults | Pass the initial state as a constructor argument |
| Dialog visibility or error as an effect | Lost on rotation / process death | Keep it in `UiState` |
| Computing `isSaveEnabled` inside the composable | Untested logic, duplicated across platforms | Derived property on `UiState` |
| Previewing the stateful screen | Preview needs Koin/ViewModel and fails | Preview the pure view with literal states |
| Debounce or async work between `onValueChange` and the text field's value | Lost keystrokes, cursor jumps | Keep the text update synchronous; debounce side work (search) separately |
| Effect test collects after the action | Misses the emission or becomes flaky | Start the collector first, then act, then `advanceUntilIdle()` |
| Mixing idioms when extending an old screen | Two state sources, two event channels | Stay in the screen's existing idiom |

## Related skills

- `compose-multiplatform-navigation` — routes, NavHost, tabs, auth gate, deep links, back handling.
- `compose-design-system-component` — reusable components and theme tokens used by the view.
- `figma-to-mobile-ui` — turning a Figma frame into the view.
- `compose-multiplatform-localization` — strings, plurals and formatting in the view.
- [chrisbanes/skills](https://github.com/chrisbanes/skills) — `compose-state-and-effects`,
  `kotlin-concurrency-and-flow`, `compose-ui-testing-patterns`.
- [Meet-Miyani/compose-skill](https://github.com/Meet-Miyani/compose-skill) — an opinionated
  Compose/CMP architecture skill set.
- [android/skills](https://github.com/android/skills) — Jetpack Compose skills for Android-only apps.
