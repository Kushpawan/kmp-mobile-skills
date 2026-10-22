# Using other skill packs in a Kotlin Multiplatform project

Many excellent skills target native Android or native iOS. Most of them are still useful in a KMP
project, but some give advice that is wrong for shared code. This page says which is which, so you
can install them side by side with this repo.

**Rule of thumb:** a native-platform skill is safe for the **platform host** (the Android app
module, the iOS app target, and `androidMain` / `iosMain` source sets). Before applying it to
`commonMain`, check that every API it recommends exists in Kotlin Multiplatform.

## Google's android/skills

[android/skills](https://github.com/android/skills) is Google's official Android pack. Its skills
assume an Android-only Gradle project.

| Area | Safe for shared KMP code? | Notes |
|---|---|---|
| Compose performance (`jetpack-compose-performance`) | **Yes, mostly** | Stability, recomposition and lazy-list rules apply to Compose Multiplatform too. Tooling it names (Layout Inspector, Macrobenchmark, Baseline Profiles) is Android-only. |
| Adaptive layouts (`adaptive`) | Partly | Window size class concepts transfer; the Material 3 adaptive artifacts it uses may differ in Compose Multiplatform. Check for the multiplatform artifact first. |
| AGP 9 upgrade (`agp-9-upgrade`) | **No** | Written for Android-only projects. For KMP use the AGP 9 migration skill in [Kotlin/kotlin-agent-skills](https://github.com/Kotlin/kotlin-agent-skills), which covers the `com.android.kotlin.multiplatform.library` plugin. |
| Navigation 3 (`navigation-3`), navigation-event | Android host only | Uses Android-only artifacts and often Hilt. For shared navigation use `compose-multiplatform-navigation` from this repo. |
| Edge-to-edge (`edge-to-edge`) | Android host only | Activity and window insets setup. Insets *handling* inside shared Compose UI is fine. |
| XML → Compose migration | Android host only | Useful as step 1 of an Android-to-KMP migration (see `android-to-kmp-migration`). |
| Theming / styles | Android host only | Android theme attributes and XML styles. Shared theming belongs in your Compose Multiplatform theme. |
| ANR audit and fix (`anr-audit-and-fix`) | Yes, for the Android side | ANRs are Android-only; the fixes (move work off the main thread) usually land in shared code. Pair it with `kmp-crash-triage`. |
| Profiler (`android-profiler`), R8 analyzer | Yes, for the Android build | Measures and shrinks the Android app, including shared code compiled for Android. iOS needs Instruments (see `mobile-performance-fix`). |
| Intent / permission security | Android host only | Pair with `mobile-security-review`, which also covers iOS. |
| Testing setup (`testing-setup`) | Partly | Android instrumented and Robolectric tests. Shared logic tests belong in `commonTest` (see `kmp-testing-patterns`). |
| CameraX, Media3, Wear, TV, Cars, XR, Play Billing, ML Kit, Glance | Android host only | Platform features; expose them to shared code through an interface (see `kmp-expect-actual`). |

## Kotlin/kotlin-agent-skills

[Kotlin/kotlin-agent-skills](https://github.com/Kotlin/kotlin-agent-skills) is JetBrains' official
pack and is written with KMP in mind. Its AGP 9 migration, CocoaPods-to-SPM migration and Kotlin/Native
build performance skills complement `kmp-feature-module`, `kmp-xcframework-distribution` and
`kmp-build-failure-triage` here.

## Compose packs

[chrisbanes/skills](https://github.com/chrisbanes/skills),
[Meet-Miyani/compose-skill](https://github.com/Meet-Miyani/compose-skill) and
[skydoves/compose-performance-skills](https://github.com/skydoves/compose-performance-skills) mostly
apply to Compose Multiplatform. Watch for Android-only artifacts (`androidx.activity`,
`hiltViewModel`, `LocalContext`) in their examples when you are writing `commonMain` code.

Some packs prescribe an architecture (a specific MVI base class, Koin annotations). The skills in
this repo follow whatever your project already does, so if two skills disagree, your project's
existing code wins.

## SwiftUI and Swift packs

[AvdLee](https://github.com/AvdLee/SwiftUI-Agent-Skill) and
[twostraws](https://github.com/twostraws/SwiftUI-Agent-Skill) SwiftUI skills, and the Swift
concurrency and Swift Testing skills by the same authors, are fully applicable to the iOS app target.
They do not know about the Kotlin framework; use `kmp-swiftui-interop` for the boundary (observing
Kotlin `Flow`s, `suspend` functions, sealed classes and exceptions from Swift).

## When two skills overlap

Most agents load every skill whose description matches. If two installed skills fight (for example
two navigation skills), uninstall the one that does not match your project, or name the one you want
in your request ("use compose-multiplatform-navigation").
