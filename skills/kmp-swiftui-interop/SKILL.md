---
name: kmp-swiftui-interop
description: Use when SwiftUI or Swift code consumes Kotlin Multiplatform shared logic — observing a Kotlin StateFlow or Flow from Swift, calling suspend functions with async/await, switching over Kotlin sealed classes, SKIE, KMP-NativeCoroutines, KMP-ObservableViewModel, Swift export, @ObjCName, KotlinInt boxing, doInitKoin, a crash with "doesn't have or inherit @Throws annotation", or choosing Compose Multiplatform vs native SwiftUI for iOS.
license: Apache-2.0
compatibility: Kotlin Multiplatform project whose iOS framework is consumed from Swift or SwiftUI. iOS steps need macOS with Xcode 16 or newer. The @Observable path needs iOS 17+.
metadata:
  category: ios-interop
  platforms: ios
---

# KMP ↔ SwiftUI interop

Kotlin owns state and business rules; Swift owns rendering, navigation and lifecycle. The bridge
between them must be thin, typed, cancellable and main-actor safe. Every bug in this seam is one of
four things: a leaked collection, a state write off the main thread, a Kotlin exception Swift was
never told about, or an API shape the Objective-C bridge cannot express.

## When to use

- Writing or reviewing Swift code that reads Kotlin `StateFlow` / `Flow` state, calls `suspend`
  functions, or switches over Kotlin sealed / enum types.
- Shaping a Kotlin API (`commonMain` or `iosMain`) that Swift will call.
- Choosing a bridging approach: SKIE, KMP-NativeCoroutines, KMP-ObservableViewModel, Swift export or
  hand-written wrappers.
- Deciding between Compose Multiplatform on iOS and native SwiftUI over shared logic.
- Symptoms: Swift UI not updating, a Kotlin ViewModel that keeps running after its screen closes,
  `Kotlinx_coroutines_coreFlow` with no element type, `KotlinInt` everywhere, `doInitKoin()`, a
  `switch` that needs `default`, or a crash that names `@Throws`.

## When not to use

- Building, packaging or versioning the framework (XCFramework, SPM, KMMBridge) — use
  `kmp-xcframework-distribution`.
- A Gradle, Kotlin/Native link or Xcode build error — use `kmp-build-failure-triage`.
- Pure SwiftUI layout, styling or Swift Concurrency questions with no Kotlin involved — see the
  SwiftUI and Swift Concurrency skills under Related skills.

## Step 0 — Read the project first

Detect what the project already does before writing anything. Follow it.

```bash
# How does iOS get the framework? (direct integration, SPM binary, CocoaPods)
grep -rn "embedAndSignAppleFrameworkForXcode\|embedSwiftExportForXcode" --include=project.pbxproj .
find . -name Package.swift -not -path "*/.build/*" -not -path "*/build/*"
ls Podfile 2>/dev/null; grep -rn "cocoapods {" --include=*.gradle.kts .

# Framework name Swift imports, static or dynamic, what is exported
grep -rn -A12 "binaries.framework" --include=*.gradle.kts .

# Bridging library already in use (never add a second one)
grep -rn "co.touchlab.skie\|kmp.nativecoroutines\|kmp-observableviewmodel\|swiftExport {" \
  --include=*.gradle.kts --include=*.toml .

# Shared presentation layer and DI entry point
grep -rln "class .*ViewModel" --include=*.kt . | head
grep -rn "startKoin" --include=*.kt .

# Swift side: deployment target, Swift language mode, observation style, tests
grep -rn "IPHONEOS_DEPLOYMENT_TARGET\|SWIFT_VERSION" --include=project.pbxproj . | sort -u
grep -rln "@Observable\|ObservableObject" --include=*.swift . | head
grep -rln "import Testing\|import XCTest" --include=*.swift . | head
```

Record: framework module name, bridging library, ViewModel base class (androidx `ViewModel`,
KMP-ObservableViewModel, MVI base, plain presenter), DI framework and where it starts, minimum iOS
version (`@Observable` needs 17), Swift 5 or 6 language mode, the existing wrapper/adapter pattern,
the Swift design system in use, and the accessibility-identifier convention.

**Follow what exists.** If wrappers already use `ObservableObject` + Combine, extend that idiom. If
the project uses KMP-NativeCoroutines, do not introduce SKIE. Use the defaults below only for a new
project or a new surface with no precedent.

## Workflow

### 1. Decide where the UI lives (greenfield or when asked)

| Factor | Compose Multiplatform on iOS | Native SwiftUI over shared logic |
|---|---|---|
| What is shared | UI and logic | Logic only; UI written per platform |
| Team shape | Kotlin-heavy, few iOS specialists | Dedicated iOS engineers |
| Newest iOS UI (system materials, widgets, Live Activities, App Intents) | Through UIKit interop, later | Immediately |
| Swift ↔ Kotlin surface | Tiny: one `ComposeUIViewController` | Large: every state and action crosses the bridge |
| Bridging tooling needed | Little | SKIE or equivalent is close to mandatory |
| Binary size | Adds the Skia-based renderer — measure | Smaller |

Mixing is allowed: SwiftUI can host a Compose screen through `UIViewControllerRepresentable`
wrapping `ComposeUIViewController { … }`, and Compose can host UIKit with `UIKitView` /
`UIKitViewController`. Compose Multiplatform for iOS is Stable since 1.8.0. The rest of this skill
covers the native SwiftUI path.

**Done when** the choice and its reason are written down for the user.

### 2. Pick one bridging mechanism

| Option | What Swift gets | Costs and limits | Choose when |
|---|---|---|---|
| [SKIE](https://skie.touchlab.co) | `Flow`/`StateFlow` → typed `AsyncSequence`; `suspend` → `async` callable from any thread, with cancellation both ways; sealed → `onEnum(of:)` exhaustive enum; Kotlin enums → Swift enums | Compiler plugin bound to a Kotlin version range (check before every Kotlin upgrade); source-breaking when added to an existing Swift codebase; default-argument overloads are **off by default** and deprecated | Default for new SwiftUI-over-KMP work |
| [KMP-NativeCoroutines](https://github.com/rickclephas/KMP-NativeCoroutines) | `@NativeCoroutines` / `@NativeCoroutinesState` on each declaration; Swift `asyncSequence(for:)`, `asyncFunction(for:)`, Combine and RxSwift adapters | Annotate every exposed declaration; Swift package dependency | You need Combine/RxSwift, or want explicit per-declaration opt-in |
| [KMP-ObservableViewModel](https://github.com/rickclephas/KMP-ObservableViewModel) | Kotlin ViewModel observable from SwiftUI with `@StateViewModel` / `@ObservedViewModel` | ViewModels extend its base class; pairs with `@NativeCoroutinesState` | You want Kotlin ViewModels to drive SwiftUI directly |
| [Swift export](https://kotlinlang.org/docs/native-swift-export.html) | Kotlin → Swift without Objective-C; `swiftExport { }` + `embedSwiftExportForXcode` | Alpha; direct integration only; generics largely unsupported | Experiments only — re-check its status before relying on it |
| Hand-written wrappers | Callbacks + an `AutoCloseable` from `iosMain` | Boilerplate; easy to leak or call back off-main | Tiny surface, or plugins are not allowed |

Pick one per framework. **Done when** the choice matches what Step 0 found, or the user approved a
new one.

### 3. Shape the Kotlin API for Swift

Design the Swift-facing surface deliberately — it is a public API.

- One entry point per screen or feature: `val state: StateFlow<NotesUiState>` plus plain functions
  (`fun onAction(action: NotesAction)` or named methods). Avoid exposing raw repositories.
- Model screen states as a sealed interface; each case a `data class` or `data object`. Keep fields
  non-null where possible.
- Generics survive only on classes, not on interfaces or functions. Constrain them `T : Any` so
  Swift does not see optionals. Do not expose `Flow<T>` from an interface without SKIE — Swift sees an
  untyped flow.
- `Int` is `Int32` in Swift and `Long` is `Int64`; nullable or generic primitives become boxed
  `KotlinInt` / `KotlinLong`. Keep IDs as `String` or `Long`, never a boxed generic.
- Inline `reified` functions (such as Koin's `get<T>()`) are not exported. Wrap them.
- A Kotlin function named `init…` is exported as `doInit…` (Objective-C reserves the `init` family).
- Rename for Swift with `@ObjCName(swiftName = "…")` (`@OptIn(ExperimentalObjCName::class)`). Hide
  helpers with `@HiddenFromObjC`; mark a declaration you will wrap in Swift with
  `@ShouldRefineInSwift` (both `@OptIn(ExperimentalObjCRefinement::class)`). Everything `internal`
  is already hidden.
- Every function that can fail must either return a result type (preferred at a UI boundary) or
  declare `@Throws` — see step 6.

Full Kotlin → Swift type table, with and without SKIE: [references/type-mapping.md](references/type-mapping.md).

**Done when** the generated header shows the intended Swift names (see Verify).

### 4. Write the Swift wrapper

One `@MainActor` model per screen. It mirrors Kotlin state into a Swift property and forwards
actions. Shape with SKIE and `@Observable` (iOS 17+):

```swift
import Observation
@preconcurrency import SharedKit   // Kotlin types are not Sendable; see step 5

@MainActor
@Observable
final class NotesModel {
    private(set) var state: NotesUiState
    private let viewModel: NotesViewModel   // `let` properties are not tracked by @Observable

    init(viewModel: NotesViewModel) {
        self.viewModel = viewModel
        self.state = viewModel.state.value      // first frame renders real state, not a blank
    }

    /// Mirrors Kotlin state until the calling Task is cancelled. `.task {}` cancels it on disappear.
    func observe() async {
        for await newState in viewModel.state {
            state = newState
        }
    }

    func send(_ action: NotesAction) {
        viewModel.onAction(action: action)
    }
}
```

```swift
struct NotesScreen: View {
    let model: NotesModel   // owned by a route container that creates it once (step 5)

    var body: some View {
        Group {
            switch onEnum(of: model.state) {
            case .loading:            ProgressView()
            case .content(let c):     NotesList(notes: c.notes, onDelete: { model.send(NotesActionDelete(id: $0)) })
            case .error(let e):       ErrorState(message: e.message)
            }
        }
        .task { await model.observe() }   // structured: cancelled automatically when the view goes away
    }
}
```

The complete example — Kotlin ViewModel, `iosMain` owner, Koin helper, the iOS 16
`ObservableObject` variant, the protocol boundary used for previews and tests, and a test — is in
[references/swift-wrapper-example.md](references/swift-wrapper-example.md).

**Done when** state updates render, and leaving the screen stops collection (see Verify).

### 5. Get lifecycle and threading right

- **Collect inside `.task {}`**, not `onAppear { Task { … } }`. `.task` is cancelled when the view
  disappears; an unstructured `Task` leaks until the flow completes — usually never for a `StateFlow`.
- **Create the model once.** `@State var model = NotesModel(…)` evaluates the initializer every
  time SwiftUI rebuilds the view struct and keeps only the first result. If creating it builds a
  Kotlin ViewModel that starts work in `init`, every discarded copy starts that work too. Create it
  lazily in `.task` behind `if model == nil`, keep it in a router/coordinator object that lives as
  long as the route, or use `ObservableObject` + `@StateObject` (its autoclosure runs once).
- **Release the Kotlin side.** An androidx `ViewModel`'s `viewModelScope` is cancelled only when its
  `ViewModelStore` is cleared, and on iOS nothing does that for you. Own the store in an `iosMain`
  helper with a `clear()` function, and call it deterministically: from a small, non-actor-isolated
  Swift handle whose `deinit` calls `clear()` (works on every toolchain — see the reference), or from
  the coordinator when the route is popped. `isolated deinit` (Swift 6.2) on the `@MainActor` model
  also works, but it has been reported to need iOS 18.4 or newer at runtime.
- **Main actor.** Mark the model `@MainActor`. With SKIE, the `for await` body resumes on the
  model's actor, so writes land on main. With hand-written callbacks, Kotlin may call back on any
  thread — hop to the main actor before touching UI state.
- **Swift 6 Sendable errors.** Kotlin classes arrive as non-`Sendable` Objective-C classes.
  `@preconcurrency import SharedKit` downgrades those diagnostics for that module; keep Kotlin
  objects confined to one actor rather than adding `@unchecked Sendable` conformances.
- **Kotlin threads.** Kotlin/Native's memory manager lets objects cross threads freely; the Kotlin
  code's own thread-safety is still yours. `Dispatchers.Main` on iOS is the main queue.

### 6. Make every Kotlin failure visible to Swift

Kotlin exceptions are unchecked; Swift only knows about errors a function declares.

| Kotlin declaration | Exception reaches Swift as | Otherwise |
|---|---|---|
| non-`suspend`, no `@Throws` | — | **App terminates** |
| `suspend`, no `@Throws` | Only `CancellationException`, as an error | Any other exception **terminates the app** |
| `@Throws(NotesException::class, CancellationException::class)` | Swift `throws`; listed types (and subclasses) arrive as `NSError` | Unlisted types still terminate |

The crash log says: "Function doesn't have or inherit @Throws annotation and thus exception isn't
propagated from Kotlin to Objective-C/Swift as NSError." The compiler also requires
`CancellationException` (or a superclass) in `@Throws` on a `suspend` function.

Prefer catching in Kotlin and returning a sealed result (`Success` / `Failure(message, code)`) or an
error case in `UiState`, so Swift never needs `try`. Use `@Throws` for library-style APIs.

### 7. Start DI once, resolve through helpers

```kotlin
// shared/src/iosMain/kotlin/com/example/app/di/KoinIos.kt
fun initKoin() {
    startKoin { modules(sharedModule, iosPlatformModule) }
}

object NotesDependencies : KoinComponent {
    fun notesViewModelOwner(): NotesViewModelOwner = NotesViewModelOwner(get())
}
```

```swift
@main
struct NotesApp: App {
    init() { KoinIosKt.doInitKoin() }   // file KoinIos.kt → KoinIosKt; init… → doInit…
    var body: some Scene { WindowGroup { RootView() } }
}
```

Call it exactly once (a second `startKoin` throws `KoinApplicationAlreadyStartedException`). Do not
start Koin in SwiftUI previews or Swift unit tests — inject fakes through the protocol boundary.

### 8. Render with native SwiftUI components

Use `.alert`, `.confirmationDialog`, `.sheet` / `.fullScreenCover`, `NavigationStack` with the real
navigation bar, and the app's SwiftUI design system tokens. Do not hand-roll dim overlays, fake
toolbars or custom modal containers when a system component exists. Give every interactive control a
stable `.accessibilityIdentifier(AccessibilityID.Notes.addButton)` from one namespace — distinct from
the VoiceOver `accessibilityLabel`. Known traps (including an iOS 26 alert-button contrast issue):
[references/pitfalls.md](references/pitfalls.md).

### 9. Test the Swift side

- Business logic is tested in Kotlin `commonTest`. Swift tests cover only the wrapper: state
  mirroring, action forwarding, error mapping.
- Put a Swift protocol at the boundary (`NotesSource`) with a Kotlin-backed implementation and a pure
  Swift fake. Previews and tests use the fake; no Kotlin runtime or DI is needed.
- Kotlin classes are `final` in Swift — you cannot subclass them as mocks. Kotlin *interfaces*
  become protocols you can conform to, but with SKIE their `suspend` members are awkward to
  implement in Swift; the Swift-side protocol avoids that.

## Quick reference

| Need | Without SKIE | With SKIE |
|---|---|---|
| Observe `StateFlow<T>` | Kotlin `iosMain` callback wrapper returning an `AutoCloseable` | `for await v in vm.state`; current value `vm.state.value` |
| Call `suspend fun load()` | Completion handler, or `async` (experimental), main thread only by default | `try await vm.load()` from any thread; Task cancel → coroutine cancel |
| Switch over sealed `UiState` | `if let x = s as? NotesUiStateContent` chain + fallback | `switch onEnum(of: s)` — exhaustive |
| Kotlin `enum` in `switch` | Needs `default:` | Real Swift enum, exhaustive |
| Default arguments | Swift must pass every argument | Off by default; enable per declaration (deprecated feature) |
| Kotlin `object Foo` | `Foo.shared` | `Foo.shared` |
| Top-level `fun x()` in `Util.kt` | `UtilKt.x()` | same |
| Companion member | `Foo.companion.bar` | same |

## Verify

Report every check as `PASS`, `FAIL` or `NOT RUN` with the reason. Never report a check that did
not run as passed.

```bash
# 1. Kotlin side compiles and links for the simulator (SKIE runs during this link)
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64

# 2. The Swift names are the ones you designed
find shared/build/bin/iosSimulatorArm64/debugFramework -name "*.h" -path "*Headers*" \
  -exec grep -n "NotesViewModel\|NotesUiState" {} +

# 3. Kotlin tests on iOS
./gradlew :shared:iosSimulatorArm64Test

# 4. The app builds and Swift tests pass (pick a simulator from: xcrun simctl list devices available)
xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp \
  -destination 'platform=iOS Simulator,name=iPhone 16' build test
```

5. **Lifecycle check (manual or UI test).** Temporarily log `_state.subscriptionCount` (a
   `StateFlow<Int>` on every `MutableStateFlow`) and log from the ViewModel's `onCleared()`. Open the
   screen, leave it: the count must return to 0 and `onCleared()` must run. Without this, report the
   leak check as `NOT RUN`.
6. On Swift 6 language mode, the build must have no new concurrency warnings in the wrapper files.

No macOS/Xcode available → checks 1–4 are `NOT RUN — requires macOS with Xcode`.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| `onAppear { Task { for await … } }` | The Task outlives the view; collection never stops | `.task { await model.observe() }` |
| Model built in `@State var m = Model(vm: makeVM())` | Initializer runs on every view rebuild; extra Kotlin VMs start duplicate work | Create lazily in `.task`, in a router object, or via `@StateObject` |
| Never clearing the Kotlin ViewModel on iOS | `viewModelScope` keeps running (polling, timers, DB observers) | `iosMain` owner with `ViewModelStore.clear()`, called from a handle's `deinit` |
| Writing `@Published` / `@Observable` state from a Kotlin callback thread | Off-main UI mutation: warnings, glitches, crashes | `@MainActor` model; SKIE `for await`; or hop to main |
| Kotlin function that throws, no `@Throws` | Swift cannot catch it; the app terminates | Return a sealed result, or `@Throws(…, CancellationException::class)` |
| `switch` over a Kotlin sealed class with `as?` casts | New subclasses silently fall into the fallback | SKIE `onEnum(of:)` |
| Generic interface `Repository<T>` exposed to Swift | Generics are erased on interfaces/functions | Concrete facade types, or generic *classes* with `T : Any` |
| Adding SKIE to a project that already uses KMP-NativeCoroutines | Two bridges, duplicated APIs, confusing names | Keep one per framework |
| Upgrading Kotlin without checking SKIE's supported range | iOS build breaks while Android stays green | Check SKIE's compatibility first; upgrade both together |
| Starting Koin in previews or Swift tests | Duplicate-start exceptions; slow, flaky previews | Protocol boundary + Swift fakes |
| Hand-rolled alert/sheet overlays | Breaks accessibility, keyboard and system behaviour | `.alert`, `.confirmationDialog`, `.sheet` |

## Related skills

- `kmp-xcframework-distribution` — packaging and shipping the framework to iOS (SPM, KMMBridge, tags).
- `kmp-build-failure-triage` — `No such module`, undefined symbols, Xcode run-script failures.
- `kmp-crash-triage` — symbolicating an iOS crash with Kotlin frames (including `@Throws` terminations).
- `compose-multiplatform-screen` — if step 1 chose Compose Multiplatform for the iOS UI.
- `mobile-platform-parity` — keeping the SwiftUI screen's behaviour in line with Android.
- [SwiftUI Expert skill](https://github.com/AvdLee/SwiftUI-Agent-Skill) and
  [SwiftUI Pro skill](https://github.com/twostraws/SwiftUI-Agent-Skill) — SwiftUI itself.
- [Swift Concurrency skill](https://github.com/AvdLee/Swift-Concurrency-Agent-Skill) — actors,
  Sendable, Swift 6 migration.
- [Kotlin agent skills](https://github.com/Kotlin/kotlin-agent-skills) — official Kotlin tooling skills.
- [MobileBuildMCP](https://github.com/getsentry/MobileBuildMCP) (formerly XcodeBuildMCP) — lets an
  agent build, run and test the iOS app.
- Docs: [SKIE](https://skie.touchlab.co), [Kotlin ↔ Objective-C/Swift interop](https://kotlinlang.org/docs/native-objc-interop.html),
  [Swift export](https://kotlinlang.org/docs/native-swift-export.html).
