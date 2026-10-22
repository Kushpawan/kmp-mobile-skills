# Kover setup for a KMP module

- [What Kover measures in a KMP build](#what-kover-measures-in-a-kmp-build)
- [Version catalog and plugin](#version-catalog-and-plugin)
- [One exclusion list for the whole project](#one-exclusion-list-for-the-whole-project)
- [Filters and thresholds](#filters-and-thresholds)
- [Tasks and report locations](#tasks-and-report-locations)
- [Report-only coverage in CI](#report-only-coverage-in-ci)
- [Several modules](#several-modules)

Adding a plugin changes the user's build. Show the diff and get a yes before you apply it.

## What Kover measures in a KMP build

- **Only JVM-target tests count.** Those are Android unit or host tests, and `jvm()` tests. The Kover
  docs say it plainly: native and JS targets are not supported. Code that runs only in `iosMain`
  never shows up, and running `iosSimulatorArm64Test` adds nothing to the number.
- So the number shows how much of `commonMain` (plus `androidMain` / `jvmMain`) the JVM run of
  `commonTest` and the JVM-side test sets exercises. Still run the iOS tests: they catch behaviour that
  differs on Kotlin/Native. They just do not move the coverage number.
- With Android build variants, the default ("total") report runs the tests of **every** variant. A
  variant report such as `koverXmlReportDebug` runs only that variant's tests and is faster.
- Use Kover 0.9.2 or later with the `com.android.kotlin.multiplatform.library` plugin: support for that
  plugin arrived in 0.9.2, and later 0.9.x releases fixed it further.

## Version catalog and plugin

```toml
# gradle/libs.versions.toml
[versions]
kover = "0.9.11"   # latest 0.9.x when this was written; check the releases page

[plugins]
kover = { id = "org.jetbrains.kotlinx.kover", version.ref = "kover" }
```

```kotlin
// <module>/build.gradle.kts
plugins {
    alias(libs.plugins.kover)
}
```

## One exclusion list for the whole project

Keep exclusions in one plain-text file, for example `gradle/coverage-exclusions.txt` (start from
`assets/coverage-exclusions.txt`). Every module loads it, and `kover_gaps.py --exclusions` reads the
same file, so the ranking and the build always agree.

```kotlin
// <module>/build.gradle.kts
val coverageExclusions: List<String> = rootProject.file("gradle/coverage-exclusions.txt")
    .readLines()
    .map { it.trim() }
    .filter { it.isNotEmpty() && !it.startsWith("#") }
```

Why a file and not a list inside each `kover {}` block: when exclusions are copied into every module,
they drift apart, and a reviewer cannot see in one place what is hidden from the number.

## Filters and thresholds

```kotlin
// <module>/build.gradle.kts
import kotlinx.kover.gradle.plugin.dsl.CoverageUnit

val minLineCoverage = (findProperty("coverage.minLine") as String?)?.toInt() ?: 80
val minBranchCoverage = (findProperty("coverage.minBranch") as String?)?.toInt() ?: 60

kover {
    reports {
        filters {
            excludes {
                classes(coverageExclusions)
                // Excludes annotated declarations: Compose UI and serializer-only DTOs
                annotatedBy(
                    "androidx.compose.runtime.Composable",
                    "kotlinx.serialization.Serializable",
                )
            }
        }
        verify {
            rule("Line coverage") {
                bound { minValue = minLineCoverage }          // LINE is the default unit
            }
            rule("Branch coverage") {
                bound {
                    minValue = minBranchCoverage
                    coverageUnits = CoverageUnit.BRANCH
                }
            }
        }
    }
}

// One command for "tests + reports + threshold"
tasks.register("coverage") {
    group = "verification"
    description = "Runs JVM tests, writes HTML + XML coverage, fails below the thresholds"
    dependsOn("koverHtmlReport", "koverXmlReport", "koverVerify")
}
```

- Put the thresholds in `gradle.properties` (`coverage.minLine=80`) so a team ratchets them in one
  place. Raise them only after a run proves the new number, and leave about 1 point of headroom.
- When a module first adopts Kover far below target, start the bounds at the measured baseline, not at
  0. A bound of 0 never fails, so it hides regressions.
- `tasks.named("check") { dependsOn("koverVerify") }` makes `./gradlew check` enforce the thresholds.

## Tasks and report locations

| Task | Output |
|---|---|
| `koverXmlReport` | `<module>/build/reports/kover/report.xml`: what `kover_gaps.py` reads |
| `koverHtmlReport` | `<module>/build/reports/kover/html/index.html` |
| `koverVerify` | Fails the build when a `verify` rule is not met |
| `koverLog` | Prints coverage to the console |
| `koverBinaryReport` | Binary report, for tooling |
| `kover<Report><Variant>` (e.g. `koverXmlReportDebug`) | The same, for one Android build variant |

Each report task first runs the test tasks it depends on. A failing test fails the report task, and
then no XML is written. List what a module really has with `./gradlew :<module>:tasks --all | grep -i kover`.
Variant report file names differ from `report.xml`, so look in `build/reports/kover/` after the run.

## Report-only coverage in CI

A CI job that only *publishes* coverage can still want a report when one test is red. Gate it behind a
property, so normal builds stay strict:

```kotlin
tasks.withType<Test>().configureEach {
    if (project.hasProperty("coverageIgnoreTestFailures")) {
        ignoreFailures = true
    }
}
```

Run it as `./gradlew :shared:koverXmlReport -PcoverageIgnoreTestFailures`. The test failures still
appear in the JUnit XML. Never pass the property in a job that gates merges.

## Several modules

To get one merged number, apply Kover in the root project too, and add each module as a `kover`
dependency there (`dependencies { kover(project(":shared")) }`). The root `koverXmlReport` then covers
all of them. Run `kover_gaps.py` on the merged report, or on each module's own report to work one
module at a time.
