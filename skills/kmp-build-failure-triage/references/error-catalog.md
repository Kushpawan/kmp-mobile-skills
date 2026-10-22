# KMP build error catalog

Contents

1. How to read this table
2. Environment (JDK, memory, sandbox)
3. Dependency resolution
4. Version compatibility
5. Gradle configuration and configuration cache
6. Kotlin compile and expect/actual
7. KSP and code generation
8. Kotlin/Native link
9. Xcode: Swift compile, link and run script
10. Link configuration that fails at runtime
11. Android packaging (duplicate classes, R8)

## 1. How to read this table

- **Exact** strings are error text that ships in the tools as far as this catalog knows. Strings
  marked *(typical wording)* change between tool versions — match on the key phrase.
- Lessons marked *observed with …* were seen with the stated versions; treat them as strong hints,
  not laws, on other versions.
- Each fix is the minimal one. If it does not apply, go back to the first error in the log.

## 2. Environment (JDK, memory, sandbox)

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: JAVA_HOME is not set and no 'java' command could be found in your PATH.` in the Xcode build log | Xcode runs the run script without your shell profile, so no JDK is found | In the run script, before `./gradlew`: `export JAVA_HOME="$(/usr/libexec/java_home -v 17)"` (use the JDK version the project needs), or set `org.gradle.java.home` in **`~/.gradle/gradle.properties`** (per machine, never in the project file) |
| `Android Gradle plugin requires Java 17 to run` *(typical wording; version varies)*, or `Unsupported class file major version …` | Gradle runs on an older/newer JDK than the build supports | Run Gradle on the required JDK (`./gradlew --version` shows which one it uses); align IDE, terminal, Xcode and CI |
| `Sandbox: java(…) deny(1) file-read-data …` / `deny(1) file-write-create` *(typical wording)* in the run-script output | Xcode User Script Sandboxing blocks Gradle from reading/writing the project | Build Settings → User Script Sandboxing (`ENABLE_USER_SCRIPT_SANDBOXING`) = `No`, then `./gradlew --stop` so a sandboxed daemon is not reused |
| `java.lang.OutOfMemoryError: Java heap space` / `Metaspace` during `link…Framework…` or `compileKotlinIos…` | The Kotlin/Native compiler runs inside the Gradle daemon by default, so its heap is `org.gradle.jvmargs` | `org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g` (size to the machine); fewer parallel links on small CI hosts (`--max-workers=2`) |
| `OutOfMemoryError` in a Kotlin daemon / "The daemon has terminated unexpectedly" *(typical wording)* while compiling JVM/Android Kotlin | Kotlin daemon heap too small | `kotlin.daemon.jvmargs=-Xmx3g` in `gradle.properties` |
| CI host killed mid-link with no Kotlin error | Container memory limit below Gradle + Kotlin daemon + K/N peak | Lower `-Xmx` below the container limit, reduce workers, or a larger runner |
| `xcrun: error: unable to find utility "xcodebuild"` / no simulator runtime | Command Line Tools selected instead of Xcode, or runtime not installed | `sudo xcode-select -s /Applications/Xcode.app` (ask first — it is a system setting); install the runtime in Xcode → Settings → Components |

## 3. Dependency resolution

| Symptom | Cause | Fix |
|---|---|---|
| `Could not resolve <group>:<artifact>:<version>` for an iOS or `commonMain` configuration, often with `No matching variant of … was found` and the attribute `org.jetbrains.kotlin.platform.type` = `native` *(typical wording)* | The library is JVM/Android-only — no Kotlin/Native variant | Move the dependency to `androidMain`; use a KMP alternative; or hide it behind `expect`/`actual` or an interface bound per platform. Check Maven Central for per-target artifacts (`<artifact>-iosarm64`) to confirm KMP support |
| `Could not find <group>:<artifact>:<version>` | Repository not declared in `settings.gradle.kts` (`dependencyResolutionManagement`), wrong version, or expired private-repo credentials | Declare the repository once in settings; refresh the CI token; check the exact version exists |
| `Module was compiled with an incompatible version of Kotlin. The binary version of its metadata is X, expected version is Y.` | A dependency was built with a newer Kotlin than yours | Upgrade Kotlin (and its companions) or use an older library version |
| KLIB resolver errors mentioning an incompatible ABI version or an unresolved klib *(typical wording)* | A Kotlin/Native library built with a newer compiler | Same as above |
| Android-only dependency resolves but iOS compile shows `Unresolved reference` | Dependency added to `androidMain` (or `jvmMain`) but used from `commonMain` | Use it only behind an abstraction in `commonMain` |
| Version from the catalog ignored | A `build.gradle.kts` hardcodes another version, or a BOM/platform forces one | Remove the hardcoded version; inspect with `./gradlew :shared:dependencyInsight --dependency <name> --configuration <configuration>` |

## 4. Version compatibility

| Symptom | Cause | Fix |
|---|---|---|
| `Starting in Kotlin 2.0, the Compose Compiler Gradle plugin is required when compose is enabled` | Compose compiler plugin not applied | Apply `org.jetbrains.kotlin.plugin.compose` in every Compose module, at exactly the Kotlin version (catalog: `version.ref = "kotlin"`) |
| Compose Multiplatform compile errors or warnings about an unsupported Kotlin version right after a bump | Compose Multiplatform and Kotlin out of range | Check the [Compose Multiplatform compatibility page](https://kotlinlang.org/docs/multiplatform/compose-compatibility-and-versioning.html); move both together |
| Warning that the Android Gradle Plugin version is newer than the Kotlin Gradle Plugin was tested with *(typical wording)*, then odd Android-target failures | KGP and AGP outside the supported matrix | Check the [KMP compatibility guide](https://kotlinlang.org/docs/multiplatform/multiplatform-compatibility-guide.html); align versions |
| After moving to AGP 9: KMP module using `com.android.library` with the multiplatform plugin fails or warns *(typical wording)* | AGP 9 expects the Android-KMP library plugin (`com.android.kotlin.multiplatform.library`) for KMP modules | Follow the official [AGP 9 migration skill](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-agp9-migration) |
| KSP errors immediately after a Kotlin bump | KSP release not compatible with that Kotlin | Pick the KSP release that lists your Kotlin version in its [release notes](https://github.com/google/ksp/releases) |
| iOS compile/link fails after a Kotlin bump; Android fine; stack mentions SKIE *(typical wording)* | SKIE supports a bounded Kotlin range (at the time of writing 2.0.0 – 2.4.10) and lags new Kotlin releases | Upgrade SKIE to a release that supports the new Kotlin, or hold Kotlin back. Check [SKIE's docs](https://skie.touchlab.co) before every Kotlin upgrade |
| Xcode-version-specific Kotlin/Native failures after an Xcode upgrade | Kotlin version older than what that Xcode requires | Check the Xcode column of the KMP compatibility guide; upgrade Kotlin |

## 5. Gradle configuration and configuration cache

| Symptom | Cause | Fix |
|---|---|---|
| `Configuration cache problems found in this build.` | A task reads `Project`, `Task.project` or mutable global state at execution time | Fix the task (capture values at configuration time; use providers). For a third-party plugin you cannot fix, mark its tasks `notCompatibleWithConfigurationCache(…)` or set `org.gradle.configuration-cache.problems=warn` **temporarily** |
| `invocation of 'Task.project' at execution time is unsupported` | Same | Same |
| `Plugin request for plugin already on the classpath must not include a version` | Plugin declared with a version in more than one build file | Declare versions once (root `plugins { alias(...) apply false }`), use `alias(...)` without a version in modules |
| `The Default Kotlin Hierarchy Template was not applied to …` *(typical wording)* | Manual `dependsOn(...)` edges between source sets disable the default hierarchy | Delete the manual edges and use the default `iosMain`/`appleMain` sets, or configure the hierarchy explicitly |
| Gradle sync works, CLI build fails (or the reverse) | IDE and CLI use different JDKs or Gradle properties | Make the IDE use the Gradle wrapper and the same JDK; compare `./gradlew --version` |

## 6. Kotlin compile and expect/actual

| Symptom | Cause | Fix |
|---|---|---|
| `Expected class 'X' has no actual declaration in module …` / `'expect' declaration … has no corresponding 'actual'` *(typical wording, differs between K1 and K2)* | `actual` missing for one target — often a new target added, or the `actual` placed in `iosArm64Main` instead of `iosMain` | Put iOS actuals in `iosMain` (shared by all iOS targets through the default hierarchy); add one per declared platform |
| `Actual … has no corresponding expected declaration` *(typical wording)* | Package, name or signature differs from the `expect` | Same package and exact signature; check default parameter values are only on the `expect` |
| Warning that `expect`/`actual` classes are in Beta, failing because warnings are errors | Expected and actual classes are Beta | Add `-Xexpect-actual-classes` to `compilerOptions.freeCompilerArgs`, or replace the expect class with an interface + DI |
| `Unresolved reference` only in iOS compilation | JVM API (`java.*`, `String.format`, `System.currentTimeMillis`) used from `commonMain`; compiled fine for Android only | Use a KMP library (kotlinx-datetime, kotlinx-io) or an `expect`/`actual` |
| `Redeclaration` across source sets | The same declaration in `iosMain` and `iosArm64Main` (or `commonMain` and a platform set) | Keep one |
| Compose `@Composable` errors in a module that should not use Compose | Compose plugin missing in that module, or Compose code leaked into a logic-only module | Apply the plugins where Compose lives; move the UI code out |

## 7. KSP and code generation

| Symptom | Cause | Fix |
|---|---|---|
| Room works on Android; iOS crashes at `Room.databaseBuilder(…)` with a message that the `RoomDatabaseConstructor` cannot be found *(typical wording)* | The Room compiler ran only for Android | Add the compiler to every target: `add("kspAndroid", libs.androidx.room.compiler)`, `add("kspIosArm64", …)`, `add("kspIosSimulatorArm64", …)`, `add("kspIosX64", …)` for each declared target |
| With `@ConstructedBy(AppDatabaseConstructor::class)`: iOS compile says the `expect object AppDatabaseConstructor` has no `actual` | Same cause, surfaced at compile time (the better outcome) | Same fix. Keep `@ConstructedBy` so the problem stays a compile error |
| Generated code visible on Android, `Unresolved reference` in `commonMain` | Processor runs only per target; common code needs metadata generation | Use `kspCommonMainMetadata` and add the generated metadata directory to `commonMain`, as the processor's docs describe; or keep generated-type usage in platform code |
| KSP task runs but generates nothing for iOS | Processor applied with `ksp(...)` (single-platform style) instead of per-target `add("ksp<Target>", …)` | Per-target configurations in the root `dependencies { }` block of the module |

## 8. Kotlin/Native link

| Symptom | Cause | Fix |
|---|---|---|
| `Undefined symbols for architecture arm64:` listing `_sqlite3_…` | System SQLite not linked. Dynamic framework: Kotlin/Native needs `-lsqlite3`. Static framework: the **app's** link needs it | Dynamic: `linkerOpts("-lsqlite3")` in the framework block. Static: the consumer adds `sqlite3` (SPM `linkerSettings: [.linkedLibrary("sqlite3")]` or `OTHER_LDFLAGS = -lsqlite3`). Not when using a bundled SQLite — see section 10 |
| `Undefined symbols` only in `linkDebugTestIosSimulatorArm64` / `iosSimulatorArm64Test`; the framework links | Linker options declared inside `binaries.framework { }` only | Move them to `binaries.all { linkerOpts(…) }` so test executables get them |
| `Undefined symbols … _sqlite3_load_extension` *(observed with the androidx.sqlite native driver linked against iOS system SQLite)* | The iOS SDK's SQLite does not provide extension loading | Prefer the bundled SQLite driver; or provide a no-op C definition through a small cinterop `.def` |
| `Undefined symbols … _OBJC_CLASS_$_<Class>` | Kotlin code (via cinterop or a KMP library) uses an Apple framework or native SDK the final link does not include | Link the framework: `linkerOpts("-framework", "<Name>")` for dynamic; consumer `linkedFramework("<Name>")` / the SDK's own package for static |
| `ld: warning: object file … was built for newer iOS version than being linked` *(typical wording)* | Deployment targets differ between the Kotlin framework and the app | Raise the app's deployment target, or lower the framework's minimum (Kotlin/Native deployment-target setting) |
| `duplicate symbol` | Two static Kotlin frameworks in one app, or the same static library linked through two paths | One umbrella framework; remove the duplicate linking path |
| Swift sees `Feature_notesNote` (module-prefixed) or does not see a type at all | The module is a dependency but not exported | `api(project(":feature:notes"))` in the iOS-compiled source set **and** `export(project(":feature:notes"))` in the framework block |
| `e: Compilation failed` at the very end of `linkReleaseFrameworkIos…`, with a `FileNotFoundException` under `build/skie/…/analytics/` *(observed with SKIE 0.10.x on CI)* | SKIE's analytics phase failed to write its report; the framework itself was fine | `skie { analytics { enabled.set(false) } }` (`disableUpload` alone does not skip the write) |
| `xcodebuild -create-xcframework` "No 'swiftinterface' files found" *(typical wording; observed with SKIE frameworks)* | Seen when no explicit bundle id was set, and when certain exports changed the produced Swift module | `binaryOption("bundleId", "com.example.app.SharedKit")`; re-check exports; rebuild clean |
| Kotlin/Native warning "Cannot infer a bundle ID from packages of source files and exported dependencies" *(typical wording)* | No explicit bundle id | Same `binaryOption("bundleId", …)` |
| Release link runs 20–30+ minutes or hits the CI timeout | Large umbrella framework, whole-program optimisation, many slices | Build only shipped slices; drop unused exports; enough heap; persist `~/.konan`. Last resort, *observed with Kotlin 2.x*: `freeCompilerArgs += "-Xdisable-phases=Devirtualization,RemoveRedundantCallsToStaticInitializersPhase"` — internal phase names, a wrong name is silently ignored; confirm with temporary `-Xprofile-phases`, and measure size/performance |
| Strange link errors that disappear on another machine, mentioning cached libraries *(typical wording)* | Corrupt or stale Kotlin/Native cache in `~/.konan` | `./gradlew --stop`, then remove the affected cache under `~/.konan` (ask first). As a temporary workaround only: `kotlin.native.cacheKind=none`, or the newer opt-in `disableNativeCache(…)` DSL. Remove the workaround once it builds |

## 9. Xcode: Swift compile, link and run script

| Symptom | Cause | Fix |
|---|---|---|
| `Command PhaseScriptExecution failed with a nonzero exit code` | Only the footer: the Kotlin run script failed | Read the script's output above it; triage that error |
| `No such module 'SharedKit'` | Run script placed after Compile Sources; framework not built for this configuration or architecture; `FRAMEWORK_SEARCH_PATHS` wrong; module name ≠ `baseName`; SPM product not added to the target | Run script before Compile Sources; align names; add the product; build once from Xcode after `./gradlew --stop` |
| `ld: framework not found SharedKit` / `ld: framework 'SharedKit' not found` *(wording differs by linker version)* | `OTHER_LDFLAGS` has `-framework SharedKit` but the search path has no framework for this SDK/config | Fix search paths; for custom build configurations set `KOTLIN_FRAMEWORK_BUILD_TYPE` (`Debug` or `Release`) in the target's User-Defined settings |
| `Could not find module 'SharedKit' for target 'x86_64-apple-ios-simulator'; found: arm64-apple-ios-simulator` *(typical wording)* | No `iosX64` slice and the build is for an x86_64 simulator (Intel Mac, Rosetta, CI host) | Add `iosX64()`; or build for an arm64 simulator; check `ARCHS` / `EXCLUDED_ARCHS` |
| `embedAndSignAppleFrameworkForXcode` fails when run from a terminal, asking to run it from Xcode *(typical wording)* | The task needs Xcode's environment (`SDK_NAME`, `CONFIGURATION`, …) | From the CLI use `linkDebugFrameworkIosSimulatorArm64` (or the XCFramework tasks) instead |
| `Task 'embedAndSignAppleFrameworkForXcode' not found` *(typical wording)* | No `binaries.framework` on the iOS targets of that module, or wrong module path in the script | Declare the framework; fix `:shared` in the script |
| Swift changes in Kotlin not picked up; old API still visible | Run script has "Based on dependency analysis" enabled, or Xcode reused a stale framework | Uncheck "Based on dependency analysis"; Product → Clean Build Folder for that target |
| `Value of type '…' has no member '…'` right after a Kotlin change | Kotlin name differs in Swift (`init…` → `doInit…`, nested-class concatenation, SKIE renames) or stale framework | Read the generated header; rebuild |
| `Building for 'iOS-simulator', but linking in object file built for 'iOS'` *(typical wording)* | A device slice was linked into a simulator build (fat framework or wrong search path) | Use an XCFramework or the per-SDK framework that the Gradle task produces |

## 10. Link configuration that fails at runtime

These build green and fail on the device. They belong here because the fix is in the build.

| Symptom | Cause | Fix |
|---|---|---|
| iOS-only crash on first database use with `SQLITE_MISUSE` *(observed with Room 2.8, androidx.sqlite 2.6, Kotlin 2.3 on iOS 26)* | The framework uses a bundled SQLite but also links the system one (directly or via a dependency that adds `-lsqlite3`); the linker took the system symbols and dropped the bundled archive, so the bundled driver ran against OS SQLite. Passed on local builds, failed after CI's release link | Remove `-lsqlite3` from your build. If a dependency still pulls it in, force-load the bundled archive (`-Wl,-force_load,<libandroidXBundledSqlite.a>` extracted from the `sqlite-bundled` cinterop klib per target) and add `-u _sqlite3_sourceid`. Gate releases on `nm -gU <framework binary> \| grep _sqlite3_sourceid` |
| Crash naming `@Throws` the first time an error path runs | Not a build error, but often reported as one: a Kotlin exception crossed into Swift | See `kmp-swiftui-interop` |
| Release-only `SerializationException: Serializer for class 'X' is not found.` on Android | Serialization plugin not applied in the module that declares `X`, or R8 removed the serializer (named companion objects, R8 full mode) | Apply the `org.jetbrains.kotlin.plugin.serialization` plugin there; follow the R8 rules in the [kotlinx.serialization README](https://github.com/Kotlin/kotlinx.serialization) |

## 11. Android packaging (duplicate classes, R8)

| Symptom | Cause | Fix |
|---|---|---|
| `Duplicate class <name> found in modules <a> and <b>` | Same classes from two artifacts (a relocated artifact, an old `-jvm` artifact next to the KMP one, Guava's `listenablefuture`) | Find both with `./gradlew :composeApp:dependencies --configuration <variant>RuntimeClasspath`; exclude one or align versions with a BOM / `resolutionStrategy` |
| `Missing classes detected while running R8. Please add the missing classes or apply additional keep rules that are generated in …missing_rules.txt` | A dependency references classes absent at runtime | Read `missing_rules.txt`; add `-dontwarn` only for classes truly absent at runtime; add the dependency if they are needed |
| Works in debug, `ClassNotFoundException` / `NoSuchMethodException` in release | Reflection target removed by R8 | Keep rules for the reflected classes (the library's consumer rules first) |
| `Type … is defined multiple times` from D8 *(typical wording)* | Same as duplicate classes, detected at dexing | Same fix |
