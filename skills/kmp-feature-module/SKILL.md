---
name: kmp-feature-module
description: Use when adding a new feature or library module to a Kotlin Multiplatform project - "create a module", "modularize this feature", a :feature module, settings.gradle.kts include lines, a logic/ui module split so SwiftUI can consume shared logic, an umbrella shared iOS framework, export() to Swift, com.android.kotlin.multiplatform.library, or a new module that builds on Android while Swift reports "Cannot find 'X' in scope".
license: Apache-2.0
compatibility: Kotlin Multiplatform Gradle project on Kotlin 2.x with AGP 8.10+ or 9.x. iOS framework checks need macOS with Xcode.
metadata:
  category: build
  platforms: android, ios
---

# KMP feature module

A feature module is a Gradle project with one owner, a narrow public API, and exactly two ways in:
the app's DI graph and the app's navigation host. Pick the module shape the project already uses.
The most expensive mistake is a module that builds and runs on Android while the iOS framework
silently does not contain it.

## When to use

- Creating `:feature:<name>` or a reusable library module in a KMP build.
- Splitting a feature out of a monolithic `:shared` or `:composeApp`.
- Adding a `:logic` + `:ui` pair for an app whose iOS UI is SwiftUI.
- A new module compiles for Android but its types are missing in Swift.

## When not to use

- Adding a platform API inside an existing module: use `kmp-expect-actual`.
- Adding or upgrading a dependency or Gradle plugin: use `kmp-gradle-version-catalog`.
- Auditing an existing module: use `kmp-module-health`.
- Migrating existing modules to AGP 9: use the AGP 9 migration skill in
  [Kotlin/kotlin-agent-skills](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-agp9-migration).

## Step 0 — Read the project first

Do not write a build file from memory. Read the build, record the answers, then copy the closest
existing sibling module.

```bash
cat settings.gradle.kts                                        # include(...), includeBuild, catalog path
find . -name build.gradle.kts -not -path '*/build/*' | sort    # existing modules
grep -rln "binaries.framework" --include=build.gradle.kts .     # who produces the iOS framework
grep -rn  "export(" --include=build.gradle.kts .                # what Swift can see today
grep -rlE "composeMultiplatform|org.jetbrains.compose" --include=build.gradle.kts .
ls build-logic buildSrc 2>/dev/null                            # convention plugins
grep -rl "ComposeUIViewController" --include='*.kt' . | head -3  # iOS renders Compose?
```

| Record | Where it shows up |
|---|---|
| Module naming (`:feature:notes`, `:notes`, `:features:notes-impl`) | `include(...)` lines |
| Android plugin: `com.android.kotlin.multiplatform.library` (`kotlin { android { } }`) or `com.android.library` + `androidTarget()` | sibling build files |
| iOS targets: `iosArm64`, `iosSimulatorArm64`, maybe `iosX64` | sibling build files — a new module declares the same set as its consumers |
| Convention plugins (`id("com.example.kmp.library")`) | `build-logic/`, `buildSrc/` |
| DI: Koin, kotlin-inject, Metro, manual | `startKoin`, `@Component` |
| Navigation: Navigation Compose, Navigation 3, Decompose, Voyager | the `NavHost` or root component |
| Presentation: `ViewModel` + `StateFlow`, or an MVI base such as `MviViewModel<State, Effect>` | existing ViewModels |
| Package root, test naming, fakes vs mocks | an existing module's `commonTest` |

Then choose the shape:

| What you find | Shape |
|---|---|
| The framework module applies Compose and iOS shows `ComposeUIViewController` | **A — shared Compose UI.** Screens live in `commonMain` of the feature module. |
| iOS UI is SwiftUI; the framework module has no Compose; features come as `:logic`/`:ui` (or `api`/`impl`, `domain`/`presentation`) pairs | **B — logic/ui split.** `:logic` is KMP without Compose; `:ui` is Compose for Android. |
| One monolithic `:shared` with a package per feature and no feature modules | **Ask.** Default to a new package inside `:shared`. Do not modularize as a side effect. |
| Greenfield | A if iOS will render Compose Multiplatform; B if iOS will be native SwiftUI. |

Write down the choice. Every later step follows it.

## Workflow

### 1. Name the module

| | Shape A | Shape B |
|---|---|---|
| Gradle path | `:feature:notes` | `:feature:notes:logic`, `:feature:notes:ui` |
| Directory | `feature/notes/` | `feature/notes/logic/`, `feature/notes/ui/` |
| Package | `com.example.app.feature.notes` | `com.example.app.feature.notes` in both |
| Android `namespace` | `com.example.app.feature.notes` | `…feature.notes.logic`, `…feature.notes.ui` |

Every module needs a unique `namespace`. Duplicates collide in generated `R` classes, and AGP 9 fails
the build on them by default. Done when `grep -rn 'namespace = "com.example.app.feature.notes' .`
finds nothing yet.

### 2. Register it in `settings.gradle.kts`

```kotlin
include(":feature:notes")                              // Shape A
include(":feature:notes:logic", ":feature:notes:ui")   // Shape B
```

Gradle maps `:feature:notes:logic` to `feature/notes/logic/` by default. If the build enables
`TYPESAFE_PROJECT_ACCESSORS`, other modules may write `projects.feature.notes.logic`; follow what
siblings use. Done when `./gradlew projects` lists the new path.

### 3. Write the build file

If a convention plugin exists, the build file is a few lines: apply it, set `namespace`, add
dependencies. Otherwise copy the matching template from
[references/gradle-templates.md](references/gradle-templates.md). Rules that apply either way:

- **Android target.** With the AGP KMP library plugin, Android config lives in `kotlin { android { } }`.
  Host tests and Android resources are **off by default**: add `withHostTest {}` or no
  `androidHostTest` runs, and `androidResources { enable = true }` if the module uses Compose
  resources or `res/` (without it, Compose resources fail at runtime). The plugin has no build types,
  flavours or `BuildConfig`; pass configuration in from the app through DI.
- **iOS targets.** Declare at least every target of each module that will depend on this one. A
  consumer with `iosX64()` cannot depend on a module without it. `iosX64` is only for Intel-Mac simulators and is a Tier 3 target
  in current Kotlin (see the [target support page](https://kotlinlang.org/docs/native-target-support.html)).
- **Frameworks.** Feature modules declare no `binaries.framework`. Only the module iOS links (the
  umbrella in Shape B, `:shared` or `:composeApp` in Shape A) produces one.
- **Shape B `:logic` has no Compose.** No Compose plugins, no Compose artifacts, not even through an
  `api` dependency. Compose there drags the Compose runtime into the iOS framework and puts types
  in its API that SwiftUI cannot use.
- **Versions.** Only `libs.*` accessors. New entries go through `kmp-gradle-version-catalog`.

Done when `./gradlew :feature:notes:help` (or `:feature:notes:logic:help`) configures without error.

### 4. Lay out the sources

```text
Shape A  feature/notes/src/
  commonMain/kotlin/com/example/app/feature/notes/
    data/  domain/  ui/ (NotesListScreen.kt, NotesListViewModel.kt)  navigation/  di/NotesModule.kt
  commonTest/kotlin/com/example/app/feature/notes/
  androidMain/  iosMain/            # only when an actual or platform binding is needed

Shape B  feature/notes/logic/src/commonMain/kotlin/com/example/app/feature/notes/
    data/  domain/  presentation/ (NotesListViewModel.kt, NotesListState.kt)  di/NotesModule.kt
         feature/notes/logic/src/commonTest/...
         feature/notes/ui/src/commonMain/kotlin/com/example/app/feature/notes/
    ui/ (NotesListScreen.kt, NotesListTestTags.kt)  navigation/NotesNavigation.kt  di/NotesUiModule.kt
```

Mirror the package layout of the nearest existing feature. Add `data/` and `domain/` only when the
feature has them; a screen that only navigates needs neither.

### 5. Add the DI module

Each feature exposes one DI module and registers nothing globally. Koin example:

```kotlin
// feature/notes/logic/src/commonMain/kotlin/com/example/app/feature/notes/di/NotesModule.kt
val notesModule = module {
    singleOf(::NotesRepositoryImpl) bind NotesRepository::class
    factoryOf(::ObserveNotesUseCase)
    viewModelOf(::NotesListViewModel)   // org.koin.core.module.dsl, from koin-core-viewmodel
}
```

Register it where the app builds its graph — `startKoin { modules(appModule, notesModule) }` or an
aggregating `module { includes(notesModule) }`. In Shape B the iOS app starts the same graph through
the umbrella; see [references/ios-umbrella-framework.md](references/ios-umbrella-framework.md).
Done when the app module lists `notesModule`. A missing registration is a runtime
`NoDefinitionFoundException`, not a compile error, so check it now.

### 6. Register navigation

The feature owns its destinations; the host adds one line per feature. Cross-feature navigation goes
through callbacks that the app wires, never through another feature's route type.

```kotlin
// Shape A: feature module. Shape B: the :ui module.
@Serializable data object NotesListRoute
@Serializable data class NoteDetailRoute(val noteId: String)

fun NavGraphBuilder.notesGraph(navController: NavController, onOpenProfile: () -> Unit) {
    composable<NotesListRoute> {
        NotesListScreen(
            onNoteClick = { noteId -> navController.navigate(NoteDetailRoute(noteId)) },
            onProfileClick = onOpenProfile,
        )
    }
    composable<NoteDetailRoute> { NoteDetailScreen(onBack = { navController.popBackStack() }) }
}

// App NavHost — the only place that knows two features exist.
NavHost(navController = navController, startDestination = NotesListRoute) {
    notesGraph(navController = navController, onOpenProfile = { navController.navigate(ProfileRoute) })
    profileGraph(navController = navController)
}
```

If the project uses Navigation 3, Decompose or Voyager, follow its existing registration pattern
instead; the callback rule still holds. Done when the host compiles with the new line.

### 7. Wire it into its consumers

**Shape A.** The module that owns the `NavHost` and the DI graph adds
`implementation(project(":feature:notes"))`. If iOS only reaches the feature through Compose, no
`export` is needed; export only what Swift calls directly.

**Shape B.** Two consumers, and the umbrella needs **both** lines:

```kotlin
// shared/build.gradle.kts — the umbrella that produces the iOS framework
kotlin {
    listOf(iosArm64(), iosSimulatorArm64()).forEach { target ->
        target.binaries.framework {
            baseName = "Shared"
            export(project(":feature:notes:logic"))   // puts its public API in the Swift header
        }
    }
    sourceSets {
        commonMain.dependencies {
            api(project(":feature:notes:logic"))      // export() is legal only for api dependencies
        }
    }
}
```

```kotlin
// androidApp/build.gradle.kts
dependencies { implementation(project(":feature:notes:ui")) }
```

`export` without `api` fails the build. `api` without `export` is the silent failure: Android builds
and runs, Gradle is green, and Swift later reports `Cannot find 'NotesListViewModel' in scope`.
`export` is not transitive: if `NotesListViewModel` exposes `Note` from `:core:model`, export
`:core:model` too. Done when the header check in **Verify** finds the class.

### 8. Add the first test

Add one ViewModel or use-case test in `commonTest` using the project's test style (default
`kotlin.test` + a hand-written fake + Turbine). A template is in
[references/gradle-templates.md](references/gradle-templates.md#8-first-test). Done when the test
runs on both an Android and an iOS test task.

## Rule: no feature depends on another feature

A feature-to-feature dependency couples release cycles, invites cycles, and lets one feature reach
into another's internals. Allowed edges:

| From | May depend on |
|---|---|
| `:feature:notes:ui` | `:feature:notes:logic`, `:core:*`, design system |
| `:feature:notes` / `:feature:notes:logic` | `:core:*` (model, network, database, common) |
| `:core:*` | other `:core:*` only — never a feature, never the app |
| App / umbrella | every feature and `:core:*` |

When two features must cooperate:

1. **Navigation** — callbacks wired by the app (step 6).
2. **Shared data** — move the type to a `:core:` module once a *second* feature needs it, not before.
3. **Shared behaviour** — declare an interface in a `:core:` module, implement it in the owning
   feature, and bind it in the app's DI graph. The consuming feature sees only the interface.

Check it from the root (expect no output; assumes modules under `feature/<name>/`):

```bash
for f in $(find feature -name build.gradle.kts -not -path '*/build/*'); do
  own=$(echo "$f" | cut -d/ -f2)
  grep -HnoE 'project\(":feature:[A-Za-z0-9_-]+|projects\.feature\.[A-Za-z0-9_]+' "$f" \
    | grep -vE "(:feature:|projects\.feature\.)$own\$" || true
done
```

## Quick reference

| Task | Shape A | Shape B |
|---|---|---|
| Plugins | KMP, Android KMP library, Compose MP, Compose compiler | `:logic`: KMP, Android KMP library. `:ui`: plus Compose |
| iOS targets | same as consumers | `:logic` only; `:ui` is Android-only |
| `binaries.framework` | no (unless iOS links this module) | no; the umbrella has it |
| Umbrella edits | none, unless Swift calls it | `api(project(...))` **and** `export(project(...))` |
| Android app edit | via the module that hosts the NavHost | `implementation(project(":feature:<name>:ui"))` |
| DI | `val <name>Module` registered in the app graph | same, in `:logic`; UI-only bindings in `:ui` |
| Navigation | `NavGraphBuilder.<name>Graph(...)` | same, in `:ui` |

## Verify

Run what applies and report each line as `PASS`, `FAIL` or `NOT RUN` (with the reason, e.g. "no
macOS host"). Never report a check as passed that you did not run. If a task name differs, list the
real ones with `./gradlew :feature:notes:logic:tasks --all | grep -iE 'compile|test|link'`.

```bash
./gradlew :feature:notes:logic:compileCommonMainKotlinMetadata      # shared code alone
./gradlew :feature:notes:logic:compileAndroidMain                   # AGP KMP plugin (legacy: compileDebugKotlinAndroid)
./gradlew :feature:notes:logic:compileKotlinIosSimulatorArm64       # macOS only
./gradlew :feature:notes:logic:testAndroidHostTest                  # legacy plugin: testDebugUnitTest
./gradlew :feature:notes:logic:iosSimulatorArm64Test                # macOS only
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64               # Shape B umbrella, macOS only
grep -c 'swift_name("NotesListViewModel")' \
  shared/build/bin/iosSimulatorArm64/debugFramework/Shared.framework/Headers/Shared.h   # expect >= 1
./gradlew :androidApp:assembleDebug                                 # or :composeApp:assembleDebug
```

Then run the feature-boundary check above, and build the iOS app in Xcode if a scheme exists.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| `api(...)` in the umbrella but no `export(...)` | Android is fine; Swift cannot see the module, found late and far from the cause | Add `export(project(...))` to every framework binary; run the header grep |
| Exporting a module whose public types come from an un-exported module | `export` is not transitive; those types appear in Swift with module-prefixed names or not at all | Export the type's own module too; avoid `transitiveExport = true` (size and link time) |
| Compose dependency in a `:logic` module | The SwiftUI-facing framework drags in Compose, or exposes Compose types Swift cannot use | Keep Compose in `:ui`; put state the UI needs on the state class |
| Feature imports another feature | Coupled builds, cycles, internal APIs leak | Callbacks, `:core:` types, or an interface bound by the app |
| New module declares different iOS targets than its consumer | `No matching variant` / could not resolve for `iosX64` or similar | Copy the target list from the consuming module |
| `binaries.framework` in every feature module | Extra link tasks and framework files nobody ships | Frameworks only where iOS links |
| Two Kotlin frameworks linked into one iOS app | Each carries its own Kotlin runtime; shared types are not the same type in Swift | One umbrella framework per app |
| Forgot `withHostTest {}` with the AGP KMP plugin | `androidHostTest` sources silently never compile or run | Enable host tests in `kotlin { android { } }` |
| Compose resources without `androidResources { enable = true }` | Builds, then fails at runtime on Android | Enable Android resources in that module |
| Reading `BuildConfig` in a library module | The AGP KMP library plugin generates none | Inject config from the app module |
| DI module never registered | Runtime `NoDefinitionFoundException` on first screen open | Add it to the app graph in step 5 |

## Related skills

- `kmp-expect-actual` — platform code inside the new module.
- `kmp-gradle-version-catalog` — catalog entries, convention plugins, composite builds.
- `kmp-module-health` — audit the module once it exists.
- `compose-multiplatform-navigation`, `kmp-swiftui-interop`, `kmp-xcframework-distribution` in this repo,
  for navigation depth, the Swift side of the umbrella, and shipping it as an XCFramework.
- [Kotlin/kotlin-agent-skills](https://github.com/Kotlin/kotlin-agent-skills) — AGP 9 migration and
  Kotlin/Native build performance.
- [Kotlin Multiplatform docs](https://kotlinlang.org/docs/multiplatform/) and
  [Android KMP library plugin](https://developer.android.com/kotlin/multiplatform/plugin).
