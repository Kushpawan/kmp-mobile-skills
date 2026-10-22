# Module health: output format

The skill's deliverable. Fill every section. Keep findings sorted Critical → High → Medium → Low.
Every finding carries evidence a reader can open: `path:line`, or a command with its decisive output
line.

````markdown
# Module health: <module path>

**Role:** <published library | umbrella framework | feature logic | feature UI | core | app>
**Targets:** <android, iosArm64, iosSimulatorArm64, ...>   **Host:** <macOS | Linux | Windows>
**Audited at:** <commit SHA or "working tree, uncommitted changes present">
**House rules applied:** <files read in Step 0, or "none found">

## Summary

<Two or three sentences: overall state, the single most important problem, and whether the module
is fit for its purpose (for example "not ready to publish: 2 Critical findings").>

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 0 |
| Medium | 0 |
| Low | 0 |

## Scorecard

| ID | Check | Result |
|---|---|---|
| C1 | Source sets and targets | OK / n findings / NOT CHECKED (reason) |
| C2 | commonMain purity | |
| C3 | expect/actual | |
| C4 | Boundaries and dependency direction | |
| C5 | Public API surface | |
| C6 | Tests | |
| C7 | Build configuration | |
| C8 | Documentation | |

## Findings

| ID | Severity | Check | Evidence | Impact | Fix | Effort |
|---|---|---|---|---|---|---|
| F1 | Critical | C3 | `src/commonMain/.../Clock.kt:3` expect; actual only in `src/iosArm64Main/...` | Simulator builds fail | Move the actual to `iosMain` | S |

Effort: S (under an hour), M (under a day), L (more).

## Checks run

| Command | Result |
|---|---|
| `./gradlew :<module>:compileCommonMainKotlinMetadata` | PASS / FAIL (first error line) / NOT RUN (reason) |
| `./gradlew :<module>:compileKotlinIosSimulatorArm64` | |
| `./gradlew :<module>:testAndroidHostTest` | |
| `./gradlew :<module>:iosSimulatorArm64Test` | |

## Not checked

<Anything skipped and why: no macOS host, module has no iOS targets, ABI tooling absent, and so on.
Findings that depend on a skipped check are marked "unverified" in the table.>

## Suggested order of work

1. <Critical fixes, smallest first>
2. <High fixes>
3. <Medium and Low as a batch, or deferred with a reason>

No files were changed during this audit.
````

## Example finding rows

| ID | Severity | Check | Evidence | Impact | Fix | Effort |
|---|---|---|---|---|---|---|
| F1 | Critical | C6 | `src/commonTest/.../NotesRepositoryTest.kt:4` imports `io.mockk.mockk` | `iosSimulatorArm64Test` cannot compile; no iOS test has ever run | Replace with a hand-written `FakeNotesApi` in `commonTest` | M |
| F2 | High | C1 | `src/androidUnitTest/` holds 6 test files; module applies `com.android.kotlin.multiplatform.library` | Those tests are ignored; Android coverage is overstated | Move to `src/androidHostTest/`, add `withHostTest {}` | S |
| F3 | High | C4 | `build.gradle.kts:31` `implementation(project(":feature:profile"))` | Notes cannot ship or change without profile | Navigation callback wired by the app, or a `:core` interface | M |
| F4 | Medium | C5 | `src/commonMain/.../NotesRepositoryImpl.kt:12` is `public` | Implementation detail becomes API; Swift sees it too | Make it `internal`; enable `explicitApi()` | S |
| F5 | Low | C8 | No `README.md` in the module | New contributors cannot find entry points | Add purpose, public entry points, how to depend on it | S |
