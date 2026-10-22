---
name: kmp-crash-triage
description: Use when a Kotlin Multiplatform app crashes, hangs or is killed on Android or iOS — FATAL EXCEPTION, ANR, SIGABRT, SIGSEGV, EXC_BAD_ACCESS, EXC_BREAKPOINT, "Uncaught Kotlin exception", kfun: frames, an unsymbolicated .ips or .crash file, a tombstone, an obfuscated R8 stack trace, a Crashlytics, Bugsnag or Play Console vitals crash cluster, missing dSYM or mapping.txt, or SQLITE_MISUSE on iOS.
license: Apache-2.0
compatibility: Kotlin Multiplatform app with Android and iOS targets. Android steps need adb and the Android SDK command-line tools; iOS steps need macOS with Xcode command-line tools (xcrun, atos, dwarfdump).
metadata:
  category: debug
  platforms: android, ios
---

# Kotlin Multiplatform crash triage

A crash is fixed only when you can point at the line that caused it, explain why, and show a test
or reproduction that no longer crashes. Get a **readable** stack first — deobfuscated on Android,
symbolicated on iOS — because most wrong crash fixes start from a stack nobody could read.

## When to use

- A crash, ANR, hang or watchdog kill on Android or iOS, from a user, QA, a crash reporter or the
  store consoles.
- A stack trace that is obfuscated (`a.b.c(Unknown Source)`), unsymbolicated (hex addresses only), or
  ends in `abort()` with no hint of the Kotlin code that threw.
- Crashes that happen only in release builds, only on iOS, or only after an upgrade.

## When not to use

- The app does not crash but shows wrong data or behaviour → `mobile-bug-fix`.
- The app is slow or the main thread is busy but nothing is killed → `mobile-performance-fix`.
  ANRs and iOS watchdog kills start here, then move there once the blocking call is known.
- A test fails intermittently → `kmp-flaky-test-triage`.
- The build or link fails → `kmp-build-failure-triage`.

## Step 0 — Read the project first

Find out how crashes are captured and how symbols get to the reporter. Most "unreadable crash"
problems are configuration problems.

1. **Crash reporter per platform.** Search Gradle files, `Info.plist`, the iOS app delegate and the
   Android `Application` for Firebase Crashlytics, Bugsnag, Sentry or an in-house reporter. Note
   whether Kotlin exceptions on iOS are captured with CrashKiOS, the Sentry KMP SDK, or a custom
   `setUnhandledExceptionHook`.
2. **Android release config.** Is `isMinifyEnabled` true for release? Where does `mapping.txt` get
   uploaded (Play via the app bundle, `firebaseCrashlytics.mappingFileUploadEnabled`)? Are native
   debug symbols uploaded for any `.so`?
3. **iOS framework.** Framework name, static or dynamic (`isStatic = true` in
   `binaries.framework {}`), and how it is embedded. Does the Xcode target build
   `DWARF with dSYM File` for Release, and does a build phase upload dSYMs (including the Kotlin
   framework's dSYM when it is dynamic)?
4. **Swift-facing API.** Which Kotlin functions does Swift call, and do they carry `@Throws`? Which
   coroutine scopes or flows are started on behalf of Swift?
5. **SQLite.** Which driver: Room `BundledSQLiteDriver`, Room `NativeSQLiteDriver`, SQLDelight's
   native driver? Search for `-lsqlite3` in Gradle `linkerOpts`, Xcode `OTHER_LDFLAGS` and SPM
   `linkerSettings` across **all** frameworks the app links.
6. **Logger and breadcrumbs.** The project's logger (Kermit, Napier or other) and whether it forwards
   to the crash reporter.

## Workflow

### 1. Collect

Get one **complete** report per distinct crash signature, with the exact build that produced it.

| Source | Android | iOS |
|---|---|---|
| Your device / emulator | `adb logcat -b crash -d` | Xcode console (`Uncaught Kotlin exception: …`), crash report from the device |
| Testers | bug report zip (`adb bugreport`) | `.ips` from Settings → Privacy & Security → Analytics & Improvements → Analytics Data |
| Production | Play Console Android vitals, Crashlytics / Bugsnag / Sentry | Xcode Organizer → Crashes, the crash reporter |

For each signature record: app version **and** build number, OS version, device model, affected
users or count, first version seen, and whether it is foreground or background.

Done when you have the full text — every `Caused by:` on Android; the whole report including the
**Binary Images** section (or `usedImages` in `.ips`) on iOS. Platform details:
[references/android.md](references/android.md) and
[references/ios-kotlin-native.md](references/ios-kotlin-native.md).

### 2. Make the stack readable

- **Android:** deobfuscate with the `mapping.txt` from **that exact build** using R8 `retrace`. A
  mapping from another build gives confident, wrong names.
- **iOS:** symbolicate with the dSYM whose UUID matches the crashed binary
  (`dwarfdump --uuid` vs. the Binary Images UUID). Use Xcode, `xcrun crashlog`, or `atos` for single
  addresses. A dynamic Kotlin framework has its **own** dSYM; a static one is inside the app's.

Done when your own frames show function names (ideally file and line). If symbols are missing,
fix the upload for the next release and say so — do not guess from addresses.

### 3. Classify the signature

Use the table in [Quick reference](#quick-reference). The class decides where to look: a JVM
exception has its cause in the trace; a Kotlin exception that escaped to Swift shows the abort at
the call site; a Swift trap points at a force-unwrap or cast; a watchdog or ANR is a blocked main
thread; a jetsam event is memory.

### 4. Locate the frame in shared vs platform code

Walk the crashed thread from the top and find the **first frame in your code**. Skip OS, runtime
and library frames — but note which library called into your code.

- Kotlin on Android appears as normal JVM frames (`NotesRepository.kt:42`), whichever source set it
  came from — check the file's path to tell `commonMain` from `androidMain`.
- Kotlin on iOS appears as `kfun:` symbols, e.g.
  `kfun:com.example.app.notes.NotesRepository#find(kotlin.String){}com.example.app.notes.Note?`.
  The package and class map straight to a source file.
- For an **uncaught Kotlin exception** on iOS, Apple's crashed thread shows where Swift/ObjC called
  into Kotlin, not where Kotlin threw. The throw site is in the `Uncaught Kotlin exception:` console
  output or in the Kotlin stack a reporter records through an unhandled-exception hook.

Done when you can name the file and function, and say whether it is `commonMain`, a platform
`actual`, Swift, or the Android host app.

### 5. Reproduce

Same build type as the crash (release when the crash is release-only). Drive the path from the
breadcrumbs; force the preconditions the report suggests: no network, process death (Android:
"Don't keep activities", or `adb shell am kill <package>` while backgrounded), rotation, low
memory, upgrade from the previous version with existing data. If a reproduction on a device is
impractical, recreate the precondition in a test.

Done when you can make it crash on demand, or a test throws the same exception.

### 6. Fix the cause

Fix the code that produced the bad state, not the frame that noticed it. Common KMP fixes:

| Cause | Fix |
|---|---|
| Kotlin exception reaches Swift from a function without `@Throws` | Catch at the boundary and return a result type, or add `@Throws(SpecificException::class)` and handle the Swift `throws` |
| `launch` on iOS without a `CoroutineExceptionHandler`, exception escapes | Handle failure inside the coroutine (`runCatching` / `try` that rethrows `CancellationException`) and expose it as state |
| `as!` cast in Swift on a bridged Kotlin type | `as?` plus handling, or expose a concrete type from Kotlin |
| UI touched off the main thread (either platform) | Switch to the main dispatcher / `@MainActor` before UI work; collect UI state on Main |
| `SQLITE_MISUSE` on iOS with Room's bundled driver | Remove system SQLite (`-lsqlite3`) from that binary — see the iOS reference |
| Release-only `ClassNotFoundException` / missing serializer | Add the precise keep rule, or remove the reflection |

### 7. Test

Write the failing test first (see `mobile-bug-fix` step 5). Crash-specific patterns:

- Boundary crash: a `commonTest` that the Swift-facing function **returns** an error value for the
  failing input instead of throwing; plus a Swift test if the Swift side needs changes.
- Coroutine crash: a `runTest` that the ViewModel ends in an error state and that no exception
  escapes (`runTest` rethrows unhandled coroutine exceptions at the end of the test).
- Release-only crash: build the release variant and exercise the path; a unit test cannot see R8.

### 8. Guard

- After release, watch crash-free users/sessions for the fixed version in Play vitals, Organizer or
  the reporter; confirm the signature stops for the new build.
- Record the handled failure as a non-fatal through the reporter so it stays visible.
- If the stack was unreadable, fix symbol and mapping upload now and verify one symbolicated test
  crash from a release-configured build before the next release.
- On iOS, if Kotlin crashes arrive as bare `abort()` stacks, add CrashKiOS (Crashlytics or Bugsnag)
  or your reporter's KMP integration.

## Quick reference

| Signature | Meaning | Look at |
|---|---|---|
| `FATAL EXCEPTION: main` / `AndroidRuntime` | Uncaught JVM exception | The **last** `Caused by:` and its first frame in your package |
| `ANR in com.example.app` | Main thread blocked ~5 s on input | ANR trace main thread — see the Android reference |
| `Fatal signal 11 (SIGSEGV)` + tombstone | Native crash in a `.so` | `ndk-stack` with unstripped libraries |
| Obfuscated `a.b.c(Unknown Source)` | R8 release build | `retrace` with that build's `mapping.txt` |
| `Uncaught Kotlin exception:` + `EXC_CRASH (SIGABRT)` | Kotlin exception escaped (to Swift, a coroutine root, or a thread) | Console / reporter Kotlin stack; `@Throws`; coroutine handlers |
| `EXC_BREAKPOINT (SIGTRAP)` in Swift frames | Swift runtime trap: `!` on nil, failed `as!`, index out of range | The Swift frame 0 line |
| `EXC_BAD_ACCESS (SIGSEGV / SIGBUS)` | Invalid memory access | Interop pointers, use-after-free, threading on ObjC objects |
| `0x8badf00d` in Termination Reason | iOS watchdog: launch or main thread too slow | Main-thread work → `mobile-performance-fix` |
| `JetsamEvent_…` log | iOS killed the app for memory | Memory growth → `mobile-performance-fix` |
| `SQLITE_MISUSE` / error code 21 on iOS only | Two SQLite copies in one app, or a closed connection used | The iOS reference, SQLite section |
| `_dispatch_assert_queue_fail` (typical) | Swift runtime isolation check: main-actor code ran off main | Thread a Kotlin callback arrives on |
| `InvalidMutabilityException`, `IncorrectDereferenceException` | Legacy Kotlin/Native memory model | Upgrade Kotlin; the old model was removed in Kotlin 1.9.20 |

## Verify

Run what applies and report each check as **PASS**, **FAIL** or **NOT RUN (reason)**. Never report a
check as passed that you did not run.

```bash
# Readable stack (Android)
retrace app/build/outputs/mapping/release/mapping.txt crash.txt
# Readable stack (iOS) — the UUIDs must match the report's Binary Images / usedImages
dwarfdump --uuid MyApp.app.dSYM
dwarfdump --uuid Shared.framework.dSYM          # dynamic Kotlin framework only
xcrun crashlog MyApp-2025-01-01-120000.ips
# The fix
./gradlew :shared:allTests                       # includes the new regression test
./gradlew :shared:iosSimulatorArm64Test          # macOS only
./gradlew :composeApp:assembleRelease            # release-only crashes: R8 config still builds
xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp -configuration Release \
  -destination 'generic/platform=iOS Simulator' build
```

Also report: the reproduction no longer crashes on the crashing platform (PASS / FAIL / NOT RUN),
and the other platform still works on the same path.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Retracing with the latest `mapping.txt` | Each build has its own mapping; names come out plausible and wrong | Archive the mapping per release; use the one for the crashed build |
| Using a dSYM without checking the UUID | Symbols resolve to wrong functions | `dwarfdump --uuid` must match the report |
| Reading the top `Exception`, not the last `Caused by:` | The top is often a wrapper (`RuntimeException`, `InvocationTargetException`) | Read to the deepest cause |
| Treating the iOS crashed thread as the throw site | For Kotlin exceptions it is the Swift→Kotlin call site | Use the Kotlin stack from the console or the reporter |
| Fixing with `try/catch` around the call site | Hides the bug; in coroutines also eats `CancellationException` | Fix the producer; rethrow cancellation |
| Assuming iOS behaves like Android for exceptions | Android crashes with a JVM trace; Kotlin/Native aborts at the boundary | Design the Swift-facing API to return errors |
| Converting `.ips` JSON numbers directly | `base` and `imageOffset` are decimal in JSON | Convert to hex before `atos`; or use `xcrun crashlog` |
| Debugging only with the debugger attached | Xcode intercepts the crash, no report is written | Detach (Debug → Detach) to let the OS write the report |

## Related skills

- `mobile-bug-fix` — test-first fix and PR summary once the cause is known.
- `mobile-performance-fix` — ANRs, watchdog kills and jetsam events after triage.
- `kmp-build-failure-triage` — link errors, duplicate or missing symbols.
- `mobile-platform-parity` — exceptions that behave differently on the two platforms.
- `mobile-release` — symbol and mapping upload as part of shipping.
- [android/skills `performance/anr-audit-and-fix`](https://github.com/android/skills/tree/main/performance/anr-audit-and-fix) — ANR trace diagnosis (link, not duplicated here).
- [CharlesWiltgen/Axiom `axiom-analyze-crash`](https://github.com/CharlesWiltgen/Axiom/tree/main/axiom-codex/skills/axiom-analyze-crash) — deeper `.ips`, MetricKit and `.xccrashpoint` analysis for the Swift side.
- [touchlab/CrashKiOS](https://github.com/touchlab/CrashKiOS) — Kotlin stacks for iOS crashes in Crashlytics and Bugsnag.
- [Kotlin/Native debugging](https://kotlinlang.org/docs/native-debugging.html) — dSYMs, LLDB and `kfun:` breakpoints.
