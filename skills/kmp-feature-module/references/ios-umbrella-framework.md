# iOS umbrella framework (Shape B)

How feature `:logic` modules reach Swift through one framework, and how to prove they did.

## Contents

1. [One framework per app](#1-one-framework-per-app)
2. [`api` plus `export`](#2-api-plus-export)
3. [Export is not transitive](#3-export-is-not-transitive)
4. [Check the header, not the build result](#4-check-the-header-not-the-build-result)
5. [Framework options](#5-framework-options)
6. [Starting the DI graph from Swift](#6-starting-the-di-graph-from-swift)
7. [Handing objects to Swift](#7-handing-objects-to-swift)
8. [XCFramework output](#8-xcframework-output)

## 1. One framework per app

Link exactly one Kotlin framework into an iOS app. Each Kotlin framework embeds its own copy of the
Kotlin runtime and of every Kotlin library it contains. With two frameworks, the same Kotlin class
(say `Note` from `:core:model`) exists twice, Swift sees two unrelated types, and the app pays for
both copies. The umbrella module (`:shared` here) depends on every `:logic` module and is the only
module with `binaries.framework`.

## 2. `api` plus `export`

```kotlin
kotlin {
    listOf(iosArm64(), iosSimulatorArm64()).forEach { target ->
        target.binaries.framework {
            baseName = "Shared"
            export(project(":feature:notes:logic"))
        }
    }
    sourceSets {
        commonMain.dependencies { api(project(":feature:notes:logic")) }
    }
}
```

| You declared | Result |
|---|---|
| `api` and `export` | The module's public API is in the Swift header. Correct. |
| `export` only | The build fails: exported dependencies must be `api` dependencies of the source set. |
| `api` only | Builds everywhere. The header has only the umbrella's own declarations; Swift reports `Cannot find 'NotesListViewModel' in scope`. |
| `implementation` only | Same as `api` only, and Android consumers of `:shared` cannot see the module either. |

Types from a non-exported module that appear in the umbrella's own signatures are still emitted, but
under a module-prefixed name (the familiar `Kotlinx_coroutines_coreFlow` style). If you see those
prefixes for your own modules, an `export` is missing.

Exporting a dependency includes its whole public API and disables dead-code elimination for it, so
export what Swift calls, not everything the umbrella depends on.

## 3. Export is not transitive

`export(project(":feature:notes:logic"))` does not export `:core:model`, even if
`NotesListViewModel` exposes `Note`. Export each module whose types Swift uses by name, and make each
one an `api` dependency.

`transitiveExport = true` exports the whole tree. The Kotlin docs advise against it because it grows
both link time and binary size; prefer an explicit list.

## 4. Check the header, not the build result

A green Gradle build proves nothing about Swift visibility. After linking:

```bash
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64
H=shared/build/bin/iosSimulatorArm64/debugFramework/Shared.framework/Headers/Shared.h
grep -c 'swift_name("NotesListViewModel")' "$H"     # >= 1 means Swift can see it
grep -o 'swift_name("[A-Za-z]*")' "$H" | sort -u | head -50
```

Kotlin classes appear in the header with the framework name as a prefix (`SharedNotesListViewModel`)
and a `swift_name` attribute that gives the Swift name. Release frameworks are under
`releaseFramework/`; the path otherwise matches.

## 5. Framework options

| Option | Guidance |
|---|---|
| `baseName` | The Swift module name (`import Shared`). Changing it breaks every Swift `import`. |
| `isStatic` | Static is the default in the KMP project wizard and the simplest to link. Keep whatever the Xcode project already expects. |
| `binaryOption("bundleId", "com.example.app.shared")` | Sets `CFBundleIdentifier` in the framework's `Info.plist`. Set it when the link warns that it cannot infer a bundle ID; tooling that assembles XCFrameworks has been observed to fail without it. |
| `freeCompilerArgs` / linker options | Copy from an existing framework module only with the comment that explains them. Linker flags in this area (for example system SQLite vs a bundled SQLite) are often load-bearing. |

## 6. Starting the DI graph from Swift

Koin's `get<T>()` is a reified inline function, so Swift cannot call it. Start the graph from Kotlin
and expose small, non-generic accessors.

```kotlin
// shared/src/commonMain/kotlin/com/example/app/shared/SharedModules.kt
val sharedModules: List<Module> = listOf(notesModule, profileModule)

// shared/src/iosMain/kotlin/com/example/app/shared/KoinIos.kt
fun initKoin() {
    startKoin { modules(sharedModules) }
}

class NotesDependencies : KoinComponent {
    fun notesListViewModel(): NotesListViewModel = get()
}
```

```swift
import Shared

@main
struct NotesApp: App {
    // Top-level functions are exported on a class named after the file (KoinIos.kt -> KoinIosKt).
    // Kotlin functions whose names start with "init" get a "do" prefix in Swift.
    init() { KoinIosKt.doInitKoin() }

    var body: some Scene { WindowGroup { NotesListView() } }
}
```

Call `initKoin()` exactly once, before any accessor. Calling `startKoin` twice throws.

## 7. Handing objects to Swift

What the Swift side has to deal with when it receives Kotlin objects:

- `StateFlow` / `Flow` and `suspend` functions: without extra tooling, Swift gets callback-based
  wrappers. [SKIE](https://skie.touchlab.co) turns flows into `AsyncSequence`, suspend functions
  into `async`, and sealed classes into exhaustive Swift enums. If the project already uses SKIE,
  apply it only to the umbrella module.
- Kotlin default arguments are not visible to Swift through the Objective-C header; Swift must pass
  every parameter. Add overloads, or use SKIE's opt-in default-arguments support.
- A Kotlin `ViewModel` held only by Swift is never cleared by an Android lifecycle, so its
  `viewModelScope` keeps running after the screen disappears. Give the Swift wrapper an explicit
  end-of-life path from its `deinit`.

The Swift-side patterns are covered by `kmp-swiftui-interop` in this repo.

## 8. XCFramework output

For distribution (SPM, a separate iOS repository), collect the per-target frameworks into an
XCFramework:

```kotlin
import org.jetbrains.kotlin.gradle.plugin.mpp.apple.XCFramework

kotlin {
    val xcf = XCFramework("Shared")
    listOf(iosArm64(), iosSimulatorArm64()).forEach { target ->
        target.binaries.framework {
            baseName = "Shared"
            export(project(":feature:notes:logic"))
            xcf.add(this)
        }
    }
}
```

This registers `assembleXCFramework`, `assembleSharedDebugXCFramework` and
`assembleSharedReleaseXCFramework`. Packaging and publishing are covered by
`kmp-xcframework-distribution` in this repo; see also the
[Kotlin native binaries guide](https://kotlinlang.org/docs/multiplatform/multiplatform-build-native-binaries.html).
