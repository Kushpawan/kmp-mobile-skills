# Measuring performance on Android and iOS

Contents

1. Release-like builds
2. Android: startup
3. Android: frames and system traces
4. Android: memory
5. Android: battery and background work
6. iOS: Instruments from Xcode and the command line
7. iOS: launch time and hangs
8. Kotlin/Native: GC pauses and logs
9. App size
10. Recording results

Use the deeper skills for analysis — [android/skills `profilers/android-profiler`](https://github.com/android/skills/tree/main/profilers/android-profiler)
for Android traces and heap dumps, and the Instruments-focused skills in
[CharlesWiltgen/Axiom](https://github.com/CharlesWiltgen/Axiom) for iOS. This page lists the
capture commands and the KMP-specific details.

## 1. Release-like builds

- Android: a non-debuggable variant with R8 on — `release`, or a `staging` / `benchmark` build type
  that inherits from it. `./gradlew :composeApp:assembleRelease` (installing needs a signing
  config; benchmark build types commonly sign with the debug key).
- iOS: Xcode's **Profile** action (Product → Profile, ⌘I) builds the scheme's Profile
  configuration, Release by default. Kotlin frameworks built through the Xcode Gradle build phase
  follow the Xcode configuration; check that a Release Xcode build links the **release** Kotlin
  framework.

## 2. Android: startup

```bash
PKG=com.example.app
for i in $(seq 1 6); do                       # discard the first run
  adb shell am force-stop $PKG
  adb shell am start -W -n $PKG/.MainActivity | grep TotalTime
done
```

Logcat also prints `Displayed com.example.app/.MainActivity: +…ms` for each launch.

For repeatable numbers, a Macrobenchmark module (`androidx.benchmark:benchmark-macro-junit4`)
measures cold start with `StartupTimingMetric` and scrolling with `FrameTimingMetric`; the same
module can generate a Baseline Profile with the `androidx.baselineprofile` plugin. Adding one is
net-new work — propose it rather than treating it as part of a quick fix.

```kotlin
@Test
fun coldStartup() = benchmarkRule.measureRepeated(
    packageName = "com.example.app",
    metrics = listOf(StartupTimingMetric()),
    iterations = 5,
    startupMode = StartupMode.COLD,
) {
    pressHome()
    startActivityAndWait()
}
```

## 3. Android: frames and system traces

Quick frame statistics without a trace:

```bash
adb shell dumpsys gfxinfo com.example.app reset
# ... perform the scroll or animation ...
adb shell dumpsys gfxinfo com.example.app | grep -E "Total frames|Janky frames"
```

A system trace shows **why** frames are late (composition, layout, draw, GC, binder, lock
contention). Record from Android Studio's profiler (System Trace) or with the on-device tool:

```bash
adb shell perfetto -o /data/misc/perfetto-traces/trace.perfetto-trace -t 10s \
  sched freq idle am wm gfx view binder_driver hal dalvik input res memory
adb pull /data/misc/perfetto-traces/trace.perfetto-trace
```

Open the file at ui.perfetto.dev or in Android Studio. Name the janky frames and the slice that
dominates them in the report.

## 4. Android: memory

```bash
adb shell dumpsys meminfo com.example.app                    # Java heap, native heap, totals
adb shell am dumpheap com.example.app /data/local/tmp/app.hprof
adb pull /data/local/tmp/app.hprof                           # open in Android Studio
```

Take one heap dump after warm-up and one after repeating the suspect flow several times; compare
retained instances of your classes rather than totals.

LeakCanary finds retained `Activity`, `Fragment`, `View` and ViewModel instances in debug builds:

```toml
# gradle/libs.versions.toml
[versions]
leakcanary = "x.y"          # use the current release

[libraries]
leakcanary-android = { module = "com.squareup.leakcanary:leakcanary-android", version.ref = "leakcanary" }
```

```kotlin
// Android app module
dependencies {
    debugImplementation(libs.leakcanary.android)
}
```

## 5. Android: battery and background work

```bash
adb shell dumpsys batterystats --reset
# ... use the app or leave it in the background for the period in question ...
adb shell dumpsys batterystats com.example.app      # wakelocks, jobs, alarms, network per app
adb shell dumpsys jobscheduler | grep -A5 com.example.app
adb shell dumpsys alarm | grep -A3 com.example.app
```

A background sync that reschedules itself on every failure, or a location request with a short
interval left running, are the usual culprits.

## 6. iOS: Instruments from Xcode and the command line

Profile on a **device**. Useful templates: Time Profiler (CPU), Animation Hitches (frame drops),
Hangs, App Launch, Allocations, Leaks, os_signpost.

```bash
xcrun xctrace list templates
xcrun xctrace list devices
# Attach to the running app on a device for 20 seconds
xcrun xctrace record --template 'Time Profiler' --device '<device name or UDID>' \
  --attach '<app process name>' --time-limit 20s --output scroll-before.trace
# Allocations while launching a process (see `xcrun xctrace help record` for launch options)
xcrun xctrace record --template 'Allocations' --launch -- <path-to-executable-or-app>
xcrun xctrace export --input scroll-before.trace --toc   # list what the trace contains
```

Kotlin frames appear with `kfun:` names. Release builds need the dSYMs available to Instruments to
show names instead of addresses.

## 7. iOS: launch time and hangs

- **App Launch** template in Instruments for one launch in detail.
- Xcode Organizer → Launch Time and Hangs, for field data from TestFlight / App Store users.
- A UI test that measures launch repeatedly:

```swift
func testLaunchPerformance() throws {
    measure(metrics: [XCTApplicationLaunchMetric()]) {
        XCUIApplication().launch()
    }
}
```

- On the device, Settings → Developer → Hang Detection flags hangs while you use the app.
- MetricKit delivers `MXHangDiagnostic` with call stacks on a later launch.

## 8. Kotlin/Native: GC pauses and logs

GC pauses can show up as hitches on iOS. To see them in Instruments:

1. Add `kotlin.native.binary.enableSafepointSignposts=true` to `gradle.properties`.
2. Profile with the **os_signpost** instrument, subsystem `org.kotlinlang.native.runtime`,
   category `safepoint`. Each event is a GC pause.

GC logs on stderr (visible in the Xcode console):

```kotlin
kotlin {
    targets.withType<org.jetbrains.kotlin.gradle.plugin.mpp.KotlinNativeTarget> {
        binaries.all {
            freeCompilerArgs += "-Xruntime-logs=gc=info"   // diagnostic builds only
        }
    }
}
```

A steadily growing number of stable references in the root set suggests Swift/ObjC objects held by
Kotlin are not being released — the skill's memory reference covers what to do about it.

## 9. App size

- Android: Build → Analyze APK in Android Studio, or `bundletool` for an app bundle. R8 keep-rule
  bloat: [android/skills `performance/r8-analyzer`](https://github.com/android/skills/tree/main/performance/r8-analyzer).
- iOS: export an archive with app thinning to get the *App Thinning Size Report*. Check the Kotlin
  framework's share of it.
- Kotlin framework: `export(...)` puts all of an exported dependency's API into the framework and
  disables dead-code elimination for it. Export only what Swift calls, and avoid
  `transitiveExport = true`, which the Kotlin docs say can increase binary size and compile time.

## 10. Recording results

Record each measurement with: device model and OS, build variant, number of runs, median and
range, and the exact command or template. Use the same values for the after-measurement. Numbers
from a debug build, an emulator or a simulator are labelled "directional".
