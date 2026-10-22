# KMP Mobile Skills

[![CI](https://github.com/Kushpawan/kmp-mobile-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/Kushpawan/kmp-mobile-skills/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Agent Skills](https://img.shields.io/badge/format-Agent%20Skills-8A2BE2)](https://agentskills.io/specification)

Agent skills for building **Kotlin Multiplatform** apps on **Android and iOS**, and for finding and
fixing the bugs in them.

Each skill is a folder with a `SKILL.md` that teaches your AI coding agent one job: scaffold a feature
module, wire a Ktor endpoint, expose shared state to SwiftUI, triage an iOS crash with Kotlin/Native
frames, stop a flaky test, review a change for Android/iOS divergence. Skills load only when the task
needs them, so installing all of them costs almost nothing until one is used.

They follow the open [Agent Skills](https://agentskills.io/specification) format, so the same files work
in **Claude Code, OpenAI Codex, Cursor, Gemini CLI, GitHub Copilot, VS Code, Windsurf, JetBrains Junie
and Android Studio**.

## Quick start

Any agent, one command ([skills CLI](https://skills.sh)):

```bash
npx skills add Kushpawan/kmp-mobile-skills
```

Claude Code, as a plugin (adds the two reviewer agents as well):

```text
/plugin marketplace add Kushpawan/kmp-mobile-skills
/plugin install kmp-mobile-skills@kmp-mobile-skills
```

Per-agent instructions, team setup, updating and uninstalling: **[INSTALL.md](INSTALL.md)**.

Then just describe the task in your own words, inside your KMP project:

> "Add a profile feature module with a screen that loads the user from `/v1/me`."
>
> "The iOS app crashes on launch since we bumped Room. Here's the .ips file."
>
> "`OrdersViewModelTest` fails on CI about one run in five. Fix it properly."
>
> "Review my branch before I open the PR, especially anything that behaves differently on iOS."

In Claude Code you can also call a skill directly, e.g. `/kmp-mobile-skills:kmp-crash-triage`.

## Skills

<!-- catalog:start -->

### Build: project and modules

| Skill | Platforms | Use it when |
|---|---|---|
| [`kmp-expect-actual`](skills/kmp-expect-actual/SKILL.md) | android + ios | Kotlin Multiplatform shared code needs a platform API or platform-specific behaviour - expect/actual declarations, a missing or "no corresponding actual declaration"… |
| [`kmp-feature-module`](skills/kmp-feature-module/SKILL.md) | android + ios | adding a new feature or library module to a Kotlin Multiplatform project - "create a module", "modularize this feature", a :feature module, settings.gradle.kts include… |
| [`kmp-gradle-version-catalog`](skills/kmp-gradle-version-catalog/SKILL.md) | android + ios | adding, upgrading or auditing dependencies and Gradle plugins in a Kotlin Multiplatform project - libs.versions.toml, [versions] [libraries] [plugins] [bundles], "Could… |

### UI

| Skill | Platforms | Use it when |
|---|---|---|
| [`compose-design-system-component`](skills/compose-design-system-component/SKILL.md) | android + ios | creating or changing a reusable Compose Multiplatform design-system component — button, text field, chip, card, badge, avatar, dialog — or theme tokens: variant and size… |
| [`compose-multiplatform-localization`](skills/compose-multiplatform-localization/SKILL.md) | android + ios | localising a Compose Multiplatform app — composeResources strings.xml, values-fr / values-b+zh+Hans folders, plurals, string arrays, stringResource… |
| [`compose-multiplatform-navigation`](skills/compose-multiplatform-navigation/SKILL.md) | android + ios | building or debugging navigation in Compose Multiplatform commonMain — type-safe @Serializable routes, NavHost, nested graphs, splash/login gate, session expiry, bottom… |
| [`compose-multiplatform-screen`](skills/compose-multiplatform-screen/SKILL.md) | android + ios | adding or extending a Compose Multiplatform screen in commonMain — a new screen, ViewModel, UiState, actions/intents, one-shot side effects (navigate, snackbar), MVI or… |
| [`figma-to-mobile-ui`](skills/figma-to-mobile-ui/SKILL.md) | android + ios | implementing a Figma frame, screen or component as Compose Multiplatform or SwiftUI code in a Kotlin Multiplatform app — a figma.com/design link, "build this from… |

### Data

| Skill | Platforms | Use it when |
|---|---|---|
| [`kmp-api-endpoint`](skills/kmp-api-endpoint/SKILL.md) | android + ios | adding, wiring or fixing one REST endpoint in a Kotlin Multiplatform shared module — "add a GET/POST/PUT/DELETE call", "integrate this API", "call /orders from shared… |
| [`kmp-data-layer`](skills/kmp-data-layer/SKILL.md) | android + ios | designing, adding or refactoring the data layer of a Kotlin Multiplatform app in commonMain — Ktor HttpClient setup, DTOs and kotlinx.serialization, repositories and… |
| [`kmp-koin-di`](skills/kmp-koin-di/SKILL.md) | android + ios | setting up, extending or debugging Koin dependency injection in a Kotlin Multiplatform app — modules in commonMain, platform modules, startKoin in Application, initKoin… |
| [`kmp-room-database`](skills/kmp-room-database/SKILL.md) | android + ios | adding, configuring or debugging Room in a Kotlin Multiplatform project — @Database, @Dao, @Entity in commonMain, RoomDatabaseConstructor, BundledSQLiteDriver, KSP per… |
| [`kmp-secure-storage`](skills/kmp-secure-storage/SKILL.md) | android + ios | storing access tokens, refresh tokens, API keys or other secrets from Kotlin Multiplatform shared code — Android Keystore, a replacement for deprecated… |

### iOS interop

| Skill | Platforms | Use it when |
|---|---|---|
| [`kmp-swiftui-interop`](skills/kmp-swiftui-interop/SKILL.md) | ios | SwiftUI or Swift code consumes Kotlin Multiplatform shared logic — observing a Kotlin StateFlow or Flow from Swift, calling suspend functions with async/await, switching… |
| [`kmp-xcframework-distribution`](skills/kmp-xcframework-distribution/SKILL.md) | ios | shipping a Kotlin Multiplatform module to an iOS app — XCFramework, assembleXCFramework, embedAndSignAppleFrameworkForXcode, Swift Package Manager binaryTarget… |

### Testing

| Skill | Platforms | Use it when |
|---|---|---|
| [`kmp-build-check`](skills/kmp-build-check/SKILL.md) | android + ios | you need to know whether a Kotlin Multiplatform change still builds and passes tests on both Android and iOS - "did I break iOS?", before pushing or opening a PR, after… |
| [`kmp-test-coverage-backfill`](skills/kmp-test-coverage-backfill/SKILL.md) | android + ios | Kotlin Multiplatform unit-test coverage must go up - a Kover report (koverXmlReport, report.xml) below target, koverVerify failing the build, "backfill tests", "get this… |
| [`kmp-testing-patterns`](skills/kmp-testing-patterns/SKILL.md) | android + ios | writing or fixing unit tests in a Kotlin Multiplatform project - commonTest, kotlin.test, runTest, StandardTestDispatcher, Dispatchers.setMain, Turbine, testing a… |
| [`mobile-accessibility-test-ids`](skills/mobile-accessibility-test-ids/SKILL.md) | android + ios | adding or fixing stable UI-test locators and accessibility labels in a Kotlin Multiplatform or native mobile app - Compose testTag, testTagsAsResourceId, SwiftUI… |

### Debug and fix

| Skill | Platforms | Use it when |
|---|---|---|
| [`kmp-build-failure-triage`](skills/kmp-build-failure-triage/SKILL.md) | android + ios | a Kotlin Multiplatform build fails on Android or iOS — Gradle, KSP, Kotlin/Native link or Xcode errors such as "Undefined symbols for architecture arm64", "framework not… |
| [`kmp-crash-triage`](skills/kmp-crash-triage/SKILL.md) | android + ios | a Kotlin Multiplatform app crashes, hangs or is killed on Android or iOS — FATAL EXCEPTION, ANR, SIGABRT, SIGSEGV, EXC_BAD_ACCESS, EXC_BREAKPOINT, "Uncaught Kotlin… |
| [`kmp-flaky-test-triage`](skills/kmp-flaky-test-triage/SKILL.md) | android + ios | a Kotlin Multiplatform test is flaky — passes and fails without code changes, fails only on CI, only on iOS or Kotlin/Native, only with the whole suite or in another… |
| [`mobile-bug-fix`](skills/mobile-bug-fix/SKILL.md) | android + ios | asked to fix a bug, defect, regression or issue in a Kotlin Multiplatform (Android + iOS) app — "fix this bug", "this broke after the update", wrong data on screen, a… |

### Performance

| Skill | Platforms | Use it when |
|---|---|---|
| [`mobile-performance-fix`](skills/mobile-performance-fix/SKILL.md) | android + ios | a Kotlin Multiplatform (Android + iOS) app is slow, laggy or janky, drops frames while scrolling, starts slowly, keeps a loader spinning after a tap, freezes (ANR, iOS… |

### Review

| Skill | Platforms | Use it when |
|---|---|---|
| [`kmp-code-review`](skills/kmp-code-review/SKILL.md) | android + ios | asked to review local Kotlin Multiplatform, Kotlin, Compose or Swift changes before opening a pull request — "review my changes", "review this branch", "pre-PR review"… |
| [`kmp-module-health`](skills/kmp-module-health/SKILL.md) | android + ios | asked to audit, health-check or assess a Kotlin Multiplatform module or library before a release, refactor or handover - platform imports leaking into commonMain… |
| [`mobile-platform-parity`](skills/mobile-platform-parity/SKILL.md) | android + ios | a change touches only one platform of a Kotlin Multiplatform app — androidMain, iosMain, Swift or SwiftUI, an Android or iOS host app — or when Android and iOS behave… |
| [`mobile-security-review`](skills/mobile-security-review/SKILL.md) | android + ios | reviewing a Kotlin Multiplatform, Android or iOS app or change for security — API keys or secrets in source, BuildConfig or Info.plist, tokens or PII in logs, cleartext… |

### Plan and implement

| Skill | Platforms | Use it when |
|---|---|---|
| [`mobile-feature-implement`](skills/mobile-feature-implement/SKILL.md) | android + ios | an approved feature plan for a Kotlin Multiplatform (Android + iOS) app must be executed - "implement the plan", "build docs/plans/notes-search.md", "start phase 1"… |
| [`mobile-feature-plan`](skills/mobile-feature-plan/SKILL.md) | android + ios | a Kotlin Multiplatform (Android + iOS) feature request, ticket, user story or Figma link needs a written plan before code is written - "plan this feature", "write a… |

### Release and CI

| Skill | Platforms | Use it when |
|---|---|---|
| [`kmp-ci-github-actions`](skills/kmp-ci-github-actions/SKILL.md) | android + ios | setting up, fixing or speeding up GitHub Actions CI for a Kotlin Multiplatform (Android + iOS) project - .github/workflows YAML, "add CI", macos-latest or macos-15-intel… |
| [`mobile-release`](skills/mobile-release/SKILL.md) | android + ios | versioning or shipping a Kotlin Multiplatform app or shared library to Google Play and the App Store - "cut a release", "bump the version", versionCode, versionName… |

### Migration

| Skill | Platforms | Use it when |
|---|---|---|
| [`android-to-kmp-migration`](skills/android-to-kmp-migration/SKILL.md) | android + ios | an existing Android app (Kotlin, Jetpack, Views or Compose) should share code with iOS through Kotlin Multiplatform - "migrate to KMP", "add iOS to our Android app"… |

### Tooling

| Skill | Platforms | Use it when |
|---|---|---|
| [`kmp-dev-machine-cleanup`](skills/kmp-dev-machine-cleanup/SKILL.md) | android + ios | a macOS machine used for Kotlin Multiplatform, Android or iOS development is slow, swapping, or out of disk - "Mac is slow", "free RAM", "free disk space", "clean… |

_34 skills. Generated by `scripts/sync_manifests.py`; do not edit by hand._

<!-- catalog:end -->

### Agents (Claude Code only)

| Agent | What it does |
|---|---|
| [`kotlin-reviewer`](agents/kotlin-reviewer.md) | Read-only reviewer for Kotlin, Compose and Gradle changes. Returns one JSON finding per line. |
| [`swift-reviewer`](agents/swift-reviewer.md) | Read-only reviewer for Swift and SwiftUI changes, including code that calls into the shared KMP framework. |

Every other agent gets the same review through the `kmp-code-review` skill.

## How the skills behave

- **They follow your project, not ours.** Every skill that writes code starts by reading your build
  files, module layout and existing code. If you use Hilt, SQLDelight, Decompose or your own MVI base
  class, the skill writes code in that style. Defaults (Compose Multiplatform, Koin, Ktor +
  kotlinx.serialization, Room KMP, Kermit/Napier, `kotlin.test` + fakes + Turbine) are used only for a
  new project or a module with no precedent.
- **Both platforms, every time.** A change is not done until it compiles and its tests pass for
  Android *and* iOS. Skills report each check as `PASS`, `FAIL` or `NOT RUN` (with the reason, e.g.
  "iOS link needs macOS") and never claim a check they did not run.
- **Measure before fixing.** Debug and performance skills collect evidence (stack traces, traces,
  profiler numbers) before proposing a change, and re-measure after.
- **They ask before anything risky.** Deleting files, rewriting git history, touching signing or
  keystores, pushing, or opening a PR always waits for your go-ahead.

## Works well with

These packs cover native-platform topics in depth. This repo links to them rather than copying them.

| Pack | Covers | License |
|---|---|---|
| [android/skills](https://github.com/android/skills) | Official Android: ANR, profiler, Compose performance, Navigation 3, R8, XML→Compose, security | Apache-2.0 |
| [Kotlin/kotlin-agent-skills](https://github.com/Kotlin/kotlin-agent-skills) | Official Kotlin: AGP 9 migration for KMP, CocoaPods→SPM, Kotlin/Native build performance | Apache-2.0 |
| [chrisbanes/skills](https://github.com/chrisbanes/skills) | Kotlin API design, coroutines/Flow, Compose state, Compose UI testing, Gradle | Apache-2.0 |
| [Meet-Miyani/compose-skill](https://github.com/Meet-Miyani/compose-skill) | Compose Multiplatform architecture, UI, data, platform | MIT |
| [skydoves/compose-performance-skills](https://github.com/skydoves/compose-performance-skills) | Compose stability, Baseline Profiles, Macrobenchmark | Apache-2.0 |
| [AvdLee/SwiftUI-Agent-Skill](https://github.com/AvdLee/SwiftUI-Agent-Skill) | SwiftUI state, composition, performance | MIT |
| [twostraws/SwiftUI-Agent-Skill](https://github.com/twostraws/SwiftUI-Agent-Skill) | SwiftUI review and modern APIs | MIT |
| [AvdLee/Swift-Concurrency-Agent-Skill](https://github.com/AvdLee/Swift-Concurrency-Agent-Skill) | Swift concurrency | MIT |
| [CharlesWiltgen/Axiom](https://github.com/CharlesWiltgen/Axiom) | iOS crash symbolication, memory and performance audits | MIT |

[docs/using-with-other-skill-packs.md](docs/using-with-other-skill-packs.md) explains which Android
skills are safe to apply to shared KMP code and which only apply to the Android host app.

## Repository layout

```text
skills/<skill-name>/SKILL.md   one skill per folder (+ references/, scripts/, assets/)
agents/                        Claude Code subagents
evals/<skill>-trigger/         claude plugin eval cases: does a realistic prompt load the skill?
docs/                          authoring guide and guides for using other packs alongside
scripts/                       validate, sync manifests, scaffold evals, run tests
.claude-plugin/ .codex-plugin/ .cursor-plugin/ .agents/plugins/ plugin.json gemini-extension.json
                               install manifests for each agent family
```

## Contributing

New skills, fixes and better examples are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) and the
[skill authoring guide](docs/skill-authoring-guide.md) first. Before opening a PR:

```bash
python3 scripts/validate_skills.py --strict
python3 scripts/sync_manifests.py --check
python3 scripts/run_tests.py
```

## Security

Skills can run scripts on your machine through your agent. Read a skill before installing it, from
here or anywhere else. Report a vulnerability privately as described in [SECURITY.md](SECURITY.md).

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

This project is community-maintained and is not affiliated with or endorsed by JetBrains, Google,
Apple, Anthropic, OpenAI or any other company whose products it mentions. Product names are
trademarks of their respective owners.
