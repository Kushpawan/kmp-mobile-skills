# Lens — Gradle, iOS integration, release config and CI

Tier 2 rows for build scripts, version catalogs, manifests and project settings, Swift Package
Manager files, CI pipelines and the shell they run. A hit is a proposal the author can reject with a
reason; a project rule that says otherwise wins. Security-relevant build settings (cleartext
traffic, `debuggable`, backups, signing secrets) belong to the security review, not here.

**Columns.** *Lens* — stable name, becomes the key `build/<lensName>`. *What a hit looks like* — the
violation; *Applies when* states a condition. *Floor* — minimum severity. *Mech?* — `yes`: the build,
a lint or a script can catch it; `partial`: a grep finds candidates; `no`: needs reading.

## Contents

1. [Gradle and the version catalog](#1-gradle-and-the-version-catalog)
2. [Kotlin Multiplatform targets and the iOS framework](#2-kotlin-multiplatform-targets-and-the-ios-framework)
3. [Android release configuration](#3-android-release-configuration)
4. [Xcode and Swift Package Manager](#4-xcode-and-swift-package-manager)
5. [CI pipelines](#5-ci-pipelines)
6. [Shell scripts](#6-shell-scripts)

## 1. Gradle and the version catalog

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Hardcoded version | A version string in `build.gradle.kts` (`implementation("group:artifact:1.2.3")`, `version "1.2.3"` on a plugin) in a project that uses `gradle/libs.versions.toml` | Medium | yes — grep |
| Incomplete catalog entry | A new library without its `[versions]` entry and `version.ref`, or a version added to a module-local catalog when the project keeps one shared catalog | Medium | partial |
| Second library for one job | A new dependency that duplicates one already used for the same job — a second JSON library, HTTP client, DI framework, image loader or logger | Medium | partial |
| Dependency in the wrong source set | A JVM- or Android-only artifact added to `commonMain`, or a multiplatform one added only to `androidMain` while common code needs it. The first fails only when an iOS target compiles — often only on macOS | High | yes — compile every target |
| `implementation` leaking into public API | A type from an `implementation` dependency appears in a public signature of a library module — consumers fail to compile. Use `api` or hide the type | High | yes — consumer build |
| Compiler-plugin version skew | KSP, a Swift-bridging plugin or another compiler plugin bumped (or Kotlin bumped) without the matching version of the other | Medium | yes — build fails |
| Configuration-time side effect | A network call, `exec`, file write or credential lookup at configuration time in `settings.gradle.kts` / `build.gradle.kts` — breaks offline builds and the configuration cache. *Applies unless* it is the documented way the project authenticates to its repository | Medium | partial |
| Machine-specific path | An absolute path into a home directory, a local SDK location or a sibling checkout in a committed build file | Medium | yes — grep |
| Library blast radius | A change to a library module that other apps consume, validated only in the library's own build. *Applies when* consumers build a published artifact (or a composite build is off by default) — rebuild each consumer against the local copy (`includeBuild` with dependency substitution) before merging | High | partial |

## 2. Kotlin Multiplatform targets and the iOS framework

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Target removed | A target dropped from `kotlin { }` — e.g. `iosX64` — while a consumer still builds that slice (Intel-Mac simulators, an x86_64 CI host) | Medium | partial |
| KSP not wired for every target | A KSP processor added only to `commonMain` metadata or to some targets (for Room KMP: `kspAndroid`, `kspIosArm64`, `kspIosSimulatorArm64`, `kspIosX64` as the project's targets require) — generated code is missing on the others: a build error at best, a runtime failure at worst | High | partial |
| Framework export without `api` | A module passed to `export(...)` in the framework block that is not an `api` dependency, or a module Swift needs that is `api` but not exported — Swift cannot see its declarations | High | yes — Gradle fails on the first case |
| Two Kotlin frameworks in one app | A second Kotlin framework linked into the same iOS app instead of exporting both modules through one umbrella framework — each carries its own Kotlin runtime and shared types, which are not interchangeable in Swift | High | partial |
| System and bundled SQLite mixed | `-lsqlite3` added to a framework whose persistence uses a bundled SQLite driver, or missing from one that uses the system driver (Room's `NativeSQLiteDriver` needs it, including on test binaries). Mixing both lets the linker resolve `sqlite3_*` to the copy you did not intend — verify on device | High | partial |
| Framework binary option drift | `isStatic`, `baseName` or `binaryOption` changed for a framework that Xcode projects or Swift packages already link by name and type | High | partial |

## 3. Android release configuration

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Application identity changed | `applicationId` (or an `applicationIdSuffix` on the release variant) changed for a published app — installs become a different app; users lose updates and local data | Critical | yes — grep |
| Version codes not advanced | A release change where `versionCode` did not increase, or `versionCode` and `versionName` moved independently when the project ties them. *Applies to* release commits | Medium | partial |
| `targetSdk` bumped without behaviour review | A `targetSdk` raise without the platform behaviour changes it opts into — e.g. explicit `android:exported` (31), foreground service types (34), enforced edge-to-edge (35) | High | partial — Android Lint |
| `minSdk` raised silently | `minSdk` increased in a change that does not say so — drops every user below it from updates | Medium | yes — grep |
| Release-only crash from shrinking | Reflection-based code (Gson, reflective serializers, a `Class.forName`, JNI callbacks) added with R8 enabled and no keep rule — works in debug, crashes in release | High | partial — run the release build |
| Overly broad keep rule | `-keep class com.example.** { *; }` or `-dontobfuscate` / `-dontshrink` added to fix one crash — disables shrinking for everything under it | Medium | yes — grep |

## 4. Xcode and Swift Package Manager

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Stale package checksum | A `.binaryTarget(url:checksum:)` pointing at a new framework zip with the old checksum, or a new checksum for an unchanged URL — package resolution fails for every consumer | High | yes — `swift package compute-checksum` |
| Linker flags lost through SPM | A static framework that needs a system library (e.g. `sqlite3`) shipped as an SPM `binaryTarget` — binary targets cannot declare linker settings, so each consumer target must add `linkerSettings: [.linkedLibrary("sqlite3")]` | High | partial |
| Script sandboxing blocks the Kotlin build | A Run Script phase that builds the Kotlin framework (`embedAndSignAppleFrameworkForXcode`) with `ENABLE_USER_SCRIPT_SANDBOXING = YES` — the script cannot write its outputs | Medium | yes — grep the project file |
| Deployment target raised silently | `IPHONEOS_DEPLOYMENT_TARGET` or the package `platforms:` raised in a change that does not say so — drops users on older iOS versions | Medium | yes — grep |
| Bundle identifier changed | `PRODUCT_BUNDLE_IDENTIFIER` changed for a shipped configuration — it becomes a different app, and Keychain items tied to the old identifier are no longer reachable | Critical | yes — grep |

## 5. CI pipelines

GitHub Actions (`.github/workflows/*.yml`) and GitLab CI (`.gitlab-ci.yml`, included files). Review
the YAML and the scripts it calls.

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Untrusted code with secrets | A `pull_request_target` (or `workflow_run`) workflow that checks out and runs the pull request's code with secrets or a write token available | Critical | partial |
| Script injection | An attacker-controlled expression (`${{ github.event.pull_request.title }}`, a branch name, an issue body) interpolated directly into a `run:` script. Pass it through an environment variable and quote it | High | partial |
| Mutable action reference | A third-party action referenced by a branch or tag (`@main`, `@v3`) where the project pins full commit SHAs | Medium | yes — grep |
| Coupled jobs drift | Jobs that must agree — build, publish, tag, release — decide branch, channel or trigger with separate, non-identical conditions, so changing one does not change the others | High | no |
| Condition precedence | GitLab: a broad earlier `rules:` entry shadowing a later specific one, or a job whose rules match where its required `needs:` job's rules do not. GitHub: an `if:` that mixes `${{ }}` with literal text (`if: ${{ a }} && ${{ b }}`) — it evaluates to a non-empty string and is always true | High | no |
| Variable semantics | A rule or script testing a variable whose effective value differs from the one assumed — unset vs empty, defined only in another job, overridden at trigger time, or a secret unavailable to fork pull requests | High | no |
| Shallow-clone assumption | `git describe`, `git merge-base`, changelog or version-from-tags logic on a shallow checkout (`actions/checkout` fetches one commit by default) or on a persistent runner with stale refs | Medium | no |
| Non-idempotent pipeline step | A publish, tag or release step that is not safe to retry — a re-run republishes, re-tags, or fails because an earlier step half-completed | Medium | no |
| Release not bound to its commit | A tag, version or release created from a different commit or version than the artifact published — HEAD moved, version read before the bump — or a downgrade guard that checks ancestry instead of version order | High | no |

## 6. Shell scripts

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Strict-mode surprise | `set -e` / `pipefail` aborting on an expected non-zero exit (`grep` with no match, `diff`), or `\|\| true` masking a real failure | High | partial — ShellCheck |
| Unquoted expansion | `$VAR` or `$(cmd)` unquoted where it can hold spaces, globs or be empty — paths with spaces are common on developer machines | High | yes — ShellCheck |
| Unchecked empty value | A command substitution or variable used without checking it is non-empty (`rm -rf "$DIR/"` with `DIR` empty) | Critical | partial — ShellCheck |
| Untrusted input in a command | An external value (branch name, PR title, file name from a download) interpolated into `eval`, `sh -c` or an unquoted command | High | partial |
