# Complete example — a notes screen in SwiftUI over a Kotlin ViewModel

Contents

1. Assumptions
2. Kotlin: state, actions, ViewModel (`commonMain`)
3. Kotlin: the iOS owner and DI helper (`iosMain`)
4. Swift: the lifetime handle
5. Swift: `@Observable` model (iOS 17+)
6. Swift: `ObservableObject` model (iOS 16)
7. Swift: the screen
8. Optional: a Swift protocol boundary for previews and tests
9. Swift tests
10. Variant: without SKIE

## 1. Assumptions

- Framework module `SharedKit`, built from `:shared`, with SKIE applied.
- Shared ViewModels extend `androidx.lifecycle.ViewModel` from the KMP `lifecycle-viewmodel`
  artifact (the `ViewModelProvider.create` API used below is in the multiplatform artifact; check
  your version has it).
- Koin for DI. Package root `com.example.app`.
- Adapt every name to what Step 0 found. If the project's ViewModels extend something else, keep
  the same three ideas: mirror state in `.task`, create once, release deterministically.

## 2. Kotlin: state, actions, ViewModel

```kotlin
// shared/src/commonMain/kotlin/com/example/app/notes/NotesContract.kt
package com.example.app.notes

data class Note(val id: String, val title: String, val updatedAtEpochMillis: Long)

/** Screen state. Sealed so Swift can switch exhaustively through SKIE's onEnum(of:). */
sealed interface NotesUiState {
    data object Loading : NotesUiState
    data class Content(val notes: List<Note>) : NotesUiState
    data class Error(val message: String) : NotesUiState
}

sealed interface NotesAction {
    data object Refresh : NotesAction
    data class Delete(val id: String) : NotesAction
}

interface NotesRepository {
    /** Never throws to callers: failures come back as Result.failure. Cancellation is rethrown. */
    suspend fun notes(): Result<List<Note>>
    suspend fun delete(id: String): Result<Unit>
}
```

```kotlin
// shared/src/commonMain/kotlin/com/example/app/notes/NotesViewModel.kt
package com.example.app.notes

class NotesViewModel(
    private val notesRepository: NotesRepository,
) : ViewModel() {

    private val _state = MutableStateFlow<NotesUiState>(NotesUiState.Loading)
    val state: StateFlow<NotesUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun onAction(action: NotesAction) {
        when (action) {
            NotesAction.Refresh -> load()
            is NotesAction.Delete -> viewModelScope.launch {
                notesRepository.delete(action.id)
                load()
            }
        }
    }

    private fun load() {
        viewModelScope.launch {
            _state.value = NotesUiState.Loading
            _state.value = notesRepository.notes().fold(
                onSuccess = { NotesUiState.Content(it) },
                onFailure = { NotesUiState.Error(it.message ?: "Could not load notes") },
            )
        }
    }
}
```

Errors become a state, so no function Swift calls can throw — no `@Throws` needed and no crash path.
Because `init` starts work, the iOS side must create this ViewModel exactly once per screen.

## 3. Kotlin: the iOS owner and DI helper

```kotlin
// shared/src/iosMain/kotlin/com/example/app/notes/NotesViewModelOwner.kt
package com.example.app.notes

/**
 * Owns the ViewModelStore for one iOS screen. Android's framework clears the store for you;
 * on iOS nothing does, so viewModelScope would run forever without clear().
 */
class NotesViewModelOwner(notesRepository: NotesRepository) {
    private val store = ViewModelStore()

    val viewModel: NotesViewModel = ViewModelProvider.create(
        store = store,
        factory = viewModelFactory { initializer { NotesViewModel(notesRepository) } },
    )[NotesViewModel::class]

    /** Cancels viewModelScope. Call once, when the screen is gone for good. */
    fun clear() = store.clear()
}
```

```kotlin
// shared/src/iosMain/kotlin/com/example/app/di/KoinIos.kt
package com.example.app.di

fun initKoin() {
    startKoin { modules(sharedModule, iosPlatformModule) }
}

/** Swift cannot call Koin's reified get<T>(); expose typed factory functions instead. */
object NotesDependencies : KoinComponent {
    fun notesViewModelOwner(): NotesViewModelOwner = NotesViewModelOwner(notesRepository = get())
}
```

Swift sees `KoinIosKt.doInitKoin()` and `NotesDependencies.shared.notesViewModelOwner()`.

## 4. Swift: the lifetime handle

```swift
import SharedKit

/// Deliberately NOT actor-isolated, so its deinit can touch `owner` on any Swift toolchain.
/// The @MainActor model below holds it; when the model is released, the Kotlin scope is cancelled.
final class NotesOwnerHandle {
    let owner: NotesViewModelOwner
    init(_ owner: NotesViewModelOwner) { self.owner = owner }
    deinit { owner.clear() }
}
```

The handle only runs `deinit` if nothing keeps the model alive. The `.task` that runs `observe()`
holds the model until SwiftUI cancels it, so do not store the model anywhere that outlives the
screen (a singleton, a long-lived coordinator array) without removing it on pop.

## 5. Swift: `@Observable` model (iOS 17+)

```swift
import Observation
@preconcurrency import SharedKit

@MainActor
@Observable
final class NotesModel {
    private(set) var state: NotesUiState
    private let handle: NotesOwnerHandle

    init(owner: NotesViewModelOwner) {
        handle = NotesOwnerHandle(owner)
        state = owner.viewModel.state.value      // render real state on the first frame
    }

    /// Runs until the calling Task is cancelled. SKIE ends the Kotlin collection on cancel.
    func observe() async {
        for await newState in handle.owner.viewModel.state {
            state = newState                     // on the main actor: the model is @MainActor
        }
    }

    func refresh() { handle.owner.viewModel.onAction(action: NotesActionRefresh.shared) }
    func delete(id: String) { handle.owner.viewModel.onAction(action: NotesActionDelete(id: id)) }
}
```

Names: a nested Kotlin `NotesAction.Delete` was observed exported as `NotesActionDelete`, and a
`data object` is reached through `.shared`. Confirm in your generated header — naming can differ
across Kotlin and SKIE versions.

## 6. Swift: `ObservableObject` model (iOS 16)

```swift
import Combine
@preconcurrency import SharedKit

@MainActor
final class NotesObservableModel: ObservableObject {
    @Published private(set) var state: NotesUiState
    private let handle: NotesOwnerHandle

    init(owner: NotesViewModelOwner) {
        handle = NotesOwnerHandle(owner)
        state = owner.viewModel.state.value
    }

    func observe() async {
        for await newState in handle.owner.viewModel.state { state = newState }
    }
}

struct NotesScreenLegacy: View {
    // @StateObject's autoclosure runs once per view identity — the Kotlin ViewModel is created once.
    @StateObject private var model = NotesObservableModel(
        owner: NotesDependencies.shared.notesViewModelOwner()
    )

    var body: some View {
        NotesContent(state: model.state)
            .task { await model.observe() }
    }
}
```

## 7. Swift: the screen

SwiftUI may evaluate a view's initializer — and a `navigationDestination` closure — more than once.
Anything written as `NotesModel(owner: …)` in a view initializer can therefore build extra Kotlin
ViewModels. Create the model lazily, once per view identity:

```swift
import SwiftUI
@preconcurrency import SharedKit

/// Route container: builds the model on first appearance only.
struct NotesRoute: View {
    @State private var model: NotesModel?

    var body: some View {
        Group {
            if let model {
                NotesScreen(model: model)
            } else {
                ProgressView()
            }
        }
        .task {
            if model == nil {
                model = NotesModel(owner: NotesDependencies.shared.notesViewModelOwner())
            }
        }
    }
}

struct NotesScreen: View {
    let model: NotesModel            // @Observable: reading model.state in body tracks it
    @State private var pendingDeleteID: String?

    var body: some View {
        Group {
            switch onEnum(of: model.state) {
            case .loading:
                ProgressView()
            case .content(let content):
                List(content.notes, id: \.id) { note in
                    Text(note.title)
                        .swipeActions {
                            Button("Delete", role: .destructive) { pendingDeleteID = note.id }
                                .accessibilityIdentifier(AccessibilityID.Notes.deleteButton(note.id))
                        }
                }
                .refreshable { model.refresh() }
            case .error(let error):
                VStack {
                    Text(error.message)
                    Button("Retry") { model.refresh() }
                        .accessibilityIdentifier(AccessibilityID.Notes.retryButton)
                }
            }
        }
        .navigationTitle("Notes")
        .confirmationDialog(
            "Delete this note?",
            isPresented: Binding(get: { pendingDeleteID != nil }, set: { if !$0 { pendingDeleteID = nil } }),
            titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) {
                if let id = pendingDeleteID { model.delete(id: id) }
            }
            .accessibilityIdentifier(AccessibilityID.Notes.confirmDelete)
        }
        .task { await model.observe() }
    }
}
```

`.refreshable { model.refresh() }` returns immediately because the action is fire-and-forget; if the
spinner should stay until data arrives, expose a `suspend fun refresh()` and `await` it. Replace the
plain `Text`/`Button` views with the app's SwiftUI design-system components.

## 8. Optional: a Swift protocol boundary for previews and tests

Use this when the screen has Swift-side logic worth testing, or when previews must not boot Kotlin
and DI. It costs one mapping layer.

```swift
enum NotesViewState: Equatable {
    case loading
    case content([NoteRow])
    case error(String)
}

struct NoteRow: Identifiable, Equatable { let id: String; let title: String }

enum NotesIntent: Equatable { case refresh, delete(id: String) }

@MainActor
protocol NotesSource {
    func states() -> AsyncStream<NotesViewState>
    func send(_ intent: NotesIntent)
}

@MainActor
final class KotlinNotesSource: NotesSource {
    private let handle: NotesOwnerHandle
    init(owner: NotesViewModelOwner) { handle = NotesOwnerHandle(owner) }

    func states() -> AsyncStream<NotesViewState> {
        let flow = handle.owner.viewModel.state
        return AsyncStream { continuation in
            let task = Task { @MainActor in
                for await state in flow { continuation.yield(Self.map(state)) }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }   // consumer gone → stop collecting
        }
    }

    func send(_ intent: NotesIntent) {
        switch intent {
        case .refresh: handle.owner.viewModel.onAction(action: NotesActionRefresh.shared)
        case .delete(let id): handle.owner.viewModel.onAction(action: NotesActionDelete(id: id))
        }
    }

    static func map(_ state: NotesUiState) -> NotesViewState {
        switch onEnum(of: state) {
        case .loading: return .loading
        case .content(let c): return .content(c.notes.map { NoteRow(id: $0.id, title: $0.title) })
        case .error(let e): return .error(e.message)
        }
    }
}

@MainActor
@Observable
final class NotesScreenModel {
    private(set) var state: NotesViewState = .loading
    private let source: NotesSource
    init(source: NotesSource) { self.source = source }

    func observe() async { for await s in source.states() { state = s } }
    func send(_ intent: NotesIntent) { source.send(intent) }
}

/// Pure Swift: previews and tests need no Kotlin runtime, no DI.
@MainActor
final class FakeNotesSource: NotesSource {
    private let scripted: [NotesViewState]
    private(set) var sent: [NotesIntent] = []
    init(states: [NotesViewState]) { scripted = states }

    func states() -> AsyncStream<NotesViewState> {
        let scripted = self.scripted
        return AsyncStream { continuation in
            for state in scripted { continuation.yield(state) }
            continuation.finish()                // finite: observe() returns, tests stay deterministic
        }
    }

    func send(_ intent: NotesIntent) { sent.append(intent) }
}
```

## 9. Swift tests

Swift Testing (Xcode 16+). Keep the project's naming convention; `should_x_when_y` shown.

```swift
import Testing
@testable import NotesFeature

@MainActor
struct NotesScreenModelTests {
    private let groceries = NoteRow(id: "1", title: "Groceries")

    @Test func should_showLatestState_when_sourceEmitsContent() async {
        let source = FakeNotesSource(states: [.loading, .content([groceries])])
        let model = NotesScreenModel(source: source)

        await model.observe()                    // returns when the fake's finite stream ends

        #expect(model.state == .content([groceries]))
    }

    @Test func should_forwardDelete_when_userConfirmsDelete() {
        let source = FakeNotesSource(states: [])
        let model = NotesScreenModel(source: source)

        model.send(.delete(id: "1"))

        #expect(source.sent == [.delete(id: "1")])
    }

    @Test func should_mapKotlinError_when_viewModelFails() {
        // Kotlin data classes can be constructed from Swift; Long parameters arrive as Int64.
        let mapped = KotlinNotesSource.map(NotesUiStateError(message: "Offline"))
        #expect(mapped == .error("Offline"))
    }
}
```

The third test links the Kotlin framework into the test target; the first two do not need it.

## 10. Variant: without SKIE

Without SKIE, Swift sees `StateFlow` as an untyped Objective-C object. Bridge it in Kotlin:

```kotlin
// shared/src/iosMain/kotlin/com/example/app/util/FlowWatcher.kt
package com.example.app.util

/** Collects on the main dispatcher and hands each value to Swift. Swift must call close(). */
class FlowWatcher<T : Any>(private val flow: Flow<T>) {
    fun watch(onEach: (T) -> Unit): AutoCloseable {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
        flow.onEach(onEach).launchIn(scope)
        return AutoCloseable { scope.cancel() }
    }
}

fun NotesViewModel.watchState(): FlowWatcher<NotesUiState> = FlowWatcher(state)
```

Swift keeps the returned object and calls `close()` when the view disappears or the model is
released (the handle pattern from section 4 works here too). Values arrive on the main queue because
the scope uses `Dispatchers.Main`; any other dispatcher means hopping to the main actor in Swift.
`FlowWatcher` is a generic *class*, so its type parameter survives into Swift; a generic function
would not.
