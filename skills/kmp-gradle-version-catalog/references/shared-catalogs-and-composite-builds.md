# Shared catalogs and composite builds

How several repositories share one set of versions, how to find drift, and how to build an app
against a local checkout of a library.

## Contents

1. [Choosing how to share a catalog](#1-choosing-how-to-share-a-catalog)
2. [Option A: git submodule](#2-option-a-git-submodule)
3. [Option B: published catalog](#3-option-b-published-catalog)
4. [Auditing drift](#4-auditing-drift)
5. [Composite builds for local library work](#5-composite-builds-for-local-library-work)
6. [Composite build pitfalls](#6-composite-build-pitfalls)

## 1. Choosing how to share a catalog

| Option | Good for | Cost |
|---|---|---|
| One catalog per repo, kept aligned by audit | Few repos, loose coupling | Drift is normal; needs the audit in section 4 |
| Git submodule with the TOML file | Repos released together; versions change often | Every consumer must update the submodule pointer; easy to forget `git submodule update` |
| Published catalog (`version-catalog` plugin) | Many consumers, versioned releases of the platform | A release per catalog change; consumers bump one coordinate |

Whichever you choose, each consuming build still has exactly one catalog named `libs`.

## 2. Option A: git submodule

The submodule lives at a fixed path (here `gradle/shared-catalog/`). Adding or moving a submodule
changes the repository; confirm with the user before running git commands.

```kotlin
// settings.gradle.kts of each consumer
dependencyResolutionManagement {
    versionCatalogs {
        create("libs") { from(files("gradle/shared-catalog/libs.versions.toml")) }
    }
}
```

Do not also keep a `gradle/libs.versions.toml` in that repo. Gradle imports that file automatically
as `libs`, and a second `from(...)` for the same catalog fails the build. CI must check out
submodules (`git submodule update --init`), or the import fails with a missing file.

## 3. Option B: published catalog

```kotlin
// catalog/build.gradle.kts in the platform repo
plugins {
    `version-catalog`
    `maven-publish`
}

catalog {
    versionCatalog { from(files("../gradle/libs.versions.toml")) }
}

publishing {
    publications {
        create<MavenPublication>("catalog") { from(components["versionCatalog"]) }
    }
}
```

```kotlin
// settings.gradle.kts of each consumer
dependencyResolutionManagement {
    repositories { mavenCentral() /* plus the private Maven repository that hosts the catalog */ }
    versionCatalogs {
        create("libs") {
            from("com.example:catalog:<version>")
            version("kotlin", "<override>")   // optional local override of one version key
        }
    }
}
```

Use overrides sparingly and record why; an override is drift by design.

## 4. Auditing drift

`scripts/catalog_drift.py` (in this skill) compares any number of catalogs and lists:

- `versions` keys whose values differ or are missing,
- `libraries` and `plugins` aliases whose module, id or *resolved* version differs (so two catalogs
  that use different `version.ref` keys for the same library still compare correctly),
- `inline` entries with a literal version instead of `version.ref`,
- `hardcoded` versioned coordinates and plugin versions in `*.gradle(.kts)` files (`--scan-gradle`).

```bash
python3 scripts/catalog_drift.py app=../notes-app/gradle/libs.versions.toml \
                                 sdk=../notes-sdk/gradle/libs.versions.toml \
                                 --only-differs --format json
python3 scripts/catalog_drift.py gradle/libs.versions.toml --scan-gradle . --fail-on-drift
```

`--only-differs` hides keys that exist in only some catalogs (normal when repos use different
libraries). Exit codes: `0` clean or report-only, `1` drift with `--fail-on-drift`, `2` bad input.

Resolving drift: pick the highest version that every consumer has actually been built and tested
against, change it in one place, and rebuild every consumer. Ask before downgrading anything.

## 5. Composite builds for local library work

Gradle substitutes an included build's projects for external coordinates automatically when the
project's `group:name` matches the dependency. Most published libraries set a different artifact
name than the project name, so declare the substitution explicitly:

```kotlin
// settings.gradle.kts of the consuming app
fun localFlag(name: String): Boolean =
    providers.gradleProperty("local.$name").orNull == "true" ||
        providers.gradleProperty("local.all").orNull == "true"

if (localFlag("notes-sdk")) {
    includeBuild("../notes-sdk") {
        dependencySubstitution {
            substitute(module("com.example:notes-sdk")).using(project(":sdk"))
        }
    }
}
```

```bash
./gradlew :androidApp:assembleDebug -Plocal.notes-sdk=true
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64 -Plocal.notes-sdk=true   # iOS, macOS only
```

Build files keep using `libs.notes.sdk`; only resolution changes. An `export(libs.notes.sdk)` in an
iOS framework follows the substitution in practice, so Swift sees the local code too.

For a one-off run without editing settings: `./gradlew --include-build ../notes-sdk <task>`
(automatic substitution only).

## 6. Composite build pitfalls

| Pitfall | Effect | Fix |
|---|---|---|
| Flag defaults to on, or is committed as `true` | CI and teammates build unpublished code | Default off; local `gradle.properties` changes stay uncommitted |
| Library change validated with the flag off | The app built the published artifact; the change was never exercised | Rebuild every consumer with the flag on before publishing |
| Different Kotlin or AGP versions in the two builds | Confusing plugin and metadata errors | Same versions across the composite |
| Included build relies on the consumer's repositories or catalog | Included builds are configured in isolation | The library's own `settings.gradle.kts` declares both |
| Substitution names a project path that does not exist | Configuration fails in the consumer | Match `project(":sdk")` to the library's `settings.gradle.kts` |
| Custom publishing logic in the library (renamed artifacts) | Automatic substitution misses it | Explicit `substitute(module(...)).using(project(...))` |
