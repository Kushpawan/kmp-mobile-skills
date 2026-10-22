---
name: kmp-module-health
description: Use when asked to audit, health-check or assess a Kotlin Multiplatform module or library before a release, refactor or handover - platform imports leaking into commonMain, missing or misplaced actuals, dependency cycles or feature-to-feature dependencies, a public API that is too wide, explicit API mode, binary-compatibility (ABI) validation, missing or iOS-only-broken tests, hardcoded versions, or "is this module in good shape?".
license: Apache-2.0
compatibility: Kotlin Multiplatform Gradle project. Read-only audit using grep, find and Gradle compile/test tasks; iOS checks need macOS with Xcode. Python 3 for the optional dependency-graph snippet.
metadata:
  category: review
  platforms: android, ios
---

# KMP module health audit

A read-only audit that measures one module (or a set of them) against eight checks, ranks every
finding by what it breaks, and backs each one with a file and line. The audit changes nothing. Fixes
are offered afterwards and applied only when the user asks.

## When to use

- Before publishing a shared library, or before a large refactor.
- Taking over a module and wanting to know its real state.
- After a run of quick fixes that may have blurred module boundaries.
- A module "works on Android" but nobody has built iOS recently.

## When not to use

- Reviewing one change or pull request line by line: use a code-review skill.
- Fixing a specific build failure: `kmp-build-failure-triage` in this repo.
- Creating a module: `kmp-feature-module`. Adding dependencies: `kmp-gradle-version-catalog`.
- Writing the missing tests the audit finds: `kmp-testing-patterns` in this repo.

## Step 0 — Scope it and read the project's rules

1. **Confirm scope.** Which module paths, and why (release, refactor, onboarding). If the user named
   none, list modules from `settings.gradle.kts` and ask.
2. **Read the house rules first.** `README.md`, `CONTRIBUTING.md`, `docs/` architecture notes, ADRs,
   and lint configs (`detekt.yml`, `.editorconfig`, Konsist tests). **The project's own rules win**:
   do not flag what the project deliberately allows, and do flag violations of rules it states.
3. **Classify each module.** The role decides which checks weigh most:

| Role | Weigh most |
|---|---|
| Published library | C5 public API and ABI, C7 build, C8 docs |
| Umbrella iOS framework module | C4 `api`/`export` parity, C5 Swift-facing API, C7 framework config |
| Feature logic module consumed by SwiftUI | C2 no Compose, C4 boundaries, C6 tests |
| Feature UI module | C4 boundaries, C6 state/ViewModel tests |
| Core/infrastructure module | C4 dependency direction, C3 expect/actual, C6 tests |
| App module | C7 build config; most other checks apply lightly |

4. **Know the host.** iOS compilation and iOS tests need macOS. On another host those checks are
   `NOT RUN`, and findings that depend on them are marked unverified.

## Workflow

1. **Inventory.** Record targets, plugins, source sets with file counts, and direct dependencies.
   Commands in [references/checks.md](references/checks.md#c0-inventory). Done when you can state the
   module's role, targets and dependencies in three lines.
2. **Run checks C1–C8** below, using the commands in [references/checks.md](references/checks.md).
   Grep finds candidates; the compiler and test tasks are the ground truth. Every finding needs
   evidence (`path:line` or command output). Done when each check is `OK`, has findings, or is
   `NOT CHECKED` with a reason.
3. **Run the Verify commands.** They only write to `build/` directories. Done when each has
   `PASS`, `FAIL` or `NOT RUN`.
4. **Rank** every finding with the severity rubric. Done when no finding lacks a severity.
5. **Write the report** with [references/output-format.md](references/output-format.md),
   in chat or to a file only if the user asks for one.
6. **Offer fixes**, grouped by severity, with effort estimates. Apply none without a yes.

## The eight checks

| ID | Check | Typical findings |
|---|---|---|
| C1 | Source sets and targets | Tests in directories the Android KMP plugin ignores (`src/androidUnitTest`, `src/test`); per-architecture source sets duplicating `iosMain`; source sets for targets that are not declared |
| C2 | `commonMain` purity | `android.*`, `java.*`, `platform.*` imports; `println`/`Log`/`NSLog` instead of the project's logger (Kermit, Napier); Compose in a module SwiftUI consumes |
| C3 | expect/actual | An `expect` without an `actual` on the path of a declared target; actuals only in `iosArm64Main`; large `expect class` APIs that should be interfaces |
| C4 | Boundaries and dependency direction | Cycles; feature → feature dependencies; `:core` depending on a feature; `api` where `implementation` is enough; umbrella `api` list differs from its `export` list |
| C5 | Public API surface | No explicit API mode on a library; public `Impl`/`Dto`/`Entity` types; public `MutableStateFlow`; no ABI check on a published library; Swift-facing API without `@Throws` or with interface generics |
| C6 | Tests | No `commonTest`; ViewModels, use cases, repositories or mappers without tests; placeholder tests; JVM-only mocking in `commonTest`; Android host tests not enabled; iOS tests never run |
| C7 | Build configuration | Hardcoded versions; plugin set differs from siblings or convention plugin; duplicate `namespace`; literal SDK levels; framework/linker/compiler flags without an explanation |
| C8 | Documentation | No README stating purpose and entry points; public library API without KDoc; no changelog for a published artifact; module missing from the architecture doc |

Do not flag every `androidx.*` import in `commonMain`: many AndroidX artifacts are multiplatform
(lifecycle, Room, DataStore, collection, annotation, paging, and the JetBrains-published navigation
and lifecycle forks). If it compiles for iOS, it is not a purity finding.

## Severity rubric

| Severity | Meaning | Examples |
|---|---|---|
| **Critical** | Breaks a declared target now, or ships wrong behaviour | Missing `actual` for a declared target; platform import in `commonMain`; dependency cycle; Swift-used module missing from the umbrella `export`; `commonTest` that cannot compile for iOS |
| **High** | Hides failures or will block the next release | Host tests disabled so Android unit tests never run; tests in ignored directories; feature → feature dependency; published library with no ABI check; hardcoded versions; Compose in a SwiftUI-facing logic module; unexplained `-lsqlite3` next to a bundled SQLite driver |
| **Medium** | Raises the cost of change | Public API wider than its consumers need; `expect class` where an interface fits; `api` leaks; ViewModel or use case without tests; duplicated per-architecture iOS code |
| **Low** | Hygiene | Missing README or KDoc; inconsistent file suffixes; stale comments |

When unsure between two levels, pick the higher and say why in the finding.

## Quick reference

| Question | Fastest evidence |
|---|---|
| Does common code compile without platform leaks? | `compileCommonMainKotlinMetadata` |
| Does every declared iOS target have its actuals? | `compileKotlinIosSimulatorArm64` and `compileKotlinIosArm64` |
| Do tests run on both platforms? | `testAndroidHostTest` (or `testDebugUnitTest`) and `iosSimulatorArm64Test` |
| Does Swift see the module? | `swift_name("…")` in the linked framework header |
| Is the public ABI tracked? | An `api/` dump directory plus `checkKotlinAbi` or `apiCheck` in CI |
| Any cycles or feature → feature edges? | The dependency-graph snippet in the checks reference |

## Verify

Report each as `PASS`, `FAIL` or `NOT RUN` (with the reason). Never report a check that did not
run as passed. Replace `:feature:notes:logic` with the module under audit; list real task names with
`./gradlew :feature:notes:logic:tasks --all | grep -iE 'compile|test|abi|api'`.

```bash
./gradlew :feature:notes:logic:compileCommonMainKotlinMetadata
./gradlew :feature:notes:logic:compileAndroidMain              # legacy plugin: compileDebugKotlinAndroid
./gradlew :feature:notes:logic:compileKotlinIosSimulatorArm64  # macOS only
./gradlew :feature:notes:logic:compileKotlinIosArm64           # macOS only
./gradlew :feature:notes:logic:testAndroidHostTest             # legacy plugin: testDebugUnitTest
./gradlew :feature:notes:logic:iosSimulatorArm64Test           # macOS only
./gradlew :feature:notes:logic:checkKotlinAbi                  # only if ABI validation is configured
```

A failing Verify command is itself a Critical or High finding; quote the first decisive error line.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Editing files during the audit | The report no longer describes the code that was audited; the user did not ask for changes | Report first; offer fixes; apply on a yes |
| Grep-only verdicts | Grep misses intermediate source sets and flags valid KMP imports | Confirm with the compile and test tasks |
| Flagging all `androidx.*` imports in common code | Many AndroidX libraries are multiplatform | Flag only what fails to compile for iOS |
| Reporting a `NOT RUN` check as fine | iOS problems hide until CI or release | Mark `NOT RUN` and mark dependent findings unverified |
| Counting test files instead of checking what they cover | Ten mapper tests do not cover an untested ViewModel | Map logic classes to their tests |
| Findings without `path:line` | Nobody can act on them | Evidence on every finding |
| Ignoring the project's documented rules | Recommends the opposite of a deliberate decision | Read and apply house rules in Step 0 |
| Treating an `actual` in `iosArm64Main` as complete | Simulator and Intel targets still lack it | Check every declared target, or move it to `iosMain` |
| One undifferentiated list | The Critical item gets lost among style nits | Severity-ranked report |

## Related skills

- `kmp-expect-actual`, `kmp-feature-module`, `kmp-gradle-version-catalog` — the fixes for most findings.
- `kmp-testing-patterns`, `kmp-build-failure-triage`, `kmp-swiftui-interop` in this repo.
- [chrisbanes/skills `release-kotlin-library`](https://github.com/chrisbanes/skills/tree/main/skills/release-kotlin-library)
  and [`kotlin-api-design`](https://github.com/chrisbanes/skills/tree/main/skills/kotlin-api-design) — library releases and API shape.
- [Kotlin binary compatibility validation](https://kotlinlang.org/docs/gradle-binary-compatibility-validation.html)
  and [Kotlin library API guidelines](https://kotlinlang.org/docs/api-guidelines-introduction.html).
