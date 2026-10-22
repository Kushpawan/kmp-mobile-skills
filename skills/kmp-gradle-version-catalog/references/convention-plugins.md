# Convention plugins for KMP modules

A `build-logic` included build holds the configuration every KMP module repeats: plugins, targets,
SDK levels, test setup. Module build files then contain only what differs.

## Contents

1. [Layout](#1-layout)
2. [Wire it into the root build](#2-wire-it-into-the-root-build)
3. [Let build-logic read the same catalog](#3-let-build-logic-read-the-same-catalog)
4. [The KMP library convention plugin](#4-the-kmp-library-convention-plugin)
5. [A Compose convention plugin](#5-a-compose-convention-plugin)
6. [Using them in a module](#6-using-them-in-a-module)
7. [Pitfalls](#7-pitfalls)

## 1. Layout

```text
build-logic/
├── settings.gradle.kts
└── convention/
    ├── build.gradle.kts
    └── src/main/kotlin/
        ├── KmpLibraryConventionPlugin.kt
        └── KmpComposeConventionPlugin.kt
```

## 2. Wire it into the root build

```kotlin
// settings.gradle.kts (root)
pluginManagement {
    includeBuild("build-logic")
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}
```

```kotlin
// build.gradle.kts (root) — puts the real plugins on the classpath once
plugins {
    alias(libs.plugins.kotlinMultiplatform) apply false
    alias(libs.plugins.androidKotlinMultiplatformLibrary) apply false
    alias(libs.plugins.composeMultiplatform) apply false
    alias(libs.plugins.composeCompiler) apply false
}
```

## 3. Let build-logic read the same catalog

An included build does not inherit the root's catalog or repositories. Import the same file:

```kotlin
// build-logic/settings.gradle.kts
dependencyResolutionManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
    versionCatalogs {
        create("libs") { from(files("../gradle/libs.versions.toml")) }
    }
}
rootProject.name = "build-logic"
include(":convention")
```

The plugin code needs the Gradle plugins as libraries, so add catalog entries for their artifacts:

```toml
[libraries]
android-gradlePlugin = { module = "com.android.tools.build:gradle", version.ref = "agp" }
kotlin-gradlePlugin = { module = "org.jetbrains.kotlin:kotlin-gradle-plugin", version.ref = "kotlin" }
compose-gradlePlugin = { module = "org.jetbrains.compose:compose-gradle-plugin", version.ref = "composeMultiplatform" }
```

```kotlin
// build-logic/convention/build.gradle.kts
plugins {
    `kotlin-dsl`
}

dependencies {
    // compileOnly: the root build already loads these plugins (section 2).
    compileOnly(libs.android.gradlePlugin)
    compileOnly(libs.kotlin.gradlePlugin)
    compileOnly(libs.compose.gradlePlugin)
}

gradlePlugin {
    plugins {
        register("kmpLibrary") {
            id = "com.example.kmp.library"
            implementationClass = "KmpLibraryConventionPlugin"
        }
        register("kmpCompose") {
            id = "com.example.kmp.compose"
            implementationClass = "KmpComposeConventionPlugin"
        }
    }
}
```

## 4. The KMP library convention plugin

The AGP KMP library plugin registers no project-level `android {}` extension. Its DSL is the Android
*target* inside the Kotlin extension, reached through
`targets.withType(KotlinMultiplatformAndroidLibraryTarget::class.java)` (available since AGP 8.8).

```kotlin
// build-logic/convention/src/main/kotlin/KmpLibraryConventionPlugin.kt
import com.android.build.api.dsl.KotlinMultiplatformAndroidLibraryTarget
import org.gradle.api.Plugin
import org.gradle.api.Project
import org.gradle.api.artifacts.VersionCatalogsExtension
import org.gradle.kotlin.dsl.configure
import org.gradle.kotlin.dsl.getByType
import org.jetbrains.kotlin.gradle.dsl.KotlinMultiplatformExtension

class KmpLibraryConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) = with(target) {
        pluginManager.apply("org.jetbrains.kotlin.multiplatform")
        pluginManager.apply("com.android.kotlin.multiplatform.library")

        // Precompiled and binary plugins have no type-safe `libs`; look entries up by name.
        val libs = extensions.getByType<VersionCatalogsExtension>().named("libs")
        fun version(alias: String): String = libs.findVersion(alias).get().requiredVersion

        extensions.configure<KotlinMultiplatformExtension> {
            iosArm64()
            iosSimulatorArm64()

            targets.withType(KotlinMultiplatformAndroidLibraryTarget::class.java).configureEach {
                compileSdk = version("android-compileSdk").toInt()
                minSdk = version("android-minSdk").toInt()
                withHostTest {}
            }

            sourceSets.commonTest.dependencies {
                implementation(libs.findLibrary("kotlin-test").get())
                implementation(libs.findLibrary("kotlinx-coroutines-test").get())
            }
        }
    }
}
```

`configureEach { … }` uses the receiver form because `kotlin-dsl` turns Gradle `Action`s into
lambdas with receivers. Each module still sets its own `namespace`; deriving it from the project path
(`"com.example.app" + path.replace(':', '.')`) is an option if the team agrees on the convention.

## 5. A Compose convention plugin

```kotlin
// build-logic/convention/src/main/kotlin/KmpComposeConventionPlugin.kt
import org.gradle.api.Plugin
import org.gradle.api.Project

class KmpComposeConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) = with(target) {
        pluginManager.apply("org.jetbrains.compose")
        pluginManager.apply("org.jetbrains.kotlin.plugin.compose")
    }
}
```

Add the Compose artifacts every UI module uses in the same way as the test dependencies above, or
leave them in the module build files if modules differ.

## 6. Using them in a module

```kotlin
// feature/notes/build.gradle.kts
plugins {
    id("com.example.kmp.library")
    id("com.example.kmp.compose")
}

kotlin {
    android { namespace = "com.example.app.feature.notes" }
    sourceSets {
        commonMain.dependencies { implementation(project(":core:model")) }
    }
}
```

To apply convention plugins through the catalog instead of string IDs, add `[plugins]` entries
without a version (for example `example-kmp-library = { id = "com.example.kmp.library" }`) and use
`alias(libs.plugins.example.kmp.library)`.

## 7. Pitfalls

| Pitfall | Fix |
|---|---|
| `libs` unresolved inside `build-logic` | Import the catalog in `build-logic/settings.gradle.kts` (section 3) |
| `ClassNotFoundException` for an AGP or KGP type at configuration time | The root build must load the plugin (`apply false`), because build-logic uses `compileOnly` |
| `alias(libs.plugins.x)` inside a precompiled script plugin's `plugins {}` | Not supported; apply by ID with `pluginManager.apply("...")` |
| Convention plugin hardcodes SDK levels or versions | Read them from the catalog with `findVersion` |
| Every module gets every dependency "just in case" | Conventions carry configuration, not feature dependencies |
| One giant plugin for apps, libraries and Compose | Small composable plugins: library, compose, app |
