---
name: kmp-gradle-version-catalog
description: Use when adding, upgrading or auditing dependencies and Gradle plugins in a Kotlin Multiplatform project - libs.versions.toml, [versions] [libraries] [plugins] [bundles], "Could not resolve" or "No matching variant" for iosArm64, Kotlin vs Compose Multiplatform vs AGP vs KSP compatibility, one catalog shared across several repos (git submodule or published catalog), version drift, build-logic convention plugins, or includeBuild with dependencySubstitution for local library development.
license: Apache-2.0
compatibility: Gradle 8+ Kotlin Multiplatform project. The drift script needs Python 3.11+ (standard library only, no network). iOS compile checks need macOS with Xcode.
metadata:
  category: build
  platforms: android, ios
---

# KMP Gradle version catalog and dependencies

Every version lives in exactly one version catalog, every dependency lands in the narrowest source
set that needs it, and nothing goes into `commonMain` until you have confirmed it publishes iOS
variants. Upgrades of Kotlin, Compose Multiplatform, AGP and KSP move together or not at all.

## When to use

- Adding a library or Gradle plugin, or a bundle of them.
- "Could not resolve", "No matching variant" or a Kotlin metadata/ABI version error after adding one.
- Upgrading Kotlin, Compose Multiplatform, AGP, KSP or Gradle.
- Several repositories should share one catalog, or their versions have drifted.
- Extracting repeated build configuration into convention plugins.
- Developing a library locally while an app consumes it.

## When not to use

- Creating the module that will use the dependency: `kmp-feature-module`.
- Writing the platform abstraction around an Android-only library: `kmp-expect-actual`.
- Migrating a project to AGP 9 as a whole: the AGP 9 migration skill in
  [Kotlin/kotlin-agent-skills](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-agp9-migration).
- A failing build you have not yet diagnosed: `kmp-build-failure-triage` in this repo.

## Step 0 — Read the project first

```bash
ls gradle/libs.versions.toml 2>/dev/null                       # default catalog location
grep -nE 'versionCatalogs|from\(|includeBuild|dependencySubstitution|repositoriesMode' settings.gradle.kts
cat .gitmodules 2>/dev/null                                     # catalog shared as a submodule?
ls build-logic buildSrc 2>/dev/null                             # convention plugins
grep -nE '^(kotlin|agp|composeMultiplatform|compose-multiplatform|ksp)\s*=' gradle/libs.versions.toml
grep -rnE '"[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:[0-9]' --include='*.gradle.kts' . | grep -v /build/ | head
```

| Record | Why |
|---|---|
| Catalog path: `gradle/libs.versions.toml`, a file imported in `settings.gradle.kts`, or a published `group:artifact:version` | Edit the real source of truth, not a copy |
| Alias style: `ktor-client-core` (accessor `libs.ktor.client.core`) or camelCase | New entries match existing ones |
| Version key style: `kotlinx-coroutines` vs `kotlinxCoroutines` | Same |
| Kotlin, AGP, Compose Multiplatform, KSP, Gradle versions | Decide compatibility before choosing a library version |
| Convention plugins | Shared config belongs there, not copied into modules |
| `includeBuild` + substitution flags | Local-library mode exists; know its property names |
| Existing hardcoded versions in build files | Report them; do not add more |

## Workflow A — Add a dependency

1. **Confirm the targets.** For anything going into `commonMain`, confirm iOS variants exist:
   search [klibs.io](https://klibs.io), read the library's docs, or check Maven Central for per-target
   artifacts (`<artifact>-iosarm64`, `<artifact>-iossimulatorarm64`):

   ```bash
   G=io/ktor A=ktor-client-core
   for t in iosarm64 iossimulatorarm64; do
     printf '%-18s %s\n' "$t" "$(curl -s -o /dev/null -w '%{http_code}' \
       "https://repo1.maven.org/maven2/$G/$A-$t/maven-metadata.xml")"
   done   # 200 = published; androidx artifacts live on Google Maven instead
   ```

   No iOS variant means the library is Android-only: put it in `androidMain` behind an interface
   (`kmp-expect-actual`). Done when you know which source set it belongs in.
2. **Confirm the Kotlin version.** A library compiled by a newer Kotlin than the project's can fail
   with a metadata or ABI version error, especially on Kotlin/Native. Read its release notes for the
   Kotlin it was built with. Done when the chosen version supports the project's Kotlin.
3. **Add catalog entries.** One `[versions]` key per version family, `version.ref` everywhere,
   aliases in the file's existing style. Pin an exact stable version taken from the library's
   releases page; never `+`, `latest.release` or a range unless the project already uses rich
   versions. Entry forms, naming rules, BOMs and rich versions are in
   [references/catalog-syntax.md](references/catalog-syntax.md).

   ```toml
   [versions]
   ktor = "<exact version>"

   [libraries]
   ktor-client-core = { module = "io.ktor:ktor-client-core", version.ref = "ktor" }
   ktor-client-content-negotiation = { module = "io.ktor:ktor-client-content-negotiation", version.ref = "ktor" }
   ktor-serialization-kotlinx-json = { module = "io.ktor:ktor-serialization-kotlinx-json", version.ref = "ktor" }
   ktor-client-okhttp = { module = "io.ktor:ktor-client-okhttp", version.ref = "ktor" }
   ktor-client-darwin = { module = "io.ktor:ktor-client-darwin", version.ref = "ktor" }
   ktor-client-mock = { module = "io.ktor:ktor-client-mock", version.ref = "ktor" }

   [bundles]
   ktor-common = ["ktor-client-core", "ktor-client-content-negotiation", "ktor-serialization-kotlinx-json"]
   ```

4. **Wire it into the narrowest source set.**

   ```kotlin
   kotlin {
       sourceSets {
           commonMain.dependencies { implementation(libs.bundles.ktor.common) }
           androidMain.dependencies { implementation(libs.ktor.client.okhttp) }   // engine per platform
           iosMain.dependencies { implementation(libs.ktor.client.darwin) }
           commonTest.dependencies { implementation(libs.ktor.client.mock) }
       }
   }
   ```

   Use `api` only when the dependency's types appear in this module's public API (and therefore
   in an iOS `export`). Done when the module compiles for every target (Verify).
5. **Plugins.** Add a `[plugins]` entry, declare it once in the root `build.gradle.kts` with
   `alias(libs.plugins.x) apply false`, then `alias(libs.plugins.x)` in the module. Catalog plugin
   aliases cannot be used in `settings.gradle.kts`.
6. **Annotation processors (KSP).** KMP needs one configuration per target, for example
   `add("kspAndroid", libs.androidx.room.compiler)`, `add("kspIosArm64", …)`,
   `add("kspIosSimulatorArm64", …)`, and `kspIosX64` if that target exists. A missing target either
   fails that target's compilation or, for processors whose output is looked up at runtime, fails
   only when the app runs on that platform. Done when every declared target has a line.

## Workflow B — Upgrade Kotlin, Compose Multiplatform, AGP or KSP

Change one axis per commit and run the full Verify after each. These must agree:

| Component | Constraint |
|---|---|
| Kotlin Multiplatform, Compose compiler (`org.jetbrains.kotlin.plugin.compose`), serialization plugin | Same version as Kotlin: give them all `version.ref = "kotlin"` |
| Compose Multiplatform (`org.jetbrains.compose`) | Each release needs a minimum Kotlin; current releases need Kotlin 2.1.0+ and 2.2.20+ for iOS. See the [compatibility page](https://kotlinlang.org/docs/multiplatform/compose-compatibility-and-versioning.html) |
| `material3`, `navigation-compose`, `lifecycle-*` under `org.jetbrains.*` | Own version lines; take them from the Compose Multiplatform release notes, not from the CMP version |
| AGP | Each Kotlin Gradle plugin release supports an AGP range; see the table in [Configure a Gradle project](https://kotlinlang.org/docs/gradle-configure-project.html) |
| Gradle, JDK | Minimums come from AGP and KGP; AGP 9 needs JDK 17+ |
| KSP | Releases before 2.3.0 are versioned `<kotlin>-<ksp>` and must match Kotlin exactly; 2.3.0+ have their own line. Check the [KSP releases](https://github.com/google/ksp/releases) |
| Xcode | Each Kotlin release supports an Xcode range; see the [KMP compatibility guide](https://kotlinlang.org/docs/multiplatform/multiplatform-compatibility-guide.html) |

Dependencies compiled with an older Kotlin are usually fine; dependencies compiled with a newer one
are not. Upgrade the project's Kotlin first, then libraries that require it.

## Workflow C — Share one catalog across repositories

Options, how to set each up, and how to override a version locally are in
[references/shared-catalogs-and-composite-builds.md](references/shared-catalogs-and-composite-builds.md).
In short: a git submodule imported with `from(files(...))`, or a catalog published with the
`version-catalog` plugin and imported with `from("com.example:catalog:<version>")`.

Audit drift between catalogs, and hardcoded versions in build scripts, with the bundled script
(paths relative to this skill's directory; read-only; output is a table or JSON):

```bash
python3 scripts/catalog_drift.py app=../notes-app/gradle/libs.versions.toml \
                                 sdk=../notes-sdk/gradle/libs.versions.toml --only-differs
python3 scripts/catalog_drift.py gradle/libs.versions.toml --scan-gradle . --format json
python3 scripts/catalog_drift.py --help
```

Exit code 1 with `--fail-on-drift` makes it usable in CI. Never downgrade to resolve drift without
asking; align on the highest version that every consumer has been built against.

## Workflow D — Convention plugins

When three or more modules repeat the same plugins, targets and SDK levels, move that block into a
`build-logic` included build. Full setup — `build-logic/settings.gradle.kts` reading the same catalog,
`compileOnly` plugin artifacts, and a `KmpLibraryConventionPlugin` that configures the
AGP KMP library target — is in [references/convention-plugins.md](references/convention-plugins.md).
Do not create `build-logic` in a project that has none without asking; it is a structural change.

## Workflow E — Develop a library locally against an app

Gate an `includeBuild` behind a Gradle property so the default build always uses the published
artifact:

```kotlin
// settings.gradle.kts of the consuming app
if (providers.gradleProperty("local.notes-sdk").orNull == "true") {
    includeBuild("../notes-sdk") {
        dependencySubstitution {
            substitute(module("com.example:notes-sdk")).using(project(":sdk"))
        }
    }
}
```

```bash
./gradlew :androidApp:assembleDebug -Plocal.notes-sdk=true
```

With the flag off, local library edits reach no consumer. Rebuild every consumer with its flag on
before publishing a library change. Keep Kotlin and AGP identical across the composite. Never commit
the flag as `true`. Details and pitfalls are in the shared-catalogs reference.

## Quick reference

| Task | How |
|---|---|
| Library accessor | `ktor-client-core` → `libs.ktor.client.core`; `[bundles] ktor-common` → `libs.bundles.ktor.common` |
| Plugin accessor | `libs.plugins.kotlinMultiplatform` in `plugins { alias(...) }` |
| Version in Kotlin code | `libs.versions.android.minSdk.get().toInt()` |
| Reserved alias words | `extensions`, `class`, `convention`; `bundles`, `versions`, `plugins` cannot start an alias |
| Common-only dependency | `commonMain.dependencies { implementation(...) }` |
| Platform-only dependency | `androidMain` / `iosMain` |
| Test-only | `commonTest`; JVM-only test libraries (MockK, JUnit 5) go in `androidHostTest`, never `commonTest` |
| BOM (Android only) | `androidMain.dependencies { implementation(project.dependencies.platform(libs.firebase.bom)) }` |
| KSP | `add("ksp<Target>", libs.x.compiler)` for each target |
| Local library | `includeBuild` + `dependencySubstitution`, gated by `-Plocal.<lib>=true` |

## Verify

Report every check as `PASS`, `FAIL` or `NOT RUN` (with the reason). Never report a check that did
not run as passed. Replace `:shared` with each module you touched.

```bash
./gradlew help                                         # catalog and settings parse
./gradlew :shared:compileCommonMainKotlinMetadata
./gradlew :shared:compileAndroidMain                   # legacy plugin: compileDebugKotlinAndroid
./gradlew :shared:compileKotlinIosSimulatorArm64       # macOS only; proves the iOS variant resolves
./gradlew :shared:allTests                             # or the project's test tasks
./gradlew :androidApp:assembleDebug                    # or :composeApp:assembleDebug
./gradlew :shared:dependencyInsight --dependency ktor-client-core --configuration <configuration>
python3 scripts/catalog_drift.py gradle/libs.versions.toml --scan-gradle . --fail-on-drift
```

List configuration names for `dependencyInsight` with `./gradlew :shared:dependencies | grep -i classpath`.
After a Kotlin upgrade also link the iOS framework (`linkDebugFrameworkIosSimulatorArm64`) and
build the Xcode project.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Android-only library in `commonMain` | iOS compilation fails with "No matching variant" or unresolved artifacts | `androidMain` plus an interface in common |
| Version literal in `build.gradle.kts` | Drifts from the catalog; invisible to upgrades | Catalog entry with `version.ref` |
| Compose compiler or serialization plugin on its own version key | Mismatched Kotlin compiler plugins fail the build after an upgrade | `version.ref = "kotlin"` |
| Using the Compose Multiplatform version for material3, navigation or lifecycle | Those artifacts have separate version lines; the version may not exist or may not match | Take each from the CMP release notes |
| JVM-only test library in `commonTest` | iOS test compilation fails | Fakes in `commonTest`; JVM tools in `androidHostTest` |
| Plugin versions requested per module instead of once in the root | "The Kotlin Gradle plugin was loaded multiple times in different subprojects", or "already on the classpath with an unknown version" when build-logic also provides it | `apply false` in root, versionless `alias` in modules |
| A catalog named `libs` imported from a file while `gradle/libs.versions.toml` also exists | Gradle auto-imports the default file; calling `from` twice fails | One source: delete the stray file or rename one catalog |
| KSP configured for some targets only | That target fails to compile, or crashes at runtime where generated code is looked up dynamically | One `ksp<Target>` line per target |
| `includeBuild` always on | CI and teammates build unpublished code; releases differ from what was tested | Gate it with a property that defaults to off |
| Upgrading Kotlin, AGP and CMP in one commit | A failure cannot be attributed | One axis per commit |
| Accessing `libs.plugins.*` inside a precompiled script plugin's `plugins {}` | Not supported by Gradle | Binary convention plugins with `VersionCatalogsExtension` |

## Related skills

- `kmp-feature-module` — new modules and their build files.
- `kmp-module-health` — audits hardcoded versions and build config per module.
- `kmp-build-failure-triage` in this repo — diagnosing a red build.
- [Kotlin/kotlin-agent-skills](https://github.com/Kotlin/kotlin-agent-skills) — AGP 9 migration,
  Kotlin/Native build performance.
- [chrisbanes/skills `gradle-run`](https://github.com/chrisbanes/skills/tree/main/skills/gradle-run) —
  running Gradle with compact output.
- [Gradle version catalogs](https://docs.gradle.org/current/userguide/version_catalogs.html),
  [composite builds](https://docs.gradle.org/current/userguide/composite_builds.html),
  [KMP dependencies](https://kotlinlang.org/docs/multiplatform/multiplatform-add-dependencies.html).
