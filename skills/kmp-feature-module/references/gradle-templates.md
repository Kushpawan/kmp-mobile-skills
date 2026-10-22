# Gradle templates for KMP feature modules

Copy the closest existing sibling module first. Use these only when the project has no precedent,
and adjust aliases to the project's catalog naming.

## Contents

1. [Catalog entries the templates assume](#1-catalog-entries-the-templates-assume)
2. [Shape A — feature module with shared Compose UI](#2-shape-a--feature-module-with-shared-compose-ui)
3. [Shape B — `:logic` module](#3-shape-b--logic-module)
4. [Shape B — `:ui` module](#4-shape-b--ui-module)
5. [Shape B — umbrella `:shared`](#5-shape-b--umbrella-shared)
6. [With a convention plugin](#6-with-a-convention-plugin)
7. [Legacy layout: AGP 8 with `com.android.library`](#7-legacy-layout-agp-8-with-comandroidlibrary)
8. [First test](#8-first-test)

## 1. Catalog entries the templates assume

Keep the project's real version values; `<version>` marks where they go.

```toml
[versions]
agp = "<version>"
kotlin = "<version>"
composeMultiplatform = "<version>"
composeMaterial3 = "<version>"     # recent Compose Multiplatform releases version material3 separately
jetbrains-lifecycle = "<version>"  # org.jetbrains.androidx.* has its own version line
jetbrains-navigation = "<version>"
koin = "<version>"
kotlinx-coroutines = "<version>"
kotlinx-serialization = "<version>"
turbine = "<version>"
android-compileSdk = "<version>"
android-minSdk = "<version>"

[libraries]
compose-runtime = { module = "org.jetbrains.compose.runtime:runtime", version.ref = "composeMultiplatform" }
compose-foundation = { module = "org.jetbrains.compose.foundation:foundation", version.ref = "composeMultiplatform" }
compose-material3 = { module = "org.jetbrains.compose.material3:material3", version.ref = "composeMaterial3" }
navigation-compose = { module = "org.jetbrains.androidx.navigation:navigation-compose", version.ref = "jetbrains-navigation" }
lifecycle-viewmodel = { module = "org.jetbrains.androidx.lifecycle:lifecycle-viewmodel", version.ref = "jetbrains-lifecycle" }
lifecycle-viewmodel-compose = { module = "org.jetbrains.androidx.lifecycle:lifecycle-viewmodel-compose", version.ref = "jetbrains-lifecycle" }
koin-core = { module = "io.insert-koin:koin-core", version.ref = "koin" }
koin-core-viewmodel = { module = "io.insert-koin:koin-core-viewmodel", version.ref = "koin" }
koin-compose-viewmodel = { module = "io.insert-koin:koin-compose-viewmodel", version.ref = "koin" }
kotlinx-coroutines-core = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-core", version.ref = "kotlinx-coroutines" }
kotlinx-coroutines-test = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-test", version.ref = "kotlinx-coroutines" }
kotlinx-serialization-json = { module = "org.jetbrains.kotlinx:kotlinx-serialization-json", version.ref = "kotlinx-serialization" }
kotlin-test = { module = "org.jetbrains.kotlin:kotlin-test", version.ref = "kotlin" }
turbine = { module = "app.cash.turbine:turbine", version.ref = "turbine" }

[plugins]
kotlinMultiplatform = { id = "org.jetbrains.kotlin.multiplatform", version.ref = "kotlin" }
androidKotlinMultiplatformLibrary = { id = "com.android.kotlin.multiplatform.library", version.ref = "agp" }
androidApplication = { id = "com.android.application", version.ref = "agp" }
composeMultiplatform = { id = "org.jetbrains.compose", version.ref = "composeMultiplatform" }
composeCompiler = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
kotlinSerialization = { id = "org.jetbrains.kotlin.plugin.serialization", version.ref = "kotlin" }
```

The root `build.gradle.kts` declares each plugin once with `apply false` so every module shares one
plugin classloader:

```kotlin
plugins {
    alias(libs.plugins.kotlinMultiplatform) apply false
    alias(libs.plugins.androidKotlinMultiplatformLibrary) apply false
    alias(libs.plugins.androidApplication) apply false
    alias(libs.plugins.composeMultiplatform) apply false
    alias(libs.plugins.composeCompiler) apply false
    alias(libs.plugins.kotlinSerialization) apply false
}
```

## 2. Shape A — feature module with shared Compose UI

`feature/notes/build.gradle.kts`. Screens, ViewModels and data all live in `commonMain`; iOS renders
them through the app's `ComposeUIViewController`.

```kotlin
plugins {
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.androidKotlinMultiplatformLibrary)
    alias(libs.plugins.composeMultiplatform)
    alias(libs.plugins.composeCompiler)
    alias(libs.plugins.kotlinSerialization)   // @Serializable navigation routes
}

kotlin {
    android {
        namespace = "com.example.app.feature.notes"
        compileSdk = libs.versions.android.compileSdk.get().toInt()
        minSdk = libs.versions.android.minSdk.get().toInt()
        withHostTest {}                       // off by default; creates androidHostTest
        androidResources { enable = true }    // off by default; Compose resources need it
    }

    // Same list as the module that links the iOS framework.
    iosArm64()
    iosSimulatorArm64()

    sourceSets {
        commonMain.dependencies {
            implementation(project(":core:model"))
            implementation(libs.compose.runtime)
            implementation(libs.compose.foundation)
            implementation(libs.compose.material3)
            implementation(libs.navigation.compose)
            implementation(libs.lifecycle.viewmodel.compose)
            implementation(libs.koin.compose.viewmodel)
            implementation(libs.kotlinx.serialization.json)
        }
        commonTest.dependencies {
            implementation(libs.kotlin.test)
            implementation(libs.kotlinx.coroutines.test)
            implementation(libs.turbine)
        }
    }
}
```

## 3. Shape B — `:logic` module

`feature/notes/logic/build.gradle.kts`. Kotlin only, no Compose. It compiles into the framework that
SwiftUI consumes, so everything public here is Swift API.

```kotlin
plugins {
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.androidKotlinMultiplatformLibrary)
    alias(libs.plugins.kotlinSerialization)   // only if it declares @Serializable types
    // No Compose plugins in this module.
}

kotlin {
    android {
        namespace = "com.example.app.feature.notes.logic"
        compileSdk = libs.versions.android.compileSdk.get().toInt()
        minSdk = libs.versions.android.minSdk.get().toInt()
        withHostTest {}
    }

    iosArm64()
    iosSimulatorArm64()
    // No binaries.framework here: the umbrella module produces the only framework.

    sourceSets {
        commonMain.dependencies {
            api(project(":core:model"))            // its types appear in this module's public API
            api(libs.lifecycle.viewmodel)          // ViewModel is a supertype of public classes
            implementation(libs.kotlinx.coroutines.core)
            implementation(libs.koin.core)
            implementation(libs.koin.core.viewmodel)   // viewModelOf DSL without Compose
        }
        commonTest.dependencies {
            implementation(libs.kotlin.test)
            implementation(libs.kotlinx.coroutines.test)
            implementation(libs.turbine)
        }
    }
}
```

Use `api` only for dependencies whose types appear in this module's public signatures; everything
else is `implementation`. Every `api` dependency of an exported module becomes a candidate for the
umbrella's `export` list.

## 4. Shape B — `:ui` module

`feature/notes/ui/build.gradle.kts`. Compose screens for Android only. Keeping it a KMP module with a
single Android target leaves the code in `commonMain`, so adding iOS Compose later is a target change,
not a move. A plain Android library module is also fine if that is what siblings use.

```kotlin
plugins {
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.androidKotlinMultiplatformLibrary)
    alias(libs.plugins.composeMultiplatform)
    alias(libs.plugins.composeCompiler)
    alias(libs.plugins.kotlinSerialization)   // routes declared here
}

kotlin {
    android {
        namespace = "com.example.app.feature.notes.ui"
        compileSdk = libs.versions.android.compileSdk.get().toInt()
        minSdk = libs.versions.android.minSdk.get().toInt()
        androidResources { enable = true }
    }
    // No iOS targets: iOS renders this feature in SwiftUI from the :logic module.

    sourceSets {
        commonMain.dependencies {
            api(project(":feature:notes:logic"))
            implementation(libs.compose.runtime)
            implementation(libs.compose.foundation)
            implementation(libs.compose.material3)
            implementation(libs.navigation.compose)
            implementation(libs.lifecycle.viewmodel.compose)
            implementation(libs.koin.compose.viewmodel)
            implementation(libs.kotlinx.serialization.json)
        }
    }
}
```

## 5. Shape B — umbrella `:shared`

`shared/build.gradle.kts`. The single iOS framework. It lists every `:logic` module twice: once as an
`api` dependency, once in `export`.

```kotlin
plugins {
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.androidKotlinMultiplatformLibrary)
}

kotlin {
    // Keep the Android target only if the Android app consumes :shared (for example for the DI
    // aggregate). If Android depends on the features directly, the umbrella can be iOS-only.
    android {
        namespace = "com.example.app.shared"
        compileSdk = libs.versions.android.compileSdk.get().toInt()
        minSdk = libs.versions.android.minSdk.get().toInt()
    }

    listOf(iosArm64(), iosSimulatorArm64()).forEach { target ->
        target.binaries.framework {
            baseName = "Shared"          // the Swift module name: `import Shared`
            isStatic = true              // match what the Xcode project already links
            export(project(":core:model"))
            export(project(":feature:notes:logic"))
            export(project(":feature:profile:logic"))
        }
    }

    sourceSets {
        commonMain.dependencies {
            api(project(":core:model"))
            api(project(":feature:notes:logic"))
            api(project(":feature:profile:logic"))
            implementation(libs.koin.core)
        }
    }
}
```

`api` may also be declared in `iosMain.dependencies` instead of `commonMain` when only the iOS
framework needs it; `export` accepts `api` dependencies of the source set that compiles the binary.

## 6. With a convention plugin

When the build has `build-logic/` convention plugins, a feature build file shrinks to the parts that
differ per module. Plugin IDs are examples; use the project's.

```kotlin
plugins {
    id("com.example.kmp.library")    // KMP + Android KMP library plugin, iOS targets, SDK levels
    id("com.example.kmp.compose")    // Shape A, or Shape B :ui only
}

kotlin {
    android { namespace = "com.example.app.feature.notes" }
    sourceSets {
        commonMain.dependencies {
            implementation(project(":core:model"))
        }
    }
}
```

Writing the convention plugin itself is covered by `kmp-gradle-version-catalog`.

## 7. Legacy layout: AGP 8 with `com.android.library`

Projects that have not migrated still use `androidTarget()` plus a top-level `android {}` block.
Match it in a new module rather than mixing plugins in one build. On AGP 9 this combination works
only behind opt-out flags and is scheduled for removal, so plan the migration separately.

```kotlin
plugins {
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.androidLibrary)   // com.android.library
}

kotlin {
    androidTarget()
    iosArm64()
    iosSimulatorArm64()

    sourceSets {
        commonMain.dependencies { implementation(project(":core:model")) }
    }
}

android {
    namespace = "com.example.app.feature.notes"
    compileSdk = libs.versions.android.compileSdk.get().toInt()
    defaultConfig { minSdk = libs.versions.android.minSdk.get().toInt() }
}
```

Differences to remember: source sets are `androidUnitTest` / `androidInstrumentedTest` (not
`androidHostTest` / `androidDeviceTest`), tasks are `compileDebugKotlinAndroid` and
`testDebugUnitTest`, and Android resources are on by default.

## 8. First test

`feature/notes/logic/src/commonTest/kotlin/com/example/app/feature/notes/presentation/NotesListViewModelTest.kt`.
It runs on every target (`testAndroidHostTest`, `iosSimulatorArm64Test`). The ViewModel under test:

```kotlin
data class NotesListState(val notes: List<Note> = emptyList(), val isLoading: Boolean = true)

class NotesListViewModel(observeNotes: ObserveNotesUseCase) : ViewModel() {
    val state: StateFlow<NotesListState> = observeNotes()
        .map { notes -> NotesListState(notes = notes, isLoading = false) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), NotesListState())
}
```

The test, with a hand-written fake instead of a mocking library (most mocking libraries are JVM-only
and do not compile for iOS test targets):

```kotlin
@OptIn(ExperimentalCoroutinesApi::class)
class NotesListViewModelTest {
    private val testDispatcher = StandardTestDispatcher()

    // viewModelScope uses Dispatchers.Main, which tests must replace on every platform.
    @BeforeTest fun setUp() = Dispatchers.setMain(testDispatcher)
    @AfterTest fun tearDown() = Dispatchers.resetMain()

    @Test
    fun should_exposeNotes_when_repositoryEmits() = runTest(testDispatcher) {
        val repository = FakeNotesRepository(initial = listOf(Note(id = "1", title = "Groceries")))
        val viewModel = NotesListViewModel(observeNotes = ObserveNotesUseCase(repository))

        viewModel.state.test {
            assertEquals(NotesListState(), awaitItem())
            assertEquals(listOf("Groceries"), awaitItem().notes.map { it.title })
        }
    }
}

private class FakeNotesRepository(initial: List<Note>) : NotesRepository {
    private val notes = MutableStateFlow(initial)
    override fun observeNotes(): Flow<List<Note>> = notes
}
```
