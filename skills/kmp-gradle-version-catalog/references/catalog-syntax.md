# Version catalog syntax for KMP projects

## Contents

1. [Entry forms](#1-entry-forms)
2. [Alias naming and accessors](#2-alias-naming-and-accessors)
3. [Versions without a library](#3-versions-without-a-library)
4. [BOM-managed and versionless entries](#4-bom-managed-and-versionless-entries)
5. [Rich versions](#5-rich-versions)
6. [House rules worth adopting](#6-house-rules-worth-adopting)

## 1. Entry forms

```toml
[versions]
kotlin = "<version>"
koin = "<version>"

[libraries]
# Preferred: module + version.ref
koin-core = { module = "io.insert-koin:koin-core", version.ref = "koin" }
# Equivalent long form
koin-test = { group = "io.insert-koin", name = "koin-test", version.ref = "koin" }
# Literal version: allowed, but drifts silently; the drift script reports it as "inline"
turbine = { module = "app.cash.turbine:turbine", version = "<version>" }

[plugins]
kotlinMultiplatform = { id = "org.jetbrains.kotlin.multiplatform", version.ref = "kotlin" }

[bundles]
koin-common = ["koin-core", "koin-test"]   # entries are library aliases, not modules
```

A bundle is only a list of aliases; it does not merge versions or scopes. Use bundles for sets that
always travel together in the same source set.

## 2. Alias naming and accessors

| TOML alias | Accessor | Note |
|---|---|---|
| `ktor-client-core` | `libs.ktor.client.core` | Dashes and underscores become dots |
| `ktorClientCore` | `libs.ktorClientCore` | camelCase avoids sub-groups |
| `[versions] android-minSdk` | `libs.versions.android.minSdk` | `.get()` returns the string |
| `[plugins] composeCompiler` | `libs.plugins.composeCompiler` | Only inside `plugins { alias(...) }` |
| `[bundles] ktor-common` | `libs.bundles.ktor.common` | |

Reserved: `extensions`, `class` and `convention` cannot be aliases, and `bundles`, `versions` and
`plugins` cannot be the first segment of a library alias (`versions-x` is invalid; `x-versions`
is fine). An alias that is both a leaf and a group (`ktor-client` and `ktor-client-core`) works but
reads poorly; prefer distinct names.

## 3. Versions without a library

Values such as SDK levels, JVM targets or the framework name can live in `[versions]` so every
module reads the same value:

```toml
[versions]
android-compileSdk = "<level>"
android-minSdk = "<level>"
```

```kotlin
compileSdk = libs.versions.android.compileSdk.get().toInt()
```

## 4. BOM-managed and versionless entries

Some Android-only libraries are versioned by a BOM. Keep the library entry versionless and import
the BOM where the library is used:

```toml
[libraries]
firebase-bom = { module = "com.google.firebase:firebase-bom", version.ref = "firebaseBom" }
firebase-crashlytics = { module = "com.google.firebase:firebase-crashlytics" }
```

```kotlin
kotlin {
    sourceSets {
        androidMain.dependencies {
            implementation(project.dependencies.platform(libs.firebase.bom))
            implementation(libs.firebase.crashlytics)
        }
    }
}
```

Versionless entries are fine for BOM members. Anywhere else, a missing version is a resolution error
waiting to happen.

## 5. Rich versions

```toml
[versions]
kotlinx-coroutines = { strictly = "[1.9, 2.0[", prefer = "<version>" }
```

Members: `require` (the plain-string meaning), `strictly`, `prefer`, `reject`, `rejectAll`. Rich
versions are a tool for library authors who must express a range. In applications, an exact version
is easier to reason about. Remember the catalog only *requests* versions; conflict resolution may
still pick a higher one. Check with `dependencyInsight`.

## 6. House rules worth adopting

- Sort each section, or group it with comments (`# Networking`, `# Testing`), and keep to it.
- Comment any version that is pinned on purpose (`# held at X until the iOS crash in Y is fixed`).
- One `[versions]` key per release train (`ktor`, `koin`), not one per artifact.
- Compiler plugins tied to Kotlin (`plugin.compose`, `plugin.serialization`) use `version.ref = "kotlin"`.
- A dependency change goes in its own commit, so a regression can be bisected to it.
