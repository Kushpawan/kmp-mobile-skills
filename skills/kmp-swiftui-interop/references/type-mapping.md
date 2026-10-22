# Kotlin → Swift type mapping

Contents

1. Declarations
2. Primitives, strings, collections
3. Functions, coroutines, errors
4. Naming and visibility controls
5. Generics
6. Swift export (Alpha)

Default column = Kotlin/Native's Objective-C export as Swift sees it. Always confirm against your
own generated header (`<Framework>.framework/Headers/<Framework>.h`) — exact names shift between
Kotlin and SKIE versions.

## 1. Declarations

| Kotlin | Swift (default export) | With SKIE |
|---|---|---|
| `class Note` | `class Note` (subclass of the framework's Kotlin base class) | same |
| final class (Kotlin default) | Cannot be subclassed in Swift — no Swift mocks by subclassing | same |
| `interface NotesRepository` | `protocol NotesRepository`; Swift classes may conform | same |
| `object Clock` | `Clock.shared` | same |
| `companion object` | `Note.companion` (the class is `Note.Companion`, also reachable as `Note.Companion.shared`) | same |
| `enum class Priority { LOW, HIGH }` | `class Priority` with `Priority.low`, `.high`; `switch` needs `default:` | Real Swift `enum`, exhaustive |
| `sealed interface NotesUiState` | Class hierarchy; branch with `as?` downcasts | `switch onEnum(of: state)` with typed associated values |
| nested `NotesUiState.Content` | Observed as `NotesUiStateContent` (Kotlin 2.x) | same; case `.content` in `onEnum` |
| `data object Loading` | `NotesUiStateLoading.shared` | `.loading` case |
| `data class` | Class with `copy(…)`, `isEqual`/`==`, `hash`, `description` | same |
| Extension on a Kotlin class `fun Note.label()` | Instance method `note.label()` | same |
| Extension on a non-Kotlin type `fun String.slug()` | Static helper `NotesKt.slug(receiver)` style — check the header | same |
| Top-level `fun formatDate()` in `Dates.kt` | `DatesKt.formatDate()` | same |

## 2. Primitives, strings, collections

| Kotlin | Swift | Note |
|---|---|---|
| `Int` / `Long` / `Short` / `Byte` | `Int32` / `Int64` / `Int16` / `Int8` | Swift `Int` is 64-bit: convert explicitly |
| `UInt`, `ULong` | `UInt32`, `UInt64` | |
| `Boolean`, `Double`, `Float` | `Bool`, `Double`, `Float` | |
| `Char` | `unichar` (UTF-16 code unit) | Not a Swift `Character` |
| `Int?`, or `Int` used as a generic argument | `KotlinInt?` / `KotlinInt` (an `NSNumber` subclass) | Read with `.int32Value`; build with `KotlinInt(int: 5)` |
| `String` | `String` | |
| `List<T>` | `[T]` | Elements of primitive type are boxed: `List<Int>` → `[KotlinInt]` |
| `MutableList<T>` | `NSMutableArray` | |
| `Set<T>` / `MutableSet<T>` | `Set<T>` / `KotlinMutableSet` | To pass a mutable set *into* Kotlin, create a Kotlin collection |
| `Map<K, V>` / `MutableMap<K, V>` | `[K: V]` / `KotlinMutableDictionary` | |
| `ByteArray` | `KotlinByteArray` | Not `Data` — convert in a helper on one side |
| `Unit` (return) | `Void`; `KotlinUnit` when used as a generic argument | |
| `Throwable` | `KotlinThrowable` | |

Large collections are bridged, not shared: converting a big `List` on every state emission costs
time on the main thread. Keep emitted lists modest or page them.

## 3. Functions, coroutines, errors

| Kotlin | Swift (default export) | With SKIE |
|---|---|---|
| Default arguments | Not exported — Swift passes every argument | Overloads only when enabled per declaration (`@DefaultArgumentInterop.Enabled`); off by default, deprecated, O(2ⁿ) overloads |
| Function type `(Int) -> Unit` | Closure with boxed parameters: `(KotlinInt) -> Void` | same |
| `suspend fun load(): List<Note>` | `load(completionHandler:)`, plus an experimental `async` form; call from the main thread unless the binary option `objcExportSuspendFunctionLaunchThreadRestriction=none` is set | `try await load()` from any thread; cancelling the Swift Task cancels the coroutine |
| `Flow<T>` | `Kotlinx_coroutines_coreFlow` — element type lost; needs a Kotlin-side collector | `SkieSwiftFlow<T>`: an `AsyncSequence` |
| `StateFlow<T>` | `Kotlinx_coroutines_coreStateFlow` | `SkieSwiftStateFlow<T>`: `AsyncSequence` + `.value` |
| `Flow<T?>` | — | `SkieSwiftOptionalFlow<T>` |
| Exception from a non-`suspend` function without `@Throws` | App terminates | same |
| Exception from a `suspend` function without `@Throws` | Only `CancellationException` arrives as an error; anything else terminates | same |
| `@Throws(IOException::class, CancellationException::class)` | `throws`; listed types and subclasses arrive as `NSError` | same |

`AsyncSequence` → `Flow` (Swift into Kotlin) is not converted by SKIE. Pass Swift values into Kotlin
through plain function calls.

A type from a dependency that is used in your API but not `export(…)`-ed still appears, with a
module prefix (`Kotlinx_coroutines_coreFlow`, `Feature_notesNote`). That prefix is the signal that
you meant to export the module — add `api(…)` and `export(…)` (see `kmp-xcframework-distribution`).

## 4. Naming and visibility controls

| Tool | Effect | Opt-in |
|---|---|---|
| `@ObjCName(swiftName = "NoteItem")` | Custom Swift (and Objective-C) name for a class, function, parameter or property | `@OptIn(ExperimentalObjCName::class)` |
| `@HiddenFromObjC` | Not exported to Objective-C/Swift; still visible to other Kotlin modules | `@OptIn(ExperimentalObjCRefinement::class)` |
| `@ShouldRefineInSwift` | Exported as `swift_private` (`__name`), so you can wrap it in a nicer Swift extension | `@OptIn(ExperimentalObjCRefinement::class)` |
| `internal` / `private` | Not exported | — |
| A name starting with `init` | Exported with a `do` prefix: `initKoin()` → `doInitKoin()` | Rename, or use `@ObjCName` |
| Member names that clash with `NSObject` (for example a property `description`) | Exported with a trailing underscore (`description_`) | Rename in Kotlin, or use `@ObjCName` |

Opt in once per module instead of per declaration:

```kotlin
kotlin {
    sourceSets.all {
        languageSettings.optIn("kotlin.experimental.ExperimentalObjCName")
        languageSettings.optIn("kotlin.experimental.ExperimentalObjCRefinement")
    }
}
```

## 5. Generics

- Generic parameters survive only on **classes**. Generic interfaces and generic functions are
  erased (Swift sees `Any?` / `id`).
- Constrain `T : Any` when values are never null; otherwise every `T` is optional in Swift.
- Primitive type arguments are boxed: `Box<Int>` is `Box<KotlinInt>`.
- Variance (`out T`, `in T`) is not expressed in Swift; casts may be needed.
- With SKIE, calling `suspend` members of a generic class needs the `skie(…)` wrapper, for example
  `try await skie(box).load()`.

Rule of thumb: the Swift-facing API is concrete types. Keep generics inside Kotlin.

## 6. Swift export (Alpha)

[Swift export](https://kotlinlang.org/docs/native-swift-export.html) generates Swift directly instead
of going through Objective-C. Status when this was written: **Alpha** — breaking changes expected.

- Enable with a `swiftExport { moduleName = "Shared"; flattenPackage = "com.example.app" }` block in
  `kotlin { }`, and replace the Xcode run-script task with `embedSwiftExportForXcode`.
- Works only with direct integration (not with XCFramework/SPM distribution).
- Packages are preserved as nested Swift namespaces; primitives are not boxed when nullable;
  `suspend` → `async`, `Flow` → `AsyncSequence`; sealed hierarchies switchable.
- Generic types are largely unsupported; type parameters are erased to their bounds.
- SKIE works on the Objective-C export. Do not plan to combine the two without checking both
  projects' current docs.

Treat Swift export as something to prototype on a branch, not a production dependency, until its
status page says otherwise.
