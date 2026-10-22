---
name: kmp-expect-actual
description: Use when Kotlin Multiplatform shared code needs a platform API or platform-specific behaviour - expect/actual declarations, a missing or "no corresponding actual declaration" error, androidMain or iosMain implementations, platform.Foundation or platform.UIKit interop, Android Context in shared code, the expect/actual classes Beta warning (-Xexpect-actual-classes), or choosing between expect/actual and an interface bound in DI.
license: Apache-2.0
compatibility: Kotlin Multiplatform Gradle project on Kotlin 2.x. Compiling iosMain needs macOS with Xcode.
metadata:
  category: build
  platforms: android, ios
---

# KMP expect/actual and platform abstractions

Shared code says *what* it needs in `commonMain`; each platform says *how*. Default to an interface
in `commonMain` with one implementation per platform, bound in DI. Use `expect`/`actual` for small
leaf functions, factories, properties and type aliases. Before either, check whether the standard
library or a KMP library the project already uses does the job.

## When to use

- `commonMain` code needs something only a platform has: storage, device info, files, sensors,
  biometrics, haptics, system services.
- A build fails because an `expect` has no `actual` for one target.
- Deciding between `expect class`, `expect fun` and an interface.
- Android code in `commonMain` needs a `Context`, or iOS code needs Foundation/UIKit.

## When not to use

- Creating the module that will hold the code: `kmp-feature-module`.
- Adding the library that would make the abstraction unnecessary: `kmp-gradle-version-catalog`.
- Swift calling into Kotlin, or Kotlin flows and suspend functions seen from Swift: `kmp-swiftui-interop`.
- Auditing all expect/actual pairs in a module: `kmp-module-health`.

## Step 0 — Read the project first

```bash
grep -rnE '^\s*(public |internal )?expect (fun|val|var|class|object|interface|enum|annotation)' \
  --include='*.kt' . | grep -v /build/                           # existing expect declarations
grep -rnE 'actual (fun|val|class|object|typealias)' --include='*.kt' . | grep -v /build/ | head -40
find . -type d -name '*Main' -path '*/src/*' -not -path '*/build/*' \
  | sed -E 's#.*/src/##' | sort | uniq -c                       # source sets in use
grep -rnE 'platformModule|expect val .*Module' --include='*.kt' .   # platform DI modules
grep -rn 'Xexpect-actual-classes' --include='*.gradle.kts' .
grep -rnE 'androidContext\(|applicationContext|lateinit var .*Context' --include='*.kt' . | head
```

| Record | Why it matters |
|---|---|
| Existing pattern: `expect fun` factories, interfaces bound in DI, or both | Write the new abstraction the same way |
| File naming: `X.kt` / `X.android.kt` / `X.ios.kt`, or another suffix | Match it; see Quick reference for why suffixes matter |
| Intermediate source sets: `iosMain`, `appleMain`, `nativeMain` | Put iOS actuals in the shared `iosMain`, not per-architecture sets |
| How Android gets a `Context`: Koin `androidContext()`, a holder set in `Application`, `androidx.startup` | Reuse it; never add a second mechanism |
| DI framework and where platform bindings live | Bind the new implementation next to the existing ones |
| KMP libraries already present (DataStore, multiplatform-settings, kotlinx-io, Okio, kotlinx-datetime) | They may already solve the problem |
| Whether `-Xexpect-actual-classes` is set | Tells you if `expect class` is an accepted idiom here |

## Decision table

| Need | Use | Stability |
|---|---|---|
| A value or pure function with no state and no need for a fake (platform name, a constant) | `expect fun` / `expect val` | Stable |
| A service with several members, state, a `Context` or view controller, or a fake in tests | `interface` in `commonMain` + `class` per platform, bound in DI | Stable (plain Kotlin) |
| A platform type that already matches the API 1:1 | `expect class` + `actual typealias` | Beta |
| A singleton with no constructor parameters | Usually an interface + DI `single`; `expect object` only if the project does this already | Beta |
| An annotation needed on some platforms only (for example a parcelize marker) | `@OptionalExpectation expect annotation class` | Beta (opt-in) |
| The iOS side needs a Swift-only API (WidgetKit, StoreKit 2, CryptoKit) | `interface` in `commonMain`, implemented in Swift, passed in at startup | Stable |

Expected and actual *classes* — which includes objects, interfaces, enums, annotations and actual type
aliases — are Beta; the compiler warns until you add `-Xexpect-actual-classes`. The Kotlin docs
recommend interfaces in simple cases because they allow more than one implementation per platform
and trivial fakes in tests.

## Workflow

### 1. Look for an existing solution

Check, in order: the Kotlin standard library (for example `kotlin.uuid.Uuid` since 2.0.20 and
`kotlin.time.Clock` since 2.1.20, both opt-in in the versions that introduced them), kotlinx
libraries, KMP libraries already in the catalog, then [klibs.io](https://klibs.io). Done when you can
name why none fits. If one fits, stop and use it.

### 2. Write the common contract

Put it in the package of the layer that owns the need (`data/`, `platform/`), never in a catch-all
`Platform.kt`. Use only common types in signatures — no `Context`, `NSURL`, `File` or `UIImage`. Make
I/O `suspend` or `Flow`-returning when the platform call can block.

```kotlin
// commonMain/kotlin/com/example/app/notes/data/NoteDraftStore.kt
/** Keeps unsaved note text across process death. Platform-backed; use a fake in tests. */
interface NoteDraftStore {
    fun read(noteId: String): String?
    fun write(noteId: String, text: String)
    fun clear(noteId: String)
}
```

Done when `commonMain` compiles against the interface alone.

### 3. Write the Android implementation

```kotlin
// androidMain/kotlin/com/example/app/notes/data/NoteDraftStore.android.kt
internal class AndroidNoteDraftStore(context: Context) : NoteDraftStore {
    // A singleton must never hold an Activity: keep only the application context.
    private val prefs = context.applicationContext
        .getSharedPreferences("note_drafts", Context.MODE_PRIVATE)

    override fun read(noteId: String): String? = prefs.getString(key(noteId), null)
    override fun write(noteId: String, text: String) { prefs.edit().putString(key(noteId), text).apply() }
    override fun clear(noteId: String) { prefs.edit().remove(key(noteId)).apply() }

    private fun key(noteId: String) = "draft_$noteId"
}
```

The `Context` arrives through the constructor from DI. Other ways to get one, and what to do when an
API needs an `Activity`, are in [references/android-context.md](references/android-context.md).

### 4. Write the iOS implementation

```kotlin
// iosMain/kotlin/com/example/app/notes/data/NoteDraftStore.ios.kt
import platform.Foundation.NSUserDefaults

internal class IosNoteDraftStore(
    private val defaults: NSUserDefaults = NSUserDefaults(suiteName = "note_drafts"),
) : NoteDraftStore {
    override fun read(noteId: String): String? = defaults.stringForKey(key(noteId))
    override fun write(noteId: String, text: String) = defaults.setObject(text, forKey = key(noteId))
    override fun clear(noteId: String) = defaults.removeObjectForKey(key(noteId))

    private fun key(noteId: String) = "draft_$noteId"
}
```

Objective-C selectors become Kotlin names with named arguments (`setObject:forKey:` is
`setObject(value, forKey = key)`). APIs that take pointers, `NSError**` out-parameters or C structs
need `@OptIn(ExperimentalForeignApi::class)`; recipes for those, `NSData` conversion and main-thread
rules are in [references/ios-interop.md](references/ios-interop.md). Done when
`compileKotlinIosSimulatorArm64` passes.

### 5. Bind each implementation in DI

```kotlin
// commonMain
expect val platformDataModule: Module

// androidMain — androidContext() comes from koin-android and needs
// startKoin { androidContext(this@NotesApplication) } in the Application.
actual val platformDataModule: Module = module {
    single<NoteDraftStore> { AndroidNoteDraftStore(androidContext()) }
}

// iosMain
actual val platformDataModule: Module = module {
    single<NoteDraftStore> { IosNoteDraftStore() }
}
```

Add `platformDataModule` to the module list the app already starts. If the project binds platform
classes another way (a per-platform module list passed to `initKoin`, kotlin-inject components),
follow it. Done when both apps start and resolve `NoteDraftStore`.

### 6. Fake it and test it

```kotlin
// commonTest
class FakeNoteDraftStore : NoteDraftStore {
    private val drafts = mutableMapOf<String, String>()
    override fun read(noteId: String) = drafts[noteId]
    override fun write(noteId: String, text: String) { drafts[noteId] = text }
    override fun clear(noteId: String) { drafts.remove(noteId) }
}
```

Every consumer of `NoteDraftStore` is tested in `commonTest` with the fake. Test the real
implementations only where their behaviour is the point: `iosSimulatorArm64Test` can use a throwaway
`NSUserDefaults` suite; Android needs a host test with Robolectric or a device test. Done when the
consumer's tests pass on both an Android and an iOS test task.

### 7. Compile every target

The compiler checks that each `expect` has an `actual` only for targets it compiles. A build that
never compiles iOS will not notice a missing iOS actual. Run the Verify commands for every target the
module declares.

## Smaller shapes

```kotlin
// expect fun — stateless, no fake needed
// commonMain/.../Platform.kt
expect fun platformName(): String
// androidMain/.../Platform.android.kt
actual fun platformName(): String = "Android ${android.os.Build.VERSION.SDK_INT}"
// iosMain/.../Platform.ios.kt
actual fun platformName(): String =
    UIDevice.currentDevice.systemName() + " " + UIDevice.currentDevice.systemVersion
```

```kotlin
// expect class + actual typealias — Beta, needs -Xexpect-actual-classes
// commonMain
expect class PlatformLock() {
    fun lock()
    fun unlock()
}
// androidMain: an existing JVM class with matching members
actual typealias PlatformLock = java.util.concurrent.locks.ReentrantLock
// iosMain
actual class PlatformLock actual constructor() {
    private val delegate = NSRecursiveLock()
    actual fun lock() = delegate.lock()
    actual fun unlock() = delegate.unlock()
}
```

The lock is only an illustration of the syntax; `kotlinx.atomicfu` already ships multiplatform locks.

```kotlin
// build.gradle.kts — only when the project accepts expect/actual classes
kotlin {
    compilerOptions { freeCompilerArgs.add("-Xexpect-actual-classes") }
}
```

## Quick reference

| Item | Rule |
|---|---|
| Files | `NoteDraftStore.kt` (common), `NoteDraftStore.android.kt`, `NoteDraftStore.ios.kt` |
| Why the suffix | Top-level declarations in `Platform.kt` compile to a JVM facade class `PlatformKt`; if same-named files in `commonMain` and `androidMain` both hold non-expect top-level code, the Android build fails with a duplicate JVM class name |
| Package | An `actual` must be in the same package as its `expect` |
| iOS location | `iosMain` (shared by `iosArm64`, `iosSimulatorArm64`, `iosX64`), not `iosArm64Main` |
| Android location | `androidMain` |
| Expect content | Signatures only, no bodies, no default implementations |
| Platform imports | `android.*`, `java.*`, `platform.*` only in platform source sets |
| iOS opt-ins | `ExperimentalForeignApi` for pointers and C interop; `BetaInteropApi` for some Objective-C helpers |
| Context | Application context only, injected; never an `Activity` in a long-lived object |

## Verify

Report each as `PASS`, `FAIL` or `NOT RUN` (with the reason, e.g. "no macOS host"). Never report a
check that did not run as passed. Replace `:shared` with the module you changed.

```bash
./gradlew :shared:compileCommonMainKotlinMetadata        # common code has no platform leaks
./gradlew :shared:compileAndroidMain                     # AGP KMP plugin (legacy: compileDebugKotlinAndroid)
./gradlew :shared:compileKotlinIosSimulatorArm64         # macOS only
./gradlew :shared:compileKotlinIosArm64                  # device target, macOS only
./gradlew :shared:testAndroidHostTest                    # legacy plugin: testDebugUnitTest
./gradlew :shared:iosSimulatorArm64Test                  # macOS only
grep -rnE '^import (android|java|javax|platform)\.' shared/src/commonMain   # expect no output
```

If `iosX64` is declared, also run `compileKotlinIosX64`. Then launch both apps and exercise the
feature once; DI binding errors only show at runtime.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| `expect class` with many members where an interface would do | No fakes, one implementation per platform, Beta warnings | Interface + per-platform class + DI |
| `actual` in a different package or with a different signature | "no actual declaration" for that target | Same package, same name, same parameter and return types |
| iOS `actual` only in `iosArm64Main` | Device builds pass; simulator builds fail | Move it to `iosMain` |
| `actual` only checked on Android | iOS failure surfaces on CI or a teammate's Mac | Compile `iosSimulatorArm64` before pushing |
| Same file name in `commonMain` and `androidMain` | Duplicate JVM class name (`PlatformKt`) | Use the `.android.kt` / `.ios.kt` suffix |
| Storing an `Activity` in a singleton actual | Memory leak and crashes after rotation | Keep `applicationContext`; see the Android reference for Activity-bound APIs |
| `expect fun` that needs a `Context` | No way to pass it without a global | Switch to an interface with constructor injection |
| Calling UIKit off the main thread | Undefined behaviour, Main Thread Checker reports, crashes | `withContext(Dispatchers.Main)` around UIKit calls |
| Platform types in the common signature | Leaks into every caller; blocks other targets | Common types only; convert inside the actual |
| Writing an abstraction the stdlib already has | Extra code to maintain on two platforms | Step 1: check stdlib and existing libraries first |
| Kotlin cannot see a Swift-only API | Kotlin/Native calls Objective-C, not Swift-only symbols | Implement the interface in Swift; see the iOS reference |

## Related skills

- `kmp-feature-module` — where the abstraction's module lives and how it reaches iOS.
- `kmp-module-health` — inventory every expect/actual pair in a module.
- `kmp-swiftui-interop` and `kmp-testing-patterns` in this repo — the Swift side and the test side.
- [chrisbanes/skills `kotlin-api-design`](https://github.com/chrisbanes/skills/tree/main/skills/kotlin-api-design) — API shape and KMP platform boundaries.
- [Kotlin docs: expected and actual declarations](https://kotlinlang.org/docs/multiplatform/multiplatform-expect-actual.html)
  and [hierarchical project structure](https://kotlinlang.org/docs/multiplatform/multiplatform-hierarchy.html).
