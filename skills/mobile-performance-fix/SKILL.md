---
name: mobile-performance-fix
description: Use when a Kotlin Multiplatform (Android + iOS) app is slow, laggy or janky, drops frames while scrolling, starts slowly, keeps a loader spinning after a tap, freezes (ANR, iOS hang, watchdog 0x8badf00d), grows in memory or is killed for it (jetsam, OutOfMemoryError), leaks objects between Kotlin and Swift, drains battery, or ships an oversized APK or framework — including Compose Multiplatform and SwiftUI screens over shared code.
license: Apache-2.0
compatibility: Kotlin Multiplatform app with Android and iOS targets. Android measurement needs adb and Android Studio or Perfetto; iOS measurement needs macOS with Xcode and Instruments and, for real numbers, a physical device.
metadata:
  category: performance
  platforms: android, ios
---

# Mobile performance fix — measure, fix, prove

Evidence first. Never change code on a hunch, and never report a fix without a before and an after
number measured the same way. If you cannot measure it, say so instead of guessing. In apps with
offline storage and background sync, the biggest wins are usually I/O and waiting on user-gesture
paths, not recomposition.

## When to use

- "Slow", "laggy", "janky", "stutters", "freezes", "takes forever to open", "spinner after I tap
  Save", "battery drain", "memory keeps growing", "the app gets killed in the background".
- ANRs, iOS hangs and watchdog terminations once `kmp-crash-triage` has identified the blocked
  thread.
- Memory growth or leaks on either platform, including objects shared between Kotlin and Swift.
- APK, app bundle or iOS framework size.

## When not to use

- The app crashes → `kmp-crash-triage` first.
- Wrong results rather than slow ones → `mobile-bug-fix`.
- Gradle or Xcode **build** speed → `kmp-build-failure-triage` covers build problems; build-time
  tuning is out of scope here.

## Rule 0 — what invalidates a measurement

1. **Debug builds lie.** Debuggable Android builds turn off runtime optimisations and Compose does
   extra work in debug; Kotlin/Native debug binaries and Swift `-Onone` code are unoptimised.
   Measure a release build, or a release-like variant (for example `staging` with minify on and
   `debuggable false`). Debug builds are fine for reproducing a functional bug, never for numbers.
2. **The first run lies.** JIT, disk caches and (on Android) profile installation warm up over the
   first launches. Discard the first one or two runs.
3. **Instrumentation lies.** An attached debugger, an in-app HTTP inspector (e.g. Chucker on
   Android), verbose logging, StrictMode penalties, and Xcode diagnostics (Zombies, Address
   Sanitizer) all add overhead per frame or per request.
4. **Emulators and simulators are directional only.** The iOS Simulator runs on the Mac's CPU and
   memory; profile iOS on a device. Android emulator jank reproduces, absolute milliseconds do not.
5. **One run is not a measurement.** Five or more runs; report the median and the spread.

## Step 0 — Read the project first

1. **Build variants.** Which variants are release-like? Is R8 enabled for them? Is there a
   `:benchmark` / Macrobenchmark module or a Baseline Profile?
2. **UI stack.** Compose Multiplatform on both platforms, or SwiftUI over shared ViewModels on iOS?
   Which state holders feed the UI, and how Swift observes them (SKIE, KMP-NativeCoroutines, a
   hand-written callback API).
3. **Data and sync.** Database (Room KMP, SQLDelight), the HTTP client, image loading (Coil, Kamel,
   platform loaders), and whether writes go through a background sync queue.
4. **Startup.** Android `Application.onCreate`, iOS `App.init` / `didFinishLaunching`, and DI setup
   (Koin `createdAtStart`, eager singletons, database opening).
5. **Instrumentation.** The project's logger (Kermit, Napier or other) and any analytics events that
   already record latency — find out exactly what they measure.
6. **Style.** The project's code conventions for the fix; keep existing diagnostic log lines.

## Workflow

### 1. Fix the target

Pin down, one line each: app, screen or interaction, platform and device, build variant, and what
"slow" means as a number — frames dropped while scrolling the orders list, milliseconds from tap to
the saved state, `TotalTime` at cold start, MB after ten minutes. Ask if the user has not said. Do
not profile the whole app.

### 2. Capture evidence and a baseline

| Symptom | Android | iOS | Minimum evidence |
|---|---|---|---|
| Jank, scroll stutter | System trace (Android Studio profiler / Perfetto); Macrobenchmark `FrameTimingMetric` | Instruments: Time Profiler, Animation Hitches | The janky frames and the slice or stack that dominates them |
| Slow start | `adb shell am start -W` (`TotalTime`), Macrobenchmark `StartupTimingMetric` | Instruments App Launch; Organizer launch metrics; `XCTApplicationLaunchMetric` | ≥5 cold starts, median + spread, plus one trace |
| Slow gesture (tap → result) | Logger timestamps at tap and at state change; then a trace | Same, plus Time Profiler | Local-ack latency per run; what the time is spent waiting on |
| Freeze / ANR / hang | ANR traces (see `kmp-crash-triage`) | Instruments Hangs; Organizer Hangs; MetricKit `MXHangDiagnostic` | The blocked main-thread stack |
| Memory growth / leak | Heap dumps before/after; LeakCanary | Allocations (generations), Leaks, Xcode Memory Graph | Retained objects that grow per repetition of the flow |
| Battery / wakeups | `adb shell dumpsys batterystats`, `dumpsys power` | Organizer energy reports; MetricKit | The wake lock, alarm, job or timer responsible |
| Size | APK Analyzer; R8 reports | App Thinning Size Report; framework size per architecture | Size by component before/after |

Capture commands and tool details: [references/measurement.md](references/measurement.md).

Write the baseline into the report **before** touching code.

### 3. Diagnose by layer

Work outward from the measurement, in this order.

#### 3a. Gesture and I/O paths — check first

- **Never block a user gesture on draining an entire background sync queue.** A drain processes
  every pending item (uploads, other records) with network timeouts on each, and may wait behind a
  drain that is already running. The user's tap then waits on unrelated backlog. Instead: write
  the record locally as *pending*, trigger the queue without awaiting the drain, and wait — with a
  short bound — only for **this** record's acknowledgement.
- **Treat "pending" as success.** If the bound expires, return the pending record. The UI shows it
  from the local database stream and updates when the server acknowledges it. Offline is the same
  path.
- **Do not wrap the whole drain in a timeout** at the call site: cancelling it can cancel an HTTP
  request mid-flight. **Do not post the record inline** from the repository to "make it fast" when
  records depend on each other — ordering belongs to the queue.
- **Cap location fetches on gesture paths** with `withTimeoutOrNull`. A platform location fix can
  take several seconds; location attached to a record is metadata. Make any blocking decision
  that needs location (for example a geofence check) explicitly, before the gesture's work starts.
- **Measure gesture latency as local-ack latency** (tap → UI shows the saved or pending state) and
  record server-ack latency separately. Mixing them makes a good fix look like a regression.
- Waiting for the full queue is right only when that is the point (an explicit "Sync now", a final
  submit that requires everything uploaded) — and then show progress, not an unexplained spinner.
- Also: main-thread database or file I/O (the repository should use an injected I/O dispatcher),
  `runBlocking` on the main thread, and N sequential requests on screen entry that could run
  concurrently with `async`.

Worked example and tests: [references/gesture-latency.md](references/gesture-latency.md).

#### 3b. Data layer

- A missing index on a filtered or sorted column; `SELECT *` into wide rows for a list.
- A database `Flow` that re-emits the whole list on any write to the table, feeding an expensive
  mapping — use `distinctUntilChanged()` and keep mapping cheap or off the main thread.
- Unbounded list fetches where the API supports paging.
- Large JSON parsed on the main thread; images decoded at full size — downsample to the display
  size before decoding.

#### 3c. UI

- **Compose (Android, and iOS with Compose Multiplatform):** use the Compose performance skills
  linked below rather than rules from memory. Highest-yield checks: stable `key` and `contentType`
  on lazy items; state reads deferred into layout/draw lambdas for scroll- or animation-driven
  values; no allocation or heavy work in composition; state collected with lifecycle awareness.
  Some AndroidX Compose APIs are not available in Compose Multiplatform, or only in newer versions —
  check the CMP version in `gradle/libs.versions.toml` before recommending one.
- **SwiftUI over shared state:** a Kotlin state object republished on every small change can
  invalidate large view trees. Observe the narrowest value a view needs; see the SwiftUI
  performance skills linked below.

#### 3d. Startup

- Android `Application.onCreate` and iOS launch code: logging setup, database open, sync
  scheduling, DI graph creation. Anything not needed for the first frame moves off the launch path
  or behind first use.
- Eager DI singletons (Koin `createdAtStart = true`, modules that construct clients at
  registration) cost the same on iOS — the shared graph is built in Kotlin/Native.
- Android: R8 on the measured variant; Baseline Profiles for startup and critical journeys.
- iOS: each dynamic framework adds load work at launch; a static Kotlin framework avoids one —
  measure before switching, since it changes linking for the whole app.

#### 3e. Memory

Details, tools and code: [references/memory.md](references/memory.md). The KMP-specific causes:

- **Retain cycles across Kotlin and Swift are never collected.** Kotlin's GC reclaims cycles of
  Kotlin objects, but a cycle that includes at least one Swift/ObjC object cannot be reclaimed. The
  usual shape: a Kotlin object stores a Swift closure that captures `self`, and `self` holds the
  Kotlin object. Use `[weak self]` and an explicit cancel/close.
- **Collection started from Swift that nothing cancels** keeps the collector, its closure and
  everything they capture alive, and keeps doing work. Return a cancellation handle, or use an
  integration (SKIE, KMP-NativeCoroutines) whose Swift task cancellation reaches Kotlin.
- **Swift/ObjC objects released by Kotlin are freed only after a GC**, so memory can look higher
  than expected without being a leak; a long loop that creates interop objects may need an
  `autoreleasepool`.
- Android: the usual leaks — an `Activity` or `View` held by a ViewModel, a singleton, or a
  never-cancelled scope.

### 4. Fix

- One cause per change, at the smallest responsible layer. No drive-by refactors.
- Follow the project's style. Keep existing diagnostic log lines; never add `println` / `Log.d` /
  `NSLog`.
- If the fix changes a published library, say so: consumers see it only after a new version is
  published or they build against the local copy.

### 5. Prove it

Re-run the **same** measurement: same device, build variant, iterations and data.

```text
Symptom      <what the user saw>
Measured     <metric> = <before> (median of n=<runs>, <device>, <variant>)
Cause        <one sentence, with the trace slice, stack or code path that proves it>
Fix          <file:line> — <what changed>
Result       <metric> = <after> (same conditions)  ->  <delta>
Not fixed    <anything still slow, with its number>
```

A fix with no after-number is not done. **If the change did not move the number, say so and revert
it** rather than keeping speculative churn. Then run the affected module's tests on both platforms.

## Quick reference

| Symptom | First suspect | Evidence to get |
|---|---|---|
| Spinner after tap that grows with offline backlog | Gesture awaits a full sync-queue drain | Logger timestamps around the await; queue length |
| Spinner after tap, worse indoors | Uncapped location fetch on the gesture path | Time spent in the location call |
| Janky list scroll | Unstable or missing keys, heavy item composition, image decode size | System trace / Time Profiler over the scroll |
| Slow cold start on both platforms | Eager DI graph, database open, network on launch | Startup trace; time per init step |
| Freeze when opening a screen | Main-thread I/O or `runBlocking` | Main-thread stack during the freeze |
| iOS memory grows per visit to a screen | Kotlin↔Swift retain cycle or uncancelled collection | Allocations generations; Memory Graph |
| Android memory grows per visit | Leaked `Activity`/`View`/ViewModel | LeakCanary trace or heap dump diff |
| Killed in background (iOS) | High memory at suspension | `JetsamEvent` logs; Allocations |

## Verify

Report each check as **PASS**, **FAIL** or **NOT RUN (reason)**, and each measurement with its numbers.
Never report a check as passed that you did not run.

```bash
./gradlew :composeApp:assembleRelease                 # or the release-like variant from Step 0
adb shell am force-stop com.example.app && adb shell am start -W -n com.example.app/.MainActivity
./gradlew :benchmark:tasks --all | grep -i connected  # Macrobenchmark task name, if the module exists
xcrun xctrace record --template 'Time Profiler' --device '<device name or UDID>' \
  --attach '<app process name>' --time-limit 20s --output before.trace
./gradlew :shared:allTests                            # behaviour unchanged on every target
./gradlew :shared:iosSimulatorArm64Test               # macOS only
```

Name the measurement commands you actually ran in the report, with device and variant. A number
from a debug build or a simulator is reported as directional, not as a result.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Measuring a debug build | Debug costs dominate and hide the real bottleneck | Release or release-like variant |
| Optimising recomposition first | Most user-visible waits are I/O on the gesture path | Check gesture and I/O paths first (3a) |
| Awaiting the whole sync queue from a button | Latency scales with unrelated backlog and network timeouts | Trigger the queue, bounded wait on the caller's own record |
| `withTimeoutOrNull` around the full drain | Cancels in-flight requests mid-upload | Bound only the wait for the caller's record |
| Reporting server-ack time as tap latency | A correct fix looks like no change | Record local-ack and server-ack separately |
| Profiling iOS on the Simulator | Mac CPU and memory are not a phone's | Profile on a device |
| Keeping a change that did not move the number | Adds risk and churn with no benefit | Revert it and report "no gain" |
| `[self]` captured in a closure stored by Kotlin | Cross-runtime cycle, never collected | `[weak self]` plus an explicit cancel |

## Related skills

- `kmp-crash-triage` — ANRs, hangs and watchdog kills start there.
- `mobile-bug-fix` — behaviour bugs found while profiling.
- `mobile-platform-parity` — when one platform is slow and the other is not because behaviour differs.
- [android/skills `profilers/android-profiler`](https://github.com/android/skills/tree/main/profilers/android-profiler) — recording and analysing Android traces, heap dumps and CPU profiles.
- [android/skills `jetpack-compose/jetpack-compose-performance`](https://github.com/android/skills/tree/main/jetpack-compose/jetpack-compose-performance) — Compose stability, lazy layouts, phase deferral.
- [android/skills `performance/r8-analyzer`](https://github.com/android/skills/tree/main/performance/r8-analyzer) and [`performance/anr-audit-and-fix`](https://github.com/android/skills/tree/main/performance/anr-audit-and-fix).
- [skydoves/compose-performance-skills](https://github.com/skydoves/compose-performance-skills) — `measurement/testing-compose-in-release-mode`, `measurement/generating-baseline-profiles`, `audit/auditing-compose-performance`, `lists/optimizing-lazy-layouts`.
- [Dimillian/Skills `swiftui-performance-audit`](https://github.com/Dimillian/Skills/tree/main/swiftui-performance-audit) and [CharlesWiltgen/Axiom](https://github.com/CharlesWiltgen/Axiom) (`axiom-profile-performance`, `axiom-audit-memory`) — the SwiftUI and Instruments side.
- [Baseline Profiles overview](https://developer.android.com/topic/performance/baselineprofiles/overview) and [Kotlin/Native and Swift/ObjC ARC integration](https://kotlinlang.org/docs/native-arc-integration.html).
