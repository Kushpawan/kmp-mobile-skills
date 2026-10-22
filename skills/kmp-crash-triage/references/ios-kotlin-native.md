# iOS and Kotlin/Native crash triage — depth

Contents

1. Where crash reports live
2. Reading a report: `.crash` text and `.ips` JSON
3. Symbolicating, and finding the right dSYM
4. Kotlin frames and how Kotlin exceptions crash on iOS
5. Capturing Kotlin stacks: unhandled-exception hook and CrashKiOS
6. Threading crashes
7. Swift ↔ Kotlin casting crashes
8. `SQLITE_MISUSE`: two SQLite copies in one app
9. Watchdog kills and jetsam
10. Legacy memory-model exceptions

## 1. Where crash reports live

| Situation | Where |
|---|---|
| TestFlight and App Store users | Xcode Organizer → Crashes (symbolicated when dSYMs were included at upload). TestFlight users share crashes automatically. |
| A device you can connect | Xcode's device window (Devices and Simulators, or the device hub in newer Xcode) → device logs / crash reports |
| A device you cannot connect | On the device: Settings → Privacy & Security → Analytics & Improvements → Analytics Data. App crashes are named `<AppBinaryName>_<DateTime>`; memory kills `JetsamEvent_<DateTime>`. Share the file. |
| Simulator | `~/Library/Logs/DiagnosticReports/` on the Mac |
| While debugging | Xcode intercepts the crash and **no report is written**. Debug → Detach (or `detach` in LLDB) to let the app finish crashing. |
| Third-party reporter | Crashlytics, Bugsnag, Sentry dashboards — only as good as the dSYMs uploaded to them |
| In-app | MetricKit `MXCrashDiagnostic` / `MXHangDiagnostic` payloads, delivered on a later launch |

Also capture the Xcode console or device log around the crash: Kotlin/Native prints
`Uncaught Kotlin exception: <class>: <message>` followed by the Kotlin stack before aborting.

## 2. Reading a report: `.crash` text and `.ips` JSON

Since iOS 15 / macOS 12, crash reports are `.ips` files: **two JSON objects**. Line 1 is metadata
(`bug_type` `309` means a crash report); the rest is the report. Xcode and Console render it as the
familiar text layout.

Key fields in the report object:

| Field | Meaning |
|---|---|
| `exception.type`, `exception.signal` | e.g. `EXC_CRASH` / `SIGABRT`, `EXC_BAD_ACCESS` / `SIGSEGV` |
| `termination` | who terminated the process and why (watchdog codes appear here) |
| `faultingThread` | index into `threads` of the crashed thread |
| `threads[].frames[]` | `imageIndex` (into `usedImages`), `imageOffset`, `symbol` when symbolicated |
| `usedImages[]` | `name`, `uuid`, `base` (load address), `arch` |
| `lastExceptionBacktrace` | backtrace of an Objective-C / C++ language exception, when there was one |
| `asi` | application-specific information strings |

**JSON numbers are decimal.** Runtime address = `base + imageOffset`; convert to hex before passing
to `atos`. A stdlib-only helper that prints the faulting thread in `atos`-ready form:

```python
# Run with: python3 -I ips_frames.py MyApp-2025-01-01-120000.ips
import json, sys

with open(sys.argv[1]) as f:
    header = json.loads(f.readline())
    report = json.loads(f.read())

if str(header.get("bug_type")) != "309":
    sys.exit(f"not a crash report (bug_type={header.get('bug_type')})")

images = report["usedImages"]
for i, frame in enumerate(report["threads"][report["faultingThread"]]["frames"]):
    image = images[frame["imageIndex"]]
    base = image["base"]
    print(f'{i:3} {image.get("name", "?"):28} uuid={image.get("uuid", "?")} '
          f'load=0x{base:x} addr=0x{base + frame["imageOffset"]:x} {frame.get("symbol", "")}')
```

## 3. Symbolicating, and finding the right dSYM

**Match the UUID first.** Every binary image in the report has a build UUID. The dSYM must have
the same one:

```bash
dwarfdump --uuid MyApp.app.dSYM                     # app (and any static Kotlin framework inside it)
dwarfdump --uuid Shared.framework.dSYM              # dynamic Kotlin framework
mdfind "com_apple_xcode_dsym_uuids == <UUID>"       # find a dSYM on this Mac by UUID
```

Archived builds keep dSYMs inside the `.xcarchive` (`dSYMs/`) under
`~/Library/Developer/Xcode/Archives/`.

**Where the Kotlin code's symbols are:**

- **Dynamic framework** — Kotlin code is its own image in the report (e.g. `Shared`). Kotlin/Native
  produces `<Name>.framework.dSYM` next to release frameworks by default, e.g.
  `shared/build/bin/iosArm64/releaseFramework/Shared.framework.dSYM`. It must be uploaded to the
  crash reporter **in addition to** the app's dSYM.
- **Static framework** — Kotlin code is linked into the app executable, so its frames belong to the
  app image and resolve through the app's dSYM. Confirm by checking that `atos` returns a `kfun:`
  name for one of those frames.

**Tools, from least to most manual:**

```bash
# 1. Open the .ips / .crash in Xcode, or use the Organizer — symbolicates with dSYMs it can find.
# 2. LLDB-based, whole report:
xcrun crashlog MyApp-2025-01-01-120000.ips
# 3. Apple's script for JSON reports (path inside Xcode.app):
#    Contents/SharedFrameworks/CoreSymbolicationDT.framework/Resources/CrashSymbolicator.py
#    It needs every dSYM the report references; see `python3 CrashSymbolicator.py --help`.
python3 CrashSymbolicator.py MyApp.ips -d MyApp.app.dSYM -o symbolicated.ips
# 4. Single addresses. Point -o at the DWARF file inside the dSYM bundle, not the bundle itself.
atos -arch arm64 -o Shared.framework.dSYM/Contents/Resources/DWARF/Shared \
  -l 0x104a6c000 -i 0x104b1f2a8
```

`-i` expands inlined frames; `-dedup` expands `<deduplicated_symbol>` frames from release builds.
OS framework frames need the device symbols for that OS version, which Xcode downloads when the
device is connected.

## 4. Kotlin frames and how Kotlin exceptions crash on iOS

**Kotlin symbols** start with `kfun:`, followed by the package, class, function and signature, for
example:

```text
kfun:com.example.app.notes.NotesRepository#find(kotlin.String){}com.example.app.notes.Note?    member
kfun:com.example.app.notes#toDomain__at__com.example.app.notes.NoteDto(){}com.example.app.notes.Note   extension
kfun:com.example.app.notes.NotesRepository#load#suspend(kotlin.String;kotlin.coroutines.Continuation<com.example.app.notes.Note>){}kotlin.Any?   suspend
```

`nm` and some tools show a leading underscore (`_kfun:`). The exact mangling varies between Kotlin
versions; the package and class always map to a source file. The same names work as LLDB
breakpoints (`b kfun:…`).

**How a Kotlin exception becomes a crash.** An exception that reaches the edge of Kotlin code
uncaught goes to the Kotlin/Native unhandled-exception path: the installed hook runs if there is
one; otherwise the runtime prints `Uncaught Kotlin exception: …` with the Kotlin stack and calls
`abort()`. The report shows `EXC_CRASH (SIGABRT)`. Edges include:

- **A Swift/ObjC call into Kotlin that throws.** Swift has checked errors; Kotlin does not. Only
  exceptions that are instances (or subclasses) of the classes in the function's `@Throws` list
  become an `NSError` / Swift `throws`. Every other exception reaching Swift is unhandled and
  terminates the program.
  - Non-`suspend` function **without** `@Throws`: no Kotlin exception propagates — any throw
    crashes.
  - `suspend` function **without** `@Throws`: only `CancellationException` propagates (as
    `NSError`); anything else crashes.
- **A coroutine root with no handler.** On Kotlin/Native, an exception that escapes a `launch` with
  no `CoroutineExceptionHandler` ends in `processUnhandledException`: the hook runs if set,
  otherwise the app terminates. On Android the same code crashes with a JVM trace through the
  thread's uncaught-exception handler — same bug, different evidence.
- **Top-level `main()` or a `Worker` boundary.**

Because the crash happens where control leaves Kotlin, Apple's crashed-thread backtrace often ends
at the **Swift→Kotlin call site** with `abort()` above it, not at the `throw`. Get the throw site
from the console output, or capture it with a hook (section 5).

**Fix patterns:**

```kotlin
// commonMain — a Swift-facing API that never lets an exception escape.
class NotesFacade(private val repository: NotesRepository) {
    suspend fun loadNote(id: String): NoteResult = try {
        NoteResult.Loaded(repository.load(id))
    } catch (e: CancellationException) {
        throw e                       // must propagate; Swift sees it as an NSError
    } catch (e: NoteNotFoundException) {
        NoteResult.NotFound(id)
    }
}

// Alternative when Swift should use do/catch: declare exactly what can be thrown.
@Throws(NoteNotFoundException::class, CancellationException::class)
suspend fun loadNoteOrThrow(id: String): Note = repository.load(id)
```

Anything not listed still crashes, so `@Throws` is a contract to keep in sync with the
implementation — a result type is harder to get wrong.

## 5. Capturing Kotlin stacks: unhandled-exception hook and CrashKiOS

Crash reporters on iOS record the threads at the moment of the crash, which for Kotlin is the
abort, not the throw. To get the Kotlin stack:

**Your own hook** (Kotlin/Native, `kotlin.native` package, experimental API):

```kotlin
// iosMain — call once at app start, before any Kotlin work runs.
@OptIn(ExperimentalNativeApi::class)
fun installUnhandledExceptionReporting(report: (Throwable) -> Unit) {
    setUnhandledExceptionHook { throwable ->
        report(throwable)                          // log / record as fatal with your reporter
        terminateWithUnhandledException(throwable) // keep the default "crash" behaviour
    }
}
```

`setUnhandledExceptionHook` returns the previous hook, and a new one replaces it. Decide which
component owns the hook — your code or the crash-reporter integration — and install it once. End a
terminating hook with `terminateWithUnhandledException`; a hook that returns normally lets
`processUnhandledException` return, so the app keeps running in whatever state the failure left.

**CrashKiOS** ([touchlab/CrashKiOS](https://github.com/touchlab/CrashKiOS)) records Kotlin crashes
and non-fatals in Firebase Crashlytics or Bugsnag with symbolicated Kotlin frames:

```toml
# gradle/libs.versions.toml — use the latest CrashKiOS release
[versions]
crashkios = "x.y.z"

[libraries]
crashkios-crashlytics = { module = "co.touchlab.crashkios:crashlytics", version.ref = "crashkios" }
crashkios-bugsnag = { module = "co.touchlab.crashkios:bugsnag", version.ref = "crashkios" }
```

```kotlin
// shared/build.gradle.kts — commonMain.dependencies { implementation(libs.crashkios.crashlytics) }

// iosMain — called from the iOS app's startup code, after the Crashlytics SDK is configured.
fun startCrashReporting() {
    enableCrashlytics()                       // switch from no-op to the real implementation
    setCrashlyticsUnhandledExceptionHook()    // record uncaught Kotlin exceptions
}
```

- The iOS app still adds the Crashlytics (or Bugsnag) SDK itself.
- **Dynamic framework:** apply the `co.touchlab.crashkios.crashlyticslink` (or `…bugsnaglink`)
  Gradle plugin to fix undefined-symbol link errors, and add a build phase that uploads the Kotlin
  framework's dSYM with Crashlytics' `upload-symbols`. Static frameworks need neither.
- Bugsnag uses `startBugsnag(config)` and `enableBugsnag()` instead.

## 6. Threading crashes

- **UIKit off the main thread.** A Kotlin callback, completion handler or flow emission delivered
  on a background thread into Swift code that touches UI. In debug, Xcode's Main Thread Checker
  (scheme → Run → Diagnostics) reports it (*typical*: "Main Thread Checker: UI API called on a
  background thread"); in release it shows up as random UI corruption or `EXC_BAD_ACCESS`. Do not
  assume which thread a Kotlin callback arrives on — hop to the main actor in Swift, or emit UI
  state on `Dispatchers.Main` in Kotlin.
- **Swift runtime isolation checks.** In the Swift 6 language mode, a closure isolated to
  `@MainActor` that is invoked from another thread can trap at runtime (top frame *typically*
  `_dispatch_assert_queue_fail`). Kotlin calling a Swift closure from `Dispatchers.Default` is a
  common way to get there.
- **Deinit on the GC thread.** Swift/ObjC objects referenced from Kotlin are released only after a
  Kotlin GC. Their `deinit` runs on the main thread if they were passed to Kotlin on the main
  thread; it runs on a GC thread if they were passed on another thread or if the main queue is not
  being processed. A view or view controller released there can crash in UIKit. Pass UI objects to
  Kotlin on the main thread only — better, do not let Kotlin hold UI objects. The
  `kotlin.native.binary.objcDisposeOnMain` Gradle property controls this behaviour.

## 7. Swift ↔ Kotlin casting crashes

A failed `as!` or a force-unwrapped `nil` traps: `EXC_BREAKPOINT (SIGTRAP)` on arm64, with the
Swift line in frame 0, and the console *typically* says `Could not cast value of type '…' to '…'`.
Kotlin-specific ways to get there:

- Generic types lose their type arguments in the Objective-C header (variance in particular), so
  Swift sees `Any` or a base type and force-casts.
- Kotlin numbers inside generics and lambdas arrive as boxed `KotlinInt`, `KotlinLong`, … (subclasses
  of `NSNumber`), not Swift `Int32` / `Int64`.
- Sealed classes are a class hierarchy in Swift; a `switch` that force-casts to the expected
  subclass breaks when a new subclass is added. SKIE can expose sealed hierarchies as exhaustive
  Swift enums.

Fix with `as?` and an explicit fallback, or expose a concrete, non-generic type from Kotlin for the
Swift caller.

## 8. `SQLITE_MISUSE`: two SQLite copies in one app

Room KMP's `BundledSQLiteDriver` compiles SQLite into your binary. `NativeSQLiteDriver` (and
SQLDelight's native driver) use the system library, which is why their setup adds the `-lsqlite3`
linker option. An app should link **one** SQLite.

Observed failure (one production app, release builds on iOS 26): a framework using
`BundledSQLiteDriver` shipped in an app that also linked system SQLite — `-lsqlite3` had been added
for a *different* framework that used the native driver. Room calls failed with `SQLITE_MISUSE`
(error code 21; *typical* message "bad parameter or other API misuse") and crashed. The team's
analysis was that the linker bound `sqlite3_*` calls to the system library instead of the bundled
copy; removing `-lsqlite3` from the binary that used the bundled driver fixed it. Treat the
mechanism as a strong hypothesis, not documented behaviour; the checks below tell you whether you
are exposed.

```bash
# Is system SQLite linked into the app?
otool -L MyApp.app/MyApp | grep -i sqlite
# Does the Kotlin framework define its own sqlite3 symbols (bundled), or import them?
nm -gU Shared.framework/Shared | grep -c ' _sqlite3_'     # defined here
nm -u  Shared.framework/Shared | grep ' _sqlite3_'        # expected from another image
# Who adds -lsqlite3?
grep -rn "lsqlite3" --include='*.kts' --include='*.pbxproj' --include='*.xcconfig' --include='Package.swift' .
```

For a static framework, run the `nm` checks on the final app executable. If two parts of the app
genuinely need different drivers, move them to the same driver; verify any linker workaround on a
release build on a real device, because debug builds and simulators may not show the failure.

Other `SQLITE_MISUSE` causes are ordinary bugs: using a connection or statement after closing it,
or using one connection from several threads in a way the driver does not allow.

## 9. Watchdog kills and jetsam

- **Watchdog:** `EXC_CRASH (SIGKILL)`, `Termination Reason: Namespace SPRINGBOARD, Code 0x8badf00d`.
  The main thread was blocked too long at launch, resume or during a scene transition. Look at the
  main thread's backtrace for synchronous I/O, a `runBlocking`-style bridge, a lock, or Kotlin
  initialisation done eagerly at startup (DI graph, database open). Fix with
  `mobile-performance-fix`.
- **Jetsam:** the OS killed the app for memory. There is no crash report — look for
  `JetsamEvent_<DateTime>` logs and Organizer's memory metrics. Investigate growth with
  `mobile-performance-fix` (memory section).

Neither appears in Organizer's Crashes list; check the device's Analytics Data, MetricKit, or
Organizer's other metrics.

## 10. Legacy memory-model exceptions

`InvalidMutabilityException`, `IncorrectDereferenceException`, `FreezingException` and
`freeze()` belong to the old Kotlin/Native memory model, which was removed from the compiler in
Kotlin 1.9.20. Seeing them means the app (or a library in it) is built with a very old Kotlin
version: upgrade before investigating further.
