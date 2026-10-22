---
name: mobile-platform-parity
description: Use when a change touches only one platform of a Kotlin Multiplatform app — androidMain, iosMain, Swift or SwiftUI, an Android or iOS host app — or when Android and iOS behave differently - a bug fixed on one side only, different validation, error, empty or loading states, copy, permission prompts, background or offline behaviour, analytics events, deep links, date, number or time-zone formatting, accessibility ids, feature flags, or two expect/actual implementations that disagree.
license: Apache-2.0
compatibility: Kotlin Multiplatform project with Android and iOS targets, with shared UI (Compose Multiplatform) or native UI over shared logic. Reads both platforms' sources; builds for iOS need macOS with Xcode.
metadata:
  category: review
  platforms: android, ios
---

# Mobile platform parity

Find places where Android and iOS do different things for the same user action. A code review reads
one platform at a time, and a build proves only that each side compiles; neither notices that the
two sides disagree. This review holds both sides in context at once.

The principle: **shared code removes parity risk, and every platform-specific line reintroduces
it.** A rule fixed in `commonMain` cannot drift. A rule written twice will.

## When to use

- A change edits `androidMain`, `iosMain` (or `appleMain`, `nativeMain`), Swift, SwiftUI, or an
  Android or iOS host app, and not the other platform.
- A bug was reported on one platform: check whether the other has it, and whether the fix belongs
  in shared code.
- Before releasing a feature on both platforms, or when QA reports "it works differently on iOS".
- An `expect` declaration or its `actual`s changed.

## When not to use

- A change confined to `commonMain` with no platform-specific behaviour behind it — shared code
  cannot diverge by itself. (Still check `actual`s that the changed common code now calls
  differently.)
- General correctness review — use `kmp-code-review`.
- Security controls in depth — use `mobile-security-review`; this skill only flags a control present
  on one platform and missing on the other.

## Step 0 — Read the project first

Map how this project splits work between platforms before comparing anything:

1. **Architecture.** Shared Compose Multiplatform UI, native SwiftUI over shared view models, or
   separate native apps sharing only a data layer. Parity risk grows in that order.
2. **Source sets.** `commonMain`, `androidMain`, `iosMain`, `appleMain`, `nativeMain`, `jvmMain`,
   and where the iOS host app and any Swift packages live.
3. **Where each concern lives on each side:** strings (`composeResources`, `res/values`,
   `Localizable.strings` / `.xcstrings`), analytics wrapper, feature-flag client, permission
   handling, deep link configuration (intent filters and `assetlinks.json`; associated domains and
   `apple-app-site-association`), date and number formatting helpers.
4. **Documented divergences.** The project's rules files (`AGENTS.md`, `CLAUDE.md`,
   `CONTRIBUTING.md`, `.cursor/rules/*`, `.github/copilot-instructions.md`), ADRs, or a parity log.
   A divergence recorded there is not a finding.

Done when you can say, for the feature in question, which parts are shared and which are written
per platform.

## Where shared code removes risk — and where platform code brings it back

| Architecture | Parity comes free for | Risk remains in |
|---|---|---|
| Shared Compose UI + shared view models | Layout, copy, states, validation, analytics fired from view models | `expect`/`actual` code, insets and keyboard handling, back navigation, permission prompts, system pickers and share sheets, platform formatters |
| SwiftUI over shared view models | Business rules, state machines, validation and analytics that live in the view model | Swift re-implementing a rule, Swift-side formatting, copy duplicated in two string files, accessibility ids, analytics fired from views |
| Native apps over a shared data layer | Networking and persistence | Everything the user sees — treat every screen as two implementations |

## Workflow

### 1. Classify the changed files

```bash
git diff --name-only "$(git merge-base origin/main HEAD)" HEAD; git diff --name-only HEAD   # use the project's base branch
```

Bucket every file: **Android** (`androidMain`, `android*Main`, the Android app module, `res/`,
`AndroidManifest.xml`), **iOS** (`iosMain`, `ios*Main`, `appleMain`, `nativeMain`, `*.swift`,
`Info.plist`, `*.xcstrings`), **shared** (`commonMain`, `composeResources`). A change with files in
only one platform bucket is the case this skill exists for.

Done when each platform-specific change has a one-line description of the behaviour it adds or
alters.

### 2. Find the counterpart

For each platform-specific change, locate the code that does the same job on the other platform:

| Changed on one side | Counterpart on the other |
|---|---|
| An `actual` | Every other `actual` of the same `expect` — grep for `actual fun Name`, `actual class Name`, `actual object Name`, `actual val Name` |
| A Compose screen (Android-only UI) | The SwiftUI view for the same route — search by screen name, route, test identifiers or string keys |
| A Swift view or view model | The Compose screen and the shared view model it should be using |
| Android host (`Application`, `MainActivity`, manifest) | iOS host (`@main` App, `AppDelegate`, `SceneDelegate`, `Info.plist`, entitlements) |
| A string key | The same key in the other platform's string files |
| An analytics call | The same event name on the other side |
| A deep link route | The other platform's link configuration and router |

No counterpart is itself a result: either the feature is intentionally one-platform (document it)
or the other platform is missing it (a finding).

### 3. Compare along the dimensions

Read both sides in full, then walk the rows in
[references/parity-dimensions.md](references/parity-dimensions.md) that apply. For each row, write
down the behaviour on each side with `file:line` evidence. "Probably the same" is not evidence.

### 4. Ask whether the rule belongs in shared code

When both sides implement the same user-observable rule — a validation, a threshold, an eligibility
check, a formatting choice — the recommended fix is to move it into `commonMain` and have both
platforms call it, not to patch the second copy. Note it in the finding's `fix`.

### 5. Check for documented intent

A divergence is acceptable only when it is written down:

- forced by the OS (iOS cannot re-prompt for a denied permission; Android has a system back button),
  **or** a product decision, **and**
- recorded where the next reader will find it: a comment at *both* code sites naming the reason, an
  entry in the project's parity log or ADRs, or — for a fix landing on one platform first — a
  follow-up issue named in the pull request.

```kotlin
// Platform difference (intentional): iOS cannot show the system prompt again after a denial,
// so iOS opens Settings here. Android re-requests. Same outcome: an explanation, then a path to grant.
```

Undocumented divergence is a finding even when it is defensible.

### 6. Rate and try to disprove

Severity no lower than the row's floor. For every Critical and High: Is the difference forced by the
OS? Is the behaviour already supplied by shared code that one side calls indirectly? Is the feature
absent on the other platform by design? Is the counterpart in a file you have not read yet? Mark
survivors `CONFIRMED`; downgrade or drop the rest.

### 7. Report

Emit one JSON object per line, then the parity matrix and the findings, most severe first.

```json
{"file":"shared/src/iosMain/kotlin/com/example/app/profile/AvatarUploader.ios.kt","line":27,"severity":"High","tier":2,"lens":"parity/semanticActualDivergence","title":"iOS upload timeout is 60 s, Android 15 s","why":"the iOS actual relies on the URLSession default while the Android actual sets 15 s; a slow network shows an error on Android and a spinner for a minute on iOS","fix":"name UPLOAD_TIMEOUT_MS in commonMain and pass it to both actuals","rule":"Semantic actual divergence","counterpart":"shared/src/androidMain/kotlin/com/example/app/profile/AvatarUploader.android.kt:31","verdict":"CONFIRMED"}
```

Fields: `file`, `line`, `severity` (`Critical` · `High` · `Medium` · `Low`), `tier` (`1` project rule ·
`2` dimension row), `lens` (`parity/<lensName>`), `title`, `why`, `fix`, `rule`, `counterpart`
(`file:line` on the other platform, or `"none"` when it is missing), `verdict` (`CONFIRMED` ·
`PLAUSIBLE`; every Critical and High is `CONFIRMED`). Finish with
`reviewed: <n> files · <m> findings`.

Then the matrix, one row per dimension you compared:

| Dimension | Android | iOS | Same? | Evidence |
|---|---|---|---|---|
| Upload timeout | 15 s | 60 s (URLSession default) | No — F1 | `AvatarUploader.android.kt:31`, `AvatarUploader.ios.kt:27` |
| Denied-permission branch | Re-request with rationale | Opens Settings | Yes — documented, OS-forced | comments at both sites |

"No divergence found" is a valid result; the matrix shows what was compared.

### 8. Offer fixes

Ask which to fix. In order of preference: move the rule to `commonMain`; mirror the fix on the other
platform in the same change; or open a follow-up issue with the exact divergence, both file paths
and the expected behaviour. Never "fix" a documented, OS-forced difference.

## Quick reference

| Dimension | Typical divergence |
|---|---|
| `expect`/`actual` semantics | Timeout, error type, null vs empty, result thread, units (ms vs s) |
| Validation | Regex, limits, trimming, when it runs |
| Error / empty / loading | Message mapping, retry offered, blocking vs non-blocking |
| Copy | Missing keys, plurals, placeholders, languages |
| Permissions | Order, priming, denied and permanently-denied paths, precise vs approximate |
| Background and lifecycle | Restoration, background work timing, suspended timers |
| Offline | Queue vs fail, cache policy, connectivity semantics |
| Analytics | Event names, property keys and types, firing point, user id reset |
| Accessibility | Identifier and label coverage, text scaling, touch targets |
| Deep links | Paths, parameter validation, signed-out and cold-start handling |
| Formatting | Time zone, 12/24 h, separators, currency, DST arithmetic |
| Feature flags | Key, default on fetch failure, evaluation time |

## Verify

Report each check as `PASS`, `FAIL` or `NOT RUN — <reason>`. Never claim one that was not run.

```bash
# Both platforms still build and the shared tests pass on both targets
./gradlew :composeApp:assembleDebug
./gradlew :shared:allTests                         # includes iOS simulator tests on macOS
xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp \
  -destination 'platform=iOS Simulator,name=iPhone 16' build

t=$(mktemp -d)

# String keys present on one side only (adjust paths to the project's string files)
grep -ho 'name="[^"]*"' composeApp/src/androidMain/res/values/strings.xml | cut -d'"' -f2 | sort -u > "$t/keys-android"
grep -ho '^"[^"]*"' iosApp/iosApp/en.lproj/Localizable.strings | tr -d '"' | sort -u > "$t/keys-ios"
comm -3 "$t/keys-android" "$t/keys-ios"

# Analytics event names fired on one side only (replace track( with the project's analytics call)
grep -rhoE 'track\("[A-Za-z0-9_]+"' --include=*.kt . | sort -u > "$t/events-kotlin"
grep -rhoE 'track\("[A-Za-z0-9_]+"' --include=*.swift . | sort -u > "$t/events-swift"
comm -3 "$t/events-kotlin" "$t/events-swift"
```

When the project's strings are shared through Compose resources, or events are fired only from
shared view models, those two checks are `NOT RUN — shared by construction`; say so. For a behaviour
that cannot be read from source (timing, permissions), run the same scenario on an emulator and a
simulator and record both outcomes.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Comparing signatures, not behaviour | Two `actual`s that compile can still disagree on timeouts, errors and threads | Read both bodies; compare defaults the platform libraries supply |
| Patching the second copy of a rule | The copies drift again on the next change | Move the rule into `commonMain` |
| Flagging OS-forced differences | Noise; the team stops reading the report | Check the platform constraint, then require only documentation |
| Accepting an undocumented "intentional" difference | The next developer "fixes" it, or copies it somewhere it is wrong | Comment at both sites, or an entry in the parity log |
| Skipping review because the diff is one-platform | That is exactly when divergence is introduced | Always find and read the counterpart |
| Trusting string-file parity when copy is built in code | Hardcoded or concatenated strings bypass the key comparison | Grep the screens for literals too |
| Comparing in the simulator only | Permissions, background limits and time zones behave differently on devices | Run timing and permission scenarios on real devices when they matter |

## Related skills

- `kmp-code-review` — general review; its findings schema is the one used here.
- `mobile-security-review` — when the divergent behaviour is a security control.
- `kmp-expect-actual` — restructuring an `expect`/`actual` pair so behaviour is defined once.
- `compose-multiplatform-localization` — moving strings into shared resources.
- `compose-multiplatform-navigation` — shared routes and deep links.
- External: [android/skills](https://github.com/android/skills),
  [twostraws/SwiftUI-Agent-Skill](https://github.com/twostraws/SwiftUI-Agent-Skill).
