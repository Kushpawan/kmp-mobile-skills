# Android crash triage — depth

Contents

1. Getting the trace
2. Reading a JVM crash
3. Deobfuscating R8 stack traces
4. Release-only crashes
5. Common crash signatures in KMP apps on Android
6. ANRs
7. Native crashes and tombstones
8. Why the process died: `ApplicationExitInfo`

## 1. Getting the trace

```bash
adb logcat -b crash -d > crash.txt          # the crash buffer only: uncaught exceptions, native crashes
adb logcat -d -v threadtime > full.txt      # everything, for context around the crash
adb bugreport bugreport.zip                 # full device state, includes ANR traces and tombstones
```

`-d` dumps and exits; drop it to stream while you reproduce. Clear old output first with
`adb logcat -c` so the file holds one crash.

Production sources:

- **Play Console → Android vitals → Crashes and ANRs** (menu names change over time). Clusters by
  signature, with OS / device breakdowns. Deobfuscated automatically when Play has the mapping
  file for that version.
- **Firebase Crashlytics / Bugsnag / Sentry.** Check that the dashboard shows the same version and
  build you are investigating, and whether the issue is fatal or non-fatal.

## 2. Reading a JVM crash

```text
E AndroidRuntime: FATAL EXCEPTION: main
E AndroidRuntime: Process: com.example.app, PID: 12345
E AndroidRuntime: java.lang.IllegalStateException: Note n42 not found
E AndroidRuntime:   at com.example.app.notes.NotesRepository.require(NotesRepository.kt:88)
E AndroidRuntime:   at com.example.app.notes.EditNoteViewModel$load$1.invokeSuspend(EditNoteViewModel.kt:41)
E AndroidRuntime:   at kotlin.coroutines.jvm.internal.BaseContinuationImpl.resumeWith(...)
E AndroidRuntime:   at kotlinx.coroutines.DispatchedTask.run(...)
E AndroidRuntime:   ...
E AndroidRuntime: Caused by: ...
```

- `FATAL EXCEPTION: <thread>` names the thread. `main` means the UI thread.
- Read **down to the last `Caused by:`** — that is the original failure; everything above wraps it.
  `... 12 more` means the remaining frames equal the enclosing trace's.
- Find the first frame in your package. Kotlin from `commonMain` and `androidMain` both appear as
  ordinary JVM frames; the file name tells you which source file, the path tells you which set.
- `invokeSuspend` + `kotlinx.coroutines.DispatchedTask.run` means the exception escaped a coroutine.
  The cause is in the coroutine body; the *crash* happened because no handler caught it. On iOS
  the same bug aborts the process instead of producing this trace.

## 3. Deobfuscating R8 stack traces

The mapping file is written to `<module>/build/outputs/mapping/<variant>/mapping.txt` and is
**overwritten on every build** — archive one copy per released build.

```bash
# retrace ships with the Android SDK command-line tools (cmdline-tools/<version>/bin)
$ANDROID_HOME/cmdline-tools/latest/bin/retrace \
  app/build/outputs/mapping/release/mapping.txt crash.txt
# With no stack-trace file, retrace reads stdin (end with Ctrl+D).
```

Options include `--verbose` (method signatures) and `--regex` for unusual log formats.

Where mapping files reach the consoles:

- **Play:** with an Android App Bundle built by AGP 4.1 or later, Play takes the mapping from the
  bundle. APK uploads need the file uploaded manually in App bundle explorer → Downloads.
- **Crashlytics:** the Crashlytics Gradle plugin uploads the mapping for minified variants;
  `firebaseCrashlytics.mappingFileUploadEnabled = false` turns that off (stacks then stay
  obfuscated).
- **Android Studio:** Logcat deobfuscates automatically from Android Studio Otter 3 Feature Drop
  with AGP 9.0; older setups need `retrace`.

Line numbers: AGP 8.6+ retraces file names and line numbers by default for all `minSdk` values. On
older AGP, check that your rules do not strip `SourceFile` / `LineNumberTable` attributes if you
need lines.

## 4. Release-only crashes

When a crash appears only in `release`, suspect, in order:

1. **R8 removed or renamed something used reflectively** — class lookups by name, `enumValueOf`
   with names from the server, JSON libraries that use reflection, `Class.forName` in a library.
   kotlinx.serialization ships consumer rules for the common cases; serializers looked up by name
   (named companion objects, some polymorphic setups) are the usual gaps — check the library's
   Android/R8 notes for your version. Typical message:
   `Serializer for class 'NoteDto' is not found.`
2. **Optimisation changed timing** — a race that the slower debug build hid.
3. **Different configuration** — release base URL, logging off, a flag default.

Reproduce with the same variant (`./gradlew :composeApp:installRelease`, which needs a signing
config for release, or a `staging` flavour with minify on) rather than reasoning from the debug
build.

## 5. Common crash signatures in KMP apps on Android

Messages marked *typical* vary by library version — match on the exception class.

| Exception | Usual cause in a KMP app | Where to look |
|---|---|---|
| `NoSuchMethodError`, `NoClassDefFoundError`, `AbstractMethodError` | Two modules compiled against different versions of the same library (binary incompatibility), or a stale published artifact | `./gradlew :composeApp:dependencies` for version conflicts; rebuild with aligned versions |
| `IllegalStateException: Module with the Main dispatcher is missing` | `kotlinx-coroutines-android` missing or version-mismatched with `-core` | Version catalog alignment |
| Koin `NoDefinitionFoundException` (*typical*: "No definition found for type …") | A constructor gained a parameter, or a module is not loaded | The module list passed to `startKoin` |
| `SerializationException`, `MissingFieldException`, `JsonDecodingException` | API shape differs from the DTO: missing field without default, unknown key, wrong type | The DTO; `ignoreUnknownKeys`, defaults, nullable fields |
| `CalledFromWrongThreadException: Only the original thread that created a view hierarchy can touch its views.` | View/UI work from a background coroutine | Collect UI state on `Dispatchers.Main` |
| `ClassCastException` after returning to the app | Restored state after process death has a different type than assumed | `SavedStateHandle` keys, navigation arguments |
| `TransactionTooLargeException` | Too much data in a `Bundle` (saved state, intent extras) | Store IDs, not objects |
| `ForegroundServiceStartNotAllowedException` | Starting a foreground service from the background on Android 12+ | WorkManager or an allowed exemption |
| `SecurityException` | Missing runtime permission, or a permission revoked while running | The permission check before the call |
| `OutOfMemoryError` | Bitmaps, unbounded caches, a leak | `mobile-performance-fix` memory section |

## 6. ANRs

Diagnosis of ANR traces is covered by the
[android/skills `performance/anr-audit-and-fix`](https://github.com/android/skills/tree/main/performance/anr-audit-and-fix)
skill — use it rather than duplicating it here. Where the traces are:

- Play Console Android vitals (ANR clusters with main-thread stacks).
- `adb bugreport` zip, under `FS/data/anr/`.
- `ApplicationExitInfo` with `REASON_ANR` and `getTraceInputStream()` (section 8).

KMP-specific causes worth checking first:

- `runBlocking` on the main thread, often inside a helper written to make a suspend API callable
  from Java or from Android lifecycle callbacks.
- Database or file I/O dispatched on `Dispatchers.Main` because a repository uses the caller's
  context instead of an injected I/O dispatcher.
- A user gesture that synchronously waits for a whole background sync queue to drain (see
  `mobile-performance-fix`).

## 7. Native crashes and tombstones

A native crash shows in logcat as a block that starts with a line of asterisks and
`Fatal signal 11 (SIGSEGV)` (or `SIGABRT`, `SIGBUS`), followed by a backtrace of `.so` frames. The
full tombstone is in the bug report zip (`FS/data/tombstones/`).

Symbolicate with `ndk-stack` against the **unstripped** libraries:

```bash
adb logcat | $ANDROID_NDK_HOME/ndk-stack -sym app/build/intermediates/cxx/RelWithDebInfo/<hash>/obj/arm64-v8a
$ANDROID_NDK_HOME/ndk-stack -sym <dir-with-unstripped-.so> -dump crash.txt
```

Keep the leading asterisk line when copying a trace; `ndk-stack` needs it. For Play, upload native
debug symbols (or include them in the bundle) so vitals can symbolicate.

In KMP apps the native code is usually not yours: it comes from libraries such as the bundled
SQLite driver (JNI), image codecs or crypto. Note the library and version from the frame, check
its issue tracker, and look for a call pattern from your code (for example using a database
connection after closing it, or from many threads without the library's threading rules).

## 8. Why the process died: `ApplicationExitInfo`

On Android 11 (API 30) and later, the app can ask why previous processes ended — crashes, ANRs,
native crashes, low-memory kills — and upload that on next launch. This catches deaths that leave
no crash-reporter event, such as low-memory kills.

```kotlin
// androidMain or the Android host app: read on startup, report through your logger or reporter.
val activityManager = context.getSystemService(ActivityManager::class.java)
val exits = activityManager.getHistoricalProcessExitReasons(context.packageName, 0, 5)
for (exit in exits) {
    // exit.reason: REASON_CRASH, REASON_CRASH_NATIVE, REASON_ANR, REASON_LOW_MEMORY, ...
    // exit.getTraceInputStream() holds the ANR trace or native tombstone when available.
    logger.w { "Previous exit: reason=${exit.reason} desc=${exit.description} at=${exit.timestamp}" }
}
```

Guard the call with `Build.VERSION.SDK_INT >= Build.VERSION_CODES.R` when `minSdk` is lower.
