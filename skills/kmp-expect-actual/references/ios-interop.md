# iOS actuals: Kotlin/Native interop recipes

Recipes for `iosMain` code that calls Apple frameworks. Each one states the opt-in it needs. Imports
are `platform.<Framework>.<Symbol>`, for example `platform.Foundation.NSUserDefaults`,
`platform.UIKit.UIDevice`.

## Contents

1. [Reading Objective-C APIs from Kotlin](#1-reading-objective-c-apis-from-kotlin)
2. [Opt-in annotations](#2-opt-in-annotations)
3. [`NSError` out-parameters](#3-nserror-out-parameters)
4. [`NSData` and `ByteArray`](#4-nsdata-and-bytearray)
5. [File locations](#5-file-locations)
6. [Main thread](#6-main-thread)
7. [Swift-only APIs: implement the interface in Swift](#7-swift-only-apis-implement-the-interface-in-swift)
8. [Testing iOS actuals](#8-testing-ios-actuals)

## 1. Reading Objective-C APIs from Kotlin

- Selectors become methods with named arguments: `setObject:forKey:` is
  `setObject(value, forKey = key)`; `removeItemAtPath:error:` is
  `removeItemAtPath(path, error = errorPointer)`.
- Initializers become constructors: `initWithSuiteName:` is `NSUserDefaults(suiteName = "x")`.
- Singletons are properties: `NSFileManager.defaultManager`, `UIDevice.currentDevice`.
- `NSString` and Kotlin `String` convert automatically; so do `NSArray`/`List` and
  `NSDictionary`/`Map` at API boundaries.
- If an IDE cannot resolve a `platform.*` import, the module probably has no iOS target compiled on
  this host, or the IDE has not indexed the Kotlin/Native distribution yet. Compile once with
  `./gradlew :shared:compileKotlinIosSimulatorArm64`.

## 2. Opt-in annotations

| Annotation | Needed for |
|---|---|
| `kotlinx.cinterop.ExperimentalForeignApi` | Pointers, `memScoped`, `alloc`, `usePinned`, C structs, most APIs with `NSError**` parameters |
| `kotlinx.cinterop.BetaInteropApi` | Some Objective-C helpers, such as certain `create(...)` factory functions and `ObjCObjectVar` |

Put `@OptIn(...)` on the smallest function that needs it. If the compiler asks for an opt-in you did
not expect, read the symbol's declaration rather than adding module-wide opt-ins.

## 3. `NSError` out-parameters

```kotlin
import kotlinx.cinterop.*
import platform.Foundation.NSError
import platform.Foundation.NSFileManager

@OptIn(ExperimentalForeignApi::class, BetaInteropApi::class)
internal fun deleteFile(path: String): Result<Unit> = memScoped {
    val errorRef = alloc<ObjCObjectVar<NSError?>>()
    val deleted = NSFileManager.defaultManager.removeItemAtPath(path, error = errorRef.ptr)
    if (deleted) {
        Result.success(Unit)
    } else {
        Result.failure(IllegalStateException(errorRef.value?.localizedDescription ?: "delete failed"))
    }
}
```

Pass `error = null` only when you will not read the error.

## 4. `NSData` and `ByteArray`

```kotlin
import kotlinx.cinterop.*
import platform.Foundation.NSData
import platform.Foundation.create
import platform.posix.memcpy

@OptIn(ExperimentalForeignApi::class)
internal fun NSData.toByteArray(): ByteArray {
    val size = length.toInt()
    val bytes = ByteArray(size)
    if (size > 0) {
        bytes.usePinned { pinned -> memcpy(pinned.addressOf(0), this.bytes, length) }
    }
    return bytes
}

@OptIn(ExperimentalForeignApi::class, BetaInteropApi::class)
internal fun ByteArray.toNSData(): NSData {
    if (isEmpty()) return NSData()
    return usePinned { pinned -> NSData.create(bytes = pinned.addressOf(0), length = size.toULong()) }
}
```

The empty-array guard matters: `addressOf(0)` on an empty array is out of bounds.

## 5. File locations

```kotlin
import kotlinx.cinterop.ExperimentalForeignApi
import platform.Foundation.NSDocumentDirectory
import platform.Foundation.NSFileManager
import platform.Foundation.NSUserDomainMask

@OptIn(ExperimentalForeignApi::class)
internal fun documentsDirectoryPath(): String {
    val url = NSFileManager.defaultManager.URLForDirectory(
        directory = NSDocumentDirectory,
        inDomain = NSUserDomainMask,
        appropriateForURL = null,
        create = false,
        error = null,
    )
    return requireNotNull(url?.path) { "Documents directory unavailable" }
}
```

Use `NSCachesDirectory` for data the OS may purge, and `NSApplicationSupportDirectory` for app data
the user should not see in the Files app.

## 6. Main thread

Kotlin/Native does not stop you from calling UIKit off the main thread; the result is undefined
behaviour, Main Thread Checker reports in Xcode, or crashes. On iOS, `Dispatchers.Main` is the main
queue:

```kotlin
internal suspend fun showShareSheet(text: String) = withContext(Dispatchers.Main) {
    // UIKit calls only inside this block
}
```

Foundation types such as `NSUserDefaults` and `NSFileManager.defaultManager` are documented as safe
to use from any thread.

## 7. Swift-only APIs: implement the interface in Swift

Kotlin/Native calls Objective-C. APIs that exist only in Swift (WidgetKit's `WidgetCenter`, StoreKit 2,
CryptoKit, SwiftData) are not reachable from `iosMain`. Declare the interface in `commonMain`,
implement it in Swift, and hand the instance to Kotlin at startup.

```kotlin
// commonMain
interface WidgetRefresher {
    fun reloadAll()
}

// iosMain — the iOS app passes its implementation in
fun initKoin(widgetRefresher: WidgetRefresher) {
    startKoin {
        modules(sharedModules + module { single<WidgetRefresher> { widgetRefresher } })
    }
}

// androidMain — bound in the Android platform module instead
internal class AndroidWidgetRefresher(private val context: Context) : WidgetRefresher {
    override fun reloadAll() { /* AppWidgetManager update */ }
}
```

```swift
import Shared
import WidgetKit

final class IosWidgetRefresher: NSObject, WidgetRefresher {
    func reloadAll() { WidgetCenter.shared.reloadAllTimelines() }
}

// At launch. Kotlin functions starting with "init" get a "do" prefix in Swift.
KoinIosKt.doInitKoin(widgetRefresher: IosWidgetRefresher())
```

Keep these interfaces small and synchronous where possible; a Kotlin `suspend` member is awkward to
implement from Swift.

## 8. Testing iOS actuals

`iosSimulatorArm64Test` runs `iosTest` on a simulator, so Foundation APIs behave as in the app. Use a
throwaway store and clean it up:

```kotlin
class IosNoteDraftStoreTest {
    private val suiteName = "note_drafts_test"
    private val defaults = NSUserDefaults(suiteName = suiteName)

    @AfterTest
    fun tearDown() = defaults.removePersistentDomainForName(suiteName)

    @Test
    fun should_returnDraft_when_written() {
        val store = IosNoteDraftStore(defaults)
        store.write(noteId = "1", text = "Buy milk")
        assertEquals("Buy milk", store.read(noteId = "1"))
    }
}
```

This needs a macOS host. On Linux CI the task is skipped or unavailable; report it as `NOT RUN`.
