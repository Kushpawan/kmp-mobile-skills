---
name: kmp-build-failure-triage
description: Use when a Kotlin Multiplatform build fails on Android or iOS — Gradle, KSP, Kotlin/Native link or Xcode errors such as "Undefined symbols for architecture arm64", "framework not found", "No such module", "Could not resolve" in commonMain, expect/actual mismatches, "Command PhaseScriptExecution failed", JAVA_HOME or sandbox errors in the Xcode run script, Kotlin daemon OutOfMemoryError, configuration cache problems, "Duplicate class", or R8 missing classes.
license: Apache-2.0
compatibility: Kotlin Multiplatform Gradle project. iOS steps need macOS with Xcode; Android steps need a JDK supported by the project's Android Gradle Plugin.
metadata:
  category: debug
  platforms: android, ios
---

# KMP build failure triage

The last line of a failed build is almost never the cause. Find the **first real error**, name the
layer it belongs to, make the smallest fix, then prove that **both** platforms still build. A KMP
change that fixes iOS can break Android, and the reverse.

## When to use

- Any red build in a KMP project: Gradle sync/configuration, dependency resolution, Kotlin compile
  (common or platform), KSP, Kotlin/Native framework link, Swift compile, Xcode link, Android
  dex/R8.
- "Works on Android, fails on iOS" (or the reverse), "works locally, fails on CI", "broke after a
  version bump".
- Link-time configuration that only shows up at runtime on iOS (for example a database driver that
  crashes on first use).

## When not to use

- The app builds and then crashes for a reason unrelated to build configuration — use
  `kmp-crash-triage`.
- Nothing is failing yet and you only want to confirm a change builds on both platforms — use
  `kmp-build-check`.
- Builds succeed but are slow — see the
  [Kotlin/Native build performance skill](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-native-build-performance).
- Packaging, SPM and versioning problems after the framework exists — use
  `kmp-xcframework-distribution`. Swift API shape questions — use `kmp-swiftui-interop`.

## Step 0 — Read the project first

Collect the facts before touching anything. Most "mystery" failures are a version or environment
mismatch that these commands expose.

```bash
./gradlew --version                         # Gradle and the JVM Gradle actually runs on
java -version 2>&1 | head -1; /usr/libexec/java_home -V 2>&1 | head -5
xcodebuild -version; uname -m               # Xcode, and arm64 vs x86_64 host
grep -nE '^(kotlin|agp|android|compose|ksp|skie|kmmbridge|room|sqlite|ktor|coroutines|serialization)' \
  gradle/libs.versions.toml
grep distributionUrl gradle/wrapper/gradle-wrapper.properties
cat gradle.properties                       # jvmargs, configuration cache, kotlin.native.* flags
grep -rnE "iosArm64|iosSimulatorArm64|iosX64|androidTarget|androidLibrary|jvm\(" --include=*.gradle.kts . | head
git log --oneline -5 && git diff --stat HEAD~1   # what changed right before it broke
```

Also establish: does it fail locally, on CI, or both; on a clean checkout; on one machine
architecture only. Follow the project's existing build conventions (version catalog, convention
plugins, CI scripts) — fix inside them, never around them.

## Workflow

### 1. Reproduce on the command line with a full log

```bash
./gradlew <failing-task> --stacktrace --console=plain 2>&1 | tee build.log
xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp \
  -destination 'generic/platform=iOS Simulator' build 2>&1 | tee xcode.log
```

IDE summaries hide the first error. Add `--info` only when the plain log does not explain the
failure. **Done when** a log file contains the failure.

### 2. Find the first real error

```bash
grep -nE '^e: |error:|What went wrong|Caused by:|Undefined symbols|ld: |FAILED|Exception' build.log | head -40
```

- Kotlin compiler errors start with `e: ` (warnings `w: `). The **first** `e:` is the cause; later
  ones usually cascade from it.
- Gradle's `* What went wrong:` names the failed task; the reason is above it or in the deepest
  `Caused by:` of the stack trace.
- Linker failures: read the `Undefined symbols for architecture …` block — the symbol name and its
  `referenced from` line. `ld: symbol(s) not found` and `clang: error: linker command failed` are
  just the footer.
- Xcode: `Command PhaseScriptExecution failed with a nonzero exit code` only says the run script
  failed. Expand that step in the build log (Report navigator) and read the Gradle output inside it.
- CI: use the raw job log, not the annotated summary; find the first failing step.

**Done when** you can quote one line that states the cause.

### 3. Classify the layer

| Layer | Recognise it by | Smallest task that reproduces it |
|---|---|---|
| Environment | JDK, Xcode, memory, sandbox, PATH messages | `./gradlew help` |
| Dependency resolution | `Could not resolve`, `No matching variant`, metadata/ABI version errors | `./gradlew :shared:dependencies` (filter for the failing configuration) |
| Gradle configuration | Fails before any task runs; plugin, DSL or configuration-cache errors | `./gradlew help` |
| Kotlin compile (common) | `e:` in `commonMain` files | `./gradlew :shared:compileCommonMainKotlinMetadata` |
| Kotlin compile (platform) | `e:` only for one target; expect/actual errors | `:shared:compileKotlinIosSimulatorArm64` / the Android compile task |
| KSP / code generation | Missing generated class; works on one target only | `:shared:kspKotlinIosSimulatorArm64` (list: `tasks --all \| grep -i ksp`) |
| Kotlin/Native link | `linkDebugFramework…` or `linkDebugTest…` fails; `Undefined symbols` | `:shared:linkDebugFrameworkIosSimulatorArm64` |
| Swift compile | `No such module`, `cannot find … in scope`, `has no member` | `xcodebuild … build` |
| Xcode link | `framework not found`, `Undefined symbols` in the app target | `xcodebuild … build` |
| Android packaging | `Duplicate class`, D8/R8 errors, missing keep rules | `:composeApp:assembleRelease` (or the failing variant) |

Task names differ with plugin setup; confirm with `./gradlew :shared:tasks --all | grep -iE "compile|link|ksp"`.

### 4. Apply the smallest fix

Look the symptom up in the quick reference below; the full symptom → cause → fix catalog, grouped by
layer, is in [references/error-catalog.md](references/error-catalog.md). Change one thing, re-run the
smallest task, repeat.

### 5. Caches last, and only the one you suspect

Do not open with `./gradlew clean`, deleting `~/.gradle`, `~/.konan` or DerivedData. Clear a cache
only when the evidence points to it (the error names a file that no longer exists, a clean checkout
builds, the failure follows one machine). Clear the specific cache, and **ask the user before
deleting any directory**. Stop Gradle daemons with `./gradlew --stop` first — a daemon started with
different settings (sandboxed, different JDK) is a cache too.

### 6. Rebuild both platforms

Run the matrix in Verify. **Done when** every check is `PASS`, or `NOT RUN` with a reason.

### 7. Report

One line of root cause, the fix, what was verified (with PASS / FAIL / NOT RUN), and any workaround
that must be removed later (a disabled cache, a pinned version, a suppressed check).

## Quick reference

| Symptom | First thing to check |
|---|---|
| `Undefined symbols for architecture arm64:` with `_sqlite3_…` | Static framework needs system SQLite linked by the consumer — or you use a bundled SQLite and should not link the system one |
| `Undefined symbols` only in `linkDebugTest…` | Linker options set on `binaries.framework` but not `binaries.all` |
| Swift sees a type prefixed with a module name, or not at all | Module is `api(...)` but not `export(...)` in the framework block (or the reverse) |
| `No such module 'SharedKit'` | Framework not built for this configuration/architecture; run script after Compile Sources; product not linked |
| `framework not found` / `ld: framework 'SharedKit' not found` | Search paths or `OTHER_LDFLAGS` point at a framework that was never built for this SDK/config |
| `Could not find module … for target 'x86_64-apple-ios-simulator'` | No `iosX64` slice and the host/simulator is x86_64 |
| `Could not resolve` in `commonMain` / `No matching variant` | Library has no KMP (iOS) variant — move it to `androidMain` or pick a KMP library |
| `… compiled with an incompatible version of Kotlin` | A dependency was built with a newer Kotlin |
| expect/actual "has no actual" / "no corresponding expected" | Missing `actual` for one target, or package/signature mismatch |
| Room works on Android, iOS crashes on first DB use | KSP compiler not added for every iOS target |
| `Starting in Kotlin 2.0, the Compose Compiler Gradle plugin is required` | Apply `org.jetbrains.kotlin.plugin.compose` at the Kotlin version |
| iOS build broke right after a Kotlin bump; Android fine | SKIE / KSP / Compose Multiplatform do not support that Kotlin version yet |
| Run script: `JAVA_HOME is not set` / wrong Java version | Xcode does not load your shell profile |
| Run script: `Sandbox: … deny(1) file-read-data` | User Script Sandboxing is on |
| `OutOfMemoryError` / daemon disappeared during iOS link | `org.gradle.jvmargs` too small — the Kotlin/Native compiler runs in the Gradle daemon |
| `Configuration cache problems found in this build` | A task or plugin touches `Project` at execution time |
| `Duplicate class … found in modules …` | Same classes from two artifacts |
| `Missing classes detected while running R8` | Missing keep/`-dontwarn` rules; check `missing_rules.txt` |

## Verify

Report every check as `PASS`, `FAIL` or `NOT RUN` with the reason. Never mark a check that did not
run as passed. Adjust task names to the project (Step 0).

```bash
./gradlew :shared:compileCommonMainKotlinMetadata         # common code
./gradlew :composeApp:assembleDebug                       # Android app (or the project's app module)
./gradlew :shared:testDebugUnitTest                       # JVM/Android unit tests (name varies by plugin)
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64     # iOS framework link
./gradlew :shared:iosSimulatorArm64Test                   # iOS tests (links the test executable too)
xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp \
  -destination 'generic/platform=iOS Simulator' build     # the iOS app itself
```

- No macOS, no Xcode, or no simulator runtime (`xcrun simctl list runtimes`) → the iOS checks are
  `NOT RUN — <reason>`. Say that CI must cover them.
- If the original failure was release-only (R8, release link), also run the release variant
  (`assembleRelease`, `linkReleaseFrameworkIosArm64`).
- If the fix touched linker options, check the symbol the runtime needs is present (for SQLite:
  `nm -gU <framework binary> | grep _sqlite3_sourceid` when a bundled copy is expected).

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Fixing the last error in the log | It is a cascade or a footer | Fix the first `e:` / first `Undefined symbols` entry |
| `clean` + deleting caches as step one | Slow, hides the real cause, often "fixes" nothing | Classify first; clear one cache with evidence, after asking |
| Verifying only the platform that failed | KMP fixes cross platforms (`api`/`export`, source sets, linker flags) | Run the full matrix |
| Adding `-lsqlite3` to silence undefined SQLite symbols | With a bundled SQLite driver it can make the bundled copy disappear from the binary | Decide system vs bundled; link exactly one |
| `transitiveExport = true` to make a type visible | Exports everything; longer links, bigger binary | `api` + `export` the one module |
| Bumping Kotlin alone | SKIE, KSP, Compose Multiplatform and AGP have compatibility ranges | Bump the set together; check each project's compatibility notes |
| Setting `org.gradle.java.home` to a personal path in the project's `gradle.properties` | Breaks every other machine and CI | Put it in `~/.gradle/gradle.properties`, or export `JAVA_HOME` in the run script |
| Disabling the configuration cache or Kotlin/Native caches permanently | Slower builds forever for a one-off issue | Treat as a temporary workaround; record why |
| Adding `OTHER_LDFLAGS` in the app for a library problem | Every consumer must repeat it | Fix in the library's package (`linkerSettings`) or Gradle config |
| Removing `iosX64` to speed up builds | Intel-hosted simulators and CI lose the module | Keep it when anyone runs x86_64 simulators |

## Related skills

- `kmp-xcframework-distribution` — XCFramework, SPM `binaryTarget`, linker settings for consumers.
- `kmp-swiftui-interop` — Swift-side API problems once the build is green.
- `kmp-build-check` — the both-platform build and test matrix after the fix.
- `kmp-gradle-version-catalog` — aligning Kotlin, Compose Multiplatform, AGP, KSP and SKIE versions.
- `kmp-expect-actual` — designing the platform split when an expect/actual error is really a design problem.
- `kmp-crash-triage` — crashes that are not caused by build configuration.
- `kmp-ci-github-actions` — failures that only happen on CI runners.
- [Kotlin agent skills](https://github.com/Kotlin/kotlin-agent-skills) — including the
  [AGP 9 migration](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-agp9-migration)
  and [Kotlin/Native build performance](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-native-build-performance) skills.
- [MobileBuildMCP](https://github.com/getsentry/MobileBuildMCP) (formerly XcodeBuildMCP) — structured
  Xcode build and simulator access for agents.
- Docs: [KMP compatibility guide](https://kotlinlang.org/docs/multiplatform/multiplatform-compatibility-guide.html),
  [Compose Multiplatform compatibility](https://kotlinlang.org/docs/multiplatform/compose-compatibility-and-versioning.html),
  [Kotlin/Native compilation time](https://kotlinlang.org/docs/native-improving-compilation-time.html).
