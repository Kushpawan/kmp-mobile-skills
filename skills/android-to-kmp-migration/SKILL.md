---
name: android-to-kmp-migration
description: Use when an existing Android app (Kotlin, Jetpack, Views or Compose) should share code with iOS through Kotlin Multiplatform - "migrate to KMP", "add iOS to our Android app", "make this module multiplatform", "create a shared module", Retrofit/Gson/Hilt/RxJava/Glide/SharedPreferences/java.time with no iOS equivalent, com.android.kotlin.multiplatform.library, or an incremental migration plan.
license: Apache-2.0
compatibility: Existing Android Gradle project in Kotlin. iOS steps need macOS with Xcode. Library support statements checked October 2026.
metadata:
  category: migration
  platforms: android, ios
---

# Android to Kotlin Multiplatform migration

Migrate in thin, shippable slices: create a shared module, prove one vertical slice runs on iOS
early, then move code inward-out — domain, data, presentation, and only then (optionally) UI. The
Android app must be releasable after every merged step. A migration that lives on a long branch, or
that leaves iOS until the end, is where these projects stall.

## When to use

- An Android app needs an iOS version and the team wants to share business logic.
- A module or package should become multiplatform without rewriting the app.
- Deciding which Android libraries to replace, keep, or hide behind interfaces.
- Estimating and sequencing the migration for a team.

## When not to use

- Upgrading an existing KMP project to AGP 9: use the AGP 9 migration skill (Kotlin) or the AGP 9
  upgrade skill (Android), linked below.
- Converting Java sources to Kotlin first: use the Java-to-Kotlin skill linked below, then return.
- Adding one new feature module to a project that is already KMP: use `kmp-feature-module`.
- One `expect`/`actual` pair: use `kmp-expect-actual`.

## Step 0 — Read the project first

```bash
cat settings.gradle.kts; find . -name build.gradle.kts -not -path '*/build/*' | sort
sed -n '1,80p' gradle/libs.versions.toml               # Kotlin, AGP, Compose, library versions
cat gradle/wrapper/gradle-wrapper.properties
grep -rnE 'kotlin\("kapt"\)|kotlin-kapt|org.jetbrains.kotlin.kapt' --include='*.kts' .   # kapt users
grep -rhoE '^import (android|androidx|dagger|javax\.inject|io\.reactivex|com\.google\.gson|com\.squareup\.(retrofit2|moshi)|com\.bumptech|java\.time|timber)[.a-z]*' \
  --include='*.kt' app/src/main | sort | uniq -c | sort -rn | head -40   # what the code leans on
find . -path '*/src/main/java' -o -path '*/src/main/kotlin' | head     # source roots per module
ls app/src/main/res/layout 2>/dev/null | wc -l                         # View-based UI size
```

Record: modules and their dependencies, Kotlin/AGP/Gradle versions, DI framework, async style
(coroutines, RxJava, LiveData), networking, persistence, image loading, logging, UI toolkit
(Views, Compose, mixed), test style, and whether `kapt` is in use. Ask the team two decisions before
planning:

1. **iOS UI:** Compose Multiplatform (share UI too) or native SwiftUI over shared logic?
2. **DI:** move the shared graph to a KMP DI library, or keep Hilt in the Android app and build the
   iOS graph separately?

## Workflow

Write the plan with `mobile-feature-plan` (one phase per step below), then execute it with
`mobile-feature-implement`. Each step ends with the Android release build and tests green.

### 1. Assess and classify

For each package or module, put it in one bucket:

| Bucket | Signal | Action |
|---|---|---|
| Pure Kotlin | no `android.*`, `java.*` (other than trivial), or Android-only library imports | Moves to `commonMain` as is |
| Android API at the edges | `Context`, `SharedPreferences`, `ConnectivityManager`, file paths, `Build` | Interface or `expect`/`actual`; Android impl moves to `androidMain` |
| Android-only library | Retrofit, Gson, Hilt annotations, RxJava, Glide, Timber, `java.time` | Swap per [references/library-swap.md](references/library-swap.md), or hide behind an interface |
| UI | Activities, Fragments, XML, Compose screens | Last; optional |

Summary of the library swaps (details, caveats and per-library notes in the reference):

| Android | KMP |
|---|---|
| Retrofit + OkHttp | Ktor client (OkHttp engine on Android, Darwin on iOS) |
| Gson / Moshi | kotlinx.serialization |
| Room | Room KMP |
| Hilt / Dagger | Koin (or kotlin-inject / Metro), or keep Hilt in the Android app only |
| `java.time` | kotlinx-datetime + `kotlin.time` |
| RxJava | coroutines + Flow (bridge with `kotlinx-coroutines-rx3`) |
| LiveData | `StateFlow` |
| androidx ViewModel | androidx lifecycle-viewmodel (KMP artifacts) |
| Glide | Coil 3 |
| SharedPreferences | DataStore Preferences (KMP) |
| Timber | Kermit or Napier |

Done when: every package has a bucket and every Android-only dependency has a decision.

### 2. Prepare the build

- Align versions: check the
  [Kotlin Multiplatform compatibility guide](https://kotlinlang.org/docs/multiplatform/multiplatform-compatibility-guide.html)
  for the Kotlin / AGP / Gradle / Xcode combination.
- **AGP 9:** a module can no longer apply the Kotlin Multiplatform plugin together with
  `com.android.application` (or the classic `com.android.library`); KMP libraries use
  `com.android.kotlin.multiplatform.library`, which has a single variant (no build types or
  flavours inside the shared module). AGP 9 also has built-in Kotlin, so `org.jetbrains.kotlin.android`
  is removed, and `kapt` must move to KSP (or AGP's legacy-kapt plugin). Do this on the Android app
  **before** adding `:shared`, with the AGP 9 migration skills linked below.
- Move hardcoded dependency versions into `gradle/libs.versions.toml` (`kmp-gradle-version-catalog`).

Done when: the Android app builds and releases on the target Kotlin/AGP versions, unchanged.

### 3. Create `:shared` and ship it empty

```toml
# gradle/libs.versions.toml — reuse the project's existing version keys
[plugins]
kotlin-multiplatform = { id = "org.jetbrains.kotlin.multiplatform", version.ref = "kotlin" }
android-kotlin-multiplatform-library = { id = "com.android.kotlin.multiplatform.library", version.ref = "agp" }
```

```kotlin
// shared/build.gradle.kts
plugins {
    alias(libs.plugins.kotlin.multiplatform)
    alias(libs.plugins.android.kotlin.multiplatform.library)
}

kotlin {
    android {                       // AGP 8.10–8.11: androidLibrary { }
        namespace = "com.example.app.shared"
        compileSdk = libs.versions.android.compileSdk.get().toInt()
        minSdk = libs.versions.android.minSdk.get().toInt()
        withHostTest { }            // enables src/androidHostTest and the host test task
    }
    listOf(iosArm64(), iosSimulatorArm64()).forEach { target ->   // add iosX64() only if Intel simulators matter
        target.binaries.framework {
            baseName = "Shared"
            isStatic = true
        }
    }
    sourceSets {
        commonMain.dependencies {
            implementation(libs.kotlinx.coroutines.core)
        }
        commonTest.dependencies {
            implementation(libs.kotlin.test)
        }
    }
}
```

Add `include(":shared")` to `settings.gradle.kts`, the plugins with `apply false` in the root build
file, and `implementation(project(":shared"))` to the Android app. Merge this alone.

Done when: `:androidApp` (or `:app`) builds a release with `:shared` on its classpath, and
`./gradlew :shared:iosSimulatorArm64Test` runs on macOS.

### 4. Bring up an iOS vertical slice early

Before moving much code, prove the iOS path end to end:

1. Create the iOS app (the KMP wizard's `iosApp`, or an Xcode project) and integrate the framework —
   direct integration runs `./gradlew :shared:embedAndSignAppleFrameworkForXcode` from an Xcode build
   phase; SPM or CocoaPods integration is the alternative (`kmp-xcframework-distribution`).
2. Call one shared function from Swift, then one real use case that does I/O (for example "load the
   current user's profile" through the shared repository).
3. Check Swift ergonomics on that slice: `suspend` functions, `Flow`, sealed classes and default
   arguments are where Swift friction appears (`kmp-swiftui-interop`).

Done when: the iOS app shows real data from shared code on a simulator, built from a clean checkout.

### 5. Move the domain

Move models, validators, use cases and pure business rules to `commonMain`. Keep the **same package
names** so Android imports do not change. Replace `java.time`, `java.util.UUID`, `String.format`
and other JVM-only APIs (kotlinx-datetime; `kotlin.uuid.Uuid`, which needs an opt-in on some Kotlin versions; string templates). Move their unit
tests to `commonTest` so they run on both platforms.

Done when: domain tests pass in `testAndroidHostTest` and `iosSimulatorArm64Test`; Android release builds.

### 6. Move the data layer

One data source at a time, behind the repository interface the app already uses:

- Networking: Ktor + kotlinx.serialization in `commonMain`; per-platform engines. Keep the Retrofit
  implementation bound in Android DI until the Ktor one passes the same tests, then switch the
  binding and delete the old one.
- Persistence: Room KMP (or SQLDelight if the team prefers); key-value with DataStore.
- Platform pieces (connectivity, file paths, secure storage) behind interfaces with
  `androidMain`/`iosMain` implementations (`kmp-expect-actual`, `kmp-secure-storage`).

Done when: each repository has one implementation in `commonMain`, tested with fakes, used by Android.

### 7. Move presentation (ViewModels)

Use androidx `lifecycle-viewmodel` in `commonMain`. Replace `LiveData` with `StateFlow` (Android
screens can collect it, or bridge with `asLiveData()` temporarily). Inject dispatchers. Android
Fragments/Compose screens keep working against the same ViewModels; the iOS app consumes them
through a Swift wrapper.

Done when: ViewModel tests run on both platforms and both apps use the shared ViewModels for the
migrated features.

### 8. Optionally move UI to Compose Multiplatform

Only if the team chose shared UI. View-based screens go to Jetpack Compose first (Android's XML to
Compose migration skill), then the Compose code moves to `commonMain`: replace `R.string`/`R.drawable`
with Compose Multiplatform resources, Android-only Compose APIs with multiplatform equivalents, and
Coil 2/Glide with Coil 3. Migrate screen by screen behind the existing navigation.

### 9. Clean up

Remove bridges (`kotlinx-coroutines-rx3`, `asLiveData()`), unused Android-only libraries, and dead
DI bindings. Re-run `kmp-module-health` on `:shared`.

## Quick reference

| Rule | Why |
|---|---|
| Android shippable after every merge | The migration never blocks a release |
| iOS slice in the first few steps | Toolchain, framework and Swift-interop problems surface while cheap |
| Inward-out: domain → data → presentation → UI | Each layer depends only on layers already shared |
| Same package names when moving files | No import churn in the Android app |
| Interface + platform impl when no KMP library exists | Never block on a missing library |
| Old and new implementations behind one interface | Switch the DI binding, not the callers |

## Verify

Run after each step. Report each check as `PASS`, `FAIL` or `NOT RUN` with the reason (for example
"NOT RUN — no macOS host"). Never mark a check PASS that you did not run.

```bash
./gradlew :shared:compileCommonMainKotlinMetadata
./gradlew :shared:testAndroidHostTest                 # legacy com.android.library: testDebugUnitTest
./gradlew :shared:iosSimulatorArm64Test               # macOS
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64 # macOS
./gradlew :androidApp:assembleRelease                 # or :app:assembleRelease — Android still shippable
./gradlew :androidApp:testDebugUnitTest               # existing Android tests still pass
grep -rlE '^import (android|java\.time|io\.reactivex|com\.google\.gson|retrofit2)\.' shared/src/commonMain   # expect no output
xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build                  # macOS
```

Then `kmp-build-check` before each PR.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Big-bang branch | Months of conflicts; Android releases freeze | Small PRs to main; Android shippable each time |
| iOS left until "the shared code is done" | Interop, toolchain and API-shape problems found after the investment | Vertical slice in step 4 |
| Moving UI first | Drags every layer below it along at once | Domain → data → presentation → UI |
| KMP plugin added to the `com.android.application` module on AGP 9 | Not supported; the build fails | Separate `:shared` library module |
| Keeping `kapt` for Hilt/Room on AGP 9 | Incompatible with AGP's built-in Kotlin | KSP (or the legacy-kapt plugin) |
| `@Inject` / Hilt annotations in `commonMain` | Hilt is JVM/Android-only; iOS cannot compile it | Plain constructors; provide them from an Android Hilt module |
| Gson → kotlinx.serialization without payload tests | Unknown keys and missing fields now throw | `ignoreUnknownKeys`, defaults, tests on captured JSON |
| Room DAO functions left blocking | Non-Android targets require `suspend` or `Flow` | Convert DAOs while moving them |
| KSP for Room added only to `kspAndroid` | iOS has no generated database code: the build fails on the missing `actual`, or construction fails at runtime | KSP on every declared target |
| `-lsqlite3` added with `BundledSQLiteDriver` | Reported to let the link pick system SQLite over the bundled copy | One driver per framework; link the system library only for `NativeSQLiteDriver` |
| Exporting the whole shared API to Swift | Bigger framework, slower links, awkward Swift surface | Export only what Swift needs; design that API for Swift |
| Copying files instead of moving them | Two diverging copies of the same logic | Move, keep the package, delete the original |

## Related skills

- `mobile-feature-plan`, `mobile-feature-implement` — plan and execute each migration step.
- `kmp-feature-module`, `kmp-expect-actual`, `kmp-gradle-version-catalog` — module and build mechanics.
- `kmp-data-layer`, `kmp-api-endpoint`, `kmp-room-database`, `kmp-secure-storage`, `kmp-koin-di` — data-layer targets.
- `kmp-swiftui-interop`, `kmp-xcframework-distribution` — the iOS side of the slice.
- `compose-multiplatform-screen`, `compose-multiplatform-localization` — if UI moves too.
- `kmp-ci-github-actions` — add the macOS job as soon as `:shared` exists.
- External: [Kotlin AGP 9 migration skill](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-agp9-migration) ·
  [Kotlin Java-to-Kotlin skill](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-java-to-kotlin) ·
  [Android skills](https://github.com/android/skills) (AGP 9 upgrade, XML-to-Compose migration) ·
  [Make your Android application work on iOS](https://kotlinlang.org/docs/multiplatform/multiplatform-integrate-in-existing-app.html) ·
  [Migrating a Jetpack Compose app to KMP](https://kotlinlang.org/docs/multiplatform/migrate-from-android.html) ·
  [Add KMP to an existing project](https://developer.android.com/kotlin/multiplatform/migrate) ·
  [Android Gradle library plugin for KMP](https://developer.android.com/kotlin/multiplatform/plugin).
