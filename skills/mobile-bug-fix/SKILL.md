---
name: mobile-bug-fix
description: Use when asked to fix a bug, defect, regression or issue in a Kotlin Multiplatform (Android + iOS) app — "fix this bug", "this broke after the update", wrong data on screen, a button that does nothing, a bug report, issue link or QA ticket, "works on Android but not iOS", or unexpected behaviour in commonMain, androidMain, iosMain, Swift/SwiftUI or the Android host app.
license: Apache-2.0
compatibility: Kotlin Multiplatform Gradle project with Android and iOS targets. iOS reproduction and tests need macOS with Xcode.
metadata:
  category: debug
  platforms: android, ios
---

# Mobile bug fix

Find the root cause before changing code, prove it with a test that fails for the reason the user
saw, make the smallest fix at the layer that owns the cause, and verify on **both** platforms. A
shared codebase means a fix in `commonMain` ships to Android and iOS at once — so does a bad fix.

## When to use

- A bug report, issue link, QA ticket or a plain "fix this" for a KMP app.
- Wrong data, missing data, wrong state after an action, a control that does nothing, a regression
  after an update.
- The user does not yet know whether the cause is shared code, platform code or the Swift layer.

## When not to use

Route to the specialist skill when the symptom matches. Come back here for steps 5–9 (test, fix,
verify, summary) if the specialist skill does not cover them.

| Symptom | Use |
|---|---|
| Crash, ANR, `FATAL EXCEPTION`, `.ips` / tombstone, `SIGABRT`, `EXC_BAD_ACCESS`, `kfun:` frames | `kmp-crash-triage` |
| A test passes and fails without code changes, or fails only on CI / only on iOS | `kmp-flaky-test-triage` |
| Slow, janky, long loader, slow start, memory growth, battery drain | `mobile-performance-fix` |
| Compile, link, Gradle sync, KSP, XCFramework or Xcode build error | `kmp-build-failure-triage` |
| Same code behaves differently on Android and iOS | `mobile-platform-parity` |
| Reviewing a change rather than fixing a reported bug | `kmp-code-review` |

## Step 0 — Read the project first

Before reproducing anything, learn how this project is built and tested. Write down what you find;
later steps depend on it.

1. **Modules and source sets.** Read `settings.gradle.kts` and each module's `build.gradle.kts`.
   Note which modules are KMP, which targets they declare (`androidTarget()` or the
   `com.android.kotlin.multiplatform.library` plugin, `iosArm64`, `iosSimulatorArm64`, `iosX64`,
   `jvm`), and where the iOS framework is produced (`binaries.framework { baseName = … }`).
2. **iOS host.** Find the Xcode project (`iosApp/*.xcodeproj` or a workspace) and how it consumes
   the framework: Gradle build phase (`embedAndSignAppleFrameworkForXcode`), SPM, or CocoaPods. Note
   whether the Swift side is SwiftUI over shared ViewModels, Compose Multiplatform via
   `ComposeUIViewController`, or both, and whether SKIE or KMP-NativeCoroutines is applied.
3. **Architecture.** MVVM or MVI, the ViewModel base class, use cases or not, repository and data
   source shape, how errors are modelled (a `Result`-like sealed type, exceptions, `Either`).
4. **Libraries.** Read `gradle/libs.versions.toml`: DI (Koin, Hilt, kotlin-inject, manual),
   networking (Ktor, Ktorfit), persistence (Room KMP, SQLDelight, DataStore), logging (Kermit,
   Napier), test libraries (kotlin.test, Turbine, kotlinx-coroutines-test, Kotest, MockK).
5. **Test conventions.** Find existing tests: naming (`should_x_when_y` or other), fakes vs mocks,
   dispatcher injection, where shared tests live (`commonTest`) and what the test task names are:
   `./gradlew :shared:tasks --group verification`.
6. **Logger.** Use the project's logger for any diagnostic logging, never `println` / `Log.d` /
   `NSLog` added ad hoc.

Follow what exists. Do not introduce a second library for a job the project already does.

## Workflow

### 1. Capture the report

Fill this in from the ticket, the user and the logs. Ask for anything critical that you cannot
infer — usually steps, platform and build.

```text
Summary      one sentence: what is wrong
Steps        numbered, from a cold start
Expected     what should happen
Actual       what happens (exact text, screenshot, log line)
Platform     Android / iOS / both — OS version, device or simulator
Build        app version + build number, debug / release, flavour (e.g. staging)
State        signed in? which account type? online / offline? fresh install or upgrade?
Since        first seen in version …, or "always"
Evidence     logs, crash ids, screen recordings, server request ids
```

Done when you can state the bug in one sentence and list steps someone else could follow.

### 2. Reproduce — reported platform first, then the other

- Reproduce on the platform in the report, with the **same build type**. Release builds differ:
  R8 shrinking and obfuscation, optimised Kotlin/Native code, logging disabled, different base URLs.
- Then try the **other** platform. Record a matrix:

  | | Android | iOS |
  |---|---|---|
  | Reproduces? | yes / no / not tried (why) | yes / no / not tried (why) |

- Cannot reproduce? Compare state, not code first: account, data on the server, locale and time
  zone, OS version, upgrade vs fresh install, network conditions, feature flags. Add temporary
  logging through the project's logger at the boundaries (ViewModel action in, repository result
  out) rather than guessing.
- For a regression with a known good version, `git bisect` between the two tags is often faster
  than reading code.

Done when the bug reproduces reliably, or you have a written list of what you tried and the user
agrees how to proceed.

### 3. Locate the layer and source set

The matrix from step 2 narrows the search:

- **Both platforms fail** → most likely `commonMain`: a mapper, repository, use case, ViewModel
  reducer, or the API response itself.
- **Only one platform fails** → that platform's `actual`, the Android host app (lifecycle, process
  death, permissions), the Swift layer (state observation, main-thread hops, casting), or a common
  API that behaves differently per platform (→ `mobile-platform-parity`).

Trace the data path from where the symptom shows to where the wrong value is produced:

```text
Composable / SwiftUI view → ViewModel (state, actions) → use case → repository
  → remote data source (HTTP) / local data source (DB, preferences) → platform actual
```

At each hop, check the value with a test, a breakpoint or a log line. The first hop where the value
is wrong is where the cause lives. Done when you can name the file and line that **produces** the
wrong behaviour — not the line that displays it.

### 4. Root cause before fix

Write the cause as one paragraph: *"X happens because Y, when Z."* Then attack it:

- Does it explain **every** symptom in the report, including why the other platform is or is not
  affected and why it started in that version?
- Does it predict something you have not observed yet? Check that prediction.
- Re-read the actual code path and its callers; do not rely on what a function's name suggests.

If the hypothesis survives, continue. If not, go back to step 3.

Reject symptom patches. Each of these hides the bug and usually creates a second one:

| Patch | Why it is wrong |
|---|---|
| `?: return` / `!!` → `?.` to stop a crash | the missing value is the bug; now it fails silently |
| `try { … } catch (e: Exception) {}` | swallows the real error, and in coroutines also `CancellationException` |
| `delay(500)` before a read | hides a race; fails on slower devices and CI |
| Filtering bad items in the UI | the repository still returns bad data to every other caller |
| `if (platform == iOS)` around shared logic | two behaviours to maintain; the shared bug remains |

### 5. Write a failing test first

Pick the lowest layer that shows the bug:

| Cause lives in | Test goes in | Runs with |
|---|---|---|
| `commonMain` logic | `commonTest` — runs on every target | `allTests`, or the per-target task |
| `androidMain` actual | `androidUnitTest` / `androidHostTest`, or instrumented test if it needs a device | `testDebugUnitTest` / `testAndroidHostTest` |
| `iosMain` actual | `iosTest` | `iosSimulatorArm64Test` |
| Swift / SwiftUI code | the Xcode test target (XCTest / Swift Testing) | `xcodebuild test` |
| Pure rendering | a UI test if the project has them; otherwise document the manual check | — |

Use the project's fakes and naming. A test in the example domain, for a mapper that drops a note's
title when the API sends `null` for an optional field:

```kotlin
class NoteMapperTest {
    @Test
    fun should_keepTitle_when_bodyIsNull() {
        val dto = NoteDto(id = "n1", title = "Groceries", body = null)

        val note = dto.toDomain()

        assertEquals("Groceries", note.title)   // fails before the fix: title was ""
        assertEquals("", note.body)
    }
}
```

Run it and confirm it **fails for the reason in the report** (assertion message matches the wrong
value), not because of a compile error or an unrelated exception. A test that has never failed has
not proven anything.

### 6. Make the minimal fix

- Change the layer that owns the cause; keep the diff small; no drive-by refactors or renames.
- Write it in the project's idiom (its error type, DI, logger, naming).
- Find every caller of anything whose behaviour you change (`grep -rn` for the symbol in Kotlin and
  Swift). A changed constructor also needs its DI registration updated.
- If the right fix changes a public API of a published library, a database schema, or the
  architecture, stop and explain the options to the user before doing it.

### 7. Verify on both platforms

Run the new test (it must pass now), then the module's full suite on Android **and** iOS, then build
both apps, then repeat the original reproduction steps on both platforms. Commands are in
[Verify](#verify). If the changed module is a library consumed by other projects, rebuild at least
one consumer against the local copy.

### 8. Guard against regression

- The test from step 5 stays in the suite.
- Add one test per extra edge case you discovered (empty list, `null`, offline, second call).
- If the same mistake pattern can exist elsewhere, search for it and **list** the other sites in the
  summary. Fix them only if the user agrees — they are separate changes.

### 9. Write the summary for the PR

```markdown
**Bug** <one sentence, with the ticket link>
**Cause** <the root-cause paragraph from step 4, with file:line>
**Fix** <what changed and why at this layer>
**Evidence**
- Failing test before / passing after: `NoteMapperTest.should_keepTitle_when_bodyIsNull`
- Android unit tests: PASS · iOS simulator tests: PASS · Android build: PASS · iOS build: NOT RUN (no macOS)
- Manual repro on Pixel 8 / Android 15: fixed · iPhone 16 simulator / iOS 18: fixed
**Risk** <who else calls the changed code; platforms affected; what was not verified>
**Follow-ups** <similar sites found in step 8, not changed here>
```

Do not commit, push or open the PR unless the user asked you to.

## Quick reference

| Clue | Look first at |
|---|---|
| Wrong on both platforms | `commonMain` mapper, repository, reducer; the API response |
| Wrong only on iOS | `iosMain` actual; Swift observation of state (missed updates, wrong thread); `as!` casts on bridged generics; `KotlinInt`-style boxed numbers; enum / sealed bridging |
| Wrong only on Android | `androidMain` actual; lifecycle (rotation, process death, back stack); permissions |
| Only in release builds | R8 keep rules (serialization, reflection), obfuscated names in logs, different flavour config |
| Only after upgrade, not fresh install | database migration, stored preferences, cached data format |
| Only for some users or locales | time zone and locale formatting, server data shape, account type |
| Intermittent | a race: missing `await`, shared mutable state, ordering between two flows |
| Only offline / poor network | retry and timeout policy, cached vs remote source precedence |

## Verify

Run what applies and report each check as **PASS**, **FAIL** or **NOT RUN (reason)**. Never report a
check as passed that you did not run. Replace module and task names with the ones from Step 0.

```bash
./gradlew :shared:testDebugUnitTest --tests 'com.example.app.notes.NoteMapperTest'   # the new test (Android host)
./gradlew :shared:allTests                          # every target's tests for the module
./gradlew :shared:testAndroidHostTest               # if the module uses the KMP Android library plugin
./gradlew :shared:iosSimulatorArm64Test             # iOS simulator tests (macOS only)
./gradlew :composeApp:assembleDebug                 # Android app builds
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64   # iOS framework links (macOS only)
xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp \
  -destination 'platform=iOS Simulator,name=<an installed simulator>' build   # iOS app builds
```

List installed simulators with `xcrun simctl list devices available`. Manual reproduction on each
platform is its own check: report it as PASS / FAIL / NOT RUN like the commands.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Fixing where the symptom shows | Other screens and the other platform still get bad data | Trace to the hop that produces the wrong value (step 3) |
| Testing only the reported platform | A `commonMain` fix can break the other platform | Run both platforms' tests and builds every time |
| Reproducing on a debug build when the report is from release | R8 and optimisation bugs do not appear in debug | Match the build type of the report |
| Writing the test after the fix | You never see it fail, so it may not test the bug | Test first, watch it fail for the right reason |
| Catching `Exception` in a coroutine | Also catches `CancellationException` and breaks cancellation | Catch specific types, or rethrow `CancellationException` |
| Changing a constructor without its DI binding | Runtime crash when the graph resolves | Update the module definition and run the app |
| Widening the fix into a refactor | Larger blast radius, harder review, hidden regressions | Minimal fix now; list refactors as follow-ups |
| Claiming iOS is fine without running it | Kotlin/Native and Swift bridging differ from the JVM | Run `iosSimulatorArm64Test` and build the app, or report NOT RUN |

## Related skills

- `kmp-crash-triage` — crashes, ANRs, symbolication, Kotlin/Native frames.
- `kmp-flaky-test-triage` — tests that fail intermittently.
- `mobile-performance-fix` — slowness, jank, long loaders, memory growth.
- `kmp-build-failure-triage` — compile, link and Gradle errors.
- `mobile-platform-parity` — the same code behaving differently on Android and iOS.
- `kmp-code-review` — review the fix before raising the PR.
- [android/skills](https://github.com/android/skills) — `testing/testing-setup` for Android test infrastructure.
- [CharlesWiltgen/Axiom](https://github.com/CharlesWiltgen/Axiom) — iOS-side test-failure and crash analysis.
- [Dimillian/Skills](https://github.com/Dimillian/Skills) — `ios-debugger-agent` (drives the iOS
  simulator through XcodeBuildMCP while reproducing) and `bug-hunt-swarm` (parallel read-only
  root-cause investigation).
